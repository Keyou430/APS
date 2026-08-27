"""Add organization-bound identity context for phase B."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260731_0006"
down_revision: str | None = "20260729_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = {
    "knowledge:share": "Share owned knowledge",
    "knowledge:govern": "Govern organization knowledge",
    "knowledge:ops": "Read knowledge operations",
    "audit:read": "Read organization audit events",
    "members:invite": "Invite organization guests",
}
ROLE_PERMISSION_ADDITIONS = {
    "manager": ("knowledge:share", "knowledge:govern", "knowledge:ops", "audit:read"),
    "user": ("knowledge:share",),
    "guest": ("chat:use", "knowledge:read"),
}
REQUIRED_ROLE_PERMISSION_CODES = {
    "admin": (),
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
        *ROLE_PERMISSION_ADDITIONS["manager"],
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
        *ROLE_PERMISSION_ADDITIONS["user"],
    ),
    "guest": ROLE_PERMISSION_ADDITIONS["guest"],
}


def _normalize_existing_emails(bind) -> None:
    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("email", sa.String()),
        sa.column("normalized_email", sa.String()),
    )
    collisions = bind.execute(
        sa.select(sa.func.lower(sa.func.trim(users.c.email)), sa.func.count())
        .group_by(sa.func.lower(sa.func.trim(users.c.email)))
        .having(sa.func.count() > 1)
    ).all()
    if collisions:
        raise RuntimeError("normalized email conflicts must be resolved before migration")
    bind.execute(
        sa.update(users).values(normalized_email=sa.func.lower(sa.func.trim(users.c.email)))
    )


def _replace_profile_unique_constraint(*, downgrade: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        naming_convention = {
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        }
        with op.batch_alter_table(
            "hermes_profiles",
            recreate="always",
            naming_convention=naming_convention,
        ) as batch:
            if downgrade:
                batch.drop_constraint(
                    "uq_hermes_profiles_organization_user", type_="unique"
                )
                batch.create_unique_constraint(
                    "uq_hermes_profiles_user_id", ["user_id"]
                )
            else:
                batch.drop_constraint("uq_hermes_profiles_user_id", type_="unique")
                batch.create_unique_constraint(
                    "uq_hermes_profiles_organization_user",
                    ["organization_id", "user_id"],
                )
        return

    if downgrade:
        op.drop_constraint(
            "uq_hermes_profiles_organization_user",
            "hermes_profiles",
            type_="unique",
        )
        op.create_unique_constraint(
            "hermes_profiles_user_id_key", "hermes_profiles", ["user_id"]
        )
    else:
        op.drop_constraint(
            "hermes_profiles_user_id_key", "hermes_profiles", type_="unique"
        )
        op.create_unique_constraint(
            "uq_hermes_profiles_organization_user",
            "hermes_profiles",
            ["organization_id", "user_id"],
        )


def _seed_identity_permissions(bind) -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("permissions", sa.JSON()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer()),
        sa.column("permission_id", sa.Integer()),
    )
    existing_codes = set(bind.scalars(sa.select(permissions.c.code)).all())
    missing = [
        {"code": code, "description": description}
        for code, description in NEW_PERMISSIONS.items()
        if code not in existing_codes
    ]
    if missing:
        bind.execute(sa.insert(permissions), missing)

    permission_ids = dict(bind.execute(sa.select(permissions.c.code, permissions.c.id)).all())
    existing_role_names = set(bind.scalars(sa.select(roles.c.name)).all())
    missing_roles = [
        role_name for role_name in REQUIRED_ROLE_PERMISSION_CODES if role_name not in existing_role_names
    ]
    if missing_roles:
        bind.execute(
            sa.insert(roles),
            [{"name": role_name, "permissions": []} for role_name in missing_roles],
        )
    role_ids = dict(bind.execute(sa.select(roles.c.name, roles.c.id)).all())
    existing_links = set(
        bind.execute(
            sa.select(role_permissions.c.role_id, role_permissions.c.permission_id)
        ).all()
    )
    additions = []
    for role_name, codes in REQUIRED_ROLE_PERMISSION_CODES.items():
        if role_name == "admin":
            codes = tuple(permission_ids)
        for code in codes:
            permission_id = permission_ids.get(code)
            if permission_id is None:
                continue
            pair = (role_ids[role_name], permission_id)
            if pair not in existing_links:
                additions.append({"role_id": pair[0], "permission_id": pair[1]})
    if additions:
        bind.execute(sa.insert(role_permissions), additions)


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("users", sa.Column("normalized_email", sa.String(255), nullable=True))
    _normalize_existing_emails(bind)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users", recreate="always") as batch:
            batch.alter_column(
                "normalized_email", existing_type=sa.String(255), nullable=False
            )
    else:
        op.alter_column(
            "users", "normalized_email", existing_type=sa.String(255), nullable=False
        )
    op.create_index(
        "ix_users_normalized_email", "users", ["normalized_email"], unique=True
    )

    op.add_column(
        "organization_memberships",
        sa.Column("member_type", sa.String(20), nullable=False, server_default="internal"),
    )
    op.add_column(
        "organization_memberships",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_organization_memberships_member_type",
        "organization_memberships",
        ["member_type"],
    )
    op.create_index(
        "ix_organization_memberships_expires_at",
        "organization_memberships",
        ["expires_at"],
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("organization_memberships", recreate="always") as batch:
            batch.create_check_constraint(
                "ck_org_memberships_member_type",
                "member_type IN ('internal', 'guest')",
            )
    else:
        op.create_check_constraint(
            "ck_org_memberships_member_type",
            "organization_memberships",
            "member_type IN ('internal', 'guest')",
        )

    organization_column = sa.Column(
        "organization_id",
        sa.Integer(),
        sa.ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
            name="fk_refresh_tokens_organization_id_organizations",
        ),
        nullable=True,
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("refresh_tokens", recreate="always") as batch:
            batch.add_column(organization_column)
    else:
        op.add_column("refresh_tokens", organization_column)
    op.create_index(
        "ix_refresh_tokens_organization_id",
        "refresh_tokens",
        ["organization_id"],
    )
    refresh_tokens = sa.table(
        "refresh_tokens",
        sa.column("revoked", sa.Boolean()),
    )
    bind.execute(sa.update(refresh_tokens).values(revoked=True))

    _replace_profile_unique_constraint(downgrade=False)
    _seed_identity_permissions(bind)


def downgrade() -> None:
    bind = op.get_bind()
    profiles = sa.table("hermes_profiles", sa.column("user_id", sa.Integer()))
    duplicates = bind.execute(
        sa.select(profiles.c.user_id, sa.func.count())
        .group_by(profiles.c.user_id)
        .having(sa.func.count() > 1)
    ).all()
    if duplicates:
        raise RuntimeError("cannot downgrade while users have profiles in multiple organizations")

    _replace_profile_unique_constraint(downgrade=True)

    roles = sa.table("roles", sa.column("id", sa.Integer()), sa.column("name", sa.String()))
    guest_role_id = bind.scalar(sa.select(roles.c.id).where(roles.c.name == "guest"))
    if guest_role_id is not None:
        bind.execute(sa.delete(roles).where(roles.c.id == guest_role_id))
    permissions = sa.table("permissions", sa.column("code", sa.String()))
    bind.execute(sa.delete(permissions).where(permissions.c.code.in_(tuple(NEW_PERMISSIONS))))

    op.drop_index("ix_refresh_tokens_organization_id", table_name="refresh_tokens")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("refresh_tokens", recreate="always") as batch:
            batch.drop_column("organization_id")
    else:
        op.drop_column("refresh_tokens", "organization_id")

    op.drop_index(
        "ix_organization_memberships_expires_at",
        table_name="organization_memberships",
    )
    op.drop_index(
        "ix_organization_memberships_member_type",
        table_name="organization_memberships",
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("organization_memberships", recreate="always") as batch:
            batch.drop_constraint("ck_org_memberships_member_type", type_="check")
            batch.drop_column("expires_at")
            batch.drop_column("member_type")
    else:
        op.drop_constraint(
            "ck_org_memberships_member_type",
            "organization_memberships",
            type_="check",
        )
        op.drop_column("organization_memberships", "expires_at")
        op.drop_column("organization_memberships", "member_type")

    op.drop_index("ix_users_normalized_email", table_name="users")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users", recreate="always") as batch:
            batch.drop_column("normalized_email")
    else:
        op.drop_column("users", "normalized_email")
