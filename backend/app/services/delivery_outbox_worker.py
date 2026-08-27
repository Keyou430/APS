"""Delivery outbox consumer (Phase 1 C1).

Claims delivery_outbox rows (pending/due retry), sends through the
provider-matched adapter, and records provider message ids or sanitized
failures. Business transactions only enqueue rows; all external calls happen
here, outside any business transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models import DeliveryOutbox, DeliveryTarget
from app.services.routing import ChannelDeliveryAdapter, mark_delivery_failure


async def enqueue_channel_delivery(
    db: AsyncSession,
    *,
    organization_id: int,
    delivery_target_id: int,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> DeliveryOutbox:
    """Idempotent enqueue for platform-owned notifications (no run correlation)."""
    existing = await db.scalar(
        select(DeliveryOutbox).where(DeliveryOutbox.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.organization_id != organization_id:
            raise ValueError("Delivery idempotency key conflicts with another organization")
        return existing
    outbox = DeliveryOutbox(
        organization_id=organization_id,
        run_correlation_id=None,
        delivery_target_id=delivery_target_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    try:
        # The unique-key race is local to this enqueue attempt. A savepoint
        # keeps an enclosing approval/audit transaction usable when another
        # worker wins the same idempotency key between the read and flush.
        async with db.begin_nested():
            db.add(outbox)
            await db.flush()
    except IntegrityError:
        existing = await db.scalar(
            select(DeliveryOutbox).where(DeliveryOutbox.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        return existing
    return outbox


async def claim_delivery_outbox(
    db: AsyncSession, *, worker_id: str, limit: int = 10, now: datetime | None = None
) -> list[DeliveryOutbox]:
    moment = now or datetime.now(UTC)
    statement = (
        select(DeliveryOutbox)
        .where(
            or_(
                DeliveryOutbox.status == "pending",
                (DeliveryOutbox.status == "retry")
                & DeliveryOutbox.next_attempt_at.is_not(None)
                & (DeliveryOutbox.next_attempt_at <= moment),
            )
        )
        .order_by(DeliveryOutbox.id)
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    rows = list((await db.scalars(statement)).all())
    for row in rows:
        row.status = "sending"
        row.claimed_at = moment
    await db.flush()
    return rows


async def recover_stale_delivery_claims(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    lease_seconds: float | None = None,
    max_attempts: int | None = None,
) -> int:
    moment = now or datetime.now(UTC)
    settings = get_settings()
    lease = timedelta(
        seconds=lease_seconds or settings.delivery_worker_lease_seconds
    )
    attempts_limit = max_attempts or settings.delivery_worker_max_attempts
    rows = list(
        (
            await db.scalars(
                select(DeliveryOutbox).where(
                    DeliveryOutbox.status == "sending",
                    DeliveryOutbox.claimed_at.is_not(None),
                    DeliveryOutbox.claimed_at <= moment - lease,
                )
            )
        ).all()
    )
    for row in rows:
        row.claimed_at = None
        mark_delivery_failure(
            row,
            error_code="delivery_lease_expired",
            now=moment,
            max_attempts=attempts_limit,
            base_delay_seconds=settings.delivery_worker_backoff_base_seconds,
        )
    await db.flush()
    return len(rows)


async def run_delivery_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    adapters: dict[str, ChannelDeliveryAdapter],
    worker_id: str,
    limit: int = 10,
    now: datetime | None = None,
    max_attempts: int | None = None,
) -> int:
    moment = now or datetime.now(UTC)
    settings = get_settings()
    attempts_limit = max_attempts or settings.delivery_worker_max_attempts
    async with session_factory() as db:
        await recover_stale_delivery_claims(db, now=moment, max_attempts=attempts_limit)
        claimed = await claim_delivery_outbox(db, worker_id=worker_id, limit=limit, now=moment)
        await db.commit()

    for snapshot in claimed:
        async with session_factory() as db:
            row = (
                await db.scalars(
                    select(DeliveryOutbox)
                    .where(
                        DeliveryOutbox.id == snapshot.id,
                        DeliveryOutbox.status == "sending",
                    )
                )
            ).unique().one_or_none()
            if row is None:
                continue
            target = await db.get(DeliveryTarget, row.delivery_target_id)
            if target is None or not target.is_active:
                row.claimed_at = None
                mark_delivery_failure(
                    row,
                    error_code="delivery_target_inactive",
                    now=moment,
                    max_attempts=attempts_limit,
                    base_delay_seconds=settings.delivery_worker_backoff_base_seconds,
                )
                await db.commit()
                continue
            adapter = adapters.get(target.provider)
            if adapter is None:
                row.claimed_at = None
                mark_delivery_failure(
                    row,
                    error_code=f"{target.provider}_not_configured",
                    now=moment,
                    max_attempts=attempts_limit,
                    base_delay_seconds=settings.delivery_worker_backoff_base_seconds,
                )
                await db.commit()
                continue
            try:
                result = await adapter.send(
                    target, event_type=row.event_type, payload=row.payload or {}
                )
            except Exception as exc:  # sanitized codes only reach the row
                code = getattr(exc, "code", None)
                if not isinstance(code, str) or not code:
                    code = "delivery_adapter_error"
                row.claimed_at = None
                mark_delivery_failure(
                    row,
                    error_code=code[:120],
                    now=moment,
                    max_attempts=attempts_limit,
                    base_delay_seconds=settings.delivery_worker_backoff_base_seconds,
                )
                await db.commit()
                continue
            row.status = "sent"
            row.attempts = (row.attempts or 0) + 1
            row.last_error = None
            row.next_attempt_at = None
            row.claimed_at = None
            row.delivered_at = moment
            row.external_message_id = result.external_message_id
            await db.commit()
    return len(claimed)
