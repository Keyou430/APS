"""Project scope API（D7）：visibility + roster CAS + placement-only resource links。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    CurrentUser,
    OrganizationContext,
    has_permission,
    require_permission,
)
from app.database import get_db
from app.models import OrganizationMembership, Project, ProjectMember, ProjectResourceLink
from app.schemas.projects import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
    ResourceLinkCreate,
    ResourceLinkListResponse,
    ResourceLinkResponse,
    RosterResponse,
    RosterUpdate,
)
from app.services.project_authorization import (
    project_visible_to,
    roster_managed_by,
    visible_projects_filter_expression,
)

router = APIRouter(prefix="/api/projects", tags=["Projects"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ProjectReadContext = Annotated[
    OrganizationContext, Depends(require_permission("projects:read"))
]
ProjectWriteContext = Annotated[
    OrganizationContext, Depends(require_permission("projects:write"))
]


async def visible_project(
    db: AsyncSession,
    project_id: int,
    *,
    organization_id: int,
    user_id: int,
    for_update: bool = False,
) -> Project:
    statement = select(Project).where(
        Project.id == project_id,
        Project.organization_id == organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    project = await db.scalar(statement)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await project_visible_to(
        db, project, organization_id=organization_id, user_id=user_id
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("", response_model=ProjectListResponse, summary="List visible projects")
async def list_projects(
    db: DbSession,
    user: CurrentUser,
    context: ProjectReadContext,
) -> ProjectListResponse:
    items = list(
        (
            await db.scalars(
                select(Project)
                .where(
                    Project.organization_id == context.organization_id,
                    visible_projects_filter_expression(
                        organization_id=context.organization_id, user_id=user.id
                    ),
                )
                .order_by(Project.id)
            )
        ).all()
    )
    return ProjectListResponse(items=items)


@router.post("", response_model=ProjectResponse, status_code=201, summary="Create a project")
async def create_project(
    payload: ProjectCreate,
    db: DbSession,
    user: CurrentUser,
    context: ProjectWriteContext,
) -> Project:
    project = Project(
        organization_id=context.organization_id,
        owner_user_id=user.id,
        name=payload.name,
        description=payload.description,
        visibility=payload.visibility,
        roster_revision=1,
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectMember(
            organization_id=context.organization_id,
            project_id=project.id,
            user_id=user.id,
            role="admin",
        )
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get project detail")
async def get_project(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ProjectReadContext,
) -> Project:
    return await visible_project(
        db,
        project_id,
        organization_id=context.organization_id,
        user_id=user.id,
    )


@router.put("/{project_id}", response_model=ProjectResponse, summary="Update a project (owner)")
async def update_project(
    payload: ProjectUpdate,
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ProjectWriteContext,
) -> Project:
    project = await visible_project(
        db,
        project_id,
        organization_id=context.organization_id,
        user_id=user.id,
        for_update=True,
    )
    if project.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.visibility is not None:
        project.visibility = payload.visibility
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204, summary="Delete a project (owner)")
async def delete_project(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ProjectWriteContext,
) -> None:
    project = await visible_project(
        db,
        project_id,
        organization_id=context.organization_id,
        user_id=user.id,
        for_update=True,
    )
    if project.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.execute(
        delete(ProjectMember).where(ProjectMember.project_id == project_id)
    )
    await db.execute(
        delete(ProjectResourceLink).where(ProjectResourceLink.project_id == project_id)
    )
    await db.delete(project)
    await db.commit()


@router.put(
    "/{project_id}/roster",
    response_model=RosterResponse,
    summary="Update roster with CAS (owner or projects:manage)",
)
async def update_roster(
    payload: RosterUpdate,
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ProjectWriteContext,
) -> RosterResponse:
    project = await visible_project(
        db,
        project_id,
        organization_id=context.organization_id,
        user_id=user.id,
        for_update=True,
    )
    if not roster_managed_by(
        project,
        user.id,
        has_manage=has_permission(context.membership, "projects:manage"),
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    if project.roster_revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Project revision conflict")
    for member_id in payload.add:
        membership = await db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.organization_id == context.organization_id,
                OrganizationMembership.user_id == member_id,
                OrganizationMembership.is_active.is_(True),
            )
        )
        if membership is None:
            raise HTTPException(
                status_code=404, detail="Roster member not found in organization"
            )
    if payload.remove:
        await db.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id.in_(payload.remove),
            )
        )
    existing_ids = set(
        (
            await db.scalars(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
            )
        ).all()
    )
    for member_id in payload.add:
        if member_id not in existing_ids:
            db.add(
                ProjectMember(
                    organization_id=context.organization_id,
                    project_id=project_id,
                    user_id=member_id,
                    role="member",
                )
            )
    project.roster_revision += 1
    member_ids = sorted(
        (
            await db.scalars(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
            )
        ).all()
    )
    await db.commit()
    return RosterResponse(roster_revision=project.roster_revision, member_ids=member_ids)


@router.post(
    "/{project_id}/resources",
    response_model=ResourceLinkResponse,
    status_code=201,
    summary="Link a resource to a project (placement only, owner/manage)",
)
async def link_resource(
    payload: ResourceLinkCreate,
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ProjectWriteContext,
) -> ResourceLinkResponse:
    project = await visible_project(
        db,
        project_id,
        organization_id=context.organization_id,
        user_id=user.id,
        for_update=True,
    )
    if not roster_managed_by(
        project,
        user.id,
        has_manage=has_permission(context.membership, "projects:manage"),
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    existing = await db.scalar(
        select(ProjectResourceLink).where(
            ProjectResourceLink.project_id == project_id,
            ProjectResourceLink.resource_type == payload.resource_type,
            ProjectResourceLink.ref_id == payload.ref_id,
        )
    )
    if existing is not None:
        existing.ord = payload.ord
        await db.commit()
        await db.refresh(existing)
        return existing
    link = ProjectResourceLink(
        organization_id=context.organization_id,
        project_id=project_id,
        resource_type=payload.resource_type,
        ref_id=payload.ref_id,
        ord=payload.ord,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


@router.get(
    "/{project_id}/resources",
    response_model=ResourceLinkListResponse,
    summary="List project resource placements",
)
async def list_resources(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    context: ProjectReadContext,
) -> ResourceLinkListResponse:
    await visible_project(
        db,
        project_id,
        organization_id=context.organization_id,
        user_id=user.id,
    )
    items = list(
        (
            await db.scalars(
                select(ProjectResourceLink)
                .where(
                    ProjectResourceLink.project_id == project_id,
                    ProjectResourceLink.organization_id == context.organization_id,
                )
                .order_by(ProjectResourceLink.ord, ProjectResourceLink.id)
            )
        ).all()
    )
    return ResourceLinkListResponse(items=items)
