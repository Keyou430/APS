"""Phase C1 delivery outbox contract tests (fake transport only).

The fake HTTP transport proves the adapter/worker contract: token handling,
light payload, sanitized error codes, retry/dead-letter, idempotency, claim
isolation and lease recovery. Real Feishu send/read-back requires the
authorized test tenant (C5) and is NOT claimed by these tests.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.database import SessionLocal
from app.models import DeliveryOutbox, DeliveryTarget, OrganizationMembership
from app.services.feishu_delivery import (
    FeishuDeliveryAdapter,
    FeishuDeliveryError,
    build_feishu_delivery_adapter,
    feishu_configuration_status,
)
from app.services.delivery_outbox_worker import (
    claim_delivery_outbox,
    enqueue_channel_delivery,
    run_delivery_cycle,
    recover_stale_delivery_claims,
)

pytestmark = pytest.mark.asyncio


class FakeRouter:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.token_calls = 0
        self.send_status = 200
        self.send_body: dict = {"code": 0, "msg": "success", "data": {"message_id": "om-feishu-1"}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        self.requests.append((request.method, str(request.url), body))
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            self.token_calls += 1
            if self.send_status == 401:
                return httpx.Response(400, json={"code": 99991663, "msg": "app secret invalid"})
            return httpx.Response(
                200, json={"code": 0, "msg": "ok", "tenant_access_token": "t-xyz", "expire": "7200"}
            )
        if request.url.path.endswith("/im/v1/messages"):
            if self.send_status != 200:
                return httpx.Response(
                    self.send_status, json={"code": 230002, "msg": "has no permission"}
                )
            return httpx.Response(200, json=self.send_body)
        return httpx.Response(404, json={"code": 404, "msg": "not found"})


def _adapter(router: FakeRouter) -> FeishuDeliveryAdapter:
    return FeishuDeliveryAdapter(
        app_id="cli_test",
        app_secret="secret-value-never-logged",
        transport=httpx.MockTransport(router.handler),
    )


async def _feishu_target(organization_id: int, *, conversation: str | None = None) -> DeliveryTarget:
    if conversation is None:
        conversation = f"oc-target-{uuid4().hex[:8]}"
    async with SessionLocal() as db:
        target = DeliveryTarget(
            organization_id=organization_id,
            provider="feishu",
            external_conversation_id=conversation,
        )
        db.add(target)
        await db.commit()
        await db.refresh(target)
        return target


async def _org_id() -> int:
    async with SessionLocal() as db:
        membership = await db.scalar(select(OrganizationMembership).limit(1))
        assert membership is not None
        return membership.organization_id


async def test_adapter_sends_light_notification_and_caches_token() -> None:
    router = FakeRouter()
    adapter = _adapter(router)
    organization_id = await _org_id()

    async with SessionLocal() as db:
        target = await db.get(DeliveryTarget, (await _feishu_target(organization_id)).id)

    first = await adapter.send(
        target,
        event_type="pipeline.decision.approved",
        payload={"decision_id": 42, "status": "approved"},
    )
    second = await adapter.send(
        target,
        event_type="pipeline.decision.approved",
        payload={"decision_id": 43, "status": "approved"},
    )

    assert first.external_message_id == "om-feishu-1"
    assert second.external_message_id == "om-feishu-1"
    # One token fetch for both sends.
    assert router.token_calls == 1
    send_requests = [r for r in router.requests if "/im/v1/messages?" in r[1]]
    assert len(send_requests) == 2
    method, url, body = send_requests[0]
    assert method == "POST"
    assert "receive_id_type=chat_id" in url
    assert body["receive_id"].startswith("oc-target-")
    content = json.loads(body["content"])
    # Light notification only: no model text, no secrets, no internal paths.
    assert "42" in content["text"] or "决策" in content["text"]
    assert "secret-value" not in body["content"]
    assert "prompt" not in body["content"]


async def test_adapter_maps_auth_failure_to_sanitized_code() -> None:
    router = FakeRouter()
    router.send_status = 401  # makes the token endpoint reject
    adapter = _adapter(router)
    organization_id = await _org_id()

    async with SessionLocal() as db:
        target = await db.get(DeliveryTarget, (await _feishu_target(organization_id)).id)

    with pytest.raises(FeishuDeliveryError) as excinfo:
        await adapter.send(
            target,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 1, "status": "approved"},
        )
    assert excinfo.value.code == "feishu_auth_failed"
    assert "secret" not in str(excinfo.value)


async def test_enqueue_channel_delivery_is_idempotent() -> None:
    organization_id = await _org_id()
    target = await _feishu_target(organization_id)

    async with SessionLocal() as db:
        first = await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 7, "status": "approved"},
            idempotency_key="decision-approved:7:feishu:" + str(target.id),
        )
        second = await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 7, "status": "approved"},
            idempotency_key="decision-approved:7:feishu:" + str(target.id),
        )
        await db.commit()

    assert first.id == second.id
    # Finalize so later consumer cycles in this module never pick it up.
    async with SessionLocal() as db:
        row = await db.scalar(
            select(DeliveryOutbox).where(DeliveryOutbox.idempotency_key == first.idempotency_key)
        )
        assert row is not None
        row.status = "sent"
        await db.commit()


async def test_enqueue_unique_race_preserves_outer_transaction(monkeypatch) -> None:
    """A duplicate-key race must not roll back unrelated approval work."""
    organization_id = await _org_id()
    target = await _feishu_target(organization_id)
    key = "savepoint-race"

    async with SessionLocal() as winner_db:
        winner = await enqueue_channel_delivery(
            winner_db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 11, "status": "approved"},
            idempotency_key=key,
        )
        await winner_db.commit()

    async with SessionLocal() as db:
        marker = DeliveryOutbox(
            organization_id=organization_id,
            run_correlation_id=None,
            delivery_target_id=target.id,
            event_type="approval.audit.marker",
            idempotency_key="outer-transaction-marker",
            payload={"preserve": True},
        )
        db.add(marker)
        await db.flush()

        original_scalar = db.scalar
        scalar_calls = 0

        async def stale_preflight(statement, *args, **kwargs):
            nonlocal scalar_calls
            scalar_calls += 1
            if scalar_calls == 1:
                return None
            return await original_scalar(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", stale_preflight)
        duplicate = await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 11, "status": "approved"},
            idempotency_key=key,
        )
        marker.payload = {"preserve": True, "updated": True}
        await db.commit()

    assert duplicate.id == winner.id
    async with SessionLocal() as db:
        saved_marker = await db.scalar(
            select(DeliveryOutbox).where(
                DeliveryOutbox.idempotency_key == "outer-transaction-marker"
            )
        )
        assert saved_marker is not None
        assert saved_marker.payload == {"preserve": True, "updated": True}


async def test_consumer_claims_sends_and_marks_sent() -> None:
    organization_id = await _org_id()
    target = await _feishu_target(organization_id)
    async with SessionLocal() as db:
        await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 9, "status": "approved"},
            idempotency_key="consume-ok",
        )
        await db.commit()

    router = FakeRouter()
    processed = await run_delivery_cycle(
        SessionLocal,
        adapters={"feishu": _adapter(router)},
        worker_id="delivery-worker-a",
        # Other suites may leave due rows in the shared test DB; only this
        # suite's own row state is asserted.
        limit=50,
    )
    assert processed >= 1

    async with SessionLocal() as db:
        row = (
            await db.scalars(select(DeliveryOutbox).where(DeliveryOutbox.idempotency_key == "consume-ok"))
        ).one()
        assert row.status == "sent"
        assert row.external_message_id == "om-feishu-1"
        assert row.delivered_at is not None
        assert row.last_error is None


async def test_consumer_failures_retry_with_backoff_then_dead_letter() -> None:
    organization_id = await _org_id()
    target = await _feishu_target(organization_id)
    async with SessionLocal() as db:
        await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type="pipeline.decision.rejected",
            payload={"decision_id": 10, "status": "rejected"},
            idempotency_key="consume-fail",
        )
        await db.commit()

    class FailingAdapter:
        provider = "feishu"

        async def send(self, target, *, event_type, payload):
            raise FeishuDeliveryError("feishu_send_failed")

    max_attempts = 3
    base_now = datetime.now(UTC) + timedelta(hours=1)
    for attempt in range(max_attempts):
        # Jump the clock past the previous attempt's backoff so the retry
        # row becomes claimable again on the next cycle.
        await run_delivery_cycle(
            SessionLocal,
            adapters={"feishu": FailingAdapter()},
            worker_id="delivery-worker-fail",
            limit=5,
            now=base_now + timedelta(minutes=30 * attempt),
            max_attempts=max_attempts,
        )

    async with SessionLocal() as db:
        row = (
            await db.scalars(select(DeliveryOutbox).where(DeliveryOutbox.idempotency_key == "consume-fail"))
        ).one()
        assert row.status == "dead_letter"
        assert row.attempts == max_attempts
        assert row.last_error == "feishu_send_failed"
        assert row.delivered_at is None


async def test_consumer_without_adapter_reports_not_configured_without_fake_success() -> None:
    organization_id = await _org_id()
    target = await _feishu_target(organization_id)
    async with SessionLocal() as db:
        await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 11, "status": "approved"},
            idempotency_key="consume-unconfigured",
        )
        await db.commit()

    await run_delivery_cycle(
        SessionLocal, adapters={}, worker_id="delivery-worker-x", limit=5
    )

    async with SessionLocal() as db:
        row = (
            await db.scalars(
                select(DeliveryOutbox).where(DeliveryOutbox.idempotency_key == "consume-unconfigured")
            )
        ).one()
        assert row.status == "retry"
        assert row.last_error == "feishu_not_configured"
        assert row.delivered_at is None


async def test_two_consumers_claim_disjoint_rows() -> None:
    organization_id = await _org_id()
    target_a = await _feishu_target(organization_id, conversation="oc-a")
    target_b = await _feishu_target(organization_id, conversation="oc-b")
    async with SessionLocal() as db:
        await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target_a.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 1, "status": "approved"},
            idempotency_key="claim-1",
        )
        await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target_b.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 2, "status": "approved"},
            idempotency_key="claim-2",
        )
        await db.commit()

    async with SessionLocal() as db:
        first = await claim_delivery_outbox(db, worker_id="w1", limit=1)
        await db.commit()
    async with SessionLocal() as db:
        second = await claim_delivery_outbox(db, worker_id="w2", limit=1)
        await db.commit()

    assert len(first) == 1 and len(second) == 1
    assert first[0].id != second[0].id
    assert {row.status for row in (*first, *second)} == {"sending"}


async def test_stale_sending_claims_are_requeued() -> None:
    organization_id = await _org_id()
    target = await _feishu_target(organization_id)
    async with SessionLocal() as db:
        row = await enqueue_channel_delivery(
            db,
            organization_id=organization_id,
            delivery_target_id=target.id,
            event_type="pipeline.decision.approved",
            payload={"decision_id": 12, "status": "approved"},
            idempotency_key="stale-claim",
        )
        row.status = "sending"
        row.claimed_at = datetime.now(UTC) - timedelta(hours=1)
        await db.commit()

    async with SessionLocal() as db:
        recovered = await recover_stale_delivery_claims(
            db, now=datetime.now(UTC), lease_seconds=120, max_attempts=5
        )
        await db.commit()
    assert recovered == 1

    async with SessionLocal() as db:
        row = (
            await db.scalars(select(DeliveryOutbox).where(DeliveryOutbox.idempotency_key == "stale-claim"))
        ).one()
        assert row.status == "retry"
        assert row.last_error == "delivery_lease_expired"


def test_build_adapter_requires_credentials() -> None:
    assert build_feishu_delivery_adapter(Settings()) is None
    assert (
        build_feishu_delivery_adapter(Settings(feishu_app_id="cli_x", feishu_app_secret=None))
        is None
    )
    adapter = build_feishu_delivery_adapter(
        Settings(feishu_app_id="cli_x", feishu_app_secret="s")  # type: ignore[arg-type]
    )
    assert adapter is not None


async def test_delivery_status_can_report_worker_configuration_without_api_credentials() -> None:
    settings = Settings(feishu_delivery_configured=True)

    assert feishu_configuration_status(settings) == "configured"
    assert build_feishu_delivery_adapter(settings) is None


async def test_delivery_status_endpoint_reports_config_and_counts(
    client, admin_headers
) -> None:
    response = await client.get("/api/delivery/status", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["feishu"] in {"configured", "feishu_not_configured"}
    assert isinstance(body["outbox"], dict)
