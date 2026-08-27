from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel


WorkItemStatus = Literal["pending", "in_progress", "completed", "cancelled"]
WorkItemPriority = Literal["low", "medium", "high"]
WorkItemOrigin = Literal["manual", "reminder", "chat", "agent"]
WorkItemScope = Literal["day", "week"]


class WorkItemSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class WorkItemCreate(WorkItemSchema):
    assignee_membership_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    priority: WorkItemPriority = "medium"
    due_at: datetime | None = None
    task_scope: WorkItemScope = "day"
    archive_timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    origin: WorkItemOrigin = "manual"
    source_ref: str | None = Field(
        default=None,
        max_length=500,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9:/_.#?-]{0,499}$",
    )

    @model_validator(mode="after")
    def require_opaque_runtime_reference(self) -> "WorkItemCreate":
        if self.origin in {"chat", "agent"} and self.source_ref is None:
            raise ValueError("chat and agent work items require an opaque source reference")
        return self

    @field_validator("archive_timezone")
    @classmethod
    def validate_archive_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("archiveTimezone must be a valid IANA timezone") from exc
        return value


class WorkItemStatusUpdate(WorkItemSchema):
    status: WorkItemStatus


class WorkItemUpdate(WorkItemSchema):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    priority: WorkItemPriority | None = None
    due_at: datetime | None = None
    archive_timezone: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("archive_timezone")
    @classmethod
    def validate_archive_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("archiveTimezone must be a valid IANA timezone") from exc
        return value


class WorkItemResponse(WorkItemSchema):
    id: int
    organization_id: int
    assignee_membership_id: int
    created_by_membership_id: int
    title: str
    description: str | None
    status: WorkItemStatus
    priority: WorkItemPriority
    due_at: datetime | None
    task_scope: WorkItemScope
    archive_timezone: str
    archive_after: datetime | None
    original_scope: WorkItemScope | None
    original_due_at: datetime | None
    archived_at: datetime | None
    archive_reason: Literal["overdue"] | None
    archive_batch_id: str | None
    week_key: str | None
    origin: WorkItemOrigin
    source_ref: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("archive_after", "archived_at")
    def serialize_archive_timestamp(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.isoformat().replace("+00:00", "Z")


class WorkItemListResponse(WorkItemSchema):
    items: list[WorkItemResponse]
    total: int = Field(ge=0)


class WorkItemEventResponse(WorkItemSchema):
    id: int
    work_item_id: int
    actor_membership_id: int
    from_status: WorkItemStatus | None
    to_status: WorkItemStatus
    occurred_at: datetime


class WorkItemEventListResponse(WorkItemSchema):
    items: list[WorkItemEventResponse]
