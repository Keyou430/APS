from __future__ import annotations

import json
from pathlib import Path


def test_evaluation_fixture_has_100_labeled_cases_without_query_copy() -> None:
    path = Path(__file__).parent / "fixtures/rag/evaluation.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(rows) == 100
    assert len({row["case_id"] for row in rows}) == 100
    document_labels_by_tenant = {
        tenant: {
            entry_id
            for row in rows
            if row["tenant"] == tenant
            for entry_id in row["expected_entry_ids"]
        }
        for tenant in {row["tenant"] for row in rows}
    }
    for row in rows:
        assert row["expected_entry_ids"]
        assert row["expected_chunk_ids"]
        assert row["document_chunks"]
        assert all(row["query"].casefold() != chunk.casefold() for chunk in row["document_chunks"])
        assert set(row["hard_negative_entry_ids"]).isdisjoint(row["expected_entry_ids"])
        assert set(row["hard_negative_entry_ids"]).issubset(
            document_labels_by_tenant[row["tenant"]]
        )
