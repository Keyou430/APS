from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.pipeline_scheduler import validate_schedule_expression


TaskType = Literal["web_research", "general"]
TaskStatus = Literal["ready", "paused", "deleted"]
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
    created_at: datetime


class PipelineDecisionListResponse(BaseModel):
    items: list[PipelineDecisionResponse]


class RequestChangesRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4_000)


class RejectDecisionRequest(RequestChangesRequest):
    reason_type: Literal["no_need", "other", "regenerate"]
