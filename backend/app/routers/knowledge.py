from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, OrganizationContext, has_permission, require_permission
from app.config import get_settings
from app.database import get_db
from app.models import (
    ChatSession,
    ChatTurn,
    ChatTurnCitation,
    KnowledgeAccessGrant,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeEntry,
    KnowledgeIngestionJob,
    OrganizationMembership,
    User,
)
from app.schemas.knowledge import (
    FixedKnowledgeContextListResponse,
    FixedKnowledgeContextResponse,
    KnowledgeCreate,
    KnowledgeCollectionAssignment,
    KnowledgeCollectionCreate,
    KnowledgeCollectionListResponse,
    KnowledgeCollectionResponse,
    KnowledgeCollectionUpdate,
    KnowledgeCitationResolveResponse,
    KnowledgeAccessUpdate,
    KnowledgeContentPreview,
    KnowledgeGrantCreate,
    KnowledgeGrantListResponse,
    KnowledgeGrantResponse,
    KnowledgeMemberListResponse,
    KnowledgeMemberSummary,
    KnowledgeIngestionResponse,
    KnowledgeListResponse,
    KnowledgeRetrieveRequest,
    KnowledgeRetrieveResponse,
    KnowledgeResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeType,
    KnowledgeUpdate,
)
from app.services.knowledge_ingestion import cancel_active_ingestions, enqueue_ingestion
from app.services.audit import record_audit
from app.services.knowledge_authorization import (
    AuthorizedKnowledgeEntryRepository,
    KnowledgeAuthorizationScope,
)
from app.services.knowledge_retrieval import (
    RetrievalScope,
    build_platform_knowledge_retriever,
    record_retrieval_event,
)
from app.services.object_storage import LocalPrivateObjectStorage
from app.services.fixed_knowledge import fixed_context_by_id, fixed_contexts_for_username
from app.services.public_link_fetcher import (
    PublicLinkFetchError,
    fetch_public_collaboration_link,
    is_collaboration_link,
)


_MAX_KNOWLEDGE_UPLOAD_BYTES = 50 * 1024 * 1024
_ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".html", ".csv"}
_TEXT_UPLOAD_EXTENSIONS = {".txt", ".md", ".html", ".csv"}


async def _read_knowledge_upload(file: UploadFile) -> bytes:
    filename = file.filename or ""
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.casefold()
    if (
        not filename
        or safe_name != filename
        or "/" in filename
        or "\\" in filename
        or suffix not in _ALLOWED_UPLOAD_EXTENSIONS
    ):
        raise HTTPException(status_code=422, detail="content_type_not_allowed")

    content_type = (file.content_type or "").split(";", 1)[0].strip().casefold()
    expected_types = {
        ".pdf": {"application/pdf"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
        ".txt": {"text/plain"},
        ".md": {"text/markdown", "text/plain"},
        ".html": {"text/html"},
        ".csv": {"text/csv", "text/plain"},
    }
    if content_type and content_type not in expected_types[suffix] and content_type != "application/octet-stream":
        raise HTTPException(status_code=422, detail="content_type_not_allowed")

    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > _MAX_KNOWLEDGE_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="payload_too_large")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=422, detail="content_type_not_allowed")

    if suffix == ".pdf" and not data.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="content_type_not_allowed")
    if suffix in {".docx", ".xlsx", ".pptx"} and not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=422, detail="content_type_not_allowed")
    if suffix in _TEXT_UPLOAD_EXTENSIONS and b"\x00" in data:
        raise HTTPException(status_code=422, detail="content_type_not_allowed")
    return data

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
KnowledgeReadContext = Annotated[
    OrganizationContext, Depends(require_permission("knowledge:read"))
]
KnowledgeWriteContext = Annotated[
    OrganizationContext, Depends(require_permission("knowledge:write"))
]


async def delete_stored_file(file_reference: str) -> None:
    settings = get_settings()
    normalized = file_reference.replace("\\", "/")
    if normalized.startswith("private/"):
        await LocalPrivateObjectStorage(settings.upload_dir).delete(normalized)
        return

    upload_root = settings.upload_dir.resolve()
    legacy_path = Path(file_reference).resolve()
    if not legacy_path.is_relative_to(upload_root):
        raise RuntimeError("Legacy knowledge file is outside the upload root")
    legacy_path.unlink(missing_ok=True)


async def owned_entry(
    db: AsyncSession, entry_id: int, user_id: int, organization_id: int
) -> KnowledgeEntry:
    entry = await db.scalar(
        select(KnowledgeEntry).where(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.user_id == user_id,
            KnowledgeEntry.organization_id == organization_id,
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return entry


def authorized_repository(
    db: AsyncSession,
    user_id: int,
    context: OrganizationContext,
) -> AuthorizedKnowledgeEntryRepository:
    return AuthorizedKnowledgeEntryRepository(
        db,
        KnowledgeAuthorizationScope(
            organization_id=context.organization_id,
            user_id=user_id,
            membership_id=context.membership.id,
            member_type=context.member_type,
        ),
    )


async def knowledge_response(
    db: AsyncSession, entry: KnowledgeEntry, user_id: int
) -> dict[str, object]:
    is_owner = entry.user_id == user_id
    if is_owner:
        access_source = "owner"
    elif entry.visibility == "organization_members":
        access_source = "organization"
    else:
        access_source = "grant"
    owner_user = await db.get(User, entry.user_id)
    latest_job = await db.scalar(
        select(KnowledgeIngestionJob)
        .where(KnowledgeIngestionJob.knowledge_entry_id == entry.id)
        .order_by(KnowledgeIngestionJob.created_at.desc(), KnowledgeIngestionJob.id.desc())
    )
    return {
        "id": entry.id,
        "type": entry.type,
        "title": entry.title,
        "url": entry.url,
        "content": entry.content if is_owner else None,
        "file_path": None,
        "collection_id": entry.collection_id,
        "owner_id": entry.user_id,
        "owner": (
            {"id": owner_user.id, "username": owner_user.username}
            if owner_user is not None
            else None
        ),
        "visibility": entry.visibility,
        "enabled": entry.enabled,
        "access_source": access_source,
        "ingestion_status": latest_job.status if latest_job is not None else None,
        "updated_at": entry.updated_at,
        "archived_at": entry.archived_at,
        "created_at": entry.created_at,
    }


async def shareable_entry(
    db: AsyncSession,
    entry_id: int,
    user_id: int,
    context: OrganizationContext,
) -> KnowledgeEntry:
    entry = await db.scalar(
        select(KnowledgeEntry).where(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.organization_id == context.organization_id,
            KnowledgeEntry.archived_at.is_(None),
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    owner_can_share = entry.user_id == user_id and has_permission(
        context.membership, "knowledge:share"
    )
    if not owner_can_share and not has_permission(context.membership, "knowledge:govern"):
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return entry


async def scoped_collection(
    db: AsyncSession,
    collection_id: int,
    organization_id: int,
) -> KnowledgeCollection:
    collection = await db.scalar(
        select(KnowledgeCollection).where(
            KnowledgeCollection.id == collection_id,
            KnowledgeCollection.organization_id == organization_id,
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Knowledge collection not found")
    return collection


async def validate_collection_parent(
    db: AsyncSession,
    organization_id: int,
    parent_id: int | None,
    *,
    collection_id: int | None = None,
) -> None:
    if parent_id is None:
        return
    if collection_id is not None and parent_id == collection_id:
        raise HTTPException(status_code=409, detail="Knowledge collection cycle detected")
    parent = await scoped_collection(db, parent_id, organization_id)
    visited = {collection_id} if collection_id is not None else set()
    while True:
        if parent.id in visited:
            raise HTTPException(status_code=409, detail="Knowledge collection cycle detected")
        visited.add(parent.id)
        if parent.parent_id is None:
            return
        parent = await scoped_collection(db, parent.parent_id, organization_id)


@router.post("", response_model=KnowledgeResponse, status_code=201, summary="Create an entry")
async def create_entry(
    payload: KnowledgeCreate,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> KnowledgeEntry:
    content = payload.content
    url = str(payload.url) if payload.url else None
    if payload.type == "link" and url:
        existing = await db.scalar(
            select(KnowledgeEntry)
            .where(
                KnowledgeEntry.organization_id == context.organization_id,
                KnowledgeEntry.user_id == user.id,
                KnowledgeEntry.type == "link",
                KnowledgeEntry.url == url,
                KnowledgeEntry.archived_at.is_(None),
            )
            .order_by(KnowledgeEntry.id.desc())
        )
        if existing is not None:
            return await knowledge_response(db, existing, user.id)
    if payload.type == "link" and url and not content and is_collaboration_link(url):
        try:
            content = await fetch_public_collaboration_link(url)
        except PublicLinkFetchError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    entry = KnowledgeEntry(
        organization_id=context.organization_id,
        user_id=user.id,
        type=payload.type,
        title=payload.title,
        url=url,
        content=content,
    )
    db.add(entry)
    await db.flush()
    await record_audit(
        db,
        context.membership,
        action="knowledge.create",
        resource_type="knowledge_entry",
        resource_id=str(entry.id),
    )
    await db.commit()
    await db.refresh(entry)
    return await knowledge_response(db, entry, user.id)


@router.post(
    "/upload", response_model=KnowledgeResponse, status_code=201, summary="Upload a file entry"
)
async def upload_entry(
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
    title: Annotated[str, Form(min_length=1, max_length=255)],
    collection_id: Annotated[int, Form(ge=1)],
    file: Annotated[UploadFile, File(description="Stored as-is; no parsing or OCR in MVP")],
) -> KnowledgeEntry:
    settings = get_settings()
    await scoped_collection(db, collection_id, context.organization_id)
    safe_name = Path(file.filename or "upload.bin").name
    object_key = f"private/{uuid4().hex}-{safe_name}"
    storage = LocalPrivateObjectStorage(settings.upload_dir)
    await storage.put_bytes(object_key, await _read_knowledge_upload(file))
    entry = KnowledgeEntry(
        organization_id=context.organization_id,
        user_id=user.id,
        type="file",
        title=title,
        collection_id=collection_id,
        file_path=object_key,
    )
    db.add(entry)
    await db.flush()
    await record_audit(
        db,
        context.membership,
        action="knowledge.upload",
        resource_type="knowledge_entry",
        resource_id=str(entry.id),
    )
    await db.commit()
    await db.refresh(entry)
    await enqueue_ingestion(db, entry, storage)
    return await knowledge_response(db, entry, user.id)


@router.get("", response_model=KnowledgeListResponse, summary="List knowledge entries")
async def list_entries(
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
    type: Annotated[KnowledgeType | None, Query()] = None,
    collection_id: Annotated[int | None, Query(ge=1)] = None,
    view: Annotated[Literal["mine", "shared", "organization"] | None, Query()] = None,
    archived: Annotated[bool, Query()] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> KnowledgeListResponse:
    if collection_id is not None:
        await scoped_collection(db, collection_id, context.organization_id)
    if archived:
        entries = list(
            (
                await db.scalars(
                    select(KnowledgeEntry)
                    .where(
                        KnowledgeEntry.organization_id == context.organization_id,
                        KnowledgeEntry.user_id == user.id,
                        KnowledgeEntry.archived_at.is_not(None),
                    )
                    .order_by(KnowledgeEntry.archived_at.desc(), KnowledgeEntry.id.desc())
                )
            ).all()
        )
    else:
        entries = await authorized_repository(db, user.id, context).list_visible()
    if collection_id is not None:
        entries = [entry for entry in entries if entry.collection_id == collection_id]
    if view == "mine":
        entries = [entry for entry in entries if entry.user_id == user.id]
    elif view == "organization":
        entries = [
            entry
            for entry in entries
            if entry.user_id != user.id and entry.visibility == "organization_members"
        ]
    elif view == "shared":
        granted_ids = set(
            (
                await db.scalars(
                    select(KnowledgeAccessGrant.knowledge_entry_id).where(
                        KnowledgeAccessGrant.organization_id == context.organization_id,
                        KnowledgeAccessGrant.grantee_membership_id == context.membership.id,
                        KnowledgeAccessGrant.revoked_at.is_(None),
                        or_(
                            KnowledgeAccessGrant.expires_at.is_(None),
                            KnowledgeAccessGrant.expires_at > datetime.now(UTC),
                        ),
                    )
                )
            ).all()
        )
        entries = [entry for entry in entries if entry.id in granted_ids]
    if type:
        entries = [entry for entry in entries if entry.type == type]
    total = len(entries)
    start = (page - 1) * page_size
    items = [
        await knowledge_response(db, entry, user.id)
        for entry in entries[start : start + page_size]
    ]
    return KnowledgeListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/retrieve",
    response_model=KnowledgeRetrieveResponse,
    summary="Retrieve authorized knowledge citations",
)
async def retrieve_knowledge(
    payload: KnowledgeRetrieveRequest,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeRetrieveResponse:
    retrieval_scope = RetrievalScope(
        organization_id=context.organization_id,
        user_id=user.id,
        membership_id=context.membership.id,
        member_type=context.member_type,
    )
    started = perf_counter()
    try:
        result = await build_platform_knowledge_retriever(db).retrieve(
            scope=retrieval_scope,
            query=payload.query,
            source_ids=payload.source_ids,
            limit=payload.limit,
        )
    except Exception:
        await record_retrieval_event(
            db,
            scope=retrieval_scope,
            query=payload.query,
            request_kind="rest",
            retrieval_mode="empty",
            result_count=0,
            latency_ms=int((perf_counter() - started) * 1000),
            outcome="failed",
        )
        await db.commit()
        raise
    await record_retrieval_event(
        db,
        scope=retrieval_scope,
        query=payload.query,
        request_kind="rest",
        retrieval_mode=result.mode,
        result_count=len(result.citations),
        latency_ms=int((perf_counter() - started) * 1000),
        outcome="success",
    )
    await db.commit()
    return result


@router.get(
    "/collections",
    response_model=KnowledgeCollectionListResponse,
    summary="List current organization knowledge collections",
)
async def list_collections(
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeCollectionListResponse:
    collections = list(
        (
            await db.scalars(
                select(KnowledgeCollection)
                .where(KnowledgeCollection.organization_id == context.organization_id)
                .order_by(
                    KnowledgeCollection.sort_order,
                    KnowledgeCollection.name,
                    KnowledgeCollection.id,
                )
            )
        ).all()
    )
    visible_entries = await authorized_repository(db, user.id, context).list_visible()
    visible_counts: dict[int, int] = {}
    for entry in visible_entries:
        if entry.collection_id is not None:
            visible_counts[entry.collection_id] = visible_counts.get(entry.collection_id, 0) + 1
    return KnowledgeCollectionListResponse(
        items=[
            KnowledgeCollectionResponse.model_validate(
                {**collection.__dict__, "source_count": visible_counts.get(collection.id, 0)}
            )
            for collection in collections
        ]
    )


@router.post(
    "/collections",
    response_model=KnowledgeCollectionResponse,
    status_code=201,
    summary="Create a knowledge collection",
)
async def create_collection(
    payload: KnowledgeCollectionCreate,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> KnowledgeCollectionResponse:
    await validate_collection_parent(db, context.organization_id, payload.parent_id)
    collection = KnowledgeCollection(
        organization_id=context.organization_id,
        parent_id=payload.parent_id,
        name=payload.name,
        description=payload.description,
        sort_order=payload.sort_order,
    )
    db.add(collection)
    await db.flush()
    await record_audit(
        db,
        context.membership,
        action="knowledge.collection.create",
        resource_type="knowledge_collection",
        resource_id=str(collection.id),
    )
    await db.commit()
    await db.refresh(collection)
    return KnowledgeCollectionResponse.model_validate(
        {**collection.__dict__, "source_count": 0}
    )


@router.patch(
    "/collections/{collection_id}",
    response_model=KnowledgeCollectionResponse,
    summary="Update a knowledge collection",
)
async def update_collection(
    collection_id: int,
    payload: KnowledgeCollectionUpdate,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> KnowledgeCollectionResponse:
    collection = await scoped_collection(db, collection_id, context.organization_id)
    if "parent_id" in payload.model_fields_set:
        await validate_collection_parent(
            db,
            context.organization_id,
            payload.parent_id,
            collection_id=collection.id,
        )
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(collection, name, value)
    await record_audit(
        db,
        context.membership,
        action="knowledge.collection.update",
        resource_type="knowledge_collection",
        resource_id=str(collection.id),
    )
    await db.commit()
    await db.refresh(collection)
    visible_entries = await authorized_repository(db, user.id, context).list_visible()
    source_count = sum(entry.collection_id == collection.id for entry in visible_entries)
    return KnowledgeCollectionResponse.model_validate(
        {**collection.__dict__, "source_count": source_count}
    )


@router.delete(
    "/collections/{collection_id}",
    status_code=204,
    summary="Delete an empty knowledge collection",
)
async def delete_collection(
    collection_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> None:
    collection = await scoped_collection(db, collection_id, context.organization_id)
    child = await db.scalar(
        select(KnowledgeCollection.id).where(
            KnowledgeCollection.organization_id == context.organization_id,
            KnowledgeCollection.parent_id == collection.id,
        )
    )
    entry = await db.scalar(
        select(KnowledgeEntry.id).where(
            KnowledgeEntry.organization_id == context.organization_id,
            KnowledgeEntry.collection_id == collection.id,
        )
    )
    if child is not None or entry is not None:
        raise HTTPException(status_code=409, detail="Knowledge collection is not empty")
    await record_audit(
        db,
        context.membership,
        action="knowledge.collection.delete",
        resource_type="knowledge_collection",
        resource_id=str(collection.id),
    )
    await db.delete(collection)
    await db.commit()


@router.put(
    "/{entry_id}/collection",
    response_model=KnowledgeResponse,
    summary="Move a knowledge entry to a collection",
)
async def move_entry_to_collection(
    entry_id: int,
    payload: KnowledgeCollectionAssignment,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> dict[str, object]:
    entry = await db.scalar(
        select(KnowledgeEntry).where(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.organization_id == context.organization_id,
            KnowledgeEntry.archived_at.is_(None),
        )
    )
    if entry is None or (
        entry.user_id != user.id
        and not has_permission(context.membership, "knowledge:govern")
    ):
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    if payload.collection_id is not None:
        await scoped_collection(db, payload.collection_id, context.organization_id)
    entry.collection_id = payload.collection_id
    await record_audit(
        db,
        context.membership,
        action="knowledge.collection.move",
        resource_type="knowledge_entry",
        resource_id=str(entry.id),
        details={"collection_id": payload.collection_id},
    )
    await db.commit()
    await db.refresh(entry)
    return await knowledge_response(db, entry, user.id)


@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
    summary="Search entries through the platform RAG boundary",
)
async def search_entries(
    payload: KnowledgeSearchRequest,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeSearchResponse:
    result = await build_platform_knowledge_retriever(db).retrieve(
        scope=RetrievalScope(
            organization_id=context.organization_id,
            user_id=user.id,
            membership_id=context.membership.id,
            member_type=context.member_type,
        ),
        query=payload.query,
        source_ids=[],
        limit=min(payload.limit, 8),
    )
    entry_ids = list(dict.fromkeys(citation.entry_id for citation in result.citations))
    if not entry_ids:
        return KnowledgeSearchResponse(items=[], provider="platform-pgvector")
    visible_entries = await authorized_repository(db, user.id, context).list_visible()
    entries = [entry for entry in visible_entries if entry.id in entry_ids]
    by_id = {entry.id: entry for entry in entries}
    items = [
        await knowledge_response(db, by_id[entry_id], user.id)
        for entry_id in entry_ids
        if entry_id in by_id
    ]
    return KnowledgeSearchResponse(
        items=items,
        provider="platform-pgvector",
    )


@router.get("/members", response_model=KnowledgeMemberListResponse)
async def list_knowledge_members(
    db: DbSession,
    context: KnowledgeReadContext,
) -> KnowledgeMemberListResponse:
    can_select_members = (
        context.membership.member_type == "internal"
        and (
            has_permission(context.membership, "knowledge:share")
            or has_permission(context.membership, "knowledge:govern")
        )
    )
    if not can_select_members:
        raise HTTPException(status_code=403, detail="Insufficient permission")
    rows = (
        await db.execute(
            select(OrganizationMembership, User)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(
                OrganizationMembership.organization_id == context.organization_id,
                OrganizationMembership.is_active.is_(True),
                or_(
                    OrganizationMembership.expires_at.is_(None),
                    OrganizationMembership.expires_at > datetime.now(UTC),
                ),
            )
            .order_by(User.username, OrganizationMembership.id)
        )
    ).all()
    return KnowledgeMemberListResponse(
        items=[
            KnowledgeMemberSummary(
                membership_id=membership.id,
                user_id=user.id,
                username=user.username,
                member_type=membership.member_type,
            )
            for membership, user in rows
        ]
    )


@router.get("/fixed-contexts", response_model=FixedKnowledgeContextListResponse)
async def list_fixed_contexts(
    context: KnowledgeReadContext,
) -> FixedKnowledgeContextListResponse:
    return FixedKnowledgeContextListResponse(
        items=[
            FixedKnowledgeContextResponse(**item.__dict__)
            for item in fixed_contexts_for_username(context.user.username)
        ]
    )


@router.get("/fixed-contexts/{context_id}", response_model=FixedKnowledgeContextResponse)
async def get_fixed_context(
    context_id: str,
    context: KnowledgeReadContext,
) -> FixedKnowledgeContextResponse:
    item = fixed_context_by_id(context.user.username, context_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Fixed knowledge context not found")
    return FixedKnowledgeContextResponse(**item.__dict__)


@router.get("/{entry_id}", response_model=KnowledgeResponse, summary="Get entry detail")
async def get_entry(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeEntry:
    entry = await authorized_repository(db, user.id, context).get_visible(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return await knowledge_response(db, entry, user.id)


@router.post(
    "/{entry_id}/ingest",
    response_model=KnowledgeIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue knowledge ingestion",
)
async def ingest_entry(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> KnowledgeIngestionResponse:
    entry = await owned_entry(db, entry_id, user.id, context.organization_id)
    storage = LocalPrivateObjectStorage(get_settings().upload_dir)
    await record_audit(
        db,
        context.membership,
        action="knowledge.ingest",
        resource_type="knowledge_entry",
        resource_id=str(entry.id),
    )
    job = await enqueue_ingestion(db, entry, storage)
    return KnowledgeIngestionResponse.model_validate(
        {
            "id": job.id,
            "status": job.status,
            "attempts": job.attempts,
            "embedding_model": job.embedding_model,
            "embedding_dimension": job.embedding_dimension,
            "error_code": job.last_error_code,
            "created_at": job.created_at,
        }
    )


@router.get("/{entry_id}/content", response_model=KnowledgeContentPreview)
async def preview_content(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeContentPreview:
    entry = await authorized_repository(db, user.id, context).get_visible(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    content = entry.content
    if content is None:
        chunk_texts = list(
            (
                await db.scalars(
                    select(KnowledgeChunk.text)
                    .where(
                        KnowledgeChunk.knowledge_entry_id == entry.id,
                        KnowledgeChunk.organization_id == context.organization_id,
                    )
                    .order_by(KnowledgeChunk.ordinal)
                )
            ).all()
        )
        content = "\n\n".join(chunk_texts) if chunk_texts else None
    return KnowledgeContentPreview(
        entry_id=entry.id,
        title=entry.title,
        content=content[:12_000] if content is not None else None,
    )


@router.get("/{entry_id}/download")
async def download_entry(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> Response:
    entry = await authorized_repository(db, user.id, context).get_visible(entry_id)
    if entry is None or not entry.file_path:
        raise HTTPException(status_code=404, detail="Knowledge file not found")
    content = await LocalPrivateObjectStorage(get_settings().upload_dir).open_read(entry.file_path)
    filename = Path(entry.title).name.replace('"', "").replace("\r", "").replace("\n", "")
    await record_audit(
        db,
        context.membership,
        action="knowledge.download",
        resource_type="knowledge_entry",
        resource_id=str(entry.id),
    )
    await db.commit()
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename or "download"}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/{entry_id}/ingestion",
    response_model=KnowledgeIngestionResponse,
    summary="Get latest knowledge ingestion status",
)
async def get_ingestion_status(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeIngestionResponse:
    entry = await owned_entry(db, entry_id, user.id, context.organization_id)
    job = await db.scalar(
        select(KnowledgeIngestionJob)
        .where(KnowledgeIngestionJob.knowledge_entry_id == entry.id)
        .order_by(KnowledgeIngestionJob.created_at.desc(), KnowledgeIngestionJob.id.desc())
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Knowledge ingestion job not found")
    return KnowledgeIngestionResponse.model_validate(
        {
            "id": job.id,
            "status": job.status,
            "attempts": job.attempts,
            "embedding_model": job.embedding_model,
            "embedding_dimension": job.embedding_dimension,
            "error_code": job.last_error_code,
            "created_at": job.created_at,
        }
    )


@router.put("/{entry_id}", response_model=KnowledgeResponse, summary="Update an entry")
async def update_entry(
    payload: KnowledgeUpdate,
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> KnowledgeEntry:
    entry = await owned_entry(db, entry_id, user.id, context.organization_id)
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, name, str(value) if name == "url" and value is not None else value)
    await record_audit(
        db,
        context.membership,
        action="knowledge.update",
        resource_type="knowledge_entry",
        resource_id=str(entry.id),
    )
    await db.commit()
    await db.refresh(entry)
    return await knowledge_response(db, entry, user.id)


@router.put("/{entry_id}/access", response_model=KnowledgeResponse)
async def update_access(
    payload: KnowledgeAccessUpdate,
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> dict[str, object]:
    entry = await shareable_entry(db, entry_id, user.id, context)
    entry.visibility = payload.visibility
    await record_audit(
        db,
        context.membership,
        action="knowledge.access.update",
        resource_type="knowledge_entry",
        resource_id=str(entry.id),
        details={"visibility": payload.visibility},
    )
    await db.commit()
    await db.refresh(entry)
    return await knowledge_response(db, entry, user.id)


@router.get("/{entry_id}/grants", response_model=KnowledgeGrantListResponse)
async def list_grants(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeGrantListResponse:
    entry = await shareable_entry(db, entry_id, user.id, context)
    grants = list(
        (
            await db.scalars(
                select(KnowledgeAccessGrant)
                .where(KnowledgeAccessGrant.knowledge_entry_id == entry.id)
                .order_by(KnowledgeAccessGrant.created_at.desc())
            )
        ).all()
    )
    memberships = {
        membership.id: membership
        for membership in (
            await db.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.id.in_(
                        [grant.grantee_membership_id for grant in grants]
                    )
                )
            )
        ).all()
    }
    users = {
        member.user_id: await db.get(User, member.user_id)
        for member in memberships.values()
    }
    now = datetime.now(UTC)
    return KnowledgeGrantListResponse(
        items=[
            KnowledgeGrantResponse(
                id=grant.id,
                membership_id=grant.grantee_membership_id,
                user_id=memberships[grant.grantee_membership_id].user_id,
                username=users[memberships[grant.grantee_membership_id].user_id].username,
                member_type=memberships[grant.grantee_membership_id].member_type,
                status=(
                    "revoked"
                    if grant.revoked_at is not None
                    else "expired"
                    if grant.expires_at is not None and grant.expires_at <= now
                    else "active"
                ),
                expires_at=grant.expires_at,
                revoked_at=grant.revoked_at,
            )
            for grant in grants
        ]
    )


@router.post(
    "/{entry_id}/grants",
    response_model=KnowledgeGrantResponse,
    status_code=201,
)
async def create_grant(
    payload: KnowledgeGrantCreate,
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeGrantResponse:
    entry = await shareable_entry(db, entry_id, user.id, context)
    membership = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.id == payload.membership_id,
            OrganizationMembership.organization_id == context.organization_id,
            OrganizationMembership.is_active.is_(True),
            or_(
                OrganizationMembership.expires_at.is_(None),
                OrganizationMembership.expires_at > datetime.now(UTC),
            ),
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")
    active = await db.scalar(
        select(KnowledgeAccessGrant)
        .where(
            KnowledgeAccessGrant.knowledge_entry_id == entry.id,
            KnowledgeAccessGrant.grantee_membership_id == membership.id,
            KnowledgeAccessGrant.revoked_at.is_(None),
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    if active is not None and active.expires_at is not None and active.expires_at <= now:
        active.revoked_at = now
        active = None
    if active is not None:
        raise HTTPException(status_code=409, detail="Active knowledge grant already exists")
    grant = KnowledgeAccessGrant(
        organization_id=context.organization_id,
        knowledge_entry_id=entry.id,
        grantee_membership_id=membership.id,
        capability="read",
        expires_at=payload.expires_at,
        granted_by_user_id=user.id,
    )
    db.add(grant)
    await db.flush()
    await record_audit(
        db,
        context.membership,
        action="knowledge.grant.create",
        resource_type="knowledge_grant",
        resource_id=str(grant.id),
        details={"entry_id": entry.id, "membership_id": membership.id},
    )
    await db.commit()
    grantee = await db.get(User, membership.user_id)
    assert grantee is not None
    return KnowledgeGrantResponse(
        id=grant.id,
        membership_id=membership.id,
        user_id=membership.user_id,
        username=grantee.username,
        member_type=membership.member_type,
        status="active",
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
    )


@router.delete("/{entry_id}/grants/{grant_id}", status_code=204)
async def revoke_grant(
    entry_id: int,
    grant_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> None:
    entry = await shareable_entry(db, entry_id, user.id, context)
    grant = await db.scalar(
        select(KnowledgeAccessGrant).where(
            KnowledgeAccessGrant.id == grant_id,
            KnowledgeAccessGrant.knowledge_entry_id == entry.id,
            KnowledgeAccessGrant.organization_id == context.organization_id,
            KnowledgeAccessGrant.revoked_at.is_(None),
        )
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Knowledge grant not found")
    grant.revoked_at = datetime.now(UTC)
    await record_audit(
        db,
        context.membership,
        action="knowledge.grant.revoke",
        resource_type="knowledge_grant",
        resource_id=str(grant.id),
        details={"entry_id": entry.id},
    )
    await db.commit()


@router.delete("/{entry_id}", status_code=204, summary="Delete an entry")
async def delete_entry(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> None:
    entry = await owned_entry(db, entry_id, user.id, context.organization_id)
    await cancel_active_ingestions(db, entry.id)
    entry.archived_at = datetime.now(UTC)
    await record_audit(
        db,
        context.membership,
        action="knowledge.archive",
        resource_type="knowledge_entry",
        resource_id=str(entry.id),
    )
    await db.commit()


@router.post("/{entry_id}/restore", response_model=KnowledgeResponse)
async def restore_entry(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> dict[str, object]:
    entry = await db.scalar(
        select(KnowledgeEntry).where(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.user_id == user.id,
            KnowledgeEntry.organization_id == context.organization_id,
            KnowledgeEntry.archived_at.is_not(None),
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Archived knowledge entry not found")
    entry.archived_at = None
    await record_audit(
        db, context.membership, action="knowledge.restore", resource_type="knowledge_entry", resource_id=str(entry.id)
    )
    await db.commit()
    await db.refresh(entry)
    return await knowledge_response(db, entry, user.id)


@router.delete("/{entry_id}/purge", status_code=204)
async def purge_entry(
    entry_id: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeWriteContext,
) -> None:
    entry = await db.scalar(
        select(KnowledgeEntry).where(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.user_id == user.id,
            KnowledgeEntry.organization_id == context.organization_id,
            KnowledgeEntry.archived_at.is_not(None),
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Archived knowledge entry not found")
    if entry.file_path:
        await delete_stored_file(entry.file_path)
    await record_audit(
        db, context.membership, action="knowledge.purge", resource_type="knowledge_entry", resource_id=str(entry.id)
    )
    await db.delete(entry)
    await db.commit()


@router.get(
    "/citations/{turn_id}/{ordinal}",
    response_model=KnowledgeCitationResolveResponse,
    summary="Resolve a historical citation with current authorization",
)
async def resolve_citation(
    turn_id: int,
    ordinal: int,
    db: DbSession,
    user: CurrentUser,
    context: KnowledgeReadContext,
) -> KnowledgeCitationResolveResponse:
    row = (
        await db.execute(
            select(ChatTurnCitation, ChatTurn)
            .join(ChatTurn, ChatTurn.id == ChatTurnCitation.chat_turn_id)
            .join(ChatSession, ChatSession.id == ChatTurn.chat_session_id)
            .where(
                ChatTurnCitation.chat_turn_id == turn_id,
                ChatTurnCitation.ordinal == ordinal,
                ChatTurn.organization_id == context.organization_id,
                ChatTurn.user_id == user.id,
                ChatSession.user_id == user.id,
                ChatSession.organization_id == context.organization_id,
                ChatSession.surface == "knowledge",
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Citation not found")
    citation, _turn = row
    if citation.knowledge_entry_id is None:
        raise HTTPException(status_code=404, detail="Citation not found")
    entry = await authorized_repository(db, user.id, context).get_visible(
        citation.knowledge_entry_id
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Citation not found")
    return KnowledgeCitationResolveResponse(
        turn_id=turn_id,
        ordinal=ordinal,
        entry_id=entry.id,
        title=citation.title_snapshot,
        content_sha256=citation.content_sha256,
        source_locator=citation.source_locator,
    )
