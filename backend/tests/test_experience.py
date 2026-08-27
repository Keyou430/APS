from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.auth.security import hash_password
from app.models import AuditEvent, Organization, OrganizationMembership, Role, User


@pytest.mark.asyncio
async def test_experience_domains_and_methods_are_organization_scoped(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/experience/domains",
        headers=admin_headers,
        json={"name": "招聘", "description": "招聘流程经验"},
    )
    assert created.status_code == 201, created.text
    domain_id = created.json()["id"]

    method = await client.post(
        f"/api/experience/domains/{domain_id}/methods",
        headers=admin_headers,
        json={
            "title": "结构化面试",
            "content": "先确认岗位目标，再按 STAR 追问。",
            "source_type": "ai_summary",
            "source_reference": "chat:session-1",
        },
    )
    assert method.status_code == 201, method.text
    assert method.json()["source_type"] == "ai_summary"

    domains = await client.get("/api/experience/domains", headers=admin_headers)
    assert domains.status_code == 200
    assert domains.json()["items"][0]["method_count"] == 1

    methods = await client.get(
        f"/api/experience/domains/{domain_id}/methods", headers=admin_headers
    )
    assert methods.status_code == 200
    assert methods.json()["items"][0]["title"] == "结构化面试"

    method_id = methods.json()["items"][0]["id"]
    updated_method = await client.patch(
        f"/api/experience/methods/{method_id}",
        headers=admin_headers,
        json={"title": "结构化面试追问"},
    )
    assert updated_method.status_code == 200

    updated_domain = await client.patch(
        f"/api/experience/domains/{domain_id}",
        headers=admin_headers,
        json={"description": "更新后的招聘流程经验"},
    )
    assert updated_domain.status_code == 200

    blocked = await client.delete(f"/api/experience/domains/{domain_id}", headers=admin_headers)
    assert blocked.status_code == 409

    deleted = await client.delete(
        f"/api/experience/methods/{method_id}", headers=admin_headers
    )
    assert deleted.status_code == 204
    deleted_domain = await client.delete(
        f"/api/experience/domains/{domain_id}", headers=admin_headers
    )
    assert deleted_domain.status_code == 204

    async with SessionLocal() as db:
        actions = set(
            (
                await db.scalars(
                    select(AuditEvent.action).where(
                        AuditEvent.resource_type.in_(
                            ["experience_domain", "experience_method"]
                        )
                    )
                )
            ).all()
        )
    assert {
        "experience.domain.create",
        "experience.domain.update",
        "experience.domain.delete",
        "experience.method.create",
        "experience.method.update",
        "experience.method.delete",
    }.issubset(actions)


@pytest.mark.asyncio
async def test_knowledge_upload_requires_a_valid_collection(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    missing = await client.post(
        "/api/knowledge/upload",
        headers=admin_headers,
        data={"title": "未归档.txt"},
        files={"file": ("unfiled.txt", b"content", "text/plain")},
    )
    assert missing.status_code == 422

    invalid = await client.post(
        "/api/knowledge/upload",
        headers=admin_headers,
        data={"title": "错误目录.txt", "collection_id": "999999"},
        files={"file": ("wrong-folder.txt", b"content", "text/plain")},
    )
    assert invalid.status_code == 404


@pytest.mark.asyncio
async def test_experience_domain_cannot_cross_organization_boundary(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/experience/domains",
        headers=admin_headers,
        json={"name": "仅默认组织可见", "description": "隔离测试"},
    )
    assert created.status_code == 201, created.text
    domain_id = created.json()["id"]

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        primary_membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == admin.id,
                OrganizationMembership.organization_id == admin.default_organization_id,
            )
        )
        assert primary_membership is not None
        organization = Organization(
            name="Experience Isolation",
            slug=f"experience-isolation-{uuid4().hex}",
        )
        db.add(organization)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=admin.id,
                role_id=primary_membership.role_id,
                member_type="internal",
                is_active=True,
            )
        )
        await db.commit()
        alternate_organization_id = organization.id

    switched = await client.post(
        "/api/auth/switch-organization",
        headers=admin_headers,
        json={"organization_id": alternate_organization_id},
    )
    assert switched.status_code == 200, switched.text
    alternate_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}

    listed = await client.get("/api/experience/domains", headers=alternate_headers)
    assert listed.status_code == 200, listed.text
    assert all(item["id"] != domain_id for item in listed.json()["items"])

    assert (
        await client.get(
            f"/api/experience/domains/{domain_id}/methods",
            headers=alternate_headers,
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/experience/domains/{domain_id}",
            headers=alternate_headers,
            json={"name": "越权修改"},
        )
    ).status_code == 404

    async with SessionLocal() as db:
        organization = await db.get(Organization, alternate_organization_id)
        assert organization is not None
        await db.delete(organization)
        await db.commit()


@pytest.mark.asyncio
async def test_guest_can_read_experience_but_cannot_change_it(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        guest_role = await db.scalar(select(Role).where(Role.name == "guest"))
        assert admin is not None and guest_role is not None
        guest = User(
            username=f"experience-guest-{uuid4().hex[:8]}",
            email=f"experience-guest-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("experience-guest-password"),
            role_id=guest_role.id,
            default_organization_id=admin.default_organization_id,
        )
        db.add(guest)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=admin.default_organization_id,
                user_id=guest.id,
                role_id=guest_role.id,
                member_type="guest",
                is_active=True,
            )
        )
        await db.commit()

    login = await client.post(
        "/api/auth/login",
        json={"username": guest.username, "password": "experience-guest-password"},
    )
    assert login.status_code == 200, login.text
    guest_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/api/experience/domains", headers=guest_headers)).status_code == 200
    assert (
        await client.post(
            "/api/experience/domains",
            headers=guest_headers,
            json={"name": "guest-write", "description": "must fail"},
        )
    ).status_code == 403
