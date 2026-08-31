from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, require_permission
from app.auth.security import hash_password
from app.config import get_settings
from app.database import get_db
from app.models import OrganizationMembership, Role, User
from app.schemas.auth import UserResponse
from app.schemas.users import RoleAssignment, UserCreate, UserListResponse, UserUpdate
from app.services.audit import record_audit
from app.services.hermes_manager import profile_manager
from app.services.organization_structure import ensure_organization_structure

router = APIRouter(prefix="/api/users", tags=["Users"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
UsersReadContext = Annotated[OrganizationContext, Depends(require_permission("users:read"))]
OrgAdminContext = Annotated[OrganizationContext, Depends(require_permission("org:admin"))]


def user_response(user: User, membership: OrganizationMembership, role: Role) -> UserResponse:
    return UserResponse.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "role": role.name,
            "member_type": membership.member_type,
            "membership_id": membership.id,
            "membership_expires_at": membership.expires_at,
            "organization_id": membership.organization_id,
            "is_active": user.is_active,
            "created_at": user.created_at,
        }
    )


async def get_user_membership_or_404(
    db: AsyncSession,
    user_id: int,
    organization_id: int,
    *,
    for_update: bool = False,
) -> tuple[User, OrganizationMembership, Role]:
    statement = (
        select(User, OrganizationMembership, Role)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .join(Role, Role.id == OrganizationMembership.role_id)
        .where(
            User.id == user_id,
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    if for_update:
        statement = statement.with_for_update(of=(User, OrganizationMembership, Role))
    row = (await db.execute(statement)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return row


async def guard_last_admin(
    db: AsyncSession,
    membership: OrganizationMembership,
    role: Role,
) -> None:
    if role.name != "admin":
        return
    now = datetime.now(UTC)
    rows = list(
        (
            await db.scalars(
                select(OrganizationMembership.id)
                .join(Role, Role.id == OrganizationMembership.role_id)
                .join(User, User.id == OrganizationMembership.user_id)
                .where(
                    OrganizationMembership.organization_id == membership.organization_id,
                    OrganizationMembership.is_active.is_(True),
                    or_(
                        OrganizationMembership.expires_at.is_(None),
                        OrganizationMembership.expires_at > now,
                    ),
                    Role.name == "admin",
                    User.is_active.is_(True),
                )
                .with_for_update()
            )
        ).all()
    )
    if len(rows) <= 1:
        raise HTTPException(
            status_code=409,
            detail="Organization must retain an active administrator",
        )


@router.get("", response_model=UserListResponse, summary="List platform users")
async def list_users(
    db: DbSession,
    context: UsersReadContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    role: str | None = None,
    sort_by: Literal["username", "email", "created_at"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
) -> UserListResponse:
    predicates = [
        OrganizationMembership.organization_id == context.organization_id,
        OrganizationMembership.is_active.is_(True),
    ]
    query = (
        select(User, OrganizationMembership, Role)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .join(Role, Role.id == OrganizationMembership.role_id)
        .where(*predicates)
    )
    count_query = (
        select(func.count(User.id))
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .join(Role, Role.id == OrganizationMembership.role_id)
        .where(*predicates)
    )
    if search:
        predicate = or_(User.username.ilike(f"%{search}%"), User.email.ilike(f"%{search}%"))
        query = query.where(predicate)
        count_query = count_query.where(predicate)
    if role:
        query = query.where(Role.name == role)
        count_query = count_query.where(Role.name == role)
    sort_column = getattr(User, sort_by)
    query = query.order_by((asc if sort_order == "asc" else desc)(sort_column))
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).all()
    total = int((await db.scalar(count_query)) or 0)
    return UserListResponse(
        items=[user_response(user, membership, membership_role) for user, membership, membership_role in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=UserResponse, status_code=201, summary="Create a platform user")
async def create_user(
    payload: UserCreate, db: DbSession, admin: OrgAdminContext
) -> UserResponse:
    if get_settings().single_user_mode:
        raise HTTPException(
            status_code=409,
            detail="Single-user mode only allows the admin account",
        )
    role = await db.scalar(select(Role).where(Role.name == payload.role))
    if role is None:
        raise HTTPException(status_code=400, detail="Unknown role")
    normalized_email = str(payload.email).strip().casefold()
    user = User(
        username=payload.username,
        display_name=payload.display_name.strip() if payload.display_name else None,
        email=str(payload.email),
        normalized_email=normalized_email,
        password_hash=hash_password(payload.password),
        role=role,
        default_organization_id=admin.organization_id,
    )
    db.add(user)
    try:
        await db.flush()
        membership = OrganizationMembership(
            organization_id=admin.organization_id,
            user_id=user.id,
            role_id=role.id,
            member_type="internal",
        )
        db.add(membership)
        await ensure_organization_structure(db, admin.organization_id)
        await profile_manager.reconcile(db, user, organization_id=admin.organization_id)
        await record_audit(
            db,
            admin.membership,
            action="user.create",
            resource_type="user",
            resource_id=str(user.id),
            details={"role": role.name},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username or email already exists") from None
    return user_response(user, membership, role)


@router.get("/{user_id}", response_model=UserResponse, summary="Get a user")
async def get_user(user_id: int, db: DbSession, context: UsersReadContext) -> UserResponse:
    user, membership, role = await get_user_membership_or_404(
        db, user_id, context.organization_id
    )
    return user_response(user, membership, role)


@router.put("/{user_id}", response_model=UserResponse, summary="Update a user")
async def update_user(
    payload: UserUpdate, user_id: int, db: DbSession, admin: OrgAdminContext
) -> UserResponse:
    user, membership, role = await get_user_membership_or_404(
        db, user_id, admin.organization_id, for_update=True
    )
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("is_active") is False:
        if user_id == admin.user_id:
            raise HTTPException(
                status_code=409,
                detail="Organization must retain an active administrator",
            )
        await guard_last_admin(db, membership, role)
    for name, value in changes.items():
        if name == "email" and value is not None:
            user.email = str(value)
            user.normalized_email = str(value).strip().casefold()
        elif name == "display_name":
            user.display_name = value.strip() if value and value.strip() else None
        else:
            setattr(user, name, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username or email already exists") from None
    return user_response(user, membership, role)


@router.delete("/{user_id}", status_code=204, summary="Soft-delete a user")
async def delete_user(user_id: int, db: DbSession, admin: OrgAdminContext) -> None:
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="Administrators cannot deactivate themselves")
    user, membership, role = await get_user_membership_or_404(
        db, user_id, admin.organization_id, for_update=True
    )
    await guard_last_admin(db, membership, role)
    user.is_active = False
    await record_audit(
        db,
        admin.membership,
        action="user.deactivate",
        resource_type="user",
        resource_id=str(user.id),
    )
    await db.commit()


@router.put("/{user_id}/roles", response_model=UserResponse, summary="Assign a role")
async def assign_role(
    payload: RoleAssignment, user_id: int, db: DbSession, admin: OrgAdminContext
) -> UserResponse:
    user, membership, current_role = await get_user_membership_or_404(
        db, user_id, admin.organization_id, for_update=True
    )
    role = await db.scalar(select(Role).where(Role.name == payload.role))
    if role is None:
        raise HTTPException(status_code=400, detail="Unknown role")
    if current_role.name == "admin" and role.name != "admin":
        await guard_last_admin(db, membership, current_role)
    membership.role_id = role.id
    membership.role = role
    await record_audit(
        db,
        admin.membership,
        action="user.role.assign",
        resource_type="user",
        resource_id=str(user.id),
        details={"role": role.name},
    )
    await db.commit()
    return user_response(user, membership, role)
