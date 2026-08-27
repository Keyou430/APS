import importlib.util
from pathlib import Path


PROBE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_web_evidence.py"
SPEC = importlib.util.spec_from_file_location("probe_web_evidence", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_normalize_event_parses_sse_payload() -> None:
    event = probe.normalize_event(
        'event: tool.web_search\ndata: {"results":[{"url":"https://example.com","title":"Source"}]}'
    )

    assert event["event"] == "tool.web_search"
    assert event["results"][0]["url"] == "https://example.com"


def test_normalize_event_preserves_mapping_payload() -> None:
    event = {"event": "run.completed", "output": "done"}

    assert probe.normalize_event(event) is event


def test_classify_reports_structured_web_results() -> None:
    result = probe.classify({"url", "title", "published_at"})

    assert result["url"] is True
    assert result["searched_at"] is False
    assert result["structured_web_results"] is True
