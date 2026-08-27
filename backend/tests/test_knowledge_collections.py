from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.auth.security import create_token
from app.database import SessionLocal
from app.models import KnowledgeCollection, KnowledgeEntry, Organization, OrganizationMembership, User
from test_knowledge_authorization import create_member


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def cleanup_collection_contract_data():
    yield
    async with SessionLocal() as db:
        await db.execute(
            delete(KnowledgeEntry).where(
                KnowledgeEntry.title.in_({"Collection private", "Collection visible"})
            )
        )
        await db.execute(
            delete(KnowledgeCollection).where(
                KnowledgeCollection.name.in_(
                    {"Phase C collection", "Phase C empty collection"}
                )
            )
        )
        foreign = await db.scalar(
            select(Organization).where(
                Organization.slug == "phase-c-foreign-collection-organization"
            )
        )
        if foreign is not None:
            await db.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.organization_id == foreign.id
                )
            )
            await db.delete(foreign)
        reader = await db.scalar(
            select(User).where(User.username == "phase-c-collection-reader")
        )
        if reader is not None:
            await db.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.user_id == reader.id
                )
            )
            await db.delete(reader)
        await db.commit()


async def login(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_collection_filter_is_organization_scoped_and_does_not_grant_access(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/knowledge/collections",
        headers=admin_headers,
        json={"name": "Phase C collection", "description": "Contract fixture"},
    )
    assert created.status_code == 201, created.text
    collection_id = created.json()["id"]

    collections = await client.get("/api/knowledge/collections", headers=admin_headers)
    assert collections.status_code == 200, collections.text
    assert any(item["id"] == collection_id for item in collections.json()["items"])

    private = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Collection private", "content": "private"},
    )
    visible = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Collection visible", "content": "visible"},
    )
    assert private.status_code == 201 and visible.status_code == 201
    made_visible = await client.put(
        f"/api/knowledge/{visible.json()['id']}/access",
        headers=admin_headers,
        json={"visibility": "organization_members"},
    )
    assert made_visible.status_code == 200, made_visible.text

    for entry_id in (private.json()["id"], visible.json()["id"]):
        moved = await client.put(
            f"/api/knowledge/{entry_id}/collection",
            headers=admin_headers,
            json={"collection_id": collection_id},
        )
        assert moved.status_code == 200, moved.text

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        organization_id = admin.default_organization_id

    await create_member(
        username="phase-c-collection-reader",
        organization_id=organization_id,
    )
    reader_headers = await login(
        client, "phase-c-collection-reader", "authorization-password"
    )
    filtered = await client.get(
        f"/api/knowledge?collection_id={collection_id}", headers=reader_headers
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [visible.json()["id"]]

    nonempty_delete = await client.delete(
        f"/api/knowledge/collections/{collection_id}", headers=admin_headers
    )
    assert nonempty_delete.status_code == 409

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        foreign = Organization(
            name="Phase C foreign collection organization",
            slug="phase-c-foreign-collection-organization",
        )
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
        foreign_id = foreign.id
        foreign_token, _, _ = create_token(
            admin.id,
            "access",
            timedelta(minutes=15),
            organization_id=foreign_id,
        )

    cross_organization = await client.get(
        f"/api/knowledge?collection_id={collection_id}",
        headers={"Authorization": f"Bearer {foreign_token}"},
    )
    assert cross_organization.status_code == 404


async def test_empty_collection_filter_returns_an_empty_page(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/knowledge/collections",
        headers=admin_headers,
        json={"name": "Phase C empty collection"},
    )
    assert created.status_code == 201, created.text

    response = await client.get(
        f"/api/knowledge?collection_id={created.json()['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
