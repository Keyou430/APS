from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import MemoryCaptureSource, MemoryExtractionJob


MAX_CAPTURE_BYTES = 4096
_CREDENTIAL_PATTERN = re.compile(
    r"(?:password|passwd|api[_ -]?key|secret|token)\s*[:=]",
    re.IGNORECASE,
)
_PII_PATTERN = re.compile(
    r"(?:\bnational\s*id\b|身份证|诊断|\bdiagnosis\b|病历|\bsocial\s*security\b|"
    r"\bssn\b|\bsalary\b|薪酬|工资|\bdisciplinary\s+action\b|处分|"
    r"\bhealth\s+record\b|健康记录)",
    re.IGNORECASE,
)


class CapturePolicyDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


@dataclass(frozen=True)
class CaptureInput:
    organization_id: int
    user_id: int
    session_id: int
    turn_id: int
    text: str
    source_kind: str
    turn_status: str
    created_at: datetime


def should_capture_user_text(payload: CaptureInput) -> CapturePolicyDecision:
    if payload.source_kind != "user_text" or payload.turn_status != "completed":
        return CapturePolicyDecision.REJECT
    if not payload.text.strip() or len(payload.text.encode("utf-8")) > MAX_CAPTURE_BYTES:
        return CapturePolicyDecision.REJECT
    if _CREDENTIAL_PATTERN.search(payload.text) or _PII_PATTERN.search(payload.text):
        return CapturePolicyDecision.REJECT
    return CapturePolicyDecision.ACCEPT


def build_capture_snapshot(payload: CaptureInput) -> MemoryCaptureSource:
    if should_capture_user_text(payload) is not CapturePolicyDecision.ACCEPT:
        raise ValueError("capture input violates the bounded user-text policy (4096 UTF-8 bytes)")
    text = payload.text.strip()
    return MemoryCaptureSource(
        source_id=uuid4().hex,
        organization_id=payload.organization_id,
        user_id=payload.user_id,
        chat_session_id=payload.session_id,
        chat_turn_id=payload.turn_id,
        source_kind="user_text",
        raw_text=text,
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        status="queued",
        expires_at=payload.created_at + timedelta(hours=get_settings().memory_capture_ttl_hours),
        created_at=payload.created_at,
    )


async def enqueue_capture_source(
    db: AsyncSession,
    payload: CaptureInput,
) -> MemoryCaptureSource | None:
    settings = get_settings()
    if not settings.memory_extraction_enabled:
        return None
    if should_capture_user_text(payload) is not CapturePolicyDecision.ACCEPT:
        return None
    snapshot = build_capture_snapshot(payload)
    existing = await db.scalar(
        select(MemoryCaptureSource).where(
            MemoryCaptureSource.organization_id == snapshot.organization_id,
            MemoryCaptureSource.chat_turn_id == snapshot.chat_turn_id,
            MemoryCaptureSource.content_sha256 == snapshot.content_sha256,
        )
    )
    if existing is not None:
        return existing
    db.add(snapshot)
    await db.flush()
    db.add(
        MemoryExtractionJob(
            organization_id=snapshot.organization_id,
            user_id=snapshot.user_id,
            source_id=snapshot.id,
            provider=settings.memory_extraction_provider,
            provider_version=settings.memory_extraction_provider_version,
        )
    )
    return snapshot


async def purge_expired_sources(db: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    rows = list(
        (
            await db.scalars(
                select(MemoryCaptureSource).where(
                    MemoryCaptureSource.expires_at <= now,
                    MemoryCaptureSource.raw_text.is_not(None),
                    MemoryCaptureSource.status.in_(("completed", "failed", "cancelled")),
                )
            )
        ).all()
    )
    for source in rows:
        source.raw_text = None
        source.status = "purged"
        source.purged_at = now
    return len(rows)
