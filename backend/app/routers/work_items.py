from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, has_permission, require_permission
from app.database import get_db
from app.models import OrganizationMembership, OrganizationPlacement, WorkItem, WorkItemEvent
from app.schemas.work_items import (
    WorkItemCreate,
    WorkItemEventListResponse,
    WorkItemEventResponse,
    WorkItemListResponse,
    WorkItemResponse,
    WorkItemScope,
    WorkItemStatusUpdate,
    WorkItemUpdate,
)
from app.services.audit import record_audit
from app.services.work_item_archiver import calculate_archive_after


router = APIRouter(prefix="/api/work-items", tags=["Work Items"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
WorkItemReadContext = Annotated[OrganizationContext, Depends(require_permission("work_items:read"))]
WorkItemWriteContext = Annotated[OrganizationContext, Depends(require_permission("work_items:write"))]

STATUS_TRANSITIONS = {
    "pending": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": {"pending"},
    "cancelled": set(),
}


def can_manage_all(context: OrganizationContext) -> bool:
    return has_permission(context.membership, "org:admin")


async def scoped_membership(
    db: AsyncSession, organization_id: int, membership_id: int
) -> OrganizationMembership:
    membership = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.is_active.is_(True),
            OrganizationMembership.member_type == "internal",
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Assignee membership not found")
    return membership


async def visible_work_item(
    db: AsyncSession, context: OrganizationContext, work_item_id: int
) -> WorkItem:
    filters = [
        WorkItem.id == work_item_id,
        WorkItem.organization_id == context.organization_id,
    ]
    if not can_manage_all(context):
        filters.append(WorkItem.assignee_membership_id == context.membership.id)
    item = await db.scalar(select(WorkItem).where(*filters))
    if item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    return item


@router.post("", response_model=WorkItemResponse, status_code=201)
async def create_work_item(
    payload: WorkItemCreate, db: DbSession, context: WorkItemWriteContext
) -> WorkItem:
    assignee_id = payload.assignee_membership_id or context.membership.id
    if assignee_id != context.membership.id and not can_manage_all(context):
        raise HTTPException(status_code=403, detail="Only administrators can assign other members")
    await scoped_membership(db, context.organization_id, assignee_id)
    archive_after = (
        calculate_archive_after(payload.due_at, payload.archive_timezone)
        if payload.task_scope == "day"
        else None
    )
    item = WorkItem(
        organization_id=context.organization_id,
        assignee_membership_id=assignee_id,
        created_by_membership_id=context.membership.id,
        status="pending",
        archive_after=archive_after,
        **payload.model_dump(exclude={"assignee_membership_id"}),
    )
    db.add(item)
    await db.flush()
    db.add(
        WorkItemEvent(
            organization_id=context.organization_id,
            work_item_id=item.id,
            actor_membership_id=context.membership.id,
            from_status=None,
            to_status="pending",
        )
    )
    await record_audit(
        db,
        context.membership,
        action="work_item.create",
        resource_type="work_item",
        resource_id=str(item.id),
        details={
            "assignee_membership_id": assignee_id,
            "origin": item.origin,
            "priority": item.priority,
        },
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get("", response_model=WorkItemListResponse)
async def list_work_items(
    db: DbSession,
    context: WorkItemReadContext,
    status: Annotated[str | None, Query()] = None,
    scope: Annotated[WorkItemScope | None, Query()] = None,
    assignee_membership_id: int | None = None,
    unit_id: int | None = None,
) -> WorkItemListResponse:
    filters = [WorkItem.organization_id == context.organization_id]
    admin = can_manage_all(context)
    if not admin:
        # Placement is an admin filter only; it never expands a member's task scope.
        if unit_id is not None or (
            assignee_membership_id is not None
            and assignee_membership_id != context.membership.id
        ):
            raise HTTPException(status_code=403, detail="Insufficient permission")
        filters.append(WorkItem.assignee_membership_id == context.membership.id)
    elif assignee_membership_id is not None:
        await scoped_membership(db, context.organization_id, assignee_membership_id)
        filters.append(WorkItem.assignee_membership_id == assignee_membership_id)
    if status is not None:
        if status not in STATUS_TRANSITIONS:
            raise HTTPException(status_code=422, detail="Invalid work item status")
        filters.append(WorkItem.status == status)
    if scope is not None:
        filters.append(WorkItem.task_scope == scope)

    query = select(WorkItem)
    count_query = select(func.count(WorkItem.id))
    if unit_id is not None:
        query = query.join(
            OrganizationPlacement,
            OrganizationPlacement.membership_id == WorkItem.assignee_membership_id,
        )
        count_query = count_query.join(
            OrganizationPlacement,
            OrganizationPlacement.membership_id == WorkItem.assignee_membership_id,
        )
        filters.extend(
            [
                OrganizationPlacement.organization_id == context.organization_id,
                OrganizationPlacement.unit_id == unit_id,
            ]
        )
    items = list(
        (
            await db.scalars(
                query.where(*filters).order_by(WorkItem.status, WorkItem.due_at, WorkItem.id)
            )
        ).all()
    )
    total = await db.scalar(count_query.where(*filters))
    return WorkItemListResponse(items=items, total=total or 0)


@router.get("/events/{event_id}", response_model=WorkItemEventResponse)
async def get_work_item_event(
    event_id: int, db: DbSession, context: WorkItemReadContext
) -> WorkItemEvent:
    event = await db.scalar(
        select(WorkItemEvent).where(
            WorkItemEvent.id == event_id,
            WorkItemEvent.organization_id == context.organization_id,
        )
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Work item event not found")
    await visible_work_item(db, context, event.work_item_id)
    return event


@router.get("/{work_item_id}", response_model=WorkItemResponse)
async def get_work_item(
    work_item_id: int, db: DbSession, context: WorkItemReadContext
) -> WorkItem:
    return await visible_work_item(db, context, work_item_id)


@router.patch("/{work_item_id}", response_model=WorkItemResponse)
async def update_work_item(
    work_item_id: int,
    payload: WorkItemUpdate,
    db: DbSession,
    context: WorkItemWriteContext,
) -> WorkItem:
    item = await visible_work_item(db, context, work_item_id)
    changes = payload.model_dump(exclude_unset=True)
    for name, value in changes.items():
        setattr(item, name, value)
    if item.task_scope == "day" and item.archived_at is None and {
        "due_at",
        "archive_timezone",
    }.intersection(changes):
        item.archive_after = calculate_archive_after(item.due_at, item.archive_timezone)
    await record_audit(
        db,
        context.membership,
        action="work_item.update",
        resource_type="work_item",
        resource_id=str(item.id),
        details={"fields": sorted(changes)},
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{work_item_id}/status", response_model=WorkItemResponse)
async def update_work_item_status(
    work_item_id: int,
    payload: WorkItemStatusUpdate,
    db: DbSession,
    context: WorkItemWriteContext,
) -> WorkItem:
    item = await visible_work_item(db, context, work_item_id)
    if payload.status not in STATUS_TRANSITIONS[item.status]:
        raise HTTPException(status_code=409, detail="Invalid work item status transition")
    previous = item.status
    result = await db.execute(
        update(WorkItem)
        .where(
            WorkItem.id == item.id,
            WorkItem.organization_id == context.organization_id,
            WorkItem.status == previous,
        )
        .values(status=payload.status, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Work item status changed concurrently")
    db.add(
        WorkItemEvent(
            organization_id=context.organization_id,
            work_item_id=item.id,
            actor_membership_id=context.membership.id,
            from_status=previous,
            to_status=payload.status,
        )
    )
    await record_audit(
        db,
        context.membership,
        action="work_item.status.update",
        resource_type="work_item",
        resource_id=str(item.id),
        details={"from_status": previous, "to_status": payload.status},
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{work_item_id}", status_code=204)
async def delete_work_item(
    work_item_id: int,
    db: DbSession,
    context: WorkItemWriteContext,
) -> None:
    item = await visible_work_item(db, context, work_item_id)
    await record_audit(
        db,
        context.membership,
        action="work_item.delete",
        resource_type="work_item",
        resource_id=str(item.id),
        details={"title": item.title},
    )
    await db.execute(
        delete(WorkItemEvent).where(
            WorkItemEvent.organization_id == context.organization_id,
            WorkItemEvent.work_item_id == item.id,
        )
    )
    await db.delete(item)
    await db.commit()


@router.get("/{work_item_id}/events", response_model=WorkItemEventListResponse)
async def list_work_item_events(
    work_item_id: int, db: DbSession, context: WorkItemReadContext
) -> WorkItemEventListResponse:
    await visible_work_item(db, context, work_item_id)
    events = list(
        (
            await db.scalars(
                select(WorkItemEvent)
                .where(
                    WorkItemEvent.organization_id == context.organization_id,
                    WorkItemEvent.work_item_id == work_item_id,
                )
                .order_by(WorkItemEvent.id)
            )
        ).all()
    )
    return WorkItemEventListResponse(items=events)
