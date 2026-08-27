from __future__ import annotations

from httpx import AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.auth.security import hash_password
from app.database import Base, SessionLocal
from app.models import (
    AuditEvent,
    HermesProfile,
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from test_knowledge_authorization import create_member


pytestmark = pytest.mark.asyncio


async def login(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def create_internal_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
    username: str,
) -> tuple[int, int]:
    response = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": username,
            "password": "phase-c-structure-password",
            "email": f"{username}@example.com",
            "role": "user",
        },
    )
    assert response.status_code == 201, response.text
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        assert user is not None
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.organization_id == user.default_organization_id,
            )
        )
        assert membership is not None
        return user.id, membership.id


async def default_organization_id() -> int:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        return admin.default_organization_id


@pytest_asyncio.fixture(autouse=True)
async def cleanup_structure_contract_data():
    yield
    async with SessionLocal() as db:
        structure_tables = [
            Base.metadata.tables.get(name)
            for name in (
                "organization_placements",
                "organization_positions",
                "organization_units",
                "organization_structure_state",
            )
        ]
        for table in structure_tables:
            if table is not None:
                await db.execute(delete(table))

        users = list(
            (
                await db.scalars(
                    select(User).where(User.username.like("phase-c-structure-%"))
                )
            ).all()
        )
        user_ids = [user.id for user in users]
        if user_ids:
            await db.execute(
                delete(HermesProfile).where(HermesProfile.user_id.in_(user_ids))
            )
            await db.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.user_id.in_(user_ids)
                )
            )
            await db.execute(delete(User).where(User.id.in_(user_ids)))

        organizations = list(
            (
                await db.scalars(
                    select(Organization).where(
                        Organization.slug.like("phase-c-structure-%")
                    )
                )
            ).all()
        )
        for organization in organizations:
            await db.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization.id
                )
            )
            await db.delete(organization)
        await db.execute(
            delete(AuditEvent).where(AuditEvent.action.like("organization.%"))
        )
        await db.commit()


async def test_internal_structure_read_bootstraps_root_and_excludes_guests(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    _, internal_membership_id = await create_internal_user(
        client, admin_headers, "phase-c-structure-reader"
    )
    _, guest_membership = await create_member(
        username="phase-c-structure-guest",
        organization_id=await default_organization_id(),
        member_type="guest",
    )

    response = await client.get(
        "/api/organization/structure", headers=admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    roots = [unit for unit in body["units"] if unit["parent_id"] is None]
    assert len(roots) == 1
    assert body["revision"] >= 1
    assert internal_membership_id in {
        placement["membership_id"] for placement in body["placements"]
    }
    assert guest_membership.id not in {
        placement["membership_id"] for placement in body["placements"]
    }
    assert all(person["member_type"] == "internal" for person in body["people"])

    user_headers = await login(
        client, "phase-c-structure-reader", "phase-c-structure-password"
    )
    assert (
        await client.get("/api/organization/structure", headers=user_headers)
    ).status_code == 200
    denied = await client.post(
        "/api/organization/units",
        headers=user_headers,
        json={
            "expected_revision": body["revision"],
            "name": "Denied unit",
            "code": "denied-unit",
            "parent_id": roots[0]["id"],
        },
    )
    assert denied.status_code == 403

    guest_headers = await login(
        client, "phase-c-structure-guest", "authorization-password"
    )
    assert (
        await client.get("/api/organization/structure", headers=guest_headers)
    ).status_code == 403


async def test_admin_crud_revision_and_nonempty_unit_contract(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    _, membership_id = await create_internal_user(
        client, admin_headers, "phase-c-structure-placement"
    )
    initial = (
        await client.get("/api/organization/structure", headers=admin_headers)
    ).json()
    root_id = next(unit["id"] for unit in initial["units"] if unit["parent_id"] is None)
    root_position_id = next(
        position["id"]
        for position in initial["positions"]
        if position["unit_id"] == root_id
    )

    created_unit = await client.post(
        "/api/organization/units",
        headers=admin_headers,
        json={
            "expected_revision": initial["revision"],
            "name": "研发中心",
            "code": "engineering",
            "parent_id": root_id,
            "sort_order": 10,
        },
    )
    assert created_unit.status_code == 201, created_unit.text
    unit_state = created_unit.json()
    unit = next(item for item in unit_state["units"] if item["code"] == "engineering")

    stale = await client.post(
        "/api/organization/units",
        headers=admin_headers,
        json={
            "expected_revision": initial["revision"],
            "name": "Stale",
            "code": "stale",
            "parent_id": root_id,
        },
    )
    assert stale.status_code == 409

    created_position = await client.post(
        "/api/organization/positions",
        headers=admin_headers,
        json={
            "expected_revision": unit_state["revision"],
            "unit_id": unit["id"],
            "title": "研发工程师",
            "level": "P5",
            "sort_order": 10,
        },
    )
    assert created_position.status_code == 201, created_position.text
    position_state = created_position.json()
    position = next(
        item for item in position_state["positions"] if item["title"] == "研发工程师"
    )

    placed = await client.put(
        f"/api/organization/placements/{membership_id}",
        headers=admin_headers,
        json={
            "expected_revision": position_state["revision"],
            "unit_id": unit["id"],
            "position_id": position["id"],
            "manager_membership_id": None,
        },
    )
    assert placed.status_code == 200, placed.text
    placed_state = placed.json()
    assert next(
        item
        for item in placed_state["placements"]
        if item["membership_id"] == membership_id
    )["unit_id"] == unit["id"]

    nonempty = await client.request(
        "DELETE",
        f"/api/organization/units/{unit['id']}",
        headers=admin_headers,
        json={"expected_revision": placed_state["revision"]},
    )
    assert nonempty.status_code == 409

    moved_to_root = await client.put(
        f"/api/organization/placements/{membership_id}",
        headers=admin_headers,
        json={
            "expected_revision": placed_state["revision"],
            "unit_id": root_id,
            "position_id": root_position_id,
            "manager_membership_id": None,
        },
    )
    assert moved_to_root.status_code == 200, moved_to_root.text
    moved_state = moved_to_root.json()
    deleted_position = await client.request(
        "DELETE",
        f"/api/organization/positions/{position['id']}",
        headers=admin_headers,
        json={"expected_revision": moved_state["revision"]},
    )
    assert deleted_position.status_code == 204
    after_position_delete = (
        await client.get("/api/organization/structure", headers=admin_headers)
    ).json()
    updated_unit = await client.patch(
        f"/api/organization/units/{unit['id']}",
        headers=admin_headers,
        json={
            "expected_revision": after_position_delete["revision"],
            "name": "研发与平台中心",
        },
    )
    assert updated_unit.status_code == 200, updated_unit.text
    updated_state = updated_unit.json()
    deleted_unit = await client.request(
        "DELETE",
        f"/api/organization/units/{unit['id']}",
        headers=admin_headers,
        json={"expected_revision": updated_state["revision"]},
    )
    assert deleted_unit.status_code == 204
    final = (
        await client.get("/api/organization/structure", headers=admin_headers)
    ).json()
    assert unit["id"] not in {item["id"] for item in final["units"]}
    async with SessionLocal() as db:
        audit_actions = set(
            (
                await db.scalars(
                    select(AuditEvent.action).where(
                        AuditEvent.action.like("organization.%")
                    )
                )
            ).all()
        )
    assert {
        "organization.unit.create",
        "organization.unit.update",
        "organization.unit.delete",
        "organization.position.create",
        "organization.position.delete",
        "organization.placement.update",
    }.issubset(audit_actions)


async def test_unit_and_manager_cycles_and_invalid_batch_roll_back(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    _, first_membership_id = await create_internal_user(
        client, admin_headers, "phase-c-structure-first"
    )
    _, second_membership_id = await create_internal_user(
        client, admin_headers, "phase-c-structure-second"
    )
    initial = (
        await client.get("/api/organization/structure", headers=admin_headers)
    ).json()
    root_id = next(unit["id"] for unit in initial["units"] if unit["parent_id"] is None)
    root_position_id = next(
        position["id"]
        for position in initial["positions"]
        if position["unit_id"] == root_id
    )

    first_unit_state = (
        await client.post(
            "/api/organization/units",
            headers=admin_headers,
            json={
                "expected_revision": initial["revision"],
                "name": "Unit A",
                "code": "unit-a",
                "parent_id": root_id,
            },
        )
    ).json()
    unit_a = next(unit for unit in first_unit_state["units"] if unit["code"] == "unit-a")
    second_unit_state = (
        await client.post(
            "/api/organization/units",
            headers=admin_headers,
            json={
                "expected_revision": first_unit_state["revision"],
                "name": "Unit B",
                "code": "unit-b",
                "parent_id": unit_a["id"],
            },
        )
    ).json()
    unit_b = next(unit for unit in second_unit_state["units"] if unit["code"] == "unit-b")

    unit_position_state = (
        await client.post(
            "/api/organization/positions",
            headers=admin_headers,
            json={
                "expected_revision": second_unit_state["revision"],
                "unit_id": unit_a["id"],
                "title": "Unit A member",
                "level": "member",
            },
        )
    ).json()
    unit_a_position_id = next(
        position["id"]
        for position in unit_position_state["positions"]
        if position["title"] == "Unit A member"
    )

    unit_cycle = await client.patch(
        f"/api/organization/units/{unit_a['id']}",
        headers=admin_headers,
        json={
            "expected_revision": unit_position_state["revision"],
            "parent_id": unit_b["id"],
        },
    )
    assert unit_cycle.status_code == 409

    manager_cycle = await client.post(
        "/api/organization/placements/batch",
        headers=admin_headers,
        json={
            "expected_revision": unit_position_state["revision"],
            "items": [
                {
                    "membership_id": first_membership_id,
                    "unit_id": unit_a["id"],
                    "position_id": unit_a_position_id,
                    "manager_membership_id": second_membership_id,
                },
                {
                    "membership_id": second_membership_id,
                    "unit_id": root_id,
                    "position_id": root_position_id,
                    "manager_membership_id": first_membership_id,
                },
            ],
        },
    )
    assert manager_cycle.status_code == 409

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        role = await db.scalar(select(Role).where(Role.name == "user"))
        assert admin is not None and role is not None
        foreign = Organization(
            name="Phase C structure foreign",
            slug="phase-c-structure-foreign",
        )
        db.add(foreign)
        await db.flush()
        foreign_user = User(
            username="phase-c-structure-foreign-user",
            email="phase-c-structure-foreign-user@example.com",
            password_hash=hash_password("phase-c-structure-password"),
            role_id=role.id,
            default_organization_id=foreign.id,
        )
        db.add(foreign_user)
        await db.flush()
        foreign_membership = OrganizationMembership(
            organization_id=foreign.id,
            user_id=foreign_user.id,
            role_id=role.id,
        )
        db.add(foreign_membership)
        await db.commit()
        foreign_membership_id = foreign_membership.id

    before = await client.get("/api/organization/structure", headers=admin_headers)
    before_body = before.json()
    first_before = next(
        placement
        for placement in before_body["placements"]
        if placement["membership_id"] == first_membership_id
    )
    invalid_batch = await client.post(
        "/api/organization/placements/batch",
        headers=admin_headers,
        json={
            "expected_revision": before_body["revision"],
            "items": [
                {
                    "membership_id": first_membership_id,
                    "unit_id": unit_a["id"],
                    "position_id": unit_a_position_id,
                    "manager_membership_id": None,
                },
                {
                    "membership_id": foreign_membership_id,
                    "unit_id": unit_a["id"],
                    "position_id": unit_a_position_id,
                    "manager_membership_id": None,
                },
            ],
        },
    )
    assert invalid_batch.status_code in {404, 409}
    after = (
        await client.get("/api/organization/structure", headers=admin_headers)
    ).json()
    assert after["revision"] == before_body["revision"]
    assert next(
        placement
        for placement in after["placements"]
        if placement["membership_id"] == first_membership_id
    ) == first_before
