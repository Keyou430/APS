from __future__ import annotations

import json

import httpx
import pytest

from scripts.verify_rag_worker_recovery import load_state, wait_for_ingestion


def test_load_state_rejects_missing_recovery_identity(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"entry_id": "4", "marker": ""}), encoding="utf-8")

    with pytest.raises(ValueError, match="state is invalid"):
        load_state(path)


@pytest.mark.asyncio
async def test_wait_for_ingestion_observes_recovered_ready_status() -> None:
    statuses = iter(("queued", "processing", "ready"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"status": next(statuses)})

    async with httpx.AsyncClient(
        base_url="http://rag.test", transport=httpx.MockTransport(handler)
    ) as client:
        status = await wait_for_ingestion(
            client,
            entry_id=7,
            headers={"Authorization": "Bearer test-token"},
            timeout_seconds=1,
            poll_seconds=0,
        )

    assert status == "ready"
