from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false as sa_false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from pgvector.sqlalchemy import Vector

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    users: Mapped[list[User]] = relationship(back_populates="role")
    permission_links: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    memberships: Mapped[list[OrganizationMembership]] = relationship(back_populates="role")


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255))

    role_links: Mapped[list[RolePermission]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )

    role: Mapped[Role] = relationship(back_populates="permission_links")
    permission: Mapped[Permission] = relationship(back_populates="role_links")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    normalized_email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    default_organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    role: Mapped[Role] = relationship(back_populates="users", lazy="joined")
    default_organization: Mapped[Organization] = relationship()
    memberships: Mapped[list[OrganizationMembership]] = relationship(back_populates="user")
    hermes_profiles: Mapped[list[HermesProfile]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @validates("email")
    def normalize_email(self, _key: str, value: str) -> str:
        self.normalized_email = value.strip().casefold()
        return value


class OrganizationMembership(Base, TimestampMixin):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_memberships_org_user"),
        UniqueConstraint("organization_id", "id", name="uq_org_memberships_org_id"),
        CheckConstraint(
            "member_type IN ('internal', 'guest')",
            name="ck_org_memberships_member_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    member_type: Mapped[str] = mapped_column(String(20), default="internal", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
    role: Mapped[Role] = relationship(back_populates="memberships")


class OrganizationUnit(Base, TimestampMixin):
    __tablename__ = "organization_units"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_organization_units_org_id"),
        UniqueConstraint("organization_id", "code", name="uq_organization_units_org_code"),
        ForeignKeyConstraint(
            ["organization_id", "parent_id"],
            ["organization_units.organization_id", "organization_units.id"],
            ondelete="RESTRICT",
            name="fk_organization_units_org_parent",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrganizationPosition(Base, TimestampMixin):
    __tablename__ = "organization_positions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "id", name="uq_organization_positions_org_id"
        ),
        ForeignKeyConstraint(
            ["organization_id", "unit_id"],
            ["organization_units.organization_id", "organization_units.id"],
            ondelete="RESTRICT",
            name="fk_organization_positions_org_unit",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255))
    level: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrganizationPlacement(Base, TimestampMixin):
    __tablename__ = "organization_placements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="CASCADE",
            name="fk_organization_placements_org_membership",
        ),
        ForeignKeyConstraint(
            ["organization_id", "unit_id"],
            ["organization_units.organization_id", "organization_units.id"],
            ondelete="RESTRICT",
            name="fk_organization_placements_org_unit",
        ),
        ForeignKeyConstraint(
            ["organization_id", "position_id"],
            ["organization_positions.organization_id", "organization_positions.id"],
            ondelete="RESTRICT",
            name="fk_organization_placements_org_position",
        ),
        ForeignKeyConstraint(
            ["organization_id", "manager_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
            name="fk_organization_placements_org_manager",
        ),
    )

    membership_id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    unit_id: Mapped[int] = mapped_column(Integer, index=True)
    position_id: Mapped[int] = mapped_column(Integer, index=True)
    manager_membership_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrganizationStructureState(Base):
    __tablename__ = "organization_structure_state"

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PortalAnnouncement(Base, TimestampMixin):
    __tablename__ = "portal_announcements"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "id", name="uq_portal_announcements_org_id"
        ),
        ForeignKeyConstraint(
            ["organization_id", "author_user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            ondelete="RESTRICT",
            name="fk_portal_announcements_org_author",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'withdrawn')",
            name="ck_portal_announcements_status",
        ),
        CheckConstraint(
            "priority IN ('normal', 'important')",
            name="ck_portal_announcements_priority",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PortalAnnouncementRead(Base):
    __tablename__ = "portal_announcement_reads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "announcement_id"],
            ["portal_announcements.organization_id", "portal_announcements.id"],
            ondelete="CASCADE",
            name="fk_portal_reads_org_announcement",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            ondelete="CASCADE",
            name="fk_portal_reads_org_user",
        ),
    )

    announcement_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkItem(Base, TimestampMixin):
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_work_items_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "assignee_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
            name="fk_work_items_org_assignee",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
            name="fk_work_items_org_creator",
        ),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'cancelled')",
            name="ck_work_items_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="ck_work_items_priority",
        ),
        CheckConstraint(
            "origin IN ('manual', 'reminder', 'chat', 'agent')",
            name="ck_work_items_origin",
        ),
        CheckConstraint(
            "task_scope IN ('day', 'week')",
            name="ck_work_items_task_scope",
        ),
        CheckConstraint(
            "original_scope IS NULL OR original_scope IN ('day', 'week')",
            name="ck_work_items_original_scope",
        ),
        CheckConstraint(
            "archive_reason IS NULL OR archive_reason IN ('overdue')",
            name="ck_work_items_archive_reason",
        ),
        CheckConstraint(
            "archived_at IS NULL OR (task_scope = 'week' AND original_scope = 'day' "
            "AND original_due_at IS NOT NULL AND archive_reason = 'overdue' "
            "AND archive_batch_id IS NOT NULL AND week_key IS NOT NULL)",
            name="ck_work_items_archive_trace",
        ),
        CheckConstraint(
            "(task_scope = 'day' AND archived_at IS NULL) OR archive_after IS NULL",
            name="ck_work_items_archive_after_scope",
        ),
        Index(
            "ix_work_items_day_archive_due",
            "archive_after",
            "id",
            postgresql_where=text(
                "task_scope = 'day' AND archived_at IS NULL AND archive_after IS NOT NULL "
                "AND status IN ('pending', 'in_progress')"
            ),
            sqlite_where=text(
                "task_scope = 'day' AND archived_at IS NULL AND archive_after IS NOT NULL "
                "AND status IN ('pending', 'in_progress')"
            ),
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    assignee_membership_id: Mapped[int] = mapped_column(Integer, index=True)
    created_by_membership_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    task_scope: Mapped[str] = mapped_column(String(10), default="day")
    archive_timezone: Mapped[str] = mapped_column(String(80), default="Asia/Shanghai")
    archive_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_scope: Mapped[str | None] = mapped_column(String(10), nullable=True)
    original_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    archive_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    week_key: Mapped[str | None] = mapped_column(String(10), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    source_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkItemEvent(Base):
    __tablename__ = "work_item_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "work_item_id"],
            ["work_items.organization_id", "work_items.id"],
            ondelete="CASCADE",
            name="fk_work_item_events_org_item",
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
            name="fk_work_item_events_org_actor",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    work_item_id: Mapped[int] = mapped_column(Integer, index=True)
    actor_membership_id: Mapped[int] = mapped_column(Integer, index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class DashboardLayout(Base):
    __tablename__ = "dashboard_layouts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_dashboard_layouts_org_user"
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_dashboard_layouts_org_user",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    layouts: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    actor_kind: Mapped[str] = mapped_column(String(20), default="user")
    outcome: Mapped[str] = mapped_column(String(30), default="success", index=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class ChannelIdentity(Base, TimestampMixin):
    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "external_user_id",
            "external_conversation_id",
            name="uq_channel_identities_external",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(30), index=True)
    external_user_id: Mapped[str] = mapped_column(String(255))
    external_conversation_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    routing_rules: Mapped[list[RoutingRule]] = relationship(back_populates="channel_identity")


class DeliveryTarget(Base, TimestampMixin):
    __tablename__ = "delivery_targets"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "external_conversation_id",
            name="uq_delivery_targets_external",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(30), index=True)
    external_conversation_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    routing_rules: Mapped[list[RoutingRule]] = relationship(back_populates="delivery_target")
    outbox_items: Mapped[list[DeliveryOutbox]] = relationship(back_populates="delivery_target")


class RoutingRule(Base, TimestampMixin):
    __tablename__ = "routing_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    channel_identity_id: Mapped[int] = mapped_column(
        ForeignKey("channel_identities.id", ondelete="CASCADE"), index=True
    )
    delivery_target_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_targets.id", ondelete="CASCADE"), index=True
    )
    member_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    hermes_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("hermes_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    channel_identity: Mapped[ChannelIdentity] = relationship(back_populates="routing_rules")
    delivery_target: Mapped[DeliveryTarget] = relationship(back_populates="routing_rules")
    correlations: Mapped[list[RunCorrelation]] = relationship(back_populates="routing_rule")


class RunCorrelation(Base, TimestampMixin):
    __tablename__ = "run_correlations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    routing_rule_id: Mapped[int] = mapped_column(
        ForeignKey("routing_rules.id", ondelete="CASCADE"), index=True
    )
    channel_identity_id: Mapped[int] = mapped_column(
        ForeignKey("channel_identities.id", ondelete="CASCADE"), index=True
    )
    delivery_target_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_targets.id", ondelete="CASCADE"), index=True
    )
    member_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    hermes_session_id: Mapped[str] = mapped_column(String(100), index=True)
    hermes_run_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="started", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    routing_rule: Mapped[RoutingRule] = relationship(back_populates="correlations")
    outbox_items: Mapped[list[DeliveryOutbox]] = relationship(back_populates="correlation")


class DeliveryOutbox(Base, TimestampMixin):
    __tablename__ = "delivery_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # Nullable: platform-owned decision notifications do not originate from a
    # channel run correlation.
    run_correlation_id: Mapped[int | None] = mapped_column(
        ForeignKey("run_correlations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    delivery_target_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_targets.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    correlation: Mapped[RunCorrelation | None] = relationship(
        back_populates="outbox_items"
    )
    delivery_target: Mapped[DeliveryTarget] = relationship(back_populates="outbox_items")


class HermesProfile(Base, TimestampMixin):
    __tablename__ = "hermes_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_hermes_profiles_organization_user",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    profile_name: Mapped[str] = mapped_column(String(100), unique=True)
    hermes_home: Mapped[str] = mapped_column(String(500), unique=True)
    port: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="stopped")

    user: Mapped[User] = relationship(back_populates="hermes_profiles")


class KnowledgeCollection(Base, TimestampMixin):
    __tablename__ = "knowledge_collections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_knowledge_collections_org_id",
        ),
        ForeignKeyConstraint(
            ["organization_id", "parent_id"],
            ["knowledge_collections.organization_id", "knowledge_collections.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_collections_org_parent",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeEntry(Base, TimestampMixin):
    __tablename__ = "knowledge_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_knowledge_entries_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "collection_id"],
            ["knowledge_collections.organization_id", "knowledge_collections.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_entries_org_collection",
        ),
        CheckConstraint(
            "visibility IN ('private', 'organization_members')",
            name="ck_knowledge_entries_visibility",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    collection_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    visibility: Mapped[str] = mapped_column(String(30), default="private", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class ExperienceDomain(Base, TimestampMixin):
    __tablename__ = "experience_domains"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_experience_domains_org_name"),
        UniqueConstraint("organization_id", "id", name="uq_experience_domains_org_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExperienceMethod(Base, TimestampMixin):
    __tablename__ = "experience_methods"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "id", name="uq_experience_methods_org_id"
        ),
        ForeignKeyConstraint(
            ["organization_id", "domain_id"],
            ["experience_domains.organization_id", "experience_domains.id"],
            ondelete="CASCADE",
            name="fk_experience_methods_org_domain",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_experience_methods_org_creator",
        ),
        CheckConstraint(
            "source_type IN ('human', 'ai_summary')",
            name="ck_experience_methods_source_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    domain_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="human")
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeAccessGrant(Base, TimestampMixin):
    __tablename__ = "knowledge_access_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "knowledge_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
            name="fk_knowledge_grants_org_entry",
        ),
        ForeignKeyConstraint(
            ["organization_id", "grantee_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="CASCADE",
            name="fk_knowledge_grants_org_membership",
        ),
        Index(
            "uq_knowledge_grants_active_entry_membership",
            "knowledge_entry_id",
            "grantee_membership_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
        CheckConstraint("capability = 'read'", name="ck_knowledge_grants_capability"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    knowledge_entry_id: Mapped[int] = mapped_column(Integer, index=True)
    grantee_membership_id: Mapped[int] = mapped_column(Integer, index=True)
    capability: Mapped[str] = mapped_column(String(20), default="read")
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    granted_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )


class OrganizationInvitation(Base, TimestampMixin):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_org_invitations_org_id"),
        CheckConstraint("role = 'guest'", name="ck_org_invitations_guest_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    normalized_email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(20), default="guest")
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    membership_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrganizationInvitationResource(Base):
    __tablename__ = "organization_invitation_resources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "invitation_id"],
            ["organization_invitations.organization_id", "organization_invitations.id"],
            ondelete="CASCADE",
            name="fk_invitation_resources_org_invitation",
        ),
        ForeignKeyConstraint(
            ["organization_id", "knowledge_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
            name="fk_invitation_resources_org_entry",
        ),
    )

    invitation_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_entry_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)


class KnowledgeIngestionJob(Base, TimestampMixin):
    __tablename__ = "knowledge_ingestion_jobs"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_entry_id",
            "content_sha256",
            name="uq_knowledge_ingestion_jobs_entry_hash",
        ),
        Index(
            "ix_knowledge_ingestion_jobs_scope",
            "organization_id",
            "user_id",
            "knowledge_entry_id",
        ),
        Index("ix_knowledge_ingestion_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    knowledge_entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entries.id", ondelete="CASCADE")
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    parser_version: Mapped[str] = mapped_column(String(50))
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=1024)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class KnowledgeChunk(Base, TimestampMixin):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_entry_id",
            "content_sha256",
            "ordinal",
            name="uq_knowledge_chunks_entry_hash_ordinal",
        ),
        Index(
            "ix_knowledge_chunks_scope",
            "organization_id",
            "user_id",
            "knowledge_entry_id",
        ),
        Index(
            "ix_knowledge_chunks_text_fts",
            text("to_tsvector('simple', text)"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            info={"skip_autogenerate_sqlite": True},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    knowledge_entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entries.id", ondelete="CASCADE")
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    source_locator: Mapped[str | None] = mapped_column(String(500), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024).with_variant(JSON, "sqlite"))


class KnowledgeRetrievalEvent(Base, TimestampMixin):
    __tablename__ = "knowledge_retrieval_events"
    __table_args__ = (
        Index(
            "ix_knowledge_retrieval_events_scope",
            "organization_id",
            "user_id",
            "chat_session_id",
        ),
        Index(
            "ix_knowledge_retrieval_events_session_created_at",
            "chat_session_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    chat_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    query_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query_hmac_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_kind: Mapped[str] = mapped_column(String(20), default="rest", index=True)
    retrieval_mode: Mapped[str] = mapped_column(String(30), default="empty", index=True)
    result_count: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(30))


class MemoryCaptureSource(Base, TimestampMixin):
    __tablename__ = "memory_capture_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_memory_capture_sources_org_user",
        ),
        ForeignKeyConstraint(
            ["organization_id", "chat_session_id"],
            ["chat_sessions.organization_id", "chat_sessions.id"],
            ondelete="CASCADE",
            name="fk_memory_capture_sources_org_session",
        ),
        ForeignKeyConstraint(
            ["organization_id", "chat_turn_id"],
            ["chat_turns.organization_id", "chat_turns.id"],
            ondelete="CASCADE",
            name="fk_memory_capture_sources_org_turn",
        ),
        UniqueConstraint(
            "organization_id",
            "chat_turn_id",
            "content_sha256",
            name="uq_memory_capture_sources_org_turn_hash",
        ),
        UniqueConstraint(
            "organization_id",
            "user_id",
            "id",
            name="uq_memory_capture_sources_org_user_id",
        ),
        CheckConstraint(
            "status IN ('captured', 'queued', 'completed', 'failed', 'cancelled', 'purged')",
            name="ck_memory_capture_sources_status",
        ),
        Index(
            "ix_memory_capture_sources_org_user",
            "organization_id",
            "user_id",
        ),
        Index(
            "ix_memory_capture_sources_org_session",
            "organization_id",
            "chat_session_id",
        ),
        Index(
            "ix_memory_capture_sources_org_turn",
            "organization_id",
            "chat_turn_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    chat_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chat_turn_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(30), default="user_text")
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="captured")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryRecord(Base, TimestampMixin):
    __tablename__ = "memory_records"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            "memory_id",
            name="uq_memory_records_org_user_id",
        ),
        UniqueConstraint(
            "organization_id",
            "user_id",
            "candidate_key",
            name="uq_memory_records_org_user_candidate_key",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_memory_records_org_user",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id", "supersedes_memory_id"],
            [
                "memory_records.organization_id",
                "memory_records.user_id",
                "memory_records.memory_id",
            ],
            ondelete="RESTRICT",
            name="fk_memory_records_org_user_supersedes",
        ),
        CheckConstraint(
            "type IN ('memory', 'fact', 'preference', 'decision', 'context')",
            name="ck_memory_records_type",
        ),
        CheckConstraint("layer IN ('L1', 'L2', 'L3')", name="ck_memory_records_layer"),
        CheckConstraint(
            "status IN ('candidate', 'active', 'superseded')",
            name="ck_memory_records_status",
        ),
        CheckConstraint(
            "origin IN ('manual', 'extracted', 'imported')",
            name="ck_memory_records_origin",
        ),
        CheckConstraint("revision > 0", name="ck_memory_records_revision_positive"),
        CheckConstraint(
            "embedding_state IN ('not_configured', 'pending', 'ready', 'failed')",
            name="ck_memory_records_embedding_state",
        ),
        Index(
            "ix_memory_records_active_owner_list",
            "organization_id",
            "user_id",
            "updated_at",
            "memory_id",
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_memory_records_org_user_supersedes",
            "organization_id",
            "user_id",
            "supersedes_memory_id",
        ),
        Index(
            "ix_memory_records_active_fts",
            text("to_tsvector('simple', content)"),
            postgresql_using="gin",
            postgresql_where=text("status = 'active'"),
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_memory_records_active_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL AND status = 'active'"),
            info={"skip_autogenerate_sqlite": True},
        ).ddl_if(dialect="postgresql"),
    )

    memory_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(30), default="memory")
    layer: Mapped[str] = mapped_column(String(2), default="L1")
    status: Mapped[str] = mapped_column(String(20), default="active")
    origin: Mapped[str] = mapped_column(String(20), default="manual")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    source_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supersedes_memory_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    candidate_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024).with_variant(JSON, "sqlite"), nullable=True
    )
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    embedding_state: Mapped[str] = mapped_column(
        String(20), default="not_configured", server_default="not_configured"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemoryEmbeddingJob(Base, TimestampMixin):
    __tablename__ = "memory_embedding_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id", "memory_id"],
            [
                "memory_records.organization_id",
                "memory_records.user_id",
                "memory_records.memory_id",
            ],
            ondelete="CASCADE",
            name="fk_memory_embedding_jobs_org_user_record",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')",
            name="ck_memory_embedding_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_memory_embedding_jobs_attempts"),
        CheckConstraint("max_attempts > 0", name="ck_memory_embedding_jobs_max_attempts"),
        Index(
            "ix_memory_embedding_jobs_org_user_record",
            "organization_id",
            "user_id",
            "memory_id",
        ),
        Index(
            "ix_memory_embedding_jobs_claim",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text("status = 'queued'"),
            sqlite_where=text("status = 'queued'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    memory_id: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemoryVersion(Base, TimestampMixin):
    __tablename__ = "memory_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id", "memory_id"],
            [
                "memory_records.organization_id",
                "memory_records.user_id",
                "memory_records.memory_id",
            ],
            ondelete="CASCADE",
            name="fk_memory_versions_org_user_record",
        ),
        UniqueConstraint("memory_id", "revision", name="uq_memory_versions_record_revision"),
        Index(
            "ix_memory_versions_org_user_record",
            "organization_id",
            "user_id",
            "memory_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    memory_id: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(30))
    layer: Mapped[str] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(20))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    source_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_version: Mapped[str | None] = mapped_column(String(50), nullable=True)


class MemorySourceLink(Base, TimestampMixin):
    __tablename__ = "memory_source_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id", "memory_id"],
            [
                "memory_records.organization_id",
                "memory_records.user_id",
                "memory_records.memory_id",
            ],
            ondelete="CASCADE",
            name="fk_memory_source_links_org_user_record",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id", "source_id"],
            [
                "memory_capture_sources.organization_id",
                "memory_capture_sources.user_id",
                "memory_capture_sources.id",
            ],
            ondelete="CASCADE",
            name="fk_memory_source_links_org_user_source",
        ),
        UniqueConstraint("memory_id", "source_id", name="uq_memory_source_links_record_source"),
        Index(
            "ix_memory_source_links_org_user_record",
            "organization_id",
            "user_id",
            "memory_id",
        ),
        Index(
            "ix_memory_source_links_org_user_source",
            "organization_id",
            "user_id",
            "source_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    memory_id: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_tombstoned: Mapped[bool] = mapped_column(Boolean, default=False)


class MemoryExtractionJob(Base, TimestampMixin):
    __tablename__ = "memory_extraction_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id", "source_id"],
            [
                "memory_capture_sources.organization_id",
                "memory_capture_sources.user_id",
                "memory_capture_sources.id",
            ],
            ondelete="CASCADE",
            name="fk_memory_extraction_jobs_org_user_source",
        ),
        UniqueConstraint(
            "source_id",
            "provider",
            "provider_version",
            name="uq_memory_extraction_jobs_source_provider_version",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')",
            name="ck_memory_extraction_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_memory_extraction_jobs_attempts"),
        CheckConstraint("max_attempts > 0", name="ck_memory_extraction_jobs_max_attempts"),
        Index(
            "ix_memory_extraction_jobs_org_user_source",
            "organization_id",
            "user_id",
            "source_id",
        ),
        Index(
            "ix_memory_extraction_jobs_claim",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text("status = 'queued'"),
            sqlite_where=text("status = 'queued'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    provider: Mapped[str] = mapped_column(String(100))
    provider_version: Mapped[str] = mapped_column(String(50))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemoryRetrievalEvent(Base, TimestampMixin):
    __tablename__ = "memory_retrieval_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_memory_retrieval_events_org_user",
        ),
        ForeignKeyConstraint(
            ["organization_id", "chat_session_id"],
            ["chat_sessions.organization_id", "chat_sessions.id"],
            name="fk_memory_retrieval_events_org_session",
        ),
        Index(
            "ix_memory_retrieval_events_org_user_created",
            "organization_id",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_memory_retrieval_events_org_session",
            "organization_id",
            "chat_session_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    chat_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query_hmac_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_mode: Mapped[str] = mapped_column(String(10), default="off", server_default="off")
    retrieval_mode: Mapped[str] = mapped_column(String(30), default="fts")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(30), default="success")


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'reviewed', 'published', 'archived')",
            name="ck_skills_status",
        ),
        CheckConstraint("revision > 0", name="ck_skills_revision_positive"),
        Index(
            "ix_skills_owner_catalog",
            "organization_id",
            "user_id",
            "status",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(30), index=True)
    content: Mapped[str] = mapped_column(Text)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    current_version: Mapped[str] = mapped_column(String(20), default="v1", server_default="v1")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_promoted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SkillAccessGrant(Base, TimestampMixin):
    __tablename__ = "skill_access_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
            name="fk_skill_access_grants_skill",
        ),
        ForeignKeyConstraint(
            ["grantor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_skill_access_grants_grantor",
        ),
        ForeignKeyConstraint(
            ["organization_id", "grantee_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_skill_access_grants_org_grantee",
        ),
        CheckConstraint(
            "capability IN ('read')",
            name="ck_skill_access_grants_capability",
        ),
        Index(
            "uq_skill_access_grants_active",
            "skill_id",
            "grantee_user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
        Index("ix_skill_access_grants_skill", "skill_id"),
        Index("ix_skill_access_grants_grantor", "grantor_user_id"),
        Index("ix_skill_access_grants_org_grantee", "organization_id", "grantee_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    skill_id: Mapped[int] = mapped_column(Integer)
    grantor_user_id: Mapped[int] = mapped_column(Integer)
    grantee_user_id: Mapped[int] = mapped_column(Integer)
    capability: Mapped[str] = mapped_column(String(20), default="read", server_default="read")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SkillVersion(Base, TimestampMixin):
    __tablename__ = "skill_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
            name="fk_skill_versions_skill",
        ),
        UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
        Index("ix_skill_versions_org_skill", "organization_id", "skill_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    skill_id: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_projects_org_id"),
        CheckConstraint("visibility IN ('public', 'private')", name="ck_projects_visibility"),
        CheckConstraint("roster_revision > 0", name="ck_projects_roster_revision"),
        Index(
            "ix_projects_org_visibility",
            "organization_id",
            "visibility",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(20), default="private", server_default="private"
    )
    roster_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectMember(Base, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
            name="fk_project_members_org_project",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_project_members_org_user",
        ),
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        CheckConstraint("role IN ('member', 'admin')", name="ck_project_members_role"),
        Index("ix_project_members_org_project", "organization_id", "project_id"),
        Index("ix_project_members_org_user", "organization_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20), default="member")


class ProjectResourceLink(Base, TimestampMixin):
    __tablename__ = "project_resource_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
            name="fk_project_resource_links_org_project",
        ),
        UniqueConstraint(
            "project_id",
            "resource_type",
            "ref_id",
            name="uq_project_resource_links_ref",
        ),
        CheckConstraint(
            "resource_type IN ('knowledge', 'memory', 'skill', 'work_item')",
            name="ck_project_resource_links_type",
        ),
        Index("ix_project_resource_links_org_project", "organization_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[int] = mapped_column(Integer)
    resource_type: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[str] = mapped_column(String(64))
    ord: Mapped[int] = mapped_column(Integer, default=0)


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    type: Mapped[str] = mapped_column(String(20), default="one-time")
    recurrence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    notification_channel: Mapped[str] = mapped_column(String(20), default="in-app")


class PipelineTask(Base, TimestampMixin):
    __tablename__ = "pipeline_tasks"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "creation_key", name="uq_pipeline_tasks_creation_key"),
        CheckConstraint("task_type IN ('web_research', 'general')", name="ck_pipeline_tasks_type"),
        CheckConstraint("output_format IN ('markdown')", name="ck_pipeline_tasks_output_format"),
        CheckConstraint("status IN ('ready', 'paused', 'deleted')", name="ck_pipeline_tasks_status"),
        CheckConstraint("revision > 0", name="ck_pipeline_tasks_revision_positive"),
        Index("ix_pipeline_tasks_owner_list", "organization_id", "user_id", "updated_at", "id"),
        Index(
            "ix_pipeline_tasks_schedule",
            "next_run_at",
            "id",
            postgresql_where=text("status = 'ready'"),
            sqlite_where=text("status = 'ready'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(40), default="general")
    schedule: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Shanghai")
    input_sources: Mapped[list] = mapped_column(JSON, default=list)
    output_format: Mapped[str] = mapped_column(String(20), default="markdown")
    status: Mapped[str] = mapped_column(String(20), default="ready", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    creation_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PipelineRun(Base, TimestampMixin):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "task_id", "idempotency_key", name="uq_pipeline_runs_idempotency"),
        UniqueConstraint("organization_id", "task_id", "scheduled_for", name="uq_pipeline_runs_schedule"),
        CheckConstraint("trigger_kind IN ('scheduled', 'manual')", name="ck_pipeline_runs_trigger_kind"),
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'missed')", name="ck_pipeline_runs_status"),
        Index("ix_pipeline_runs_claim", "status", "scheduled_for", "lease_expires_at", "id"),
        Index("ix_pipeline_runs_owner", "organization_id", "user_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("pipeline_tasks.id", ondelete="CASCADE"), index=True)
    trigger_kind: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineOutput(Base, TimestampMixin):
    __tablename__ = "pipeline_outputs"
    __table_args__ = (
        UniqueConstraint("organization_id", "run_id", "version", name="uq_pipeline_outputs_run_version"),
        Index("ix_pipeline_outputs_owner", "organization_id", "user_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("pipeline_tasks.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(255))
    markdown: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(String(500))
    content_sha256: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSON, default=list)


class DashboardDecision(Base, TimestampMixin):
    __tablename__ = "dashboard_decisions"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'changes_requested', 'regenerating', 'superseded')", name="ck_dashboard_decisions_status"),
        Index("ix_dashboard_decisions_owner", "organization_id", "user_id", "status", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("pipeline_tasks.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    output_id: Mapped[int] = mapped_column(ForeignKey("pipeline_outputs.id", ondelete="CASCADE"), index=True)
    regeneration_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    change_request: Mapped[str | None] = mapped_column(Text, nullable=True)


class DecisionAction(Base, TimestampMixin):
    __tablename__ = "decision_actions"
    __table_args__ = (
        UniqueConstraint("organization_id", "decision_id", "idempotency_key", name="uq_decision_actions_idempotency"),
        CheckConstraint("action IN ('approve', 'reject', 'regenerate')", name="ck_decision_actions_action"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("dashboard_decisions.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    payload_hash: Mapped[str] = mapped_column(String(64))


class NotificationOutbox(Base, TimestampMixin):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint("organization_id", "event_key", name="uq_notification_outbox_event"),
        Index("ix_notification_outbox_claim", "status", "next_attempt_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_chat_sessions_org_id"),
        CheckConstraint("surface IN ('agent', 'knowledge')", name="ck_chat_sessions_surface"),
        CheckConstraint(
            "knowledge_scope IN ('all_visible', 'selected', 'none')",
            name="ck_chat_sessions_knowledge_scope",
        ),
        CheckConstraint("memory_mode IN ('off', 'auto')", name="ck_chat_sessions_memory_mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    hermes_session_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    active_hermes_run_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )
    active_run_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    hermes_backend: Mapped[str] = mapped_column(String(20), default="knowledge")
    surface: Mapped[str] = mapped_column(String(20), default="knowledge", index=True)
    knowledge_scope: Mapped[str] = mapped_column(String(20), default="none")
    memory_mode: Mapped[str] = mapped_column(String(10), default="off")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    title: Mapped[str] = mapped_column(String(255), default="New conversation")


class ChatSessionKnowledgeSource(Base):
    __tablename__ = "chat_session_knowledge_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "chat_session_id"],
            ["chat_sessions.organization_id", "chat_sessions.id"],
            ondelete="CASCADE",
            name="fk_chat_sources_org_session",
        ),
        ForeignKeyConstraint(
            ["organization_id", "knowledge_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
            name="fk_chat_sources_org_entry",
        ),
    )

    chat_session_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_entry_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)


class ChatTurn(Base, TimestampMixin):
    __tablename__ = "chat_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "chat_session_id"],
            ["chat_sessions.organization_id", "chat_sessions.id"],
            ondelete="CASCADE",
            name="fk_chat_turns_org_session",
        ),
        UniqueConstraint("chat_session_id", "run_id", name="uq_chat_turns_session_run"),
        UniqueConstraint("organization_id", "id", name="uq_chat_turns_org_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    chat_session_id: Mapped[int] = mapped_column(Integer, index=True)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="retrieving", index=True)
    retrieval_mode: Mapped[str] = mapped_column(String(30), default="empty")
    assistant_message_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    question_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_hmac_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ChatTurnCitation(Base):
    __tablename__ = "chat_turn_citations"

    chat_turn_id: Mapped[int] = mapped_column(
        ForeignKey("chat_turns.id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    source_locator: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title_snapshot: Mapped[str] = mapped_column(String(255))


class ChatTurnWebSource(Base):
    """Platform-validated web evidence for one chat turn (Phase 1 A2).

    Rows only originate from provider/tool events parsed by
    ``app.services.web_evidence``; model text can never produce them.
    """

    __tablename__ = "chat_turn_web_sources"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_chat_turn_web_sources_org_id"),
        UniqueConstraint(
            "chat_turn_id", "ordinal", name="uq_chat_turn_web_sources_turn_ordinal"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    chat_turn_id: Mapped[int] = mapped_column(
        ForeignKey("chat_turns.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(512))
    published_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True))
    searched_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    query: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
