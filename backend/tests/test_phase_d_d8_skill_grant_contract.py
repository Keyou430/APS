"""D8 RED：执行计划 2026-08-15 D8.1 的 Skill grant 契约。

契约：owner grant B read 后 B 可读不可写；B 不能 re-share（no-transitive）；撤销/过期立即不可读；
跨组织 membership 拒绝；Project link/全局 filesystem mount 不能代替 grant；只有 reviewed Skill 可
推广为组织可发现；管理员/受让人不能夺取 owner 写权限；grant/promotion 不改变 Hermes
toolset/filesystem mount/profile。当前后端无 skill_access_grants 表与任何 grant/promote 端点。
本文件 RED 只证明业务能力缺失。
"""

from datetime import UTC, datetime, timedelta
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
) -> dict:
    response = await client.post(
        "/api/skills",
        headers=headers,
        json={"name": name, "category": "general", "content": f"content of {name}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_grant_reads_but_not_writes(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    grantee_id, grantee_headers = await _make_user(client, "phase-d-grant-b")
    created = await create_skill(client, admin_headers, "grant probe")
    skill_id = created["id"]

    granted = await client.post(
        f"/api/skills/{skill_id}/grants",
        headers=admin_headers,
        json={"grantee_user_id": grantee_id},
    )
    assert granted.status_code == 201, (
        f"D8.1 要求 owner 可 grant B read；grant 端点缺失，实际 {granted.status_code}"
    )
    detail = await client.get(f"/api/skills/{skill_id}", headers=grantee_headers)
    assert detail.status_code == 200, detail.text

    updated = await client.put(
        f"/api/skills/{skill_id}",
        headers=grantee_headers,
        json={"content": "tamper", "expected_revision": 1},
    )
    assert updated.status_code == 404, "受让人不可写（owner predicate）"


async def test_grantee_cannot_reshare(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    grantee_id, grantee_headers = await _make_user(client, "phase-d-grant-b2")
    third_id, _third_headers = await _make_user(client, "phase-d-grant-c2")
    created = await create_skill(client, admin_headers, "reshare probe")
    skill_id = created["id"]
    granted = await client.post(
        f"/api/skills/{skill_id}/grants",
        headers=admin_headers,
        json={"grantee_user_id": grantee_id},
    )
    assert granted.status_code == 201, granted.text

    reshared = await client.post(
        f"/api/skills/{skill_id}/grants",
        headers=grantee_headers,
        json={"grantee_user_id": third_id},
    )
    assert reshared.status_code == 404, (
        f"D8.1 要求 no-transitive re-share（受让人再 grant 必须 fail closed）；实际 {reshared.status_code}"
    )


async def test_revoke_and_expiry_remove_access_immediately(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    grantee_id, grantee_headers = await _make_user(client, "phase-d-grant-b3")
    created = await create_skill(client, admin_headers, "revoke probe")
    skill_id = created["id"]
    granted = await client.post(
        f"/api/skills/{skill_id}/grants",
        headers=admin_headers,
        json={"grantee_user_id": grantee_id},
    )
    assert granted.status_code == 201, granted.text
    grant_id = granted.json()["id"]

    revoked = await client.delete(
        f"/api/skills/{skill_id}/grants/{grant_id}",
        headers=admin_headers,
    )
    assert revoked.status_code == 204, (
        f"D8.1 要求可撤销 grant；revoke 端点缺失，实际 {revoked.status_code}"
    )
    detail = await client.get(f"/api/skills/{skill_id}", headers=grantee_headers)
    assert detail.status_code == 404, "撤销后必须立即不可读"

    regranted = await client.post(
        f"/api/skills/{skill_id}/grants",
        headers=admin_headers,
        json={
            "grantee_user_id": grantee_id,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
        },
    )
    assert regranted.status_code == 201, regranted.text
    await __import__("asyncio").sleep(1.2)
    detail = await client.get(f"/api/skills/{skill_id}", headers=grantee_headers)
    assert detail.status_code == 404, "过期后必须立即不可读"


async def test_cross_org_grant_is_rejected(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    from app.models import Organization

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        role = await db.scalar(select(Role).where(Role.name == "user"))
        assert admin is not None and role is not None
        foreign = Organization(name="D8 foreign org", slug="d8-foreign-org")
        db.add(foreign)
        await db.flush()
        outsider = User(
            username="phase-d-foreign-user",
            email="phase-d-foreign-user@example.com",
            password_hash=hash_password("phase-d-foreign-user-password"),
            role_id=role.id,
            default_organization_id=foreign.id,
        )
        db.add(outsider)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=foreign.id, user_id=outsider.id, role_id=role.id
            )
        )
        await db.commit()
        outsider_id = outsider.id
    valid_target_id, _valid_headers = await _make_user(client, "phase-d-valid-target")
    created = await create_skill(client, admin_headers, "cross org grant probe")
    valid_grant = await client.post(
        f"/api/skills/{created['id']}/grants",
        headers=admin_headers,
        json={"grantee_user_id": valid_target_id},
    )
    assert valid_grant.status_code == 201, (
        f"D8.1 要求 grant 端点存在；当前端点缺失，实际 {valid_grant.status_code}"
    )
    granted = await client.post(
        f"/api/skills/{created['id']}/grants",
        headers=admin_headers,
        json={"grantee_user_id": outsider_id},
    )
    assert granted.status_code == 404, (
        f"D8.1 要求跨组织 grant 拒绝；实际 {granted.status_code}"
    )


async def test_project_link_and_filesystem_mount_do_not_substitute_grant(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    member_id, member_headers = await _make_user(client, "phase-d-project-member")
    created = await create_skill(client, admin_headers, "placement probe")
    skill_id = created["id"]

    project = await client.post(
        "/api/projects",
        headers=admin_headers,
        json={"name": "placement probe", "visibility": "private"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    roster = await client.put(
        f"/api/projects/{project_id}/roster",
        headers=admin_headers,
        json={"expected_revision": 1, "add": [member_id], "remove": []},
    )
    assert roster.status_code == 200, roster.text
    linked = await client.post(
        f"/api/projects/{project_id}/resources",
        headers=admin_headers,
        json={"resource_type": "skill", "ref_id": str(skill_id), "ord": 1},
    )
    assert linked.status_code == 201, linked.text

    detail = await client.get(f"/api/skills/{skill_id}", headers=member_headers)
    assert detail.status_code == 404, (
        f"D8.1 要求 Project resource link 不能代替 grant；实际 {detail.status_code}"
    )

    demo_path = Path(__file__).parents[2] / "deploy" / "hermes" / "skills" / "hr-weekly-report"
    assert demo_path.exists()
    discoverable = await client.get("/api/skills/discoverable", headers=member_headers)
    assert discoverable.status_code == 200, (
        f"D8.1 要求存在 discoverable 目录；端点缺失，实际 {discoverable.status_code}"
    )
    assert all(item["id"] != skill_id for item in discoverable.json()["items"]), (
        "Project resource link 不得使 skill 出现在 discoverable 目录"
    )


async def test_promotion_requires_reviewed_and_does_not_transfer_write(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    _member_id, member_headers = await _make_user(client, "phase-d-org-member")
    created = await create_skill(client, admin_headers, "promote probe")
    skill_id = created["id"]

    promoted_draft = await client.post(
        f"/api/skills/{skill_id}/promote",
        headers=admin_headers,
    )
    assert promoted_draft.status_code == 409, (
        f"D8.1 要求只有 reviewed Skill 可推广；draft 实际 {promoted_draft.status_code}"
    )
    reviewed = await client.post(f"/api/skills/{skill_id}/review", headers=admin_headers)
    assert reviewed.status_code == 200, reviewed.text
    promoted = await client.post(f"/api/skills/{skill_id}/promote", headers=admin_headers)
    assert promoted.status_code == 200, (
        f"D8.1 要求 reviewed Skill 可推广为组织可发现；promote 端点缺失，实际 {promoted.status_code}"
    )
    assert promoted.json()["is_promoted"] is True

    discoverable = await client.get("/api/skills/discoverable", headers=member_headers)
    assert discoverable.status_code == 200, discoverable.text
    assert any(item["id"] == skill_id for item in discoverable.json()["items"])

    detail = await client.get(f"/api/skills/{skill_id}", headers=member_headers)
    assert detail.status_code == 200, detail.text
    updated = await client.put(
        f"/api/skills/{skill_id}",
        headers=member_headers,
        json={"content": "tamper", "expected_revision": 1},
    )
    assert updated.status_code == 404, "推广不转移 owner 写权限"


async def test_grant_and_promotion_do_not_mutate_hermes_or_filesystem(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    grantee_id, _grantee_headers = await _make_user(client, "phase-d-grant-b4")

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

    created = await create_skill(client, admin_headers, "no hermes mutation probe")
    granted = await client.post(
        f"/api/skills/{created['id']}/grants",
        headers=admin_headers,
        json={"grantee_user_id": grantee_id},
    )
    assert granted.status_code == 201, (
        f"D8.1 要求 grant 端点存在；当前端点缺失，实际 {granted.status_code}"
    )
    reviewed = await client.post(
        f"/api/skills/{created['id']}/review", headers=admin_headers
    )
    assert reviewed.status_code == 200, reviewed.text
    promoted = await client.post(
        f"/api/skills/{created['id']}/promote", headers=admin_headers
    )
    assert promoted.status_code == 200, (
        f"D8.1 要求 promote 端点存在；当前端点缺失，实际 {promoted.status_code}"
    )

    async with SessionLocal() as db:
        profiles_after = [
            _profile_state(profile)
            for profile in (
                await db.scalars(select(HermesProfile).order_by(HermesProfile.id))
            ).all()
        ]
    entries_after = sorted(item.name for item in demo_dir.iterdir())
    assert profiles_before == profiles_after, "grant/promote 不得改变 Hermes profile"
    assert entries_before == entries_after, "grant/promote 不得改变 filesystem mount"
