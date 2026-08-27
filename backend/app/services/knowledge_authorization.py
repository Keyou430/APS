from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeAccessGrant, KnowledgeEntry, KnowledgeIngestionJob


@dataclass(frozen=True)
class KnowledgeAuthorizationScope:
    organization_id: int
    user_id: int
    membership_id: int
    member_type: str


@dataclass(frozen=True)
class AuthorizedKnowledgeSource:
    entry_id: int
    title: str
    content_sha256: str
    source_locator: str | None = None
    organization_id: int | None = None
    user_id: int | None = None


class AuthorizedKnowledgeEntryRepository:
    def __init__(
        self,
        db: AsyncSession,
        scope: KnowledgeAuthorizationScope,
    ) -> None:
        self._db = db
        self.scope = scope

    def visible_predicate(self):
        now = datetime.now(UTC)
        active_grant = exists(
            select(KnowledgeAccessGrant.id).where(
                KnowledgeAccessGrant.organization_id == self.scope.organization_id,
                KnowledgeAccessGrant.knowledge_entry_id == KnowledgeEntry.id,
                KnowledgeAccessGrant.grantee_membership_id == self.scope.membership_id,
                KnowledgeAccessGrant.capability == "read",
                KnowledgeAccessGrant.revoked_at.is_(None),
                or_(
                    KnowledgeAccessGrant.expires_at.is_(None),
                    KnowledgeAccessGrant.expires_at > now,
                ),
            )
        )
        return (
            KnowledgeEntry.organization_id == self.scope.organization_id,
            KnowledgeEntry.archived_at.is_(None),
            or_(
                KnowledgeEntry.user_id == self.scope.user_id,
                (
                    (KnowledgeEntry.visibility == "organization_members")
                    & (self.scope.member_type == "internal")
                ),
                active_grant,
            ),
        )

    async def list_visible(self) -> list[KnowledgeEntry]:
        rows = await self._db.scalars(
            select(KnowledgeEntry)
            .where(*self.visible_predicate())
            .order_by(KnowledgeEntry.updated_at.desc(), KnowledgeEntry.id.desc())
        )
        return list(rows.all())

    async def get_visible(self, entry_id: int) -> KnowledgeEntry | None:
        return await self._db.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.id == entry_id,
                *self.visible_predicate(),
            )
        )

    async def authorized_sources(
        self,
        source_ids: list[int],
    ) -> list[AuthorizedKnowledgeSource]:
        statement = (
            select(KnowledgeEntry, KnowledgeIngestionJob)
            .join(
                KnowledgeIngestionJob,
                KnowledgeIngestionJob.knowledge_entry_id == KnowledgeEntry.id,
            )
            .where(
                *self.visible_predicate(),
                KnowledgeEntry.enabled.is_(True),
                KnowledgeIngestionJob.organization_id == self.scope.organization_id,
                KnowledgeIngestionJob.status == "ready",
            )
            .order_by(
                KnowledgeEntry.id,
                KnowledgeIngestionJob.created_at.desc(),
                KnowledgeIngestionJob.id.desc(),
            )
        )
        if source_ids:
            statement = statement.where(KnowledgeEntry.id.in_(source_ids))
        rows = (await self._db.execute(statement)).all()
        sources: list[AuthorizedKnowledgeSource] = []
        seen_entry_ids: set[int] = set()
        for entry, job in rows:
            if entry.id in seen_entry_ids:
                continue
            seen_entry_ids.add(entry.id)
            sources.append(
                AuthorizedKnowledgeSource(
                    entry_id=entry.id,
                    title=entry.title,
                    content_sha256=job.content_sha256,
                    organization_id=entry.organization_id,
                    user_id=entry.user_id,
                )
            )
        return sources
