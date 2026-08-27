from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ReminderType = Literal["one-time", "recurring"]
Recurrence = Literal["daily", "weekly", "monthly"]
Channel = Literal["in-app", "feishu", "dingtalk"]


class ReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    due_date: datetime
    type: ReminderType = "one-time"
    recurrence: Recurrence | None = None
    notification_channel: Channel = "in-app"

    @model_validator(mode="after")
    def validate_recurrence(self) -> "ReminderCreate":
        if self.type == "recurring" and self.recurrence is None:
            raise ValueError("recurrence is required for recurring reminders")
        return self


class ReminderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_date: datetime | None = None
    type: ReminderType | None = None
    recurrence: Recurrence | None = None
    notification_channel: Channel | None = None


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    due_date: datetime
    type: str
    recurrence: str | None
    status: str
    notification_channel: str
    created_at: datetime


class ReminderListResponse(BaseModel):
    items: list[ReminderResponse]
