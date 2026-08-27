"""Add the Phase D2 Project scope and roster."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260811_0015"
down_revision: str | None = "20260811_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "visibility",
            sa.String(20),
            nullable=False,
            server_default="private",
        ),
        sa.Column("roster_revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name="fk_projects_org",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_projects_owner_user",
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_projects_org_id"),
        sa.CheckConstraint(
            "visibility IN ('public', 'private')",
            name="ck_projects_visibility",
        ),
        sa.CheckConstraint("roster_revision > 0", name="ck_projects_roster_revision"),
    )
    op.create_index(
        "ix_projects_org_visibility",
        "projects",
        ["organization_id", "visibility", "updated_at", "id"],
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    op.create_index("ix_projects_owner_user_id", "projects", ["owner_user_id"])

    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
            name="fk_project_members_org_project",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_project_members_org_user",
        ),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        sa.CheckConstraint("role IN ('member', 'admin')", name="ck_project_members_role"),
    )
    op.create_index(
        "ix_project_members_org_project",
        "project_members",
        ["organization_id", "project_id"],
    )
    op.create_index(
        "ix_project_members_org_user",
        "project_members",
        ["organization_id", "user_id"],
    )

    op.create_table(
        "project_resource_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("ref_id", sa.String(64), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
            name="fk_project_resource_links_org_project",
        ),
        sa.UniqueConstraint(
            "project_id",
            "resource_type",
            "ref_id",
            name="uq_project_resource_links_ref",
        ),
        sa.CheckConstraint(
            "resource_type IN ('knowledge', 'memory', 'skill', 'work_item')",
            name="ck_project_resource_links_type",
        ),
    )
    op.create_index(
        "ix_project_resource_links_org_project",
        "project_resource_links",
        ["organization_id", "project_id"],
    )

    # 权限行与 role links（seed 也会幂等同步；migration 覆盖既有库）
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    for code, description in (
        ("projects:read", "Read scoped projects"),
        ("projects:write", "Create and update scoped projects"),
        ("projects:manage", "Manage project rosters and placements"),
    ):
        op.execute(
            sa.sql.text(
                "INSERT INTO permissions (code, description) VALUES (:code, :description) "
                "ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code, description=description)
        )
    roles = sa.table("roles", sa.column("id", sa.Integer()), sa.column("name", sa.String()))
    for role_name, codes in (
        ("user", ("projects:read", "projects:write")),
        ("manager", ("projects:read", "projects:write", "projects:manage")),
    ):
        role_row = op.get_bind().execute(
            sa.select(roles.c.id).where(roles.c.name == role_name)
        ).first()
        if role_row is None:
            continue
        role_id = role_row[0]
        for code in codes:
            permission_row = op.get_bind().execute(
                sa.select(permissions.c.id).where(permissions.c.code == code)
            ).first()
            if permission_row is None:
                continue
            op.execute(
                sa.sql.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "VALUES (:role_id, :permission_id) "
                    "ON CONFLICT (role_id, permission_id) DO NOTHING"
                ).bindparams(role_id=role_id, permission_id=permission_row[0])
            )


def downgrade() -> None:
    # 清理本 revision 引入的 permission/role link，保证 re-upgrade 幂等。
    op.execute(
        sa.sql.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code IN "
            "('projects:read', 'projects:write', 'projects:manage'))"
        )
    )
    op.execute(
        sa.sql.text(
            "DELETE FROM permissions WHERE code IN "
            "('projects:read', 'projects:write', 'projects:manage') "
            "AND id NOT IN (SELECT DISTINCT permission_id FROM role_permissions)"
        )
    )
    op.drop_index("ix_project_resource_links_org_project", table_name="project_resource_links")
    op.drop_table("project_resource_links")
    op.drop_index("ix_project_members_org_user", table_name="project_members")
    op.drop_index("ix_project_members_org_project", table_name="project_members")
    op.drop_table("project_members")
    op.drop_index("ix_projects_owner_user_id", table_name="projects")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_index("ix_projects_org_visibility", table_name="projects")
    op.drop_table("projects")
