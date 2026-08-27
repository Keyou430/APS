from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrganizationMembership

from app.auth.dependencies import CurrentUser, OrganizationContext, require_permission
from app.database import get_db
from app.models import Skill, SkillAccessGrant, SkillVersion
from app.schemas.skills import (
    GeneratedSkillResponse,
    HubSkill,
    HubSkillListResponse,
    SkillCategory,
    SkillCreate,
    SkillGenerateRequest,
    SkillGrantCreate,
    SkillGrantListResponse,
    SkillGrantResponse,
    SkillListResponse,
    SkillResponse,
    SkillUpdate,
    SkillVersionListResponse,
)
from app.services.skill_authorization import (
    shared_with_me_expression,
    skill_readable_by,
)
from app.services.skill_generator import generate_skill
from app.services.skill_repository import (
    SkillNotFoundError,
    SkillRevisionConflictError,
    SkillStatusTransitionError,
    create_skill_record,
    get_owned_skill,
    list_skill_catalog,
    list_skill_versions,
    transition_skill_status,
    update_skill_with_cas,
)

router = APIRouter(prefix="/api/skills", tags=["Skills"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
SkillReadContext = Annotated[
    OrganizationContext, Depends(require_permission("skills:read"))
]
SkillWriteContext = Annotated[
    OrganizationContext, Depends(require_permission("skills:write"))
]
SkillReviewContext = Annotated[
    OrganizationContext, Depends(require_permission("skills:review"))
]
SkillPublishContext = Annotated[
    OrganizationContext, Depends(require_permission("skills:publish"))
]
SkillShareContext = Annotated[
    OrganizationContext, Depends(require_permission("skills:share"))
]
SkillGovernContext = Annotated[
    OrganizationContext, Depends(require_permission("skills:govern"))
]


async def owned_skill(
    db: AsyncSession, skill_id: int, user_id: int, organization_id: int, *, for_update: bool = False
) -> Skill:
    try:
        return await get_owned_skill(
            db,
            skill_id,
            organization_id=organization_id,
            user_id=user_id,
            for_update=for_update,
        )
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail="Skill not found") from None


@router.get("", response_model=SkillListResponse, summary="List current user's skills")
async def list_skills(
    db: DbSession,
    user: CurrentUser,
    context: SkillReadContext,
    category: Annotated[SkillCategory | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> SkillListResponse:
    items = await list_skill_catalog(
        db,
        organization_id=context.organization_id,
        user_id=user.id,
        category=category,
        include_archived=include_archived,
    )
    return SkillListResponse(items=items)


@router.get(
    "/shared-with-me",
    response_model=SkillListResponse,
    summary="List skills shared with the current user",
)
async def shared_with_me(
    db: DbSession,
    user: CurrentUser,
    context: SkillReadContext,
) -> SkillListResponse:
    items = list(
        (
            await db.scalars(
                select(Skill)
                .where(
                    Skill.organization_id == context.organization_id,
                    shared_with_me_expression(user_id=user.id),
                )
                .order_by(Skill.id)
            )
        ).all()
    )
    return SkillListResponse(items=items)


@router.get(
    "/discoverable",
    response_model=SkillListResponse,
    summary="List organization-discoverable promoted skills",
)
async def discoverable_skills(
    db: DbSession,
    _user: CurrentUser,
    context: SkillReadContext,
) -> SkillListResponse:
    items = list(
        (
            await db.scalars(
                select(Skill)
                .where(
                    Skill.organization_id == context.organization_id,
                    Skill.is_promoted.is_(True),
                    Skill.status != "archived",
                )
                .order_by(Skill.id)
            )
        ).all()
    )
    return SkillListResponse(items=items)


@router.get("/hub", response_model=HubSkillListResponse, summary="Browse mock Hermes Skills Hub")
async def skills_hub(_user: CurrentUser, _context: SkillReadContext) -> HubSkillListResponse:
    return HubSkillListResponse(
        items=[
            HubSkill(
                slug="meeting-summary",
                name="Meeting Summary",
                description="Turn meeting notes into decisions and actions.",
                category="general",
            ),
            HubSkill(
                slug="sales-report",
                name="Sales Report",
                description="Draft a structured monthly sales report.",
                category="role-specific",
            ),
        ]
    )


@router.post(
    "/generate",
    response_model=GeneratedSkillResponse,
    summary="Generate mock SKILL.md content",
)
async def generate(
    payload: SkillGenerateRequest,
    _user: CurrentUser,
    _context: SkillWriteContext,
) -> GeneratedSkillResponse:
    name, content = generate_skill(payload.description)
    return GeneratedSkillResponse(name=name, generated_skill=content)


@router.post("", response_model=SkillResponse, status_code=201, summary="Create a skill")
async def create_skill(
    payload: SkillCreate,
    db: DbSession,
    user: CurrentUser,
    context: SkillWriteContext,
) -> Skill:
    skill = await create_skill_record(
        db,
        organization_id=context.organization_id,
        user_id=user.id,
        name=payload.name,
        category=payload.category,
        content=payload.content,
        is_ai_generated=payload.category == "ai-generated",
    )
    await db.commit()
    await db.refresh(skill)
    return skill


@router.get("/{skill_id}", response_model=SkillResponse, summary="Get skill detail")
async def get_skill(
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillReadContext,
) -> Skill:
    skill = await db.scalar(
        select(Skill).where(
            Skill.id == skill_id,
            Skill.organization_id == context.organization_id,
        )
    )
    if skill is None or not await skill_readable_by(
        db,
        skill,
        organization_id=context.organization_id,
        user_id=user.id,
    ):
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.put("/{skill_id}", response_model=SkillResponse, summary="Update a skill")
async def update_skill(
    payload: SkillUpdate,
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillWriteContext,
) -> Skill:
    skill = await owned_skill(
        db, skill_id, user.id, context.organization_id, for_update=True
    )
    try:
        await update_skill_with_cas(
            db,
            skill,
            expected_revision=payload.expected_revision,
            name=payload.name,
            category=payload.category,
            content=payload.content,
        )
    except SkillRevisionConflictError:
        raise HTTPException(status_code=409, detail="Skill revision conflict") from None
    await db.commit()
    await db.refresh(skill)
    return skill


@router.get(
    "/{skill_id}/versions",
    response_model=SkillVersionListResponse,
    summary="List immutable versions of a skill",
)
async def skill_versions(
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillReadContext,
) -> SkillVersionListResponse:
    await owned_skill(db, skill_id, user.id, context.organization_id)
    items = await list_skill_versions(
        db,
        skill_id,
        organization_id=context.organization_id,
        user_id=user.id,
    )
    return SkillVersionListResponse(items=items)


@router.post(
    "/{skill_id}/review",
    response_model=SkillResponse,
    summary="Review a draft skill (requires skills:review)",
)
async def review_skill(
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillReviewContext,
) -> Skill:
    skill = await owned_skill(db, skill_id, user.id, context.organization_id, for_update=True)
    try:
        await transition_skill_status(db, skill, target="reviewed")
    except SkillStatusTransitionError:
        raise HTTPException(status_code=409, detail="Invalid skill status transition") from None
    await db.commit()
    await db.refresh(skill)
    return skill


@router.post(
    "/{skill_id}/publish",
    response_model=SkillResponse,
    summary="Publish a reviewed skill (requires skills:publish)",
)
async def publish_skill(
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillPublishContext,
) -> Skill:
    skill = await owned_skill(db, skill_id, user.id, context.organization_id, for_update=True)
    try:
        await transition_skill_status(db, skill, target="published")
    except SkillStatusTransitionError:
        raise HTTPException(status_code=409, detail="Only reviewed skills can be published") from None
    await db.commit()
    await db.refresh(skill)
    return skill


@router.post(
    "/{skill_id}/archive",
    response_model=SkillResponse,
    summary="Archive a skill (owner-only)",
)
async def archive_skill(
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillWriteContext,
) -> Skill:
    skill = await owned_skill(db, skill_id, user.id, context.organization_id, for_update=True)
    try:
        await transition_skill_status(db, skill, target="archived")
    except SkillStatusTransitionError:
        raise HTTPException(status_code=409, detail="Invalid skill status transition") from None
    await db.commit()
    await db.refresh(skill)
    return skill


@router.post(
    "/{skill_id}/grants",
    response_model=SkillGrantResponse,
    status_code=201,
    summary="Grant read access to an organization member (owner + skills:share)",
)
async def grant_skill(
    payload: SkillGrantCreate,
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillShareContext,
) -> SkillAccessGrant:
    await owned_skill(db, skill_id, user.id, context.organization_id, for_update=True)
    membership = await db.scalar(
        select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == context.organization_id,
            OrganizationMembership.user_id == payload.grantee_user_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=404, detail="Grantee is not an active organization member"
        )
    existing = await db.scalar(
        select(SkillAccessGrant).where(
            SkillAccessGrant.skill_id == skill_id,
            SkillAccessGrant.grantee_user_id == payload.grantee_user_id,
            SkillAccessGrant.organization_id == context.organization_id,
            SkillAccessGrant.revoked_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Active grant already exists")
    grant = SkillAccessGrant(
        organization_id=context.organization_id,
        skill_id=skill_id,
        grantor_user_id=user.id,
        grantee_user_id=payload.grantee_user_id,
        capability="read",
        expires_at=payload.expires_at,
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    return grant


@router.get(
    "/{skill_id}/grants",
    response_model=SkillGrantListResponse,
    summary="List grants for an owned skill (owner + skills:share)",
)
async def list_grants(
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillShareContext,
) -> SkillGrantListResponse:
    await owned_skill(db, skill_id, user.id, context.organization_id)
    items = list(
        (
            await db.scalars(
                select(SkillAccessGrant)
                .where(
                    SkillAccessGrant.skill_id == skill_id,
                    SkillAccessGrant.organization_id == context.organization_id,
                )
                .order_by(SkillAccessGrant.id)
            )
        ).all()
    )
    return SkillGrantListResponse(items=items)


@router.delete(
    "/{skill_id}/grants/{grant_id}",
    status_code=204,
    summary="Revoke a grant (owner + skills:share)",
)
async def revoke_grant(
    skill_id: int,
    grant_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillShareContext,
) -> None:
    await owned_skill(db, skill_id, user.id, context.organization_id, for_update=True)
    grant = await db.scalar(
        select(SkillAccessGrant).where(
            SkillAccessGrant.id == grant_id,
            SkillAccessGrant.skill_id == skill_id,
            SkillAccessGrant.organization_id == context.organization_id,
        )
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    grant.revoked_at = datetime.now(UTC)
    grant.revoked_by_user_id = user.id
    await db.commit()


@router.post(
    "/{skill_id}/promote",
    response_model=SkillResponse,
    summary="Promote a reviewed skill for organization discovery (skills:govern)",
)
async def promote_skill(
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillGovernContext,
) -> Skill:
    skill = await db.scalar(
        select(Skill).where(
            Skill.id == skill_id,
            Skill.organization_id == context.organization_id,
        )
    )
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.status not in ("reviewed", "published"):
        raise HTTPException(status_code=409, detail="Only reviewed skills can be promoted")
    if not skill.is_promoted:
        skill.is_promoted = True
        skill.promoted_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(skill)
    return skill


@router.delete("/{skill_id}", status_code=204, summary="Delete a skill")
async def delete_skill(
    skill_id: int,
    db: DbSession,
    user: CurrentUser,
    context: SkillWriteContext,
) -> None:
    skill = await owned_skill(db, skill_id, user.id, context.organization_id)
    await db.execute(delete(SkillVersion).where(SkillVersion.skill_id == skill_id))
    await db.delete(skill)
    await db.commit()
