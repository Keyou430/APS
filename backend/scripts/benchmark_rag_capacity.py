from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal
from app.services.query_embedding import QueryEmbeddingClient
from scripts.evaluate_rag import percentile_95


def parse_targets(value: str) -> list[int]:
    targets = [int(item) for item in value.split(",")]
    if not targets or any(target <= 0 for target in targets):
        raise ValueError("capacity targets must be positive")
    if targets != sorted(set(targets)):
        raise ValueError("capacity targets must be unique and increasing")
    return targets


async def scalar(db, statement: str, parameters: dict[str, Any] | None = None) -> Any:
    return await db.scalar(text(statement), parameters or {})


async def create_fixture(db) -> dict[str, int | str]:
    suffix = uuid4().hex
    role_id = await scalar(db, "SELECT id FROM roles WHERE name = 'user'")
    if role_id is None:
        raise RuntimeError("user role is unavailable")

    organization_id = await scalar(
        db,
        "INSERT INTO organizations (name, slug, is_active) "
        "VALUES (:name, :slug, true) RETURNING id",
        {"name": "Synthetic Capacity", "slug": f"synthetic-capacity-{suffix}"},
    )
    foreign_organization_id = await scalar(
        db,
        "INSERT INTO organizations (name, slug, is_active) "
        "VALUES (:name, :slug, true) RETURNING id",
        {"name": "Synthetic Capacity Foreign", "slug": f"synthetic-capacity-foreign-{suffix}"},
    )
    user_id = await scalar(
        db,
        "INSERT INTO users "
        "(username, password_hash, email, role_id, default_organization_id, is_active) "
        "VALUES (:username, :password_hash, :email, :role_id, :organization_id, true) "
        "RETURNING id",
        {
            "username": f"rag-capacity-{suffix}",
            "password_hash": "synthetic-capacity-no-login",
            "email": f"rag-capacity-{suffix}@example.com",
            "role_id": role_id,
            "organization_id": organization_id,
        },
    )
    foreign_user_id = await scalar(
        db,
        "INSERT INTO users "
        "(username, password_hash, email, role_id, default_organization_id, is_active) "
        "VALUES (:username, :password_hash, :email, :role_id, :organization_id, true) "
        "RETURNING id",
        {
            "username": f"rag-capacity-foreign-{suffix}",
            "password_hash": "synthetic-capacity-no-login",
            "email": f"rag-capacity-foreign-{suffix}@example.com",
            "role_id": role_id,
            "organization_id": foreign_organization_id,
        },
    )
    await db.execute(
        text(
            "INSERT INTO organization_memberships (organization_id, user_id, role_id, is_active) "
            "VALUES (:organization_id, :user_id, :role_id, true), "
            "(:foreign_organization_id, :foreign_user_id, :role_id, true)"
        ),
        {
            "organization_id": organization_id,
            "user_id": user_id,
            "foreign_organization_id": foreign_organization_id,
            "foreign_user_id": foreign_user_id,
            "role_id": role_id,
        },
    )
    entry_id = await scalar(
        db,
        "INSERT INTO knowledge_entries (organization_id, user_id, type, title, content) "
        "VALUES (:organization_id, :user_id, 'workflow_result', 'Synthetic Capacity', "
        "'capacitymarker') RETURNING id",
        {"organization_id": organization_id, "user_id": user_id},
    )
    content_sha256 = "c" * 64
    await db.execute(
        text(
            "INSERT INTO knowledge_ingestion_jobs "
            "(organization_id, user_id, knowledge_entry_id, content_sha256, status, attempts, "
            "parser_version, embedding_model, embedding_dimension) "
            "VALUES (:organization_id, :user_id, :entry_id, :content_sha256, 'ready', 1, "
            "'capacity-v1', 'text-embedding-v4', 1024)"
        ),
        {
            "organization_id": organization_id,
            "user_id": user_id,
            "entry_id": entry_id,
            "content_sha256": content_sha256,
        },
    )
    await db.commit()
    return {
        "organization_id": organization_id,
        "foreign_organization_id": foreign_organization_id,
        "user_id": user_id,
        "foreign_user_id": foreign_user_id,
        "entry_id": entry_id,
        "content_sha256": content_sha256,
    }


async def insert_chunks(
    db,
    fixture: dict[str, int | str],
    *,
    start: int,
    end: int,
    embedding_literal: str,
    batch_size: int,
) -> float:
    started = time.perf_counter()
    for batch_start in range(start, end + 1, batch_size):
        batch_end = min(end, batch_start + batch_size - 1)
        await db.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(organization_id, user_id, knowledge_entry_id, content_sha256, ordinal, text, "
                "text_sha256, source_locator, embedding) "
                "SELECT :organization_id, :user_id, :entry_id, :content_sha256, ordinal, "
                "'capacitymarker synthetic benchmark chunk ' || ordinal, :text_sha256, "
                "'chunk:' || ordinal, CAST(:embedding AS vector) "
                "FROM generate_series(CAST(:start AS integer), CAST(:end AS integer)) AS ordinal"
            ),
            {
                **fixture,
                "start": batch_start,
                "end": batch_end,
                "text_sha256": "d" * 64,
                "embedding": embedding_literal,
            },
        )
        await db.commit()
    return time.perf_counter() - started


async def query_p95_ms(
    db,
    statement: str,
    parameters: dict[str, Any],
    *,
    samples: int,
) -> float:
    latencies: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        result = await db.execute(text(statement), parameters)
        result.all()
        latencies.append((time.perf_counter() - started) * 1000)
    return percentile_95(latencies)


async def collect_metrics(
    db,
    fixture: dict[str, int | str],
    *,
    target: int,
    insertion_seconds: float,
    embedding_literal: str,
    samples: int,
) -> dict[str, Any]:
    await db.execute(text("ANALYZE knowledge_chunks"))
    await db.commit()
    parameters = {**fixture, "embedding": embedding_literal}
    vector_p95 = await query_p95_ms(
        db,
        "SELECT id FROM knowledge_chunks WHERE organization_id = :organization_id "
        "AND user_id = :user_id AND knowledge_entry_id = :entry_id "
        "AND content_sha256 = :content_sha256 "
        "ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT 24",
        parameters,
        samples=samples,
    )
    full_text_p95 = await query_p95_ms(
        db,
        "SELECT id FROM knowledge_chunks WHERE organization_id = :organization_id "
        "AND user_id = :user_id AND knowledge_entry_id = :entry_id "
        "AND content_sha256 = :content_sha256 "
        "AND to_tsvector('simple', text) @@ plainto_tsquery('simple', 'capacitymarker') "
        "ORDER BY ts_rank_cd(to_tsvector('simple', text), "
        "plainto_tsquery('simple', 'capacitymarker')) DESC, id LIMIT 24",
        parameters,
        samples=samples,
    )
    foreign_scope_same_entry = await scalar(
        db,
        "SELECT count(*) FROM knowledge_chunks WHERE "
        "organization_id = :foreign_organization_id AND user_id = :foreign_user_id "
        "AND knowledge_entry_id = :entry_id",
        fixture,
    )
    indexes = (
        await db.execute(
            text(
                "SELECT indexrelname, pg_relation_size(indexrelid) "
                "FROM pg_stat_user_indexes WHERE relname = 'knowledge_chunks' "
                "ORDER BY indexrelname"
            )
        )
    ).all()
    return {
        "target_chunks": target,
        "insertion_seconds": insertion_seconds,
        "database_bytes": await scalar(db, "SELECT pg_database_size(current_database())"),
        "knowledge_chunks_total_bytes": await scalar(
            db, "SELECT pg_total_relation_size('knowledge_chunks')"
        ),
        "knowledge_chunks_heap_bytes": await scalar(
            db, "SELECT pg_relation_size('knowledge_chunks')"
        ),
        "index_bytes": {name: size for name, size in indexes},
        "vector_query_p95_ms": vector_p95,
        "full_text_query_p95_ms": full_text_p95,
        "foreign_scope_same_entry_result_count": foreign_scope_same_entry,
    }


async def cleanup_fixture(db, fixture: dict[str, int | str]) -> float:
    started = time.perf_counter()
    await db.execute(
        text("DELETE FROM knowledge_entries WHERE id = :entry_id"),
        fixture,
    )
    await db.execute(
        text(
            "DELETE FROM organization_memberships WHERE user_id IN (:user_id, :foreign_user_id)"
        ),
        fixture,
    )
    await db.execute(
        text("DELETE FROM users WHERE id IN (:user_id, :foreign_user_id)"), fixture
    )
    await db.execute(
        text(
            "DELETE FROM organizations WHERE id IN "
            "(:organization_id, :foreign_organization_id)"
        ),
        fixture,
    )
    await db.commit()
    return time.perf_counter() - started


async def run(args: argparse.Namespace) -> dict[str, Any]:
    targets = parse_targets(args.targets)
    settings = get_settings()
    if settings.rag_query_embedding_url is None or settings.rag_query_embedding_token is None:
        raise RuntimeError("query embedding proxy configuration is incomplete")
    query_client = QueryEmbeddingClient(
        base_url=settings.rag_query_embedding_url,
        auth_token=settings.rag_query_embedding_token,
        timeout_seconds=settings.rag_query_embedding_timeout_seconds,
    )
    vector = (await query_client.embed(["capacitymarker synthetic benchmark"]))[0]
    embedding_literal = "[" + ",".join(format(value, ".9g") for value in vector) + "]"
    report: dict[str, Any] = {"targets": [], "cleanup_seconds": None}

    async with SessionLocal() as db:
        fixture = await create_fixture(db)
        current = 0
        try:
            for target in targets:
                insertion_seconds = await insert_chunks(
                    db,
                    fixture,
                    start=current + 1,
                    end=target,
                    embedding_literal=embedding_literal,
                    batch_size=args.batch_size,
                )
                report["targets"].append(
                    await collect_metrics(
                        db,
                        fixture,
                        target=target,
                        insertion_seconds=insertion_seconds,
                        embedding_literal=embedding_literal,
                        samples=args.samples,
                    )
                )
                current = target
                print(json.dumps(report["targets"][-1], sort_keys=True), flush=True)
        except BaseException:
            await db.rollback()
            raise
        finally:
            report["cleanup_seconds"] = await cleanup_fixture(db, fixture)
            report["remaining_synthetic_chunks"] = await scalar(
                db,
                "SELECT count(*) FROM knowledge_chunks WHERE knowledge_entry_id = :entry_id",
                fixture,
            )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark existing platform RAG indexes")
    parser.add_argument("--targets", default="100000,1000000")
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
