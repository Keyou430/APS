from datetime import timedelta

from httpx import AsyncClient
import pytest
from sqlalchemy import delete, select

from app.auth.security import create_token
from app.database import Base, SessionLocal
from app.models import Organization, OrganizationMembership, User


@pytest.mark.asyncio
async def test_structure_scope_uses_token_organization_not_user_default(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        original_organization_id = admin.default_organization_id
        second = Organization(
            name="Phase C scope organization",
            slug="phase-c-structure-scope",
        )
        db.add(second)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=second.id,
                user_id=admin.id,
                role_id=admin.role_id,
            )
        )
        admin.default_organization_id = second.id
        await db.commit()
        second_id = second.id
        second_token, _, _ = create_token(
            admin.id,
            "access",
            timedelta(minutes=15),
            organization_id=second.id,
        )

    try:
        original = await client.get(
            "/api/organization/structure", headers=admin_headers
        )
        second_response = await client.get(
            "/api/organization/structure",
            headers={"Authorization": f"Bearer {second_token}"},
        )
        assert original.status_code == 200, original.text
        assert second_response.status_code == 200, second_response.text
        assert original.json()["organization_id"] == original_organization_id
        assert second_response.json()["organization_id"] == second_id
        assert {
            unit["id"] for unit in original.json()["units"]
        }.isdisjoint({unit["id"] for unit in second_response.json()["units"]})
    finally:
        async with SessionLocal() as db:
            admin = await db.scalar(select(User).where(User.username == "admin"))
            assert admin is not None
            admin.default_organization_id = original_organization_id
            for table_name in (
                "organization_placements",
                "organization_positions",
                "organization_units",
                "organization_structure_state",
            ):
                table = Base.metadata.tables.get(table_name)
                if table is not None:
                    await db.execute(
                        delete(table).where(
                            table.c.organization_id.in_(
                                [original_organization_id, second_id]
                            )
                        )
                    )
            await db.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.organization_id == second_id
                )
            )
            await db.execute(delete(Organization).where(Organization.id == second_id))
            await db.commit()
