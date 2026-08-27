from __future__ import annotations

import json
from pathlib import Path

from scripts.evaluate_memory import score_case


def test_memory_evaluation_fixture_meets_phase_d_minimums() -> None:
    path = Path(__file__).parent / "fixtures" / "memory_eval" / "dataset.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    assert len(dataset["organizations"]) == 3
    assert all(item["active_count"] >= 100 for item in dataset["organizations"])
    assert all(item["excluded_count"] >= 30 for item in dataset["organizations"])
    assert all(
        item["excluded_breakdown"]
        == {"candidate": 10, "superseded": 10, "deleted": 10}
        for item in dataset["organizations"]
    )
    assert all(len(item["queries"]) >= 20 for item in dataset["organizations"])
    categories = {query["category"] for item in dataset["organizations"] for query in item["queries"]}
    assert {
        "fact",
        "preference",
        "decision",
        "correction",
        "conflict",
        "expired",
        "no_answer",
        "cross_organization",
        "prompt_injection",
    } <= categories


def test_precision_at_five_uses_a_fixed_denominator_and_separates_no_answer() -> None:
    assert score_case(expected_id="expected", result_ids=["expected"] * 1) == {
        "precision_at_5": 0.2,
        "recall_at_5": 1.0,
        "no_answer_accuracy": None,
    }
    assert score_case(expected_id=None, result_ids=[]) == {
        "precision_at_5": None,
        "recall_at_5": None,
        "no_answer_accuracy": 1.0,
    }
