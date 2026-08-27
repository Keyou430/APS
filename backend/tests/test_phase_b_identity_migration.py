from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "20260731_0006_phase_b_identity_context.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("phase_b_identity_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def legacy_metadata() -> sa.MetaData:
    metadata = sa.MetaData()
    sa.Table(
        "organizations",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
    )
    sa.Table(
        "permissions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.String(255), nullable=False),
    )
    sa.Table(
        "role_permissions",
        metadata,
        sa.Column("role_id", sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "permission_id",
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("role_id", sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("default_organization_id", sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    sa.Table(
        "organization_memberships",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_memberships_org_user"),
    )
    sa.Table(
        "refresh_tokens",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
    )
    sa.Table(
        "hermes_profiles",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "organization_id",
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_name", sa.String(100), nullable=False, unique=True),
        sa.Column("hermes_home", sa.String(500), nullable=False, unique=True),
        sa.Column("port", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("user_id"),
    )
    return metadata


def seed_legacy_rows(connection: sa.Connection, metadata: sa.MetaData) -> None:
    tables = metadata.tables
    connection.execute(
        tables["organizations"].insert(),
        {"id": 1, "name": "Default", "slug": "default", "is_active": True},
    )
    connection.execute(
        tables["roles"].insert(),
        [
            {"id": 1, "name": "admin", "permissions": ["*"]},
            {"id": 2, "name": "manager", "permissions": []},
            {"id": 3, "name": "user", "permissions": []},
        ],
    )
    connection.execute(
        tables["permissions"].insert(),
        [
            {"id": 1, "code": "chat:use", "description": "chat"},
            {"id": 2, "code": "knowledge:read", "description": "knowledge"},
        ],
    )
    connection.execute(
        tables["users"].insert(),
        {
            "id": 1,
            "username": "admin",
            "password_hash": "hash",
            "email": " Admin@Example.COM ",
            "role_id": 1,
            "default_organization_id": 1,
            "is_active": True,
        },
    )
    connection.execute(
        tables["organization_memberships"].insert(),
        {"id": 1, "organization_id": 1, "user_id": 1, "role_id": 1, "is_active": True},
    )
    connection.execute(
        tables["refresh_tokens"].insert(),
        {
            "id": 1,
            "user_id": 1,
            "jti": "legacy-refresh",
            "expires_at": datetime(2027, 1, 1, tzinfo=UTC),
            "revoked": False,
        },
    )
    connection.execute(
        tables["hermes_profiles"].insert(),
        {
            "id": 1,
            "user_id": 1,
            "organization_id": 1,
            "profile_name": "user-1-admin",
            "hermes_home": "/profiles/user-1-admin",
            "port": 9001,
            "status": "stopped",
        },
    )


def test_identity_migration_round_trip_and_security_invariants() -> None:
    migration = load_migration()
    engine = sa.create_engine("sqlite://")
    metadata = legacy_metadata()
    with engine.begin() as connection:
        metadata.create_all(connection)
        seed_legacy_rows(connection, metadata)
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        inspector = sa.inspect(connection)
        assert {column["name"] for column in inspector.get_columns("users")} >= {
            "normalized_email"
        }
        assert {column["name"] for column in inspector.get_columns("organization_memberships")} >= {
            "member_type",
            "expires_at",
        }
        assert {column["name"] for column in inspector.get_columns("refresh_tokens")} >= {
            "organization_id"
        }
        assert connection.scalar(sa.text("SELECT normalized_email FROM users WHERE id = 1")) == (
            "admin@example.com"
        )
        assert connection.scalar(sa.text("SELECT revoked FROM refresh_tokens WHERE id = 1")) == 1
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM roles WHERE name = 'guest'")) == 1
        profile_unique_columns = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("hermes_profiles")
        }
        assert ("organization_id", "user_id") in profile_unique_columns

        migration.downgrade()

        inspector = sa.inspect(connection)
        assert "normalized_email" not in {
            column["name"] for column in inspector.get_columns("users")
        }
        assert "member_type" not in {
            column["name"] for column in inspector.get_columns("organization_memberships")
        }
        assert "organization_id" not in {
            column["name"] for column in inspector.get_columns("refresh_tokens")
        }
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM roles WHERE name = 'guest'")) == 0
        profile_unique_columns = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("hermes_profiles")
        }
        assert ("user_id",) in profile_unique_columns


def test_identity_migration_seeds_required_roles_on_a_fresh_database() -> None:
    migration = load_migration()
    engine = sa.create_engine("sqlite://")
    metadata = legacy_metadata()
    permission_codes = {
        "chat:use",
        "knowledge:read",
        "knowledge:share",
        "knowledge:govern",
        "knowledge:ops",
        "audit:read",
        "members:invite",
    }
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            metadata.tables["permissions"].insert(),
            [{"code": code, "description": code} for code in sorted(permission_codes)],
        )

        migration._seed_identity_permissions(connection)
        migration._seed_identity_permissions(connection)

        roles = dict(connection.execute(sa.text("SELECT name, id FROM roles")).all())
        assert set(roles) == {"admin", "manager", "user", "guest"}
        links = connection.execute(
            sa.text(
                "SELECT roles.name, permissions.code "
                "FROM role_permissions "
                "JOIN roles ON roles.id = role_permissions.role_id "
                "JOIN permissions ON permissions.id = role_permissions.permission_id"
            )
        ).all()
        assert len(links) == len(set(links))
        assert ("manager", "knowledge:share") in links
        assert ("user", "knowledge:share") in links
        assert ("guest", "knowledge:read") in links


def test_identity_migration_fails_closed_on_normalized_email_collision() -> None:
    migration = load_migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("normalized_email", sa.String(255), nullable=True),
    )
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            users.insert(),
            [
                {"id": 1, "email": "Member@Example.com"},
                {"id": 2, "email": " member@example.COM "},
            ],
        )

        with pytest.raises(RuntimeError, match="normalized email conflicts"):
            migration._normalize_existing_emails(connection)
