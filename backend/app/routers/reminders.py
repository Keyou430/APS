from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, OrganizationContext, require_permission
from app.database import get_db
from app.models import Reminder
from app.schemas.reminders import (
    ReminderCreate,
    ReminderListResponse,
    ReminderResponse,
    ReminderUpdate,
)

router = APIRouter(prefix="/api/reminders", tags=["Reminders"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReminderReadContext = Annotated[
    OrganizationContext, Depends(require_permission("reminders:read"))
]
ReminderWriteContext = Annotated[
    OrganizationContext, Depends(require_permission("reminders:write"))
]


async def owned_reminder(
    db: AsyncSession, reminder_id: int, user_id: int, organization_id: int
) -> Reminder:
    reminder = await db.scalar(
        select(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.user_id == user_id,
            Reminder.organization_id == organization_id,
        )
    )
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@router.post("", response_model=ReminderResponse, status_code=201, summary="Create a reminder")
async def create_reminder(
    payload: ReminderCreate,
    db: DbSession,
    user: CurrentUser,
    context: ReminderWriteContext,
) -> Reminder:
    reminder = Reminder(
        organization_id=context.organization_id,
        user_id=user.id,
        status="active",
        **payload.model_dump(),
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)
    return reminder


@router.get("", response_model=ReminderListResponse, summary="List current user's reminders")
async def list_reminders(
    db: DbSession,
    user: CurrentUser,
    context: ReminderReadContext,
    status: Annotated[Literal["active", "completed"] | None, Query()] = None,
) -> ReminderListResponse:
    query = select(Reminder).where(
        Reminder.user_id == user.id,
        Reminder.organization_id == context.organization_id,
    )
    if status:
        query = query.where(Reminder.status == status)
    query = query.order_by(Reminder.due_date)
    return ReminderListResponse(items=list((await db.scalars(query)).all()))


@router.get(
    "/upcoming", response_model=ReminderListResponse, summary="List active reminders due in 7 days"
)
async def upcoming_reminders(
    db: DbSession,
    user: CurrentUser,
    context: ReminderReadContext,
) -> ReminderListResponse:
    now = datetime.now(UTC)
    query = select(Reminder).where(
        Reminder.user_id == user.id,
        Reminder.organization_id == context.organization_id,
        Reminder.status == "active",
        Reminder.due_date >= now,
        Reminder.due_date <= now + timedelta(days=7),
    )
    return ReminderListResponse(items=list((await db.scalars(query)).all()))


@router.put("/{reminder_id}", response_model=ReminderResponse, summary="Update a reminder")
async def update_reminder(
    payload: ReminderUpdate,
    reminder_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ReminderWriteContext,
) -> Reminder:
    reminder = await owned_reminder(db, reminder_id, user.id, context.organization_id)
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(reminder, name, value)
    await db.commit()
    await db.refresh(reminder)
    return reminder


@router.post(
    "/{reminder_id}/complete", response_model=ReminderResponse, summary="Mark a reminder complete"
)
async def complete_reminder(
    reminder_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ReminderWriteContext,
) -> Reminder:
    reminder = await owned_reminder(db, reminder_id, user.id, context.organization_id)
    reminder.status = "completed"
    await db.commit()
    await db.refresh(reminder)
    return reminder


@router.delete("/{reminder_id}", status_code=204, summary="Delete a reminder")
async def delete_reminder(
    reminder_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ReminderWriteContext,
) -> None:
    reminder = await owned_reminder(db, reminder_id, user.id, context.organization_id)
    await db.delete(reminder)
    await db.commit()
