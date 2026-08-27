"""Add the Phase D2 Skill grants and promotion."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260811_0016"
down_revision: str | None = "20260811_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("is_promoted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "skills",
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "skill_access_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("grantor_user_id", sa.Integer(), nullable=False),
        sa.Column("grantee_user_id", sa.Integer(), nullable=False),
        sa.Column("capability", sa.String(20), nullable=False, server_default="read"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
            name="fk_skill_access_grants_skill",
        ),
        sa.ForeignKeyConstraint(
            ["grantor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_skill_access_grants_grantor",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "grantee_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_skill_access_grants_org_grantee",
        ),
        sa.CheckConstraint(
            "capability IN ('read')",
            name="ck_skill_access_grants_capability",
        ),
    )
    op.create_index(
        "uq_skill_access_grants_active",
        "skill_access_grants",
        ["skill_id", "grantee_user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_skill_access_grants_skill", "skill_access_grants", ["skill_id"])
    op.create_index(
        "ix_skill_access_grants_grantor",
        "skill_access_grants",
        ["grantor_user_id"],
    )
    op.create_index(
        "ix_skill_access_grants_org_grantee",
        "skill_access_grants",
        ["organization_id", "grantee_user_id"],
    )

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    for code, description in (
        ("skills:share", "Share owned skills with organization members"),
        ("skills:govern", "Promote reviewed skills for organization discovery"),
    ):
        op.execute(
            sa.sql.text(
                "INSERT INTO permissions (code, description) VALUES (:code, :description) "
                "ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code, description=description)
        )
    roles = sa.table("roles", sa.column("id", sa.Integer()), sa.column("name", sa.String()))
    for role_name, codes in (
        ("user", ("skills:share",)),
        ("manager", ("skills:share", "skills:govern")),
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
            "('skills:share', 'skills:govern'))"
        )
    )
    op.execute(
        sa.sql.text(
            "DELETE FROM permissions WHERE code IN ('skills:share', 'skills:govern') "
            "AND id NOT IN (SELECT DISTINCT permission_id FROM role_permissions)"
        )
    )
    op.drop_index("ix_skill_access_grants_org_grantee", table_name="skill_access_grants")
    op.drop_index("ix_skill_access_grants_grantor", table_name="skill_access_grants")
    op.drop_index("ix_skill_access_grants_skill", table_name="skill_access_grants")
    op.drop_index("uq_skill_access_grants_active", table_name="skill_access_grants")
    op.drop_table("skill_access_grants")
    op.drop_column("skills", "promoted_at")
    op.drop_column("skills", "is_promoted")
