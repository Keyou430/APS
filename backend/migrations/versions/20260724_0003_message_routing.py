"""Add platform-owned channel routing and delivery outbox state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0003"
down_revision: str | None = "20260724_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("external_conversation_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "external_user_id",
            "external_conversation_id",
            name="uq_channel_identities_external",
        ),
    )
    op.create_index("ix_channel_identities_organization_id", "channel_identities", ["organization_id"])
    op.create_index("ix_channel_identities_provider", "channel_identities", ["provider"])
    op.create_index("ix_channel_identities_is_active", "channel_identities", ["is_active"])

    op.create_table(
        "delivery_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("external_conversation_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "external_conversation_id",
            name="uq_delivery_targets_external",
        ),
    )
    op.create_index("ix_delivery_targets_organization_id", "delivery_targets", ["organization_id"])
    op.create_index("ix_delivery_targets_provider", "delivery_targets", ["provider"])
    op.create_index("ix_delivery_targets_is_active", "delivery_targets", ["is_active"])

    op.create_table(
        "routing_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_identity_id",
            sa.Integer(),
            sa.ForeignKey("channel_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "delivery_target_id",
            sa.Integer(),
            sa.ForeignKey("delivery_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "hermes_profile_id",
            sa.Integer(),
            sa.ForeignKey("hermes_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in (
        "organization_id",
        "channel_identity_id",
        "delivery_target_id",
        "member_user_id",
        "hermes_profile_id",
        "priority",
        "enabled",
    ):
        op.create_index(f"ix_routing_rules_{column}", "routing_rules", [column])

    op.create_table(
        "run_correlations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "routing_rule_id",
            sa.Integer(),
            sa.ForeignKey("routing_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_identity_id",
            sa.Integer(),
            sa.ForeignKey("channel_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "delivery_target_id",
            sa.Integer(),
            sa.ForeignKey("delivery_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("hermes_session_id", sa.String(100), nullable=False),
        sa.Column("hermes_run_id", sa.String(100), nullable=True, unique=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="started"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in (
        "organization_id",
        "routing_rule_id",
        "channel_identity_id",
        "delivery_target_id",
        "member_user_id",
        "hermes_session_id",
        "idempotency_key",
        "status",
    ):
        op.create_index(f"ix_run_correlations_{column}", "run_correlations", [column])

    op.create_table(
        "delivery_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_correlation_id",
            sa.Integer(),
            sa.ForeignKey("run_correlations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "delivery_target_id",
            sa.Integer(),
            sa.ForeignKey("delivery_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(120), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in (
        "organization_id",
        "run_correlation_id",
        "delivery_target_id",
        "event_type",
        "idempotency_key",
        "status",
    ):
        op.create_index(f"ix_delivery_outbox_{column}", "delivery_outbox", [column])


def downgrade() -> None:
    for column in (
        "status",
        "idempotency_key",
        "event_type",
        "delivery_target_id",
        "run_correlation_id",
        "organization_id",
    ):
        op.drop_index(f"ix_delivery_outbox_{column}", table_name="delivery_outbox")
    op.drop_table("delivery_outbox")

    for column in (
        "status",
        "idempotency_key",
        "hermes_session_id",
        "member_user_id",
        "delivery_target_id",
        "channel_identity_id",
        "routing_rule_id",
        "organization_id",
    ):
        op.drop_index(f"ix_run_correlations_{column}", table_name="run_correlations")
    op.drop_table("run_correlations")

    for column in (
        "enabled",
        "priority",
        "hermes_profile_id",
        "member_user_id",
        "delivery_target_id",
        "channel_identity_id",
        "organization_id",
    ):
        op.drop_index(f"ix_routing_rules_{column}", table_name="routing_rules")
    op.drop_table("routing_rules")

    op.drop_index("ix_delivery_targets_is_active", table_name="delivery_targets")
    op.drop_index("ix_delivery_targets_provider", table_name="delivery_targets")
    op.drop_index("ix_delivery_targets_organization_id", table_name="delivery_targets")
    op.drop_table("delivery_targets")

    op.drop_index("ix_channel_identities_is_active", table_name="channel_identities")
    op.drop_index("ix_channel_identities_provider", table_name="channel_identities")
    op.drop_index("ix_channel_identities_organization_id", table_name="channel_identities")
    op.drop_table("channel_identities")
