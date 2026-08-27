"""A0 provider/Hermes web-evidence contract probe.

Runs one authorized smoke against the agent Hermes gateway on both product
paths (ordinary chat run + pipeline response) and records a sanitized
structural report: event names, field names, nested item types, and whether
any structured web-search results (url/title/published_at/...) are exposed.

Never prints API keys, message content, or full URLs (hosts only).
Exit codes: 0 = report produced; 1 = upstream error; 2 = blocked (missing
credentials or configuration).
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.hermes_client import (
    HermesHttpClient,
    HermesRequestContext,
    HermesUpstreamError,
)

URL_PATTERN = re.compile(r"^https?://([^/\s?#]+)", re.IGNORECASE)

WEB_EVIDENCE_INTEREST_FIELDS = (
    "url",
    "title",
    "published_at",
    "searched_at",
    "retrieved_at",
    "results",
    "provider",
    "source_id",
    "query",
)


def sanitize(value: object, *, depth: int = 0) -> object:
    """Return a structure-only description of a payload value."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {str(key): sanitize(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return {
            "__list_length": len(value),
            "__exemplar": sanitize(value[0], depth=depth + 1) if value else None,
        }
    if isinstance(value, str):
        match = URL_PATTERN.match(value)
        if match:
            return f"<url host={match.group(1)}>"
        return f"<str length={len(value)}>"
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return f"<{type(value).__name__}>"
    return f"<{type(value).__name__}>"


def _collect_field_names(value: object, found: set[str], *, depth: int = 0) -> None:
    if depth > 5:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key))
            _collect_field_names(item, found, depth=depth + 1)
    elif isinstance(value, list):
        for item in value[:3]:
            _collect_field_names(item, found, depth=depth + 1)


def classify(field_names: set[str]) -> dict[str, bool]:
    return {
        field: field in field_names for field in WEB_EVIDENCE_INTEREST_FIELDS
    } | {"structured_web_results": bool({"url", "title"} <= field_names)}


def normalize_event(event: object) -> dict[str, object]:
    if isinstance(event, dict):
        return event
    if not isinstance(event, str):
        return {"event": "unknown", "value_type": type(event).__name__}

    event_name = "message"
    data_lines: list[str] = []
    for line in event.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    data_text = "\n".join(data_lines)
    try:
        payload = json.loads(data_text) if data_text else {}
    except json.JSONDecodeError:
        payload = {"data_type": "non_json_string", "data_length": len(data_text)}
    if not isinstance(payload, dict):
        payload = {"data_type": type(payload).__name__}
    payload.setdefault("event", event_name)
    return payload


def parse_tool_output(raw_output: object) -> dict[str, object]:
    if not isinstance(raw_output, str):
        return raw_output if isinstance(raw_output, dict) else {}
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw_output):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw_output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("data" in parsed or "success" in parsed):
            return parsed
    return {}


PROMPT = (
    "Search the web for the latest AI industry news from this week and reply "
    "with one short summary sentence. Use the web_search tool and cite the "
    "actual result URLs. Probe marker: {marker}."
)


async def probe_chat_path(client: HermesHttpClient) -> dict:
    session_id = f"web-evidence-probe-{uuid4().hex}"
    correlation_id = uuid4().hex
    context = HermesRequestContext(
        user_id=0,
        organization_id="probe",
        session_id=session_id,
        correlation_id=correlation_id,
    )
    run_id = await client.create_response(
        PROMPT.format(marker=correlation_id[:8]),
        session_id,
        context=context,
        idempotency_key=f"web-evidence-probe-{uuid4().hex}",
    )
    event_names: list[str] = []
    field_names: set[str] = set()
    raw_events: list[dict] = []
    async for streamed_event in client.stream_events(run_id, session_id, context=context):
        event = normalize_event(streamed_event)
        raw_events.append(event)
        name = event.get("event") or event.get("type")
        event_names.append(str(name))
        _collect_field_names(event, field_names)
    return {
        "path": "chat: POST /v1/runs + GET /v1/runs/{id}/events",
        "run_id": run_id,
        "correlation_id": correlation_id,
        "event_names_in_order": event_names,
        "field_names": sorted(field_names),
        "interest_fields_present": classify(field_names),
        "sanitized_terminal_event": sanitize(raw_events[-1]) if raw_events else None,
        "web_search_event_samples": [
            sanitize(event)
            for event in raw_events
            if "web" in str(event.get("event") or event.get("type") or "").lower()
            or "search" in str(event.get("event") or event.get("type") or "").lower()
        ][:3],
    }


async def probe_pipeline_path(client: HermesHttpClient) -> dict:
    correlation_id = uuid4().hex
    context = HermesRequestContext(
        user_id=0,
        organization_id="probe",
        session_id=f"web-evidence-probe-{uuid4().hex}",
        correlation_id=correlation_id,
    )
    body, session_header = await client.create_openai_response_with_metadata(
        PROMPT.format(marker=correlation_id[:8]), context=context
    )
    output = body.get("output")
    field_names: set[str] = set()
    _collect_field_names(body, field_names)
    output_item_types: list[str] = []
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                output_item_types.append(str(item.get("type") or item.get("event")))
                if item.get("type") == "function_call_output":
                    parsed_tool_output = parse_tool_output(item.get("output"))
                    _collect_field_names(parsed_tool_output, field_names)
    return {
        "path": "pipeline: POST /v1/responses (fallback /v1/chat/completions)",
        "response_id": body.get("id"),
        "correlation_id": correlation_id,
        "hermes_session_header_present": bool(session_header),
        "output_item_types": output_item_types,
        "field_names": sorted(field_names),
        "interest_fields_present": classify(field_names),
        "sanitized_output_structure": sanitize(body),
    }


async def run_probe() -> dict:
    settings = get_settings()
    api_key = (
        settings.hermes_api_key.get_secret_value() if settings.hermes_api_key else ""
    )
    if not api_key:
        return {
            "status": "blocked",
            "blocked_reason": (
                "HERMES_API_KEY is not configured in this environment. The A0 "
                "probe requires an authorized real Hermes gateway (formal "
                "server); credentials live there and formal SSH access is "
                "currently blocked pending the user rebuilding the connection."
            ),
        }
    client = HermesHttpClient(
        settings.hermes_api_url,
        api_key=api_key,
        timeout_seconds=max(settings.hermes_http_timeout_seconds, 120.0),
        connect_timeout_seconds=settings.hermes_http_connect_timeout_seconds,
        max_retries=0,
    )
    chat_report = await probe_chat_path(client)
    pipeline_report = await probe_pipeline_path(client)
    return {
        "status": "ok",
        "hermes_api_url_host": settings.hermes_api_url.split("//")[-1].split("/")[0],
        "chat_path": chat_report,
        "pipeline_path": pipeline_report,
        "notes": (
            "If neither path exposes structured web results "
            "(interest_fields_present.structured_web_results=false), register "
            "web_evidence_provider_contract_missing and keep platform web "
            "evidence fail-closed."
        ),
    }


def main() -> int:
    try:
        report = asyncio.run(run_probe())
    except HermesUpstreamError as exc:
        print(
            json.dumps({"status": "upstream_error", "error": str(exc)[:200]}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
