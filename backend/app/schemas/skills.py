from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SkillCategory = Literal["general", "role-specific", "ai-generated"]
SkillStatus = Literal["draft", "reviewed", "published", "archived"]


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: SkillCategory = "general"
    content: str = Field(min_length=1, max_length=50_000, description="SKILL.md content")


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: SkillCategory | None = None
    content: str | None = Field(default=None, min_length=1, max_length=50_000)
    expected_revision: int = Field(gt=0)


class SkillGenerateRequest(BaseModel):
    description: str = Field(min_length=5, max_length=2000)


class SkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    content: str
    is_ai_generated: bool
    status: str
    revision: int
    current_version: str
    is_promoted: bool
    created_at: datetime


class SkillVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: str
    revision: int
    name: str
    category: str
    content: str
    content_hash: str | None
    is_ai_generated: bool
    created_at: datetime


class SkillVersionListResponse(BaseModel):
    items: list[SkillVersionResponse]


class SkillListResponse(BaseModel):
    items: list[SkillResponse]


class SkillGrantCreate(BaseModel):
    grantee_user_id: int = Field(gt=0)
    expires_at: datetime | None = None


class SkillGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    skill_id: int
    grantor_user_id: int
    grantee_user_id: int
    capability: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class SkillGrantListResponse(BaseModel):
    items: list[SkillGrantResponse]


class GeneratedSkillResponse(BaseModel):
    generated_skill: str
    name: str
    category: str = "ai-generated"


class HubSkill(BaseModel):
    slug: str
    name: str
    description: str
    category: str


class HubSkillListResponse(BaseModel):
    items: list[HubSkill]
    provider: str = "mock-hermes-hub"
