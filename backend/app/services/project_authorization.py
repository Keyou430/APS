"""Project 可见性授权（D7）：visibility + roster 判定，不授予底层资源访问。"""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectMember


def roster_managed_by(project: Project, user_id: int, *, has_manage: bool) -> bool:
    return project.owner_user_id == user_id or has_manage


async def project_visible_to(
    db: AsyncSession,
    project: Project,
    *,
    organization_id: int,
    user_id: int,
) -> bool:
    if project.organization_id != organization_id:
        return False
    if project.visibility == "public":
        return True
    if project.owner_user_id == user_id:
        return True
    member = await db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.organization_id == organization_id,
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
        )
    )
    return member is not None


def visible_projects_filter_expression(*, organization_id: int, user_id: int):
    del organization_id
    member_exists = exists().where(
        ProjectMember.project_id == Project.id,
        ProjectMember.organization_id == Project.organization_id,
        ProjectMember.user_id == user_id,
    )
    return (Project.visibility == "public") | (Project.owner_user_id == user_id) | member_exists
