from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jose import jwt
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import pytest
from httpx import AsyncClient

from app.auth.security import decode_token
from app.database import SessionLocal
from app.config import get_settings
from app.models import (
    AuditEvent,
    Organization,
    OrganizationMembership,
    Permission,
    Role,
    User,
)
from app.routers import users as users_router


def organization_access_token(user_id: int, organization_id: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "jti": uuid4().hex,
            "organization_id": organization_id,
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


@pytest.mark.asyncio
async def test_user_membership_update_lock_excludes_nullable_eager_join() -> None:
    captured_sql = ""
    expected_row = (object(), object(), object())

    class Result:
        def one_or_none(self):
            return expected_row

    class CapturingSession:
        async def execute(self, statement):
            nonlocal captured_sql
            captured_sql = str(statement.compile(dialect=postgresql.dialect()))
            return Result()

    row = await users_router.get_user_membership_or_404(
        CapturingSession(),
        user_id=7,
        organization_id=3,
        for_update=True,
    )

    assert row == expected_row
    assert "FOR UPDATE OF users, organization_memberships, roles" in captured_sql
    assert "FOR UPDATE OF roles_1" not in captured_sql


@pytest.mark.asyncio
async def test_seed_creates_default_organization_membership_and_permissions() -> None:
    async with SessionLocal() as db:
        organizations = list((await db.scalars(select(Organization))).all())
        admin = await db.scalar(select(User).where(User.username == "admin"))
        membership = await db.scalar(
            select(OrganizationMembership).where(OrganizationMembership.user_id == admin.id)
        )
        permissions = set((await db.scalars(select(Permission.code))).all())

    assert len(organizations) == 1
    assert admin.default_organization_id == organizations[0].id
    assert membership.organization_id == organizations[0].id
    assert membership.role_id == admin.role_id
    assert {"chat:use", "knowledge:read", "org:admin"}.issubset(permissions)


@pytest.mark.asyncio
async def test_manager_can_read_users_but_cannot_manage_organization_users(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "permission-manager",
            "password": "manager-password",
            "email": "permission-manager@example.com",
            "role": "manager",
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/auth/login",
        json={"username": "permission-manager", "password": "manager-password"},
    )
    manager_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/api/users", headers=manager_headers)).status_code == 200
    denied = await client.post(
        "/api/users",
        headers=manager_headers,
        json={
            "username": "manager-created-user",
            "password": "manager-created-password",
            "email": "manager-created@example.com",
            "role": "user",
        },
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_resource_remains_scoped_to_token_when_default_preference_changes(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Organization scope"}
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        original_organization_id = admin.default_organization_id
        new_org = Organization(name="Second Organization", slug="second-organization")
        db.add(new_org)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=new_org.id,
                user_id=admin.id,
                role_id=admin.role_id,
            )
        )
        admin.default_organization_id = new_org.id
        await db.commit()

    response = await client.get(
        f"/api/chat/sessions/{session_id}/messages", headers=admin_headers
    )

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        admin.default_organization_id = original_organization_id
        await db.commit()

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_role_assignment_writes_metadata_only_audit_event(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "audit-target",
            "password": "audit-password",
            "email": "audit-target@example.com",
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text
    assigned = await client.put(
        f"/api/users/{created.json()['id']}/roles",
        headers=admin_headers,
        json={"role": "manager"},
    )
    assert assigned.status_code == 200, assigned.text

    async with SessionLocal() as db:
        events = list(
            (
                await db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "user.role.assign",
                        AuditEvent.resource_id == str(created.json()["id"]),
                    )
                )
            ).all()
        )

    assert len(events) == 1
    assert events[0].details == {"role": "manager"}
    assert "password" not in str(events[0].details)
    assert "prompt" not in str(events[0].details)


@pytest.mark.asyncio
async def test_token_organization_without_matching_membership_is_rejected(
    client: AsyncClient,
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        foreign_organization = Organization(
            name="Token Mismatch Organization",
            slug="token-mismatch-organization",
        )
        db.add(foreign_organization)
        await db.commit()
        await db.refresh(foreign_organization)
        token = organization_access_token(admin.id, foreign_organization.id)

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "No active organization"


@pytest.mark.asyncio
async def test_inactive_token_organization_is_rejected(client: AsyncClient) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        organization = await db.get(Organization, admin.default_organization_id)
        assert organization is not None
        organization_id = organization.id
        token = organization_access_token(admin.id, organization.id)
        organization.is_active = False
        await db.commit()

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    async with SessionLocal() as db:
        organization = await db.get(Organization, organization_id)
        assert organization is not None
        organization.is_active = True
        await db.commit()

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "No active organization"


@pytest.mark.asyncio
async def test_current_role_is_read_from_membership_not_user_default(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "membership-role-user",
            "password": "membership-role-password",
            "email": "membership-role-user@example.com",
            "role": "user",
        },
    )
    assert created.status_code == 201, created.text

    async with SessionLocal() as db:
        user = await db.get(User, created.json()["id"])
        admin_role = await db.scalar(select(Role).where(Role.name == "admin"))
        assert user is not None
        assert admin_role is not None
        user.role_id = admin_role.id
        await db.commit()

    login = await client.post(
        "/api/auth/login",
        json={"username": "membership-role-user", "password": "membership-role-password"},
    )
    assert login.status_code == 200, login.text
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "user"


@pytest.mark.asyncio
async def test_last_admin_cannot_deactivate_self_through_update(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        admin_id = admin.id

    response = await client.put(
        f"/api/users/{admin_id}",
        headers=admin_headers,
        json={"is_active": False},
    )

    async with SessionLocal() as db:
        admin = await db.get(User, admin_id)
        assert admin is not None
        admin.is_active = True
        await db.commit()

    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "Organization must retain an active administrator"
    )


@pytest.mark.asyncio
async def test_organization_list_switch_and_refresh_keep_token_family_scoped(
    client: AsyncClient,
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        manager_role = await db.scalar(select(Role).where(Role.name == "manager"))
        assert admin is not None
        assert manager_role is not None
        original_organization_id = admin.default_organization_id
        target = Organization(name="Switch Target", slug="switch-target")
        db.add(target)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=target.id,
                user_id=admin.id,
                role_id=manager_role.id,
            )
        )
        await db.commit()
        target_id = target.id

    login = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["organization_id"] == original_organization_id
    assert decode_token(login.json()["access_token"], "access")["organization_id"] == (
        original_organization_id
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    organizations = await client.get("/api/auth/organizations", headers=headers)
    assert organizations.status_code == 200, organizations.text
    assert organizations.json()["current_organization_id"] == original_organization_id
    assert {item["organization_id"] for item in organizations.json()["items"]} >= {
        original_organization_id,
        target_id,
    }

    switched = await client.post(
        "/api/auth/switch-organization",
        headers=headers,
        json={"organization_id": target_id},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["organization_id"] == target_id
    assert decode_token(switched.json()["access_token"], "access")["organization_id"] == target_id
    assert decode_token(switched.json()["refresh_token"], "refresh")["organization_id"] == target_id

    refreshed = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": switched.json()["refresh_token"]},
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["organization_id"] == target_id
    assert decode_token(refreshed.json()["access_token"], "access")["organization_id"] == target_id

    me = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["organization_id"] == target_id
    assert me.json()["role"] == "manager"


@pytest.mark.asyncio
async def test_logout_revokes_only_the_current_organization_refresh_token(
    client: AsyncClient,
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        manager_role = await db.scalar(select(Role).where(Role.name == "manager"))
        assert admin is not None
        assert manager_role is not None
        original_organization_id = admin.default_organization_id
        target = Organization(
            name="Logout Isolation Organization",
            slug=f"logout-isolation-{uuid4().hex}",
        )
        db.add(target)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=target.id,
                user_id=admin.id,
                role_id=manager_role.id,
            )
        )
        await db.commit()
        target_id = target.id

    login = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200, login.text
    original_refresh_token = login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    switched = await client.post(
        "/api/auth/switch-organization",
        headers=headers,
        json={"organization_id": target_id},
    )
    assert switched.status_code == 200, switched.text
    target_refresh_token = switched.json()["refresh_token"]

    revoked = await client.post(
        "/api/auth/logout",
        json={"refresh_token": target_refresh_token},
    )
    assert revoked.status_code == 204
    assert (
        await client.post(
            "/api/auth/refresh", json={"refresh_token": target_refresh_token}
        )
    ).status_code == 401

    original_refresh = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": original_refresh_token},
    )
    assert original_refresh.status_code == 200, original_refresh.text
    assert original_refresh.json()["organization_id"] == original_organization_id


@pytest.mark.asyncio
async def test_last_admin_cannot_be_demoted(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        admin_role = await db.scalar(select(Role).where(Role.name == "admin"))
        assert admin is not None
        assert admin_role is not None
        admin_id = admin.id
        admin_role_id = admin_role.id

    response = await client.put(
        f"/api/users/{admin_id}/roles",
        headers=admin_headers,
        json={"role": "user"},
    )

    async with SessionLocal() as db:
        admin = await db.get(User, admin_id)
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == admin.default_organization_id,
                OrganizationMembership.user_id == admin_id,
            )
        )
        assert admin is not None
        assert membership is not None
        admin.role_id = admin_role_id
        membership.role_id = admin_role_id
        await db.commit()

    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "Organization must retain an active administrator"
    )
