from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, func, select

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import (
    KnowledgeChunk,
    KnowledgeEntry,
    KnowledgeIngestionJob,
    Organization,
    OrganizationMembership,
    RefreshToken,
    Role,
    User,
)


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    query: str
    expected_entry_ids: list[int]
    expected_chunk_ids: list[str]
    hard_negative_entry_ids: list[int]
    tenant: str
    document_chunks: list[str]


@dataclass(frozen=True)
class CitationScore:
    hit_at_1: float
    hit_at_5: float
    recall_at_5: float
    mrr: float
    unique_source_precision_at_5: float
    chunk_precision_at_5: float
    returned_citation_count: int
    relevant_chunk_count: int
    hard_negative_count: int
    failed_case: dict[str, Any] | None


def load_dataset(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        case_id = value.get("case_id")
        query = value.get("query")
        expected = value.get("expected_entry_ids")
        expected_chunks = value.get("expected_chunk_ids")
        hard_negatives = value.get("hard_negative_entry_ids")
        tenant = value.get("tenant")
        document_chunks = value.get("document_chunks")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"case_id is required at line {line_number}")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"query is required at line {line_number}")
        if not isinstance(expected, list) or not expected or any(type(item) is not int for item in expected):
            raise ValueError(f"expected_entry_ids is invalid at line {line_number}")
        if (
            not isinstance(expected_chunks, list)
            or not expected_chunks
            or any(not isinstance(item, str) or not item.strip() for item in expected_chunks)
        ):
            raise ValueError(f"expected_chunk_ids is invalid at line {line_number}")
        if (
            not isinstance(hard_negatives, list)
            or any(type(item) is not int for item in hard_negatives)
            or set(hard_negatives).intersection(expected)
        ):
            raise ValueError(f"hard_negative_entry_ids is invalid at line {line_number}")
        if not isinstance(tenant, str) or not tenant.strip():
            raise ValueError(f"tenant is required at line {line_number}")
        if (
            not isinstance(document_chunks, list)
            or not document_chunks
            or any(not isinstance(item, str) or not item.strip() for item in document_chunks)
        ):
            raise ValueError(f"document_chunks is invalid at line {line_number}")
        normalized_query = query.strip()
        if any(normalized_query.casefold() == chunk.strip().casefold() for chunk in document_chunks):
            raise ValueError(f"query must not be copied into document at line {line_number}")
        cases.append(
            EvaluationCase(
                case_id=case_id.strip(),
                query=normalized_query,
                expected_entry_ids=expected,
                expected_chunk_ids=[item.strip() for item in expected_chunks],
                hard_negative_entry_ids=hard_negatives,
                tenant=tenant.strip(),
                document_chunks=[item.strip() for item in document_chunks],
            )
        )
    if not cases:
        raise ValueError("evaluation dataset is empty")
    return cases


def percentile_95(values: list[float]) -> float:
    if not values:
        raise ValueError("latency sample is empty")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95 + 0.999999) - 1))
    return ordered[index]


def score_citations(
    *,
    expected_entry_ids: set[int],
    expected_chunk_ids: set[str],
    hard_negative_entry_ids: set[int] | None = None,
    citations: list[dict[str, Any]],
    entry_labels: dict[int, str] | None = None,
    case_id: str = "unknown",
) -> CitationScore:
    top = citations[:5]
    relevant_chunks = {
        f"{citation.get('entry_id')}:{str(citation.get('source_locator', '')).removeprefix('chunk:')}"
        for citation in top
        if citation.get("entry_id") is not None
    }
    ranked_relevance = [
        f"{citation.get('entry_id')}:{str(citation.get('source_locator', '')).removeprefix('chunk:')}"
        in expected_chunk_ids
        for citation in top
    ]
    unique_sources = {citation.get("entry_id") for citation in top}
    unique_sources.discard(None)
    relevant_sources = unique_sources.intersection(expected_entry_ids)
    chunk_hits = sum(ranked_relevance)
    hard_negative_count = sum(
        citation.get("entry_id") in (hard_negative_entry_ids or set()) for citation in top
    )
    reciprocal_rank = next(
        (1 / index for index, is_relevant in enumerate(ranked_relevance, start=1) if is_relevant),
        0.0,
    )
    failed_case = None
    if not any(ranked_relevance):
        labels = entry_labels or {}
        failed_case = {
            "case_id": case_id,
            "returned_entry_labels": [
                labels.get(entry_id, str(entry_id))
                for entry_id in dict.fromkeys(
                    citation.get("entry_id") for citation in top if citation.get("entry_id") is not None
                )
            ],
        }
    return CitationScore(
        hit_at_1=float(bool(ranked_relevance and ranked_relevance[0])),
        hit_at_5=float(any(ranked_relevance)),
        recall_at_5=(
            len(relevant_chunks.intersection(expected_chunk_ids)) / len(expected_chunk_ids)
            if expected_chunk_ids
            else 0.0
        ),
        mrr=reciprocal_rank,
        unique_source_precision_at_5=(len(relevant_sources) / len(unique_sources)) if unique_sources else 0.0,
        chunk_precision_at_5=(chunk_hits / len(top)) if top else 0.0,
        returned_citation_count=len(citations),
        relevant_chunk_count=chunk_hits,
        hard_negative_count=hard_negative_count,
        failed_case=failed_case,
    )


class SyntheticEvaluation:
    def __init__(self, *, base_url: str, cases: list[EvaluationCase]) -> None:
        self.base_url = base_url.rstrip("/")
        self.cases = cases
        self.password = secrets.token_urlsafe(24)
        self.user_ids: list[int] = []
        self.organization_ids: list[int] = []
        self.usernames: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.actual_entry_ids: dict[tuple[str, int], int] = {}
        self.entry_labels: dict[int, str] = {}

    async def setup_identities(self) -> None:
        suffix = str(time.time_ns())
        tenants = sorted({case.tenant for case in self.cases})
        async with SessionLocal() as db:
            role = await db.scalar(select(Role).where(Role.name == "user"))
            if role is None:
                raise RuntimeError("user role is unavailable")
            for tenant in tenants:
                safe_tenant = "".join(character if character.isalnum() else "-" for character in tenant)
                organization = Organization(
                    name=f"Synthetic RAG {safe_tenant} {suffix}",
                    slug=f"synthetic-rag-{safe_tenant}-{suffix}",
                )
                db.add(organization)
                await db.flush()
                username = f"rag-eval-{safe_tenant}-{suffix}"
                user = User(
                    username=username,
                    email=f"{username}@example.com",
                    password_hash=hash_password(self.password),
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
                self.organization_ids.append(organization.id)
                self.user_ids.append(user.id)
                self.usernames[tenant] = username
            await db.commit()

    async def login(self, client: httpx.AsyncClient) -> None:
        for tenant, username in self.usernames.items():
            response = await client.post(
                "/api/auth/login",
                json={"username": username, "password": self.password},
            )
            response.raise_for_status()
            self.tokens[tenant] = response.json()["access_token"]
            me = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {self.tokens[tenant]}"},
            )
            me.raise_for_status()

    async def create_and_ingest_documents(self, client: httpx.AsyncClient) -> None:
        chunks_by_document: dict[tuple[str, int], list[str]] = {}
        for case in self.cases:
            for label in case.expected_entry_ids:
                key = (case.tenant, label)
                existing = chunks_by_document.setdefault(key, case.document_chunks)
                if existing != case.document_chunks:
                    raise ValueError(f"document chunks differ for {case.tenant}:{label}")

        job_entries: list[tuple[str, int, int]] = []
        for (tenant, label), document_chunks in sorted(chunks_by_document.items()):
            headers = {"Authorization": f"Bearer {self.tokens[tenant]}"}
            body = "\n\n".join(document_chunks)
            created = await client.post(
                "/api/knowledge",
                headers=headers,
                json={
                    "type": "workflow_result",
                    "title": f"Synthetic reference {label}",
                    "content": body,
                },
            )
            created.raise_for_status()
            entry_id = created.json()["id"]
            self.actual_entry_ids[(tenant, label)] = entry_id
            self.entry_labels[entry_id] = f"{tenant}:{label}"
            queued = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=headers)
            queued.raise_for_status()
            job_entries.append((tenant, label, entry_id))

        deadline = time.monotonic() + 180
        pending = set(job_entries)
        while pending and time.monotonic() < deadline:
            for tenant, label, entry_id in list(pending):
                headers = {"Authorization": f"Bearer {self.tokens[tenant]}"}
                response = await client.get(
                    f"/api/knowledge/{entry_id}/ingestion", headers=headers
                )
                response.raise_for_status()
                status = response.json()["status"]
                if status == "ready":
                    pending.remove((tenant, label, entry_id))
                elif status == "failed":
                    raise RuntimeError(f"synthetic ingestion failed for label {label}")
            if pending:
                await asyncio.sleep(1)
        if pending:
            raise TimeoutError(f"synthetic ingestion timed out for {len(pending)} documents")

    async def evaluate(self, client: httpx.AsyncClient) -> dict[str, Any]:
        scores: list[CitationScore] = []
        mode_counts = {"hybrid": 0, "degraded_full_text": 0, "empty": 0}
        latencies_ms: list[float] = []
        cross_tenant_results = 0
        tenants = sorted(self.tokens)

        for case in self.cases:
            expected_entry_ids = {
                self.actual_entry_ids[(case.tenant, label)] for label in case.expected_entry_ids
            }
            expected_chunk_ids = {
                f"{self.actual_entry_ids[(case.tenant, int(label.split(':', 1)[0]))]}:{label.split(':', 1)[1]}"
                for label in case.expected_chunk_ids
            }
            hard_negative_entry_ids = {
                self.actual_entry_ids[(case.tenant, label)]
                for label in case.hard_negative_entry_ids
            }
            headers = {"Authorization": f"Bearer {self.tokens[case.tenant]}"}
            started = time.perf_counter()
            response = await client.post(
                "/api/knowledge/retrieve",
                headers=headers,
                json={"query": case.query, "source_ids": [], "limit": 5},
            )
            latencies_ms.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            body = response.json()
            mode_counts[body["mode"]] = mode_counts.get(body["mode"], 0) + 1
            scores.append(
                score_citations(
                    case_id=case.case_id,
                    expected_entry_ids=expected_entry_ids,
                    expected_chunk_ids=expected_chunk_ids,
                    hard_negative_entry_ids=hard_negative_entry_ids,
                    citations=body["citations"],
                    entry_labels=self.entry_labels,
                )
            )

            foreign_tenant = next((tenant for tenant in tenants if tenant != case.tenant), None)
            if foreign_tenant is not None:
                foreign_headers = {
                    "Authorization": f"Bearer {self.tokens[foreign_tenant]}"
                }
                source_ids = list(expected_entry_ids)
                isolated = await client.post(
                    "/api/knowledge/retrieve",
                    headers=foreign_headers,
                    json={"query": case.query, "source_ids": source_ids, "limit": 5},
                )
                isolated.raise_for_status()
                cross_tenant_results += len(isolated.json()["citations"])

        failures = [score.failed_case for score in scores if score.failed_case is not None]
        returned_count = sum(score.returned_citation_count for score in scores)
        return {
            "dataset_size": len(self.cases),
            "synthetic_document_count": len(self.actual_entry_ids),
            "hit_at_1": statistics.fmean(score.hit_at_1 for score in scores),
            "hit_at_5": statistics.fmean(score.hit_at_5 for score in scores),
            "recall_at_5": statistics.fmean(score.recall_at_5 for score in scores),
            "mrr": statistics.fmean(score.mrr for score in scores),
            "unique_source_precision_at_5": statistics.fmean(
                score.unique_source_precision_at_5 for score in scores
            ),
            "chunk_precision_at_5": statistics.fmean(
                score.chunk_precision_at_5 for score in scores
            ),
            "citation_accuracy": (
                sum(score.relevant_chunk_count for score in scores) / returned_count
                if returned_count
                else 0.0
            ),
            "hard_negative_rate_at_5": sum(
                score.hard_negative_count for score in scores
            )
            / returned_count
            if returned_count
            else 0.0,
            "average_returned_citation_count": returned_count / len(scores),
            "hybrid_count": mode_counts.get("hybrid", 0),
            "degraded_full_text_count": mode_counts.get("degraded_full_text", 0),
            "empty_count": mode_counts.get("empty", 0),
            "failed_cases": failures,
            "p95_retrieval_latency_ms": percentile_95(latencies_ms),
            "mean_retrieval_latency_ms": statistics.fmean(latencies_ms),
            "cross_tenant_result_count": cross_tenant_results,
        }

    async def cleanup(self, client: httpx.AsyncClient) -> dict[str, Any]:
        entry_ids = list(self.actual_entry_ids.values())
        deletion_started = time.perf_counter()
        for (tenant, _label), entry_id in list(self.actual_entry_ids.items()):
            token = self.tokens.get(tenant)
            if token:
                response = await client.delete(
                    f"/api/knowledge/{entry_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
        deletion_propagation_seconds = time.perf_counter() - deletion_started
        async with SessionLocal() as db:
            remaining_entries = 0
            remaining_jobs = 0
            remaining_chunks = 0
            if entry_ids:
                remaining_entries = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(KnowledgeEntry)
                        .where(KnowledgeEntry.id.in_(entry_ids))
                    )
                    or 0
                )
                remaining_jobs = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(KnowledgeIngestionJob)
                        .where(KnowledgeIngestionJob.knowledge_entry_id.in_(entry_ids))
                    )
                    or 0
                )
                remaining_chunks = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(KnowledgeChunk)
                        .where(KnowledgeChunk.knowledge_entry_id.in_(entry_ids))
                    )
                    or 0
                )
            if self.user_ids:
                await db.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(self.user_ids)))
                await db.execute(
                    delete(OrganizationMembership).where(
                        OrganizationMembership.user_id.in_(self.user_ids)
                    )
                )
                await db.execute(delete(User).where(User.id.in_(self.user_ids)))
            if self.organization_ids:
                await db.execute(
                    delete(Organization).where(Organization.id.in_(self.organization_ids))
                )
            await db.commit()
        return {
            "deletion_propagation_seconds": deletion_propagation_seconds,
            "remaining_evaluation_entries": remaining_entries,
            "remaining_evaluation_jobs": remaining_jobs,
            "remaining_evaluation_chunks": remaining_chunks,
        }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_dataset(args.dataset)
    evaluation = SyntheticEvaluation(base_url=args.base_url, cases=cases)
    async with httpx.AsyncClient(base_url=evaluation.base_url, timeout=args.timeout_seconds) as client:
        try:
            await evaluation.setup_identities()
            await evaluation.login(client)
            await evaluation.create_and_ingest_documents(client)
            report = await evaluation.evaluate(client)
        finally:
            cleanup_report = await evaluation.cleanup(client)
    report.update(cleanup_report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate live authorized platform RAG")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-seconds", type=float, default=40.0)
    return parser.parse_args()


def main() -> None:
    report = asyncio.run(run(parse_args()))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
