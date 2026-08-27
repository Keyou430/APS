"""Phase A1 contract tests for the platform-owned WebEvidence validator.

These tests define the single source-of-truth contract for web evidence:
provider event payloads only (never model text), strict URL/time validation,
and run correlation binding. Chat and Pipeline must both consume this module.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.web_evidence import (
    WEB_SEARCH_EVENT_COMPLETED,
    WebEvidence,
    WebEvidenceRejected,
    parse_web_search_event,
    validate_web_evidence,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
RUN_CORRELATION_ID = "corr-run-0001"


def _provider_result(**overrides: object) -> dict:
    result: dict = {
        "provider": "exa",
        "url": "https://example.com/ai-report",
        "title": "Industry AI report",
        "published_at": "2026-08-01T00:00:00Z",
        "searched_at": "2026-08-22T11:00:00Z",
        "correlation_id": RUN_CORRELATION_ID,
    }
    result.update(overrides)
    return {key: value for key, value in result.items() if value is not ...}


async def test_valid_provider_result_parses_into_web_evidence() -> None:
    evidence = validate_web_evidence(
        _provider_result(), correlation_id=RUN_CORRELATION_ID, now=NOW
    )
    assert isinstance(evidence, WebEvidence)
    assert evidence.provider == "exa"
    assert evidence.url == "https://example.com/ai-report"
    assert evidence.published_at is not None and evidence.published_at.year == 2026
    assert evidence.searched_at is not None and evidence.searched_at.hour == 11
    assert evidence.correlation_id == RUN_CORRELATION_ID


async def test_optional_provider_fields_are_preserved() -> None:
    evidence = validate_web_evidence(
        _provider_result(
            source_id="provider-result-17",
            retrieved_at="2026-08-22T11:05:00Z",
            query="latest ai news",
            snippet="A short sanitized snippet",
            content_sha256="a" * 64,
        ),
        correlation_id=RUN_CORRELATION_ID,
        now=NOW,
    )
    assert evidence.source_id == "provider-result-17"
    assert evidence.retrieved_at is not None and evidence.retrieved_at.minute == 5
    assert evidence.query == "latest ai news"
    assert evidence.snippet == "A short sanitized snippet"
    assert evidence.content_sha256 == "a" * 64


@pytest.mark.parametrize(
    "field", ["provider", "url", "title", "published_at", "searched_at"]
)
async def test_missing_required_field_is_rejected(field: str) -> None:
    payload = _provider_result()
    payload.pop(field)
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(payload, correlation_id=RUN_CORRELATION_ID, now=NOW)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html;base64,SGVsbG8=",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "not-a-url",
        "",
    ],
)
async def test_disallowed_url_schemes_are_rejected(url: str) -> None:
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(url=url), correlation_id=RUN_CORRELATION_ID, now=NOW
        )


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "localhost",
        "[::1]",
        "10.1.2.3",
        "192.168.3.107",
        "169.254.1.1",
        "172.16.0.9",
        "0.0.0.0",
    ],
)
async def test_loopback_and_private_hosts_are_rejected_by_default(host: str) -> None:
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(url=f"https://{host}/report"),
            correlation_id=RUN_CORRELATION_ID,
            now=NOW,
        )


async def test_loopback_host_allowed_only_in_explicit_test_mode() -> None:
    evidence = validate_web_evidence(
        _provider_result(url="http://127.0.0.1:8080/report"),
        correlation_id=RUN_CORRELATION_ID,
        now=NOW,
        allow_private_hosts=True,
    )
    assert evidence.url == "http://127.0.0.1:8080/report"


async def test_future_published_at_is_rejected() -> None:
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(published_at="2027-01-01T00:00:00Z"),
            correlation_id=RUN_CORRELATION_ID,
            now=NOW,
        )


async def test_searched_at_after_now_is_rejected() -> None:
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(searched_at=(NOW + timedelta(hours=1)).isoformat()),
            correlation_id=RUN_CORRELATION_ID,
            now=NOW,
        )


async def test_searched_at_before_published_at_is_rejected() -> None:
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(
                published_at="2026-08-20T00:00:00Z",
                searched_at="2026-08-19T00:00:00Z",
            ),
            correlation_id=RUN_CORRELATION_ID,
            now=NOW,
        )


async def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(published_at="2026-08-01T00:00:00"),
            correlation_id=RUN_CORRELATION_ID,
            now=NOW,
        )
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(searched_at="2026-08-22T11:00:00"),
            correlation_id=RUN_CORRELATION_ID,
            now=NOW,
        )


async def test_unparseable_datetimes_are_rejected() -> None:
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(published_at="yesterday"),
            correlation_id=RUN_CORRELATION_ID,
            now=NOW,
        )


async def test_correlation_mismatch_is_rejected() -> None:
    payload = _provider_result(correlation_id="corr-run-9999")
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(payload, correlation_id=RUN_CORRELATION_ID, now=NOW)


async def test_missing_correlation_on_result_is_rejected() -> None:
    payload = _provider_result()
    payload.pop("correlation_id")
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(payload, correlation_id=RUN_CORRELATION_ID, now=NOW)


async def test_blank_title_is_rejected() -> None:
    with pytest.raises(WebEvidenceRejected):
        validate_web_evidence(
            _provider_result(title="   "),
            correlation_id=RUN_CORRELATION_ID,
            now=NOW,
        )


async def test_parse_web_search_event_accepts_completed_results() -> None:
    event = {
        "event": WEB_SEARCH_EVENT_COMPLETED,
        "correlation_id": RUN_CORRELATION_ID,
        "provider": "exa",
        "results": [_provider_result()],
    }
    parsed = parse_web_search_event(event, correlation_id=RUN_CORRELATION_ID, now=NOW)
    assert parsed is not None
    assert parsed.event == WEB_SEARCH_EVENT_COMPLETED
    assert len(parsed.evidence) == 1
    assert parsed.evidence[0].url == "https://example.com/ai-report"
    assert parsed.rejections == []


async def test_parse_web_search_event_skips_invalid_results_but_keeps_valid_ones() -> None:
    event = {
        "event": WEB_SEARCH_EVENT_COMPLETED,
        "correlation_id": RUN_CORRELATION_ID,
        "provider": "exa",
        "results": [
            _provider_result(),
            _provider_result(url="javascript:alert(1)"),
            _provider_result(correlation_id="corr-other-run"),
        ],
    }
    parsed = parse_web_search_event(event, correlation_id=RUN_CORRELATION_ID, now=NOW)
    assert parsed is not None
    assert [item.url for item in parsed.evidence] == ["https://example.com/ai-report"]
    assert len(parsed.rejections) == 2


async def test_parse_web_search_event_ignores_unknown_event_names() -> None:
    parsed = parse_web_search_event(
        {"event": "tool.terminal.executed"}, correlation_id=RUN_CORRELATION_ID, now=NOW
    )
    assert parsed is None


async def test_parse_web_search_event_rejects_cross_run_events() -> None:
    event = {
        "event": WEB_SEARCH_EVENT_COMPLETED,
        "correlation_id": "corr-run-9999",
        "provider": "exa",
        "results": [_provider_result()],
    }
    parsed = parse_web_search_event(event, correlation_id=RUN_CORRELATION_ID, now=NOW)
    assert parsed is not None
    assert parsed.evidence == []
    assert len(parsed.rejections) == 1
