from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import HermesProfile, Organization, User
from app.services.hermes_manager import profile_manager


@pytest.mark.asyncio
async def test_profile_reconciliation_is_idempotent_and_scoped_to_organization() -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        original_organization_id = admin.default_organization_id
        original_profile = await db.scalar(
            select(HermesProfile).where(
                HermesProfile.user_id == admin.id,
                HermesProfile.organization_id == original_organization_id,
            )
        )
        assert original_profile is not None
        original_profile_id = original_profile.id
        original_home = original_profile.hermes_home
        new_organization = Organization(name="Reconciled Organization", slug="reconciled-org")
        db.add(new_organization)
        await db.flush()

        profile = await profile_manager.reconcile(
            db, admin, organization_id=new_organization.id
        )
        await db.commit()

        repeated = await profile_manager.reconcile(
            db, admin, organization_id=new_organization.id
        )
        await db.commit()

        assert repeated.id == profile.id
        assert repeated.id != original_profile_id
        assert repeated.organization_id == new_organization.id
        assert profile_manager.scope_key(admin.id, new_organization.id) == (
            f"org:{new_organization.id}:user:{admin.id}"
        )
        assert Path(repeated.hermes_home).resolve().is_relative_to(
            profile_manager.profiles_root.resolve()
        )

        preserved = await profile_manager.reconcile(
            db, admin, organization_id=original_organization_id
        )
        assert preserved.id == original_profile_id
        assert preserved.hermes_home == original_home
        await db.delete(new_organization)
        await db.commit()


@pytest.mark.asyncio
async def test_chat_session_creation_reconciles_a_missing_profile(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        profile = await db.scalar(
            select(HermesProfile).where(
                HermesProfile.user_id == admin.id,
                HermesProfile.organization_id == admin.default_organization_id,
            )
        )
        assert profile is not None
        await db.delete(profile)
        await db.commit()

    created = await client.post(
        "/api/chat/sessions", headers=admin_headers, json={"title": "Reconcile session"}
    )

    assert created.status_code == 201, created.text
    async with SessionLocal() as db:
        profile = await db.scalar(
            select(HermesProfile).where(
                HermesProfile.user_id == 1,
                HermesProfile.organization_id == 1,
            )
        )
        assert profile is not None
        assert profile.organization_id == 1
