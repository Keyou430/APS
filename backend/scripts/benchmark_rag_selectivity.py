from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database import SessionLocal
from scripts.benchmark_rag_capacity import create_fixture, cleanup_fixture
from scripts.evaluate_rag import percentile_95


SELECTIVITY = (0.0001, 0.001, 0.01, 0.1, 1.0)


def summarize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("Plans", []):
            visit(child)

    visit(plan["Plan"])
    return {
        "execution_time_ms": plan.get("Execution Time"),
        "planning_time_ms": plan.get("Planning Time"),
        "actual_rows": plan["Plan"].get("Actual Rows"),
        "rows_removed_by_filter": sum(node.get("Rows Removed by Filter", 0) for node in nodes),
        "node_types": [node.get("Node Type") for node in nodes],
        "index_names": [node.get("Index Name") for node in nodes if node.get("Index Name")],
        "sort_methods": [node.get("Sort Method") for node in nodes if node.get("Sort Method")],
        "sort_space_kb": [node.get("Sort Space Used") for node in nodes if node.get("Sort Space Used")],
        "shared_hit_blocks": sum(node.get("Shared Hit Blocks", 0) for node in nodes),
        "shared_read_blocks": sum(node.get("Shared Read Blocks", 0) for node in nodes),
        "temp_read_blocks": sum(node.get("Temp Read Blocks", 0) for node in nodes),
        "temp_written_blocks": sum(node.get("Temp Written Blocks", 0) for node in nodes),
    }


async def scalar(db, statement: str, parameters: dict[str, Any]) -> Any:
    return await db.scalar(text(statement), parameters)


async def insert_rows(db, fixture: dict[str, int | str], *, count: int, batch_size: int) -> None:
    for start in range(1, count + 1, batch_size):
        end = min(count, start + batch_size - 1)
        await db.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(organization_id, user_id, knowledge_entry_id, content_sha256, ordinal, text, "
                "text_sha256, source_locator, embedding) "
                "SELECT :organization_id, :user_id, :entry_id, :content_sha256, ordinal, "
                "CASE WHEN ordinal <= :full_count THEN 'selectivity_full' "
                "ELSE 'nonmatching synthetic text' END || CASE "
                "WHEN ordinal <= :ten_percent_count THEN ' selectivity_ten' ELSE '' END || CASE "
                "WHEN ordinal <= :one_percent_count THEN ' selectivity_one' ELSE '' END || CASE "
                "WHEN ordinal <= :point_one_percent_count THEN ' selectivity_point_one' ELSE '' END || CASE "
                "WHEN ordinal <= :point_zero_one_percent_count THEN ' selectivity_point_zero_one' ELSE '' END, "
                ":text_sha256, 'chunk:' || ordinal, "
                "CAST(:embedding AS vector) "
                "FROM generate_series(CAST(:start AS integer), CAST(:end AS integer)) AS ordinal"
            ),
            {
                **fixture,
                "start": start,
                "end": end,
                "full_count": count,
                "ten_percent_count": max(1, int(count * 0.1)),
                "one_percent_count": max(1, int(count * 0.01)),
                "point_one_percent_count": max(1, int(count * 0.001)),
                "point_zero_one_percent_count": max(1, int(count * 0.0001)),
                "text_sha256": "e" * 64,
                "embedding": fixture["embedding"],
            },
        )
        await db.commit()


async def explain(db, fixture: dict[str, int | str], *, query: str, bounded: int) -> dict[str, Any]:
    await db.execute(text("SET LOCAL enable_seqscan = off"))
    result = await db.execute(
        text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            "WITH search_query AS (SELECT plainto_tsquery('simple', :query) AS q) "
            "SELECT c.id FROM knowledge_chunks AS c, search_query "
            "WHERE c.organization_id = :organization_id AND c.user_id = :user_id "
            "AND c.knowledge_entry_id = :entry_id AND c.content_sha256 = :content_sha256 "
            "AND to_tsvector('simple', c.text) @@ search_query.q "
            "ORDER BY ts_rank_cd(to_tsvector('simple', c.text), search_query.q) DESC, c.id "
            "LIMIT :bounded"
        ),
        {**fixture, "query": query, "bounded": bounded},
    )
    plan = (result.scalar_one())[0]
    await db.execute(text("SET LOCAL enable_seqscan = on"))
    return summarize_plan(plan)


async def timed_query(db, fixture: dict[str, int | str], *, query: str, samples: int) -> dict[str, float]:
    values: list[float] = []
    await db.execute(text("SET LOCAL enable_seqscan = off"))
    for _ in range(samples):
        started = time.perf_counter()
        await db.execute(
            text(
                "WITH search_query AS (SELECT plainto_tsquery('simple', :query) AS q) "
                "SELECT c.id FROM knowledge_chunks AS c, search_query "
                "WHERE c.organization_id = :organization_id AND c.user_id = :user_id "
                "AND c.knowledge_entry_id = :entry_id AND c.content_sha256 = :content_sha256 "
                "AND to_tsvector('simple', c.text) @@ search_query.q "
                "ORDER BY ts_rank_cd(to_tsvector('simple', c.text), search_query.q) DESC, c.id LIMIT 24"
            ),
            {**fixture, "query": query},
        )
        values.append((time.perf_counter() - started) * 1000)
    await db.execute(text("SET LOCAL enable_seqscan = on"))
    values.sort()
    return {
        "p50_ms": values[len(values) // 2],
        "p95_ms": percentile_95(values),
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {"selectivity": [], "cleanup_seconds": None}
    async with SessionLocal() as db:
        fixture = await create_fixture(db)
        fixture["embedding"] = "[" + ",".join(["0.1"] * 1024) + "]"
        try:
            await insert_rows(db, fixture, count=args.target, batch_size=args.batch_size)
            await db.execute(text("ANALYZE knowledge_chunks"))
            await db.commit()
            query_by_ratio = {
                0.0001: "selectivity_point_zero_one",
                0.001: "selectivity_point_one",
                0.01: "selectivity_one",
                0.1: "selectivity_ten",
                1.0: "selectivity_full",
            }
            for ratio in SELECTIVITY:
                matching_rows = max(1, int(args.target * ratio))
                row = {
                    "target_chunks": args.target,
                    "match_ratio": ratio,
                    "matching_rows": matching_rows,
                    "explain": await explain(
                        db, fixture, query=query_by_ratio[ratio], bounded=24
                    ),
                    "timing": await timed_query(
                        db, fixture, query=query_by_ratio[ratio], samples=args.samples
                    ),
                }
                report["selectivity"].append(row)
                print(json.dumps(row, sort_keys=True), flush=True)
            await db.execute(text("DELETE FROM knowledge_chunks WHERE knowledge_entry_id = :entry_id"), fixture)
            await db.commit()
        finally:
            report["cleanup_seconds"] = await cleanup_fixture(db, fixture)
            report["remaining_chunks"] = await scalar(
                db,
                "SELECT count(*) FROM knowledge_chunks WHERE knowledge_entry_id = :entry_id",
                fixture,
            )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explain RAG FTS at controlled selectivity")
    parser.add_argument("--target", type=int, choices=(100000, 1000000), required=True)
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
