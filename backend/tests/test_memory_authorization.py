from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.auth.security import create_token
from app.database import SessionLocal
from app.models import Organization, OrganizationMembership, User


pytestmark = pytest.mark.asyncio


async def create_user_headers(
    client: AsyncClient,
    admin_headers: dict[str, str],
    username: str,
) -> dict[str, str]:
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": username,
            "password": "memory-test-password",
            "email": f"{username}@example.com",
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "memory-test-password"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_memory_is_owner_only_inside_same_organization(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    owner_headers = await create_user_headers(client, admin_headers, "memory-owner-user")
    created = await client.post(
        "/api/memory",
        headers=owner_headers,
        json={"content": "Only the owner may read this memory", "metadata": {}},
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["memory_id"]

    assert (await client.get(f"/api/memory/{memory_id}", headers=admin_headers)).status_code == 404
    admin_search = await client.get(
        "/api/memory",
        headers=admin_headers,
        params={"query": "Only the owner"},
    )
    assert admin_search.status_code == 200
    assert admin_search.json()["items"] == []
    assert (
        await client.put(
            f"/api/memory/{memory_id}",
            headers=admin_headers,
            json={"content": "Unauthorized", "expected_revision": 1},
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/memory/{memory_id}",
            headers=admin_headers,
            params={"expected_revision": 1},
        )
    ).status_code == 404


async def test_memory_scope_comes_from_token_membership_not_default_or_metadata(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        original_default = admin.default_organization_id
        foreign = Organization(name="Memory foreign organization", slug="memory-foreign-org")
        db.add(foreign)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=foreign.id,
                user_id=admin.id,
                role_id=admin.role_id,
            )
        )
        admin.default_organization_id = foreign.id
        await db.commit()
        foreign_id = foreign.id
        foreign_token, _, _ = create_token(
            admin.id,
            "access",
            timedelta(minutes=15),
            organization_id=foreign.id,
        )

    foreign_headers = {"Authorization": f"Bearer {foreign_token}"}
    try:
        created = await client.post(
            "/api/memory",
            headers=admin_headers,
            json={
                "content": "Original organization memory",
                "metadata": {
                    "organization_id": str(foreign_id),
                    "user_id": "999999",
                },
            },
        )
        assert created.status_code == 201, created.text
        memory_id = created.json()["memory_id"]

        original_list = await client.get("/api/memory", headers=admin_headers)
        foreign_list = await client.get("/api/memory", headers=foreign_headers)
        assert memory_id in {item["memory_id"] for item in original_list.json()["items"]}
        assert memory_id not in {item["memory_id"] for item in foreign_list.json()["items"]}
        assert (
            await client.get(f"/api/memory/{memory_id}", headers=foreign_headers)
        ).status_code == 404
    finally:
        async with SessionLocal() as db:
            admin = await db.scalar(select(User).where(User.username == "admin"))
            assert admin is not None
            admin.default_organization_id = original_default
            await db.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.organization_id == foreign_id
                )
            )
            await db.execute(delete(Organization).where(Organization.id == foreign_id))
            await db.commit()
