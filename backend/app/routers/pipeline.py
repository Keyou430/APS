from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, OrganizationContext, require_permission
from app.config import get_settings
from app.database import get_db
from app.models import (
    DecisionAction,
    DeliveryTarget,
    NotificationOutbox,
    PipelineOutput,
    PipelineRun,
    PipelineTask,
    RoutingRule,
)
from app.schemas.pipeline import (
    DecisionStatus,
    PipelineDecisionListResponse,
    PipelineDecisionResponse,
    PipelineDraftRequest,
    PipelineDraftResponse,
    PipelineOutputResponse,
    PipelineRunResponse,
    PipelineTaskCreate,
    PipelineTaskListResponse,
    PipelineTaskResponse,
    ApproveDecisionRequest,
    RejectDecisionRequest,
    RequestChangesRequest,
)
from app.services.object_storage import LocalPrivateObjectStorage
from app.services.audit import record_audit
from app.services.delivery_outbox_worker import enqueue_channel_delivery
from app.services.memory_repository import create_manual_memory
from app.services.pipeline_repository import PipelineRepository
from app.services.pipeline_approval import (
    require_authorized_approver,
    validate_task_approval_policy,
)
from app.services.hermes_cron_bridge import register_hermes_cron, remove_hermes_cron
from app.services.pipeline_scheduler import CronExpressionError, next_cron_run


router = APIRouter(tags=["Pipeline"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
PipelineReadContext = Annotated[
    OrganizationContext, Depends(require_permission("pipeline:read"))
]
PipelineWriteContext = Annotated[
    OrganizationContext, Depends(require_permission("pipeline:write"))
]
PipelineRunContext = Annotated[
    OrganizationContext, Depends(require_permission("pipeline:run"))
]
DecisionReadContext = Annotated[
    OrganizationContext, Depends(require_permission("decisions:read"))
]
DecisionWriteContext = Annotated[
    OrganizationContext, Depends(require_permission("decisions:decide"))
]


@router.post("/api/internal/pipeline/trigger")
async def trigger_hermes_pipeline(
    payload: dict[str, object],
    db: DbSession,
    response: Response,
    internal_key: Annotated[str | None, Header(alias="X-Hermes-Internal-Key")] = None,
) -> dict[str, object]:
    """Accept exactly one scheduled slot from a native Hermes cron job."""
    if internal_key != get_settings().hermes_cron_internal_key:
        raise HTTPException(status_code=401, detail="invalid Hermes internal key")
    try:
        task_id = int(payload["task_id"])
        scheduled_for = datetime.fromisoformat(str(payload["scheduled_for"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="task_id and scheduled_for are required") from exc
    task = await db.scalar(select(PipelineTask).where(PipelineTask.id == task_id, PipelineTask.deleted_at.is_(None)))
    if task is None or task.hermes_cron_job_id is None:
        raise HTTPException(status_code=404, detail="Hermes pipeline task not found")
    scheduled_for = scheduled_for.astimezone(UTC)
    existing = await db.scalar(select(PipelineRun).where(PipelineRun.task_id == task.id, PipelineRun.scheduled_for == scheduled_for))
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return {"run_id": existing.id, "status": 200, "created": False}
    run = PipelineRun(
        organization_id=task.organization_id,
        user_id=task.user_id,
        task_id=task.id,
        trigger_kind="scheduled",
        status="queued",
        idempotency_key=f"hermes:{task.hermes_cron_job_id}:{scheduled_for.isoformat()}",
        scheduled_for=scheduled_for,
    )
    db.add(run)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(PipelineRun).where(PipelineRun.task_id == task.id, PipelineRun.scheduled_for == scheduled_for))
        if existing is None:
            raise
        return {"run_id": existing.id, "status": 200, "created": False}
    await db.refresh(run)
    response.status_code = status.HTTP_202_ACCEPTED
    return {"run_id": run.id, "status": 202, "created": True}


def repository(db: AsyncSession, context: OrganizationContext) -> PipelineRepository:
    return PipelineRepository(
        db, organization_id=context.organization_id, user_id=context.user_id
    )


def task_response(task: PipelineTask, output: PipelineOutput | None = None) -> PipelineTaskResponse:
    return PipelineTaskResponse.model_validate(
        {**task.__dict__, "description": task.prompt, "output_id": output.id if output else None}
    )


def run_response(run: PipelineRun, output: PipelineOutput | None = None) -> PipelineRunResponse:
    return PipelineRunResponse.model_validate(
        {**run.__dict__, "output_id": output.id if output else None}
    )


def draft_from_prompt(prompt: str) -> PipelineDraftResponse:
    def cron_time(hour_text: str, minute_text: str) -> tuple[int, int]:
        hour, minute = int(hour_text), int(minute_text)
        if hour > 23 or minute > 59:
            raise ValueError("invalid time in task description")
        return hour, minute

    schedule = None
    monthly = re.search(r"每月\s*(\d{1,2})(?:日|号)\s*(\d{1,2})[:：](\d{2})", prompt)
    workday = re.search(r"(?:每(?:个)?)?工作日\s*(\d{1,2})[:：](\d{2})", prompt)
    weekly = re.search(
        r"每(?:周|星期)\s*([一二三四五六日天])(?:\s*(\d{1,2})[:：](\d{2}))?",
        prompt,
    )
    daily = re.search(r"(?:每天|每日)\s*(\d{1,2})[:：](\d{2})", prompt)
    if monthly is not None:
        day = int(monthly.group(1))
        if day < 1 or day > 31:
            raise ValueError("invalid day in task description")
        hour, minute = cron_time(monthly.group(2), monthly.group(3))
        schedule = f"{minute} {hour} {day} * *"
    elif workday is not None:
        hour, minute = cron_time(workday.group(1), workday.group(2))
        schedule = f"{minute} {hour} * * 1-5"
    elif weekly is not None:
        weekday = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0, "天": 0}[weekly.group(1)]
        hour, minute = cron_time(weekly.group(2) or "9", weekly.group(3) or "0")
        schedule = f"{minute} {hour} * * {weekday}"
    elif re.search(r"weekly\s+wednesday", prompt.casefold()):
        schedule = "0 9 * * 3"
    elif daily is not None:
        hour, minute = cron_time(daily.group(1), daily.group(2))
        schedule = f"{minute} {hour} * * *"
    weekly_schedule = weekly is not None or bool(re.search(r"weekly\s+wednesday", prompt.casefold()))
    web_research = any(
        term in prompt.casefold()
        for term in ("搜索", "趋势", "最新动态", "最近的 ai", "recent ai", "search", "web")
    )
    is_ai_weekly = weekly_schedule and ("ai" in prompt.casefold() or "人工智能" in prompt)
    is_feishu_todo_digest = "飞书" in prompt and any(
        term in prompt for term in ("待办", "任务")
    ) and any(term in prompt for term in ("摘要", "总结", "汇总"))
    is_feishu_weekly_task_report = all(term in prompt for term in ("飞书", "任务", "周报"))
    return PipelineDraftResponse(
        title=(
            "飞书任务周报"
            if is_feishu_weekly_task_report
            else "飞书待办每日摘要"
            if is_feishu_todo_digest and schedule is not None and schedule.endswith("* * *")
            else "飞书待办摘要"
            if is_feishu_todo_digest
            else "AI 最新动态周报"
            if is_ai_weekly
            else "行业趋势日报"
            if web_research
            else prompt[:80]
        ),
        prompt=prompt,
        task_type="web_research" if web_research else "general",
        schedule=schedule,
        timezone="Asia/Shanghai",
        input_sources=["web"] if web_research else [],
        output_format="markdown",
    )


@router.post("/api/pipeline/tasks/draft", response_model=PipelineDraftResponse)
async def create_draft(
    payload: PipelineDraftRequest, context: PipelineWriteContext
) -> PipelineDraftResponse:
    del context
    try:
        return draft_from_prompt(payload.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/api/pipeline/tasks", response_model=PipelineTaskResponse, status_code=status.HTTP_201_CREATED
)
async def create_task(
    payload: PipelineTaskCreate,
    db: DbSession,
    user: CurrentUser,
    context: PipelineWriteContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PipelineTaskResponse:
    repo = repository(db, context)
    if idempotency_key:
        existing = await db.scalar(
            select(PipelineTask).where(
                PipelineTask.organization_id == context.organization_id,
                PipelineTask.user_id == user.id,
                PipelineTask.creation_key == idempotency_key,
            )
        )
        if existing is not None:
            return task_response(existing, await repo.latest_output(existing.id))
    values = payload.model_dump(exclude={"confirmed"})
    await validate_task_approval_policy(
        db,
        organization_id=context.organization_id,
        owner_user_id=user.id,
        approval_required=values["approval_required"],
        assignee_type=values["approval_assignee_type"],
        assignee_id=values["approval_assignee_id"],
        role_name=values["approval_role_name"],
        escalation_role_name=values["approval_escalation_role_name"],
    )
    if values.get("schedule"):
        try:
            next_run_at = next_cron_run(
                values["schedule"], values["timezone"], after=datetime.now(UTC)
            )
        except (CronExpressionError, ZoneInfoNotFoundError) as exc:
            raise HTTPException(
                status_code=422, detail="schedule must be a valid cron expression"
            ) from exc
    else:
        next_run_at = None
    task = PipelineTask(
        organization_id=context.organization_id,
        user_id=user.id,
        status="ready",
        revision=1,
        creation_key=idempotency_key,
        next_run_at=next_run_at,
        **values,
    )
    db.add(task)
    await db.flush()
    hermes_cron_job_id: str | None = None
    if values.get("schedule"):
        try:
            hermes_cron_job_id = await register_hermes_cron(
                task_id=task.id,
                schedule=values["schedule"],
                title=values["title"],
                timezone=values["timezone"],
            )
            task.hermes_cron_job_id = hermes_cron_job_id
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=502, detail="Hermes cron registration failed") from exc
    try:
        await db.commit()
    except Exception as exc:
        try:
            await db.rollback()
        finally:
            if hermes_cron_job_id is not None:
                await remove_hermes_cron(hermes_cron_job_id, task_id=task.id)
        if not isinstance(exc, IntegrityError):
            raise
        # Concurrent request created the same creation_key first.
        existing = await db.scalar(
            select(PipelineTask).where(
                PipelineTask.organization_id == context.organization_id,
                PipelineTask.user_id == user.id,
                PipelineTask.creation_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        return task_response(existing, await repo.latest_output(existing.id))
    await db.refresh(task)
    return task_response(task)


@router.get("/api/pipeline/tasks", response_model=PipelineTaskListResponse)
async def list_tasks(
    db: DbSession,
    context: PipelineReadContext,
    task_status: Annotated[Literal["ready", "paused"] | None, Query(alias="status")] = None,
    cursor: int | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PipelineTaskListResponse:
    repo = repository(db, context)
    rows = await repo.tasks(status=task_status, cursor=cursor, limit=limit + 1)
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [task_response(item, await repo.latest_output(item.id)) for item in rows]
    return PipelineTaskListResponse(
        items=items, next_cursor=rows[-1].id if has_more and rows else None
    )


@router.get("/api/pipeline/tasks/{task_id}", response_model=PipelineTaskResponse)
async def get_task(
    task_id: int, db: DbSession, context: PipelineReadContext
) -> PipelineTaskResponse:
    repo = repository(db, context)
    task = await repo.task(task_id)
    return task_response(task, await repo.latest_output(task.id))


@router.post("/api/pipeline/tasks/{task_id}/run", response_model=PipelineRunResponse)
async def run_task(
    task_id: int,
    response: Response,
    db: DbSession,
    context: PipelineRunContext,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> PipelineRunResponse:
    repo = repository(db, context)
    task = await repo.task(task_id)
    run, created = await repo.manual_run(task, idempotency_key)
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    output = await db.scalar(
        select(PipelineOutput).where(
            PipelineOutput.run_id == run.id,
            PipelineOutput.organization_id == context.organization_id,
            PipelineOutput.user_id == context.user_id,
        )
    )
    return run_response(run, output)


@router.get("/api/pipeline/runs/{run_id}", response_model=PipelineRunResponse)
async def get_run(
    run_id: int, db: DbSession, context: PipelineReadContext
) -> PipelineRunResponse:
    repo = repository(db, context)
    run = await repo.run(run_id)
    output = await db.scalar(select(PipelineOutput).where(PipelineOutput.run_id == run.id))
    return run_response(run, output)


@router.get("/api/pipeline/outputs/{output_id}", response_model=PipelineOutputResponse)
async def get_output(
    output_id: int, db: DbSession, context: PipelineReadContext
) -> PipelineOutput:
    return await repository(db, context).output(output_id)


@router.get("/api/pipeline/outputs/{output_id}/download")
async def download_output(
    output_id: int, db: DbSession, context: PipelineReadContext
) -> FastAPIResponse:
    output = await repository(db, context).output(output_id)
    try:
        content = await LocalPrivateObjectStorage(get_settings().upload_dir).open_read(
            output.object_key
        )
    except FileNotFoundError:
        content = output.markdown.encode("utf-8")
    filename = Path(output.title).name.replace('"', "").replace("\r", "").replace("\n", "")
    return FastAPIResponse(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename or "pipeline-output"}.md"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/api/dashboard/decisions", response_model=PipelineDecisionListResponse)
async def list_decisions(
    db: DbSession,
    context: DecisionReadContext,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status: Annotated[DecisionStatus | None, Query()] = None,
) -> PipelineDecisionListResponse:
    return PipelineDecisionListResponse(
        items=await repository(db, context).decisions(status=status, limit=limit)
    )


async def _enqueue_decision_feishu_deliveries(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
    decision_id: int,
    decision_status: Literal["approved", "changes_requested"],
    payload: dict[str, object] | None = None,
) -> None:
    """Feishu delivery rows for a decision notification, inside the decision
    transaction. Idempotent per (decision, status, target); the consumer
    worker performs the external send later."""
    target_ids = (
        await db.scalars(
            select(DeliveryTarget.id)
            .join(RoutingRule, RoutingRule.delivery_target_id == DeliveryTarget.id)
            .where(
                DeliveryTarget.organization_id == organization_id,
                DeliveryTarget.provider == "feishu",
                DeliveryTarget.is_active.is_(True),
                RoutingRule.organization_id == organization_id,
                RoutingRule.member_user_id == user_id,
                RoutingRule.enabled.is_(True),
            )
            .distinct()
        )
    ).all()
    targets = (
        await db.scalars(select(DeliveryTarget).where(DeliveryTarget.id.in_(target_ids)))
    ).all() if target_ids else []
    for target in targets:
        await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type=f"pipeline.decision.{decision_status}",
            payload={
                "decision_id": decision_id,
                "status": decision_status,
                **(payload or {}),
            },
            idempotency_key=(
                f"decision-{decision_status.replace('_', '-')}:"
                f"{decision_id}:feishu:{target.id}"
            ),
        )


async def record_decision_action(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
    decision_id: int,
    action: str,
    idempotency_key: str,
    payload: dict[str, object],
) -> bool:
    payload_hash = decision_payload_hash(payload)
    existing = await db.scalar(
        select(DecisionAction).where(
            DecisionAction.organization_id == organization_id,
            DecisionAction.decision_id == decision_id,
            DecisionAction.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.action != action or existing.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail="Idempotency key payload conflict")
        return False
    db.add(
        DecisionAction(
            organization_id=organization_id,
            user_id=user_id,
            decision_id=decision_id,
            action=action,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
    )
    return True


def decision_payload_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


async def replay_decision_after_conflict(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
    decision_id: int,
    action: str,
    idempotency_key: str,
    payload: dict[str, object],
) -> object:
    await db.rollback()
    existing = await db.scalar(
        select(DecisionAction).where(
            DecisionAction.organization_id == organization_id,
            DecisionAction.decision_id == decision_id,
            DecisionAction.idempotency_key == idempotency_key,
        )
    )
    if (
        existing is None
        or existing.action != action
        or existing.payload_hash != decision_payload_hash(payload)
    ):
        raise HTTPException(status_code=409, detail="Decision was handled concurrently")
    return await PipelineRepository(
        db, organization_id=organization_id, user_id=user_id
    ).decision(decision_id)


@router.post(
    "/api/dashboard/decisions/{decision_id}/approve",
    response_model=PipelineDecisionResponse,
)
async def approve_decision(
    decision_id: int,
    db: DbSession,
    context: DecisionWriteContext,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    payload: Annotated[ApproveDecisionRequest | None, Body()] = None,
) -> object:
    organization_id = context.organization_id
    user_id = context.user_id
    repo = repository(db, context)
    decision = await repo.decision(decision_id)
    task = await db.scalar(
        select(PipelineTask).where(
            PipelineTask.id == decision.task_id,
            PipelineTask.organization_id == context.organization_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Pipeline task not found")
    await require_authorized_approver(db, task=task, user_id=context.user_id)
    key = idempotency_key
    action_payload: dict[str, object] = (payload or ApproveDecisionRequest()).model_dump()
    try:
        action_created = await record_decision_action(
            db,
            organization_id=context.organization_id,
            user_id=context.user_id,
            decision_id=decision.id,
            action="approve",
            idempotency_key=key,
            payload=action_payload,
        )
        if not action_created:
            return decision
        if decision.status != "pending":
            raise HTTPException(status_code=409, detail="Decision is already terminal")
        if decision.status == "pending":
            output = await db.scalar(
                select(PipelineOutput).where(
                    PipelineOutput.id == decision.output_id,
                    PipelineOutput.organization_id == context.organization_id,
                )
            )
            if output is None:
                raise HTTPException(status_code=404, detail="Pipeline output not found")
            memory = await create_manual_memory(
                db,
                organization_id=context.organization_id,
                user_id=context.user_id,
                content=decision.summary or output.markdown,
                memory_type="decision",
                metadata={
                    "pipeline_decision_id": str(decision.id),
                    "pipeline_output_id": str(output.id),
                    "pipeline_run_id": str(decision.run_id),
                    "pipeline_task_id": str(decision.task_id),
                },
            )
            await record_audit(
                db,
                context.membership,
                action="pipeline.decision.approve",
                resource_type="dashboard_decision",
                resource_id=str(decision.id),
                details={"memory_id": memory.memory_id, "output_id": output.id},
            )
            db.add(
                NotificationOutbox(
                    organization_id=context.organization_id,
                    event_key=f"decision-approved:{decision.id}",
                    event_type="pipeline.decision.approved",
                    payload={"decision_id": decision.id, "status": "approved"},
                    status="pending",
                )
            )
            await _enqueue_decision_feishu_deliveries(
                db,
                organization_id=context.organization_id,
                user_id=decision.user_id,
                decision_id=decision.id,
                decision_status="approved",
            )
            decision.status = "approved"
            decision.approver_user_id = context.user_id
            decision.approval_comment = (payload.comment if payload is not None else None)
            decision.decided_at = datetime.now(UTC)
            decision.revision += 1
        await db.commit()
    except IntegrityError:
        return await replay_decision_after_conflict(
            db,
            organization_id=organization_id,
            user_id=user_id,
            decision_id=decision_id,
            action="approve",
            idempotency_key=key,
            payload=action_payload,
        )
    await db.refresh(decision)
    return decision


@router.post(
    "/api/dashboard/decisions/{decision_id}/request-changes",
    response_model=PipelineDecisionResponse,
)
async def request_changes(
    decision_id: int,
    payload: RequestChangesRequest,
    db: DbSession,
    context: DecisionWriteContext,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    reason_type: str | None = None,
) -> object:
    organization_id = context.organization_id
    user_id = context.user_id
    repo = repository(db, context)
    decision = await repo.decision(decision_id)
    task = await db.scalar(
        select(PipelineTask).where(
            PipelineTask.id == decision.task_id,
            PipelineTask.organization_id == context.organization_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Pipeline task not found")
    await require_authorized_approver(db, task=task, user_id=context.user_id)
    key = idempotency_key
    action_payload: dict[str, object] = {"reason": payload.reason}
    if reason_type is not None:
        action_payload["reason_type"] = reason_type
    try:
        action_created = await record_decision_action(
            db,
            organization_id=context.organization_id,
            user_id=context.user_id,
            decision_id=decision.id,
            action="regenerate",
            idempotency_key=key,
            payload=action_payload,
        )
        if not action_created:
            return decision
        can_retry_failed_regeneration = False
        if decision.status == "changes_requested" and decision.regeneration_run_id is not None:
            previous_run = await db.get(PipelineRun, decision.regeneration_run_id)
            can_retry_failed_regeneration = previous_run is not None and previous_run.status in {
                "failed",
                "cancelled",
            }
        if decision.status != "pending" and not can_retry_failed_regeneration:
            raise HTTPException(status_code=409, detail="Decision is already terminal")
        if decision.status == "pending" or can_retry_failed_regeneration:
            run = PipelineRun(
                organization_id=context.organization_id,
                user_id=context.user_id,
                task_id=decision.task_id,
                trigger_kind="manual",
                status="queued",
                # Derived from the action's idempotency key so the run is
                # traceable to this decision action and stable across retries.
                idempotency_key=f"decision-regen:{decision.id}:{key[:100]}",
                prompt_override=(
                    f"{task.prompt}\n\n"
                    f"Regeneration feedback:\n{payload.reason}"
                ),
            )
            db.add(run)
            await db.flush()
            decision.status = "changes_requested"
            decision.change_request = payload.reason
            decision.rejection_reason = payload.reason if reason_type is not None else None
            decision.reason_type = reason_type
            decision.approver_user_id = context.user_id if reason_type is not None else None
            decision.decided_at = datetime.now(UTC) if reason_type is not None else None
            decision.regeneration_run_id = run.id
            decision.revision += 1
            if reason_type is not None:
                await record_audit(
                    db,
                    context.membership,
                    action="pipeline.decision.reject",
                    resource_type="dashboard_decision",
                    resource_id=str(decision.id),
                    details={"reason_type": reason_type, "regeneration_run_id": run.id},
                )
                await _enqueue_decision_feishu_deliveries(
                    db,
                    organization_id=context.organization_id,
                    user_id=decision.user_id,
                    decision_id=decision.id,
                    decision_status="changes_requested",
                    payload={
                        "reason_type": reason_type,
                        "regeneration_run_id": run.id,
                    },
                )
        await db.commit()
    except IntegrityError:
        return await replay_decision_after_conflict(
            db,
            organization_id=organization_id,
            user_id=user_id,
            decision_id=decision_id,
            action="regenerate",
            idempotency_key=key,
            payload=action_payload,
        )
    await db.refresh(decision)
    return decision


@router.post(
    "/api/dashboard/decisions/{decision_id}/reject",
    response_model=PipelineDecisionResponse,
)
async def reject_decision(
    decision_id: int,
    payload: RejectDecisionRequest,
    db: DbSession,
    context: DecisionWriteContext,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> object:
    return await request_changes(
        decision_id,
        RequestChangesRequest(reason=payload.reason),
        db,
        context,
        idempotency_key,
        payload.reason_type,
    )
