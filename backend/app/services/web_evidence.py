"""Platform-owned WebEvidence contract (Phase 1, section A1).

Every web citation shown by the platform must originate from a provider/tool
event payload parsed by this module. Model-generated text is never a valid
input: callers may only pass structures decoded from provider/tool events, so
free-written model fields can never enter the evidence set.

The validator is intentionally strict and fail-closed:
- URL must be http(s) with a public host (loopback/private ranges rejected
  unless the caller explicitly allows them for hermetic tests).
- Times must be timezone-aware ISO-8601; ``published_at`` may not be in the
  future and ``searched_at`` may be neither in the future nor earlier than
  ``published_at``.
- The result must carry the correlation id of the run that produced it.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

WEB_SEARCH_EVENT_STARTED = "web.search.started"
WEB_SEARCH_EVENT_COMPLETED = "web.search.completed"
WEB_SEARCH_EVENT_FAILED = "web.search.failed"

#: Upstream event names recognized as web-search activity. Anything else is
#: passed through untouched by callers and never becomes evidence. These shapes
#: stay inactive until the A0 provider probe confirms them against the pinned
#: Hermes deployment; unconfirmed shapes simply never match.
WEB_SEARCH_SOURCE_EVENT_NAMES: frozenset[str] = frozenset(
    {
        WEB_SEARCH_EVENT_COMPLETED,
        "tool.web_search",
    }
)

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

_REJECTION_TOLERANCE_SECONDS = 0


class WebEvidenceRejected(ValueError):
    """A candidate result failed platform validation."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class WebEvidence:
    provider: str
    url: str
    title: str
    published_at: datetime
    searched_at: datetime
    correlation_id: str
    retrieved_at: datetime | None = None
    source_id: str | None = None
    query: str | None = None
    snippet: str | None = None
    content_sha256: str | None = None

    def as_source_dict(self) -> dict[str, str]:
        """Stable persistence shape shared by chat and pipeline sources."""
        payload: dict[str, str] = {
            "provider": self.provider,
            "url": self.url,
            "title": self.title,
            "published_at": self.published_at.isoformat(),
            "searched_at": self.searched_at.isoformat(),
            "correlation_id": self.correlation_id,
        }
        if self.retrieved_at is not None:
            payload["retrieved_at"] = self.retrieved_at.isoformat()
        if self.source_id:
            payload["source_id"] = self.source_id
        if self.query:
            payload["query"] = self.query
        if self.content_sha256:
            payload["content_sha256"] = self.content_sha256
        return payload


@dataclass(frozen=True)
class ParsedWebSearchEvent:
    event: str
    evidence: list[WebEvidence] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    provider: str | None = None


def _parse_datetime(value: object, *, reason_code: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise WebEvidenceRejected(reason_code)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise WebEvidenceRejected(reason_code) from exc
    if parsed.tzinfo is None:
        raise WebEvidenceRejected(f"{reason_code}_naive")
    return parsed.astimezone(UTC)


def _host_is_public(host: str) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        # DNS names other than localhost are treated as public; local names
        # that only resolve inside the perimeter cannot be screened here and
        # the scheme check plus TLS boundary remain the guard.
        lowered = host.lower()
        return lowered != "localhost" and not lowered.endswith(".localhost") and not lowered.endswith(".internal")
    if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_unspecified or addr.is_reserved:
        return False
    return True


def validate_web_evidence(
    candidate: dict[str, Any],
    *,
    correlation_id: str,
    now: datetime,
    allow_private_hosts: bool = False,
) -> WebEvidence:
    """Validate one provider result against the platform contract."""
    if not isinstance(candidate, dict):
        raise WebEvidenceRejected("result_not_an_object")

    provider = candidate.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise WebEvidenceRejected("provider_missing")

    url = candidate.get("url")
    if not isinstance(url, str) or not url.strip():
        raise WebEvidenceRejected("url_missing")
    parsed_url = urlparse(url.strip())
    if parsed_url.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise WebEvidenceRejected("url_scheme_not_allowed")
    if not parsed_url.hostname:
        raise WebEvidenceRejected("url_host_missing")
    if not allow_private_hosts and not _host_is_public(parsed_url.hostname):
        raise WebEvidenceRejected("url_host_not_public")

    title = candidate.get("title")
    if not isinstance(title, str) or not title.strip():
        raise WebEvidenceRejected("title_missing")

    published_at = _parse_datetime(
        candidate.get("published_at"), reason_code="published_at_invalid"
    )
    searched_at = _parse_datetime(
        candidate.get("searched_at"), reason_code="searched_at_invalid"
    )
    if published_at > now.astimezone(UTC) and (
        published_at - now.astimezone(UTC)
    ).total_seconds() > _REJECTION_TOLERANCE_SECONDS:
        raise WebEvidenceRejected("published_at_in_future")
    if searched_at > now.astimezone(UTC):
        raise WebEvidenceRejected("searched_at_in_future")
    if searched_at < published_at:
        raise WebEvidenceRejected("searched_at_before_published_at")

    result_correlation = candidate.get("correlation_id")
    if not isinstance(result_correlation, str) or not result_correlation.strip():
        raise WebEvidenceRejected("correlation_id_missing")
    if result_correlation != correlation_id:
        raise WebEvidenceRejected("correlation_mismatch")

    retrieved_at: datetime | None = None
    if candidate.get("retrieved_at") is not None:
        retrieved_at = _parse_datetime(
            candidate.get("retrieved_at"), reason_code="retrieved_at_invalid"
        )

    snippet = candidate.get("snippet")
    if snippet is not None and not isinstance(snippet, str):
        snippet = None

    content_sha256 = candidate.get("content_sha256")
    if content_sha256 is not None and (
        not isinstance(content_sha256, str) or not content_sha256.strip()
    ):
        content_sha256 = None

    return WebEvidence(
        provider=provider.strip(),
        url=url.strip(),
        title=title.strip(),
        published_at=published_at,
        searched_at=searched_at,
        correlation_id=result_correlation,
        retrieved_at=retrieved_at,
        source_id=candidate.get("source_id") if isinstance(candidate.get("source_id"), str) else None,
        query=candidate.get("query") if isinstance(candidate.get("query"), str) else None,
        snippet=snippet,
        content_sha256=content_sha256,
    )


def parse_web_search_event(
    event: dict[str, Any],
    *,
    correlation_id: str,
    now: datetime,
    allow_private_hosts: bool = False,
) -> ParsedWebSearchEvent | None:
    """Parse one provider/tool event into validated evidence.

    Returns ``None`` for event names outside the recognized web-search
    contract; unknown events are the caller's concern (log passthrough) but can
    never contribute evidence.
    """
    if not isinstance(event, dict):
        return None
    name = event.get("event") or event.get("type")
    if not isinstance(name, str) or name not in WEB_SEARCH_SOURCE_EVENT_NAMES:
        return None

    envelope_correlation = event.get("correlation_id")
    if isinstance(envelope_correlation, str) and envelope_correlation != correlation_id:
        # Cross-run contamination: the event belongs to a different run, so no
        # result inside it may enter this run's evidence set.
        return ParsedWebSearchEvent(
            event=name,
            evidence=[],
            rejections=["event_correlation_mismatch"] * max(len(event.get("results") or []), 1),
            provider=event.get("provider") if isinstance(event.get("provider"), str) else None,
        )

    provider = event.get("provider") if isinstance(event.get("provider"), str) else None
    results = event.get("results")
    if not isinstance(results, list):
        results = []

    evidence: list[WebEvidence] = []
    rejections: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            rejections.append("result_not_an_object")
            continue
        enriched = dict(item)
        enriched.setdefault("correlation_id", event.get("correlation_id"))
        if provider:
            enriched.setdefault("provider", provider)
        try:
            evidence.append(
                validate_web_evidence(
                    enriched,
                    correlation_id=correlation_id,
                    now=now,
                    allow_private_hosts=allow_private_hosts,
                )
            )
        except WebEvidenceRejected as rejection:
            rejections.append(rejection.reason_code)

    return ParsedWebSearchEvent(
        event=name,
        evidence=evidence,
        rejections=rejections,
        provider=provider,
    )


def evidence_for_run(
    evidence: list[WebEvidence], *, correlation_id: str
) -> list[WebEvidence]:
    """Only evidence bound to the given run correlation is usable."""
    return [item for item in evidence if item.correlation_id == correlation_id]


def resolve_hostname(host: str) -> str | None:  # pragma: no cover - diagnostic helper
    """Diagnostic helper for the A0 probe report; never used in validation."""
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None
