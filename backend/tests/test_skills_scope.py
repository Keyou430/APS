from datetime import timedelta

from httpx import AsyncClient
import pytest
from sqlalchemy import delete, select

from app.auth.security import create_token
from app.database import SessionLocal
from app.models import Organization, OrganizationMembership, Skill, User


@pytest.mark.asyncio
async def test_skills_use_token_organization_even_when_user_default_changes(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/skills",
        headers=admin_headers,
        json={"name": "Phase C scoped skill", "category": "general", "content": "# Skill"},
    )
    assert created.status_code == 201, created.text

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        original_organization_id = admin.default_organization_id
        foreign_organization = Organization(
            name="Skills scope organization", slug="skills-scope-organization"
        )
        db.add(foreign_organization)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=foreign_organization.id,
                user_id=admin.id,
                role_id=admin.role_id,
            )
        )
        admin.default_organization_id = foreign_organization.id
        await db.commit()
        foreign_token, _, _ = create_token(
            admin.id,
            "access",
            timedelta(minutes=15),
            organization_id=foreign_organization.id,
        )
        foreign_organization_id = foreign_organization.id

    try:
        original = await client.get("/api/skills", headers=admin_headers)
        foreign_response = await client.get(
            "/api/skills",
            headers={"Authorization": f"Bearer {foreign_token}"},
        )
        assert "Phase C scoped skill" in [
            item["name"] for item in original.json()["items"]
        ]
        assert foreign_response.json()["items"] == []
    finally:
        async with SessionLocal() as db:
            admin = await db.scalar(select(User).where(User.username == "admin"))
            assert admin is not None
            admin.default_organization_id = original_organization_id
            await db.execute(delete(Skill).where(Skill.id == created.json()["id"]))
            await db.execute(
                delete(OrganizationMembership).where(
                    OrganizationMembership.organization_id == foreign_organization_id
                )
            )
            await db.execute(
                delete(Organization).where(Organization.id == foreign_organization_id)
            )
            await db.commit()
