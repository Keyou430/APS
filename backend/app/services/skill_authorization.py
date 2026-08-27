"""Skill grant/promotion 授权（D8）：grant 是 catalog 可见性的唯一跨 owner 通道。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrganizationMembership, Skill, SkillAccessGrant


def active_grant_expression(*, now: datetime | None = None) -> object:
    now = now or datetime.now(UTC)
    return (SkillAccessGrant.revoked_at.is_(None)) & (
        (SkillAccessGrant.expires_at.is_(None)) | (SkillAccessGrant.expires_at > now)
    )


async def skill_readable_by(
    db: AsyncSession,
    skill: Skill,
    *,
    organization_id: int,
    user_id: int,
    now: datetime | None = None,
) -> bool:
    if skill.organization_id != organization_id:
        return False
    if skill.user_id == user_id:
        return True
    active_membership = (
        await db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.is_active.is_(True),
            )
        )
    ) is not None
    if not active_membership:
        return False
    if skill.is_promoted and skill.status != "archived":
        return True
    grant = await db.scalar(
        select(SkillAccessGrant.id).where(
            SkillAccessGrant.skill_id == skill.id,
            SkillAccessGrant.grantee_user_id == user_id,
            SkillAccessGrant.organization_id == organization_id,
            active_grant_expression(now=now),
        )
    )
    return grant is not None


def shared_with_me_expression(*, user_id: int, now: datetime | None = None):
    now = now or datetime.now(UTC)
    return exists().where(
        SkillAccessGrant.skill_id == Skill.id,
        SkillAccessGrant.organization_id == Skill.organization_id,
        SkillAccessGrant.grantee_user_id == user_id,
        SkillAccessGrant.revoked_at.is_(None),
        (SkillAccessGrant.expires_at.is_(None)) | (SkillAccessGrant.expires_at > now),
    )
