"""Add Phase C knowledge collections."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0008"
down_revision: str | None = "20260731_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_id", sa.Integer()),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
            "organization_id",
            "id",
            name="uq_knowledge_collections_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "parent_id"],
            ["knowledge_collections.organization_id", "knowledge_collections.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_collections_org_parent",
        ),
    )
    op.create_index(
        "ix_knowledge_collections_organization_id",
        "knowledge_collections",
        ["organization_id"],
    )
    op.create_index(
        "ix_knowledge_collections_parent_id",
        "knowledge_collections",
        ["parent_id"],
    )

    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        with op.batch_alter_table("knowledge_entries", recreate="always") as batch:
            batch.add_column(sa.Column("collection_id", sa.Integer()))
            batch.create_foreign_key(
                "fk_knowledge_entries_org_collection",
                "knowledge_collections",
                ["organization_id", "collection_id"],
                ["organization_id", "id"],
                ondelete="RESTRICT",
            )
            batch.create_index(
                "ix_knowledge_entries_collection_id",
                ["collection_id"],
            )
        return

    op.add_column(
        "knowledge_entries",
        sa.Column("collection_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_entries_org_collection",
        "knowledge_entries",
        "knowledge_collections",
        ["organization_id", "collection_id"],
        ["organization_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_knowledge_entries_collection_id",
        "knowledge_entries",
        ["collection_id"],
    )


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        with op.batch_alter_table("knowledge_entries", recreate="always") as batch:
            batch.drop_index("ix_knowledge_entries_collection_id")
            batch.drop_constraint(
                "fk_knowledge_entries_org_collection",
                type_="foreignkey",
            )
            batch.drop_column("collection_id")
    else:
        op.drop_index(
            "ix_knowledge_entries_collection_id",
            table_name="knowledge_entries",
        )
        op.drop_constraint(
            "fk_knowledge_entries_org_collection",
            "knowledge_entries",
            type_="foreignkey",
        )
        op.drop_column("knowledge_entries", "collection_id")

    op.drop_index(
        "ix_knowledge_collections_parent_id",
        table_name="knowledge_collections",
    )
    op.drop_index(
        "ix_knowledge_collections_organization_id",
        table_name="knowledge_collections",
    )
    op.drop_table("knowledge_collections")
