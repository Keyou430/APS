from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    DashboardDecision,
    OrganizationMembership,
    PipelineOutput,
    PipelineRun,
    PipelineTask,
)
from app.services.pipeline_executor import (
    HermesPipelineExecutor,
    PipelineExecutionResult,
    claim_pipeline_runs,
    recover_stale_pipeline_runs,
    run_pipeline_cycle,
    run_pipeline_run_now,
)
from app.services.web_evidence import WebEvidence

pytestmark = pytest.mark.asyncio


async def test_general_feishu_pipeline_uses_the_known_readonly_lark_shortcut() -> None:
    captured_prompt = ""

    class CapturingClient:
        async def create_openai_response(self, prompt: str, *, context) -> dict:
            nonlocal captured_prompt
            captured_prompt = prompt
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"title":"飞书待办","markdown":"# 摘要",'
                                    '"summary":"完成","sources":[]}'
                                ),
                            }
                        ],
                    }
                ]
            }

    class CapturingRouter:
        def client_for(self, backend: str) -> CapturingClient:
            assert backend == "agent"
            return CapturingClient()

    task = PipelineTask(
        id=99,
        organization_id=1,
        user_id=1,
        title="飞书待办摘要",
        prompt="每天读取我的飞书待办并生成摘要",
        task_type="general",
        schedule="0 9 * * *",
        timezone="Asia/Shanghai",
        input_sources=[],
        output_format="markdown",
        status="ready",
    )

    result = await HermesPipelineExecutor(CapturingRouter()).execute(task)

    assert result.sources == []
    assert 'lark_cli_execute exactly with argv ["task", "+get-my-tasks"]' in captured_prompt
    assert "Do not call lark_cli_schema or lark_cli_help" in captured_prompt
    assert "sources must be an empty array" in captured_prompt


async def test_feishu_weekly_task_report_uses_all_tasks_in_current_week() -> None:
    captured_prompt = ""

    class CapturingClient:
        async def create_openai_response(self, prompt: str, *, context) -> dict:
            nonlocal captured_prompt
            captured_prompt = prompt
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"title":"任务周报","markdown":"# 周报",'
                                '"summary":"完成","sources":[]}',
                            }
                        ],
                    }
                ]
            }

    class CapturingRouter:
        def client_for(self, backend: str) -> CapturingClient:
            assert backend == "agent"
            return CapturingClient()

    task = PipelineTask(
        id=100,
        organization_id=1,
        user_id=1,
        title="飞书任务周报",
        prompt="读取本周飞书任务并生成任务周报",
        task_type="general",
        schedule="0 18 * * 5",
        timezone="Asia/Shanghai",
        input_sources=[],
        output_format="markdown",
        status="ready",
    )

    class FixedClockExecutor(HermesPipelineExecutor):
        def __init__(self, router):
            super().__init__(router, now_provider=lambda: datetime(2026, 8, 28, 10, tzinfo=UTC))

    result = await FixedClockExecutor(CapturingRouter()).execute(task)

    assert result.sources == []
    assert 'lark_cli_execute exactly with argv ["task", "+get-my-tasks", "--created_at", "2026-08-24", "--page-all"]' in captured_prompt
    assert "2026-08-24 00:00:00" in captured_prompt
    assert "2026-08-30 23:59:59" in captured_prompt
    assert "both completed and incomplete" in captured_prompt
    assert "Do not pass --complete=false" in captured_prompt


def _evidence(url: str, correlation_id: str) -> WebEvidence:
    return WebEvidence(
        provider="exa",
        url=url,
        title="Industry report",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        searched_at=datetime(2026, 8, 17, 2, 0, tzinfo=UTC),
        correlation_id=correlation_id,
    )


async def _queued_run() -> int:
    async with SessionLocal() as db:
        membership = await db.scalar(select(OrganizationMembership).limit(1))
        assert membership is not None
        task = PipelineTask(
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            title="Pipeline worker probe",
            prompt="Search current industry trends and cite sources",
            task_type="web_research",
            schedule=None,
            timezone="Asia/Shanghai",
            input_sources=["web"],
            output_format="markdown",
            status="ready",
        )
        db.add(task)
        await db.flush()
        run = PipelineRun(
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            task_id=task.id,
            trigger_kind="manual",
            status="queued",
            idempotency_key=f"worker-{task.id}",
        )
        db.add(run)
        await db.commit()
        return run.id


async def test_two_workers_cannot_claim_the_same_pipeline_run() -> None:
    run_id = await _queued_run()
    async with SessionLocal() as db:
        first = await claim_pipeline_runs(db, worker_id="worker-a", limit=1)
        await db.commit()
    async with SessionLocal() as db:
        second = await claim_pipeline_runs(db, worker_id="worker-b", limit=1)
        await db.commit()

    assert [item.id for item in first] == [run_id]
    assert all(item.id != run_id for item in second)


async def test_targeted_immediate_run_does_not_claim_another_queued_run() -> None:
    target_run_id = await _queued_run()
    other_run_id = await _queued_run()

    class FakeExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            correlation_id = f"targeted-{task.id}"
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Immediate result",
                sources=[{"url": "https://example.com/targeted"}],
                summary="Targeted run completed",
                correlation_id=correlation_id,
                evidence=[_evidence("https://example.com/targeted", correlation_id)],
            )

    executed = await run_pipeline_run_now(
        SessionLocal,
        executor=FakeExecutor(),
        worker_id="chat-targeted",
        run_id=target_run_id,
    )

    assert executed is True
    async with SessionLocal() as db:
        target = await db.get(PipelineRun, target_run_id)
        other = await db.get(PipelineRun, other_run_id)
    assert target is not None and target.status == "completed"
    assert other is not None and other.status == "queued"


async def test_targeted_immediate_run_fails_closed_without_an_executor() -> None:
    run_id = await _queued_run()

    executed = await run_pipeline_run_now(
        SessionLocal,
        executor=None,
        worker_id="chat-unavailable",
        run_id=run_id,
    )

    assert executed is True
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
    assert run is not None and run.status == "failed"
    assert run.error_code == "execution_unavailable"


async def test_stale_lease_requeues_the_original_run() -> None:
    run_id = await _queued_run()
    async with SessionLocal() as db:
        claimed = await claim_pipeline_runs(db, worker_id="worker-a", limit=1)
        assert claimed and claimed[0].id == run_id
        claimed[0].lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

    async with SessionLocal() as db:
        recovered = await recover_stale_pipeline_runs(db)
        await db.commit()
        run = await db.get(PipelineRun, run_id)
        assert recovered == 1
        assert run is not None and run.status == "queued"
        assert run.attempt == 1
        assert run.claimed_by is None


async def test_pipeline_cycle_persists_markdown_sources_and_pending_decision() -> None:
    run_id = await _queued_run()
    correlation_id = f"pipeline-evidence-{run_id}"

    class FakeExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            return PipelineExecutionResult(
                title=f"{task.title} result",
                markdown="# Trend report\n\n- Verified trend [source](https://example.com/report)",
                sources=[
                    {
                        "url": "https://example.com/report",
                        "title": "Industry report",
                        "published_at": "2026-08-17T00:00:00Z",
                        "searched_at": "2026-08-17T02:00:00Z",
                    }
                ],
                summary="One verified trend",
                correlation_id=correlation_id,
                evidence=[_evidence("https://example.com/report", correlation_id)],
            )

    processed = await run_pipeline_cycle(
        SessionLocal, executor=FakeExecutor(), worker_id="worker-success", limit=1
    )
    assert processed == 1
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        output = await db.scalar(select(PipelineOutput).where(PipelineOutput.run_id == run_id))
        decision = await db.scalar(
            select(DashboardDecision).where(DashboardDecision.run_id == run_id)
        )
        assert run is not None and run.status == "completed"
        assert output is not None
        # Sources persisted from validated provider evidence, not raw model JSON.
        assert output.sources[0]["provider"] == "exa"
        assert output.sources[0]["correlation_id"] == correlation_id
        assert decision is not None and decision.status == "pending"


async def test_pipeline_cycle_skips_decision_when_task_approval_is_disabled() -> None:
    run_id = await _queued_run()
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        assert run is not None
        task = await db.get(PipelineTask, run.task_id)
        assert task is not None
        task.task_type = "general"
        task.input_sources = []
        task.approval_required = False
        await db.commit()

    correlation_id = f"pipeline-no-approval-{run_id}"

    class FakeExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Direct output",
                sources=[],
                summary="Direct output",
                correlation_id=correlation_id,
            )

    await run_pipeline_cycle(
        SessionLocal, executor=FakeExecutor(), worker_id="worker-no-approval", limit=1
    )
    async with SessionLocal() as db:
        output = await db.scalar(select(PipelineOutput).where(PipelineOutput.run_id == run_id))
        decision = await db.scalar(
            select(DashboardDecision).where(DashboardDecision.run_id == run_id)
        )
    assert output is not None
    assert decision is None


async def test_scheduled_pipeline_cycle_creates_decision_when_approval_is_disabled() -> None:
    run_id = await _queued_run()
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        assert run is not None
        run.trigger_kind = "scheduled"
        task = await db.get(PipelineTask, run.task_id)
        assert task is not None
        task.task_type = "general"
        task.input_sources = []
        task.approval_required = False
        await db.commit()

    class FakeExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Scheduled output",
                sources=[],
                summary="Scheduled output",
                correlation_id=f"scheduled-{task.id}",
            )

    await run_pipeline_cycle(
        SessionLocal, executor=FakeExecutor(), worker_id="worker-scheduled", limit=1
    )
    async with SessionLocal() as db:
        decision = await db.scalar(
            select(DashboardDecision).where(DashboardDecision.run_id == run_id)
        )
    assert decision is not None and decision.status == "pending"


async def test_web_research_without_sources_fails_closed() -> None:
    run_id = await _queued_run()
    correlation_id = f"pipeline-evidence-{run_id}"

    class SourceLessExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Unsupported trend",
                sources=[],
                summary="Unsupported trend",
                correlation_id=correlation_id,
                evidence=[_evidence("https://example.com/report", correlation_id)],
            )

    await run_pipeline_cycle(
        SessionLocal, executor=SourceLessExecutor(), worker_id="worker-fail", limit=1
    )
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        output = await db.scalar(select(PipelineOutput).where(PipelineOutput.run_id == run_id))
        assert run is not None and run.status == "failed"
        assert run.error_code == "sources_required"
        assert output is None


async def test_web_research_uses_model_url_claim_and_provider_metadata() -> None:
    run_id = await _queued_run()
    correlation_id = f"pipeline-evidence-{run_id}"

    class UrlClaimExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Provider-backed trend",
                sources=[{"url": "https://example.com/report"}],
                summary="Provider-backed trend",
                correlation_id=correlation_id,
                evidence=[_evidence("https://example.com/report", correlation_id)],
            )

    await run_pipeline_cycle(
        SessionLocal, executor=UrlClaimExecutor(), worker_id="worker-url-claim", limit=1
    )
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        output = await db.scalar(select(PipelineOutput).where(PipelineOutput.run_id == run_id))
        assert run is not None and run.status == "completed"
        assert output is not None
        assert output.sources[0]["title"] == "Industry report"
        assert output.sources[0]["published_at"] == "2026-08-01T00:00:00+00:00"
        assert output.sources[0]["searched_at"] == "2026-08-17T02:00:00+00:00"


async def test_web_research_model_only_sources_fail_without_provider_evidence() -> None:
    run_id = await _queued_run()
    correlation_id = f"pipeline-evidence-{run_id}"

    class ModelOnlyExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Fabricated trend",
                sources=[
                    {
                        "url": "https://example.com/report",
                        "title": "Industry report",
                        "published_at": "2026-08-17T00:00:00Z",
                        "searched_at": "2026-08-17T02:00:00Z",
                    }
                ],
                summary="Fabricated trend",
                correlation_id=correlation_id,
                evidence=[],
            )

    await run_pipeline_cycle(
        SessionLocal, executor=ModelOnlyExecutor(), worker_id="worker-model-only", limit=1
    )
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        output = await db.scalar(select(PipelineOutput).where(PipelineOutput.run_id == run_id))
        decision = await db.scalar(
            select(DashboardDecision).where(DashboardDecision.run_id == run_id)
        )
        assert run is not None and run.status == "failed"
        assert run.error_code == "web_evidence_provider_contract_missing"
        assert output is None
        assert decision is None


async def test_web_research_claimed_source_without_matching_evidence_fails() -> None:
    run_id = await _queued_run()
    correlation_id = f"pipeline-evidence-{run_id}"

    class MismatchedEvidenceExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Trend with unrelated evidence",
                sources=[
                    {
                        "url": "https://claims.example.com/report",
                        "title": "Claimed report",
                        "published_at": "2026-08-17T00:00:00Z",
                        "searched_at": "2026-08-17T02:00:00Z",
                    }
                ],
                summary="Mismatched trend",
                correlation_id=correlation_id,
                evidence=[_evidence("https://real.example.com/report", correlation_id)],
            )

    await run_pipeline_cycle(
        SessionLocal,
        executor=MismatchedEvidenceExecutor(),
        worker_id="worker-mismatch",
        limit=1,
    )
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        output = await db.scalar(select(PipelineOutput).where(PipelineOutput.run_id == run_id))
        assert run is not None and run.status == "failed"
        assert run.error_code == "web_evidence_mismatch"
        assert output is None


async def test_worker_error_codes_are_sanitized_known_codes() -> None:
    run_id = await _queued_run()

    class LeakingExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            raise ValueError("upstream echoed prompt secret /var/private/key.pem")

    await run_pipeline_cycle(
        SessionLocal, executor=LeakingExecutor(), worker_id="worker-leak", limit=1
    )
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        assert run is not None and run.status == "failed"
        # Unknown ValueError text must collapse to a known sanitized code.
        assert run.error_code == "structured_output_invalid"
        assert "secret" not in (run.error_code or "")


async def test_cross_run_evidence_cannot_back_a_claim() -> None:
    run_id = await _queued_run()
    correlation_id = f"pipeline-evidence-{run_id}"

    class CrossRunEvidenceExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Trend backed by another run",
                sources=[
                    {
                        "url": "https://example.com/report",
                        "title": "Industry report",
                        "published_at": "2026-08-17T00:00:00Z",
                        "searched_at": "2026-08-17T02:00:00Z",
                    }
                ],
                summary="Cross-run trend",
                correlation_id=correlation_id,
                evidence=[_evidence("https://example.com/report", "corr-run-9999")],
            )

    await run_pipeline_cycle(
        SessionLocal,
        executor=CrossRunEvidenceExecutor(),
        worker_id="worker-cross-run",
        limit=1,
    )
    async with SessionLocal() as db:
        run = await db.get(PipelineRun, run_id)
        assert run is not None and run.status == "failed"
        assert run.error_code == "web_evidence_mismatch"
