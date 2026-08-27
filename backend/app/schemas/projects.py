"""Project scope DTOs（D7）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProjectVisibility = Literal["public", "private"]
ProjectResourceType = Literal["knowledge", "memory", "skill", "work_item"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    visibility: ProjectVisibility = "private"


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    visibility: ProjectVisibility | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    visibility: str
    owner_user_id: int
    roster_revision: int
    created_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]


class RosterUpdate(BaseModel):
    expected_revision: int = Field(gt=0)
    add: list[int] = Field(default_factory=list)
    remove: list[int] = Field(default_factory=list)


class RosterResponse(BaseModel):
    roster_revision: int
    member_ids: list[int]


class ResourceLinkCreate(BaseModel):
    resource_type: ProjectResourceType
    ref_id: str = Field(min_length=1, max_length=64)
    ord: int = Field(default=0, ge=0)


class ResourceLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_type: str
    ref_id: str
    ord: int


class ResourceLinkListResponse(BaseModel):
    items: list[ResourceLinkResponse]
