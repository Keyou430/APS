"""D6 RED：执行计划 2026-08-15 D6.1 的 Skill 生命周期契约。

当前 /api/skills 是纯 owner catalog（无 status/revision/version/hash，无 review/publish/archive）。
D6.1 契约：create 产生 v1；update 带 expected_revision 并追加 immutable version，stale 409；
no-op 幂等；review 需 skills:review、publish 需 skills:publish；archive 后 catalog 默认不可见；
deploy/hermes/skills/hr-weekly-report 的存在不能让数据库 Skill 自动 published/installed。
本文件 RED 只证明业务能力缺失；文件系统/权限范围类既有契约由现有测试继续覆盖。
"""

from pathlib import Path

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def create_skill(
    client: AsyncClient,
    headers: dict[str, str],
    name: str,
    content: str = "run a weekly report",
) -> dict:
    response = await client.post(
        "/api/skills",
        headers=headers,
        json={"name": name, "category": "general", "content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_produces_v1_draft_skill(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await create_skill(client, admin_headers, "lifecycle probe")
    assert created["status"] == "draft", (
        "D6.1 要求 create 产生 draft v1；当前 SkillResponse 无 status 字段（业务能力缺失）"
    )
    assert created["revision"] == 1
    assert created["current_version"] == "v1"


async def test_update_requires_expected_revision_and_appends_immutable_version(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await create_skill(client, admin_headers, "version probe", content="v1 content")
    skill_id = created["id"]

    updated = await client.put(
        f"/api/skills/{skill_id}",
        headers=admin_headers,
        json={"content": "v2 content", "expected_revision": 1},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["revision"] == 2, "内容变更后 revision 必须递增"
    assert body["current_version"] == "v2"

    stale = await client.put(
        f"/api/skills/{skill_id}",
        headers=admin_headers,
        json={"content": "stale overwrite", "expected_revision": 1},
    )
    assert stale.status_code == 409, (
        f"D6.1 要求 update 使用 expected_revision CAS；当前实现忽略该字段，实际 {stale.status_code}"
    )

    versions = await client.get(
        f"/api/skills/{skill_id}/versions",
        headers=admin_headers,
    )
    assert versions.status_code == 200, versions.text
    assert [item["version"] for item in versions.json()["items"]] == ["v2", "v1"], (
        "update 必须追加 immutable version 且保留 v1 历史"
    )


async def test_no_op_update_is_idempotent(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await create_skill(client, admin_headers, "noop probe", content="same content")
    skill_id = created["id"]

    first = await client.put(
        f"/api/skills/{skill_id}",
        headers=admin_headers,
        json={"content": "same content", "expected_revision": 1},
    )
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1, "no-op 更新不得递增 revision"
    assert first.json()["current_version"] == "v1", "no-op 更新不得追加版本"


async def test_review_and_publish_require_lifecycle_permissions(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await create_skill(client, admin_headers, "lifecycle gate probe")
    skill_id = created["id"]

    reviewed = await client.post(
        f"/api/skills/{skill_id}/review",
        headers=admin_headers,
    )
    assert reviewed.status_code == 200, (
        f"D6.1 要求 review 端点存在且由 skills:review 门禁；当前端点缺失，实际 {reviewed.status_code}"
    )
    assert reviewed.json()["status"] == "reviewed"

    published = await client.post(
        f"/api/skills/{skill_id}/publish",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    archived = await client.post(
        f"/api/skills/{skill_id}/archive",
        headers=admin_headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    catalog = await client.get("/api/skills", headers=admin_headers)
    assert catalog.status_code == 200
    assert all(item["id"] != skill_id for item in catalog.json()["items"]), (
        "archived skill 不得出现在默认 catalog"
    )


async def test_review_requires_skills_review_permission_for_regular_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    from sqlalchemy import select

    from app.auth.security import hash_password
    from app.database import SessionLocal
    from app.models import OrganizationMembership, Role, User

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        user_role = await db.scalar(select(Role).where(Role.name == "user"))
        assert admin is not None and user_role is not None
        regular = User(
            username="phase-d-skill-owner",
            email="phase-d-skill-owner@example.com",
            password_hash=hash_password("phase-d-skill-owner-password"),
            role_id=user_role.id,
            default_organization_id=admin.default_organization_id,
        )
        db.add(regular)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=admin.default_organization_id,
                user_id=regular.id,
                role_id=user_role.id,
            )
        )
        await db.commit()
    login = await client.post(
        "/api/auth/login",
        json={"username": "phase-d-skill-owner", "password": "phase-d-skill-owner-password"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await create_skill(client, headers, "regular owner probe")
    reviewed = await client.post(
        f"/api/skills/{created['id']}/review",
        headers=headers,
    )
    assert reviewed.status_code == 403, (
        "D6.1 要求 review 由 skills:review 门禁；普通 user 角色不应具备该能力"
    )


async def test_publish_requires_reviewed_status(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await create_skill(client, admin_headers, "unreviewed publish probe")
    published = await client.post(
        f"/api/skills/{created['id']}/publish",
        headers=admin_headers,
    )
    assert published.status_code == 409, (
        f"D6.1 要求只有 reviewed Skill 可 publish；当前实际 {published.status_code}"
    )


async def test_filesystem_demo_skill_is_not_auto_published(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    demo_path = Path(__file__).parents[2] / "deploy" / "hermes" / "skills" / "hr-weekly-report"
    assert demo_path.exists(), "本测试依赖仓库内 hr-weekly-report 演示 Skill 目录存在"

    catalog = await client.get("/api/skills", headers=admin_headers)
    assert catalog.status_code == 200
    names = {item["name"] for item in catalog.json()["items"]}
    assert "hr-weekly-report" not in names, (
        "D6.1 要求 filesystem 演示 Skill 的存在不能让数据库 Skill 自动 published/installed"
    )
