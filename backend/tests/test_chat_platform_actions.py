from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AuditEvent, OrganizationMembership, PipelineRun, PipelineTask, User
from app.services.chat_platform_actions import (
    execute_scheduled_pipeline_command,
    parse_scheduled_pipeline_command,
)
from app.services.pipeline_executor import PipelineExecutionResult
from app.services.web_evidence import WebEvidence


def _evidence(correlation_id: str) -> WebEvidence:
    return WebEvidence(
        provider="test",
        url="https://example.com/current",
        title="Current source",
        published_at=datetime(2026, 8, 17, tzinfo=UTC),
        searched_at=datetime(2026, 8, 17, 2, 0, tzinfo=UTC),
        correlation_id=correlation_id,
    )


def test_scheduled_pipeline_command_keeps_an_editable_draft_when_recurrence_is_missing() -> None:
    command = parse_scheduled_pipeline_command("帮我创建定时任务并立即执行一次，汇总行业动态")

    assert command is not None
    assert command.status == "draft"
    assert command.draft is not None
    assert command.draft.schedule is None
    assert command.run_now is True


@pytest.mark.parametrize(
    "prompt",
    [
        "定时任务每周三如何运行？",
        "不要创建定时任务，每周三执行一次。",
        "如果创建定时任务，每周三应该怎么配置？",
    ],
)
def test_scheduled_pipeline_command_ignores_questions_and_non_create_statements(prompt: str) -> None:
    assert parse_scheduled_pipeline_command(prompt) is None


@pytest.mark.asyncio
async def test_chat_command_returns_draft_without_creating_or_running_task() -> None:
    class FakeExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            correlation_id = f"chat-command-{task.id}"
            return PipelineExecutionResult(
                title=task.title,
                markdown="# AI 周报",
                summary="已生成",
                sources=[{"url": "https://example.com/current"}],
                correlation_id=correlation_id,
                evidence=[_evidence(correlation_id)],
            )

    command = parse_scheduled_pipeline_command("请创建每周三 AI 最新动态周报定时任务，并立即执行一次")
    assert command is not None
    assert command.status == "draft"
    assert command.draft is not None

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == user.default_organization_id,
                OrganizationMembership.user_id == user.id,
            )
        )
        assert membership is not None
        result = await execute_scheduled_pipeline_command(
            db,
            command=command,
            organization_id=membership.organization_id,
            user_id=user.id,
            membership=membership,
            session_id=321,
            request_id="chat-message-321",
            executor=FakeExecutor(),
            session_factory=SessionLocal,
        )

    assert result.status == "draft"
    assert result.task_id is None
    assert result.run_id is None
    assert result.draft is not None
    assert result.draft["schedule"] == "0 9 * * 3"
    assert result.draft["approval_required"] is True
    assert result.as_event()["run_now"] is True

    async with SessionLocal() as db:
        task_count = await db.scalar(select(func.count(PipelineTask.id)))
        run_count = await db.scalar(select(func.count(PipelineRun.id)))
        audit = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "chat.pipeline_task.create_and_run",
            )
        )
    assert task_count == 0
    assert run_count == 0
    assert audit is None


@pytest.mark.asyncio
async def test_chat_command_replays_same_draft_for_a_retried_message_without_side_effects() -> None:
    class FakeExecutor:
        executions = 0

        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            self.executions += 1
            correlation_id = f"chat-retry-{task.id}"
            return PipelineExecutionResult(
                title=task.title,
                markdown="# AI 周报",
                summary="已生成",
                sources=[{"url": "https://example.com/current"}],
                correlation_id=correlation_id,
                evidence=[_evidence(correlation_id)],
            )

    command = parse_scheduled_pipeline_command("请创建每周三 AI 最新动态周报定时任务，并立即执行一次")
    assert command is not None and command.status == "draft"
    executor = FakeExecutor()
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == user.default_organization_id,
                OrganizationMembership.user_id == user.id,
            )
        )
        assert membership is not None
        first = await execute_scheduled_pipeline_command(
            db,
            command=command,
            organization_id=membership.organization_id,
            user_id=user.id,
            membership=membership,
            session_id=322,
            request_id="chat-message-retry-322",
            executor=executor,
            session_factory=SessionLocal,
        )
        second = await execute_scheduled_pipeline_command(
            db,
            command=command,
            organization_id=membership.organization_id,
            user_id=user.id,
            membership=membership,
            session_id=322,
            request_id="chat-message-retry-322",
            executor=executor,
            session_factory=SessionLocal,
        )

    assert second.as_event() == first.as_event()
    assert executor.executions == 0
    async with SessionLocal() as db:
        task_count = await db.scalar(select(func.count(PipelineTask.id)))
        run_count = await db.scalar(select(func.count(PipelineRun.id)))
    assert task_count == 0
    assert run_count == 0
