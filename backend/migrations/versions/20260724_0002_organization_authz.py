"""Add organizations, normalized permissions, scoped resources, and audit events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0002"
down_revision: str | None = "20260717_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_ORGANIZATION = {"name": "Default Organization", "slug": "default"}
PERMISSION_DEFINITIONS = {
    "chat:use": "Use platform chat sessions",
    "chat:route": "Route messages to an agent",
    "knowledge:read": "Read organization knowledge",
    "knowledge:write": "Write organization knowledge",
    "agent:admin": "Manage Hermes profile metadata",
    "org:admin": "Manage organization users and roles",
    "users:read": "Read organization users",
    "profile:read": "Read own profile metadata",
    "memory:read": "Read scoped memory",
    "memory:write": "Write scoped memory",
    "skills:read": "Read scoped skills",
    "skills:write": "Write scoped skills",
    "reminders:read": "Read scoped reminders",
    "reminders:write": "Write scoped reminders",
}
ROLE_PERMISSIONS = {
    "admin": tuple(PERMISSION_DEFINITIONS),
    "manager": (
        "users:read",
        "chat:use",
        "knowledge:read",
        "knowledge:write",
        "agent:admin",
        "profile:read",
        "memory:read",
        "memory:write",
        "skills:read",
        "skills:write",
        "reminders:read",
        "reminders:write",
    ),
    "user": (
        "chat:use",
        "knowledge:read",
        "knowledge:write",
        "profile:read",
        "memory:read",
        "memory:write",
        "skills:read",
        "skills:write",
        "reminders:read",
        "reminders:write",
    ),
}
RESOURCE_TABLES = ("hermes_profiles", "knowledge_entries", "skills", "reminders", "chat_sessions")


def _set_not_null(table_name: str, column_name: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch:
            batch.alter_column(column_name, existing_type=sa.Integer(), nullable=False)
    else:
        op.alter_column(table_name, column_name, existing_type=sa.Integer(), nullable=False)


def _drop_column(table_name: str, column_name: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch:
            batch.drop_column(column_name)
    else:
        op.drop_column(table_name, column_name)


def _add_organization_column(table_name: str, *, user_column: bool = False) -> None:
    column_name = "default_organization_id" if user_column else "organization_id"
    ondelete = None if user_column else "CASCADE"
    column = sa.Column(
        column_name,
        sa.Integer(),
        sa.ForeignKey(
            "organizations.id",
            ondelete=ondelete,
            name=f"fk_{table_name}_{column_name}_organizations",
        ),
        nullable=True,
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch:
            batch.add_column(column)
    else:
        op.add_column(table_name, column)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_index("ix_organizations_is_active", "organizations", ["is_active"])

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "permission_id",
            sa.Integer(),
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_memberships_org_user"),
    )
    op.create_index(
        "ix_organization_memberships_organization_id",
        "organization_memberships",
        ["organization_id"],
    )
    op.create_index("ix_organization_memberships_user_id", "organization_memberships", ["user_id"])
    op.create_index("ix_organization_memberships_role_id", "organization_memberships", ["role_id"])
    op.create_index(
        "ix_organization_memberships_is_active", "organization_memberships", ["is_active"]
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    _add_organization_column("users", user_column=True)
    op.create_index("ix_users_default_organization_id", "users", ["default_organization_id"])
    for table_name in RESOURCE_TABLES:
        _add_organization_column(table_name)
        op.create_index(f"ix_{table_name}_organization_id", table_name, ["organization_id"])

    bind = op.get_bind()
    organizations = sa.table(
        "organizations",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
    )
    bind.execute(sa.insert(organizations).values(**DEFAULT_ORGANIZATION))
    default_organization_id = bind.scalar(
        sa.select(organizations.c.id).where(organizations.c.slug == DEFAULT_ORGANIZATION["slug"])
    )

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    bind.execute(
        sa.insert(permissions),
        [
            {"code": code, "description": description}
            for code, description in PERMISSION_DEFINITIONS.items()
        ],
    )
    permission_ids = dict(bind.execute(sa.select(permissions.c.code, permissions.c.id)).all())

    roles = sa.table("roles", sa.column("id", sa.Integer()), sa.column("name", sa.String()))
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer()),
        sa.column("permission_id", sa.Integer()),
    )
    for role_id, role_name in bind.execute(sa.select(roles.c.id, roles.c.name)).all():
        codes = ROLE_PERMISSIONS.get(role_name, ())
        if codes:
            bind.execute(
                sa.insert(role_permissions),
                [{"role_id": role_id, "permission_id": permission_ids[code]} for code in codes],
            )

    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("role_id", sa.Integer()),
        sa.column("default_organization_id", sa.Integer()),
    )
    bind.execute(
        sa.update(users)
        .where(users.c.default_organization_id.is_(None))
        .values(default_organization_id=default_organization_id)
    )
    memberships = sa.table(
        "organization_memberships",
        sa.column("organization_id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("role_id", sa.Integer()),
    )
    user_rows = bind.execute(sa.select(users.c.id, users.c.role_id)).all()
    if user_rows:
        bind.execute(
            sa.insert(memberships),
            [
                {
                    "organization_id": default_organization_id,
                    "user_id": user_id,
                    "role_id": role_id,
                }
                for user_id, role_id in user_rows
            ],
        )

    for table_name in RESOURCE_TABLES:
        resource_table = sa.table(table_name, sa.column("organization_id", sa.Integer()))
        bind.execute(
            sa.update(resource_table)
            .where(resource_table.c.organization_id.is_(None))
            .values(organization_id=default_organization_id)
        )

    _set_not_null("users", "default_organization_id")
    for table_name in RESOURCE_TABLES:
        _set_not_null(table_name, "organization_id")


def downgrade() -> None:
    for table_name in RESOURCE_TABLES:
        op.drop_index(f"ix_{table_name}_organization_id", table_name=table_name)
    op.drop_index("ix_users_default_organization_id", table_name="users")
    for table_name in (*reversed(RESOURCE_TABLES), "users"):
        _drop_column(table_name, "organization_id" if table_name != "users" else "default_organization_id")

    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_organization_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_organization_memberships_is_active", table_name="organization_memberships")
    op.drop_index("ix_organization_memberships_role_id", table_name="organization_memberships")
    op.drop_index("ix_organization_memberships_user_id", table_name="organization_memberships")
    op.drop_index(
        "ix_organization_memberships_organization_id", table_name="organization_memberships"
    )
    op.drop_table("organization_memberships")
    op.drop_table("role_permissions")
    op.drop_index("ix_permissions_code", table_name="permissions")
    op.drop_table("permissions")
    op.drop_index("ix_organizations_is_active", table_name="organizations")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
