"""Cron scheduling for pipeline tasks.

Computes ``next_run_at`` from a five-field cron expression in the task's
IANA timezone and enqueues due scheduled runs. Concurrency between workers
is collapsed by the ``(organization_id, task_id, scheduled_for)`` unique
constraint on ``pipeline_runs``.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PipelineRun, PipelineTask


class CronExpressionError(ValueError):
    """Raised when a cron expression cannot be parsed or has no future match."""


_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
_SEARCH_DAYS = 366 * 5


def _parse_field(field: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronExpressionError("cron step must be a positive integer")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            start_text, end_text = part.split("-", 1)
            if not (start_text.isdigit() and end_text.isdigit()):
                raise CronExpressionError("cron range must be numeric")
            start, end = int(start_text), int(end_text)
        else:
            if not part.isdigit():
                raise CronExpressionError("cron value must be numeric")
            start = end = int(part)
        if start < low or end > high or start > end:
            raise CronExpressionError("cron field out of range")
        values.update(range(start, end + 1, step))
    if not values:
        raise CronExpressionError("cron field is empty")
    return frozenset(values)


def parse_cron(expression: str) -> tuple[frozenset[int], ...]:
    parts = expression.split()
    if len(parts) != 5:
        raise CronExpressionError("schedule must be a five-field cron expression")
    return tuple(
        _parse_field(part, low, high) for part, (low, high) in zip(parts, _FIELD_RANGES)
    )


def _day_matches(
    day: datetime,
    dom_values: frozenset[int],
    dow_values: frozenset[int],
    dom_unrestricted: bool,
    dow_unrestricted: bool,
) -> bool:
    dom_ok = day.day in dom_values
    dow_ok = ((day.weekday() + 1) % 7) in dow_values
    if dom_unrestricted and dow_unrestricted:
        return True
    if dom_unrestricted:
        return dow_ok
    if dow_unrestricted:
        return dom_ok
    # Vixie-cron semantics: when both fields are restricted, either may match.
    return dom_ok or dow_ok


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; treat them as UTC like PostgreSQL does.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def next_cron_run(expression: str, timezone: str, *, after: datetime) -> datetime:
    """Return the next run time strictly after ``after`` (UTC-aware), in UTC."""
    minutes, hours, dom_values, month_values, dow_values = parse_cron(expression)
    dom_unrestricted = expression.split()[2] == "*"
    dow_unrestricted = expression.split()[4] == "*"
    tz = ZoneInfo(timezone)
    cursor = _as_utc(after).astimezone(tz)
    day = cursor.date()
    sorted_hours = sorted(hours)
    sorted_minutes = sorted(minutes)
    for _ in range(_SEARCH_DAYS):
        if day.month in month_values and _day_matches(
            day, dom_values, dow_values, dom_unrestricted, dow_unrestricted
        ):
            for hour in sorted_hours:
                for minute in sorted_minutes:
                    candidate = datetime.combine(day, time(hour, minute), tzinfo=tz)
                    if candidate > cursor:
                        return candidate.astimezone(UTC)
        day += timedelta(days=1)
    raise CronExpressionError("cron expression has no occurrence within five years")


async def schedule_due_pipeline_tasks(
    db: AsyncSession, *, now: datetime | None = None
) -> int:
    """Arm or enqueue scheduled runs for ready tasks and advance ``next_run_at``.

    Returns the number of runs enqueued. Only the latest due slot is
    enqueued per cycle (slots missed while no worker was running collapse
    into a single catch-up run). A task whose stored cron cannot be parsed
    is paused so the worker loop does not spin on it forever.
    """
    now = now or datetime.now(UTC)
    tasks = list(
        (
            await db.scalars(
                select(PipelineTask).where(
                    PipelineTask.status == "ready",
                    PipelineTask.deleted_at.is_(None),
                    PipelineTask.schedule.is_not(None),
                    or_(
                        PipelineTask.next_run_at.is_(None),
                        PipelineTask.next_run_at <= now,
                    ),
                )
            )
        ).all()
    )
    enqueued = 0
    for task in tasks:
        try:
            if task.next_run_at is None:
                task.next_run_at = next_cron_run(
                    task.schedule, task.timezone, after=now
                )
                continue
            upcoming = next_cron_run(
                task.schedule, task.timezone, after=_as_utc(task.next_run_at)
            )
        except CronExpressionError:
            task.status = "paused"
            continue
        try:
            async with db.begin_nested():
                db.add(
                    PipelineRun(
                        organization_id=task.organization_id,
                        user_id=task.user_id,
                        task_id=task.id,
                        trigger_kind="scheduled",
                        status="queued",
                        scheduled_for=task.next_run_at,
                    )
                )
                task.next_run_at = upcoming
            enqueued += 1
        except IntegrityError:
            # Another worker already enqueued this slot; the savepoint above
            # rolled back, so re-apply the advance to avoid re-selection.
            task.next_run_at = upcoming
    return enqueued


def validate_schedule_expression(expression: str | None) -> str | None:
    """Reject cron expressions that cannot parse or can never match a day."""
    if expression is None:
        return expression
    next_cron_run(expression, "UTC", after=datetime(2000, 1, 1, tzinfo=UTC))
    return expression
