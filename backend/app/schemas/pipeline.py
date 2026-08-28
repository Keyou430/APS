from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.pipeline_scheduler import validate_schedule_expression


TaskType = Literal["web_research", "general"]
TaskStatus = Literal["ready", "paused", "deleted"]
ApprovalAssigneeType = Literal["creator", "member", "role"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled", "missed"]
DecisionStatus = Literal[
    "pending", "approved", "rejected", "changes_requested", "regenerating", "superseded"
]


def validate_cron(value: str | None) -> str | None:
    if value is None:
        return value
    parts = value.split()
    if len(parts) != 5:
        raise ValueError("schedule must be a five-field cron expression")
    return validate_schedule_expression(value)


class PipelineDraftRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=20_000)


class PipelineDraftResponse(BaseModel):
    title: str
    prompt: str
    task_type: TaskType
    schedule: str | None = None
    timezone: str
    input_sources: list[str]
    output_format: Literal["markdown"]
    approval_required: bool = True
    approval_assignee_type: ApprovalAssigneeType = "creator"
    approval_assignee_id: int | None = None
    approval_role_name: str | None = Field(default=None, max_length=50)
    approval_reminder_after_minutes: int | None = Field(default=1440, ge=1, le=10080)
    approval_escalation_after_minutes: int | None = Field(default=2880, ge=1, le=20160)
    approval_escalation_role_name: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_approval_policy(self) -> "PipelineDraftResponse":
        if not self.approval_required:
            self.approval_assignee_type = "creator"
            self.approval_assignee_id = None
            self.approval_role_name = None
            return self
        if self.approval_assignee_type == "creator":
            self.approval_assignee_id = None
            self.approval_role_name = None
        elif self.approval_assignee_type == "member":
            if self.approval_assignee_id is None:
                raise ValueError("approval_assignee_id is required for member approval")
            self.approval_role_name = None
        elif self.approval_assignee_type == "role":
            if not self.approval_role_name:
                raise ValueError("approval_role_name is required for role approval")
            self.approval_assignee_id = None
        if (
            self.approval_reminder_after_minutes is not None
            and self.approval_escalation_after_minutes is not None
            and self.approval_escalation_after_minutes <= self.approval_reminder_after_minutes
        ):
            raise ValueError("approval_escalation_after_minutes must be after reminder")
        return self


class PipelineTaskCreate(PipelineDraftResponse):
    confirmed: Literal[True]

    _valid_cron = field_validator("schedule")(validate_cron)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be an IANA timezone") from exc
        if value != "Asia/Shanghai":
            raise ValueError("single-user scheduled tasks must use Asia/Shanghai")
        return value


class PipelineTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None = None
    prompt: str
    task_type: TaskType
    schedule: str | None
    timezone: str
    input_sources: list[str]
    output_format: Literal["markdown"]
    status: TaskStatus
    revision: int
    output_id: int | None = None
    next_run_at: datetime | None
    hermes_cron_job_id: str | None = None
    approval_required: bool
    approval_assignee_type: ApprovalAssigneeType
    approval_assignee_id: int | None
    approval_role_name: str | None
    approval_reminder_after_minutes: int | None
    approval_escalation_after_minutes: int | None
    approval_escalation_role_name: str | None
    created_at: datetime
    updated_at: datetime


class PipelineTaskListResponse(BaseModel):
    items: list[PipelineTaskResponse]
    next_cursor: int | None = None


class PipelineRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    trigger_kind: Literal["scheduled", "manual"]
    status: RunStatus
    output_id: int | None = None
    attempt: int
    error_code: str | None
    scheduled_for: datetime | None
    created_at: datetime
    completed_at: datetime | None


class PipelineOutputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    run_id: int
    version: int
    title: str
    markdown: str
    sources: list[dict]
    created_at: datetime


class PipelineDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    run_id: int
    output_id: int
    regeneration_run_id: int | None
    status: DecisionStatus
    revision: int
    title: str
    summary: str
    change_request: str | None
    approver_user_id: int | None
    approval_comment: str | None
    rejection_reason: str | None
    reason_type: str | None
    decided_at: datetime | None
    reminder_sent_at: datetime | None
    escalation_sent_at: datetime | None
    created_at: datetime


class PipelineDecisionListResponse(BaseModel):
    items: list[PipelineDecisionResponse]


class RequestChangesRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def normalize_reason(self) -> "RequestChangesRequest":
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("reason is required")
        return self


class RejectDecisionRequest(RequestChangesRequest):
    reason_type: Literal["no_need", "other", "regenerate"]


class ApproveDecisionRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def normalize_comment(self) -> "ApproveDecisionRequest":
        if self.comment is not None:
            self.comment = self.comment.strip() or None
        return self
