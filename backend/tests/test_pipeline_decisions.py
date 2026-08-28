import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    DashboardDecision,
    DecisionAction,
    DeliveryOutbox,
    DeliveryTarget,
    MemoryRecord,
    NotificationOutbox,
    PipelineOutput,
    PipelineRun,
    PipelineTask,
    ChannelIdentity,
    RoutingRule,
    User,
    OrganizationMembership,
    Role,
)
from app.auth.security import hash_password
from app.services.pipeline_approval import is_authorized_approver
from app.services.pipeline_executor import PipelineExecutionResult, run_pipeline_cycle
from app.services.web_evidence import WebEvidence

pytestmark = pytest.mark.asyncio


def _evidence(correlation_id: str) -> WebEvidence:
    return WebEvidence(
        provider="exa",
        url="https://example.com/source",
        title="Source",
        published_at=datetime(2026, 8, 17, tzinfo=UTC),
        searched_at=datetime(2026, 8, 17, 2, 0, tzinfo=UTC),
        correlation_id=correlation_id,
    )


async def _pending_decision(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    run_key: str = "decision-probe-run",
) -> dict:
    task_response = await client.post(
        "/api/pipeline/tasks",
        headers=headers,
        json={
            "confirmed": True,
            "title": "Approval probe",
            "prompt": "search current trends",
            "task_type": "web_research",
            "schedule": None,
            "timezone": "Asia/Shanghai",
            "input_sources": ["web"],
            "output_format": "markdown",
        },
    )
    assert task_response.status_code == 201
    run_response = await client.post(
        f"/api/pipeline/tasks/{task_response.json()['id']}/run",
        headers={**headers, "Idempotency-Key": run_key},
    )
    assert run_response.status_code == 202

    class FakeExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            correlation_id = f"decision-evidence-{run_key}"
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Approved knowledge\n\n[source](https://example.com/source)",
                sources=[
                    {
                        "url": "https://example.com/source",
                        "title": "Source",
                        "published_at": "2026-08-17T00:00:00Z",
                        "searched_at": "2026-08-17T02:00:00Z",
                    }
                ],
                summary="A reviewable fact",
                correlation_id=correlation_id,
                evidence=[_evidence(correlation_id)],
            )

    await run_pipeline_cycle(
        SessionLocal, executor=FakeExecutor(), worker_id="decision-worker", limit=1
    )
    decisions = await client.get("/api/dashboard/decisions", headers=headers)
    assert decisions.status_code == 200
    return next(
        item
        for item in decisions.json()["items"]
        if item["task_id"] == task_response.json()["id"]
    )


async def test_approve_creates_traceable_memory_in_the_same_owner_scope(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers)
    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/approve",
        headers={**admin_headers, "Idempotency-Key": "approve-once"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    replay = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/approve",
        headers={**admin_headers, "Idempotency-Key": "approve-once"},
    )
    assert replay.status_code == 200
    conflict = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/approve",
        headers={**admin_headers, "Idempotency-Key": "approve-again"},
    )
    assert conflict.status_code == 409
    async with SessionLocal() as db:
        memory = await db.scalar(
            select(MemoryRecord).where(
                MemoryRecord.metadata_["pipeline_decision_id"].as_string()
                == str(decision["id"])
            )
        )
        assert memory is not None
        assert memory.type == "decision"
    assert memory.metadata_["pipeline_output_id"] == str(decision["output_id"])


async def test_approve_records_optional_comment_and_audit_timestamp(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers, run_key="approve-comment-run")
    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/approve",
        headers={**admin_headers, "Idempotency-Key": "approve-comment"},
        json={"comment": "已核对来源，可以归档"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["approval_comment"] == "已核对来源，可以归档"
    assert body["approver_user_id"] is not None
    assert body["decided_at"] is not None


async def test_completed_run_creates_one_pending_decision_notification(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(
        client, admin_headers, run_key="pending-decision-notification"
    )
    async with SessionLocal() as db:
        stored = await db.get(DashboardDecision, decision["id"])
        notification = await db.scalar(
            select(NotificationOutbox).where(
                NotificationOutbox.event_key == f"decision-pending:{decision['id']}"
            )
        )
    assert stored is not None
    assert stored.approver_user_id == stored.user_id
    assert notification is not None
    assert notification.event_type == "pipeline.decision.pending"
    assert notification.payload["recipient_user_ids"] == [stored.user_id]


async def test_task_creation_rejects_missing_member_approver(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/pipeline/tasks",
        headers=admin_headers,
        json={
            "confirmed": True,
            "title": "Invalid approver",
            "prompt": "Summarize information",
            "task_type": "general",
            "schedule": None,
            "timezone": "Asia/Shanghai",
            "input_sources": [],
            "output_format": "markdown",
            "approval_required": True,
            "approval_assignee_type": "member",
            "approval_assignee_id": 999999,
        },
    )
    assert response.status_code == 422


async def test_member_approval_does_not_implicitly_authorize_task_creator() -> None:
    async with SessionLocal() as db:
        owner = await db.scalar(select(User).where(User.username == "admin"))
        role = await db.scalar(select(Role).where(Role.name == "admin"))
        assert owner is not None and role is not None
        assignee = User(
            username=f"approval-member-{uuid4().hex[:8]}",
            email=f"approval-member-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("approval-test-password"),
            role_id=role.id,
            default_organization_id=owner.default_organization_id,
        )
        db.add(assignee)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=owner.default_organization_id,
                user_id=assignee.id,
                role_id=role.id,
            )
        )
        task = PipelineTask(
            organization_id=owner.default_organization_id,
            user_id=owner.id,
            title="Assigned approval",
            prompt="Review information",
            task_type="general",
            timezone="Asia/Shanghai",
            input_sources=[],
            output_format="markdown",
            status="ready",
            approval_required=True,
            approval_assignee_type="member",
            approval_assignee_id=assignee.id,
        )
        db.add(task)
        await db.flush()

        assert await is_authorized_approver(db, task=task, user_id=owner.id) is False
        assert await is_authorized_approver(db, task=task, user_id=assignee.id) is True
        await db.rollback()


async def test_reject_records_required_reason_without_creating_memory(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers, run_key="reject-reason-run")
    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": "reject-reason"},
        json={"reason": "来源时效不足", "reason_type": "other"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "changes_requested"
    assert body["rejection_reason"] == "来源时效不足"
    assert body["reason_type"] == "other"
    assert body["regeneration_run_id"] is not None
    assert body["approver_user_id"] is not None
    assert body["decided_at"] is not None
    async with SessionLocal() as db:
        memory = await db.scalar(
            select(MemoryRecord).where(
                MemoryRecord.metadata_["pipeline_decision_id"].as_string()
                == str(decision["id"])
            )
        )
    assert memory is None


async def test_reject_requires_a_non_empty_reason(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers, run_key="reject-empty-reason-run")
    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": "reject-empty-reason"},
        json={"reason": " ", "reason_type": "other"},
    )
    assert response.status_code == 422


async def _decision_organization_id(decision: dict) -> int:
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, decision["task_id"])
        assert task is not None
        return task.organization_id


async def _feishu_delivery_target(
    organization_id: int, *, active: bool = True, routed: bool = True
) -> int:
    async with SessionLocal() as db:
        owner = await db.scalar(select(User).where(User.username == "admin"))
        assert owner is not None
        target = DeliveryTarget(
            organization_id=organization_id,
            provider="feishu",
            external_conversation_id=f"oc-decision-{uuid4().hex[:8]}",
            is_active=active,
        )
        db.add(target)
        await db.flush()
        if active and routed:
            identity = ChannelIdentity(
                organization_id=organization_id,
                provider="feishu",
                external_user_id=f"ou-decision-{uuid4().hex[:8]}",
                external_conversation_id=target.external_conversation_id,
            )
            db.add(identity)
            await db.flush()
            db.add(
                RoutingRule(
                    organization_id=organization_id,
                    channel_identity_id=identity.id,
                    delivery_target_id=target.id,
                    member_user_id=owner.id,
                    priority=10,
                )
            )
        await db.commit()
        return target.id


async def test_approve_creates_idempotent_feishu_delivery_outbox_rows(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers)
    organization_id = await _decision_organization_id(decision)
    target_id = await _feishu_delivery_target(organization_id)
    inactive_target_id = await _feishu_delivery_target(organization_id, active=False)

    for _ in range(2):  # second call replays the same action idempotency key
        response = await client.post(
            f"/api/dashboard/decisions/{decision['id']}/approve",
            headers={**admin_headers, "Idempotency-Key": "approve-delivery"},
        )
        assert response.status_code == 200

    async with SessionLocal() as db:
        owner_user_id = await db.scalar(select(User.id).where(User.username == "admin"))
        assert owner_user_id is not None
        active_target_ids = set(
            (
                await db.scalars(
                    select(DeliveryTarget.id)
                    .join(RoutingRule, RoutingRule.delivery_target_id == DeliveryTarget.id)
                    .where(
                        DeliveryTarget.organization_id == organization_id,
                        DeliveryTarget.provider == "feishu",
                        DeliveryTarget.is_active.is_(True),
                        RoutingRule.organization_id == organization_id,
                        RoutingRule.member_user_id == owner_user_id,
                        RoutingRule.enabled.is_(True),
                    )
                    .distinct()
                )
            ).all()
        )
        delivery_rows = list(
            (
                await db.scalars(
                    select(DeliveryOutbox).where(
                        DeliveryOutbox.organization_id == organization_id,
                        DeliveryOutbox.idempotency_key.startswith(
                            f"decision-approved:{decision['id']}:feishu:"
                        ),
                    )
                )
            ).all()
        )
    # One idempotent row per active feishu target of the organization.
    assert {row.delivery_target_id for row in delivery_rows} == active_target_ids
    row = next(item for item in delivery_rows if item.delivery_target_id == target_id)
    assert row.status == "pending"
    assert row.payload == {"decision_id": decision["id"], "status": "approved"}
    assert row.idempotency_key == f"decision-approved:{decision['id']}:feishu:{target_id}"
    assert all(item.delivery_target_id != inactive_target_id for item in delivery_rows)


async def test_reject_creates_changes_requested_feishu_delivery_outbox_row(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers)
    target_id = await _feishu_delivery_target(await _decision_organization_id(decision))

    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": "reject-delivery"},
        json={"reason": "No longer needed", "reason_type": "no_need"},
    )
    assert response.status_code == 200

    async with SessionLocal() as db:
        row = await db.scalar(
            select(DeliveryOutbox).where(
                DeliveryOutbox.idempotency_key
                == f"decision-changes-requested:{decision['id']}:feishu:{target_id}"
            )
        )
        assert row is not None
        assert row.payload == {
            "decision_id": decision["id"],
            "status": "changes_requested",
            "reason_type": "no_need",
            "regeneration_run_id": response.json()["regeneration_run_id"],
        }


async def test_decision_delivery_is_limited_to_owner_routes(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers)
    organization_id = await _decision_organization_id(decision)
    unrouted_target_id = await _feishu_delivery_target(organization_id, routed=False)

    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/approve",
        headers={**admin_headers, "Idempotency-Key": "approve-owner-route-only"},
    )
    assert response.status_code == 200, response.text

    async with SessionLocal() as db:
        row = await db.scalar(
            select(DeliveryOutbox).where(
                DeliveryOutbox.delivery_target_id == unrouted_target_id,
                DeliveryOutbox.idempotency_key.startswith(
                    f"decision-approved:{decision['id']}:feishu:"
                ),
            )
        )
    assert row is None


async def test_request_changes_preserves_old_output_and_creates_new_run(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers)
    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/request-changes",
        headers={**admin_headers, "Idempotency-Key": "changes-once"},
        json={"reason": "Add a second independent source"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "changes_requested"
    assert updated["regeneration_run_id"] != decision["run_id"]
    async with SessionLocal() as db:
        old_output = await db.get(PipelineOutput, decision["output_id"])
        new_run = await db.get(PipelineRun, updated["regeneration_run_id"])
        old_decision = await db.get(DashboardDecision, decision["id"])
        assert old_output is not None
        assert new_run is not None and new_run.status == "queued"
        assert old_decision is not None and old_decision.change_request


@pytest.mark.parametrize("reason_type", ["no_need", "other", "regenerate"])
async def test_reject_creates_a_regeneration_run_for_every_reason_type(
    client: AsyncClient,
    admin_headers: dict[str, str],
    reason_type: str,
) -> None:
    decision = await _pending_decision(client, admin_headers)

    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": f"reject-{reason_type}"},
        json={"reason": "No longer needed", "reason_type": reason_type},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "changes_requested"
    assert response.json()["change_request"] == "No longer needed"
    assert response.json()["regeneration_run_id"] != decision["run_id"]
    replay = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": f"reject-{reason_type}"},
        json={"reason": "No longer needed", "reason_type": reason_type},
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "changes_requested"

    async with SessionLocal() as db:
        action = await db.scalar(
            select(DecisionAction).where(DecisionAction.decision_id == decision["id"])
        )
        new_run = await db.get(PipelineRun, response.json()["regeneration_run_id"])
        assert action is not None and action.action == "regenerate"
        assert new_run is not None and new_run.status == "queued"


async def test_reject_reason_is_included_in_the_regeneration_prompt(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(
        client, admin_headers, run_key="reject-feedback-run"
    )
    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": "reject-feedback"},
        json={"reason": "补充最近 30 天的独立来源", "reason_type": "other"},
    )
    assert response.status_code == 200, response.text
    regeneration_run_id = response.json()["regeneration_run_id"]

    seen_prompts: list[str] = []

    class FeedbackExecutor:
        async def execute(self, task: PipelineTask) -> PipelineExecutionResult:
            seen_prompts.append(task.prompt)
            correlation_id = "reject-feedback-evidence"
            return PipelineExecutionResult(
                title=task.title,
                markdown="# Regenerated knowledge",
                sources=[
                    {
                        "url": "https://example.com/source",
                        "title": "Source",
                        "published_at": "2026-08-17T00:00:00Z",
                        "searched_at": "2026-08-17T02:00:00Z",
                    }
                ],
                summary="Regenerated from feedback",
                correlation_id=correlation_id,
                evidence=[_evidence(correlation_id)],
            )

    await run_pipeline_cycle(
        SessionLocal,
        executor=FeedbackExecutor(),
        worker_id="reject-feedback-worker",
        limit=1,
    )

    assert seen_prompts == [
        "search current trends\n\nRegeneration feedback:\n补充最近 30 天的独立来源"
    ]
    async with SessionLocal() as db:
        regenerated_decision = await db.scalar(
            select(DashboardDecision).where(
                DashboardDecision.run_id == regeneration_run_id
            )
        )
    assert regenerated_decision is not None
    assert regenerated_decision.status == "pending"


async def test_reject_with_regenerate_reason_creates_a_new_run(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers)

    response = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": "reject-regenerate"},
        json={"reason": "Use a newer source", "reason_type": "regenerate"},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "changes_requested"
    assert updated["regeneration_run_id"] != decision["run_id"]
    async with SessionLocal() as db:
        action = await db.scalar(
            select(DecisionAction).where(DecisionAction.decision_id == decision["id"])
        )
        new_run = await db.get(PipelineRun, updated["regeneration_run_id"])
    assert action is not None and action.action == "regenerate"
    assert new_run is not None and new_run.status == "queued"


async def test_failed_regeneration_can_be_retried_with_a_fresh_action_key(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers, run_key="failed-regen-retry")
    first = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": "failed-regen-first"},
        json={"reason": "补充当天待办详情", "reason_type": "regenerate"},
    )
    assert first.status_code == 200
    first_run_id = first.json()["regeneration_run_id"]
    async with SessionLocal() as db:
        first_run = await db.get(PipelineRun, first_run_id)
        assert first_run is not None
        first_run.status = "failed"
        first_run.error_code = "upstream_timeout"
        await db.commit()

    retry = await client.post(
        f"/api/dashboard/decisions/{decision['id']}/reject",
        headers={**admin_headers, "Idempotency-Key": "failed-regen-retry"},
        json={"reason": "补充当天待办详情", "reason_type": "regenerate"},
    )

    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "changes_requested"
    assert retry.json()["regeneration_run_id"] != first_run_id
    async with SessionLocal() as db:
        retry_run = await db.get(PipelineRun, retry.json()["regeneration_run_id"])
        assert retry_run is not None
        assert retry_run.status == "queued"
        assert "补充当天待办详情" in (retry_run.prompt_override or "")


async def test_decision_list_applies_status_and_limit(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers)
    await client.post(
        f"/api/dashboard/decisions/{decision['id']}/approve",
        headers={**admin_headers, "Idempotency-Key": "approve-for-filter"},
    )
    pending_decision = await _pending_decision(
        client, admin_headers, run_key="decision-probe-run-pending"
    )

    approved = await client.get(
        "/api/dashboard/decisions?status=approved&limit=1", headers=admin_headers
    )
    pending = await client.get(
        "/api/dashboard/decisions?status=pending&limit=1", headers=admin_headers
    )

    assert approved.status_code == 200
    assert [item["id"] for item in approved.json()["items"]] == [decision["id"]]
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()["items"]] == [pending_decision["id"]]
    limited = await client.get("/api/dashboard/decisions?limit=1", headers=admin_headers)
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 1


async def test_concurrent_approve_with_same_key_replays_without_duplicate_side_effects(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    decision = await _pending_decision(client, admin_headers)
    responses = await asyncio.gather(
        client.post(
            f"/api/dashboard/decisions/{decision['id']}/approve",
            headers={**admin_headers, "Idempotency-Key": "concurrent-approve"},
        ),
        client.post(
            f"/api/dashboard/decisions/{decision['id']}/approve",
            headers={**admin_headers, "Idempotency-Key": "concurrent-approve"},
        ),
        return_exceptions=True,
    )
    assert all(isinstance(response, Response) for response in responses), responses
    assert [response.status_code for response in responses] == [200, 200]
    assert {response.json()["status"] for response in responses} == {"approved"}

    async with SessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count(DecisionAction.id)).where(
                    DecisionAction.decision_id == decision["id"]
                )
            )
        ) == 1
        assert (
            await db.scalar(
                select(func.count(MemoryRecord.memory_id)).where(
                    MemoryRecord.metadata_["pipeline_decision_id"].as_string()
                    == str(decision["id"])
                )
            )
        ) == 1
        assert (
            await db.scalar(
                select(func.count(NotificationOutbox.id)).where(
                    NotificationOutbox.event_key == f"decision-approved:{decision['id']}"
                )
            )
        ) == 1
