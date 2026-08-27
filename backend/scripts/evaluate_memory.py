from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth.security import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    MemoryRecord,
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from app.services.memory_retrieval import (  # noqa: E402
    MemoryRetrievalScope,
    retrieve_authorized_memories,
)


@dataclass(frozen=True)
class EvaluationIdentity:
    organization_id: int
    user_id: int
    fixture_id: str


class DeterministicTestEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [deterministic_vector(text) for text in texts]


def deterministic_vector(value: str) -> list[float]:
    vector = [0.0] * 1024
    for token in value.casefold().replace(".", "").replace(",", "").split():
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:2], "big") % len(vector)] += 1.0
    if not any(vector):
        vector[0] = 1.0
    magnitude = math.sqrt(sum(item * item for item in vector))
    return [item / magnitude for item in vector]


def require_disposable_database(allowed: bool) -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    if not allowed or not url.drivername.startswith("postgresql"):
        raise RuntimeError("memory evaluation requires an explicitly allowed PostgreSQL database")
    if not (url.database or "").startswith("phase_d_memory_"):
        raise RuntimeError("database name must start with phase_d_memory_")


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def score_case(*, expected_id: str | None, result_ids: list[str]) -> dict[str, float | None]:
    if expected_id is None:
        return {
            "precision_at_5": None,
            "recall_at_5": None,
            "no_answer_accuracy": float(not result_ids),
        }
    hit = float(expected_id in result_ids[:5])
    return {
        "precision_at_5": hit / 5,
        "recall_at_5": hit,
        "no_answer_accuracy": None,
    }


async def create_fixture(dataset: dict[str, Any]) -> list[EvaluationIdentity]:
    identities: list[EvaluationIdentity] = []
    async with SessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.name == "memory-evaluation"))
        if role is None:
            role = Role(name="memory-evaluation", permissions=[])
            db.add(role)
            await db.flush()
        for organization_fixture in dataset["organizations"]:
            fixture_id = organization_fixture["id"]
            organization = Organization(
                name=f"Synthetic memory evaluation {fixture_id}",
                slug=f"phase-d-memory-eval-{fixture_id}",
            )
            db.add(organization)
            await db.flush()
            user = User(
                username=f"phase-d-memory-eval-{fixture_id}",
                email=f"phase-d-memory-eval-{fixture_id}@example.invalid",
                password_hash=hash_password("synthetic-evaluation-only"),
                role_id=role.id,
                default_organization_id=organization.id,
            )
            db.add(user)
            await db.flush()
            db.add(
                OrganizationMembership(
                    organization_id=organization.id,
                    user_id=user.id,
                    role_id=role.id,
                )
            )
            await db.flush()
            identities.append(
                EvaluationIdentity(
                    organization_id=organization.id,
                    user_id=user.id,
                    fixture_id=fixture_id,
                )
            )
            await seed_memories(db, organization_fixture, identities[-1])
        await db.commit()
    return identities


async def seed_memories(db, fixture: dict[str, Any], identity: EvaluationIdentity) -> None:
    records: list[MemoryRecord] = []
    expected_count = 0
    for query in fixture["queries"]:
        content = query["content"]
        if content is None:
            continue
        expected_count += 1
        records.append(
            memory_record(
                identity,
                memory_id=f"{identity.fixture_id}{expected_count:04d}".ljust(32, "0"),
                content=content,
                status="active",
                embedding=deterministic_vector(content),
                source_summary=f"synthetic:{query['id']}",
            )
        )
    while len(records) < fixture["active_count"]:
        ordinal = len(records) + 1
        content = f"{identity.fixture_id} synthetic filler memory number {ordinal}"
        records.append(
            memory_record(
                identity,
                memory_id=f"{identity.fixture_id}f{ordinal:04d}".ljust(32, "0"),
                content=content,
                status="active",
                embedding=deterministic_vector(content),
                source_summary="synthetic:filler",
            )
        )
    for status, marker in (("candidate", "c"), ("superseded", "s")):
        for ordinal in range(10):
            content = f"{identity.fixture_id} excluded {status} planmarker {ordinal}"
            records.append(
                memory_record(
                    identity,
                    memory_id=f"{identity.fixture_id}{marker}{ordinal:04d}".ljust(32, "0"),
                    content=content,
                    status=status,
                    embedding=deterministic_vector(content),
                    source_summary=f"synthetic:{status}",
                )
            )
    db.add_all(records)
    await db.flush()
    deleted = [
        memory_record(
            identity,
            memory_id=f"{identity.fixture_id}d{ordinal:04d}".ljust(32, "0"),
            content=f"{identity.fixture_id} physically deleted planmarker {ordinal}",
            status="active",
            embedding=None,
            source_summary="synthetic:deleted",
        )
        for ordinal in range(10)
    ]
    db.add_all(deleted)
    await db.flush()
    await db.execute(
        delete(MemoryRecord).where(
            MemoryRecord.memory_id.in_([record.memory_id for record in deleted])
        )
    )


def memory_record(
    identity: EvaluationIdentity,
    *,
    memory_id: str,
    content: str,
    status: str,
    embedding: list[float] | None,
    source_summary: str,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id[:32],
        organization_id=identity.organization_id,
        user_id=identity.user_id,
        content=content,
        type="fact",
        layer="L1",
        status=status,
        origin="imported",
        revision=1,
        metadata_={},
        embedding=embedding,
        embedding_model="deterministic-test" if embedding is not None else None,
        embedding_version="v1" if embedding is not None else None,
        source_summary=source_summary,
    )


async def evaluate_mode(
    dataset: dict[str, Any],
    identities: list[EvaluationIdentity],
    *,
    embedding_provider: DeterministicTestEmbedding | None,
) -> dict[str, Any]:
    precision: list[float] = []
    recall: list[float] = []
    no_answer_accuracy: list[float] = []
    latencies: list[float] = []
    token_counts: list[int] = []
    authorization_leaks = 0
    by_fixture = {item.fixture_id: item for item in identities}
    async with SessionLocal() as db:
        for organization_fixture in dataset["organizations"]:
            identity = by_fixture[organization_fixture["id"]]
            expected_ordinal = 0
            for query in organization_fixture["queries"]:
                expected_id = None
                if query["content"] is not None:
                    expected_ordinal += 1
                    expected_id = f"{identity.fixture_id}{expected_ordinal:04d}".ljust(32, "0")
                started = time.perf_counter()
                records = await retrieve_authorized_memories(
                    db,
                    scope=MemoryRetrievalScope(
                        organization_id=identity.organization_id,
                        user_id=identity.user_id,
                    ),
                    query=query["query"],
                    limit=5,
                    embedding_provider=embedding_provider,
                )
                latencies.append((time.perf_counter() - started) * 1000)
                authorization_leaks += sum(
                    record.organization_id != identity.organization_id
                    or record.user_id != identity.user_id
                    or record.status != "active"
                    for record in records
                )
                result_ids = [record.memory_id for record in records]
                case_score = score_case(expected_id=expected_id, result_ids=result_ids)
                if case_score["precision_at_5"] is not None:
                    precision.append(case_score["precision_at_5"])
                    recall.append(case_score["recall_at_5"] or 0.0)
                if case_score["no_answer_accuracy"] is not None:
                    no_answer_accuracy.append(case_score["no_answer_accuracy"])
                token_counts.append(sum(len(record.content.split()) for record in records))
    if authorization_leaks:
        raise AssertionError(f"memory authorization leakage: {authorization_leaks}")
    return {
        "total_query_count": len(precision) + len(no_answer_accuracy),
        "relevant_query_count": len(precision),
        "no_answer_query_count": len(no_answer_accuracy),
        "precision_at_5": sum(precision) / len(precision),
        "recall_at_5": sum(recall) / len(recall),
        "no_answer_accuracy": sum(no_answer_accuracy) / len(no_answer_accuracy),
        "latency_p95_ms": percentile_95(latencies),
        "context_token_count_total": sum(token_counts),
        "context_token_count_p95": percentile_95([float(value) for value in token_counts]),
        "authorization_leaks": authorization_leaks,
    }


async def cleanup_fixture(identities: list[EvaluationIdentity]) -> None:
    organization_ids = [item.organization_id for item in identities]
    user_ids = [item.user_id for item in identities]
    async with SessionLocal() as db:
        await db.execute(delete(OrganizationMembership).where(OrganizationMembership.organization_id.in_(organization_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.execute(delete(Organization).where(Organization.id.in_(organization_ids)))
        await db.execute(delete(Role).where(Role.name == "memory-evaluation"))
        await db.commit()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    require_disposable_database(args.allow_disposable_database)
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    identities: list[EvaluationIdentity] = []
    try:
        identities = await create_fixture(dataset)
        report = {
            "dataset_version": dataset["version"],
            "organization_count": len(dataset["organizations"]),
            "active_count": sum(item["active_count"] for item in dataset["organizations"]),
            "excluded_count": sum(item["excluded_count"] for item in dataset["organizations"]),
            "fts_baseline": await evaluate_mode(dataset, identities, embedding_provider=None),
            "deterministic_test_rrf": await evaluate_mode(
                dataset,
                identities,
                embedding_provider=DeterministicTestEmbedding(),
            ),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return report
    finally:
        if identities:
            await cleanup_fixture(identities)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate synthetic Phase D memory retrieval")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-disposable-database", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(parse_args())), indent=2, sort_keys=True))
