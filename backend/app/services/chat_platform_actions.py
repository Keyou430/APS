"""Platform-owned actions recognized at the chat boundary.

Hermes remains a text provider. State-changing requests are parsed, authorized,
audited, and executed by the platform so a chat reply cannot masquerade as an
external action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import OrganizationMembership, PipelineRun, PipelineTask
from app.routers.pipeline import draft_from_prompt
from app.schemas.pipeline import PipelineDraftResponse
from app.services.audit import record_audit
from app.services.pipeline_executor import (
    PipelineTaskExecutor,
    run_pipeline_run_now,
)
from app.services.pipeline_repository import PipelineRepository
from app.services.pipeline_scheduler import CronExpressionError, next_cron_run


_SCHEDULED_TASK_INTENT = re.compile(r"(?:创建|新建|建立|添加).{0,80}定时任务")
_RUN_NOW_INTENT = re.compile(r"(?:立即|现在|马上).{0,8}(?:执行|运行).{0,8}(?:一次|一遍)?")
_NON_MUTATING_INTENT = re.compile(r"(?:不要|别|不需要|无需|如何|怎么|是否|如果|假如|能否|可以吗|[?？])")


@dataclass(frozen=True)
class ScheduledPipelineCommand:
    prompt: str
    status: str
    draft: PipelineDraftResponse | None
    run_now: bool


@dataclass(frozen=True)
class PlatformActionResult:
    status: str
    message: str
    task_id: int | None = None
    run_id: int | None = None
    title: str | None = None

    def as_event(self) -> dict[str, object]:
        return {
            "action": "pipeline_task",
            "status": self.status,
            "message": self.message,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "title": self.title,
        }

    def as_instruction(self) -> str:
        return (
            "PLATFORM_ACTION_RESULT (authoritative; do not contradict it): "
            f"pipeline task status={self.status}; task_id={self.task_id}; "
            f"run_id={self.run_id}; message={self.message}"
        )


def parse_scheduled_pipeline_command(prompt: str) -> ScheduledPipelineCommand | None:
    normalized = prompt.strip()
    if (
        not normalized
        or _NON_MUTATING_INTENT.search(normalized) is not None
        or _SCHEDULED_TASK_INTENT.search(normalized) is None
    ):
        return None
    draft = draft_from_prompt(normalized)
    if draft.schedule is None:
        return ScheduledPipelineCommand(
            prompt=normalized,
            status="needs_schedule",
            draft=None,
            run_now=bool(_RUN_NOW_INTENT.search(normalized)),
        )
    return ScheduledPipelineCommand(
        prompt=normalized,
        status="ready",
        draft=draft,
        run_now=bool(_RUN_NOW_INTENT.search(normalized)),
    )


def schedule_required_action() -> PlatformActionResult:
    return PlatformActionResult(
        status="needs_schedule",
        message="未创建任务：请明确提供执行频率，例如每天 09:00 或每周三。",
    )


def permission_denied_action() -> PlatformActionResult:
    return PlatformActionResult(
        status="permission_denied",
        message="未创建任务：当前账号缺少任务创建或执行权限。",
    )


def idempotency_required_action() -> PlatformActionResult:
    return PlatformActionResult(
        status="client_message_id_required",
        message="未创建任务：请刷新页面后重试，以确保平台操作不会重复执行。",
    )


async def execute_scheduled_pipeline_command(
    db: AsyncSession,
    *,
    command: ScheduledPipelineCommand,
    organization_id: int,
    user_id: int,
    membership: OrganizationMembership,
    session_id: int,
    request_id: str,
    executor: PipelineTaskExecutor | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> PlatformActionResult:
    if command.status != "ready" or command.draft is None:
        return schedule_required_action()

    draft = command.draft
    try:
        next_run_at = next_cron_run(draft.schedule, draft.timezone, after=datetime.now(UTC))
    except (CronExpressionError, ValueError):
        return PlatformActionResult(
            status="invalid_schedule",
            message="未创建任务：无法识别定时表达式。",
        )

    creation_key = f"chat-task-{session_id}-{request_id}"
    task = await db.scalar(
        select(PipelineTask).where(
            PipelineTask.organization_id == organization_id,
            PipelineTask.user_id == user_id,
            PipelineTask.creation_key == creation_key,
        )
    )
    if task is None:
        task = PipelineTask(
            organization_id=organization_id,
            user_id=user_id,
            title=draft.title,
            prompt=draft.prompt,
            task_type=draft.task_type,
            schedule=draft.schedule,
            timezone=draft.timezone,
            input_sources=draft.input_sources,
            output_format=draft.output_format,
            status="ready",
            revision=1,
            creation_key=creation_key,
            next_run_at=next_run_at,
        )
        db.add(task)
        try:
            await db.flush()
            await record_audit(
                db,
                membership,
                action="chat.pipeline_task.create_and_run",
                resource_type="pipeline_task",
                resource_id=str(task.id),
                details={
                    "schedule": draft.schedule,
                    "timezone": draft.timezone,
                    "immediate_execution_requested": command.run_now,
                    "chat_session_id": session_id,
                },
            )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            task = await db.scalar(
                select(PipelineTask).where(
                    PipelineTask.organization_id == organization_id,
                    PipelineTask.user_id == user_id,
                    PipelineTask.creation_key == creation_key,
                )
            )
            if task is None:
                raise
    await db.refresh(task)

    if not command.run_now:
        return PlatformActionResult(
            status="scheduled",
            message="已创建定时任务。",
            task_id=task.id,
            title=task.title,
        )

    repo = PipelineRepository(db, organization_id=organization_id, user_id=user_id)
    run, _created = await repo.manual_run(
        task,
        idempotency_key=f"chat-run-{session_id}-{request_id}",
    )
    if run.status == "queued":
        await run_pipeline_run_now(
            session_factory,
            executor=executor,
            worker_id=f"chat-{session_id}-{request_id}",
            run_id=run.id,
        )
    await db.refresh(run)
    return _action_for_run(task, run)


def _action_for_run(task: PipelineTask, run: PipelineRun) -> PlatformActionResult:
    if run.status == "completed":
        message = "已创建定时任务，并已立即执行一次。"
    elif run.status == "failed":
        message = "已创建定时任务，但本次立即执行失败。"
    elif run.status == "running":
        message = "已创建定时任务，本次立即执行正在进行。"
    else:
        message = "已创建定时任务，本次立即执行已入队。"
    return PlatformActionResult(
        status=run.status,
        message=message,
        task_id=task.id,
        run_id=run.id,
        title=task.title,
    )


__all__ = [
    "PlatformActionResult",
    "ScheduledPipelineCommand",
    "execute_scheduled_pipeline_command",
    "idempotency_required_action",
    "parse_scheduled_pipeline_command",
    "permission_denied_action",
    "schedule_required_action",
]
