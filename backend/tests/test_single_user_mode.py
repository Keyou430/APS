from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import dependencies
from app.auth.security import hash_password, verify_password
from app.config import Settings
from app.database import Base
from app.models import OrganizationMembership, Role, User
from app.seed import seed_database


@pytest.mark.asyncio
async def test_anonymous_request_uses_the_seeded_single_user_context(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(single_user_mode=True, admin_username="admin"),
    )
    response = await client.get("/api/auth/me")

    assert response.status_code == 200, response.text
    assert response.json()["username"] == "admin"
    assert response.json()["organization_id"] > 0
    assert response.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_anonymous_request_requires_a_token_when_single_user_mode_is_disabled(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(single_user_mode=False),
    )

    response = await client.get("/api/auth/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_seed_enforces_the_only_active_admin_account(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "single-user-seed.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(single_user_mode=True, admin_password="admin123")
    monkeypatch.setattr("app.seed.get_settings", lambda: settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            await seed_database(session)
            admin = await session.scalar(select(User).where(User.username == "admin"))
            user_role = await session.scalar(select(Role).where(Role.name == "user"))
            assert admin is not None
            assert user_role is not None
            admin.password_hash = hash_password("outdated-password")
            admin.is_active = False
            extra_user = User(
                username="secondary-user",
                email="secondary-user@example.com",
                normalized_email="secondary-user@example.com",
                password_hash=hash_password("secondary-password"),
                role=user_role,
                default_organization_id=admin.default_organization_id,
            )
            session.add(extra_user)
            await session.flush()
            extra_membership = OrganizationMembership(
                organization_id=admin.default_organization_id,
                user_id=extra_user.id,
                role_id=user_role.id,
            )
            session.add(extra_membership)
            await session.commit()

            await seed_database(session)
            await session.refresh(admin)
            await session.refresh(extra_user)
            await session.refresh(extra_membership)

            active_usernames = set(
                (await session.scalars(select(User.username).where(User.is_active.is_(True)))).all()
            )
            assert active_usernames == {"admin"}
            assert admin.is_active is True
            assert verify_password("admin123", admin.password_hash) is True
            assert verify_password("outdated-password", admin.password_hash) is False
            assert extra_user.is_active is False
            assert extra_membership.is_active is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_single_user_mode_rejects_creating_a_second_account(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.routers.users.get_settings",
        lambda: SimpleNamespace(single_user_mode=True),
        raising=False,
    )

    response = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "second-account",
            "password": "second-account-password",
            "email": "second-account@example.com",
            "role": "user",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Single-user mode only allows the admin account"
