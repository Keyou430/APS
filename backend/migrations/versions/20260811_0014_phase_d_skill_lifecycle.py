"""Add the Phase D2 Skill version lifecycle."""

from collections.abc import Sequence
import hashlib

import sqlalchemy as sa
from alembic import op


revision: str = "20260811_0014"
down_revision: str | None = "20260811_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.add_column(
        "skills",
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
    )
    op.add_column(
        "skills",
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "skills",
        sa.Column("current_version", sa.String(20), nullable=False, server_default="v1"),
    )
    op.add_column(
        "skills",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "skills",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    if dialect == "sqlite":
        with op.batch_alter_table("skills", recreate="always") as batch:
            batch.create_check_constraint(
                "ck_skills_status",
                "status IN ('draft', 'reviewed', 'published', 'archived')",
            )
            batch.create_check_constraint("ck_skills_revision_positive", "revision > 0")
    else:
        op.create_check_constraint(
            "ck_skills_status",
            "skills",
            "status IN ('draft', 'reviewed', 'published', 'archived')",
        )
        op.create_check_constraint("ck_skills_revision_positive", "skills", "revision > 0")

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column(
            "is_ai_generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
            name="fk_skill_versions_skill",
        ),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
    )
    op.create_index(
        "ix_skill_versions_org_skill",
        "skill_versions",
        ["organization_id", "skill_id"],
    )
    op.create_index(
        "ix_skills_owner_catalog",
        "skills",
        ["organization_id", "user_id", "status", "updated_at", "id"],
    )
    op.create_index("ix_skills_status", "skills", ["status"])

    # Backfill：现有 rows 全部成为 v1 draft，并回填 content hash 与 v1 版本行。
    connection = op.get_bind()
    skills_table = sa.table(
        "skills",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("content", sa.Text()),
        sa.column("content_hash", sa.String()),
        sa.column("is_ai_generated", sa.Boolean()),
    )
    rows = connection.execute(sa.select(skills_table)).mappings().all()
    versions_table = sa.table(
        "skill_versions",
        sa.column("organization_id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("skill_id", sa.Integer()),
        sa.column("version", sa.String()),
        sa.column("revision", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("content", sa.Text()),
        sa.column("content_hash", sa.String()),
        sa.column("is_ai_generated", sa.Boolean()),
    )
    for row in rows:
        content_hash = _sha256(row["content"])
        connection.execute(
            skills_table.update()
            .where(skills_table.c.id == row["id"])
            .values(content_hash=content_hash)
        )
    # 需要 organization_id/user_id：从 skills 表读取完整行。
    full_skills = sa.table(
        "skills",
        sa.column("id", sa.Integer()),
        sa.column("organization_id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("content", sa.Text()),
        sa.column("content_hash", sa.String()),
        sa.column("is_ai_generated", sa.Boolean()),
    )
    for row in connection.execute(sa.select(full_skills)).mappings().all():
        connection.execute(
            versions_table.insert().values(
                organization_id=row["organization_id"],
                user_id=row["user_id"],
                skill_id=row["id"],
                version="v1",
                revision=1,
                name=row["name"],
                category=row["category"],
                content=row["content"],
                content_hash=_sha256(row["content"]),
                is_ai_generated=bool(row["is_ai_generated"]),
            )
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.drop_index("ix_skills_owner_catalog", table_name="skills")
    op.drop_index("ix_skills_status", table_name="skills")
    op.drop_index("ix_skill_versions_org_skill", table_name="skill_versions")
    op.drop_table("skill_versions")
    if dialect == "sqlite":
        with op.batch_alter_table("skills", recreate="always") as batch:
            batch.drop_constraint("ck_skills_status", type_="check")
            batch.drop_constraint("ck_skills_revision_positive", type_="check")
            batch.drop_column("status")
            batch.drop_column("revision")
            batch.drop_column("current_version")
            batch.drop_column("content_hash")
            batch.drop_column("updated_at")
    else:
        op.drop_constraint("ck_skills_status", "skills", type_="check")
        op.drop_constraint("ck_skills_revision_positive", "skills", type_="check")
        op.drop_column("skills", "status")
        op.drop_column("skills", "revision")
        op.drop_column("skills", "current_version")
        op.drop_column("skills", "content_hash")
        op.drop_column("skills", "updated_at")
