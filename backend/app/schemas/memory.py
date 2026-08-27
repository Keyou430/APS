from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MemoryType = Literal["memory", "fact", "preference", "decision", "context"]
MemoryLayer = Literal["L1", "L2", "L3"]
MemoryStatus = Literal["candidate", "active", "superseded"]
MemoryOrigin = Literal["manual", "extracted", "imported"]


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    type: MemoryType = "memory"
    metadata: dict[str, str] = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    expected_revision: int = Field(gt=0)


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    memory_id: str
    content: str
    type: MemoryType
    metadata: dict[str, str]
    revision: int
    layer: MemoryLayer
    status: MemoryStatus
    origin: MemoryOrigin
    source_summary: str | None
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    provider: Literal["platform-postgres"] = "platform-postgres"
    next_cursor: str | None = None


class MemoryCandidateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["fact", "preference", "decision", "context"]
    layer: MemoryLayer
    content: str = Field(min_length=1, max_length=10000)
    confidence: float = Field(ge=0, le=1)
    source_ref: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)


class MemoryCandidateResponse(MemoryResponse):
    confidence: float
    provider: str
    provider_version: str
    source_ref: str


class MemoryCandidateListResponse(BaseModel):
    items: list[MemoryCandidateResponse]
    provider: Literal["platform-postgres"] = "platform-postgres"


class MemoryCandidateDecision(BaseModel):
    expected_revision: int = Field(gt=0)
    supersedes_memory_id: str | None = Field(default=None, min_length=1, max_length=32)
