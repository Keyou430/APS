from __future__ import annotations

from httpx import AsyncClient
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditEvent, KnowledgeChunk, KnowledgeEntry, User
from test_knowledge_authorization import create_member


pytestmark = pytest.mark.asyncio


async def login(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def organization_id() -> int:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None and admin.default_organization_id is not None
        return admin.default_organization_id


async def test_govern_member_summary_is_minimal_and_organization_scoped(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await create_member(
        username="member-summary-reader", organization_id=await organization_id()
    )

    response = await client.get("/api/knowledge/members", headers=admin_headers)

    assert response.status_code == 200, response.text
    item = next(
        member for member in response.json()["items"]
        if member["username"] == "member-summary-reader"
    )
    assert set(item) == {"membership_id", "user_id", "username", "member_type"}


async def test_internal_sharer_can_select_minimal_members_but_guest_cannot(
    client: AsyncClient,
) -> None:
    organization = await organization_id()
    await create_member(username="member-summary-sharer", organization_id=organization)
    await create_member(
        username="member-summary-guest",
        organization_id=organization,
        member_type="guest",
    )

    sharer_headers = await login(client, "member-summary-sharer", "authorization-password")
    response = await client.get("/api/knowledge/members", headers=sharer_headers)
    assert response.status_code == 200, response.text
    assert all(set(item) == {"membership_id", "user_id", "username", "member_type"} for item in response.json()["items"])

    guest_headers = await login(client, "member-summary-guest", "authorization-password")
    denied = await client.get("/api/knowledge/members", headers=guest_headers)
    assert denied.status_code == 403


async def test_owner_can_share_and_reader_sees_metadata_without_content(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    reader, membership = await create_member(
        username="sharing-reader", organization_id=await organization_id()
    )
    entry = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Shared policy", "content": "private body"},
    )
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["id"]

    access = await client.put(
        f"/api/knowledge/{entry_id}/access",
        headers=admin_headers,
        json={"visibility": "organization_members"},
    )
    assert access.status_code == 200, access.text

    grant = await client.post(
        f"/api/knowledge/{entry_id}/grants",
        headers=admin_headers,
        json={"membership_id": membership.id},
    )
    assert grant.status_code == 201, grant.text
    grant_id = grant.json()["id"]

    reader_headers = await login(client, "sharing-reader", "authorization-password")
    visible = await client.get(f"/api/knowledge/{entry_id}", headers=reader_headers)
    assert visible.status_code == 200, visible.text
    assert visible.json()["content"] is None
    preview = await client.get(f"/api/knowledge/{entry_id}/content", headers=reader_headers)
    assert preview.status_code == 200
    assert preview.json()["content"] == "private body"
    revoked = await client.delete(
        f"/api/knowledge/{entry_id}/grants/{grant_id}", headers=admin_headers
    )
    assert revoked.status_code == 204
    private = await client.put(
        f"/api/knowledge/{entry_id}/access",
        headers=admin_headers,
        json={"visibility": "private"},
    )
    assert private.status_code == 200
    assert (await client.get(f"/api/knowledge/{entry_id}", headers=reader_headers)).status_code == 404
    async with SessionLocal() as db:
        audits = list(
            (
                await db.scalars(
                    select(AuditEvent).where(AuditEvent.resource_id.in_({str(entry_id), str(grant_id)}))
                )
            ).all()
        )
    assert {event.action for event in audits}.issuperset(
        {"knowledge.create", "knowledge.access.update", "knowledge.grant.create", "knowledge.grant.revoke"}
    )
    assert "private body" not in repr([event.details for event in audits])


async def test_file_preview_uses_authorized_parsed_chunks(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    entry = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "file", "title": "Parsed file preview"},
    )
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["id"]

    async with SessionLocal() as db:
        stored_entry = await db.get(KnowledgeEntry, entry_id)
        assert stored_entry is not None
        for ordinal, text in enumerate(("第一段已解析正文", "第二段已解析正文")):
            db.add(
                KnowledgeChunk(
                    organization_id=stored_entry.organization_id,
                    user_id=stored_entry.user_id,
                    knowledge_entry_id=stored_entry.id,
                    content_sha256="a" * 64,
                    ordinal=ordinal,
                    text=text,
                    text_sha256=("b" if ordinal == 0 else "c") * 64,
                    source_locator=f"chunk:{ordinal}",
                    embedding=[0.0] * 1024,
                )
            )
        await db.commit()

    preview = await client.get(
        f"/api/knowledge/{entry_id}/content",
        headers=admin_headers,
    )

    assert preview.status_code == 200, preview.text
    assert preview.json()["content"] == "第一段已解析正文\n\n第二段已解析正文"


async def test_archive_restore_and_purge_are_separate_owner_commands(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    entry = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Lifecycle", "content": "body"},
    )
    entry_id = entry.json()["id"]
    archived = await client.delete(f"/api/knowledge/{entry_id}", headers=admin_headers)
    assert archived.status_code == 204
    assert (await client.get(f"/api/knowledge/{entry_id}", headers=admin_headers)).status_code == 404
    restored = await client.post(
        f"/api/knowledge/{entry_id}/restore", headers=admin_headers
    )
    assert restored.status_code == 200, restored.text
    assert (
        await client.delete(f"/api/knowledge/{entry_id}", headers=admin_headers)
    ).status_code == 204
    purged = await client.delete(
        f"/api/knowledge/{entry_id}/purge", headers=admin_headers
    )
    assert purged.status_code == 204


async def test_download_is_reauthorized_and_sets_no_store_headers(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    collection = await client.post(
        "/api/knowledge/collections", headers=admin_headers, json={"name": "共享下载测试"}
    )
    assert collection.status_code == 201, collection.text
    uploaded = await client.post(
        "/api/knowledge/upload",
        headers=admin_headers,
        data={"title": "policy.txt", "collection_id": str(collection.json()["id"])},
        files={"file": ("policy.txt", b"download body", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    entry_id = uploaded.json()["id"]
    downloaded = await client.get(
        f"/api/knowledge/{entry_id}/download", headers=admin_headers
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"download body"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["content-disposition"] == 'attachment; filename="policy.txt"'
    assert (
        await client.delete(f"/api/knowledge/{entry_id}", headers=admin_headers)
    ).status_code == 204
    assert (
        await client.get(f"/api/knowledge/{entry_id}/download", headers=admin_headers)
    ).status_code == 404
