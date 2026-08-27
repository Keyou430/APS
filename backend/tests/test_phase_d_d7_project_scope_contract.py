"""D7 RED：执行计划 2026-08-15 D7.1 的 Project scope/roster 契约。

当前后端无 projects 模型与端点。契约：当前组织可列；跨组织不可见；private Project 非 roster
不可读；owner/manage 管理 roster；roster 更新 expected_revision CAS（stale 409）；批量成员变更
全事务；guest 默认不能加入；resource link 只表达 placement/order 不授予底层资源访问。
本文件 RED 只证明业务能力缺失。
"""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.security import create_token, hash_password
from app.database import SessionLocal
from app.models import Organization, OrganizationMembership, Role, User

pytestmark = pytest.mark.asyncio


async def _make_user(
    client: AsyncClient,
    username: str,
    password: str,
    role_name: str,
    organization_id: int | None = None,
) -> tuple[int, dict[str, str]]:
    async with SessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        assert role is not None
        if organization_id is None:
            admin = await db.scalar(select(User).where(User.username == "admin"))
            assert admin is not None
            organization_id = admin.default_organization_id
        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password(password),
            role_id=role.id,
            default_organization_id=organization_id,
        )
        db.add(user)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization_id,
                user_id=user.id,
                role_id=role.id,
                member_type="guest" if role_name == "guest" else "internal",
            )
        )
        await db.commit()
        user_id = user.id
    login = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_org_members_can_list_projects(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    listed = await client.get("/api/projects", headers=admin_headers)
    assert listed.status_code == 200, (
        f"D7.1 要求当前组织可列 projects；端点缺失，实际 {listed.status_code}"
    )
    assert isinstance(listed.json()["items"], list)


async def test_create_project_returns_roster_revision_and_owner(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/projects",
        headers=admin_headers,
        json={"name": "scope probe", "description": "D7 probe", "visibility": "private"},
    )
    assert created.status_code == 201, (
        f"D7.1 要求可创建 Project；端点缺失，实际 {created.status_code}"
    )
    body = created.json()
    assert body["roster_revision"] == 1
    assert body["visibility"] == "private"
    assert body["owner_user_id"] is not None


async def test_cross_org_project_is_invisible(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        foreign = Organization(name="D7 foreign org", slug="d7-foreign-org")
        db.add(foreign)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=foreign.id,
                user_id=admin.id,
                role_id=admin.role_id,
            )
        )
        await db.commit()
        foreign_token, _, _ = create_token(
            admin.id, "access", timedelta(minutes=15), organization_id=foreign.id
        )

    created = await client.post(
        "/api/projects",
        headers=admin_headers,
        json={"name": "cross org probe", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    foreign_headers = {"Authorization": f"Bearer {foreign_token}"}
    detail = await client.get(f"/api/projects/{project_id}", headers=foreign_headers)
    assert detail.status_code == 404, (
        f"D7.1 要求跨组织 Project 不可见；实际 {detail.status_code}"
    )
    listed = await client.get("/api/projects", headers=foreign_headers)
    assert all(item["id"] != project_id for item in listed.json()["items"])


async def test_private_project_hidden_from_non_roster_members(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    member_id, member_headers = await _make_user(
        client, "phase-d-project-outsider", "phase-d-project-outsider-password", "user"
    )
    created = await client.post(
        "/api/projects",
        headers=admin_headers,
        json={"name": "private probe", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    detail = await client.get(f"/api/projects/{project_id}", headers=member_headers)
    assert detail.status_code == 404, (
        f"D7.1 要求 private Project 非 roster 成员不可读；实际 {detail.status_code}"
    )
    listed = await client.get("/api/projects", headers=member_headers)
    assert all(item["id"] != project_id for item in listed.json()["items"])


async def test_roster_update_requires_expected_revision(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    member_id, _member_headers = await _make_user(
        client, "phase-d-roster-member", "phase-d-roster-member-password", "user"
    )
    created = await client.post(
        "/api/projects",
        headers=admin_headers,
        json={"name": "roster probe", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    updated = await client.put(
        f"/api/projects/{project_id}/roster",
        headers=admin_headers,
        json={"expected_revision": 1, "add": [member_id], "remove": []},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["roster_revision"] == 2

    stale = await client.put(
        f"/api/projects/{project_id}/roster",
        headers=admin_headers,
        json={"expected_revision": 1, "add": [], "remove": [member_id]},
    )
    assert stale.status_code == 409, (
        f"D7.1 要求 roster 更新使用 CAS；陈旧 revision 实际 {stale.status_code}"
    )


async def test_bulk_roster_change_is_atomic(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/projects",
        headers=admin_headers,
        json={"name": "atomic roster probe", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    failed = await client.put(
        f"/api/projects/{project_id}/roster",
        headers=admin_headers,
        json={"expected_revision": 1, "add": [999_999], "remove": []},
    )
    assert failed.status_code == 404, (
        f"D7.1 要求批量成员变更全事务（无效成员整体失败）；实际 {failed.status_code}"
    )
    detail = await client.get(f"/api/projects/{project_id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["roster_revision"] == 1, "失败批量变更不得部分生效"


async def test_guest_cannot_use_projects(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    _guest_id, guest_headers = await _make_user(
        client, "phase-d-project-guest", "phase-d-project-guest-password", "guest"
    )
    listed = await client.get("/api/projects", headers=guest_headers)
    assert listed.status_code == 403, (
        f"D7.1 要求 guest 默认不能加入/使用 Project；实际 {listed.status_code}"
    )


async def test_resource_links_are_placement_only(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/projects",
        headers=admin_headers,
        json={"name": "resource link probe", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    linked = await client.post(
        f"/api/projects/{project_id}/resources",
        headers=admin_headers,
        json={"resource_type": "knowledge", "ref_id": "k-123", "ord": 1},
    )
    assert linked.status_code == 201, (
        f"D7.1 要求 resource link 只表达 placement/order；端点缺失，实际 {linked.status_code}"
    )
    listed = await client.get(f"/api/projects/{project_id}/resources", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["resource_type"] == "knowledge"
    assert items[0]["ref_id"] == "k-123"
    assert items[0]["ord"] == 1
    assert set(items[0].keys()) == {"id", "resource_type", "ref_id", "ord"}, (
        "resource link 只应包含 placement 元数据，不得夹带底层资源正文或授权"
    )
