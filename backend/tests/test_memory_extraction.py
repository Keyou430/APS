from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.database import SessionLocal
from app.models import MemoryCaptureSource, MemoryRecord
from app.schemas.memory import MemoryCandidateDTO
from app.services.memory_extraction import (
    ExtractionProvider,
    persist_candidates,
    validate_provider_candidate,
)


def test_provider_candidate_is_scope_neutral_and_validated() -> None:
    candidate = validate_provider_candidate(
        {
            "type": "preference",
            "layer": "L2",
            "content": "Prefer concise status updates.",
            "confidence": 0.91,
            "source_ref": "source-abc",
            "provider": "fake-extractor",
            "version": "v1",
        }
    )
    assert isinstance(candidate, MemoryCandidateDTO)
    assert not hasattr(candidate, "organization_id")
    assert not hasattr(candidate, "user_id")
    assert not hasattr(candidate, "status")


def test_provider_candidate_rejects_provider_owned_scope_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        validate_provider_candidate(
            {
                "type": "fact",
                "layer": "L1",
                "content": "A fact",
                "confidence": 0.8,
                "source_ref": "source-abc",
                "provider": "fake-extractor",
                "version": "v1",
                "organization_id": 999,
                "status": "active",
            }
        )


@pytest.mark.asyncio
async def test_disabled_provider_does_not_fabricate_candidates() -> None:
    provider = ExtractionProvider(enabled=False)
    assert await provider.extract("source text", scope_ref="opaque-scope") == []


@pytest.mark.asyncio
async def test_one_source_can_persist_multiple_candidates_idempotently() -> None:
    async with SessionLocal() as db:
        source = MemoryCaptureSource(
            source_id="multi-candidate-source",
            organization_id=1,
            user_id=1,
            source_kind="user_text",
            content_sha256="a" * 64,
            status="queued",
        )
        db.add(source)
        await db.flush()
        candidates = [
            MemoryCandidateDTO(
                type="fact",
                layer="L1",
                content="The deadline is Friday.",
                confidence=0.9,
                source_ref="turn-1",
                provider="fake-extractor",
                version="v1",
            ),
            MemoryCandidateDTO(
                type="preference",
                layer="L2",
                content="Use concise reports.",
                confidence=0.8,
                source_ref="turn-1",
                provider="fake-extractor",
                version="v1",
            ),
        ]
        first = await persist_candidates(db, source, candidates)
        retried = [
            candidates[0].model_copy(
                update={
                    "confidence": 0.85,
                }
            ),
            candidates[1],
        ]
        second = await persist_candidates(db, source, retried)
        await db.flush()
        persisted = list(
            (
                await db.scalars(
                    select(MemoryRecord).where(MemoryRecord.status == "candidate")
                )
            ).all()
        )
        await db.rollback()

    assert len(first) == 2
    assert [item.memory_id for item in second] == [item.memory_id for item in first]
    assert len(persisted) == 2


@pytest.mark.asyncio
async def test_candidate_key_distinguishes_same_ref_candidates_by_content() -> None:
    async with SessionLocal() as db:
        source = MemoryCaptureSource(
            source_id="same-ref-source",
            organization_id=1,
            user_id=1,
            source_kind="user_text",
            content_sha256="b" * 64,
            status="queued",
        )
        db.add(source)
        await db.flush()
        candidates = [
            MemoryCandidateDTO(
                type="fact",
                layer="L1",
                content="The launch date is Friday.",
                confidence=0.9,
                source_ref="turn-1",
                provider="fake-extractor",
                version="v1",
            ),
            MemoryCandidateDTO(
                type="fact",
                layer="L1",
                content="The launch owner is Mei.",
                confidence=0.88,
                source_ref="turn-1",
                provider="fake-extractor",
                version="v1",
            ),
        ]

        first = await persist_candidates(db, source, candidates)
        second = await persist_candidates(db, source, candidates)
        await db.flush()
        persisted = list(
            (
                await db.scalars(
                    select(MemoryRecord).where(
                        MemoryRecord.status == "candidate",
                        MemoryRecord.source_summary == "turn-1",
                    )
                )
            ).all()
        )
        await db.rollback()

    assert len(first) == 2
    assert [item.memory_id for item in second] == [item.memory_id for item in first]
    assert {item.content for item in persisted} == {
        "The launch date is Friday.",
        "The launch owner is Mei.",
    }
