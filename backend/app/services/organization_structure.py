from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Organization,
    OrganizationMembership,
    OrganizationPlacement,
    OrganizationPosition,
    OrganizationStructureState,
    OrganizationUnit,
    Role,
)


async def ensure_organization_structure(
    db: AsyncSession,
    organization_id: int,
) -> bool:
    changed = False
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise ValueError("Organization does not exist")

    root = await db.scalar(
        select(OrganizationUnit).where(
            OrganizationUnit.organization_id == organization_id,
            OrganizationUnit.parent_id.is_(None),
        )
    )
    if root is None:
        root = OrganizationUnit(
            organization_id=organization_id,
            parent_id=None,
            name=organization.name,
            code="root",
            sort_order=0,
            is_active=True,
        )
        db.add(root)
        await db.flush()
        changed = True

    state = await db.get(OrganizationStructureState, organization_id)
    if state is None:
        db.add(OrganizationStructureState(organization_id=organization_id, revision=1))
        changed = True

    membership_rows = (
        await db.execute(
            select(OrganizationMembership, Role)
            .join(Role, Role.id == OrganizationMembership.role_id)
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.is_active.is_(True),
                OrganizationMembership.member_type == "internal",
            )
        )
    ).all()
    positions = {
        position.title: position
        for position in (
            await db.scalars(
                select(OrganizationPosition).where(
                    OrganizationPosition.organization_id == organization_id,
                    OrganizationPosition.unit_id == root.id,
                )
            )
        ).all()
    }
    existing_placements = set(
        (
            await db.scalars(
                select(OrganizationPlacement.membership_id).where(
                    OrganizationPlacement.organization_id == organization_id
                )
            )
        ).all()
    )
    for membership, role in membership_rows:
        position = positions.get(role.name)
        if position is None:
            position = OrganizationPosition(
                organization_id=organization_id,
                unit_id=root.id,
                title=role.name,
                level=role.name,
                sort_order=len(positions),
                is_active=True,
            )
            db.add(position)
            await db.flush()
            positions[role.name] = position
            changed = True
        if membership.id not in existing_placements:
            db.add(
                OrganizationPlacement(
                    organization_id=organization_id,
                    membership_id=membership.id,
                    unit_id=root.id,
                    position_id=position.id,
                )
            )
            existing_placements.add(membership.id)
            changed = True
    return changed
