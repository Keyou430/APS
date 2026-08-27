from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, require_permission
from app.database import get_db
from app.models import HermesProfile, OrganizationMembership, User
from app.schemas.hermes import ProfileCreate, ProfileHealthResponse, ProfileResponse
from app.services.audit import record_audit
from app.services.hermes_manager import profile_manager

router = APIRouter(prefix="/api/hermes/profiles", tags=["Hermes Profiles"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
AgentAdminContext = Annotated[
    OrganizationContext, Depends(require_permission("agent:admin"))
]


async def find_profile(db: AsyncSession, user_id: int, organization_id: int) -> HermesProfile:
    profile = await db.scalar(
        select(HermesProfile).where(
            HermesProfile.user_id == user_id,
            HermesProfile.organization_id == organization_id,
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Hermes profile not found")
    return profile


@router.post(
    "",
    response_model=ProfileResponse,
    status_code=201,
    summary="Create isolated Hermes profile metadata",
    description=(
        "Creates one independent profile metadata record per user and reconciles the server-owned "
        "HTTP scope; it does not start a per-user Hermes process."
    ),
)
async def create_profile(
    payload: ProfileCreate, db: DbSession, admin: AgentAdminContext
) -> HermesProfile:
    user = await db.scalar(
        select(User)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(
            User.id == payload.user_id,
            OrganizationMembership.organization_id == admin.organization_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing = await db.scalar(
        select(HermesProfile).where(
            HermesProfile.user_id == user.id,
            HermesProfile.organization_id == admin.organization_id,
        )
    )
    profile = await profile_manager.reconcile(
        db, user, organization_id=admin.organization_id
    )
    if existing is None:
        await record_audit(
            db,
            admin.membership,
            action="hermes.profile.create",
            resource_type="hermes_profile",
            resource_id=str(profile.id),
        )
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{user_id}", response_model=ProfileResponse, summary="Get a user's profile")
async def get_profile(
    user_id: int, db: DbSession, admin: AgentAdminContext
) -> HermesProfile:
    return await find_profile(db, user_id, admin.organization_id)


@router.delete("/{user_id}", status_code=204, summary="Deactivate a user's profile")
async def deactivate_profile(
    user_id: int, db: DbSession, admin: AgentAdminContext
) -> None:
    profile = await find_profile(db, user_id, admin.organization_id)
    await profile_manager.deactivate(profile)
    await record_audit(
        db,
        admin.membership,
        action="hermes.profile.deactivate",
        resource_type="hermes_profile",
        resource_id=str(profile.id),
    )
    await db.commit()


@router.get(
    "/{user_id}/health", response_model=ProfileHealthResponse, summary="Check profile health"
)
async def profile_health(
    user_id: int, db: DbSession, admin: AgentAdminContext
) -> ProfileHealthResponse:
    profile = await find_profile(db, user_id, admin.organization_id)
    return ProfileHealthResponse(
        user_id=user_id,
        status=profile.status,
        healthy=profile.status != "error",
        detail="Server-owned profile scope check; Hermes runs through the private HTTP gateway",
    )
