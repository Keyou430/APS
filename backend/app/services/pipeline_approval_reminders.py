from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    DashboardDecision,
    NotificationOutbox,
    OrganizationMembership,
    PipelineTask,
    Role,
)
from app.services.pipeline_approval import (
    enqueue_feishu_decision_notifications,
    resolved_approver_user_ids,
)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def run_pipeline_approval_reminder_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    checked_at = now or datetime.now(UTC)
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(DashboardDecision, PipelineTask)
                .join(PipelineTask, PipelineTask.id == DashboardDecision.task_id)
                .where(DashboardDecision.status == "pending")
                .order_by(DashboardDecision.created_at.asc(), DashboardDecision.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        enqueued = 0
        for decision, task in rows:
            created_at = _as_utc(decision.created_at)
            reminder_threshold = task.approval_reminder_after_minutes
            if (
                reminder_threshold is not None
                and decision.reminder_sent_at is None
                and checked_at >= created_at + timedelta(minutes=reminder_threshold)
            ):
                recipient_user_ids = sorted(
                    set(await resolved_approver_user_ids(db, task=task))
                )
                db.add(
                    NotificationOutbox(
                        organization_id=decision.organization_id,
                        event_key=f"decision-reminder:{decision.id}",
                        event_type="pipeline.decision.reminder",
                        payload={
                            "decision_id": decision.id,
                            "task_id": task.id,
                            "status": "pending",
                            "recipient_user_ids": recipient_user_ids,
                        },
                        status="pending",
                    )
                )
                await enqueue_feishu_decision_notifications(
                    db,
                    organization_id=decision.organization_id,
                    recipient_user_ids=recipient_user_ids,
                    event_key=f"decision-reminder:{decision.id}",
                    event_type="pipeline.decision.reminder",
                    payload={
                        "decision_id": decision.id,
                        "task_id": task.id,
                        "status": "pending",
                    },
                )
                decision.reminder_sent_at = checked_at
                enqueued += 1

            escalation_threshold = task.approval_escalation_after_minutes
            if (
                escalation_threshold is not None
                and decision.escalation_sent_at is None
                and checked_at >= created_at + timedelta(minutes=escalation_threshold)
            ):
                role_name = task.approval_escalation_role_name or "admin"
                escalation_user_ids = sorted(
                    set(
                        (
                            await db.scalars(
                                select(OrganizationMembership.user_id)
                                .join(Role, Role.id == OrganizationMembership.role_id)
                                .where(
                                    OrganizationMembership.organization_id
                                    == task.organization_id,
                                    OrganizationMembership.is_active.is_(True),
                                    or_(
                                        OrganizationMembership.expires_at.is_(None),
                                        OrganizationMembership.expires_at > checked_at,
                                    ),
                                    Role.name == role_name,
                                )
                            )
                        ).all()
                    )
                )
                db.add(
                    NotificationOutbox(
                        organization_id=decision.organization_id,
                        event_key=f"decision-escalation:{decision.id}",
                        event_type="pipeline.decision.escalation",
                        payload={
                            "decision_id": decision.id,
                            "task_id": task.id,
                            "status": "pending",
                            "recipient_user_ids": escalation_user_ids,
                            "role_name": role_name,
                        },
                        status="pending",
                    )
                )
                await enqueue_feishu_decision_notifications(
                    db,
                    organization_id=decision.organization_id,
                    recipient_user_ids=escalation_user_ids,
                    event_key=f"decision-escalation:{decision.id}",
                    event_type="pipeline.decision.escalation",
                    payload={
                        "decision_id": decision.id,
                        "task_id": task.id,
                        "status": "pending",
                        "role_name": role_name,
                    },
                )
                decision.escalation_sent_at = checked_at
                enqueued += 1
        await db.commit()
        return enqueued
