from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import joinedload

import pytest

from app.database import SessionLocal
from app.models import (
    ChannelIdentity,
    DeliveryOutbox,
    DeliveryTarget,
    OrganizationMembership,
    RoutingRule,
    Role,
    RolePermission,
    User,
)
from app.services.routing import (
    RoutingNotFoundError,
    RoutingPermissionError,
    create_run_correlation,
    enqueue_approval_notification,
    enqueue_delivery,
    mark_delivery_failure,
    resolve_route,
)


async def admin_membership() -> OrganizationMembership:
    async with SessionLocal() as db:
        membership = await db.scalar(
            select(OrganizationMembership)
            .options(
                joinedload(OrganizationMembership.role)
                .selectinload(Role.permission_links)
                .joinedload(RolePermission.permission)
            )
            .where(OrganizationMembership.user_id == 1)
        )
        assert membership is not None
        return membership


@pytest.mark.asyncio
async def test_routing_resolves_inside_org_and_outbox_is_idempotent() -> None:
    membership = await admin_membership()
    async with SessionLocal() as db:
        identity = ChannelIdentity(
            organization_id=membership.organization_id,
            provider="feishu",
            external_user_id="feishu-user-1",
            external_conversation_id="feishu-chat-1",
        )
        target = DeliveryTarget(
            organization_id=membership.organization_id,
            provider="feishu",
            external_conversation_id="feishu-chat-1",
        )
        db.add_all([identity, target])
        await db.flush()
        db.add(
            RoutingRule(
                organization_id=membership.organization_id,
                channel_identity_id=identity.id,
                delivery_target_id=target.id,
                member_user_id=membership.user_id,
                priority=10,
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        route = await resolve_route(
            db,
            membership,
            provider="feishu",
            external_user_id="feishu-user-1",
            external_conversation_id="feishu-chat-1",
        )
        correlation = await create_run_correlation(
            db,
            route,
            hermes_session_id="hermes-session-1",
            hermes_run_id="hermes-run-1",
            idempotency_key="route-idem-1",
        )
        first = await enqueue_delivery(
            db,
            correlation,
            event_type="message.completed",
            payload={"text": "done"},
            idempotency_key="delivery-idem-1",
        )
        duplicate = await enqueue_delivery(
            db,
            correlation,
            event_type="message.completed",
            payload={"text": "done"},
            idempotency_key="delivery-idem-1",
        )
        await db.commit()

    assert correlation.organization_id == membership.organization_id
    assert first.id == duplicate.id


@pytest.mark.asyncio
async def test_routing_rejects_a_cross_provider_identity_target_binding() -> None:
    membership = await admin_membership()
    async with SessionLocal() as db:
        identity = ChannelIdentity(
            organization_id=membership.organization_id,
            provider="feishu",
            external_user_id="feishu-user-x",
            external_conversation_id="feishu-chat-x",
        )
        cross_provider_target = DeliveryTarget(
            organization_id=membership.organization_id,
            provider="dingtalk",
            external_conversation_id="dingtalk-chat-x",
        )
        db.add_all([identity, cross_provider_target])
        await db.flush()
        db.add(
            RoutingRule(
                organization_id=membership.organization_id,
                channel_identity_id=identity.id,
                delivery_target_id=cross_provider_target.id,
                member_user_id=membership.user_id,
                priority=1,
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        with pytest.raises(RoutingNotFoundError):
            await resolve_route(
                db,
                membership,
                provider="feishu",
                external_user_id="feishu-user-x",
                external_conversation_id="feishu-chat-x",
            )


@pytest.mark.asyncio
async def test_routing_rejects_an_identity_from_another_organization() -> None:
    membership = await admin_membership()
    async with SessionLocal() as db:
        identity = ChannelIdentity(
            organization_id=membership.organization_id + 100,
            provider="dingtalk",
            external_user_id="other-user",
            external_conversation_id="other-chat",
        )
        db.add(identity)
        await db.commit()

    async with SessionLocal() as db:
        with pytest.raises(RoutingNotFoundError):
            await resolve_route(
                db,
                membership,
                provider="dingtalk",
                external_user_id="other-user",
                external_conversation_id="other-chat",
            )


@pytest.mark.asyncio
async def test_outbox_failure_transitions_to_retry_then_dead_letter() -> None:
    now = datetime(2026, 7, 24, tzinfo=UTC)
    outbox = DeliveryOutbox(
        organization_id=1,
        delivery_target_id=1,
        event_type="message.completed",
        idempotency_key="failure-idem",
        payload={"text": "done"},
    )

    mark_delivery_failure(outbox, error_code="timeout", now=now, max_attempts=2)
    assert outbox.status == "retry"
    assert outbox.attempts == 1
    assert outbox.last_error == "timeout"
    assert outbox.next_attempt_at is not None

    mark_delivery_failure(outbox, error_code="timeout", now=now, max_attempts=2)
    assert outbox.status == "dead_letter"
    assert outbox.attempts == 2
    assert outbox.next_attempt_at is None


@pytest.mark.asyncio
async def test_approval_notification_requires_chat_route_permission() -> None:
    membership = await admin_membership()
    async with SessionLocal() as db:
        identity = ChannelIdentity(
            organization_id=membership.organization_id,
            provider="feishu",
            external_user_id="approval-user",
            external_conversation_id="approval-chat",
        )
        target = DeliveryTarget(
            organization_id=membership.organization_id,
            provider="feishu",
            external_conversation_id="approval-chat",
        )
        db.add_all([identity, target])
        await db.flush()
        db.add(
            RoutingRule(
                organization_id=membership.organization_id,
                channel_identity_id=identity.id,
                delivery_target_id=target.id,
                member_user_id=membership.user_id,
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        user_role = await db.scalar(select(Role).where(Role.name == "user"))
        route_user = User(
            username="routing-approval-user",
            password_hash="test-hash",
            email="routing-approval-user@example.com",
            role=user_role,
            default_organization_id=membership.organization_id,
        )
        db.add(route_user)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=membership.organization_id,
                user_id=route_user.id,
                role_id=user_role.id,
            )
        )
        await db.commit()
        restricted_membership = await db.scalar(
            select(OrganizationMembership)
            .options(
                joinedload(OrganizationMembership.role)
                .selectinload(Role.permission_links)
                .joinedload(RolePermission.permission)
            )
            .where(OrganizationMembership.user_id == route_user.id)
        )
        assert restricted_membership is not None

    async with SessionLocal() as db:
        route = await resolve_route(
            db,
            membership,
            provider="feishu",
            external_user_id="approval-user",
            external_conversation_id="approval-chat",
        )
        correlation = await create_run_correlation(
            db,
            route,
            hermes_session_id="approval-session",
            hermes_run_id="approval-run",
            idempotency_key="approval-run-idem",
        )
        with pytest.raises(RoutingPermissionError):
            await enqueue_approval_notification(
                db,
                restricted_membership,
                correlation,
                payload={"approval_id": "approval-1"},
                idempotency_key="approval-delivery-idem",
            )
