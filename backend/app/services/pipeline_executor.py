from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.models import (
    DashboardDecision,
    OrganizationMembership,
    PipelineOutput,
    PipelineRun,
    PipelineTask,
)
from app.services.hermes_client import (
    HermesClientRouter,
    HermesRequestContext,
    HermesUpstreamError,
    hermes_client,
    hermes_knowledge_client,
)
from app.services.object_storage import LocalPrivateObjectStorage
from app.services.pipeline_approval import enqueue_pending_decision_notifications
from app.services.pipeline_scheduler import schedule_due_pipeline_tasks
from app.services.web_evidence import (
    WebEvidence,
    WebEvidenceRejected,
    evidence_for_run,
    validate_web_evidence,
)


@dataclass(frozen=True)
class PipelineExecutionResult:
    title: str
    markdown: str
    sources: list[dict]
    summary: str
    correlation_id: str = ""
    evidence: list[WebEvidence] = field(default_factory=list)


class PipelineTaskExecutor(Protocol):
    async def execute(self, task: PipelineTask) -> PipelineExecutionResult: ...


class HermesPipelineExecutor:
    def __init__(
        self,
        router: HermesClientRouter,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._router = router
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
        session_id = f"pipeline-task-{task.id}-{uuid4().hex}"
        correlation_id = uuid4().hex
        context = HermesRequestContext(
            user_id=task.user_id,
            organization_id=str(task.organization_id),
            session_id=session_id,
            correlation_id=correlation_id,
        )
        prompt = (
            "Execute the following platform task. Return exactly one JSON object with keys "
            "title, markdown, summary, and sources. "
        )
        if task.task_type == "web_research":
            prompt += (
                "sources must be an array whose objects contain an exact url copied from an "
                "actual web search tool result of this run. The platform will attach "
                "provider-owned title and timestamp metadata; do not invent source metadata. "
                "Every url must come from an actual web search tool result of this run. Do not "
                "claim a web trend without a source. "
            )
        else:
            prompt += "This is a non-web task, so sources must be an empty array. "
            if _is_feishu_weekly_task_report(task.prompt):
                prompt += _feishu_weekly_task_report_instruction(self._now_provider())
            elif "飞书" in task.prompt and any(term in task.prompt for term in ("待办", "任务")):
                prompt += (
                    'Read Feishu tasks by calling lark_cli_execute exactly with argv ["task", '
                    '"+get-my-tasks"]. Do not call lark_cli_schema or lark_cli_help. Do not add '
                    "--as, --format, --json, or --jq because the controlled wrapper adds identity "
                    "and JSON formatting. Summarize the returned tasks without changing any "
                    "Feishu data. "
                )
        prompt += "Task:\n" + task.prompt
        body = await self._router.client_for("agent").create_openai_response(
            prompt, context=context
        )
        text = _openai_output_text(body)
        payload = _parse_structured_output(text)
        if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
            raise ValueError("structured_output_invalid")
        evidence = _collect_response_evidence(body, correlation_id=correlation_id)
        return PipelineExecutionResult(
            title=str(payload.get("title") or task.title),
            markdown=str(payload.get("markdown") or ""),
            sources=[item for item in payload["sources"] if isinstance(item, dict)],
            summary=str(payload.get("summary") or ""),
            correlation_id=correlation_id,
            evidence=evidence,
        )


_WEB_SEARCH_OUTPUT_ITEM_TYPES = frozenset(
    {"web_search_call", "web.search.call", "tool.web_search"}
)
_WEB_SEARCH_FUNCTION_NAMES = frozenset({"web_search", "web_search_tool"})

#: Closed set of sanitized error codes executors may surface on a run row.
SANITIZED_EXECUTOR_ERROR_CODES = frozenset(
    {
        "execution_unavailable",
        "structured_output_invalid",
        "sources_required",
        "web_evidence_provider_contract_missing",
        "web_evidence_mismatch",
    }
)


def _collect_response_evidence(
    body: dict[str, object], *, correlation_id: str
) -> list[WebEvidence]:
    """Collect validated evidence from provider response output items.

    Only recognized web-search tool item types contribute; model text never
    enters this path. Unrecognized shapes simply yield no evidence and the
    run-level cross-validation fails closed.
    """
    output = body.get("output")
    if not isinstance(output, list):
        return []
    evidence: list[WebEvidence] = []
    now = datetime.now(UTC)
    web_call_ids = {
        item.get("call_id")
        for item in output
        if isinstance(item, dict)
        and item.get("type") == "function_call"
        and item.get("name") in _WEB_SEARCH_FUNCTION_NAMES
        and isinstance(item.get("call_id"), str)
    }
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type") or item.get("event")
        results: object = item.get("results")
        provider = item.get("provider")
        if item_type == "function_call_output" and item.get("call_id") in web_call_ids:
            raw_output = item.get("output")
            tool_payload = _parse_tool_result(raw_output)
            data = tool_payload.get("data") if isinstance(tool_payload, dict) else None
            results = data.get("web") if isinstance(data, dict) else None
        elif not isinstance(item_type, str) or item_type not in _WEB_SEARCH_OUTPUT_ITEM_TYPES:
            continue
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            enriched = dict(result)
            enriched.setdefault("correlation_id", correlation_id)
            if isinstance(provider, str):
                enriched.setdefault("provider", provider)
            try:
                evidence.append(
                    validate_web_evidence(enriched, correlation_id=correlation_id, now=now)
                )
            except WebEvidenceRejected:
                continue
    return evidence


def _parse_tool_result(raw_output: object) -> dict[str, object]:
    """Parse JSON from Hermes' untrusted-tool-result envelope."""
    if isinstance(raw_output, dict):
        return raw_output
    if not isinstance(raw_output, str):
        raw_output = str(raw_output)
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw_output):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw_output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("data" in parsed or "success" in parsed):
            return parsed
    return {}


def _openai_output_text(body: dict[str, object]) -> str:
    output = body.get("output")
    if not isinstance(output, list):
        raise ValueError("structured_output_invalid")
    chunks: list[str] = []
    for message in output:
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for item in message["content"]:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
    text = "".join(chunks).strip()
    if not text:
        raise ValueError("structured_output_invalid")
    return text


def _parse_structured_output(text: str) -> dict[str, object]:
    """Accept a JSON object or a JSON code fence, never arbitrary prose."""
    decoder = json.JSONDecoder()
    candidates = [text]
    candidates.extend(re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE))
    for candidate in candidates:
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if (
                isinstance(parsed, dict)
                and isinstance(parsed.get("sources"), list)
                and all(key in parsed for key in ("title", "markdown", "summary"))
            ):
                return parsed
    raise ValueError("structured_output_invalid")


def build_pipeline_executor(settings: Settings | None = None) -> PipelineTaskExecutor | None:
    resolved = settings or get_settings()
    if not resolved.hermes_use_http:
        return None
    return HermesPipelineExecutor(
        HermesClientRouter(agent=hermes_client, knowledge=hermes_knowledge_client)
    )


async def claim_pipeline_runs(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int = 10,
    run_id: int | None = None,
) -> list[PipelineRun]:
    statement = (
        select(PipelineRun)
        .where(PipelineRun.status == "queued")
        .order_by(PipelineRun.created_at, PipelineRun.id)
    )
    if run_id is not None:
        statement = statement.where(PipelineRun.id == run_id).limit(1)
    else:
        statement = statement.limit(limit)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    rows = list((await db.scalars(statement)).all())
    now = datetime.now(UTC)
    lease = timedelta(seconds=get_settings().pipeline_worker_lease_seconds)
    for row in rows:
        row.status = "running"
        row.claimed_by = worker_id
        row.lease_expires_at = now + lease
    await db.flush()
    return rows


async def recover_stale_pipeline_runs(
    db: AsyncSession, *, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    rows = list(
        (
            await db.scalars(
                select(PipelineRun).where(
                    PipelineRun.status == "running",
                    PipelineRun.lease_expires_at.is_not(None),
                    PipelineRun.lease_expires_at <= now,
                )
            )
        ).all()
    )
    for row in rows:
        row.attempt += 1
        row.claimed_by = None
        row.lease_expires_at = None
        if row.attempt >= get_settings().pipeline_worker_max_attempts:
            row.status = "failed"
            row.error_code = "max_attempts_exceeded"
            row.completed_at = now
        else:
            row.status = "queued"
    await db.flush()
    return len(rows)


def _valid_web_sources(sources: list[dict]) -> bool:
    return bool(sources) and all(
        isinstance(source.get("url"), str)
        and source["url"].strip()
        and source["url"].startswith(("https://", "http://"))
        for source in sources
    )


def cross_validated_web_sources(
    result: PipelineExecutionResult,
) -> tuple[list[dict], str | None]:
    """Cross-check model-claimed sources against provider evidence.

    Returns the persisted source payloads (built from validated evidence, not
    raw model JSON) and a failure error code, or ``(sources, None)`` on success.
    """
    if not _valid_web_sources(result.sources):
        return [], "sources_required"
    run_evidence = evidence_for_run(result.evidence, correlation_id=result.correlation_id)
    if not run_evidence:
        # Foreign-run evidence can never back this run's claims; only a fully
        # absent provider evidence channel counts as a missing contract.
        failure = (
            "web_evidence_mismatch" if result.evidence else "web_evidence_provider_contract_missing"
        )
        return [], failure
    evidence_by_url = {item.url: item for item in run_evidence}
    claimed_urls: list[str] = []
    for source in result.sources:
        url = source.get("url")
        if isinstance(url, str) and url in evidence_by_url:
            claimed_urls.append(url)
    if not claimed_urls or len(claimed_urls) < len(
        [s for s in result.sources if isinstance(s.get("url"), str)]
    ):
        return [], "web_evidence_mismatch"
    persisted: list[dict] = []
    for url in claimed_urls:
        persisted.append(evidence_by_url[url].as_source_dict())
    return persisted, None


def _cross_validate_web_sources(result: PipelineExecutionResult) -> str | None:
    _, failure = cross_validated_web_sources(result)
    return failure


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: int,
    worker_id: str,
    error_code: str,
) -> None:
    async with session_factory() as db:
        run = await db.get(PipelineRun, run_id)
        if run is not None and run.status == "running" and run.claimed_by == worker_id:
            run.status = "failed"
            run.error_code = error_code
            run.completed_at = datetime.now(UTC)
            run.lease_expires_at = None
            await db.commit()


async def _complete_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: int,
    worker_id: str,
    result: PipelineExecutionResult,
) -> None:
    async with session_factory() as db:
        run = await db.get(PipelineRun, run_id)
        if run is None or run.status != "running" or run.claimed_by != worker_id:
            return
        task = await db.get(PipelineTask, run.task_id)
        if task is None or task.deleted_at is not None or task.status == "deleted":
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            run.lease_expires_at = None
            await db.commit()
            return
        if task.task_type == "web_research":
            persisted_sources, failure = cross_validated_web_sources(result)
            if failure is not None:
                run.status = "failed"
                run.error_code = failure
                run.completed_at = datetime.now(UTC)
                run.lease_expires_at = None
                await db.commit()
                return
        else:
            persisted_sources = result.sources
        version = 1 + (
            await db.scalar(
                select(PipelineOutput.version)
                .where(PipelineOutput.task_id == task.id)
                .order_by(PipelineOutput.version.desc())
                .limit(1)
            )
            or 0
        )
        content = result.markdown.encode("utf-8")
        object_key = (
            f"pipeline/{task.organization_id}/{task.user_id}/{task.id}/"
            f"run-{run.id}-v{version}.md"
        )
        await LocalPrivateObjectStorage(get_settings().upload_dir).put_bytes(object_key, content)
        output = PipelineOutput(
            organization_id=task.organization_id,
            user_id=task.user_id,
            task_id=task.id,
            run_id=run.id,
            version=version,
            title=result.title,
            markdown=result.markdown,
            object_key=object_key,
            content_sha256=hashlib.sha256(content).hexdigest(),
            sources=persisted_sources,
        )
        db.add(output)
        await db.flush()
        if task.approval_required:
            decision = DashboardDecision(
                organization_id=task.organization_id,
                user_id=task.user_id,
                task_id=task.id,
                run_id=run.id,
                output_id=output.id,
                status="pending",
                revision=1,
                title=result.title,
                summary=result.summary,
            )
            db.add(decision)
            await db.flush()
            await enqueue_pending_decision_notifications(
                db, task=task, decision=decision
            )
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.lease_expires_at = None
        await db.commit()


async def _execute_claimed_pipeline_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    executor: PipelineTaskExecutor,
    worker_id: str,
    run_id: int,
) -> None:
    async with session_factory() as db:
        run = await db.get(PipelineRun, run_id)
        task = await db.get(PipelineTask, run.task_id) if run is not None else None
        membership = (
            await db.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == task.organization_id,
                    OrganizationMembership.user_id == task.user_id,
                    OrganizationMembership.is_active.is_(True),
                )
            )
            if task is not None
            else None
        )
    if task is None or membership is None:
        await _mark_failed(session_factory, run_id, worker_id, "owner_membership_inactive")
        return
    original_prompt = task.prompt
    if run is not None and run.prompt_override:
        # Feedback is scoped to this run. Restore the persisted task prompt
        # after execution so regeneration never rewrites the task definition.
        task.prompt = run.prompt_override
    try:
        result = await executor.execute(task)
    except HermesUpstreamError:
        await _mark_failed(session_factory, run_id, worker_id, "hermes_unavailable")
        return
    except ValueError as exc:
        # Only a closed set of sanitized error codes may reach the run row;
        # arbitrary exception text (provider echoes, paths) is collapsed.
        code = str(exc)[:120]
        if code not in SANITIZED_EXECUTOR_ERROR_CODES:
            code = "structured_output_invalid"
        await _mark_failed(session_factory, run_id, worker_id, code)
        return
    finally:
        task.prompt = original_prompt
    await _complete_run(session_factory, run_id=run_id, worker_id=worker_id, result=result)


def _is_feishu_weekly_task_report(prompt: str) -> bool:
    return (
        "飞书" in prompt
        and "周报" in prompt
        and any(term in prompt for term in ("待办", "任务"))
    )


def _feishu_weekly_task_report_instruction(now: datetime) -> str:
    """Build the fixed data contract for a Feishu task weekly report."""
    local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    week_start = (local_now - timedelta(days=local_now.weekday())).date()
    week_end = week_start + timedelta(days=6)
    return (
        "This is a Feishu task weekly report. Its reporting interval is the current "
        f"natural week in Asia/Shanghai: {week_start} 00:00:00 through "
        f"{week_end} 23:59:59. Read Feishu tasks by calling lark_cli_execute exactly "
        'with argv ["task", "+get-my-tasks", "--created_at", '
        f'"{week_start}", "--page-all"]. Do not call lark_cli_schema or '
        "lark_cli_help. Do not add --as, --format, --json, or --jq because the "
        "controlled wrapper adds identity and JSON formatting. Do not pass "
        "--complete=false: include both completed and incomplete tasks. Summarize "
        "only tasks whose created time is within the reporting interval, and state "
        "that the report is counted by task creation time. Do not change any Feishu data. "
    )


async def run_pipeline_run_now(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    executor: PipelineTaskExecutor | None,
    worker_id: str,
    run_id: int,
) -> bool:
    """Claim and execute exactly one queued run.

    Chat-triggered execution must never run a generic worker cycle, because a
    generic cycle could claim a queued task belonging to a different request.
    """
    async with session_factory() as db:
        claimed = await claim_pipeline_runs(db, worker_id=worker_id, run_id=run_id)
        await db.commit()
    if not claimed:
        return False
    if executor is None:
        await _mark_failed(session_factory, run_id, worker_id, "execution_unavailable")
        return True
    await _execute_claimed_pipeline_run(
        session_factory,
        executor=executor,
        worker_id=worker_id,
        run_id=run_id,
    )
    return True


async def run_pipeline_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    executor: PipelineTaskExecutor,
    worker_id: str,
    limit: int = 10,
) -> int:
    async with session_factory() as db:
        await recover_stale_pipeline_runs(db)
        await schedule_due_pipeline_tasks(db)
        claimed = await claim_pipeline_runs(db, worker_id=worker_id, limit=limit)
        await db.commit()
    for snapshot in claimed:
        await _execute_claimed_pipeline_run(
            session_factory,
            executor=executor,
            worker_id=worker_id,
            run_id=snapshot.id,
        )
    return len(claimed)
