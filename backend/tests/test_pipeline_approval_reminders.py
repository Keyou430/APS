import importlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    DashboardDecision,
    NotificationOutbox,
    PipelineOutput,
    PipelineRun,
    PipelineTask,
    User,
)

pytestmark = pytest.mark.asyncio


async def _pending_decision(
    *,
    created_at: datetime,
    reminder_after_minutes: int | None = 60,
    escalation_after_minutes: int | None = None,
) -> int:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        task = PipelineTask(
            organization_id=user.default_organization_id,
            user_id=user.id,
            title="Reminder probe",
            prompt="Summarize current information",
            task_type="general",
            schedule=None,
            timezone="Asia/Shanghai",
            input_sources=[],
            output_format="markdown",
            status="ready",
            revision=1,
            approval_required=True,
            approval_assignee_type="creator",
            approval_reminder_after_minutes=reminder_after_minutes,
            approval_escalation_after_minutes=escalation_after_minutes,
        )
        db.add(task)
        await db.flush()
        run = PipelineRun(
            organization_id=task.organization_id,
            user_id=user.id,
            task_id=task.id,
            trigger_kind="manual",
            status="completed",
        )
        db.add(run)
        await db.flush()
        output = PipelineOutput(
            organization_id=task.organization_id,
            user_id=user.id,
            task_id=task.id,
            run_id=run.id,
            version=1,
            title=task.title,
            markdown="# Result",
            object_key=f"test/reminder-{run.id}.md",
            content_sha256="0" * 64,
            sources=[],
        )
        db.add(output)
        await db.flush()
        decision = DashboardDecision(
            organization_id=task.organization_id,
            user_id=user.id,
            task_id=task.id,
            run_id=run.id,
            output_id=output.id,
            status="pending",
            revision=1,
            title=task.title,
            summary="Review me",
            created_at=created_at,
        )
        db.add(decision)
        await db.commit()
        return decision.id


async def test_pending_decision_reminder_is_enqueued_once_after_threshold() -> None:
    now = datetime.now(UTC)
    decision_id = await _pending_decision(created_at=now - timedelta(minutes=61))
    try:
        module = importlib.import_module("app.services.pipeline_approval_reminders")
    except ModuleNotFoundError:
        pytest.fail("pipeline approval reminder service is missing")
    cycle = getattr(module, "run_pipeline_approval_reminder_cycle", None)
    assert callable(cycle)

    await cycle(SessionLocal, now=now, limit=10)
    await cycle(SessionLocal, now=now + timedelta(minutes=1), limit=10)

    async with SessionLocal() as db:
        decision = await db.get(DashboardDecision, decision_id)
        count = await db.scalar(
            select(func.count(NotificationOutbox.id)).where(
                NotificationOutbox.event_key == f"decision-reminder:{decision_id}"
            )
        )
    assert decision is not None
    assert decision.status == "pending"
    assert decision.reminder_sent_at is not None
    assert count == 1


async def test_pending_decision_escalation_is_enqueued_once_without_terminal_status() -> None:
    now = datetime.now(UTC)
    decision_id = await _pending_decision(
        created_at=now - timedelta(minutes=121),
        reminder_after_minutes=None,
        escalation_after_minutes=120,
    )
    module = importlib.import_module("app.services.pipeline_approval_reminders")
    cycle = module.run_pipeline_approval_reminder_cycle

    await cycle(SessionLocal, now=now, limit=10)
    await cycle(SessionLocal, now=now + timedelta(minutes=1), limit=10)

    async with SessionLocal() as db:
        decision = await db.get(DashboardDecision, decision_id)
        notification = await db.scalar(
            select(NotificationOutbox).where(
                NotificationOutbox.event_key == f"decision-escalation:{decision_id}"
            )
        )
        count = await db.scalar(
            select(func.count(NotificationOutbox.id)).where(
                NotificationOutbox.event_key == f"decision-escalation:{decision_id}"
            )
        )
    assert decision is not None
    assert decision.status == "pending"
    assert decision.escalation_sent_at is not None
    assert notification is not None
    assert notification.payload["recipient_user_ids"]
    assert count == 1
