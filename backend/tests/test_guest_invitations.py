from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import asyncio

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models import KnowledgeAccessGrant, Organization, OrganizationInvitation, OrganizationMembership, Role, User
from app.auth.security import verify_password
from app.services.guest_invitation_delivery import InvitationDeliveryError
from app.services.invitations import reset_invitation_accept_limiter
from app.services.invitations import locked_membership_statement, locked_user_by_email_statement
from test_knowledge_authorization import create_member


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_invitation_limits() -> None:
    reset_invitation_accept_limiter()


async def test_postgres_invitation_locks_target_primary_tables_only() -> None:
    user_sql = str(locked_user_by_email_statement("guest@example.com").compile(dialect=postgresql.dialect()))
    membership_sql = str(locked_membership_statement(1, 2).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF users" in user_sql
    assert "FOR UPDATE OF organization_memberships" in membership_sql


def invitation_payload(email: str, entry_id: int) -> dict:
    now = datetime.now(UTC)
    return {
        "email": email,
        "token_expires_at": (now + timedelta(hours=2)).isoformat(),
        "membership_expires_at": (now + timedelta(days=14)).isoformat(),
        "resource_ids": [entry_id],
    }


async def organization_id() -> int:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None and admin.default_organization_id is not None
        return admin.default_organization_id


async def test_external_guests_default_off_and_endpoints_fail_closed(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    assert Settings().feature_external_guests is False
    assert (await client.get("/api/invitations", headers=admin_headers)).status_code == 404
    assert (await client.get("/api/invitations")).status_code == 404
    assert (
        await client.post(
            "/api/invitations/accept",
            json={"token": "not-a-token", "username": "guest-user", "password": "password-123"},
        )
    ).status_code == 404


async def test_production_guest_flag_requires_smtp_delivery_adapter() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", feature_external_guests=True, guest_invitation_delivery_adapter="test")
    with pytest.raises(ValidationError):
        Settings(app_env="container", feature_external_guests=True, guest_invitation_delivery_adapter="test")
    with pytest.raises(ValidationError):
        Settings(
            guest_invitation_delivery_adapter="smtp",
            guest_invitation_public_base_url="https://platform.example",
            smtp_host="smtp.qq.com",
            smtp_username="sender@example.com",
            smtp_password="smtp-authorization-code",
        )

    settings = Settings(
        app_env="production",
        rag_embedding_enabled=True,
        jwt_secret_key="production-only-jwt-secret-key",
        admin_password="production-admin-password",
        feature_external_guests=True,
        guest_invitation_delivery_adapter="smtp",
        guest_invitation_public_base_url="https://platform.example",
        smtp_host="smtp.qq.com",
        smtp_username="sender@example.com",
        smtp_password="smtp-authorization-code",
        guest_invitation_recipient_allowlist="recipient@example.com",
        rag_query_audit_hmac_key="production-only-audit-hmac-key",
    )
    assert settings.guest_invitation_delivery_adapter == "smtp"
    assert settings.guest_invitation_recipient_allowed("  RECIPIENT@EXAMPLE.COM  ") is True


async def test_production_like_settings_reject_known_default_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="container", jwt_secret_key="development-only-change-me")

    settings = Settings(
        app_env="container",
        single_user_mode=True,
        admin_password="admin123",
        jwt_secret_key="production-only-jwt-secret-key",
        rag_query_audit_hmac_key="production-only-audit-hmac-key",
    )
    assert settings.admin_password == "admin123"

    with pytest.raises(ValidationError):
        Settings(
            app_env="container",
            single_user_mode=False,
            admin_password="admin123",
            jwt_secret_key="production-only-jwt-secret-key",
            rag_query_audit_hmac_key="production-only-audit-hmac-key",
        )


async def test_smtp_create_delivers_without_returning_plaintext_token(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deliveries: list[dict[str, object]] = []

    async def capture_delivery(**kwargs: object) -> None:
        deliveries.append(kwargs)

    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    monkeypatch.setenv("GUEST_INVITATION_DELIVERY_ADAPTER", "smtp")
    monkeypatch.setenv("GUEST_INVITATION_PUBLIC_BASE_URL", "https://platform.example")
    monkeypatch.setenv("SMTP_HOST", "smtp.qq.com")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-authorization-code")
    monkeypatch.setenv("GUEST_INVITATION_RECIPIENT_ALLOWLIST", "recipient@example.com")
    monkeypatch.setattr("app.routers.invitations.deliver_invitation", capture_delivery)
    get_settings.cache_clear()
    try:
        entry = await client.post(
            "/api/knowledge",
            headers=admin_headers,
            json={"type": "workflow_result", "title": "SMTP guest resource", "content": "body"},
        )
        response = await client.post(
            "/api/invitations",
            headers=admin_headers,
            json=invitation_payload("recipient@example.com", entry.json()["id"]),
        )

        assert response.status_code == 201, response.text
        assert "token" not in response.json()
        assert deliveries[0]["recipient"] == "recipient@example.com"
        assert len(str(deliveries[0]["token"])) >= 43

        regenerated = await client.post(
            f"/api/invitations/{response.json()['id']}/regenerate",
            headers=admin_headers,
            json={"token_expires_at": (datetime.now(UTC) + timedelta(hours=4)).isoformat()},
        )
        assert regenerated.status_code == 200, regenerated.text
        assert "token" not in regenerated.json()
        assert len(deliveries) == 2
        assert deliveries[1]["token"] != deliveries[0]["token"]
    finally:
        get_settings.cache_clear()


async def test_smtp_delivery_failure_revokes_invitation_and_returns_safe_503(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_delivery(**_kwargs: object) -> None:
        raise InvitationDeliveryError("provider details must not escape")

    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    monkeypatch.setenv("GUEST_INVITATION_DELIVERY_ADAPTER", "smtp")
    monkeypatch.setenv("GUEST_INVITATION_PUBLIC_BASE_URL", "https://platform.example")
    monkeypatch.setenv("SMTP_HOST", "smtp.qq.com")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-authorization-code")
    monkeypatch.setenv("GUEST_INVITATION_RECIPIENT_ALLOWLIST", "failed-recipient@example.com")
    monkeypatch.setattr("app.routers.invitations.deliver_invitation", fail_delivery)
    get_settings.cache_clear()
    try:
        entry = await client.post(
            "/api/knowledge",
            headers=admin_headers,
            json={"type": "workflow_result", "title": "Failed SMTP guest", "content": "body"},
        )
        response = await client.post(
            "/api/invitations",
            headers=admin_headers,
            json=invitation_payload("failed-recipient@example.com", entry.json()["id"]),
        )

        assert response.status_code == 503
        assert response.json()["error"]["message"] == "Invitation delivery failed"
        assert "provider details" not in response.text
        async with SessionLocal() as db:
            invitation = await db.scalar(
                select(OrganizationInvitation).where(
                    OrganizationInvitation.normalized_email == "failed-recipient@example.com"
                )
            )
            assert invitation is not None and invitation.revoked_at is not None
    finally:
        get_settings.cache_clear()


async def test_smtp_rejects_recipient_outside_the_approved_trial_window(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered = False

    async def capture_delivery(**_kwargs: object) -> None:
        nonlocal delivered
        delivered = True

    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    monkeypatch.setenv("GUEST_INVITATION_DELIVERY_ADAPTER", "smtp")
    monkeypatch.setenv("GUEST_INVITATION_PUBLIC_BASE_URL", "https://platform.example")
    monkeypatch.setenv("GUEST_INVITATION_RECIPIENT_ALLOWLIST", "approved@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.qq.com")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-authorization-code")
    monkeypatch.setattr("app.routers.invitations.deliver_invitation", capture_delivery)
    get_settings.cache_clear()
    try:
        entry = await client.post(
            "/api/knowledge",
            headers=admin_headers,
            json={"type": "workflow_result", "title": "Rejected SMTP guest", "content": "body"},
        )
        response = await client.post(
            "/api/invitations",
            headers=admin_headers,
            json=invitation_payload("outside@example.com", entry.json()["id"]),
        )

        assert response.status_code == 403
        assert delivered is False
        async with SessionLocal() as db:
            invitation = await db.scalar(
                select(OrganizationInvitation).where(
                    OrganizationInvitation.normalized_email == "outside@example.com"
                )
            )
            assert invitation is None
    finally:
        get_settings.cache_clear()


async def test_create_returns_token_once_and_list_never_returns_token_or_digest(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    get_settings.cache_clear()
    try:
        entry = await client.post(
            "/api/knowledge",
            headers=admin_headers,
            json={"type": "workflow_result", "title": "Guest resource", "content": "body"},
        )
        response = await client.post(
            "/api/invitations",
            headers=admin_headers,
            json=invitation_payload("  GUEST@Example.COM  ", entry.json()["id"]),
        )
        assert response.status_code == 201, response.text
        created = response.json()
        token = created.pop("token")
        assert len(token) >= 43
        assert created["email"] == "guest@example.com"
        assert created["status"] == "pending"

        async with SessionLocal() as db:
            invitation = await db.get(OrganizationInvitation, created["id"])
            assert invitation is not None
            assert invitation.token_digest == sha256(token.encode()).hexdigest()
            assert token not in repr(invitation.__dict__)

        listed = await client.get("/api/invitations", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        serialized = listed.text.casefold()
        assert token.casefold() not in serialized
        assert "token_digest" not in serialized
        assert "\"token\"" not in serialized
    finally:
        get_settings.cache_clear()


async def login(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    response = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_new_guest_accept_is_transactional_and_guest_is_explicit_grant_only(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    get_settings.cache_clear()
    try:
        entry = await client.post(
            "/api/knowledge",
            headers=admin_headers,
            json={"type": "workflow_result", "title": "Explicit guest file", "content": "guest body"},
        )
        organization_entry = await client.post(
            "/api/knowledge",
            headers=admin_headers,
            json={"type": "workflow_result", "title": "Internal only", "content": "internal body"},
        )
        await client.put(
            f"/api/knowledge/{organization_entry.json()['id']}/access",
            headers=admin_headers,
            json={"visibility": "organization_members"},
        )
        created = await client.post(
            "/api/invitations",
            headers=admin_headers,
            json=invitation_payload("new-guest@example.com", entry.json()["id"]),
        )
        token = created.json()["token"]
        accepted = await client.post(
            "/api/invitations/accept",
            json={"token": token, "username": "new-guest", "password": "guest-password-123"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted"

        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.normalized_email == "new-guest@example.com"))
            assert user is not None and verify_password("guest-password-123", user.password_hash)
            membership = await db.scalar(select(OrganizationMembership).where(
                OrganizationMembership.organization_id == accepted.json()["organization_id"],
                OrganizationMembership.user_id == user.id,
            ))
            assert membership is not None and membership.member_type == "guest" and membership.is_active
            grants = list((await db.scalars(select(KnowledgeAccessGrant).where(
                KnowledgeAccessGrant.grantee_membership_id == membership.id,
                KnowledgeAccessGrant.revoked_at.is_(None),
            ))).all())
            assert [grant.knowledge_entry_id for grant in grants] == [entry.json()["id"]]

        guest_headers = await login(client, "new-guest", "guest-password-123")
        profile = await client.get("/api/auth/me", headers=guest_headers)
        assert profile.status_code == 200
        assert profile.json()["member_type"] == "guest"
        assert set(profile.json()["permissions"]) == {
            "chat:use",
            "knowledge:read",
            "experience:read",
        }
        assert (await client.get(f"/api/knowledge/{entry.json()['id']}", headers=guest_headers)).status_code == 200
        assert (await client.get(f"/api/knowledge/{organization_entry.json()['id']}", headers=guest_headers)).status_code == 404
        assert (await client.post("/api/knowledge/upload", headers=guest_headers, files={"file": ("guest.txt", b"nope", "text/plain")}, data={"title": "guest"})).status_code == 403
        assert (await client.put(f"/api/knowledge/{entry.json()['id']}", headers=guest_headers, json={"title": "changed"})).status_code == 403
        assert (await client.get(f"/api/knowledge/{entry.json()['id']}/download", headers=guest_headers)).status_code == 404
        assert (await client.get("/api/users", headers=guest_headers)).status_code == 403
        assert (await client.get("/api/knowledge/members", headers=guest_headers)).status_code == 403
        assert (await client.get("/api/knowledge/operations/overview", headers=guest_headers)).status_code == 403
        assert (await client.post("/api/chat/sessions", headers=guest_headers, json={"surface": "agent"})).status_code == 403
        assert (await client.post("/api/chat/sessions", headers=guest_headers, json={"surface": "knowledge"})).status_code == 201
        assert (await client.post("/api/hermes/profiles", headers=guest_headers, json={"user_id": accepted.json()["user_id"]})).status_code == 403
        revoked = await client.post(
            f"/api/invitations/guest-memberships/{accepted.json()['membership_id']}/revoke",
            headers=admin_headers,
        )
        assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
        async with SessionLocal() as db:
            active_grants = list((await db.scalars(select(KnowledgeAccessGrant).where(
                KnowledgeAccessGrant.grantee_membership_id == accepted.json()["membership_id"],
                KnowledgeAccessGrant.revoked_at.is_(None),
            ))).all())
            assert active_grants == []
        assert (await client.get("/api/auth/me", headers=guest_headers)).status_code == 403
    finally:
        get_settings.cache_clear()


async def test_existing_account_must_authenticate_and_internal_membership_is_not_downgraded(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    get_settings.cache_clear()
    try:
        async with SessionLocal() as db:
            admin = await db.scalar(select(User).where(User.username == "admin"))
            assert admin is not None and admin.default_organization_id is not None
            organization_id = admin.default_organization_id
        existing, membership = await create_member(username="existing-invitee", organization_id=organization_id)
        original_hash = existing.password_hash
        entry = await client.post(
            "/api/knowledge", headers=admin_headers,
            json={"type": "workflow_result", "title": "Existing user resource", "content": "body"},
        )
        created = await client.post(
            "/api/invitations", headers=admin_headers,
            json=invitation_payload(existing.email.upper(), entry.json()["id"]),
        )
        token = created.json()["token"]
        assert (await client.post("/api/invitations/accept", json={"token": token})).status_code == 403
        assert (await client.post("/api/invitations/accept", headers=admin_headers, json={"token": token})).status_code == 403

        existing_headers = await login(client, existing.username, "authorization-password")
        accepted = await client.post("/api/invitations/accept", headers=existing_headers, json={"token": token})
        assert accepted.status_code == 200, accepted.text
        repeated = await client.post("/api/invitations/accept", headers=existing_headers, json={"token": token})
        assert repeated.status_code == 200 and repeated.json()["status"] == "already_accepted"
        async with SessionLocal() as db:
            refreshed_user = await db.get(User, existing.id)
            refreshed_membership = await db.get(OrganizationMembership, membership.id)
            assert refreshed_user is not None and refreshed_user.password_hash == original_hash
            assert refreshed_membership is not None and refreshed_membership.member_type == "internal"
    finally:
        get_settings.cache_clear()


async def test_accept_rate_limit_is_uniform_for_invalid_tokens(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.invitations import reset_invitation_accept_limiter

    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    get_settings.cache_clear()
    reset_invitation_accept_limiter()
    try:
        statuses = [
            (await client.post(
                "/api/invitations/accept",
                json={"token": f"invalid-token-{index:02d}".ljust(32, "x")},
            )).status_code
            for index in range(9)
        ]
        assert statuses[:8] == [404] * 8
        assert statuses[8] == 429
    finally:
        reset_invitation_accept_limiter()
        get_settings.cache_clear()


async def test_concurrent_accept_consumes_one_pending_token(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    get_settings.cache_clear()
    try:
        entry = await client.post(
            "/api/knowledge", headers=admin_headers,
            json={"type": "workflow_result", "title": "Concurrent guest", "content": "body"},
        )
        created = await client.post(
            "/api/invitations", headers=admin_headers,
            json=invitation_payload("concurrent-guest@example.com", entry.json()["id"]),
        )
        token = created.json()["token"]
        responses = await asyncio.gather(*[
            client.post(
                "/api/invitations/accept",
                json={"token": token, "username": "concurrent-guest", "password": "guest-password-123"},
            )
            for _ in range(2)
        ])
        assert sorted(response.status_code for response in responses) == [200, 409]
    finally:
        get_settings.cache_clear()


async def test_cross_organization_existing_user_and_expired_or_inactive_scope_fail_closed(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_EXTERNAL_GUESTS", "true")
    get_settings.cache_clear()
    try:
        async with SessionLocal() as db:
            admin = await db.scalar(select(User).where(User.username == "admin"))
            admin_role = await db.scalar(select(Role).where(Role.name == "admin"))
            assert admin is not None and admin_role is not None
            second = Organization(name="Guest target", slug="guest-target")
            db.add(second)
            await db.flush()
            db.add(OrganizationMembership(
                organization_id=second.id,
                user_id=admin.id,
                role_id=admin_role.id,
                member_type="internal",
            ))
            await db.commit()
            second_id = second.id

        existing, _ = await create_member(
            username="cross-organization-invitee",
            organization_id=await organization_id(),
        )
        switched = await client.post(
            "/api/auth/switch-organization",
            headers=admin_headers,
            json={"organization_id": second_id},
        )
        assert switched.status_code == 200, switched.text
        second_admin_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
        entry = await client.post(
            "/api/knowledge",
            headers=second_admin_headers,
            json={"type": "workflow_result", "title": "Cross organization", "content": "body"},
        )
        invitation = await client.post(
            "/api/invitations",
            headers=second_admin_headers,
            json=invitation_payload(existing.email, entry.json()["id"]),
        )
        existing_headers = await login(client, existing.username, "authorization-password")
        accepted = await client.post(
            "/api/invitations/accept",
            headers=existing_headers,
            json={"token": invitation.json()["token"]},
        )
        assert accepted.status_code == 200, accepted.text
        membership_id = accepted.json()["membership_id"]

        switched_existing = await client.post(
            "/api/auth/switch-organization",
            headers=existing_headers,
            json={"organization_id": second_id},
        )
        assert switched_existing.status_code == 200, switched_existing.text
        guest_headers = {"Authorization": f"Bearer {switched_existing.json()['access_token']}"}

        async with SessionLocal() as db:
            membership = await db.get(OrganizationMembership, membership_id)
            assert membership is not None and membership.member_type == "guest"
            membership.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
        assert (await client.get("/api/auth/me", headers=guest_headers)).status_code == 403

        async with SessionLocal() as db:
            membership = await db.get(OrganizationMembership, membership_id)
            organization = await db.get(Organization, second_id)
            assert membership is not None and organization is not None
            membership.expires_at = datetime.now(UTC) + timedelta(days=1)
            organization.is_active = False
            await db.commit()
        assert (await client.get("/api/auth/me", headers=guest_headers)).status_code == 403
    finally:
        async with SessionLocal() as db:
            second = await db.get(Organization, second_id)
            if second is not None:
                await db.delete(second)
                await db.commit()
        get_settings.cache_clear()
