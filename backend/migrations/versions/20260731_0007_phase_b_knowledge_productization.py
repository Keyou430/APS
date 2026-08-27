"""Add phase B knowledge productization persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260731_0007"
down_revision: str | None = "20260731_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _upgrade_existing_tables() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        with op.batch_alter_table("organization_memberships", recreate="always") as batch:
            batch.create_unique_constraint(
                "uq_org_memberships_org_id", ["organization_id", "id"]
            )
        with op.batch_alter_table("knowledge_entries", recreate="always") as batch:
            batch.add_column(
                sa.Column(
                    "visibility", sa.String(30), nullable=False, server_default="private"
                )
            )
            batch.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )
            batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True)))
            batch.create_unique_constraint(
                "uq_knowledge_entries_org_id", ["organization_id", "id"]
            )
            batch.create_check_constraint(
                "ck_knowledge_entries_visibility",
                "visibility IN ('private', 'organization_members')",
            )
        with op.batch_alter_table("chat_sessions", recreate="always") as batch:
            batch.add_column(sa.Column("surface", sa.String(20), nullable=True))
            batch.add_column(sa.Column("knowledge_scope", sa.String(20), nullable=True))
            batch.create_unique_constraint(
                "uq_chat_sessions_org_id", ["organization_id", "id"]
            )
        with op.batch_alter_table("audit_events", recreate="always") as batch:
            batch.add_column(
                sa.Column(
                    "actor_kind", sa.String(20), nullable=False, server_default="user"
                )
            )
            batch.add_column(
                sa.Column(
                    "outcome", sa.String(30), nullable=False, server_default="success"
                )
            )
            batch.add_column(sa.Column("request_id", sa.String(100)))
        with op.batch_alter_table("knowledge_retrieval_events", recreate="always") as batch:
            batch.alter_column(
                "chat_session_id", existing_type=sa.Integer(), nullable=True
            )
            batch.alter_column("query_sha256", existing_type=sa.String(64), nullable=True)
            batch.add_column(sa.Column("query_hmac", sa.String(64)))
            batch.add_column(sa.Column("query_hmac_version", sa.Integer()))
            batch.add_column(
                sa.Column(
                    "request_kind", sa.String(20), nullable=False, server_default="rest"
                )
            )
            batch.add_column(
                sa.Column(
                    "retrieval_mode", sa.String(30), nullable=False, server_default="empty"
                )
            )
            batch.create_foreign_key(
                "fk_knowledge_retrieval_events_chat_session",
                "chat_sessions",
                ["chat_session_id"],
                ["id"],
                ondelete="SET NULL",
            )
        return

    op.create_unique_constraint(
        "uq_org_memberships_org_id",
        "organization_memberships",
        ["organization_id", "id"],
    )
    op.add_column(
        "knowledge_entries",
        sa.Column("visibility", sa.String(30), nullable=False, server_default="private"),
    )
    op.add_column(
        "knowledge_entries",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "knowledge_entries", sa.Column("archived_at", sa.DateTime(timezone=True))
    )
    op.create_check_constraint(
        "ck_knowledge_entries_visibility",
        "knowledge_entries",
        "visibility IN ('private', 'organization_members')",
    )
    op.create_unique_constraint(
        "uq_knowledge_entries_org_id",
        "knowledge_entries",
        ["organization_id", "id"],
    )
    op.add_column("chat_sessions", sa.Column("surface", sa.String(20), nullable=True))
    op.add_column(
        "chat_sessions", sa.Column("knowledge_scope", sa.String(20), nullable=True)
    )
    op.create_unique_constraint(
        "uq_chat_sessions_org_id", "chat_sessions", ["organization_id", "id"]
    )
    op.add_column(
        "audit_events",
        sa.Column("actor_kind", sa.String(20), nullable=False, server_default="user"),
    )
    op.add_column(
        "audit_events",
        sa.Column("outcome", sa.String(30), nullable=False, server_default="success"),
    )
    op.add_column("audit_events", sa.Column("request_id", sa.String(100)))
    op.alter_column(
        "knowledge_retrieval_events",
        "chat_session_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "knowledge_retrieval_events",
        "query_sha256",
        existing_type=sa.String(64),
        nullable=True,
    )
    op.add_column(
        "knowledge_retrieval_events", sa.Column("query_hmac", sa.String(64))
    )
    op.add_column(
        "knowledge_retrieval_events", sa.Column("query_hmac_version", sa.Integer())
    )
    op.add_column(
        "knowledge_retrieval_events",
        sa.Column("request_kind", sa.String(20), nullable=False, server_default="rest"),
    )
    op.add_column(
        "knowledge_retrieval_events",
        sa.Column("retrieval_mode", sa.String(30), nullable=False, server_default="empty"),
    )
    op.create_foreign_key(
        "fk_knowledge_retrieval_events_chat_session",
        "knowledge_retrieval_events",
        "chat_sessions",
        ["chat_session_id"],
        ["id"],
        ondelete="SET NULL",
    )


def upgrade() -> None:
    _upgrade_existing_tables()
    op.execute(
        sa.text(
            "UPDATE chat_sessions SET surface = CASE "
            "WHEN hermes_backend = 'agent' THEN 'agent' ELSE 'knowledge' END"
        )
    )
    op.execute(
        sa.text(
            "UPDATE chat_sessions SET knowledge_scope = CASE "
            "WHEN surface = 'knowledge' THEN 'all_visible' ELSE 'none' END"
        )
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("chat_sessions", recreate="always") as batch:
            batch.alter_column("surface", existing_type=sa.String(20), nullable=False)
            batch.alter_column(
                "knowledge_scope", existing_type=sa.String(20), nullable=False
            )
            batch.create_check_constraint(
                "ck_chat_sessions_surface", "surface IN ('agent', 'knowledge')"
            )
            batch.create_check_constraint(
                "ck_chat_sessions_knowledge_scope",
                "knowledge_scope IN ('all_visible', 'selected', 'none')",
            )
    else:
        op.alter_column("chat_sessions", "surface", existing_type=sa.String(20), nullable=False)
        op.alter_column(
            "chat_sessions", "knowledge_scope", existing_type=sa.String(20), nullable=False
        )
        op.create_check_constraint(
            "ck_chat_sessions_surface",
            "chat_sessions",
            "surface IN ('agent', 'knowledge')",
        )
        op.create_check_constraint(
            "ck_chat_sessions_knowledge_scope",
            "chat_sessions",
            "knowledge_scope IN ('all_visible', 'selected', 'none')",
        )

    op.create_index("ix_knowledge_entries_visibility", "knowledge_entries", ["visibility"])
    op.create_index("ix_knowledge_entries_archived_at", "knowledge_entries", ["archived_at"])
    op.create_index("ix_chat_sessions_surface", "chat_sessions", ["surface"])
    op.create_index("ix_audit_events_outcome", "audit_events", ["outcome"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])
    op.create_index(
        "ix_knowledge_retrieval_events_request_kind",
        "knowledge_retrieval_events",
        ["request_kind"],
    )
    op.create_index(
        "ix_knowledge_retrieval_events_retrieval_mode",
        "knowledge_retrieval_events",
        ["retrieval_mode"],
    )

    op.create_table(
        "knowledge_access_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_entry_id", sa.Integer(), nullable=False),
        sa.Column("grantee_membership_id", sa.Integer(), nullable=False),
        sa.Column("capability", sa.String(20), nullable=False, server_default="read"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "knowledge_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
            name="fk_knowledge_grants_org_entry",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "grantee_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="CASCADE",
            name="fk_knowledge_grants_org_membership",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("capability = 'read'", name="ck_knowledge_grants_capability"),
    )
    for column in (
        "organization_id",
        "knowledge_entry_id",
        "grantee_membership_id",
        "expires_at",
        "revoked_at",
        "granted_by_user_id",
    ):
        op.create_index(f"ix_knowledge_access_grants_{column}", "knowledge_access_grants", [column])
    op.create_index(
        "uq_knowledge_grants_active_entry_membership",
        "knowledge_access_grants",
        ["knowledge_entry_id", "grantee_membership_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("normalized_email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="guest"),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "invited_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("membership_expires_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_org_invitations_org_id"),
        sa.CheckConstraint("role = 'guest'", name="ck_org_invitations_guest_role"),
    )
    for column in (
        "organization_id",
        "normalized_email",
        "token_digest",
        "invited_by_user_id",
        "token_expires_at",
    ):
        op.create_index(
            f"ix_organization_invitations_{column}",
            "organization_invitations",
            [column],
            unique=column == "token_digest",
        )

    op.create_table(
        "organization_invitation_resources",
        sa.Column("invitation_id", sa.Integer(), primary_key=True),
        sa.Column("knowledge_entry_id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "invitation_id"],
            ["organization_invitations.organization_id", "organization_invitations.id"],
            ondelete="CASCADE",
            name="fk_invitation_resources_org_invitation",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "knowledge_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
            name="fk_invitation_resources_org_entry",
        ),
    )
    op.create_index(
        "ix_organization_invitation_resources_organization_id",
        "organization_invitation_resources",
        ["organization_id"],
    )

    op.create_table(
        "chat_session_knowledge_sources",
        sa.Column("chat_session_id", sa.Integer(), primary_key=True),
        sa.Column("knowledge_entry_id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "chat_session_id"],
            ["chat_sessions.organization_id", "chat_sessions.id"],
            ondelete="CASCADE",
            name="fk_chat_sources_org_session",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "knowledge_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
            name="fk_chat_sources_org_entry",
        ),
    )
    op.create_index(
        "ix_chat_session_knowledge_sources_organization_id",
        "chat_session_knowledge_sources",
        ["organization_id"],
    )

    op.create_table(
        "chat_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chat_session_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="retrieving"),
        sa.Column("retrieval_mode", sa.String(30), nullable=False, server_default="empty"),
        sa.Column("assistant_message_id", sa.String(100)),
        sa.Column("question_hmac", sa.String(64)),
        sa.Column("question_hmac_version", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "chat_session_id"],
            ["chat_sessions.organization_id", "chat_sessions.id"],
            ondelete="CASCADE",
            name="fk_chat_turns_org_session",
        ),
        sa.UniqueConstraint("chat_session_id", "run_id", name="uq_chat_turns_session_run"),
    )
    for column in (
        "organization_id",
        "user_id",
        "chat_session_id",
        "run_id",
        "status",
        "assistant_message_id",
    ):
        op.create_index(f"ix_chat_turns_{column}", "chat_turns", [column])

    op.create_table(
        "chat_turn_citations",
        sa.Column(
            "chat_turn_id",
            sa.Integer(),
            sa.ForeignKey("chat_turns.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column(
            "knowledge_entry_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_entries.id", ondelete="SET NULL"),
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_locator", sa.String(500)),
        sa.Column("title_snapshot", sa.String(255), nullable=False),
    )
    op.create_index(
        "ix_chat_turn_citations_knowledge_entry_id",
        "chat_turn_citations",
        ["knowledge_entry_id"],
    )


def downgrade() -> None:
    op.drop_table("chat_turn_citations")
    op.drop_table("chat_turns")
    op.drop_table("chat_session_knowledge_sources")
    op.drop_table("organization_invitation_resources")
    op.drop_table("organization_invitations")
    op.drop_table("knowledge_access_grants")

    op.drop_index(
        "ix_knowledge_retrieval_events_retrieval_mode",
        table_name="knowledge_retrieval_events",
    )
    op.drop_index(
        "ix_knowledge_retrieval_events_request_kind",
        table_name="knowledge_retrieval_events",
    )
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_outcome", table_name="audit_events")
    op.drop_index("ix_chat_sessions_surface", table_name="chat_sessions")
    op.drop_index("ix_knowledge_entries_archived_at", table_name="knowledge_entries")
    op.drop_index("ix_knowledge_entries_visibility", table_name="knowledge_entries")

    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        with op.batch_alter_table("knowledge_retrieval_events", recreate="always") as batch:
            batch.drop_constraint(
                "fk_knowledge_retrieval_events_chat_session", type_="foreignkey"
            )
            batch.drop_column("retrieval_mode")
            batch.drop_column("request_kind")
            batch.drop_column("query_hmac_version")
            batch.drop_column("query_hmac")
            batch.alter_column("query_sha256", existing_type=sa.String(64), nullable=False)
            batch.alter_column(
                "chat_session_id", existing_type=sa.Integer(), nullable=False
            )
        with op.batch_alter_table("audit_events", recreate="always") as batch:
            batch.drop_column("request_id")
            batch.drop_column("outcome")
            batch.drop_column("actor_kind")
        with op.batch_alter_table("chat_sessions", recreate="always") as batch:
            batch.drop_constraint("ck_chat_sessions_knowledge_scope", type_="check")
            batch.drop_constraint("ck_chat_sessions_surface", type_="check")
            batch.drop_constraint("uq_chat_sessions_org_id", type_="unique")
            batch.drop_column("knowledge_scope")
            batch.drop_column("surface")
        with op.batch_alter_table("knowledge_entries", recreate="always") as batch:
            batch.drop_constraint("ck_knowledge_entries_visibility", type_="check")
            batch.drop_constraint("uq_knowledge_entries_org_id", type_="unique")
            batch.drop_column("archived_at")
            batch.drop_column("updated_at")
            batch.drop_column("visibility")
        with op.batch_alter_table("organization_memberships", recreate="always") as batch:
            batch.drop_constraint("uq_org_memberships_org_id", type_="unique")
        return

    for column in (
        "retrieval_mode",
        "request_kind",
        "query_hmac_version",
        "query_hmac",
    ):
        op.drop_column("knowledge_retrieval_events", column)
    op.drop_constraint(
        "fk_knowledge_retrieval_events_chat_session",
        "knowledge_retrieval_events",
        type_="foreignkey",
    )
    op.alter_column(
        "knowledge_retrieval_events",
        "query_sha256",
        existing_type=sa.String(64),
        nullable=False,
    )
    op.alter_column(
        "knowledge_retrieval_events",
        "chat_session_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    for column in ("request_id", "outcome", "actor_kind"):
        op.drop_column("audit_events", column)
    op.drop_constraint("ck_chat_sessions_knowledge_scope", "chat_sessions", type_="check")
    op.drop_constraint("ck_chat_sessions_surface", "chat_sessions", type_="check")
    op.drop_constraint("uq_chat_sessions_org_id", "chat_sessions", type_="unique")
    op.drop_column("chat_sessions", "knowledge_scope")
    op.drop_column("chat_sessions", "surface")
    op.drop_constraint(
        "uq_knowledge_entries_org_id", "knowledge_entries", type_="unique"
    )
    op.drop_constraint(
        "ck_knowledge_entries_visibility", "knowledge_entries", type_="check"
    )
    op.drop_column("knowledge_entries", "archived_at")
    op.drop_column("knowledge_entries", "updated_at")
    op.drop_column("knowledge_entries", "visibility")
    op.drop_constraint(
        "uq_org_memberships_org_id", "organization_memberships", type_="unique"
    )
