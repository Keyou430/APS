from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MemoryCaptureSource, MemoryRecord, MemorySourceLink, MemoryVersion
from app.schemas.memory import MemoryCandidateDTO


def validate_provider_candidate(payload: Mapping[str, object]) -> MemoryCandidateDTO:
    return MemoryCandidateDTO.model_validate(dict(payload))


class CandidateProvider(Protocol):
    async def extract(self, source_text: str, *, scope_ref: str) -> list[MemoryCandidateDTO]: ...


class ExtractionProvider:
    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    async def extract(self, source_text: str, *, scope_ref: str) -> list[MemoryCandidateDTO]:
        if not self.enabled:
            return []
        raise RuntimeError("No external memory extraction provider is configured")


async def persist_candidates(
    db: AsyncSession,
    source: MemoryCaptureSource,
    candidates: list[MemoryCandidateDTO],
) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    for candidate in candidates:
        candidate_key = hashlib.sha256(
            "\x1f".join(
                (
                    str(source.id),
                    candidate.provider,
                    candidate.version,
                    candidate.type,
                    candidate.layer,
                    candidate.source_ref,
                    hashlib.sha256(candidate.content.encode("utf-8")).hexdigest(),
                )
            ).encode("utf-8")
        ).hexdigest()
        existing = await db.scalar(
            select(MemoryRecord).where(
                MemoryRecord.organization_id == source.organization_id,
                MemoryRecord.user_id == source.user_id,
                MemoryRecord.candidate_key == candidate_key,
            )
        )
        if existing is not None:
            records.append(existing)
            continue
        now = datetime.now(UTC)
        record = MemoryRecord(
            memory_id=uuid4().hex,
            organization_id=source.organization_id,
            user_id=source.user_id,
            content=candidate.content,
            type=candidate.type,
            layer=candidate.layer,
            status="candidate",
            origin="extracted",
            revision=1,
            metadata_={},
            source_summary=candidate.source_ref,
            confidence=candidate.confidence,
            provider=candidate.provider,
            provider_version=candidate.version,
            candidate_key=candidate_key,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        await db.flush()
        db.add(
            MemorySourceLink(
                organization_id=source.organization_id,
                user_id=source.user_id,
                memory_id=record.memory_id,
                source_id=source.id,
                source_label=candidate.source_ref,
            )
        )
        db.add(
            MemoryVersion(
                organization_id=source.organization_id,
                user_id=source.user_id,
                memory_id=record.memory_id,
                revision=1,
                content=record.content,
                type=record.type,
                layer=record.layer,
                status=record.status,
                origin=record.origin,
                metadata_={},
                source_summary=record.source_summary,
                confidence=record.confidence,
                provider=record.provider,
                provider_version=record.provider_version,
            )
        )
        records.append(record)
    source.status = "completed"
    await db.flush()
    return records
