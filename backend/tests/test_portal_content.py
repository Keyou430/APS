from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import (
    AuditEvent,
    Organization,
    OrganizationMembership,
    Reminder,
    Role,
    User,
)


async def current_organization_id() -> int:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == admin.id,
                OrganizationMembership.organization_id == admin.default_organization_id,
            )
        )
        assert membership is not None
        return membership.organization_id


async def create_announcement(client, headers: dict[str, str], suffix: str) -> dict:
    response = await client.post(
        "/api/enterprise/announcements",
        headers=headers,
        json={
            "title": f"Phase C announcement {suffix}",
            "summary": f"Summary {suffix}",
            "content": f"Content {suffix}",
            "priority": "important",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_announcement_lifecycle_read_state_and_audit_are_persistent(
    client, admin_headers: dict[str, str]
) -> None:
    draft = await create_announcement(client, admin_headers, "lifecycle")
    assert draft["status"] == "draft"

    before_publish = await client.get("/api/enterprise/portal", headers=admin_headers)
    assert before_publish.status_code == 200, before_publish.text
    assert draft["id"] not in {item["id"] for item in before_publish.json()["announcements"]}

    published = await client.post(
        f"/api/enterprise/announcements/{draft['id']}/publish",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["publishedAt"] is not None

    pinned = await client.post(
        f"/api/enterprise/announcements/{draft['id']}/pin",
        headers=admin_headers,
        json={"is_pinned": True},
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["isPinned"] is True

    marked = await client.post(
        f"/api/enterprise/announcements/{draft['id']}/read",
        headers=admin_headers,
    )
    assert marked.status_code == 204, marked.text
    for _ in range(2):
        refreshed = await client.get("/api/enterprise/portal", headers=admin_headers)
        announcement = next(
            item for item in refreshed.json()["announcements"] if item["id"] == draft["id"]
        )
        assert announcement["isRead"] is True

    withdrawn = await client.post(
        f"/api/enterprise/announcements/{draft['id']}/withdraw",
        headers=admin_headers,
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "withdrawn"
    portal = await client.get("/api/enterprise/portal", headers=admin_headers)
    assert draft["id"] not in {item["id"] for item in portal.json()["announcements"]}

    async with SessionLocal() as db:
        actions = set(
            await db.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.resource_type == "portal_announcement",
                    AuditEvent.resource_id == draft["id"],
                )
            )
        )
    assert {
        "portal.announcement.create",
        "portal.announcement.publish",
        "portal.announcement.pin",
        "portal.announcement.withdraw",
    }.issubset(actions)


async def test_announcements_are_stably_sorted_and_regular_members_are_read_only(
    client, admin_headers: dict[str, str]
) -> None:
    first = await create_announcement(client, admin_headers, "stable-first")
    second = await create_announcement(client, admin_headers, "stable-second")
    for announcement in (first, second):
        response = await client.post(
            f"/api/enterprise/announcements/{announcement['id']}/publish",
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
    pinned = await client.post(
        f"/api/enterprise/announcements/{first['id']}/pin",
        headers=admin_headers,
        json={"is_pinned": True},
    )
    assert pinned.status_code == 200, pinned.text

    listing = await client.get(
        "/api/enterprise/announcements?page=1&page_size=20", headers=admin_headers
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"][0]["id"] == first["id"]
    assert listing.json()["page"] == 1
    assert listing.json()["pageSize"] == 20

    async with SessionLocal() as db:
        organization_id = await current_organization_id()
        user_role = await db.scalar(select(Role).where(Role.name == "user"))
        assert user_role is not None
        member = User(
            username="portal-read-only-member",
            email="portal-read-only-member@example.com",
            password_hash=hash_password("portal-read-only-password"),
            role_id=user_role.id,
            default_organization_id=organization_id,
        )
        db.add(member)
        await db.flush()
        db.add(OrganizationMembership(
            organization_id=organization_id,
            user_id=member.id,
            role_id=user_role.id,
        ))
        await db.commit()

    login = await client.post(
        "/api/auth/login",
        json={"username": "portal-read-only-member", "password": "portal-read-only-password"},
    )
    assert login.status_code == 200, login.text
    member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/enterprise/portal", headers=member_headers)).status_code == 200
    denied = await client.post(
        "/api/enterprise/announcements",
        headers=member_headers,
        json={"title": "Denied", "summary": "Denied", "priority": "normal"},
    )
    assert denied.status_code == 403


async def test_portal_content_uses_token_organization_and_fails_closed_cross_org(
    client, admin_headers: dict[str, str]
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        admin_role = await db.scalar(select(Role).where(Role.name == "admin"))
        assert admin is not None and admin_role is not None
        default_organization_id = admin.default_organization_id
        second = Organization(name="Portal Isolation Organization", slug="portal-isolation-org")
        db.add(second)
        await db.flush()
        db.add(OrganizationMembership(
            organization_id=second.id,
            user_id=admin.id,
            role_id=admin_role.id,
        ))
        await db.commit()
        second_id = second.id

    switched = await client.post(
        "/api/auth/switch-organization",
        headers=admin_headers,
        json={"organization_id": second_id},
    )
    assert switched.status_code == 200, switched.text
    second_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
    second_announcement = await create_announcement(client, second_headers, "other-org")
    published = await client.post(
        f"/api/enterprise/announcements/{second_announcement['id']}/publish",
        headers=second_headers,
    )
    assert published.status_code == 200, published.text

    original = await client.get("/api/enterprise/announcements", headers=admin_headers)
    assert second_announcement["id"] not in {item["id"] for item in original.json()["items"]}
    cross_read = await client.post(
        f"/api/enterprise/announcements/{second_announcement['id']}/read",
        headers=admin_headers,
    )
    assert cross_read.status_code == 404

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        assert admin.default_organization_id == default_organization_id


async def test_portal_todo_mutation_quick_link_allowlist_and_activity_redaction(
    client, admin_headers: dict[str, str]
) -> None:
    organization_id = await current_organization_id()
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        reminder = Reminder(
            organization_id=organization_id,
            user_id=admin.id,
            title="Persisted portal todo",
            description="Portal todo detail",
            due_date=datetime.now(UTC) + timedelta(days=1),
            status="active",
        )
        db.add(reminder)
        await db.flush()
        db.add(AuditEvent(
            organization_id=organization_id,
            actor_user_id=admin.id,
            action="organization.unit.update",
            resource_type="organization_unit",
            resource_id="1",
            details={"token": "must-not-leak", "content": "private-body"},
        ))
        db.add(AuditEvent(
            organization_id=organization_id,
            actor_user_id=admin.id,
            action="internal.secret.rotate",
            resource_type="secret",
            resource_id="hidden",
            details={"token": "also-hidden"},
        ))
        await db.commit()
        reminder_id = reminder.id

    portal = await client.get("/api/enterprise/portal", headers=admin_headers)
    assert portal.status_code == 200, portal.text
    payload = portal.json()
    todo = next(item for item in payload["todos"] if item["id"] == str(reminder_id))
    assert todo["completed"] is False
    urls = {item["url"] for item in payload["quickLinks"]}
    assert "/organization/structure" in urls
    assert urls.issubset({"/knowledge/ai", "/workspace", "/organization/structure", "/calendar"})
    serialized_activities = str(payload["activities"])
    assert "must-not-leak" not in serialized_activities
    assert "private-body" not in serialized_activities
    assert "also-hidden" not in serialized_activities
    assert "organization.unit.update" not in serialized_activities

    completed = await client.put(
        f"/api/enterprise/portal/todos/{reminder_id}",
        headers=admin_headers,
        json={"completed": True},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed"] is True
    refreshed = await client.get("/api/enterprise/portal", headers=admin_headers)
    todo = next(item for item in refreshed.json()["todos"] if item["id"] == str(reminder_id))
    assert todo["completed"] is True
