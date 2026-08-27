from __future__ import annotations

import json

import pytest

from scripts.evaluate_rag import (
    load_dataset,
    percentile_95,
    score_citations,
)


def test_load_dataset_rejects_empty_and_malformed_rows(tmp_path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset is empty"):
        load_dataset(empty)

    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "query": "q",
                "expected_entry_ids": [],
                "expected_chunk_ids": [],
                "hard_negative_entry_ids": [],
                "document_chunks": ["unrelated reference"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 1"):
        load_dataset(malformed)


def test_percentile_95_uses_nearest_rank() -> None:
    assert percentile_95([float(value) for value in range(1, 101)]) == 95.0


def test_load_dataset_requires_chunk_labels_and_rejects_query_copied_into_document(tmp_path) -> None:
    missing_chunks = tmp_path / "missing-chunks.jsonl"
    missing_chunks.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "query": "annual leave",
                "expected_entry_ids": [1001],
                "document_chunks": ["paid leave policy"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expected_chunk_ids"):
        load_dataset(missing_chunks)

    copied_query = tmp_path / "copied-query.jsonl"
    copied_query.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "query": "annual leave",
                "expected_entry_ids": [1001],
                "expected_chunk_ids": ["1001:0"],
                "hard_negative_entry_ids": [],
                "tenant": "tenant-a",
                "document_chunks": ["annual leave"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="query must not be copied"):
        load_dataset(copied_query)


def test_score_citations_reports_chunk_and_unique_source_metrics_without_hiding_low_precision() -> None:
    result = score_citations(
        expected_entry_ids={1001},
        expected_chunk_ids={"1001:0"},
        hard_negative_entry_ids={1002},
        citations=[
            {"entry_id": 1002, "source_locator": "chunk:0"},
            {"entry_id": 1001, "source_locator": "chunk:0"},
            {"entry_id": 1001, "source_locator": "chunk:1"},
        ],
        entry_labels={1001: "policy", 1002: "holiday"},
    )

    assert result.hit_at_1 == 0.0
    assert result.hit_at_5 == 1.0
    assert result.recall_at_5 == 1.0
    assert result.mrr == 0.5
    assert result.unique_source_precision_at_5 == 0.5
    assert result.chunk_precision_at_5 == pytest.approx(1 / 3)
    assert result.returned_citation_count == 3
    assert result.relevant_chunk_count == 1
    assert result.hard_negative_count == 1
    assert result.failed_case is None


def test_score_citations_returns_failure_case_id_and_entry_labels_without_text() -> None:
    result = score_citations(
        case_id="case-404",
        expected_entry_ids={1001},
        expected_chunk_ids={"1001:0"},
        hard_negative_entry_ids={1002},
        citations=[{"entry_id": 1002, "source_locator": "chunk:2"}],
        entry_labels={1001: "policy", 1002: "holiday"},
    )

    assert result.failed_case == {
        "case_id": "case-404",
        "returned_entry_labels": ["holiday"],
    }
    assert "text" not in result.failed_case
    assert result.hard_negative_count == 1
