import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditEvent, WorkItem


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkItemArchiveResult:
    archived_count: int
    batch_id: str | None


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def calculate_archive_after(due_at: datetime | None, timezone_name: str) -> datetime | None:
    if due_at is None:
        return None
    timezone = ZoneInfo(timezone_name)
    local_due = due_at.replace(tzinfo=timezone) if due_at.tzinfo is None else due_at.astimezone(timezone)
    next_day = local_due.date() + timedelta(days=1)
    return datetime.combine(next_day, time.min, timezone).astimezone(UTC)


async def archive_overdue_day_work_items(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    batch_size: int = 100,
) -> WorkItemArchiveResult:
    now_utc = ensure_utc(now or datetime.now(UTC))
    async with session_factory() as db:
        items = list(
            (
                await db.scalars(
                    select(WorkItem)
                    .where(
                        WorkItem.task_scope == "day",
                        WorkItem.archived_at.is_(None),
                        WorkItem.archive_after.is_not(None),
                        WorkItem.archive_after <= now_utc,
                        WorkItem.status.in_(("pending", "in_progress")),
                    )
                    .order_by(WorkItem.archive_after, WorkItem.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        if not items:
            return WorkItemArchiveResult(archived_count=0, batch_id=None)

        batch_id = str(uuid4())
        for item in items:
            timezone = ZoneInfo(item.archive_timezone)
            local_archive_time = now_utc.astimezone(timezone)
            iso_year, iso_week, _ = local_archive_time.isocalendar()
            week_key = f"{iso_year:04d}-W{iso_week:02d}"
            item.original_scope = item.task_scope
            item.original_due_at = item.due_at
            item.task_scope = "week"
            item.archived_at = now_utc
            item.archive_reason = "overdue"
            item.archive_batch_id = batch_id
            item.week_key = week_key
            item.archive_after = None
            db.add(
                AuditEvent(
                    organization_id=item.organization_id,
                    actor_user_id=None,
                    actor_kind="system",
                    action="work_item.scope.archive",
                    resource_type="work_item",
                    resource_id=str(item.id),
                    details={
                        "archive_batch_id": batch_id,
                        "archive_reason": "overdue",
                        "from_scope": "day",
                        "to_scope": "week",
                        "original_due_at": item.original_due_at.isoformat()
                        if item.original_due_at
                        else None,
                        "week_key": week_key,
                    },
                )
            )
        await db.commit()
        return WorkItemArchiveResult(archived_count=len(items), batch_id=batch_id)


async def run_work_item_archiver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    poll_seconds: float,
    batch_size: int,
) -> None:
    while True:
        try:
            result = await archive_overdue_day_work_items(
                session_factory, batch_size=batch_size
            )
            if result.archived_count:
                logger.info(
                    "Archived %s overdue daily work items in batch %s",
                    result.archived_count,
                    result.batch_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Work item archive cycle failed")
        await asyncio.sleep(poll_seconds)
