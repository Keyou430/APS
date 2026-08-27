from __future__ import annotations

import pytest

from scripts.benchmark_rag_selectivity import SELECTIVITY, summarize_plan, timed_query


def test_selectivity_scenarios_include_representative_and_worst_case() -> None:
    assert SELECTIVITY == (0.0001, 0.001, 0.01, 0.1, 1.0)


def test_summarize_plan_reports_index_sort_and_buffers() -> None:
    result = summarize_plan(
        {
            "Planning Time": 1.0,
            "Execution Time": 2.0,
            "Plan": {
                "Node Type": "Sort",
                "Actual Rows": 24,
                "Sort Method": "top-N heapsort",
                "Sort Space Used": 12,
                "Shared Hit Blocks": 3,
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": "ix_knowledge_chunks_text_fts",
                        "Shared Read Blocks": 4,
                        "Rows Removed by Filter": 8,
                    }
                ],
            },
        }
    )
    assert result["index_names"] == ["ix_knowledge_chunks_text_fts"]
    assert result["sort_methods"] == ["top-N heapsort"]
    assert result["shared_hit_blocks"] == 3
    assert result["shared_read_blocks"] == 4
    assert result["rows_removed_by_filter"] == 8


@pytest.mark.asyncio
async def test_timed_query_uses_nearest_rank_p95(monkeypatch) -> None:
    class RecordingDb:
        statements: list[str] = []

        async def execute(self, *_args, **_kwargs):
            self.statements.append(str(_args[0]).lower())
            return None

    values = iter(float(value) for value in range(21))
    monkeypatch.setattr("scripts.benchmark_rag_selectivity.time.perf_counter", lambda: next(values))

    db = RecordingDb()
    result = await timed_query(
        db,
        {
            "organization_id": 1,
            "user_id": 2,
            "entry_id": 3,
            "content_sha256": "a" * 64,
        },
        query="marker",
        samples=10,
    )

    assert result == {"p50_ms": 1000.0, "p95_ms": 1000.0}
    assert db.statements[0] == "set local enable_seqscan = off"
    assert db.statements[-1] == "set local enable_seqscan = on"
