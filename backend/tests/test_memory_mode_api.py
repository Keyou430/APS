from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import ChatSession, OrganizationMembership, Role, User


pytestmark = pytest.mark.asyncio


async def test_memory_mode_is_owner_controlled_and_knowledge_only(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    knowledge = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Memory mode", "surface": "knowledge"},
    )
    assert knowledge.status_code == 201, knowledge.text
    knowledge_id = knowledge.json()["id"]
    assert knowledge.json()["memory_mode"] == "off"

    updated = await client.put(
        f"/api/chat/sessions/{knowledge_id}/memory-mode",
        headers=admin_headers,
        json={"memory_mode": "auto", "expected_revision": 1},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() == {"memory_mode": "auto", "revision": 2}

    agent = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Agent mode", "surface": "agent"},
    )
    assert agent.status_code == 201, agent.text
    rejected = await client.put(
        f"/api/chat/sessions/{agent.json()['id']}/memory-mode",
        headers=admin_headers,
        json={"memory_mode": "auto", "expected_revision": 1},
    )
    assert rejected.status_code == 404


async def test_chat_session_responses_expose_revision_for_memory_mode_cas(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Memory CAS reload", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["revision"] == 1

    listed = await client.get("/api/chat/sessions", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    matching = [
        item
        for item in listed.json()["items"]
        if item["id"] == created.json()["id"]
    ]
    assert matching
    assert matching[0]["revision"] == 1


async def test_memory_mode_cannot_change_during_active_run(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Memory active run", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text
    async with SessionLocal() as db:
        session = await db.get(ChatSession, created.json()["id"])
        assert session is not None
        session.active_hermes_run_id = "run-in-flight"
        session.active_run_status = "running"
        await db.commit()

    changed = await client.put(
        f"/api/chat/sessions/{created.json()['id']}/memory-mode",
        headers=admin_headers,
        json={"memory_mode": "auto", "expected_revision": 1},
    )

    assert changed.status_code == 409
    async with SessionLocal() as db:
        session = await db.get(ChatSession, created.json()["id"])
        assert session is not None
        assert session.memory_mode == "off"
        assert session.revision == 1


async def test_guest_without_memory_permission_cannot_change_mode_or_read_memory(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Admin memory session", "surface": "knowledge"},
    )
    assert created.status_code == 201
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        guest_role = await db.scalar(select(Role).where(Role.name == "guest"))
        assert admin is not None and guest_role is not None
        guest = User(
            username="phase-d-memory-guest",
            email="phase-d-memory-guest@example.com",
            password_hash=hash_password("phase-d-memory-guest-password"),
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
            )
        )
        await db.commit()
    login = await client.post(
        "/api/auth/login",
        json={
            "username": "phase-d-memory-guest",
            "password": "phase-d-memory-guest-password",
        },
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    changed = await client.put(
        f"/api/chat/sessions/{created.json()['id']}/memory-mode",
        headers=headers,
        json={"memory_mode": "auto", "expected_revision": 1},
    )
    assert changed.status_code == 403
    assert (await client.get("/api/memory", headers=headers)).status_code == 403
