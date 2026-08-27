from datetime import datetime

from pydantic import BaseModel


class KnowledgeOperationsOverview(BaseModel):
    entries: int
    chunks: int
    jobs_by_status: dict[str, int]
    retrievals_by_mode: dict[str, int]


class KnowledgeOperationJob(BaseModel):
    id: int
    entry_id: int
    status: str
    attempts: int
    error_code: str | None
    created_at: datetime


class KnowledgeOperationJobList(BaseModel):
    items: list[KnowledgeOperationJob]
