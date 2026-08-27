from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ExperienceSourceType = Literal["human", "ai_summary"]


class ExperienceDomainCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)


class ExperienceDomainUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class ExperienceMethodCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=200_000)
    source_type: ExperienceSourceType = "human"
    source_reference: str | None = Field(default=None, max_length=500)


class ExperienceMethodUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)
    source_type: ExperienceSourceType | None = None
    source_reference: str | None = Field(default=None, max_length=500)


class ExperienceMethodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain_id: int
    title: str
    content: str
    source_type: ExperienceSourceType
    source_reference: str | None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime


class ExperienceMethodListResponse(BaseModel):
    items: list[ExperienceMethodResponse]


class ExperienceDomainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    method_count: int = 0
    created_at: datetime
    updated_at: datetime


class ExperienceDomainListResponse(BaseModel):
    items: list[ExperienceDomainResponse]
