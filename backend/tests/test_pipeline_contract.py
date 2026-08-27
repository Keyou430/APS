from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Organization, OrganizationMembership, PipelineTask, Role, User
from app.services.pipeline_executor import (
    PipelineExecutionResult,
    run_pipeline_cycle,
)
from app.services.web_evidence import WebEvidence


def _evidence(url: str, correlation_id: str) -> WebEvidence:
    return WebEvidence(
        provider="exa",
        url=url,
        title="Current source",
        published_at=datetime(2026, 8, 17, tzinfo=UTC),
        searched_at=datetime(2026, 8, 17, 2, 0, tzinfo=UTC),
        correlation_id=correlation_id,
    )


@pytest.mark.asyncio
async def test_pipeline_draft_requires_confirmation_before_creation(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/pipeline/tasks/draft",
        headers=admin_headers,
        json={
            "prompt": "每天17:30搜索行业趋势，整理成Markdown日报，生成后进入待审批状态",
        },
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["title"]
    assert draft["task_type"] == "web_research"
    assert draft["timezone"] == "Asia/Shanghai"
    assert draft["output_format"] == "markdown"
    assert "id" not in draft

    listed = await client.get("/api/pipeline/tasks", headers=admin_headers)
    assert listed.status_code == 200
    assert all(item.get("prompt") != draft["prompt"] for item in listed.json()["items"])


@pytest.mark.asyncio
async def test_wednesday_ai_news_prompt_is_parsed_as_a_scheduled_web_task(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/pipeline/tasks/draft",
        headers=admin_headers,
        json={"prompt": "每周三给我一份 AI 最新动态的周报"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "AI 最新动态周报"
    assert response.json()["task_type"] == "web_research"
    assert response.json()["schedule"] == "0 9 * * 3"
    assert response.json()["input_sources"] == ["web"]


@pytest.mark.asyncio
async def test_pipeline_task_run_decision_output_and_download_are_owner_scoped(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    draft = await client.post(
        "/api/pipeline/tasks/draft",
        headers=admin_headers,
        json={"prompt": "每天17:30搜索行业趋势，整理成Markdown日报"},
    )
    assert draft.status_code == 200
    task = await client.post(
        "/api/pipeline/tasks",
        headers={**admin_headers, "Idempotency-Key": "pipeline-create-1"},
        json={**draft.json(), "confirmed": True},
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]

    first = await client.post(
        f"/api/pipeline/tasks/{task_id}/run",
        headers={**admin_headers, "Idempotency-Key": "pipeline-run-1"},
    )
    assert first.status_code == 202
    second = await client.post(
        f"/api/pipeline/tasks/{task_id}/run",
        headers={**admin_headers, "Idempotency-Key": "pipeline-run-1"},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    run_id = first.json()["id"]
    run = await client.get(f"/api/pipeline/runs/{run_id}", headers=admin_headers)
    assert run.status_code == 200
    assert run.json()["status"] in {"queued", "running", "completed", "failed"}

    decisions = await client.get("/api/dashboard/decisions", headers=admin_headers)
    assert decisions.status_code == 200
    assert "items" in decisions.json()

    # A completed fixture is created through the test-only executor endpoint.
    output = await client.get("/api/pipeline/outputs/1", headers=admin_headers)
    assert output.status_code in {200, 404}


@pytest.mark.asyncio
async def test_pipeline_invalid_schedule_is_rejected(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/pipeline/tasks",
        headers=admin_headers,
        json={
            "confirmed": True,
            "title": "Invalid schedule",
            "prompt": "search trends",
            "task_type": "web_research",
            "schedule": "not-a-cron",
            "timezone": "Mars/Olympus",
            "input_sources": ["web"],
            "output_format": "markdown",
            "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_run_output_and_download_are_current_and_owner_scoped(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    task_response = await client.post(
        "/api/pipeline/tasks",
        headers=admin_headers,
        json={
            "confirmed": True,
            "title": "Output scope probe",
            "prompt": "search current trends",
            "task_type": "web_research",
            "schedule": None,
            "timezone": "Asia/Shanghai",
            "input_sources": ["web"],
            "output_format": "markdown",
        },
    )
    assert task_response.status_code == 201
    task_id = task_response.json()["id"]
    first_run = await client.post(
        f"/api/pipeline/tasks/{task_id}/run",
        headers={**admin_headers, "Idempotency-Key": "output-run-1"},
    )
    assert first_run.status_code == 202

    class FakeExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            correlation_id = f"output-evidence-{task.id}"
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Current output\n\n[source](https://example.com/current)",
                sources=[
                    {
                        "url": "https://example.com/current",
                        "title": "Current source",
                        "published_at": "2026-08-17T00:00:00Z",
                        "searched_at": "2026-08-17T02:00:00Z",
                    }
                ],
                summary="Current output",
                correlation_id=correlation_id,
                evidence=[_evidence("https://example.com/current", correlation_id)],
            )

    assert (
        await run_pipeline_cycle(
            SessionLocal, executor=FakeExecutor(), worker_id="output-worker", limit=1
        )
        == 1
    )
    completed = await client.get(
        f"/api/pipeline/runs/{first_run.json()['id']}", headers=admin_headers
    )
    output_id = completed.json()["output_id"]
    assert output_id is not None
    output = await client.get(f"/api/pipeline/outputs/{output_id}", headers=admin_headers)
    assert output.status_code == 200
    download = await client.get(
        f"/api/pipeline/outputs/{output_id}/download", headers=admin_headers
    )
    assert download.status_code == 200
    assert download.headers["content-disposition"].endswith('"Output scope probe.md"')
    assert download.headers["cache-control"] == "private, no-store"
    assert download.text.startswith("# Current output")

    second_run = await client.post(
        f"/api/pipeline/tasks/{task_id}/run",
        headers={**admin_headers, "Idempotency-Key": "output-run-2"},
    )
    assert second_run.status_code == 202
    assert second_run.json()["output_id"] is None

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        admin_role = await db.scalar(select(Role).where(Role.name == "admin"))
        assert admin is not None and admin_role is not None
        foreign = Organization(name="Pipeline foreign org", slug="pipeline-foreign-org")
        db.add(foreign)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=foreign.id,
                user_id=admin.id,
                role_id=admin_role.id,
            )
        )
        foreign_task = PipelineTask(
            organization_id=foreign.id,
            user_id=admin.id,
            title="Foreign task",
            prompt="foreign private prompt",
            task_type="general",
            timezone="Asia/Shanghai",
            input_sources=[],
            output_format="markdown",
            status="ready",
        )
        db.add(foreign_task)
        await db.commit()
        foreign_task_id = foreign_task.id
        foreign_org_id = foreign.id

    foreign_response = await client.get(
        f"/api/pipeline/tasks/{foreign_task_id}", headers=admin_headers
    )
    assert foreign_response.status_code == 404
    switched = await client.post(
        "/api/auth/switch-organization",
        headers=admin_headers,
        json={"organization_id": foreign_org_id},
    )
    assert switched.status_code == 200
    foreign_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
    assert (
        await client.get(f"/api/pipeline/tasks/{task_id}", headers=foreign_headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/pipeline/outputs/{output_id}", headers=foreign_headers)
    ).status_code == 404
    assert (
        await client.get(
            f"/api/pipeline/outputs/{output_id}/download", headers=foreign_headers
        )
    ).status_code == 404
    async with SessionLocal() as db:
        foreign = await db.get(Organization, foreign_org_id)
        assert foreign is not None
        await db.delete(foreign)
        await db.commit()
