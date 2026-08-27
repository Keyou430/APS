from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DashboardDecision, PipelineOutput, PipelineRun, PipelineTask


class PipelineRepository:
    def __init__(self, db: AsyncSession, *, organization_id: int, user_id: int) -> None:
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id

    async def task(self, task_id: int) -> PipelineTask:
        task = await self.db.scalar(
            select(PipelineTask).where(
                PipelineTask.id == task_id,
                PipelineTask.organization_id == self.organization_id,
                PipelineTask.user_id == self.user_id,
                PipelineTask.deleted_at.is_(None),
            )
        )
        if task is None:
            raise HTTPException(status_code=404, detail="Pipeline task not found")
        return task

    async def tasks(
        self, *, status: str | None = None, cursor: int | None = None, limit: int = 20
    ) -> list[PipelineTask]:
        statement = select(PipelineTask).where(
            PipelineTask.organization_id == self.organization_id,
            PipelineTask.user_id == self.user_id,
            PipelineTask.deleted_at.is_(None),
        )
        if status is not None:
            statement = statement.where(PipelineTask.status == status)
        if cursor is not None:
            statement = statement.where(PipelineTask.id < cursor)
        return list(
            (await self.db.scalars(statement.order_by(PipelineTask.id.desc()).limit(limit))).all()
        )

    async def latest_output(self, task_id: int) -> PipelineOutput | None:
        return await self.db.scalar(
            select(PipelineOutput)
            .where(
                PipelineOutput.task_id == task_id,
                PipelineOutput.organization_id == self.organization_id,
                PipelineOutput.user_id == self.user_id,
            )
            .order_by(PipelineOutput.version.desc(), PipelineOutput.id.desc())
        )

    async def run(self, run_id: int) -> PipelineRun:
        run = await self.db.scalar(
            select(PipelineRun)
            .join(PipelineTask, PipelineTask.id == PipelineRun.task_id)
            .where(
                PipelineRun.id == run_id,
                PipelineTask.organization_id == self.organization_id,
                PipelineTask.user_id == self.user_id,
            )
        )
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        return run

    async def manual_run(self, task: PipelineTask, idempotency_key: str) -> tuple[PipelineRun, bool]:
        existing = await self.db.scalar(
            select(PipelineRun).where(
                PipelineRun.task_id == task.id,
                PipelineRun.organization_id == self.organization_id,
                PipelineRun.user_id == self.user_id,
                PipelineRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing, False
        run = PipelineRun(
            organization_id=self.organization_id,
            user_id=self.user_id,
            task_id=task.id,
            trigger_kind="manual",
            status="queued",
            idempotency_key=idempotency_key,
            scheduled_for=None,
        )
        self.db.add(run)
        try:
            await self.db.commit()
        except IntegrityError:
            # Concurrent request inserted the same idempotency key first.
            await self.db.rollback()
            existing = await self.db.scalar(
                select(PipelineRun).where(
                    PipelineRun.task_id == task.id,
                    PipelineRun.organization_id == self.organization_id,
                    PipelineRun.user_id == self.user_id,
                    PipelineRun.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise
            return existing, False
        await self.db.refresh(run)
        return run, True

    async def output(self, output_id: int) -> PipelineOutput:
        output = await self.db.scalar(
            select(PipelineOutput)
            .join(PipelineTask, PipelineTask.id == PipelineOutput.task_id)
            .where(
                PipelineOutput.id == output_id,
                PipelineTask.organization_id == self.organization_id,
                PipelineTask.user_id == self.user_id,
            )
        )
        if output is None:
            raise HTTPException(status_code=404, detail="Pipeline output not found")
        return output

    async def decision(self, decision_id: int) -> DashboardDecision:
        decision = await self.db.scalar(
            select(DashboardDecision)
            .join(PipelineTask, PipelineTask.id == DashboardDecision.task_id)
            .where(
                DashboardDecision.id == decision_id,
                PipelineTask.organization_id == self.organization_id,
                PipelineTask.user_id == self.user_id,
            )
            .with_for_update()
        )
        if decision is None:
            raise HTTPException(status_code=404, detail="Dashboard decision not found")
        return decision

    async def decisions(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[DashboardDecision]:
        statement = (
            select(DashboardDecision)
            .join(PipelineTask, PipelineTask.id == DashboardDecision.task_id)
            .where(
                PipelineTask.organization_id == self.organization_id,
                PipelineTask.user_id == self.user_id,
            )
        )
        if status is not None:
            statement = statement.where(DashboardDecision.status == status)
        return list(
            (
                await self.db.scalars(
                    statement
                    .order_by(DashboardDecision.created_at.desc(), DashboardDecision.id.desc())
                    .limit(limit)
                )
            ).all()
        )


def utc_now() -> datetime:
    return datetime.now(UTC)
