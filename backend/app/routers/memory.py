from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, require_permission
from app.database import get_db
from app.schemas.memory import (
    MemoryCreate,
    MemoryCandidateDecision,
    MemoryCandidateListResponse,
    MemoryCandidateResponse,
    MemoryListResponse,
    MemoryResponse,
    MemoryType,
    MemoryUpdate,
)
from app.services.audit import record_audit
from app.services.memory_repository import (
    InvalidMemoryCursorError,
    MemoryNotFoundError,
    MemoryRevisionConflictError,
    create_manual_memory,
    confirm_candidate,
    delete_active_memory,
    get_active_memory,
    list_active_memories,
    list_candidate_memories,
    memory_response_data,
    update_active_memory,
    reject_candidate,
)


router = APIRouter(prefix="/api/memory", tags=["Memory"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
MemoryReadContext = Annotated[
    OrganizationContext, Depends(require_permission("memory:read"))
]
MemoryWriteContext = Annotated[
    OrganizationContext, Depends(require_permission("memory:write"))
]


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Memory not found")


def revision_conflict() -> HTTPException:
    return HTTPException(status_code=409, detail="Memory revision conflict")


@router.get(
    "/candidates",
    response_model=MemoryCandidateListResponse,
    summary="List current user's pending memory candidates",
)
async def list_candidates(
    db: DbSession,
    context: MemoryReadContext,
) -> MemoryCandidateListResponse:
    items = await list_candidate_memories(
        db,
        organization_id=context.organization_id,
        user_id=context.user_id,
    )
    return MemoryCandidateListResponse(
        items=[
            MemoryCandidateResponse.model_validate(
                {
                    **memory_response_data(item.record),
                    "confidence": item.record.confidence or 0.0,
                    "provider": item.record.provider or "unknown",
                    "provider_version": item.record.provider_version or "unknown",
                    "source_ref": item.source_ref,
                }
            )
            for item in items
        ]
    )


@router.get(
    "",
    response_model=MemoryListResponse,
    summary="List or search current user's active memories",
    description="Reads the platform-owned PostgreSQL memory ledger using owner-scoped queries.",
)
async def list_memory(
    db: DbSession,
    context: MemoryReadContext,
    query: Annotated[str, Query(max_length=10000)] = "",
    type: Annotated[MemoryType | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MemoryListResponse:
    try:
        page = await list_active_memories(
            db,
            organization_id=context.organization_id,
            user_id=context.user_id,
            query=query,
            memory_type=type,
            cursor=cursor,
            limit=limit,
        )
    except InvalidMemoryCursorError:
        raise HTTPException(status_code=422, detail="Invalid memory cursor") from None
    return MemoryListResponse(
        items=[MemoryResponse.model_validate(memory_response_data(item)) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", response_model=MemoryResponse, status_code=201, summary="Create a manual memory")
async def add_memory(
    payload: MemoryCreate,
    db: DbSession,
    context: MemoryWriteContext,
) -> MemoryResponse:
    record = await create_manual_memory(
        db,
        organization_id=context.organization_id,
        user_id=context.user_id,
        content=payload.content,
        memory_type=payload.type,
        metadata=payload.metadata,
    )
    await record_audit(
        db,
        context.membership,
        action="memory.create",
        resource_type="memory",
        resource_id=record.memory_id,
        details={
            "revision": record.revision,
            "layer": record.layer,
            "origin": record.origin,
            "status": record.status,
        },
    )
    await db.commit()
    return MemoryResponse.model_validate(memory_response_data(record))


@router.get("/{memory_id}", response_model=MemoryResponse, summary="Get an active memory")
async def get_memory(
    memory_id: str,
    db: DbSession,
    context: MemoryReadContext,
) -> MemoryResponse:
    try:
        record = await get_active_memory(
            db,
            memory_id,
            organization_id=context.organization_id,
            user_id=context.user_id,
        )
    except MemoryNotFoundError:
        raise not_found() from None
    return MemoryResponse.model_validate(memory_response_data(record))


@router.post(
    "/{memory_id}/confirm",
    response_model=MemoryResponse,
    summary="Confirm a pending memory candidate",
)
async def confirm_memory_candidate(
    payload: MemoryCandidateDecision,
    memory_id: str,
    db: DbSession,
    context: MemoryWriteContext,
) -> MemoryResponse:
    try:
        record = await confirm_candidate(
            db,
            memory_id,
            organization_id=context.organization_id,
            user_id=context.user_id,
            expected_revision=payload.expected_revision,
            supersedes_memory_id=payload.supersedes_memory_id,
        )
    except MemoryNotFoundError:
        raise not_found() from None
    except MemoryRevisionConflictError:
        raise revision_conflict() from None
    await record_audit(
        db,
        context.membership,
        action="memory.confirm",
        resource_type="memory",
        resource_id=memory_id,
        details={"revision": record.revision, "status": record.status},
    )
    await db.commit()
    return MemoryResponse.model_validate(memory_response_data(record))


@router.post("/{memory_id}/reject", status_code=204, summary="Reject a pending memory candidate")
async def reject_memory_candidate(
    payload: MemoryCandidateDecision,
    memory_id: str,
    db: DbSession,
    context: MemoryWriteContext,
) -> Response:
    try:
        await reject_candidate(
            db,
            memory_id,
            organization_id=context.organization_id,
            user_id=context.user_id,
            expected_revision=payload.expected_revision,
        )
    except MemoryNotFoundError:
        raise not_found() from None
    except MemoryRevisionConflictError:
        raise revision_conflict() from None
    await record_audit(
        db,
        context.membership,
        action="memory.reject",
        resource_type="memory",
        resource_id=memory_id,
        details={"status": "rejected"},
    )
    await db.commit()
    return Response(status_code=204)


@router.put("/{memory_id}", response_model=MemoryResponse, summary="Update an active memory")
async def update_memory(
    payload: MemoryUpdate,
    memory_id: str,
    db: DbSession,
    context: MemoryWriteContext,
) -> MemoryResponse:
    try:
        record = await update_active_memory(
            db,
            memory_id,
            organization_id=context.organization_id,
            user_id=context.user_id,
            content=payload.content,
            expected_revision=payload.expected_revision,
        )
    except MemoryNotFoundError:
        raise not_found() from None
    except MemoryRevisionConflictError:
        raise revision_conflict() from None
    await record_audit(
        db,
        context.membership,
        action="memory.update",
        resource_type="memory",
        resource_id=record.memory_id,
        details={
            "revision": record.revision,
            "layer": record.layer,
            "origin": record.origin,
            "status": record.status,
        },
    )
    await db.commit()
    return MemoryResponse.model_validate(memory_response_data(record))


@router.delete("/{memory_id}", status_code=204, summary="Delete an active memory")
async def delete_memory(
    memory_id: str,
    db: DbSession,
    context: MemoryWriteContext,
    expected_revision: Annotated[int, Query(gt=0)],
) -> Response:
    try:
        details = await delete_active_memory(
            db,
            memory_id,
            organization_id=context.organization_id,
            user_id=context.user_id,
            expected_revision=expected_revision,
        )
    except MemoryNotFoundError:
        raise not_found() from None
    except MemoryRevisionConflictError:
        raise revision_conflict() from None
    await record_audit(
        db,
        context.membership,
        action="memory.delete",
        resource_type="memory",
        resource_id=memory_id,
        details=details,
    )
    await db.commit()
    return Response(status_code=204)
