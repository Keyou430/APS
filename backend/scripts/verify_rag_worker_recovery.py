from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import KnowledgeChunk, KnowledgeEntry, KnowledgeIngestionJob


async def login(client: httpx.AsyncClient) -> dict[str, str]:
    settings = get_settings()
    response = await client.post(
        "/api/auth/login",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def wait_for_ingestion(
    client: httpx.AsyncClient,
    *,
    entry_id: int,
    headers: dict[str, str],
    timeout_seconds: float,
    poll_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while True:
        response = await client.get(
            f"/api/knowledge/{entry_id}/ingestion", headers=headers
        )
        response.raise_for_status()
        status = str(response.json()["status"])
        if status in {"ready", "failed"}:
            return status
        if time.monotonic() >= deadline:
            raise TimeoutError(f"ingestion remained {status}")
        await asyncio.sleep(poll_seconds)


def load_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or type(value.get("entry_id")) is not int
        or not isinstance(value.get("marker"), str)
        or not value["marker"]
    ):
        raise ValueError("recovery state is invalid")
    return value


async def remaining_rows(entry_id: int) -> dict[str, int]:
    async with SessionLocal() as db:
        result: dict[str, int] = {}
        for label, model in (
            ("entry", KnowledgeEntry),
            ("job", KnowledgeIngestionJob),
            ("chunk", KnowledgeChunk),
        ):
            column = model.id if model is KnowledgeEntry else model.knowledge_entry_id
            result[label] = int(
                await db.scalar(
                    select(func.count()).select_from(model).where(column == entry_id)
                )
                or 0
            )
        return result


async def queue_while_worker_is_stopped(args: argparse.Namespace) -> dict[str, Any]:
    marker = f"faultrecovery{uuid4().hex}"
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout_seconds) as client:
        headers = await login(client)
        created = await client.post(
            "/api/knowledge",
            headers=headers,
            json={
                "type": "workflow_result",
                "title": "Synthetic worker recovery probe",
                "content": f"{marker} validates interrupted ingestion recovery.",
            },
        )
        created.raise_for_status()
        entry_id = int(created.json()["id"])
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(
            json.dumps({"entry_id": entry_id, "marker": marker}), encoding="utf-8"
        )
        queued = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=headers)
        queued.raise_for_status()
        await asyncio.sleep(args.hold_seconds)
        observed = await client.get(
            f"/api/knowledge/{entry_id}/ingestion", headers=headers
        )
        observed.raise_for_status()
        status = str(observed.json()["status"])
        if status != "queued":
            raise RuntimeError(f"expected queued ingestion while worker is stopped, got {status}")
        return {
            "entry_id": entry_id,
            "queued_status": status,
            "queued_observation_seconds": args.hold_seconds,
        }


async def recover_after_worker_start(args: argparse.Namespace) -> dict[str, Any]:
    state = load_state(args.state)
    entry_id = int(state["entry_id"])
    marker = str(state["marker"])
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout_seconds) as client:
        headers = await login(client)
        recovery_started = time.perf_counter()
        status = await wait_for_ingestion(
            client,
            entry_id=entry_id,
            headers=headers,
            timeout_seconds=args.recovery_timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        recovery_seconds = time.perf_counter() - recovery_started
        if status != "ready":
            raise RuntimeError(f"ingestion failed after worker recovery: {status}")
        retrieved = await client.post(
            "/api/knowledge/retrieve",
            headers=headers,
            json={"query": marker, "source_ids": [entry_id], "limit": 5},
        )
        retrieved.raise_for_status()
        retrieval = retrieved.json()
        citation_count = len(retrieval["citations"])
        if retrieval["mode"] != "hybrid" or not any(
            citation.get("entry_id") == entry_id for citation in retrieval["citations"]
        ):
            raise RuntimeError("recovered entry was not returned by hybrid retrieval")

        deletion_started = time.perf_counter()
        deleted = await client.delete(f"/api/knowledge/{entry_id}", headers=headers)
        deleted.raise_for_status()
        deletion_seconds = time.perf_counter() - deletion_started
    remaining = await remaining_rows(entry_id)
    if any(remaining.values()):
        raise RuntimeError(f"recovery fixture deletion did not propagate: {remaining}")
    report = {
        "entry_id": entry_id,
        "recovered_status": status,
        "worker_recovery_seconds": recovery_seconds,
        "retrieval_mode": retrieval["mode"],
        "citation_count": citation_count,
        "deletion_propagation_seconds": deletion_seconds,
        "remaining_rows": remaining,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    args.state.unlink(missing_ok=True)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify RAG worker stop and recovery behavior")
    parser.add_argument("phase", choices=("queue", "recover"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path(".runtime/rag-recovery.json"))
    parser.add_argument("--hold-seconds", type=float, default=3.0)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--timeout-seconds", type=float, default=40.0)
    parser.add_argument("--recovery-timeout-seconds", type=float, default=180.0)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.phase == "queue":
        return await queue_while_worker_is_stopped(args)
    return await recover_after_worker_start(args)


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(parse_args())), sort_keys=True))
