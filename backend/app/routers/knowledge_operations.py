from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, require_permission
from app.database import get_db
from app.models import KnowledgeChunk, KnowledgeEntry, KnowledgeIngestionJob, KnowledgeRetrievalEvent
from app.schemas.knowledge_operations import (
    KnowledgeOperationJob,
    KnowledgeOperationJobList,
    KnowledgeOperationsOverview,
)
from app.services.audit import record_audit


router = APIRouter(prefix="/api/knowledge/operations", tags=["Knowledge Operations"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
OpsContext = Annotated[OrganizationContext, Depends(require_permission("knowledge:ops"))]
GovernContext = Annotated[
    OrganizationContext, Depends(require_permission("knowledge:govern"))
]


@router.get("/overview", response_model=KnowledgeOperationsOverview)
async def overview(db: DbSession, context: OpsContext) -> KnowledgeOperationsOverview:
    organization_id = context.organization_id
    entries = await db.scalar(
        select(func.count()).select_from(KnowledgeEntry).where(
            KnowledgeEntry.organization_id == organization_id,
            KnowledgeEntry.archived_at.is_(None),
        )
    )
    chunks = await db.scalar(
        select(func.count()).select_from(KnowledgeChunk).where(
            KnowledgeChunk.organization_id == organization_id
        )
    )
    job_rows = (
        await db.execute(
            select(KnowledgeIngestionJob.status, func.count())
            .where(KnowledgeIngestionJob.organization_id == organization_id)
            .group_by(KnowledgeIngestionJob.status)
        )
    ).all()
    retrieval_rows = (
        await db.execute(
            select(KnowledgeRetrievalEvent.retrieval_mode, func.count())
            .where(KnowledgeRetrievalEvent.organization_id == organization_id)
            .group_by(KnowledgeRetrievalEvent.retrieval_mode)
        )
    ).all()
    return KnowledgeOperationsOverview(
        entries=int(entries or 0),
        chunks=int(chunks or 0),
        jobs_by_status={status: count for status, count in job_rows},
        retrievals_by_mode={mode: count for mode, count in retrieval_rows},
    )


@router.get("/jobs", response_model=KnowledgeOperationJobList)
async def list_jobs(
    db: DbSession,
    context: OpsContext,
    status: Annotated[str | None, Query()] = None,
) -> KnowledgeOperationJobList:
    statement = select(KnowledgeIngestionJob).where(
        KnowledgeIngestionJob.organization_id == context.organization_id
    )
    if status is not None:
        statement = statement.where(KnowledgeIngestionJob.status == status)
    jobs = list((await db.scalars(statement.order_by(KnowledgeIngestionJob.id.desc()))).all())
    return KnowledgeOperationJobList(
        items=[
            KnowledgeOperationJob(
                id=job.id,
                entry_id=job.knowledge_entry_id,
                status=job.status,
                attempts=job.attempts,
                error_code=job.last_error_code,
                created_at=job.created_at,
            )
            for job in jobs
        ]
    )


async def governed_job(db: AsyncSession, job_id: int, organization_id: int) -> KnowledgeIngestionJob:
    job = await db.scalar(
        select(KnowledgeIngestionJob)
        .where(
            KnowledgeIngestionJob.id == job_id,
            KnowledgeIngestionJob.organization_id == organization_id,
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Knowledge job not found")
    return job


@router.post("/jobs/{job_id}/retry", response_model=KnowledgeOperationJob)
async def retry_job(job_id: int, db: DbSession, context: GovernContext) -> KnowledgeOperationJob:
    job = await governed_job(db, job_id, context.organization_id)
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried")
    job.status = "queued"
    job.attempts = 0
    job.last_error_code = None
    await record_audit(
        db, context.membership, action="knowledge.job.retry", resource_type="knowledge_job", resource_id=str(job.id)
    )
    await db.commit()
    return KnowledgeOperationJob(
        id=job.id, entry_id=job.knowledge_entry_id, status=job.status,
        attempts=job.attempts, error_code=job.last_error_code, created_at=job.created_at
    )

@router.post("/jobs/{job_id}/cancel", response_model=KnowledgeOperationJob)
async def cancel_job(job_id: int, db: DbSession, context: GovernContext) -> KnowledgeOperationJob:
    job = await governed_job(db, job_id, context.organization_id)
    if job.status == "queued":
        job.status = "cancelled"
    elif job.status == "processing":
        job.status = "cancel_requested"
    else:
        raise HTTPException(status_code=409, detail="Knowledge job cannot be cancelled")
    await record_audit(
        db, context.membership, action="knowledge.job.cancel", resource_type="knowledge_job", resource_id=str(job.id), details={"status": job.status}
    )
    await db.commit()
    return KnowledgeOperationJob(
        id=job.id, entry_id=job.knowledge_entry_id, status=job.status,
        attempts=job.attempts, error_code=job.last_error_code, created_at=job.created_at
    )
