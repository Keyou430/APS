from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import PipelineTask
from app.routers import pipeline
from app.schemas.pipeline import PipelineTaskCreate
from app.services import hermes_cron_bridge
from app.services.pipeline_scheduler import schedule_due_pipeline_tasks


def scheduled_task_payload() -> PipelineTaskCreate:
    return PipelineTaskCreate(
        confirmed=True,
        title="飞书待办每日摘要",
        prompt="每天09:00读取我的飞书待办并生成摘要",
        task_type="general",
        schedule="0 9 * * *",
        timezone="Asia/Shanghai",
        input_sources=[],
        output_format="markdown",
    )


def failing_commit_session(exc: Exception) -> MagicMock:
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    db.flush = AsyncMock(side_effect=lambda: setattr(db.add.call_args.args[0], "id", 101))
    db.commit = AsyncMock(side_effect=exc)
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_startup_reconciliation_registers_an_existing_unbound_task(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/pipeline/tasks",
        headers={**admin_headers, "Idempotency-Key": "legacy-unbound-task"},
        json=scheduled_task_payload().model_dump(mode="json"),
    )
    task_id = created.json()["id"]
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        task.hermes_cron_job_id = None
        await db.commit()

    register = AsyncMock(return_value="reconciled-job")
    reconciled = await hermes_cron_bridge.reconcile_unbound_pipeline_tasks(
        SessionLocal,
        registrar=register,
    )

    assert reconciled == 1
    register.assert_awaited_once()
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        assert task.hermes_cron_job_id == "reconciled-job"


@pytest.mark.asyncio
async def test_commit_failure_removes_new_hermes_cron_job() -> None:
    db = failing_commit_session(RuntimeError("database unavailable"))
    remove = AsyncMock()

    with (
        patch.object(pipeline, "register_hermes_cron", new=AsyncMock(return_value="orphan-job")),
        patch.object(pipeline, "remove_hermes_cron", new=remove, create=True),
        pytest.raises(RuntimeError, match="database unavailable"),
    ):
        await pipeline.create_task(
            scheduled_task_payload(),
            db,
            SimpleNamespace(id=7),
            SimpleNamespace(organization_id=3, user_id=7),
            "commit-failure",
        )

    remove.assert_awaited_once_with("orphan-job", task_id=101)


@pytest.mark.asyncio
async def test_idempotency_conflict_removes_new_job_before_returning_existing_task() -> None:
    conflict = IntegrityError("insert", {}, Exception("unique constraint"))
    db = failing_commit_session(conflict)
    existing = SimpleNamespace(id=88)
    db.scalar = AsyncMock(side_effect=[None, existing])
    remove = AsyncMock()
    latest_output = AsyncMock(return_value=None)

    with (
        patch.object(pipeline, "register_hermes_cron", new=AsyncMock(return_value="losing-job")),
        patch.object(pipeline, "remove_hermes_cron", new=remove, create=True),
        patch.object(pipeline, "repository", return_value=SimpleNamespace(latest_output=latest_output)),
        patch.object(pipeline, "task_response", return_value="existing-response"),
    ):
        response = await pipeline.create_task(
            scheduled_task_payload(),
            db,
            SimpleNamespace(id=7),
            SimpleNamespace(organization_id=3, user_id=7),
            "duplicate-key",
        )

    assert response == "existing-response"
    remove.assert_awaited_once_with("losing-job", task_id=101)
    latest_output.assert_awaited_once_with(88)


def test_scheduled_tasks_are_limited_to_the_platform_timezone() -> None:
    payload = scheduled_task_payload().model_dump()
    payload["timezone"] = "UTC"

    with pytest.raises(ValueError, match="Asia/Shanghai"):
        PipelineTaskCreate.model_validate(payload)


@pytest.mark.asyncio
async def test_remove_hermes_cron_invokes_native_remove_command() -> None:
    executable = hermes_cron_bridge._hermes_executable()
    proc = SimpleNamespace(
        communicate=AsyncMock(return_value=(b"Removed job\n", b"")),
        returncode=0,
    )
    with patch.object(
        hermes_cron_bridge.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ) as spawn:
        await hermes_cron_bridge.remove_hermes_cron("job-42")

    spawn.assert_awaited_once_with(
        executable,
        "cron",
        "remove",
        "job-42",
        env={
            **{
                key: value
                for key, value in hermes_cron_bridge.os.environ.items()
                if key != "RAG_QUERY_AUDIT_HMAC_KEY"
            },
            "HERMES_HOME": str(Path(executable).resolve().parent),
        },
        stdout=hermes_cron_bridge.asyncio.subprocess.PIPE,
        stderr=hermes_cron_bridge.asyncio.subprocess.PIPE,
    )


def test_hermes_cli_environment_excludes_backend_only_audit_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RAG_QUERY_AUDIT_HMAC_KEY", "backend-only-secret")

    environment = hermes_cron_bridge._hermes_cli_environment(str(tmp_path / "hermes.exe"))

    assert "RAG_QUERY_AUDIT_HMAC_KEY" not in environment


@pytest.mark.asyncio
async def test_remove_hermes_cron_removes_the_task_script_after_job_removal(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "hermes.exe"
    executable.touch()
    script_path = tmp_path / "scripts" / "platform_pipeline_task_42.py"
    script_path.parent.mkdir()
    script_path.write_text("internal key", encoding="utf-8")
    proc = SimpleNamespace(
        communicate=AsyncMock(return_value=(b"Removed job\n", b"")),
        returncode=0,
    )
    with (
        patch.object(hermes_cron_bridge, "_hermes_executable", return_value=str(executable)),
        patch.object(
            hermes_cron_bridge.asyncio,
            "create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ),
    ):
        await hermes_cron_bridge.remove_hermes_cron("job-42", task_id=42)

    assert not script_path.exists()


@pytest.mark.asyncio
async def test_register_hermes_cron_uses_a_deterministic_no_agent_script(
    tmp_path,
) -> None:
    executable = tmp_path / "hermes.exe"
    executable.touch()
    proc = SimpleNamespace(
        communicate=AsyncMock(return_value=(b"Created job: deterministic-job\n", b"")),
        returncode=0,
    )
    with (
        patch.object(hermes_cron_bridge, "_hermes_executable", return_value=str(executable)),
        patch.object(
            hermes_cron_bridge.asyncio,
            "create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ) as spawn,
    ):
        job_id = await hermes_cron_bridge.register_hermes_cron(
            task_id=42,
            schedule="0 9 * * *",
            title="飞书待办摘要",
            timezone="Asia/Shanghai",
        )

    assert job_id == "deterministic-job"
    script_path = tmp_path / "scripts" / "platform_pipeline_task_42.py"
    script = script_path.read_text(encoding="utf-8")
    assert "TASK_ID = 42" in script
    assert "/api/internal/pipeline/trigger" in script
    assert "replace(second=0, microsecond=0)" in script
    spawn.assert_awaited_once_with(
        str(executable),
        "cron",
        "create",
        "0 9 * * *",
        "--name",
        "飞书待办摘要",
        "--script",
        script_path.name,
        "--no-agent",
        env={
            **{
                key: value
                for key, value in hermes_cron_bridge.os.environ.items()
                if key != "RAG_QUERY_AUDIT_HMAC_KEY"
            },
            "HERMES_HOME": str(tmp_path),
        },
        stdout=hermes_cron_bridge.asyncio.subprocess.PIPE,
        stderr=hermes_cron_bridge.asyncio.subprocess.PIPE,
    )
@pytest.mark.asyncio
async def test_remove_hermes_cron_reports_command_failure() -> None:
    proc = SimpleNamespace(
        communicate=AsyncMock(return_value=(b"", "任务不存在".encode("utf-8"))),
        returncode=1,
    )
    with patch.object(
        hermes_cron_bridge.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        with pytest.raises(RuntimeError, match="Hermes cron remove failed: 任务不存在"):
            await hermes_cron_bridge.remove_hermes_cron("missing-job")


@pytest.mark.asyncio
async def test_remove_hermes_cron_reports_timeout_and_stops_process() -> None:
    async def raise_timeout(awaitable, *, timeout: float) -> None:
        del timeout
        awaitable.close()
        raise TimeoutError

    proc = SimpleNamespace(
        communicate=AsyncMock(),
        kill=MagicMock(),
        wait=AsyncMock(),
    )
    with (
        patch.object(
            hermes_cron_bridge.asyncio,
            "create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ),
        patch.object(
            hermes_cron_bridge.asyncio,
            "wait_for",
            new=raise_timeout,
        ),
        pytest.raises(RuntimeError, match="Hermes cron remove timed out"),
    ):
        await hermes_cron_bridge.remove_hermes_cron("slow-job")

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_confirmed_scheduled_task_registers_hermes_cron_and_persists_job_id(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    with patch(
        "app.routers.pipeline.register_hermes_cron",
        new=AsyncMock(return_value="hermes-job-42"),
    ) as register:
        response = await client.post(
            "/api/pipeline/tasks",
            headers={**admin_headers, "Idempotency-Key": "cron-create-1"},
            json={
                "confirmed": True,
                "title": "飞书待办每日摘要",
                "prompt": "每天09:00读取我的飞书待办并生成摘要",
                "task_type": "general",
                "schedule": "0 9 * * *",
                "timezone": "Asia/Shanghai",
                "input_sources": [],
                "output_format": "markdown",
            },
        )
    assert response.status_code == 201, response.text
    register.assert_awaited_once()
    assert response.json()["hermes_cron_job_id"] == "hermes-job-42"
    async with SessionLocal() as db:
        task = await db.scalar(select(PipelineTask).where(PipelineTask.id == response.json()["id"]))
        assert task is not None
        assert task.hermes_cron_job_id == "hermes-job-42"


@pytest.mark.asyncio
async def test_cron_registration_failure_does_not_create_platform_task(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    with patch(
        "app.routers.pipeline.register_hermes_cron",
        new=AsyncMock(side_effect=RuntimeError("Hermes unavailable")),
    ):
        response = await client.post(
            "/api/pipeline/tasks",
            headers={**admin_headers, "Idempotency-Key": "cron-create-fail"},
            json={
                "confirmed": True,
                "title": "失败任务",
                "prompt": "每天09:00读取飞书待办",
                "task_type": "general",
                "schedule": "0 9 * * *",
                "timezone": "Asia/Shanghai",
                "input_sources": [],
                "output_format": "markdown",
            },
        )
    assert response.status_code == 502
    listed = await client.get("/api/pipeline/tasks", headers=admin_headers)
    assert all(item["title"] != "失败任务" for item in listed.json()["items"])


@pytest.mark.asyncio
async def test_hermes_trigger_is_idempotent_for_one_scheduled_slot(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    with patch("app.routers.pipeline.register_hermes_cron", new=AsyncMock(return_value="job-trigger")):
        created = await client.post(
            "/api/pipeline/tasks",
            headers={**admin_headers, "Idempotency-Key": "cron-trigger-task"},
            json={
                "confirmed": True,
                "title": "触发测试",
                "prompt": "每天09:00读取飞书待办",
                "task_type": "general",
                "schedule": "0 9 * * *",
                "timezone": "Asia/Shanghai",
                "input_sources": [],
                "output_format": "markdown",
            },
        )
    task_id = created.json()["id"]
    payload = {"task_id": task_id, "scheduled_for": "2026-08-28T01:00:00Z"}
    first = await client.post("/api/internal/pipeline/trigger", json=payload, headers={"X-Hermes-Internal-Key": "development-only"})
    second = await client.post("/api/internal/pipeline/trigger", json=payload, headers={"X-Hermes-Internal-Key": "development-only"})
    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"]


@pytest.mark.asyncio
async def test_local_scheduler_does_not_enqueue_hermes_owned_task(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    with patch("app.routers.pipeline.register_hermes_cron", new=AsyncMock(return_value="job-owned")):
        await client.post(
            "/api/pipeline/tasks",
            headers={**admin_headers, "Idempotency-Key": "cron-owned-task"},
            json={
                "confirmed": True,
                "title": "Hermes owned",
                "prompt": "每天09:00读取飞书待办",
                "task_type": "general",
                "schedule": "0 9 * * *",
                "timezone": "Asia/Shanghai",
                "input_sources": [],
                "output_format": "markdown",
            },
        )
    async with SessionLocal() as db:
        assert await schedule_due_pipeline_tasks(db, now=datetime.now(UTC)) == 0
