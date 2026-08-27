import asyncio

from sqlalchemy import select

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import AuditEvent, Organization, OrganizationMembership, Role, User, WorkItem


async def create_internal_member(client, username: str) -> tuple[dict[str, str], int]:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        role = await db.scalar(select(Role).where(Role.name == "user"))
        assert admin is not None and role is not None
        member = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password("work-item-password"),
            role_id=role.id,
            default_organization_id=admin.default_organization_id,
        )
        db.add(member)
        await db.flush()
        membership = OrganizationMembership(
            organization_id=admin.default_organization_id,
            user_id=member.id,
            role_id=role.id,
        )
        db.add(membership)
        await db.commit()
        membership_id = membership.id
    login = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "work-item-password"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, membership_id


async def current_admin_membership_id() -> int:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == admin.default_organization_id,
                OrganizationMembership.user_id == admin.id,
            )
        )
        assert membership is not None
        return membership.id


async def create_work_item(
    client,
    headers: dict[str, str],
    *,
    title: str,
    assignee_membership_id: int | None = None,
    origin: str = "manual",
    source_ref: str | None = None,
) -> dict:
    payload = {
        "title": title,
        "description": "Visible task description",
        "priority": "high",
        "origin": origin,
        "sourceRef": source_ref,
    }
    if assignee_membership_id is not None:
        payload["assigneeMembershipId"] = assignee_membership_id
    response = await client.post("/api/work-items", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_work_item_status_transitions_write_append_only_events(
    client, admin_headers: dict[str, str]
) -> None:
    item = await create_work_item(
        client,
        admin_headers,
        title="Traceable work item",
        origin="agent",
        source_ref="agent:run/phase-c-123",
    )
    assert item["status"] == "pending"
    assert item["sourceRef"] == "agent:run/phase-c-123"

    started = await client.patch(
        f"/api/work-items/{item['id']}/status",
        headers=admin_headers,
        json={"status": "in_progress"},
    )
    assert started.status_code == 200, started.text
    completed = await client.patch(
        f"/api/work-items/{item['id']}/status",
        headers=admin_headers,
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text

    invalid = await client.patch(
        f"/api/work-items/{item['id']}/status",
        headers=admin_headers,
        json={"status": "in_progress"},
    )
    assert invalid.status_code == 409

    events = await client.get(
        f"/api/work-items/{item['id']}/events", headers=admin_headers
    )
    assert events.status_code == 200, events.text
    transitions = [(event["fromStatus"], event["toStatus"]) for event in events.json()["items"]]
    assert transitions == [(None, "pending"), ("pending", "in_progress"), ("in_progress", "completed")]
    event_id = events.json()["items"][0]["id"]
    assert (await client.patch(f"/api/work-items/events/{event_id}", headers=admin_headers, json={})).status_code == 405
    assert (await client.delete(f"/api/work-items/events/{event_id}", headers=admin_headers)).status_code == 405

    async with SessionLocal() as db:
        membership = await db.get(
            OrganizationMembership, item["createdByMembershipId"]
        )
        assert membership is not None
        audits = list(
            (
                await db.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.resource_type == "work_item",
                        AuditEvent.resource_id == str(item["id"]),
                    )
                    .order_by(AuditEvent.id)
                )
            ).all()
        )
        assert [audit.action for audit in audits] == [
            "work_item.create",
            "work_item.status.update",
            "work_item.status.update",
        ]
        assert all(
            audit.organization_id == membership.organization_id
            and audit.actor_user_id == membership.user_id
            for audit in audits
        )


async def test_concurrent_status_updates_preserve_one_traceable_event_chain(
    client, admin_headers: dict[str, str]
) -> None:
    item = await create_work_item(
        client,
        admin_headers,
        title="Concurrent work item",
    )

    completed, cancelled = await asyncio.gather(
        client.patch(
            f"/api/work-items/{item['id']}/status",
            headers=admin_headers,
            json={"status": "completed"},
        ),
        client.patch(
            f"/api/work-items/{item['id']}/status",
            headers=admin_headers,
            json={"status": "cancelled"},
        ),
    )

    assert sorted([completed.status_code, cancelled.status_code]) == [200, 409]
    events = await client.get(
        f"/api/work-items/{item['id']}/events", headers=admin_headers
    )
    assert events.status_code == 200, events.text
    transitions = [
        (event["fromStatus"], event["toStatus"])
        for event in events.json()["items"]
    ]
    assert transitions[0] == (None, "pending")
    assert transitions[1:] in [
        [("pending", "completed")],
        [("pending", "cancelled")],
    ]


async def test_work_item_details_can_be_edited_reopened_and_deleted(
    client, admin_headers: dict[str, str]
) -> None:
    item = await create_work_item(
        client,
        admin_headers,
        title="Editable work item",
    )

    updated = await client.patch(
        f"/api/work-items/{item['id']}",
        headers=admin_headers,
        json={
            "title": "Edited work item",
            "description": "Updated task details",
            "priority": "low",
            "dueAt": "2026-08-12T09:30:00+08:00",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Edited work item"
    assert updated.json()["description"] == "Updated task details"
    assert updated.json()["priority"] == "low"
    assert updated.json()["dueAt"].startswith("2026-08-12T09:30:00")

    completed = await client.patch(
        f"/api/work-items/{item['id']}/status",
        headers=admin_headers,
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text
    reopened = await client.patch(
        f"/api/work-items/{item['id']}/status",
        headers=admin_headers,
        json={"status": "pending"},
    )
    assert reopened.status_code == 200, reopened.text

    deleted = await client.delete(
        f"/api/work-items/{item['id']}", headers=admin_headers
    )
    assert deleted.status_code == 204, deleted.text
    assert (
        await client.get(f"/api/work-items/{item['id']}", headers=admin_headers)
    ).status_code == 404


async def test_work_item_source_ref_rejects_prompt_or_body_content(
    client, admin_headers: dict[str, str]
) -> None:
    unsafe = await client.post(
        "/api/work-items",
        headers=admin_headers,
        json={
            "title": "Unsafe source",
            "origin": "chat",
            "sourceRef": "This is a full user prompt with private body content",
        },
    )
    assert unsafe.status_code == 422

    safe = await create_work_item(
        client,
        admin_headers,
        title="Safe source",
        origin="chat",
        source_ref="chat:session/42#turn-8",
    )
    assert "private body" not in str(safe).lower()


async def test_members_see_only_their_tasks_while_admin_can_filter_by_department(
    client, admin_headers: dict[str, str]
) -> None:
    member_headers, member_membership_id = await create_internal_member(
        client, "work-item-member-scope"
    )
    admin_membership_id = await current_admin_membership_id()
    member_item = await create_work_item(
        client,
        admin_headers,
        title="Member scoped item",
        assignee_membership_id=member_membership_id,
    )
    admin_item = await create_work_item(
        client,
        admin_headers,
        title="Admin scoped item",
        assignee_membership_id=admin_membership_id,
    )

    member_list = await client.get("/api/work-items", headers=member_headers)
    assert member_list.status_code == 200, member_list.text
    assert {item["id"] for item in member_list.json()["items"]} == {member_item["id"]}
    assert (await client.get(f"/api/work-items/{admin_item['id']}", headers=member_headers)).status_code == 404

    structure = await client.get("/api/organization/structure", headers=admin_headers)
    assert structure.status_code == 200, structure.text
    root_unit_id = next(unit["id"] for unit in structure.json()["units"] if unit["parent_id"] is None)
    filtered = await client.get(
        f"/api/work-items?unit_id={root_unit_id}", headers=admin_headers
    )
    assert filtered.status_code == 200, filtered.text
    assert {member_item["id"], admin_item["id"]}.issubset(
        {item["id"] for item in filtered.json()["items"]}
    )

    forbidden_filter = await client.get(
        f"/api/work-items?unit_id={root_unit_id}", headers=member_headers
    )
    assert forbidden_filter.status_code == 403


async def test_work_item_from_another_organization_fails_closed(
    client, admin_headers: dict[str, str]
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        role = await db.scalar(select(Role).where(Role.name == "admin"))
        assert admin is not None and role is not None
        foreign = Organization(
            name="Work item boundary organization",
            slug="work-item-boundary-organization",
        )
        db.add(foreign)
        await db.flush()
        membership = OrganizationMembership(
            organization_id=foreign.id,
            user_id=admin.id,
            role_id=role.id,
        )
        db.add(membership)
        await db.flush()
        work_item = WorkItem(
            organization_id=foreign.id,
            assignee_membership_id=membership.id,
            created_by_membership_id=membership.id,
            title="Foreign organization task",
        )
        db.add(work_item)
        await db.commit()
        work_item_id = work_item.id
        foreign_id = foreign.id

    response = await client.get(
        f"/api/work-items/{work_item_id}", headers=admin_headers
    )
    assert response.status_code == 404

    async with SessionLocal() as db:
        foreign = await db.get(Organization, foreign_id)
        assert foreign is not None
        await db.delete(foreign)
        await db.commit()
