from sqlalchemy import select

from app.database import SessionLocal
from app.models import Organization, OrganizationMembership, Role, User
from app.schemas.portal import DashboardLayoutResponse


async def test_dashboard_layout_schema_persists_revision_and_rejects_stale_writes(
    client, admin_headers: dict[str, str]
) -> None:
    assert "revision" in DashboardLayoutResponse.model_fields
    initial = await client.get("/api/dashboard/layout", headers=admin_headers)
    assert initial.status_code == 200, initial.text
    body = initial.json()
    assert body["revision"] >= 1
    assert body["widgets"][0]["title"] == "我的任务"
    assert body["widgets"][1]["title"] == "智能任务"
    assert "AI 流水线" not in str(body)

    layouts = body["layouts"]
    layouts["lg"][0]["x"] = 1
    saved = await client.put(
        "/api/dashboard/layout",
        headers=admin_headers,
        json={"layouts": layouts, "expectedRevision": body["revision"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == body["revision"] + 1
    refreshed = await client.get("/api/dashboard/layout", headers=admin_headers)
    assert refreshed.json()["layouts"]["lg"][0]["x"] == 1
    assert refreshed.json()["revision"] == saved.json()["revision"]

    stale = await client.put(
        "/api/dashboard/layout",
        headers=admin_headers,
        json={"layouts": body["layouts"], "expectedRevision": body["revision"]},
    )
    assert stale.status_code == 409


async def test_dashboard_layout_is_scoped_to_token_organization_not_default(
    client, admin_headers: dict[str, str]
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        role = await db.scalar(select(Role).where(Role.name == "admin"))
        assert admin is not None and role is not None
        default_organization_id = admin.default_organization_id
        second = Organization(name="Dashboard Layout Org", slug="dashboard-layout-org")
        db.add(second)
        await db.flush()
        db.add(OrganizationMembership(
            organization_id=second.id,
            user_id=admin.id,
            role_id=role.id,
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
    second_layout = await client.get("/api/dashboard/layout", headers=second_headers)
    assert second_layout.status_code == 200, second_layout.text
    assert second_layout.json()["revision"] == 1

    original_layout = await client.get("/api/dashboard/layout", headers=admin_headers)
    assert original_layout.status_code == 200, original_layout.text
    assert original_layout.json()["id"] != second_layout.json()["id"]
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None and admin.default_organization_id == default_organization_id
        second = await db.get(Organization, second_id)
        assert second is not None
        await db.delete(second)
        await db.commit()
