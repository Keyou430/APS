"""Add organization-scoped experience method domains."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0022"
down_revision: str | None = "20260823_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experience_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "name", name="uq_experience_domains_org_name"),
        sa.UniqueConstraint("organization_id", "id", name="uq_experience_domains_org_id"),
    )
    op.create_index("ix_experience_domains_organization_id", "experience_domains", ["organization_id"])
    op.create_table(
        "experience_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="human"),
        sa.Column("source_reference", sa.String(500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_experience_methods_org_id"),
        sa.ForeignKeyConstraint(["organization_id", "domain_id"], ["experience_domains.organization_id", "experience_domains.id"], ondelete="CASCADE", name="fk_experience_methods_org_domain"),
        sa.ForeignKeyConstraint(["organization_id", "created_by_user_id"], ["organization_memberships.organization_id", "organization_memberships.user_id"], ondelete="RESTRICT", name="fk_experience_methods_org_creator"),
        sa.CheckConstraint("source_type IN ('human', 'ai_summary')", name="ck_experience_methods_source_type"),
    )
    op.create_index("ix_experience_methods_organization_id", "experience_methods", ["organization_id"])
    op.create_index("ix_experience_methods_domain_id", "experience_methods", ["domain_id"])
    op.create_index("ix_experience_methods_created_by_user_id", "experience_methods", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_experience_methods_created_by_user_id", table_name="experience_methods")
    op.drop_index("ix_experience_methods_domain_id", table_name="experience_methods")
    op.drop_index("ix_experience_methods_organization_id", table_name="experience_methods")
    op.drop_table("experience_methods")
    op.drop_index("ix_experience_domains_organization_id", table_name="experience_domains")
    op.drop_table("experience_domains")
