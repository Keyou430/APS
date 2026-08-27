from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import has_permission
from app.models import (
    ChannelIdentity,
    DeliveryOutbox,
    DeliveryTarget,
    HermesProfile,
    OrganizationMembership,
    RoutingRule,
    RunCorrelation,
)

SUPPORTED_PROVIDERS = ("feishu", "dingtalk")


class RoutingError(RuntimeError):
    pass


class RoutingNotFoundError(RoutingError):
    pass


class RoutingPermissionError(RoutingError):
    pass


@dataclass(frozen=True)
class ResolvedRoute:
    organization_id: int
    routing_rule: RoutingRule
    channel_identity: ChannelIdentity
    delivery_target: DeliveryTarget
    member_user_id: int


@dataclass(frozen=True)
class DeliveryResult:
    provider: str
    external_message_id: str | None = None


class ChannelDeliveryAdapter(Protocol):
    provider: str

    async def send(
        self,
        target: DeliveryTarget,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> DeliveryResult: ...


class UnconfiguredDeliveryAdapter:
    """Contract placeholder until a provider credential and webhook contract exist."""

    def __init__(self, provider: str) -> None:
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported delivery provider: {provider}")
        self.provider = provider

    async def send(
        self,
        target: DeliveryTarget,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> DeliveryResult:
        raise RoutingError(f"Delivery adapter is not configured for {self.provider}")


def _require_route_permission(membership: OrganizationMembership) -> None:
    if not has_permission(membership, "chat:route"):
        raise RoutingPermissionError("chat:route permission is required")


async def resolve_route(
    db: AsyncSession,
    membership: OrganizationMembership,
    *,
    provider: str,
    external_user_id: str,
    external_conversation_id: str,
) -> ResolvedRoute:
    _require_route_permission(membership)
    if provider not in SUPPORTED_PROVIDERS:
        raise RoutingNotFoundError("Unsupported channel provider")

    route = await db.scalar(
        select(RoutingRule)
        .join(ChannelIdentity, RoutingRule.channel_identity_id == ChannelIdentity.id)
        .join(DeliveryTarget, RoutingRule.delivery_target_id == DeliveryTarget.id)
        .options(
            joinedload(RoutingRule.channel_identity),
            joinedload(RoutingRule.delivery_target),
        )
        .where(
            RoutingRule.organization_id == membership.organization_id,
            RoutingRule.enabled.is_(True),
            ChannelIdentity.organization_id == membership.organization_id,
            ChannelIdentity.provider == provider,
            ChannelIdentity.external_user_id == external_user_id,
            ChannelIdentity.external_conversation_id == external_conversation_id,
            ChannelIdentity.is_active.is_(True),
            DeliveryTarget.id == RoutingRule.delivery_target_id,
            DeliveryTarget.organization_id == membership.organization_id,
            # A channel identity of one provider must never resolve to a
            # delivery target of another provider.
            DeliveryTarget.provider == provider,
            DeliveryTarget.is_active.is_(True),
        )
        .order_by(RoutingRule.priority.asc(), RoutingRule.id.asc())
    )
    if route is None:
        raise RoutingNotFoundError("No active route matched the channel identity")

    target_membership = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == membership.organization_id,
            OrganizationMembership.user_id == route.member_user_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    if target_membership is None:
        raise RoutingNotFoundError("Route target is not an active organization member")

    if route.hermes_profile_id is not None:
        profile = await db.scalar(
            select(HermesProfile).where(
                HermesProfile.id == route.hermes_profile_id,
                HermesProfile.organization_id == membership.organization_id,
                HermesProfile.user_id == route.member_user_id,
            )
        )
        if profile is None:
            raise RoutingNotFoundError("Route profile is outside the organization scope")

    return ResolvedRoute(
        organization_id=membership.organization_id,
        routing_rule=route,
        channel_identity=route.channel_identity,
        delivery_target=route.delivery_target,
        member_user_id=route.member_user_id,
    )


async def create_run_correlation(
    db: AsyncSession,
    route: ResolvedRoute,
    *,
    hermes_session_id: str,
    hermes_run_id: str | None,
    idempotency_key: str,
) -> RunCorrelation:
    existing = await db.scalar(
        select(RunCorrelation).where(RunCorrelation.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if (
            existing.organization_id != route.organization_id
            or existing.routing_rule_id != route.routing_rule.id
        ):
            raise RoutingError("Run idempotency key conflicts with another route")
        return existing

    correlation = RunCorrelation(
        organization_id=route.organization_id,
        routing_rule_id=route.routing_rule.id,
        channel_identity_id=route.channel_identity.id,
        delivery_target_id=route.delivery_target.id,
        member_user_id=route.member_user_id,
        hermes_session_id=hermes_session_id,
        hermes_run_id=hermes_run_id,
        idempotency_key=idempotency_key,
    )
    db.add(correlation)
    await db.flush()
    return correlation


async def enqueue_delivery(
    db: AsyncSession,
    correlation: RunCorrelation,
    *,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> DeliveryOutbox:
    existing = await db.scalar(
        select(DeliveryOutbox).where(DeliveryOutbox.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if (
            existing.organization_id != correlation.organization_id
            or existing.run_correlation_id != correlation.id
        ):
            raise RoutingError("Delivery idempotency key conflicts with another correlation")
        return existing

    outbox = DeliveryOutbox(
        organization_id=correlation.organization_id,
        run_correlation_id=correlation.id,
        delivery_target_id=correlation.delivery_target_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    db.add(outbox)
    await db.flush()
    return outbox


async def enqueue_approval_notification(
    db: AsyncSession,
    membership: OrganizationMembership,
    correlation: RunCorrelation,
    *,
    payload: dict[str, Any],
    idempotency_key: str,
) -> DeliveryOutbox:
    _require_route_permission(membership)
    if correlation.organization_id != membership.organization_id:
        raise RoutingPermissionError("Approval correlation is outside the organization scope")
    return await enqueue_delivery(
        db,
        correlation,
        event_type="hermes.approval.request",
        payload=payload,
        idempotency_key=idempotency_key,
    )


def mark_delivery_failure(
    outbox: DeliveryOutbox,
    *,
    error_code: str,
    now: datetime,
    max_attempts: int = 5,
    base_delay_seconds: int = 5,
) -> None:
    outbox.attempts = (outbox.attempts or 0) + 1
    outbox.last_error = error_code[:120]
    if outbox.attempts >= max_attempts:
        outbox.status = "dead_letter"
        outbox.next_attempt_at = None
        return
    outbox.status = "retry"
    outbox.next_attempt_at = now + timedelta(
        seconds=base_delay_seconds * (2 ** (outbox.attempts - 1))
    )
