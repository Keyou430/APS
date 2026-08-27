from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, require_permission
from app.database import get_db
from app.models import AuditEvent
from app.schemas.audit import AuditEventListResponse, AuditEventResponse


router = APIRouter(prefix="/api/audit-events", tags=["Audit"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
AuditContext = Annotated[OrganizationContext, Depends(require_permission("audit:read"))]
_SENSITIVE_DETAIL_FRAGMENTS = (
    "content",
    "query",
    "prompt",
    "answer",
    "chunk",
    "path",
    "token",
    "password",
    "key",
    "error_body",
)


def safe_details(details: dict) -> dict:
    return {
        str(key): value
        for key, value in details.items()
        if not any(fragment in str(key).casefold() for fragment in _SENSITIVE_DETAIL_FRAGMENTS)
        and isinstance(value, (str, int, float, bool, type(None)))
    }


@router.get("", response_model=AuditEventListResponse)
async def list_audit_events(
    db: DbSession,
    context: AuditContext,
    cursor: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    action: Annotated[str | None, Query()] = None,
    resource_type: Annotated[str | None, Query()] = None,
    outcome: Annotated[str | None, Query()] = None,
    created_after: Annotated[datetime | None, Query()] = None,
) -> AuditEventListResponse:
    statement = select(AuditEvent).where(
        AuditEvent.organization_id == context.organization_id
    )
    if cursor is not None:
        statement = statement.where(AuditEvent.id < cursor)
    if action is not None:
        statement = statement.where(AuditEvent.action == action)
    if resource_type is not None:
        statement = statement.where(AuditEvent.resource_type == resource_type)
    if outcome is not None:
        statement = statement.where(AuditEvent.outcome == outcome)
    if created_after is not None:
        statement = statement.where(AuditEvent.created_at >= created_after)
    events = list((await db.scalars(statement.order_by(AuditEvent.id.desc()).limit(limit + 1))).all())
    next_cursor = events[limit].id if len(events) > limit else None
    return AuditEventListResponse(
        items=[
            AuditEventResponse(
                id=event.id, actor_user_id=event.actor_user_id, actor_kind=event.actor_kind,
                action=event.action, resource_type=event.resource_type, resource_id=event.resource_id,
                outcome=event.outcome, request_id=event.request_id, details=safe_details(event.details),
                created_at=event.created_at,
            )
            for event in events[:limit]
        ],
        next_cursor=next_cursor,
    )
