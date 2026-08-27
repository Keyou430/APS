from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


KnowledgeType = Literal["link", "file", "workflow_result"]


class KnowledgeOwnerSummary(BaseModel):
    id: int
    username: str


class KnowledgeCreate(BaseModel):
    type: KnowledgeType
    title: str = Field(min_length=1, max_length=255)
    url: HttpUrl | None = None
    content: str | None = Field(default=None, max_length=200_000)

    @model_validator(mode="after")
    def validate_link(self) -> "KnowledgeCreate":
        if self.type == "link" and self.url is None:
            raise ValueError("url is required for link entries")
        return self


class KnowledgeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    url: HttpUrl | None = None
    content: str | None = Field(default=None, max_length=200_000)
    enabled: bool | None = None


class KnowledgeCollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    parent_id: int | None = None
    sort_order: int = 0


class KnowledgeCollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    parent_id: int | None = None
    sort_order: int | None = None


class KnowledgeCollectionAssignment(BaseModel):
    collection_id: int | None


class KnowledgeCollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    name: str
    description: str
    sort_order: int
    source_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeCollectionListResponse(BaseModel):
    items: list[KnowledgeCollectionResponse]


class KnowledgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    url: str | None
    content: str | None
    file_path: str | None
    collection_id: int | None = None
    owner_id: int | None = None
    owner: KnowledgeOwnerSummary | None = None
    visibility: Literal["private", "organization_members"] = "private"
    enabled: bool = True
    access_source: Literal["owner", "organization", "grant"] = "owner"
    ingestion_status: (
        Literal["queued", "processing", "cancel_requested", "ready", "failed", "cancelled"] | None
    ) = None
    updated_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime

    @field_validator("file_path", mode="before")
    @classmethod
    def redact_private_storage_location(cls, _value: object) -> None:
        return None


class KnowledgeIngestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: Literal["queued", "processing", "cancel_requested", "ready", "failed", "cancelled"]
    attempts: int
    embedding_model: str
    embedding_dimension: int
    error_code: str | None = None
    created_at: datetime

    @field_validator("error_code", mode="before")
    @classmethod
    def expose_stable_error_code(cls, value: object) -> object:
        return value


class KnowledgeListResponse(BaseModel):
    items: list[KnowledgeResponse]
    total: int
    page: int
    page_size: int


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=50)


class KnowledgeSearchResponse(BaseModel):
    items: list[KnowledgeResponse]
    provider: str = "platform-pgvector"


class KnowledgeRetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    source_ids: list[int] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=8, ge=1, le=8)


class KnowledgeCitation(BaseModel):
    entry_id: int
    title: str
    content_sha256: str
    source_locator: str | None = None
    text: str
    score: float


class KnowledgeCitationResolveResponse(BaseModel):
    turn_id: int
    ordinal: int
    entry_id: int
    title: str
    content_sha256: str
    source_locator: str | None = None


class KnowledgeAccessUpdate(BaseModel):
    visibility: Literal["private", "organization_members"]


class KnowledgeGrantCreate(BaseModel):
    membership_id: int
    expires_at: datetime | None = None


class KnowledgeGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    membership_id: int
    user_id: int
    username: str
    member_type: Literal["internal", "guest"]
    status: Literal["active", "expired", "revoked"]
    capability: Literal["read"] = "read"
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class KnowledgeGrantListResponse(BaseModel):
    items: list[KnowledgeGrantResponse]


class KnowledgeMemberSummary(BaseModel):
    membership_id: int
    user_id: int
    username: str
    member_type: Literal["internal", "guest"]


class KnowledgeMemberListResponse(BaseModel):
    items: list[KnowledgeMemberSummary]


class KnowledgeContentPreview(BaseModel):
    entry_id: int
    title: str
    content: str | None


class FixedKnowledgeContextResponse(BaseModel):
    id: str
    kind: Literal["enterprise", "role"]
    title: str
    summary: str
    content: str
    source_name: str
    source_sha256: str | None = None
    immutable: Literal[True] = True


class FixedKnowledgeContextListResponse(BaseModel):
    items: list[FixedKnowledgeContextResponse]


class KnowledgeRetrieveResponse(BaseModel):
    citations: list[KnowledgeCitation]
    mode: Literal["hybrid", "degraded_full_text", "empty"]
