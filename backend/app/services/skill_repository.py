"""Skill 生命周期 repository（D6：immutable version、review/publish/archive、CAS）。"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Skill, SkillVersion


class SkillNotFoundError(KeyError):
    pass


class SkillRevisionConflictError(RuntimeError):
    pass


class SkillStatusTransitionError(RuntimeError):
    pass


def skill_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _version_from_skill(record: Skill) -> SkillVersion:
    return SkillVersion(
        organization_id=record.organization_id,
        user_id=record.user_id,
        skill_id=record.id,
        version=record.current_version,
        revision=record.revision,
        name=record.name,
        category=record.category,
        content=record.content,
        content_hash=record.content_hash,
        is_ai_generated=record.is_ai_generated,
    )


async def get_owned_skill(
    db: AsyncSession,
    skill_id: int,
    *,
    organization_id: int,
    user_id: int,
    for_update: bool = False,
) -> Skill:
    statement = select(Skill).where(
        Skill.id == skill_id,
        Skill.organization_id == organization_id,
        Skill.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    record = await db.scalar(statement)
    if record is None:
        raise SkillNotFoundError(skill_id)
    return record


async def create_skill_record(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
    name: str,
    category: str,
    content: str,
    is_ai_generated: bool,
) -> Skill:
    record = Skill(
        organization_id=organization_id,
        user_id=user_id,
        name=name,
        category=category,
        content=content,
        is_ai_generated=is_ai_generated,
        status="draft",
        revision=1,
        current_version="v1",
        content_hash=skill_content_hash(content),
    )
    db.add(record)
    await db.flush()
    db.add(_version_from_skill(record))
    await db.flush()
    return record


async def update_skill_with_cas(
    db: AsyncSession,
    record: Skill,
    *,
    expected_revision: int,
    name: str | None,
    category: str | None,
    content: str | None,
) -> tuple[Skill, bool]:
    """CAS 更新；no-op（内容/名称/分类均未变）不追加版本、不递增 revision。"""
    if record.revision != expected_revision:
        raise SkillRevisionConflictError(record.id)
    new_name = name if name is not None else record.name
    new_category = category if category is not None else record.category
    new_content = content if content is not None else record.content
    if (
        new_name == record.name
        and new_category == record.category
        and new_content == record.content
    ):
        return record, False
    record.name = new_name
    record.category = new_category
    record.content = new_content
    record.is_ai_generated = new_category == "ai-generated"
    record.revision += 1
    record.current_version = f"v{record.revision}"
    record.content_hash = skill_content_hash(new_content)
    db.add(_version_from_skill(record))
    await db.flush()
    return record, True


async def transition_skill_status(
    db: AsyncSession,
    record: Skill,
    *,
    target: str,
) -> Skill:
    if record.status == target:
        return record
    allowed = {
        "reviewed": {"draft"},
        "published": {"reviewed"},
        "archived": {"draft", "reviewed", "published"},
    }
    if target not in allowed or record.status not in allowed[target]:
        raise SkillStatusTransitionError(record.id)
    record.status = target
    await db.flush()
    return record


async def list_skill_catalog(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
    category: str | None,
    include_archived: bool = False,
) -> list[Skill]:
    statement = select(Skill).where(
        Skill.organization_id == organization_id,
        Skill.user_id == user_id,
    )
    if not include_archived:
        statement = statement.where(Skill.status != "archived")
    if category:
        statement = statement.where(Skill.category == category)
    return list((await db.scalars(statement.order_by(Skill.id))).all())


async def list_skill_versions(
    db: AsyncSession,
    skill_id: int,
    *,
    organization_id: int,
    user_id: int,
) -> list[SkillVersion]:
    return list(
        (
            await db.scalars(
                select(SkillVersion)
                .where(
                    SkillVersion.skill_id == skill_id,
                    SkillVersion.organization_id == organization_id,
                    SkillVersion.user_id == user_id,
                )
                .order_by(SkillVersion.revision.desc(), SkillVersion.id.desc())
            )
        ).all()
    )
