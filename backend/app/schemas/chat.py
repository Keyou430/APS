from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


ChatSurface = Literal["agent", "knowledge"]
KnowledgeScopeMode = Literal["all_visible", "selected", "none"]


class ChatSessionCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=255, examples=["Project planning"])
    surface: ChatSurface = "knowledge"


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255, examples=["Project planning"])

    @model_validator(mode="after")
    def validate_title(self) -> "ChatSessionUpdate":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title must not be blank")
        return self


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    hermes_session_id: str
    surface: ChatSurface
    knowledge_scope: KnowledgeScopeMode
    memory_mode: Literal["off", "auto"] = "off"
    revision: int = Field(gt=0)
    source_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionResponse]


class MessageCreate(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=20000,
        description="Only the new user message; history remains in Hermes",
        examples=["Tell me about Hermes Agent"],
    )
    source_ids: list[int] | None = Field(default=None, max_length=50)
    attachments: list["ChatAttachmentInput"] = Field(default_factory=list, max_length=5)
    links: list[str] = Field(default_factory=list, max_length=5)
    client_message_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=72,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
        description="Stable client message identifier used for idempotent platform actions",
    )


class ChatAttachmentInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=12_000)


class ChatAttachmentResponse(BaseModel):
    id: str
    title: str
    content: str
    size: int
    media_type: str


class LinkPreviewRequest(BaseModel):
    url: HttpUrl


class LinkPreviewResponse(BaseModel):
    url: HttpUrl
    title: str
    domain: str


class KnowledgeScopeUpdate(BaseModel):
    mode: KnowledgeScopeMode
    source_ids: list[int] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_selected_sources(self) -> "KnowledgeScopeUpdate":
        self.source_ids = list(dict.fromkeys(self.source_ids))
        if self.mode == "selected" and not self.source_ids:
            raise ValueError("selected scope requires source_ids")
        if self.mode != "selected" and self.source_ids:
            raise ValueError("source_ids are only valid for selected scope")
        return self


class KnowledgeScopeResponse(BaseModel):
    knowledge_scope: KnowledgeScopeMode
    source_ids: list[int]


class MemoryModeUpdate(BaseModel):
    memory_mode: Literal["off", "auto"]
    expected_revision: int = Field(gt=0)


class MemoryModeResponse(BaseModel):
    memory_mode: Literal["off", "auto"]
    revision: int = Field(gt=0)


class RunApprovalRequest(BaseModel):
    choice: Literal["once", "deny"]


class RunStopResponse(BaseModel):
    run_id: str
    status: str


class RunApprovalResponse(BaseModel):
    run_id: str
    choice: Literal["once", "deny"]
    resolved: int


class ChatCitation(BaseModel):
    ordinal: int
    entry_id: int | None
    title: str
    content_sha256: str
    source_locator: str | None = None


class ChatWebSource(BaseModel):
    ordinal: int
    provider: str
    url: str
    title: str
    published_at: datetime
    searched_at: datetime
    correlation_id: str
    retrieved_at: datetime | None = None
    source_id: str | None = None
    query: str | None = None
    content_sha256: str | None = None


class ChatMessage(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    turn_id: int | None = None
    citations: list[ChatCitation] = Field(default_factory=list)
    web_sources: list[ChatWebSource] = Field(default_factory=list)
    retrieval_mode: Literal["hybrid", "degraded_full_text", "empty"] | None = None
    turn_status: str | None = None
    rejected_source_count: int | None = Field(default=None, ge=0)


class ChatMessageListResponse(BaseModel):
    items: list[ChatMessage]
