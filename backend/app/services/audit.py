from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, OrganizationMembership


async def record_audit(
    db: AsyncSession,
    membership: OrganizationMembership,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: Mapping[str, object] | None = None,
) -> None:
    db.add(
        AuditEvent(
            organization_id=membership.organization_id,
            actor_user_id=membership.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=dict(details or {}),
        )
    )
