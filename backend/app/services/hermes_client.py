from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import httpx
from pydantic import SecretStr

from app.config import get_settings


@dataclass(frozen=True)
class HermesRequestContext:
    """Server-owned scope passed to Hermes without embedding policy in the client."""

    user_id: int
    organization_id: str | None
    session_id: str
    correlation_id: str

    @property
    def profile_key(self) -> str:
        organization = self.organization_id or "unassigned"
        return f"org:{organization}:user:{self.user_id}"


class HermesUpstreamError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)


def sse_payloads(streamed_events: list[str]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for event in streamed_events:
        data_lines = [
            line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")
        ]
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise HermesUpstreamError("Hermes event stream returned invalid JSON") from exc
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def associate_terminal_message(
    *,
    before_messages: list[dict[str, Any]],
    history_reads: list[list[dict[str, Any]]],
    streamed_events: list[str],
) -> str:
    if not history_reads:
        raise HermesUpstreamError("Hermes did not return session history")
    id_sequences = {
        tuple(str(message.get("id")) for message in messages)
        for messages in history_reads
    }
    if len(id_sequences) != 1:
        raise HermesUpstreamError("Hermes history message ids were not stable")

    terminal_events = [
        payload
        for payload in sse_payloads(streamed_events)
        if payload.get("event") == "run.completed"
    ]
    if len(terminal_events) != 1 or not isinstance(terminal_events[0].get("output"), str):
        raise HermesUpstreamError("Hermes run did not expose one terminal output")

    before_ids = {str(message.get("id")) for message in before_messages}
    terminal_output = terminal_events[0]["output"]
    if not terminal_output.strip():
        raise HermesUpstreamError("Hermes run did not expose non-empty terminal output")
    matches = [
        message
        for message in history_reads[-1]
        if str(message.get("id")) not in before_ids
        and message.get("role") == "assistant"
        and isinstance(message.get("content"), str)
        and message["content"].strip()
        and message.get("content") == terminal_output
    ]
    if len(matches) != 1 or matches[0].get("id") is None:
        raise HermesUpstreamError(
            "Hermes terminal output did not match exactly one new assistant message"
        )
    return str(matches[0]["id"])


class HermesProvider(Protocol):
    async def create_response(
        self,
        content: str,
        session_id: str,
        *,
        context: HermesRequestContext | None = None,
        previous_response_id: str | None = None,
        idempotency_key: str | None = None,
        instructions: str | None = None,
    ) -> str: ...

    async def stream_events(
        self,
        run_id: str,
        session_id: str,
        prompt: str | None = None,
        *,
        context: HermesRequestContext | None = None,
    ) -> AsyncIterator[str]: ...

    async def get_session_messages(
        self,
        session_id: str,
        *,
        context: HermesRequestContext | None = None,
    ) -> list[dict[str, Any]]: ...


class HermesClient:
    """Compatibility mock for local frontend demos and backend contract tests."""

    def __init__(self) -> None:
        self._messages: dict[str, list[dict[str, Any]]] = defaultdict(list)

    async def create_response(
        self,
        content: str,
        session_id: str,
        *,
        context: HermesRequestContext | None = None,
        previous_response_id: str | None = None,
        idempotency_key: str | None = None,
        instructions: str | None = None,
    ) -> str:
        del context, previous_response_id, idempotency_key, instructions
        now = datetime.now(UTC)
        self._messages[session_id].append(
            {"id": uuid4().hex, "role": "user", "content": content, "created_at": now}
        )
        return uuid4().hex

    async def stream_events(
        self,
        run_id: str,
        session_id: str,
        prompt: str,
        *,
        context: HermesRequestContext | None = None,
    ) -> AsyncIterator[str]:
        del context
        response = f"Mock Hermes response to: {prompt}"
        chunks = response.split(" ")
        built: list[str] = []
        yield self._event("run.created", {"run_id": run_id, "session_id": session_id})
        for index, chunk in enumerate(chunks):
            text = chunk + (" " if index < len(chunks) - 1 else "")
            built.append(text)
            yield self._event("response.output_text.delta", {"delta": text})
            await asyncio.sleep(0)
        self._messages[session_id].append(
            {
                "id": uuid4().hex,
                "role": "assistant",
                "content": "".join(built),
                "created_at": datetime.now(UTC),
            }
        )
        yield self._event(
            "response.completed",
            {"event": "run.completed", "run_id": run_id, "output": "".join(built)},
        )

    async def get_session_messages(
        self,
        session_id: str,
        *,
        context: HermesRequestContext | None = None,
    ) -> list[dict[str, Any]]:
        del context
        return list(self._messages[session_id])

    async def create_openai_response(
        self,
        content: str,
        *,
        previous_response_id: str | None = None,
        context: HermesRequestContext | None = None,
    ) -> dict[str, Any]:
        del previous_response_id, context
        return {"id": uuid4().hex, "output": [{"type": "message", "content": content}]}

    async def stop_run(
        self,
        run_id: str,
        *,
        context: HermesRequestContext | None = None,
    ) -> dict[str, Any]:
        del context
        return {"run_id": run_id, "status": "stopped"}

    async def approve_run(
        self,
        run_id: str,
        choice: str,
        *,
        context: HermesRequestContext | None = None,
    ) -> dict[str, Any]:
        del context
        return {"run_id": run_id, "choice": choice, "resolved": 1}

    @staticmethod
    def _event(event: str, data: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class HermesHttpClient:
    """Small platform-owned adapter for the pinned Hermes API server."""

    _RETRYABLE_CONNECTION_ERRORS = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadError,
        httpx.RemoteProtocolError,
        httpx.WriteError,
    )

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | SecretStr,
        timeout_seconds: float = 30.0,
        connect_timeout_seconds: float = 5.0,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        secret = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not secret:
            raise ValueError("Hermes API key is required for the HTTP adapter")
        self.base_url = base_url.rstrip("/")
        self.api_key = secret
        self.timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.transport = transport

    async def create_response(
        self,
        content: str,
        session_id: str,
        *,
        context: HermesRequestContext | None = None,
        previous_response_id: str | None = None,
        idempotency_key: str | None = None,
        instructions: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {"input": content, "session_id": session_id}
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if instructions:
            payload["instructions"] = instructions
        body = await self._request_json(
            "POST",
            "/v1/runs",
            payload=payload,
            context=context,
            idempotency_key=idempotency_key or f"run-{uuid4().hex}",
        )
        run_id = body.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise HermesUpstreamError("Hermes run response did not include run_id")
        return run_id

    async def create_openai_response(
        self,
        content: str,
        *,
        previous_response_id: str | None = None,
        context: HermesRequestContext | None = None,
    ) -> dict[str, Any]:
        body, _session_id = await self.create_openai_response_with_metadata(
            content,
            previous_response_id=previous_response_id,
            context=context,
        )
        return body

    async def create_openai_response_with_metadata(
        self,
        content: str,
        *,
        previous_response_id: str | None = None,
        context: HermesRequestContext | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        payload: dict[str, Any] = {
            "input": content,
            "store": True,
        }
        if context is not None:
            payload["session_id"] = context.session_id
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        idempotency_key = f"response-{uuid4().hex}"
        try:
            body, headers = await self._request_json_with_headers(
                "POST",
                "/v1/responses",
                payload=payload,
                context=context,
                idempotency_key=idempotency_key,
            )
        except HermesUpstreamError as exc:
            if exc.status_code != 404:
                raise
            chat_body, headers = await self._request_json_with_headers(
                "POST",
                "/v1/chat/completions",
                payload={
                    "model": "hermes-agent",
                    "messages": [{"role": "user", "content": content}],
                    "stream": False,
                },
                context=context,
                idempotency_key=idempotency_key,
            )
            body = self._chat_completion_as_response(chat_body)
        return body, headers.get("X-Hermes-Session-Id")

    @staticmethod
    def _chat_completion_as_response(body: dict[str, Any]) -> dict[str, Any]:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HermesUpstreamError("Hermes chat completion did not include choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if isinstance(content, list):
            text = "".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, Mapping)
            )
        else:
            text = str(content or "")
        if not text.strip():
            raise HermesUpstreamError("Hermes chat completion did not include text")
        return {
            "id": str(body.get("id") or uuid4().hex),
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        }

    async def stream_events(
        self,
        run_id: str,
        session_id: str,
        prompt: str | None = None,
        *,
        context: HermesRequestContext | None = None,
    ) -> AsyncIterator[str]:
        del prompt
        if context is not None and context.session_id != session_id:
            raise ValueError("Hermes request context session does not match the run session")
        path = f"/v1/runs/{run_id}/events"
        headers = self._headers(context=context)
        try:
            async with self._client() as client:
                async with client.stream("GET", path, headers=headers) as response:
                    if response.status_code >= 400:
                        raise HermesUpstreamError(
                            f"Hermes upstream returned HTTP {response.status_code}",
                            status_code=response.status_code,
                        )
                    event_name: str | None = None
                    data_lines: list[str] = []
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            event_name = line[6:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                        elif not line:
                            formatted = self._format_sse_event(
                                event_name,
                                data_lines,
                                correlation_id=context.correlation_id if context else None,
                            )
                            if formatted is not None:
                                yield formatted
                            event_name = None
                            data_lines = []
                    formatted = self._format_sse_event(
                        event_name,
                        data_lines,
                        correlation_id=context.correlation_id if context else None,
                    )
                    if formatted is not None:
                        yield formatted
        except HermesUpstreamError:
            raise
        except self._RETRYABLE_CONNECTION_ERRORS as exc:
            yield self._event(
                "upstream.disconnected",
                {"run_id": run_id, "session_id": session_id, "retryable": True},
            )
            raise HermesUpstreamError(
                "Hermes event stream disconnected",
                retryable=True,
            ) from exc

    async def get_session_messages(
        self,
        session_id: str,
        *,
        context: HermesRequestContext | None = None,
    ) -> list[dict[str, Any]]:
        try:
            body = await self._request_json(
                "GET",
                f"/api/sessions/{session_id}/messages",
                context=context,
            )
        except HermesUpstreamError as exc:
            if exc.status_code == 404:
                return []
            raise
        raw_messages = body.get("data")
        if not isinstance(raw_messages, list):
            raise HermesUpstreamError("Hermes session history response did not include data")
        return [self._map_message(item) for item in raw_messages if isinstance(item, dict)]

    async def stop_run(
        self,
        run_id: str,
        *,
        context: HermesRequestContext | None = None,
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"/v1/runs/{run_id}/stop",
            payload={},
            context=context,
        )

    async def approve_run(
        self,
        run_id: str,
        choice: str,
        *,
        context: HermesRequestContext | None = None,
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"/v1/runs/{run_id}/approval",
            payload={"choice": choice},
            context=context,
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        context: HermesRequestContext | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body, _headers = await self._request_json_with_headers(
            method,
            path,
            payload=payload,
            context=context,
            idempotency_key=idempotency_key,
        )
        return body

    async def _request_json_with_headers(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        context: HermesRequestContext | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], Mapping[str, str]]:
        headers = self._headers(context=context, idempotency_key=idempotency_key)
        retryable = method in {"GET", "HEAD"} or idempotency_key is not None
        for attempt in range(self.max_retries + 1):
            try:
                async with self._client() as client:
                    response = await client.request(
                        method,
                        path,
                        json=payload,
                        headers=headers,
                    )
                if response.status_code >= 400:
                    raise HermesUpstreamError(
                        f"Hermes upstream returned HTTP {response.status_code}",
                        status_code=response.status_code,
                    )
                body = response.json()
                if not isinstance(body, dict):
                    raise HermesUpstreamError("Hermes upstream returned a non-object payload")
                return body, response.headers
            except HermesUpstreamError:
                raise
            except self._RETRYABLE_CONNECTION_ERRORS as exc:
                if not retryable or attempt >= self.max_retries:
                    raise HermesUpstreamError(
                        "Hermes upstream connection failed",
                        retryable=retryable,
                    ) from exc
                if self.retry_backoff_seconds:
                    await asyncio.sleep(self.retry_backoff_seconds * (attempt + 1))
            except (httpx.TimeoutException, ValueError) as exc:
                raise HermesUpstreamError(
                    f"Hermes upstream request failed: {type(exc).__name__}"
                ) from exc
        raise HermesUpstreamError("Hermes upstream request exhausted retries")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        )

    def _headers(
        self,
        *,
        context: HermesRequestContext | None,
        idempotency_key: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "X-Correlation-ID": context.correlation_id if context else uuid4().hex,
        }
        if context is not None:
            headers["X-Hermes-Session-Key"] = context.profile_key
            headers["X-Hermes-Session-Id"] = context.session_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @classmethod
    def _format_sse_event(
        cls,
        event_name: str | None,
        data_lines: list[str],
        *,
        correlation_id: str | None = None,
    ) -> str | None:
        if not data_lines:
            return None
        raw = "\n".join(data_lines)
        if raw == "[DONE]":
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HermesUpstreamError("Hermes event stream returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HermesUpstreamError("Hermes event stream returned a non-object event")
        upstream_event = str(payload.get("event") or event_name or "message")
        if upstream_event == "tool.web_search" and correlation_id:
            payload.setdefault("correlation_id", correlation_id)
            results = payload.get("results")
            if isinstance(results, list):
                for result in results:
                    if isinstance(result, dict):
                        result.setdefault("correlation_id", correlation_id)
        mapped_event = {
            "message.delta": "response.output_text.delta",
            "run.completed": "response.completed",
            "run.failed": "response.failed",
            "run.cancelled": "response.cancelled",
        }.get(upstream_event, upstream_event)
        return cls._event(mapped_event, payload)

    @staticmethod
    def _map_message(message: Mapping[str, Any]) -> dict[str, Any]:
        created_at = message.get("created_at") or message.get("timestamp")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(UTC)
        if not isinstance(created_at, datetime):
            created_at = datetime.now(UTC)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return {
            "id": str(message.get("id") or uuid4().hex),
            "role": str(message.get("role") or "assistant"),
            "content": HermesHttpClient._content_text(message.get("content", "")),
            "created_at": created_at,
        }

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, Mapping):
                    text = item.get("text")
                    if text is not None:
                        parts.append(str(text))
            return "".join(parts)
        if content is None:
            return ""
        return str(content)

    @staticmethod
    def _event(event: str, data: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@dataclass(frozen=True)
class HermesClientRouter:
    agent: HermesProvider
    knowledge: HermesProvider

    def client_for(self, backend: str) -> HermesProvider:
        if backend == "agent":
            return self.agent
        if backend == "knowledge":
            return self.knowledge
        raise ValueError(f"Unsupported Hermes backend: {backend}")


def _build_hermes_client() -> HermesProvider:
    settings = get_settings()
    if not settings.hermes_use_http:
        return HermesClient()
    if settings.hermes_api_key is None or not settings.hermes_api_key.get_secret_value():
        raise RuntimeError("HERMES_API_KEY is required when HERMES_USE_HTTP=true")
    return HermesHttpClient(
        settings.hermes_api_url,
        api_key=settings.hermes_api_key,
        timeout_seconds=settings.hermes_http_timeout_seconds,
        connect_timeout_seconds=settings.hermes_http_connect_timeout_seconds,
        max_retries=settings.hermes_http_max_retries,
    )


hermes_client = _build_hermes_client()


def _build_knowledge_hermes_client() -> HermesProvider:
    settings = get_settings()
    if not settings.hermes_use_http:
        return hermes_client
    if settings.hermes_api_key is None or not settings.hermes_api_key.get_secret_value():
        raise RuntimeError("HERMES_API_KEY is required when HERMES_USE_HTTP=true")
    return HermesHttpClient(
        settings.hermes_knowledge_api_url,
        api_key=settings.hermes_api_key,
        timeout_seconds=settings.hermes_http_timeout_seconds,
        connect_timeout_seconds=settings.hermes_http_connect_timeout_seconds,
        max_retries=settings.hermes_http_max_retries,
    )


hermes_knowledge_client = _build_knowledge_hermes_client()
