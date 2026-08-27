"""D9 RED：执行计划 2026-08-15 D9.1/D9.2 的 per-request trusted projection 契约。

契约：只有服务器选定的 published version 可作为 platform instruction 注入；draft/unreviewed/
ungranted/revoked/archived Skill 永不进入 Hermes instructions/tools；跨组织相同内容不串线；
下一请求必须重新授权（撤权即时生效）；不得把授权 Skill 复制到长期 Hermes profile 或 filesystem；
现有全局 hr-weekly-report mount 不能作为 scoped authorization 替身。
当前后端无 skill_context 投影服务，chat instructions 只包含 fixed/knowledge/memory/transient。
本文件 RED 以 importlib 能力断言证明缺失（不是 import 错误），行为断言在 GREEN 后全部可执行。
"""

import importlib.util
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import HermesProfile, OrganizationMembership, Role, User

pytestmark = pytest.mark.asyncio


async def _make_user(
    client: AsyncClient,
    username: str,
    role_name: str = "user",
) -> tuple[int, dict[str, str]]:
    async with SessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert role is not None and admin is not None
        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password(f"{username}-password"),
            role_id=role.id,
            default_organization_id=admin.default_organization_id,
        )
        db.add(user)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=admin.default_organization_id,
                user_id=user.id,
                role_id=role.id,
            )
        )
        await db.commit()
        user_id = user.id
    login = await client.post(
        "/api/auth/login", json={"username": username, "password": f"{username}-password"}
    )
    assert login.status_code == 200
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def create_skill(
    client: AsyncClient,
    headers: dict[str, str],
    name: str,
    content: str | None = None,
) -> dict:
    response = await client.post(
        "/api/skills",
        headers=headers,
        json={"name": name, "category": "general", "content": content or f"content of {name}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_runtime_projection_service_exists() -> None:
    spec = importlib.util.find_spec("app.services.skill_context")
    assert spec is not None, (
        "D9.1 要求 per-request trusted projection 服务存在（app.services.skill_context）；"
        "当前缺失，runtime projection 能力不存在（业务能力缺失）"
    )


async def _make_published_skill(client, headers, name: str) -> dict:
    created = await create_skill(client, headers, name)
    reviewed = await client.post(f"/api/skills/{created['id']}/review", headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    published = await client.post(f"/api/skills/{created['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    return published.json()


async def test_projection_selects_only_published_authorized_skills(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    from app.services.skill_context import select_authorized_skills

    await _make_published_skill(client, admin_headers, "projection published")
    draft = await create_skill(client, admin_headers, "projection draft")
    await client.post(f"/api/skills/{draft['id']}/review", headers=admin_headers)
    archived = await _make_published_skill(client, admin_headers, "projection archived")
    await client.post(f"/api/skills/{archived['id']}/archive", headers=admin_headers)

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        selected = await select_authorized_skills(
            db,
            organization_id=admin.default_organization_id,
            user_id=admin.id,
            surface="knowledge",
        )
    names = {skill.name for skill in selected}
    assert "projection published" in names, "published owner Skill 必须进入投影"
    assert "projection draft" not in names, "reviewed 但未 published 不得进入投影"
    assert "projection archived" not in names, "archived 不得进入投影"


async def test_projection_respects_grant_promotion_and_revocation(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    from app.services.skill_context import select_authorized_skills

    member_id, _member_headers = await _make_user(client, "phase-d-projection-member")
    granted = await _make_published_skill(client, admin_headers, "projection granted")
    promoted = await _make_published_skill(client, admin_headers, "projection promoted")
    await client.post(f"/api/skills/{promoted['id']}/promote", headers=admin_headers)
    await _make_published_skill(client, admin_headers, "projection ungranted")

    grant = await client.post(
        f"/api/skills/{granted['id']}/grants",
        headers=admin_headers,
        json={"grantee_user_id": member_id},
    )
    assert grant.status_code == 201, grant.text

    async def selected_names() -> set[str]:
        async with SessionLocal() as db:
            admin = await db.scalar(select(User).where(User.username == "admin"))
            assert admin is not None
            items = await select_authorized_skills(
                db,
                organization_id=admin.default_organization_id,
                user_id=member_id,
                surface="knowledge",
            )
        return {skill.name for skill in items}

    names = await selected_names()
    assert "projection granted" in names, "active grant 必须进入投影"
    assert "projection promoted" in names, "promoted 组织可发现 Skill 必须进入投影"
    assert "projection ungranted" not in names, "未授权 Skill 不得进入投影"

    await client.delete(
        f"/api/skills/{granted['id']}/grants/{grant.json()['id']}",
        headers=admin_headers,
    )
    names = await selected_names()
    assert "projection granted" not in names, "撤权后下一请求投影必须立即排除"


async def test_projection_block_is_untrusted_and_bounded(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    from app.services.skill_context import build_authorized_skills_block, select_authorized_skills

    await _make_published_skill(client, admin_headers, "projection block probe")
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        selected = await select_authorized_skills(
            db,
            organization_id=admin.default_organization_id,
            user_id=admin.id,
            surface="knowledge",
        )
        block = build_authorized_skills_block(selected, surface="knowledge")
        off_block = build_authorized_skills_block(selected, surface="agent")
    assert "AUTHORIZED_SKILLS" in block
    assert "untrusted" in block.lower()
    assert "content of projection block probe" in block
    assert len(block.encode("utf-8")) <= 4_096, "投影块必须受字节预算约束"
    assert off_block == "", "agent surface 不得注入 Skill 投影"


async def test_projection_does_not_mutate_hermes_or_filesystem(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    from app.services.skill_context import select_authorized_skills

    await _make_published_skill(client, admin_headers, "projection no mutation probe")

    def _profile_state(profile: HermesProfile) -> dict:
        return {
            column.name: getattr(profile, column.name)
            for column in HermesProfile.__table__.columns
        }

    async with SessionLocal() as db:
        profiles_before = [
            _profile_state(profile)
            for profile in (
                await db.scalars(select(HermesProfile).order_by(HermesProfile.id))
            ).all()
        ]
    demo_dir = Path(__file__).parents[2] / "deploy" / "hermes" / "skills"
    entries_before = sorted(item.name for item in demo_dir.iterdir())

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        await select_authorized_skills(
            db,
            organization_id=admin.default_organization_id,
            user_id=admin.id,
            surface="knowledge",
        )
    async with SessionLocal() as db:
        profiles_after = [
            _profile_state(profile)
            for profile in (
                await db.scalars(select(HermesProfile).order_by(HermesProfile.id))
            ).all()
        ]
    entries_after = sorted(item.name for item in demo_dir.iterdir())
    assert profiles_before == profiles_after, "投影不得写入 Hermes profile"
    assert entries_before == entries_after, "投影不得写入 filesystem mount"
