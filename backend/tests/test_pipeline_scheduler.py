from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import PipelineRun, PipelineTask
from app.services.pipeline_executor import (
    PipelineExecutionResult,
    run_pipeline_cycle,
)
from app.services.web_evidence import WebEvidence
from app.services.pipeline_scheduler import (
    CronExpressionError,
    next_cron_run,
    schedule_due_pipeline_tasks,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def test_next_cron_run_resolves_weekly_slot_in_task_timezone() -> None:
    # 2026-08-20 is a Thursday; the next Wednesday 09:00 Asia/Shanghai slot
    # is 2026-08-26 09:00 CST == 01:00 UTC.
    after = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    assert next_cron_run("0 9 * * 3", "Asia/Shanghai", after=after) == datetime(
        2026, 8, 26, 1, 0, tzinfo=UTC
    )


def test_next_cron_run_supports_steps_and_returns_strictly_after() -> None:
    after = datetime(2026, 8, 20, 12, 3, tzinfo=UTC)
    assert next_cron_run("*/5 * * * *", "UTC", after=after) == datetime(
        2026, 8, 20, 12, 5, tzinfo=UTC
    )


def test_next_cron_run_dom_dow_union_semantics() -> None:
    # Both day fields restricted: the 13th OR any Friday may match.
    after = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)  # Thursday
    assert next_cron_run("0 0 13 * 5", "UTC", after=after) == datetime(
        2026, 8, 21, 0, 0, tzinfo=UTC  # Friday
    )


@pytest.mark.parametrize(
    "expression",
    ["* * * *", "61 * * * *", "* 24 * * *", "0 0 32 * *", "a b c d e", "0 0 30 2 *"],
)
def test_invalid_or_never_matching_cron_is_rejected(expression: str) -> None:
    with pytest.raises(CronExpressionError):
        next_cron_run(expression, "UTC", after=datetime(2026, 8, 20, tzinfo=UTC))


@pytest.mark.asyncio
async def test_scheduled_task_creation_arms_next_run_at(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/pipeline/tasks",
        headers=admin_headers,
        json={
            "confirmed": True,
            "title": "Weekly AI report",
            "prompt": "search AI trends weekly",
            "task_type": "web_research",
            "schedule": "0 9 * * 3",
            "timezone": "Asia/Shanghai",
            "input_sources": ["web"],
            "output_format": "markdown",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["next_run_at"] is not None
    armed_raw = body["next_run_at"].replace("Z", "+00:00")
    armed = datetime.fromisoformat(armed_raw)
    if armed.tzinfo is None:
        armed = armed.replace(tzinfo=UTC)
    assert armed > datetime.now(UTC)
    # Wednesday 09:00 Asia/Shanghai == 01:00 UTC (Wednesday in UTC).
    assert armed.utcoffset() == timedelta(0)
    assert armed.weekday() == 2 and armed.hour == 1


@pytest.mark.asyncio
async def test_invalid_cron_is_rejected_at_task_creation(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/pipeline/tasks",
        headers=admin_headers,
        json={
            "confirmed": True,
            "title": "Broken cron",
            "prompt": "search trends",
            "task_type": "web_research",
            "schedule": "0 0 30 2 *",
            "timezone": "Asia/Shanghai",
            "input_sources": ["web"],
            "output_format": "markdown",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_due_task_enqueues_exactly_one_scheduled_run_and_advances(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/pipeline/tasks",
        headers=admin_headers,
        json={
            "confirmed": True,
            "title": "Due task",
            "prompt": "search trends",
            "task_type": "general",
            "schedule": "0 9 * * 3",
            "timezone": "Asia/Shanghai",
            "input_sources": [],
            "output_format": "markdown",
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        task.hermes_cron_job_id = None
        # Simulate a slot that became due an hour ago.
        task.next_run_at = datetime.now(UTC) - timedelta(hours=1)
        await db.commit()

        first = await schedule_due_pipeline_tasks(db)
        assert first == 1
        runs = list(
            (
                await db.scalars(
                    select(PipelineRun).where(PipelineRun.task_id == task_id)
                )
            ).all()
        )
        assert len(runs) == 1
        assert runs[0].trigger_kind == "scheduled"
        assert runs[0].status == "queued"
        assert runs[0].scheduled_for is not None
        await db.commit()

        # Second scheduling pass must not duplicate the slot.
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        assert _utc(task.next_run_at) > datetime.now(UTC)
        assert await schedule_due_pipeline_tasks(db) == 0


@pytest.mark.asyncio
async def test_worker_cycle_executes_enqueued_scheduled_run(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/pipeline/tasks",
        headers=admin_headers,
        json={
            "confirmed": True,
            "title": "Worker scheduled task",
            "prompt": "search trends",
            "task_type": "web_research",
            "schedule": "0 9 * * 3",
            "timezone": "Asia/Shanghai",
            "input_sources": ["web"],
            "output_format": "markdown",
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        task.hermes_cron_job_id = None
        task.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

    class FakeExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            correlation_id = f"scheduler-evidence-{task.id}"
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Scheduled output",
                sources=[
                    {
                        "url": "https://example.com/scheduled",
                        "title": "Scheduled source",
                        "published_at": "2026-08-20T00:00:00Z",
                        "searched_at": "2026-08-20T01:00:00Z",
                    }
                ],
                summary="Scheduled output",
                correlation_id=correlation_id,
                evidence=[
                    WebEvidence(
                        provider="exa",
                        url="https://example.com/scheduled",
                        title="Scheduled source",
                        published_at=datetime(2026, 8, 20, tzinfo=UTC),
                        searched_at=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
                        correlation_id=correlation_id,
                    )
                ],
            )

    claimed = await run_pipeline_cycle(
        SessionLocal, executor=FakeExecutor(), worker_id="scheduler-test", limit=5
    )
    assert claimed == 1

    async with SessionLocal() as db:
        run = await db.scalar(
            select(PipelineRun).where(
                PipelineRun.task_id == task_id,
                PipelineRun.trigger_kind == "scheduled",
            )
        )
        assert run is not None
        assert run.status == "completed"
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        assert task.next_run_at is not None
        assert _utc(task.next_run_at) > datetime.now(UTC)
