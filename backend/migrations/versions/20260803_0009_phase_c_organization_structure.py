"""Add Phase C organization structure and permissions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0009"
down_revision: str | None = "20260803_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = {
    "org:read": "Read organization structure",
    "portal:read": "Read organization portal",
    "portal:manage": "Manage organization portal",
    "work_items:read": "Read organization work items",
    "work_items:write": "Write organization work items",
}


def _seed_permissions() -> None:
    for code, description in NEW_PERMISSIONS.items():
        op.execute(
            sa.text(
                "INSERT INTO permissions (code, description) "
                "VALUES (:code, :description) "
                "ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description"
            ).bindparams(code=code, description=description)
        )
    op.execute(
        sa.text(
            "UPDATE permissions SET description = "
            "'Manage organization users, roles, and structure' "
            "WHERE code = 'org:admin'"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT roles.id, permissions.id "
            "FROM roles "
            "JOIN permissions ON permissions.code IN ("
            "'org:read', 'portal:read', 'portal:manage', "
            "'work_items:read', 'work_items:write'"
            ") "
            "WHERE roles.name = 'admin' "
            "OR (roles.name IN ('manager', 'user') "
            "AND permissions.code IN ("
            "'org:read', 'portal:read', 'work_items:read', 'work_items:write'"
            ")) "
            "ON CONFLICT (role_id, permission_id) DO NOTHING"
        )
    )


def upgrade() -> None:
    op.create_table(
        "organization_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_id", sa.Integer()),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_organization_units_org_id"
        ),
        sa.UniqueConstraint(
            "organization_id", "code", name="uq_organization_units_org_code"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "parent_id"],
            ["organization_units.organization_id", "organization_units.id"],
            ondelete="RESTRICT",
            name="fk_organization_units_org_parent",
        ),
    )
    for column in ("organization_id", "parent_id", "is_active"):
        op.create_index(
            f"ix_organization_units_{column}", "organization_units", [column]
        )

    op.create_table(
        "organization_structure_state",
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "organization_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("level", sa.String(80)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_organization_positions_org_id"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "unit_id"],
            ["organization_units.organization_id", "organization_units.id"],
            ondelete="RESTRICT",
            name="fk_organization_positions_org_unit",
        ),
    )
    for column in ("organization_id", "unit_id", "is_active"):
        op.create_index(
            f"ix_organization_positions_{column}",
            "organization_positions",
            [column],
        )

    op.create_table(
        "organization_placements",
        sa.Column("membership_id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("manager_membership_id", sa.Integer()),
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
            ["organization_id", "membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="CASCADE",
            name="fk_organization_placements_org_membership",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "unit_id"],
            ["organization_units.organization_id", "organization_units.id"],
            ondelete="RESTRICT",
            name="fk_organization_placements_org_unit",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "position_id"],
            ["organization_positions.organization_id", "organization_positions.id"],
            ondelete="RESTRICT",
            name="fk_organization_placements_org_position",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "manager_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
            name="fk_organization_placements_org_manager",
        ),
    )
    for column in (
        "organization_id",
        "unit_id",
        "position_id",
        "manager_membership_id",
    ):
        op.create_index(
            f"ix_organization_placements_{column}",
            "organization_placements",
            [column],
        )

    op.execute(
        sa.text(
            "INSERT INTO organization_units "
            "(organization_id, parent_id, name, code, sort_order, is_active) "
            "SELECT id, NULL, name, 'root', 0, true FROM organizations"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO organization_structure_state (organization_id, revision) "
            "SELECT id, 1 FROM organizations"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO organization_positions "
            "(organization_id, unit_id, title, level, sort_order, is_active) "
            "SELECT DISTINCT memberships.organization_id, units.id, roles.name, "
            "roles.name, 0, true "
            "FROM organization_memberships AS memberships "
            "JOIN roles ON roles.id = memberships.role_id "
            "JOIN organization_units AS units "
            "ON units.organization_id = memberships.organization_id "
            "AND units.parent_id IS NULL "
            "WHERE memberships.member_type = 'internal'"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO organization_placements "
            "(membership_id, organization_id, unit_id, position_id) "
            "SELECT memberships.id, memberships.organization_id, units.id, positions.id "
            "FROM organization_memberships AS memberships "
            "JOIN roles ON roles.id = memberships.role_id "
            "JOIN organization_units AS units "
            "ON units.organization_id = memberships.organization_id "
            "AND units.parent_id IS NULL "
            "JOIN organization_positions AS positions "
            "ON positions.organization_id = memberships.organization_id "
            "AND positions.unit_id = units.id "
            "AND positions.title = roles.name "
            "WHERE memberships.member_type = 'internal'"
        )
    )
    _seed_permissions()


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN ("
            "SELECT id FROM permissions WHERE code IN ("
            "'org:read', 'portal:read', 'portal:manage', "
            "'work_items:read', 'work_items:write'"
            "))"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM permissions WHERE code IN ("
            "'org:read', 'portal:read', 'portal:manage', "
            "'work_items:read', 'work_items:write'"
            ")"
        )
    )
    op.execute(
        sa.text(
            "UPDATE permissions SET description = 'Manage organization users and roles' "
            "WHERE code = 'org:admin'"
        )
    )
    op.drop_table("organization_placements")
    op.drop_table("organization_positions")
    op.drop_table("organization_structure_state")
    op.drop_table("organization_units")
