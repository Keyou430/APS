from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import (
    KnowledgeAccessGrant,
    KnowledgeChunk,
    KnowledgeEntry,
    KnowledgeIngestionJob,
    OrganizationMembership,
    Role,
    User,
)
from app.services.knowledge_authorization import (
    AuthorizedKnowledgeEntryRepository,
    KnowledgeAuthorizationScope,
)


async def create_member(
    *,
    username: str,
    organization_id: int,
    member_type: str = "internal",
) -> tuple[User, OrganizationMembership]:
    async with SessionLocal() as db:
        role_name = "guest" if member_type == "guest" else "user"
        role = await db.scalar(select(Role).where(Role.name == role_name))
        assert role is not None
        user = User(
            username=username,
            password_hash=hash_password("authorization-password"),
            email=f"{username}@example.com",
            role_id=role.id,
            default_organization_id=organization_id,
        )
        db.add(user)
        await db.flush()
        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=user.id,
            role_id=role.id,
            member_type=member_type,
        )
        db.add(membership)
        await db.commit()
        return user, membership


async def create_entry(
    *,
    organization_id: int,
    owner_id: int,
    title: str,
    visibility: str = "private",
    archived_at: datetime | None = None,
) -> KnowledgeEntry:
    async with SessionLocal() as db:
        entry = KnowledgeEntry(
            organization_id=organization_id,
            user_id=owner_id,
            type="workflow_result",
            title=title,
            content=title,
            visibility=visibility,
            archived_at=archived_at,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry


@pytest.mark.asyncio
async def test_visible_resource_matrix_distinguishes_internal_and_guest_members() -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        organization_id = admin.default_organization_id
        owner_id = admin.id
    internal_user, internal_membership = await create_member(
        username="authorization-internal",
        organization_id=organization_id,
    )
    guest_user, guest_membership = await create_member(
        username="authorization-guest",
        organization_id=organization_id,
        member_type="guest",
    )
    private = await create_entry(
        organization_id=organization_id,
        owner_id=owner_id,
        title="Private",
    )
    organization = await create_entry(
        organization_id=organization_id,
        owner_id=owner_id,
        title="Organization",
        visibility="organization_members",
    )
    granted = await create_entry(
        organization_id=organization_id,
        owner_id=owner_id,
        title="Granted",
    )
    expired = await create_entry(
        organization_id=organization_id,
        owner_id=owner_id,
        title="Expired",
    )
    revoked = await create_entry(
        organization_id=organization_id,
        owner_id=owner_id,
        title="Revoked",
    )
    archived = await create_entry(
        organization_id=organization_id,
        owner_id=owner_id,
        title="Archived",
        visibility="organization_members",
        archived_at=datetime.now(UTC),
    )
    async with SessionLocal() as db:
        db.add_all(
            [
                KnowledgeAccessGrant(
                    organization_id=organization_id,
                    knowledge_entry_id=granted.id,
                    grantee_membership_id=internal_membership.id,
                    capability="read",
                    granted_by_user_id=owner_id,
                ),
                KnowledgeAccessGrant(
                    organization_id=organization_id,
                    knowledge_entry_id=granted.id,
                    grantee_membership_id=guest_membership.id,
                    capability="read",
                    granted_by_user_id=owner_id,
                ),
                KnowledgeAccessGrant(
                    organization_id=organization_id,
                    knowledge_entry_id=expired.id,
                    grantee_membership_id=internal_membership.id,
                    capability="read",
                    expires_at=datetime.now(UTC) - timedelta(minutes=1),
                    granted_by_user_id=owner_id,
                ),
                KnowledgeAccessGrant(
                    organization_id=organization_id,
                    knowledge_entry_id=revoked.id,
                    grantee_membership_id=internal_membership.id,
                    capability="read",
                    revoked_at=datetime.now(UTC),
                    granted_by_user_id=owner_id,
                ),
            ]
        )
        await db.commit()

    async with SessionLocal() as db:
        internal_repository = AuthorizedKnowledgeEntryRepository(
            db,
            KnowledgeAuthorizationScope(
                organization_id=organization_id,
                user_id=internal_user.id,
                membership_id=internal_membership.id,
                member_type="internal",
            ),
        )
        guest_repository = AuthorizedKnowledgeEntryRepository(
            db,
            KnowledgeAuthorizationScope(
                organization_id=organization_id,
                user_id=guest_user.id,
                membership_id=guest_membership.id,
                member_type="guest",
            ),
        )
        internal_ids = {entry.id for entry in await internal_repository.list_visible()}
        guest_ids = {entry.id for entry in await guest_repository.list_visible()}

    assert organization.id in internal_ids
    assert granted.id in internal_ids
    assert private.id not in internal_ids
    assert expired.id not in internal_ids
    assert revoked.id not in internal_ids
    assert archived.id not in internal_ids
    assert guest_ids == {granted.id}

    async with SessionLocal() as db:
        restored = await db.get(KnowledgeEntry, archived.id)
        assert restored is not None
        restored.archived_at = None
        await db.commit()
        repository = AuthorizedKnowledgeEntryRepository(
            db,
            KnowledgeAuthorizationScope(
                organization_id=organization_id,
                user_id=internal_user.id,
                membership_id=internal_membership.id,
                member_type="internal",
            ),
        )
        assert await repository.get_visible(archived.id) is not None
        await db.delete(restored)
        await db.commit()
        assert await repository.get_visible(archived.id) is None

        cross_organization_repository = AuthorizedKnowledgeEntryRepository(
            db,
            KnowledgeAuthorizationScope(
                organization_id=organization_id + 10_000,
                user_id=internal_user.id,
                membership_id=internal_membership.id,
                member_type="internal",
            ),
        )
        assert await cross_organization_repository.get_visible(organization.id) is None


@pytest.mark.asyncio
async def test_authorized_ready_sources_preserve_owner_revision_tuple() -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        organization_id = admin.default_organization_id
        owner_id = admin.id
    reader, membership = await create_member(
        username="authorization-reader",
        organization_id=organization_id,
    )
    entry = await create_entry(
        organization_id=organization_id,
        owner_id=owner_id,
        title="Shared indexed source",
    )
    revision = "d" * 64
    async with SessionLocal() as db:
        db.add(
            KnowledgeAccessGrant(
                organization_id=organization_id,
                knowledge_entry_id=entry.id,
                grantee_membership_id=membership.id,
                capability="read",
                granted_by_user_id=owner_id,
            )
        )
        db.add(
            KnowledgeIngestionJob(
                organization_id=organization_id,
                user_id=owner_id,
                knowledge_entry_id=entry.id,
                content_sha256=revision,
                status="ready",
                attempts=1,
                parser_version="test-v1",
                embedding_model="text-embedding-v4",
                embedding_dimension=1024,
            )
        )
        db.add(
            KnowledgeChunk(
                organization_id=organization_id,
                user_id=owner_id,
                knowledge_entry_id=entry.id,
                content_sha256=revision,
                ordinal=0,
                text="shared owner chunk",
                text_sha256="e" * 64,
                source_locator="chunk:0",
                embedding=[0.1] * 1024,
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        repository = AuthorizedKnowledgeEntryRepository(
            db,
            KnowledgeAuthorizationScope(
                organization_id=organization_id,
                user_id=reader.id,
                membership_id=membership.id,
                member_type="internal",
            ),
        )
        sources = await repository.authorized_sources([entry.id])

    assert len(sources) == 1
    assert sources[0].organization_id == organization_id
    assert sources[0].user_id == owner_id
    assert sources[0].entry_id == entry.id
    assert sources[0].content_sha256 == revision
