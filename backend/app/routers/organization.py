from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, require_permission
from app.database import get_db
from app.models import (
    OrganizationMembership,
    OrganizationPlacement,
    OrganizationPosition,
    OrganizationStructureState,
    OrganizationUnit,
    Role,
    User,
)
from app.schemas.organization import (
    OrganizationPersonResponse,
    OrganizationPlacementBatch,
    OrganizationPlacementInput,
    OrganizationPlacementResponse,
    OrganizationPlacementUpdate,
    OrganizationPositionCreate,
    OrganizationPositionResponse,
    OrganizationPositionUpdate,
    OrganizationStructureResponse,
    OrganizationUnitCreate,
    OrganizationUnitResponse,
    OrganizationUnitUpdate,
    RevisionRequest,
)
from app.services.audit import record_audit
from app.services.organization_structure import ensure_organization_structure


router = APIRouter(prefix="/api/organization", tags=["Organization Structure"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
OrganizationReadContext = Annotated[
    OrganizationContext, Depends(require_permission("org:read"))
]
OrganizationAdminContext = Annotated[
    OrganizationContext, Depends(require_permission("org:admin"))
]


async def structure_snapshot(
    db: AsyncSession,
    organization_id: int,
) -> OrganizationStructureResponse:
    state = await db.get(OrganizationStructureState, organization_id)
    if state is None:
        raise RuntimeError("Organization structure state is missing")
    units = list(
        (
            await db.scalars(
                select(OrganizationUnit)
                .where(OrganizationUnit.organization_id == organization_id)
                .order_by(
                    OrganizationUnit.sort_order,
                    OrganizationUnit.name,
                    OrganizationUnit.id,
                )
            )
        ).all()
    )
    positions = list(
        (
            await db.scalars(
                select(OrganizationPosition)
                .where(OrganizationPosition.organization_id == organization_id)
                .order_by(
                    OrganizationPosition.sort_order,
                    OrganizationPosition.title,
                    OrganizationPosition.id,
                )
            )
        ).all()
    )
    placements = list(
        (
            await db.scalars(
                select(OrganizationPlacement)
                .where(OrganizationPlacement.organization_id == organization_id)
                .order_by(OrganizationPlacement.membership_id)
            )
        ).all()
    )
    people_rows = (
        await db.execute(
            select(OrganizationMembership, User, Role)
            .join(User, User.id == OrganizationMembership.user_id)
            .join(Role, Role.id == OrganizationMembership.role_id)
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.is_active.is_(True),
                OrganizationMembership.member_type == "internal",
            )
            .order_by(User.username, OrganizationMembership.id)
        )
    ).all()
    return OrganizationStructureResponse(
        organization_id=organization_id,
        revision=state.revision,
        units=[OrganizationUnitResponse.model_validate(unit) for unit in units],
        positions=[
            OrganizationPositionResponse.model_validate(position)
            for position in positions
        ],
        placements=[
            OrganizationPlacementResponse.model_validate(placement)
            for placement in placements
        ],
        people=[
            OrganizationPersonResponse(
                membership_id=membership.id,
                user_id=user.id,
                username=user.username,
                email=user.email,
                role=role.name,
                member_type=membership.member_type,
            )
            for membership, user, role in people_rows
        ],
    )


async def ensure_structure(db: AsyncSession, organization_id: int) -> None:
    if await ensure_organization_structure(db, organization_id):
        await db.commit()


async def locked_state(
    db: AsyncSession,
    organization_id: int,
    expected_revision: int,
) -> OrganizationStructureState:
    await ensure_organization_structure(db, organization_id)
    await db.flush()
    state = await db.scalar(
        select(OrganizationStructureState)
        .where(OrganizationStructureState.organization_id == organization_id)
        .with_for_update()
    )
    if state is None:
        raise RuntimeError("Organization structure state is missing")
    if state.revision != expected_revision:
        raise HTTPException(
            status_code=409,
            detail="Organization structure revision conflict",
        )
    return state


async def scoped_unit(
    db: AsyncSession,
    organization_id: int,
    unit_id: int,
) -> OrganizationUnit:
    unit = await db.scalar(
        select(OrganizationUnit).where(
            OrganizationUnit.organization_id == organization_id,
            OrganizationUnit.id == unit_id,
        )
    )
    if unit is None:
        raise HTTPException(status_code=404, detail="Organization unit not found")
    return unit


async def scoped_position(
    db: AsyncSession,
    organization_id: int,
    position_id: int,
) -> OrganizationPosition:
    position = await db.scalar(
        select(OrganizationPosition).where(
            OrganizationPosition.organization_id == organization_id,
            OrganizationPosition.id == position_id,
        )
    )
    if position is None:
        raise HTTPException(status_code=404, detail="Organization position not found")
    return position


async def validate_unit_parent(
    db: AsyncSession,
    organization_id: int,
    unit_id: int,
    parent_id: int,
) -> None:
    units = {
        unit.id: unit
        for unit in (
            await db.scalars(
                select(OrganizationUnit).where(
                    OrganizationUnit.organization_id == organization_id
                )
            )
        ).all()
    }
    if parent_id not in units:
        raise HTTPException(status_code=404, detail="Parent organization unit not found")
    current_id: int | None = parent_id
    visited = {unit_id}
    while current_id is not None:
        if current_id in visited:
            raise HTTPException(status_code=409, detail="Organization unit cycle detected")
        visited.add(current_id)
        current_id = units[current_id].parent_id


async def validate_placement_items(
    db: AsyncSession,
    organization_id: int,
    items: list[OrganizationPlacementInput],
) -> dict[int, OrganizationPlacement]:
    membership_ids = [item.membership_id for item in items]
    if len(set(membership_ids)) != len(membership_ids):
        raise HTTPException(status_code=409, detail="Duplicate placement membership")
    manager_ids = {
        item.manager_membership_id
        for item in items
        if item.manager_membership_id is not None
    }
    required_membership_ids = set(membership_ids) | manager_ids
    memberships = {
        membership.id: membership
        for membership in (
            await db.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.id.in_(required_membership_ids),
                    OrganizationMembership.is_active.is_(True),
                    OrganizationMembership.member_type == "internal",
                )
            )
        ).all()
    }
    if set(memberships) != required_membership_ids:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    units = {
        unit.id: unit
        for unit in (
            await db.scalars(
                select(OrganizationUnit).where(
                    OrganizationUnit.organization_id == organization_id,
                    OrganizationUnit.id.in_({item.unit_id for item in items}),
                    OrganizationUnit.is_active.is_(True),
                )
            )
        ).all()
    }
    positions = {
        position.id: position
        for position in (
            await db.scalars(
                select(OrganizationPosition).where(
                    OrganizationPosition.organization_id == organization_id,
                    OrganizationPosition.id.in_({item.position_id for item in items}),
                    OrganizationPosition.is_active.is_(True),
                )
            )
        ).all()
    }
    for item in items:
        unit = units.get(item.unit_id)
        position = positions.get(item.position_id)
        if unit is None or position is None:
            raise HTTPException(status_code=404, detail="Placement target not found")
        if position.unit_id != unit.id:
            raise HTTPException(
                status_code=409,
                detail="Position does not belong to organization unit",
            )

    placements = {
        placement.membership_id: placement
        for placement in (
            await db.scalars(
                select(OrganizationPlacement).where(
                    OrganizationPlacement.organization_id == organization_id
                )
            )
        ).all()
    }
    manager_graph = {
        membership_id: placement.manager_membership_id
        for membership_id, placement in placements.items()
    }
    for item in items:
        manager_graph[item.membership_id] = item.manager_membership_id

    active_internal_count = len(
        (
            await db.scalars(
                select(OrganizationMembership.id).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.is_active.is_(True),
                    OrganizationMembership.member_type == "internal",
                )
            )
        ).all()
    )
    max_depth = active_internal_count + 1
    for start in manager_graph:
        current: int | None = start
        visited: set[int] = set()
        while current is not None:
            if current in visited or len(visited) > max_depth:
                raise HTTPException(
                    status_code=409,
                    detail="Organization manager cycle detected",
                )
            visited.add(current)
            current = manager_graph.get(current)
    return placements


async def apply_placement_batch(
    db: AsyncSession,
    context: OrganizationContext,
    state: OrganizationStructureState,
    items: list[OrganizationPlacementInput],
) -> None:
    placements = await validate_placement_items(db, context.organization_id, items)
    for item in items:
        placement = placements.get(item.membership_id)
        if placement is None:
            placement = OrganizationPlacement(
                organization_id=context.organization_id,
                membership_id=item.membership_id,
                unit_id=item.unit_id,
                position_id=item.position_id,
            )
            db.add(placement)
        placement.unit_id = item.unit_id
        placement.position_id = item.position_id
        placement.manager_membership_id = item.manager_membership_id
    state.revision += 1


@router.get("/structure", response_model=OrganizationStructureResponse)
async def get_structure(
    db: DbSession,
    context: OrganizationReadContext,
) -> OrganizationStructureResponse:
    await ensure_structure(db, context.organization_id)
    return await structure_snapshot(db, context.organization_id)


@router.post(
    "/units",
    response_model=OrganizationStructureResponse,
    status_code=201,
)
async def create_unit(
    payload: OrganizationUnitCreate,
    db: DbSession,
    context: OrganizationAdminContext,
) -> OrganizationStructureResponse:
    state = await locked_state(db, context.organization_id, payload.expected_revision)
    parent = await scoped_unit(db, context.organization_id, payload.parent_id)
    if not parent.is_active:
        raise HTTPException(status_code=409, detail="Parent organization unit is inactive")
    duplicate = await db.scalar(
        select(OrganizationUnit.id).where(
            OrganizationUnit.organization_id == context.organization_id,
            OrganizationUnit.code == payload.code,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Organization unit code already exists")
    unit = OrganizationUnit(
        organization_id=context.organization_id,
        parent_id=parent.id,
        name=payload.name,
        code=payload.code,
        sort_order=payload.sort_order,
        is_active=True,
    )
    db.add(unit)
    await db.flush()
    state.revision += 1
    await record_audit(
        db,
        context.membership,
        action="organization.unit.create",
        resource_type="organization_unit",
        resource_id=str(unit.id),
        details={"name": unit.name, "parent_id": unit.parent_id},
    )
    await db.commit()
    return await structure_snapshot(db, context.organization_id)


@router.patch("/units/{unit_id}", response_model=OrganizationStructureResponse)
async def update_unit(
    unit_id: int,
    payload: OrganizationUnitUpdate,
    db: DbSession,
    context: OrganizationAdminContext,
) -> OrganizationStructureResponse:
    state = await locked_state(db, context.organization_id, payload.expected_revision)
    unit = await scoped_unit(db, context.organization_id, unit_id)
    changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    if unit.parent_id is None:
        if changes.get("parent_id") is not None or changes.get("is_active") is False:
            raise HTTPException(status_code=409, detail="Root organization unit is protected")
        changes.pop("parent_id", None)
    elif "parent_id" in changes:
        parent_id = changes["parent_id"]
        if parent_id is None:
            raise HTTPException(status_code=409, detail="Only one root unit is allowed")
        await validate_unit_parent(db, context.organization_id, unit.id, parent_id)
    if "code" in changes and changes["code"] != unit.code:
        duplicate = await db.scalar(
            select(OrganizationUnit.id).where(
                OrganizationUnit.organization_id == context.organization_id,
                OrganizationUnit.code == changes["code"],
                OrganizationUnit.id != unit.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Organization unit code already exists")
    before = {name: getattr(unit, name) for name in changes}
    for name, value in changes.items():
        setattr(unit, name, value)
    state.revision += 1
    await record_audit(
        db,
        context.membership,
        action="organization.unit.update",
        resource_type="organization_unit",
        resource_id=str(unit.id),
        details={"before": before, "after": changes},
    )
    await db.commit()
    return await structure_snapshot(db, context.organization_id)


@router.delete("/units/{unit_id}", status_code=204, response_model=None)
async def delete_unit(
    unit_id: int,
    payload: RevisionRequest,
    db: DbSession,
    context: OrganizationAdminContext,
) -> None:
    state = await locked_state(db, context.organization_id, payload.expected_revision)
    unit = await scoped_unit(db, context.organization_id, unit_id)
    if unit.parent_id is None:
        raise HTTPException(status_code=409, detail="Root organization unit is protected")
    has_child = await db.scalar(
        select(OrganizationUnit.id).where(
            OrganizationUnit.organization_id == context.organization_id,
            OrganizationUnit.parent_id == unit.id,
        )
    )
    has_position = await db.scalar(
        select(OrganizationPosition.id).where(
            OrganizationPosition.organization_id == context.organization_id,
            OrganizationPosition.unit_id == unit.id,
        )
    )
    has_placement = await db.scalar(
        select(OrganizationPlacement.membership_id).where(
            OrganizationPlacement.organization_id == context.organization_id,
            OrganizationPlacement.unit_id == unit.id,
        )
    )
    if has_child is not None or has_position is not None or has_placement is not None:
        raise HTTPException(status_code=409, detail="Organization unit is not empty")
    await db.delete(unit)
    state.revision += 1
    await record_audit(
        db,
        context.membership,
        action="organization.unit.delete",
        resource_type="organization_unit",
        resource_id=str(unit.id),
    )
    await db.commit()


@router.post(
    "/positions",
    response_model=OrganizationStructureResponse,
    status_code=201,
)
async def create_position(
    payload: OrganizationPositionCreate,
    db: DbSession,
    context: OrganizationAdminContext,
) -> OrganizationStructureResponse:
    state = await locked_state(db, context.organization_id, payload.expected_revision)
    unit = await scoped_unit(db, context.organization_id, payload.unit_id)
    if not unit.is_active:
        raise HTTPException(status_code=409, detail="Organization unit is inactive")
    position = OrganizationPosition(
        organization_id=context.organization_id,
        unit_id=unit.id,
        title=payload.title,
        level=payload.level,
        sort_order=payload.sort_order,
        is_active=True,
    )
    db.add(position)
    await db.flush()
    state.revision += 1
    await record_audit(
        db,
        context.membership,
        action="organization.position.create",
        resource_type="organization_position",
        resource_id=str(position.id),
        details={"title": position.title, "unit_id": position.unit_id},
    )
    await db.commit()
    return await structure_snapshot(db, context.organization_id)


@router.patch("/positions/{position_id}", response_model=OrganizationStructureResponse)
async def update_position(
    position_id: int,
    payload: OrganizationPositionUpdate,
    db: DbSession,
    context: OrganizationAdminContext,
) -> OrganizationStructureResponse:
    state = await locked_state(db, context.organization_id, payload.expected_revision)
    position = await scoped_position(db, context.organization_id, position_id)
    changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    if "unit_id" in changes:
        unit = await scoped_unit(db, context.organization_id, changes["unit_id"])
        if not unit.is_active:
            raise HTTPException(status_code=409, detail="Organization unit is inactive")
        used = await db.scalar(
            select(OrganizationPlacement.membership_id).where(
                OrganizationPlacement.organization_id == context.organization_id,
                OrganizationPlacement.position_id == position.id,
            )
        )
        if used is not None and changes["unit_id"] != position.unit_id:
            raise HTTPException(status_code=409, detail="Position still has members")
    before = {name: getattr(position, name) for name in changes}
    for name, value in changes.items():
        setattr(position, name, value)
    state.revision += 1
    await record_audit(
        db,
        context.membership,
        action="organization.position.update",
        resource_type="organization_position",
        resource_id=str(position.id),
        details={"before": before, "after": changes},
    )
    await db.commit()
    return await structure_snapshot(db, context.organization_id)


@router.delete("/positions/{position_id}", status_code=204, response_model=None)
async def delete_position(
    position_id: int,
    payload: RevisionRequest,
    db: DbSession,
    context: OrganizationAdminContext,
) -> None:
    state = await locked_state(db, context.organization_id, payload.expected_revision)
    position = await scoped_position(db, context.organization_id, position_id)
    used = await db.scalar(
        select(OrganizationPlacement.membership_id).where(
            OrganizationPlacement.organization_id == context.organization_id,
            OrganizationPlacement.position_id == position.id,
        )
    )
    if used is not None:
        raise HTTPException(status_code=409, detail="Position still has members")
    await db.delete(position)
    state.revision += 1
    await record_audit(
        db,
        context.membership,
        action="organization.position.delete",
        resource_type="organization_position",
        resource_id=str(position.id),
    )
    await db.commit()


@router.put(
    "/placements/{membership_id}",
    response_model=OrganizationStructureResponse,
)
async def update_placement(
    membership_id: int,
    payload: OrganizationPlacementUpdate,
    db: DbSession,
    context: OrganizationAdminContext,
) -> OrganizationStructureResponse:
    state = await locked_state(db, context.organization_id, payload.expected_revision)
    item = OrganizationPlacementInput(
        membership_id=membership_id,
        unit_id=payload.unit_id,
        position_id=payload.position_id,
        manager_membership_id=payload.manager_membership_id,
    )
    await apply_placement_batch(db, context, state, [item])
    await record_audit(
        db,
        context.membership,
        action="organization.placement.update",
        resource_type="organization_placement",
        resource_id=str(membership_id),
        details=item.model_dump(),
    )
    await db.commit()
    return await structure_snapshot(db, context.organization_id)


@router.post(
    "/placements/batch",
    response_model=OrganizationStructureResponse,
)
async def update_placements_batch(
    payload: OrganizationPlacementBatch,
    db: DbSession,
    context: OrganizationAdminContext,
) -> OrganizationStructureResponse:
    state = await locked_state(db, context.organization_id, payload.expected_revision)
    await apply_placement_batch(db, context, state, payload.items)
    await record_audit(
        db,
        context.membership,
        action="organization.placement.batch",
        resource_type="organization_placement",
        details={"membership_ids": [item.membership_id for item in payload.items]},
    )
    await db.commit()
    return await structure_snapshot(db, context.organization_id)
