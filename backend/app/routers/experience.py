from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, OrganizationContext, require_permission
from app.database import get_db
from app.models import ExperienceDomain, ExperienceMethod
from app.schemas.experience import (
    ExperienceDomainCreate,
    ExperienceDomainListResponse,
    ExperienceDomainResponse,
    ExperienceDomainUpdate,
    ExperienceMethodCreate,
    ExperienceMethodListResponse,
    ExperienceMethodResponse,
    ExperienceMethodUpdate,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/api/experience", tags=["Experience Methods"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadContext = Annotated[OrganizationContext, Depends(require_permission("experience:read"))]
WriteContext = Annotated[OrganizationContext, Depends(require_permission("experience:write"))]


async def owned_domain(db: AsyncSession, domain_id: int, organization_id: int) -> ExperienceDomain:
    domain = await db.scalar(
        select(ExperienceDomain).where(
            ExperienceDomain.id == domain_id,
            ExperienceDomain.organization_id == organization_id,
        )
    )
    if domain is None:
        raise HTTPException(status_code=404, detail="Experience domain not found")
    return domain


async def owned_method(db: AsyncSession, method_id: int, organization_id: int) -> ExperienceMethod:
    method = await db.scalar(
        select(ExperienceMethod).where(
            ExperienceMethod.id == method_id,
            ExperienceMethod.organization_id == organization_id,
        )
    )
    if method is None:
        raise HTTPException(status_code=404, detail="Experience method not found")
    return method


@router.get("/domains", response_model=ExperienceDomainListResponse)
async def list_domains(db: DbSession, context: ReadContext) -> ExperienceDomainListResponse:
    rows = await db.execute(
        select(ExperienceDomain, func.count(ExperienceMethod.id))
        .outerjoin(
            ExperienceMethod,
            (ExperienceMethod.domain_id == ExperienceDomain.id)
            & (ExperienceMethod.organization_id == ExperienceDomain.organization_id),
        )
        .where(ExperienceDomain.organization_id == context.organization_id)
        .group_by(ExperienceDomain.id)
        .order_by(ExperienceDomain.name, ExperienceDomain.id)
    )
    return ExperienceDomainListResponse(
        items=[
            ExperienceDomainResponse.model_validate(
                {**domain.__dict__, "method_count": count}
            )
            for domain, count in rows.all()
        ]
    )


@router.post("/domains", response_model=ExperienceDomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    payload: ExperienceDomainCreate,
    db: DbSession,
    user: CurrentUser,
    context: WriteContext,
) -> ExperienceDomainResponse:
    existing = await db.scalar(
        select(ExperienceDomain).where(
            ExperienceDomain.organization_id == context.organization_id,
            ExperienceDomain.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Experience domain already exists")
    domain = ExperienceDomain(
        organization_id=context.organization_id,
        name=payload.name,
        description=payload.description,
    )
    db.add(domain)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)
        message = str(exc.orig).lower()
        if constraint == "uq_experience_domains_org_name" or (
            "unique" in message and "experience_domains" in message
        ):
            raise HTTPException(status_code=409, detail="Experience domain already exists") from exc
        raise
    await record_audit(db, context.membership, action="experience.domain.create", resource_type="experience_domain", resource_id=str(domain.id))
    await db.commit()
    await db.refresh(domain)
    return ExperienceDomainResponse.model_validate({**domain.__dict__, "method_count": 0})


@router.patch("/domains/{domain_id}", response_model=ExperienceDomainResponse)
async def update_domain(
    domain_id: int,
    payload: ExperienceDomainUpdate,
    db: DbSession,
    context: WriteContext,
) -> ExperienceDomainResponse:
    domain = await owned_domain(db, domain_id, context.organization_id)
    if payload.name is not None and payload.name != domain.name:
        duplicate = await db.scalar(
            select(ExperienceDomain).where(
                ExperienceDomain.organization_id == context.organization_id,
                ExperienceDomain.name == payload.name,
                ExperienceDomain.id != domain_id,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Experience domain already exists")
        domain.name = payload.name
    if payload.description is not None:
        domain.description = payload.description
    await record_audit(
        db,
        context.membership,
        action="experience.domain.update",
        resource_type="experience_domain",
        resource_id=str(domain.id),
    )
    await db.commit()
    await db.refresh(domain)
    count = await db.scalar(
        select(func.count())
        .select_from(ExperienceMethod)
        .where(
            ExperienceMethod.domain_id == domain.id,
            ExperienceMethod.organization_id == context.organization_id,
        )
    )
    return ExperienceDomainResponse.model_validate({**domain.__dict__, "method_count": count or 0})


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(domain_id: int, db: DbSession, context: WriteContext) -> None:
    domain = await owned_domain(db, domain_id, context.organization_id)
    count = await db.scalar(
        select(func.count())
        .select_from(ExperienceMethod)
        .where(
            ExperienceMethod.domain_id == domain.id,
            ExperienceMethod.organization_id == context.organization_id,
        )
    )
    if count:
        raise HTTPException(status_code=409, detail="Experience domain is not empty")
    await record_audit(
        db,
        context.membership,
        action="experience.domain.delete",
        resource_type="experience_domain",
        resource_id=str(domain.id),
    )
    await db.delete(domain)
    await db.commit()


@router.get("/domains/{domain_id}/methods", response_model=ExperienceMethodListResponse)
async def list_methods(domain_id: int, db: DbSession, context: ReadContext) -> ExperienceMethodListResponse:
    await owned_domain(db, domain_id, context.organization_id)
    methods = list(
        (
            await db.scalars(
                select(ExperienceMethod)
                .where(
                    ExperienceMethod.domain_id == domain_id,
                    ExperienceMethod.organization_id == context.organization_id,
                )
                .order_by(ExperienceMethod.updated_at.desc(), ExperienceMethod.id.desc())
            )
        ).all()
    )
    return ExperienceMethodListResponse(items=[ExperienceMethodResponse.model_validate(item) for item in methods])


@router.post("/domains/{domain_id}/methods", response_model=ExperienceMethodResponse, status_code=status.HTTP_201_CREATED)
async def create_method(
    domain_id: int,
    payload: ExperienceMethodCreate,
    db: DbSession,
    user: CurrentUser,
    context: WriteContext,
) -> ExperienceMethodResponse:
    await owned_domain(db, domain_id, context.organization_id)
    method = ExperienceMethod(
        organization_id=context.organization_id,
        domain_id=domain_id,
        title=payload.title,
        content=payload.content,
        source_type=payload.source_type,
        source_reference=payload.source_reference,
        created_by_user_id=user.id,
    )
    db.add(method)
    await db.flush()
    await record_audit(db, context.membership, action="experience.method.create", resource_type="experience_method", resource_id=str(method.id))
    await db.commit()
    await db.refresh(method)
    return ExperienceMethodResponse.model_validate(method)


@router.patch("/methods/{method_id}", response_model=ExperienceMethodResponse)
async def update_method(
    method_id: int,
    payload: ExperienceMethodUpdate,
    db: DbSession,
    context: WriteContext,
) -> ExperienceMethodResponse:
    method = await owned_method(db, method_id, context.organization_id)
    for field in ("title", "content", "source_type", "source_reference"):
        value = getattr(payload, field)
        if value is not None:
            setattr(method, field, value)
    await record_audit(
        db,
        context.membership,
        action="experience.method.update",
        resource_type="experience_method",
        resource_id=str(method.id),
    )
    await db.commit()
    await db.refresh(method)
    return ExperienceMethodResponse.model_validate(method)


@router.delete("/methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_method(method_id: int, db: DbSession, context: WriteContext) -> None:
    method = await owned_method(db, method_id, context.organization_id)
    await record_audit(
        db,
        context.membership,
        action="experience.method.delete",
        resource_type="experience_method",
        resource_id=str(method.id),
    )
    await db.delete(method)
    await db.commit()
