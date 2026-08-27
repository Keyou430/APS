from sqlalchemy import ColumnElement

from app.models import MemoryRecord


def owner_active_predicates(
    *,
    organization_id: int,
    user_id: int,
) -> tuple[ColumnElement[bool], ...]:
    return (
        MemoryRecord.organization_id == organization_id,
        MemoryRecord.user_id == user_id,
        MemoryRecord.status == "active",
    )
