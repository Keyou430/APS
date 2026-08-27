"""Phase A2 chat-path contract tests: web evidence via SSE + persistence.

Only provider/tool events may become web evidence. The relay must emit
platform events (web.search.started/completed/failed) carrying the run
correlation id, persist validated evidence per chat turn, and restore it from
history. Unrecognized events pass through without becoming evidence.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ChatTurn, ChatTurnWebSource
from app.routers import chat as chat_router
from app.services.hermes_client import HermesClient


async def _web_source_rows_for_session(session_id: int) -> list[ChatTurnWebSource]:
    async with SessionLocal() as db:
        turn_ids = list(
            (
                await db.scalars(
                    select(ChatTurn.id).where(ChatTurn.chat_session_id == session_id)
                )
            ).all()
        )
        if not turn_ids:
            return []
        return list(
            (
                await db.scalars(
                    select(ChatTurnWebSource).where(
                        ChatTurnWebSource.chat_turn_id.in_(turn_ids)
                    )
                )
            ).all()
        )

pytestmark = pytest.mark.asyncio


def _result_payload(correlation_id: str, *, url: str = "https://example.com/ai-news") -> dict:
    now = datetime.now(UTC)
    return {
        "provider": "exa",
        "url": url,
        "title": "Latest AI news",
        "published_at": (now - timedelta(days=2)).isoformat(),
        "searched_at": (now - timedelta(hours=1)).isoformat(),
        "correlation_id": correlation_id,
    }


class WebSearchMockHermes(HermesClient):
    """Mock provider whose stream emits one web_search tool event."""

    def __init__(self, web_event: dict | None) -> None:
        super().__init__()
        self._web_event = web_event

    async def stream_events(self, run_id, session_id, prompt, *, context=None):
        yield self._event("run.created", {"run_id": run_id, "session_id": session_id})
        if self._web_event is not None:
            yield self._event("tool.web_search", self._web_event)
        answer = "Mock answer with search"
        self._messages[session_id].append(
            {
                "id": f"assistant-{run_id}",
                "role": "assistant",
                "content": answer,
                "created_at": datetime.now(UTC),
            }
        )
        yield self._event("response.output_text.delta", {"delta": answer})
        yield self._event(
            "response.completed",
            {"event": "run.completed", "run_id": run_id, "output": answer},
        )


def _sse_event_names(raw: str) -> list[str]:
    return [
        line[len("event: ") :].strip()
        for line in raw.splitlines()
        if line.startswith("event: ")
    ]


def _sse_payload(raw: str, event_name: str) -> dict:
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if line == f"event: {event_name}":
            for follow in lines[index + 1 :]:
                if follow.startswith("data: "):
                    return json.loads(follow[len("data: ") :])
    raise AssertionError(f"event {event_name} not found")


async def _send_and_collect(
    client: AsyncClient, headers: dict[str, str], provider: WebSearchMockHermes, monkeypatch
) -> tuple[int, str]:
    monkeypatch.setattr(chat_router, "hermes_client", provider)
    created = await client.post(
        "/api/chat/sessions",
        headers=headers,
        json={"title": "Web evidence probe", "surface": "agent"},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    sent = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "Search the web for the latest AI news"},
    )
    assert sent.status_code == 200, sent.text
    return session_id, sent.text


async def test_valid_web_search_events_are_relayed_and_persisted(
    client: AsyncClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    correlation_probe: dict[str, str] = {}

    class CapturingProvider(WebSearchMockHermes):
        async def create_response(self, content, session_id, *, context=None, **kwargs):
            correlation_probe["correlation_id"] = context.correlation_id
            return await super().create_response(content, session_id, context=context, **kwargs)

        async def stream_events(self, run_id, session_id, prompt, *, context=None):
            self._web_event = {
                "event": "tool.web_search",
                "correlation_id": correlation_probe["correlation_id"],
                "provider": "exa",
                "results": [_result_payload(correlation_probe["correlation_id"])],
            }
            async for event in super().stream_events(
                run_id, session_id, prompt, context=context
            ):
                yield event

    provider = CapturingProvider(None)
    session_id, raw = await _send_and_collect(client, admin_headers, provider, monkeypatch)

    names = _sse_event_names(raw)
    assert "web.search.started" in names
    assert "web.search.completed" in names
    completed = _sse_payload(raw, "web.search.completed")
    assert completed["correlation_id"] == correlation_probe["correlation_id"]
    assert completed["sources"][0]["url"].startswith("https://example.com/")

    async with SessionLocal() as db:
        turn = await db.scalar(select(ChatTurn).where(ChatTurn.chat_session_id == session_id))
        assert turn is not None
        rows = list(
            (
                await db.scalars(
                    select(ChatTurnWebSource)
                    .where(ChatTurnWebSource.chat_turn_id == turn.id)
                    .order_by(ChatTurnWebSource.ordinal)
                )
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].provider == "exa"
        assert rows[0].url.startswith("https://example.com/")
        assert rows[0].correlation_id == correlation_probe["correlation_id"]
        turn_id = turn.id

    history = await client.get(
        f"/api/chat/sessions/{session_id}/messages", headers=admin_headers
    )
    assert history.status_code == 200
    assistant_items = [item for item in history.json()["items"] if item.get("role") == "assistant"]
    assert assistant_items, "assistant message missing from history"
    assert assistant_items[-1]["turn_id"] == turn_id
    web_sources = assistant_items[-1]["web_sources"]
    assert web_sources[0]["url"].startswith("https://example.com/")
    assert web_sources[0]["provider"] == "exa"


@pytest.mark.parametrize("event_order", ["empty_then_valid", "valid_then_empty"])
async def test_multiple_web_search_events_emit_one_final_aggregate_status(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch,
    event_order: str,
) -> None:
    correlation_probe: dict[str, str] = {}

    class MultiEventProvider(WebSearchMockHermes):
        async def create_response(self, content, session_id, *, context=None, **kwargs):
            correlation_probe["correlation_id"] = context.correlation_id
            return await super().create_response(content, session_id, context=context, **kwargs)

        async def stream_events(self, run_id, session_id, prompt, *, context=None):
            correlation_id = correlation_probe["correlation_id"]
            valid = _result_payload(correlation_id)
            empty = {
                "event": "tool.web_search",
                "correlation_id": correlation_id,
                "provider": "exa",
                "results": [],
            }
            valid_event = {**empty, "results": [valid]}
            events = [empty, valid_event] if event_order == "empty_then_valid" else [valid_event, empty]
            yield self._event("run.created", {"run_id": run_id, "session_id": session_id})
            for payload in events:
                yield self._event("tool.web_search", payload)
            answer = "Mock answer with search"
            self._messages[session_id].append(
                {
                    "id": f"assistant-{run_id}",
                    "role": "assistant",
                    "content": answer,
                    "created_at": datetime.now(UTC),
                }
            )
            yield self._event("response.output_text.delta", {"delta": answer})
            yield self._event(
                "response.completed",
                {"event": "run.completed", "run_id": run_id, "output": answer},
            )

    provider = MultiEventProvider(None)
    session_id, raw = await _send_and_collect(client, admin_headers, provider, monkeypatch)

    names = _sse_event_names(raw)
    assert names.count("web.search.started") == 1
    assert names.count("web.search.completed") == 1
    assert "web.search.failed" not in names
    completed = _sse_payload(raw, "web.search.completed")
    assert len(completed["sources"]) == 1
    assert len(await _web_source_rows_for_session(session_id)) == 1


async def test_unknown_web_events_never_become_evidence(
    client: AsyncClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    class UnknownEventProvider(WebSearchMockHermes):
        async def stream_events(self, run_id, session_id, prompt, *, context=None):
            self._web_event = None
            original = super().stream_events(run_id, session_id, prompt, context=context)
            async for event in original:
                yield event
                if event.startswith("event: run.created"):
                    yield self._event(
                        "tool.terminal.executed", {"run_id": run_id, "status": "done"}
                    )

    provider = UnknownEventProvider(None)
    session_id, raw = await _send_and_collect(client, admin_headers, provider, monkeypatch)

    names = _sse_event_names(raw)
    assert "tool.terminal.executed" in names  # passed through untouched
    assert not any(name.startswith("web.search.") for name in names)

    assert await _web_source_rows_for_session(session_id) == []


async def test_invalid_web_results_emit_failed_and_persist_nothing(
    client: AsyncClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    correlation_probe: dict[str, str] = {}

    class InvalidResultsProvider(WebSearchMockHermes):
        async def create_response(self, content, session_id, *, context=None, **kwargs):
            correlation_probe["correlation_id"] = context.correlation_id
            return await super().create_response(content, session_id, context=context, **kwargs)

        async def stream_events(self, run_id, session_id, prompt, *, context=None):
            now = datetime.now(UTC)
            self._web_event = {
                "event": "tool.web_search",
                "correlation_id": correlation_probe["correlation_id"],
                "provider": "exa",
                "results": [
                    _result_payload(
                        correlation_probe["correlation_id"],
                        url="javascript:alert(1)",
                    ),
                    {
                        **_result_payload(correlation_probe["correlation_id"]),
                        "published_at": (now + timedelta(days=30)).isoformat(),
                    },
                ],
            }
            async for event in super().stream_events(
                run_id, session_id, prompt, context=context
            ):
                yield event

    provider = InvalidResultsProvider(None)
    session_id, raw = await _send_and_collect(client, admin_headers, provider, monkeypatch)

    names = _sse_event_names(raw)
    assert "web.search.started" in names
    assert "web.search.failed" in names
    assert "web.search.completed" not in names
    failed = _sse_payload(raw, "web.search.failed")
    assert failed["reason"] == "web_evidence_unavailable"
    assert failed["rejections"]

    assert await _web_source_rows_for_session(session_id) == []


async def test_cross_run_web_events_are_rejected(
    client: AsyncClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    provider = WebSearchMockHermes(
        {
            "event": "tool.web_search",
            "correlation_id": "corr-run-foreign",
            "provider": "exa",
            "results": [_result_payload("corr-run-foreign")],
        }
    )
    session_id, raw = await _send_and_collect(client, admin_headers, provider, monkeypatch)

    names = _sse_event_names(raw)
    assert "web.search.failed" in names
    assert "web.search.completed" not in names

    assert await _web_source_rows_for_session(session_id) == []
