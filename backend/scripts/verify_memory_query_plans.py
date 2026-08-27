from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def require_disposable_database(allowed: bool) -> None:
    url = make_url(get_settings().database_url)
    if not allowed or not url.drivername.startswith("postgresql"):
        raise RuntimeError("query-plan verification requires explicitly allowed PostgreSQL")
    if not (url.database or "").startswith("phase_d_memory_"):
        raise RuntimeError("database name must start with phase_d_memory_")


def index_names(plan: dict[str, Any]) -> list[str]:
    names: list[str] = []

    def visit(node: dict[str, Any]) -> None:
        if node.get("Index Name"):
            names.append(node["Index Name"])
        for child in node.get("Plans", []):
            visit(child)

    visit(plan["Plan"])
    return sorted(set(names))


async def explain(db, statement: str, parameters: dict[str, Any]) -> dict[str, Any]:
    result = await db.execute(
        text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}"),
        parameters,
    )
    return result.scalar_one()[0]


async def run(args: argparse.Namespace) -> dict[str, Any]:
    require_disposable_database(args.allow_disposable_database)
    vector = "[1," + ",".join(["0"] * 1023) + "]"
    report: dict[str, Any] = {"plans": {}, "missing_fk_indexes": []}
    async with SessionLocal() as db:
        scope = (
            await db.execute(
                text(
                    "SELECT organization_id, user_id FROM organization_memberships "
                    "ORDER BY organization_id, user_id LIMIT 1"
                )
            )
        ).one()
        parameters = {
            "organization_id": scope.organization_id,
            "user_id": scope.user_id,
            "embedding": vector,
        }
        await db.execute(
            text("DELETE FROM memory_records WHERE source_summary = 'synthetic:query-plan'")
        )
        await db.execute(
            text("DELETE FROM memory_capture_sources WHERE source_id = 'phase-d-plan-source'")
        )
        await db.execute(
            text(
                "INSERT INTO memory_records "
                "(memory_id, organization_id, user_id, content, type, layer, status, origin, "
                "revision, metadata, source_summary, embedding, created_at, updated_at) "
                "SELECT md5('phase-d-plan-' || ordinal), :organization_id, :user_id, "
                "CASE WHEN ordinal <= 100 THEN 'planmarker synthetic memory ' || ordinal "
                "ELSE 'filler synthetic memory ' || ordinal END, "
                "'fact', 'L1', 'active', 'imported', 1, '{}'::json, "
                "'synthetic:query-plan', "
                "(('[' || (CASE WHEN ordinal = 1 THEN '1' ELSE '0' END) || ',' || "
                "array_to_string(array_fill(((ordinal % 97)::float / 97)::text, ARRAY[1023]), ',') || ']')::vector), "
                "now(), "
                "now() - (ordinal || ' seconds')::interval "
                "FROM generate_series(1, 1000) AS ordinal"
            ),
            parameters,
        )
        source_id = await db.scalar(
            text(
                "INSERT INTO memory_capture_sources "
                "(source_id, organization_id, user_id, source_kind, raw_text, content_sha256, "
                "status, expires_at, created_at) VALUES "
                "('phase-d-plan-source', :organization_id, :user_id, 'user_text', "
                "'synthetic source', :content_sha256, 'queued', now() + interval '1 hour', now()) "
                "RETURNING id"
            ),
            {**parameters, "content_sha256": "f" * 64},
        )
        await db.execute(
            text(
                "INSERT INTO memory_extraction_jobs "
                "(organization_id, user_id, source_id, status, attempts, max_attempts, provider, "
                "provider_version, available_at, created_at, updated_at) VALUES "
                "(:organization_id, :user_id, :source_id, 'queued', 0, 3, "
                "'synthetic', 'v1', now(), now(), now())"
            ),
            {**parameters, "source_id": source_id},
        )
        await db.execute(text("ANALYZE memory_records"))
        await db.execute(text("ANALYZE memory_extraction_jobs"))
        await db.execute(text("SET LOCAL enable_seqscan = off"))
        statements = {
            "list": (
                "SELECT memory_id FROM memory_records WHERE organization_id=:organization_id "
                "AND user_id=:user_id AND status='active' "
                "ORDER BY updated_at DESC, memory_id DESC LIMIT 20",
                "ix_memory_records_active_owner_list",
            ),
            "fts": (
                "SELECT memory_id FROM memory_records WHERE organization_id=:organization_id "
                "AND user_id=:user_id AND status='active' AND "
                "to_tsvector('simple', content) @@ websearch_to_tsquery('simple', 'planmarker') "
                "ORDER BY ts_rank_cd(to_tsvector('simple', content), "
                "websearch_to_tsquery('simple', 'planmarker')) DESC, updated_at DESC, memory_id DESC LIMIT 20",
                "ix_memory_records_active_fts",
            ),
            "vector": (
                "SELECT memory_id FROM memory_records WHERE organization_id=:organization_id "
                "AND user_id=:user_id AND status='active' AND embedding IS NOT NULL "
                "ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT 20",
                "ix_memory_records_active_embedding_hnsw",
            ),
            "queue": (
                "SELECT id FROM memory_extraction_jobs WHERE status='queued' "
                "AND available_at <= now() AND attempts < max_attempts "
                "ORDER BY available_at, created_at, id LIMIT 1",
                "ix_memory_extraction_jobs_claim",
            ),
        }
        try:
            for name, (statement, expected_index) in statements.items():
                if name == "vector":
                    await db.execute(text("SET LOCAL enable_bitmapscan = off"))
                    await db.execute(text("SET LOCAL enable_sort = off"))
                plan = await explain(db, statement, parameters)
                if name == "vector":
                    await db.execute(text("SET LOCAL enable_bitmapscan = on"))
                    await db.execute(text("SET LOCAL enable_sort = on"))
                names = index_names(plan)
                if expected_index not in names:
                    raise AssertionError(f"{name} did not use {expected_index}: {names}")
                report["plans"][name] = {
                    "expected_index": expected_index,
                    "index_names": names,
                    "execution_time_ms": plan.get("Execution Time"),
                    "shared_hit_blocks": plan["Plan"].get("Shared Hit Blocks", 0),
                }
            missing = (
                await db.execute(
                    text(
                        "WITH fk AS ("
                        " SELECT conrelid, conname, conkey FROM pg_constraint "
                        " WHERE contype='f' AND conrelid IN ("
                        "  'memory_capture_sources'::regclass, 'memory_records'::regclass, "
                        "  'memory_versions'::regclass, 'memory_source_links'::regclass, "
                        "  'memory_extraction_jobs'::regclass, 'memory_retrieval_events'::regclass"
                        " )) SELECT conname FROM fk WHERE NOT EXISTS ("
                        " SELECT 1 FROM pg_index i WHERE i.indrelid=fk.conrelid "
                        " AND i.indisvalid AND (i.indkey::smallint[])[0:cardinality(fk.conkey)-1] = fk.conkey"
                        " ) ORDER BY conname"
                    )
                )
            ).scalars().all()
            report["missing_fk_indexes"] = list(missing)
            if missing:
                raise AssertionError(f"missing memory FK indexes: {list(missing)}")
        finally:
            await db.rollback()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Phase D memory PostgreSQL query plans")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-disposable-database", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(parse_args())), indent=2, sort_keys=True))
