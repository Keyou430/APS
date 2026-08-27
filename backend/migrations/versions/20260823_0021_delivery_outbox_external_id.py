"""extend delivery outbox for platform-owned feishu delivery

Revision ID: 20260823_0021
Revises: 20260823_0020
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0021"
down_revision: str | None = "20260823_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("delivery_outbox", recreate="always") as batch:
            batch.alter_column(
                "run_correlation_id",
                existing_type=sa.Integer(),
                nullable=True,
            )
    else:
        op.alter_column(
            "delivery_outbox",
            "run_correlation_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    op.add_column(
        "delivery_outbox",
        sa.Column("external_message_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "delivery_outbox",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_delivery_outbox_external_message_id",
        "delivery_outbox",
        ["external_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delivery_outbox_external_message_id", table_name="delivery_outbox"
    )
    op.drop_column("delivery_outbox", "claimed_at")
    op.drop_column("delivery_outbox", "external_message_id")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("delivery_outbox", recreate="always") as batch:
            batch.alter_column(
                "run_correlation_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
    else:
        op.alter_column(
            "delivery_outbox",
            "run_correlation_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
