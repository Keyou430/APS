from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DashboardDecision,
    DeliveryTarget,
    NotificationOutbox,
    OrganizationMembership,
    PipelineTask,
    Role,
    RoutingRule,
)
from app.services.delivery_outbox_worker import enqueue_channel_delivery


def _active_membership_filter(now: datetime):
    return (
        OrganizationMembership.is_active.is_(True),
        (OrganizationMembership.expires_at.is_(None))
        | (OrganizationMembership.expires_at > now),
    )


async def validate_task_approval_policy(
    db: AsyncSession,
    *,
    organization_id: int,
    owner_user_id: int,
    approval_required: bool,
    assignee_type: str,
    assignee_id: int | None,
    role_name: str | None,
    escalation_role_name: str | None,
) -> None:
    if not approval_required:
        return
    now = datetime.now(UTC)
    if assignee_type == "creator":
        pass
    elif assignee_type == "member":
        member = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == assignee_id,
                *_active_membership_filter(now),
            )
        )
        if member is None:
            raise HTTPException(status_code=422, detail="approval assignee is not an active organization member")
    elif assignee_type == "role":
        role = await db.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            raise HTTPException(status_code=422, detail="approval role does not exist")
        member_count = await db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role_id == role.id,
                *_active_membership_filter(now),
            ).limit(1)
        )
        if member_count is None:
            raise HTTPException(status_code=422, detail="approval role has no active organization members")
    else:
        raise HTTPException(status_code=422, detail="invalid approval assignee type")

    if escalation_role_name:
        escalation_role = await db.scalar(
            select(Role).where(Role.name == escalation_role_name)
        )
        if escalation_role is None:
            raise HTTPException(status_code=422, detail="escalation role does not exist")


async def is_authorized_approver(
    db: AsyncSession, *, task: PipelineTask, user_id: int
) -> bool:
    if not task.approval_required:
        return False
    now = datetime.now(UTC)
    if task.approval_assignee_type == "member":
        return (
            await db.scalar(
                select(OrganizationMembership.id).where(
                    OrganizationMembership.organization_id == task.organization_id,
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.user_id == task.approval_assignee_id,
                    *_active_membership_filter(now),
                ).limit(1)
            )
        ) is not None
    if task.approval_assignee_type == "role":
        return (
            await db.scalar(
                select(OrganizationMembership.id)
                .join(Role, Role.id == OrganizationMembership.role_id)
                .where(
                    OrganizationMembership.organization_id == task.organization_id,
                    OrganizationMembership.user_id == user_id,
                    Role.name == task.approval_role_name,
                    *_active_membership_filter(now),
                )
                .limit(1)
            )
        ) is not None
    return task.approval_assignee_type == "creator" and user_id == task.user_id


async def require_authorized_approver(
    db: AsyncSession, *, task: PipelineTask, user_id: int
) -> None:
    if not await is_authorized_approver(db, task=task, user_id=user_id):
        raise HTTPException(status_code=403, detail="当前账号不是该任务的指定审批人")


async def resolved_approver_user_ids(
    db: AsyncSession, *, task: PipelineTask
) -> list[int]:
    if task.approval_assignee_type == "creator":
        return [task.user_id]
    now = datetime.now(UTC)
    statement = select(OrganizationMembership.user_id).where(
        OrganizationMembership.organization_id == task.organization_id,
        *_active_membership_filter(now),
    )
    if task.approval_assignee_type == "member":
        statement = statement.where(
            OrganizationMembership.user_id == task.approval_assignee_id
        )
    else:
        statement = statement.join(Role, Role.id == OrganizationMembership.role_id).where(
            Role.name == task.approval_role_name
        )
    return list((await db.scalars(statement)).all())


async def enqueue_pending_decision_notifications(
    db: AsyncSession, *, task: PipelineTask, decision: DashboardDecision
) -> None:
    recipient_user_ids = sorted(set(await resolved_approver_user_ids(db, task=task)))
    if len(recipient_user_ids) == 1:
        decision.approver_user_id = recipient_user_ids[0]
    db.add(
        NotificationOutbox(
            organization_id=task.organization_id,
            event_key=f"decision-pending:{decision.id}",
            event_type="pipeline.decision.pending",
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
        organization_id=task.organization_id,
        recipient_user_ids=recipient_user_ids,
        event_key=f"decision-pending:{decision.id}",
        event_type="pipeline.decision.pending",
        payload={"decision_id": decision.id, "task_id": task.id, "status": "pending"},
    )


async def enqueue_feishu_decision_notifications(
    db: AsyncSession,
    *,
    organization_id: int,
    recipient_user_ids: list[int],
    event_key: str,
    event_type: str,
    payload: dict,
) -> None:
    if not recipient_user_ids:
        return
    target_ids = (
        await db.scalars(
            select(DeliveryTarget.id)
            .join(RoutingRule, RoutingRule.delivery_target_id == DeliveryTarget.id)
            .where(
                DeliveryTarget.organization_id == organization_id,
                DeliveryTarget.provider == "feishu",
                DeliveryTarget.is_active.is_(True),
                RoutingRule.organization_id == organization_id,
                RoutingRule.member_user_id.in_(recipient_user_ids),
                RoutingRule.enabled.is_(True),
            )
            .distinct()
        )
    ).all()
    for target_id in target_ids:
        await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=f"{event_key}:feishu:{target_id}",
        )
