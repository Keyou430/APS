import importlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest


def hermes_client_module():
    try:
        return importlib.import_module("app.services.hermes_client")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Hermes client boundary is missing: {exc}")


def hermes_capabilities_module():
    try:
        return importlib.import_module("app.services.hermes_capabilities")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Hermes capability boundary is missing: {exc}")


def test_probe_script_reaches_fail_closed_missing_key_check():
    environment = os.environ.copy()
    environment.pop("HERMES_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "scripts/probe_hermes.py"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "HERMES_API_KEY is required for the Hermes probe" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def capability_payload(**overrides: object) -> dict:
    features = {
        "responses_api": True,
        "run_submission": True,
        "run_events_sse": True,
        "run_stop": True,
        "run_approval_response": True,
        "session_resources": True,
    }
    features.update(overrides)
    return {
        "object": "hermes.api_server.capabilities",
        "platform": "hermes-agent",
        "features": features,
        "endpoints": {
            "health": {"method": "GET", "path": "/health"},
            "health_detailed": {"method": "GET", "path": "/health/detailed"},
            "capabilities": {"method": "GET", "path": "/v1/capabilities"},
            "responses": {"method": "POST", "path": "/v1/responses"},
            "runs": {"method": "POST", "path": "/v1/runs"},
            "run_events": {"method": "GET", "path": "/v1/runs/{run_id}/events"},
            "run_stop": {"method": "POST", "path": "/v1/runs/{run_id}/stop"},
            "run_approval": {"method": "POST", "path": "/v1/runs/{run_id}/approval"},
            "session_messages": {
                "method": "GET",
                "path": "/api/sessions/{session_id}/messages",
            },
        },
    }


def test_real_hermes_is_the_default_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    monkeypatch.delenv("HERMES_USE_HTTP", raising=False)
    assert Settings(_env_file=None).hermes_use_http is True


@pytest.mark.asyncio
async def test_capability_probe_checks_health_and_required_features():
    module = hermes_capabilities_module()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/health/detailed":
            return httpx.Response(200, json={"status": "ok", "gateway_state": "running"})
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=capability_payload())
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = module.HermesCapabilityClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=transport,
    )

    report = await client.probe()

    assert report.healthy is True
    assert report.missing_features == ()
    assert [request.url.path for request in calls] == [
        "/health",
        "/health/detailed",
        "/v1/capabilities",
    ]
    assert calls[1].headers["Authorization"] == "Bearer test-api-key"
    assert calls[2].headers["Authorization"] == "Bearer test-api-key"


@pytest.mark.asyncio
async def test_capability_probe_fails_closed_when_stop_is_not_supported():
    module = hermes_capabilities_module()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/health/detailed":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json=capability_payload(run_stop=False))

    client = module.HermesCapabilityClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(module.HermesCapabilityError) as caught:
        await client.probe()

    assert caught.value.missing_features == ("run_stop",)


def make_context(module):
    return module.HermesRequestContext(
        user_id=7,
        organization_id="org-2",
        session_id="platform-session-7",
        correlation_id="corr-123",
    )


@pytest.mark.asyncio
async def test_http_adapter_submits_scoped_run_with_bearer_and_idempotency_headers():
    module = hermes_client_module()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"run_id": "run-123", "status": "started"})

    client = module.HermesHttpClient(
        "http://hermes:8642/",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
        retry_backoff_seconds=0,
    )
    context = make_context(module)

    run_id = await client.create_response(
        "hello",
        context.session_id,
        context=context,
        idempotency_key="idem-123",
    )

    assert run_id == "run-123"
    request = requests[0]
    assert request.url.path == "/v1/runs"
    assert json.loads(request.content) == {"input": "hello", "session_id": context.session_id}
    assert request.headers["Authorization"] == "Bearer test-api-key"
    assert request.headers["X-Hermes-Session-Key"] == "org:org-2:user:7"
    assert request.headers["X-Correlation-ID"] == "corr-123"
    assert request.headers["Idempotency-Key"] == "idem-123"


@pytest.mark.asyncio
async def test_http_adapter_submits_conversation_history_for_stateful_runs():
    module = hermes_client_module()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"run_id": "run-follow-up"})

    client = module.HermesHttpClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )
    history = [
        {"role": "user", "content": "我叫小明"},
        {"role": "assistant", "content": "你好，小明。"},
    ]

    await client.create_response(
        "我叫什么？",
        "platform-session-7",
        conversation_history=history,
    )

    assert json.loads(requests[0].content)["conversation_history"] == history


@pytest.mark.asyncio
async def test_http_adapter_adds_instructions_only_for_knowledge_run():
    module = hermes_client_module()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"run_id": "run-knowledge"})

    client = module.HermesHttpClient(
        "http://hermes-knowledge:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )
    await client.create_response(
        "question with authorized excerpts",
        "knowledge-session",
        instructions="platform-owned knowledge instructions",
    )

    assert json.loads(requests[0].content) == {
        "input": "question with authorized excerpts",
        "session_id": "knowledge-session",
        "instructions": "platform-owned knowledge instructions",
    }


def test_hermes_client_router_accepts_only_server_owned_backend_names():
    module = hermes_client_module()
    agent = object()
    knowledge = object()
    router = module.HermesClientRouter(agent=agent, knowledge=knowledge)

    assert router.client_for("agent") is agent
    assert router.client_for("knowledge") is knowledge
    with pytest.raises(ValueError, match="Unsupported Hermes backend"):
        router.client_for("browser-supplied")


@pytest.mark.asyncio
async def test_http_adapter_parses_run_sse_and_maps_terminal_events():
    module = hermes_client_module()
    sse = (
        'data: {"event":"message.delta","run_id":"run-123","delta":"hello"}\n\n'
        'data: {"event":"tool.started","run_id":"run-123"}\n\n'
        'data: {"event":"tool.completed","run_id":"run-123"}\n\n'
        'data: {"event":"tool.web_search","run_id":"run-123","provider":"exa","results":[{"provider":"exa","url":"https://example.com","title":"Source","published_at":"2026-08-22T00:00:00Z","searched_at":"2026-08-23T00:00:00Z"}]}\n\n'
        'data: {"event":"approval.request","run_id":"run-123","command":"echo hi"}\n\n'
        'data: {"event":"run.failed","run_id":"run-123"}\n\n'
        'data: {"event":"run.cancelled","run_id":"run-123"}\n\n'
        'data: {"event":"run.completed","run_id":"run-123","output":"hello"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/runs/run-123/events"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse.encode(),
        )

    client = module.HermesHttpClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    events = [
        event
        async for event in client.stream_events(
            "run-123",
            "platform-session-7",
            context=module.HermesRequestContext(
                user_id=7,
                organization_id="org-2",
                session_id="platform-session-7",
                correlation_id="corr-123",
            ),
        )
    ]

    assert "event: response.output_text.delta" in events[0]
    assert '"delta": "hello"' in events[0]
    assert "event: tool.started" in events[1]
    assert "event: tool.completed" in events[2]
    assert "event: tool.web_search" in events[3]
    assert '"correlation_id": "corr-123"' in events[3]
    assert "event: approval.request" in events[4]
    assert "event: response.failed" in events[5]
    assert "event: response.cancelled" in events[6]
    assert "event: response.completed" in events[7]


@pytest.mark.asyncio
async def test_http_adapter_retries_connection_failure_with_same_idempotency_key():
    module = hermes_client_module()
    requests: list[httpx.Request] = []
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        requests.append(request)
        if attempts == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(202, json={"run_id": "run-after-retry"})

    client = module.HermesHttpClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        retry_backoff_seconds=0,
    )

    run_id = await client.create_response(
        "retry me",
        "platform-session-7",
        context=module.HermesRequestContext(
            user_id=7,
            organization_id="org-2",
            session_id="platform-session-7",
            correlation_id="corr-123",
        ),
        idempotency_key="stable-idem",
    )

    assert run_id == "run-after-retry"
    assert attempts == 2
    assert {request.headers["Idempotency-Key"] for request in requests} == {"stable-idem"}


@pytest.mark.asyncio
async def test_http_adapter_supports_response_continuation_history_stop_and_approval():
    module = hermes_client_module()
    requests: list[httpx.Request] = []
    response_body = {"id": "resp-1", "output": []}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/responses":
            return httpx.Response(
                200,
                json=response_body,
                headers={"X-Hermes-Session-Id": "response-session-1"},
            )
        if request.url.path == "/api/sessions/platform-session-7/messages":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": "message-1",
                            "role": "user",
                            "content": "hello",
                            "timestamp": "2026-07-24T00:00:00+00:00",
                        }
                    ],
                },
            )
        if request.url.path.endswith("/stop"):
            return httpx.Response(200, json={"run_id": "run-123", "status": "stopping"})
        if request.url.path.endswith("/approval"):
            return httpx.Response(
                200,
                json={"run_id": "run-123", "choice": "once", "resolved": 1},
            )
        return httpx.Response(404)

    client = module.HermesHttpClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )
    context = make_context(module)

    first = await client.create_openai_response("first", context=context)
    response_with_metadata, response_session_id = (
        await client.create_openai_response_with_metadata("metadata", context=context)
    )
    continued = await client.create_openai_response(
        "second",
        previous_response_id=first["id"],
        context=context,
    )
    messages = await client.get_session_messages(context.session_id, context=context)
    stopped = await client.stop_run("run-123", context=context)
    approved = await client.approve_run("run-123", "once", context=context)

    assert continued["id"] == "resp-1"
    assert response_with_metadata["id"] == "resp-1"
    assert response_session_id == "response-session-1"
    assert messages[0]["created_at"] == datetime(2026, 7, 24, tzinfo=UTC)
    assert stopped["status"] == "stopping"
    assert approved["resolved"] == 1
    response_requests = [request for request in requests if request.url.path == "/v1/responses"]
    response_request = response_requests[-1]
    assert json.loads(response_request.content)["previous_response_id"] == "resp-1"


@pytest.mark.asyncio
async def test_http_adapter_falls_back_to_chat_completions_when_responses_is_missing():
    module = hermes_client_module()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/responses":
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-1",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"title":"AI weekly","markdown":"ok","summary":"ok","sources":[]}',
                            }
                        }
                    ],
                },
                headers={"X-Hermes-Session-Id": "fallback-session"},
            )
        return httpx.Response(500)

    client = module.HermesHttpClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )
    context = make_context(module)

    response, session_id = await client.create_openai_response_with_metadata(
        "create a sourced report", context=context
    )

    assert [request.url.path for request in requests] == [
        "/v1/responses",
        "/v1/chat/completions",
    ]
    assert requests[-1].headers["X-Hermes-Session-Id"] == context.session_id
    assert json.loads(requests[-1].content)["messages"][0]["content"] == (
        "create a sourced report"
    )
    assert response["id"] == "chatcmpl-1"
    assert response["output"][0]["content"][0]["text"].startswith("{\"title\"")
    assert session_id == "fallback-session"


@pytest.mark.asyncio
async def test_http_adapter_treats_missing_upstream_session_as_empty_history():
    module = hermes_client_module()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/sessions/platform-session-7/messages"
        return httpx.Response(404, json={"detail": "Session not found"})

    client = module.HermesHttpClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )
    context = make_context(module)

    messages = await client.get_session_messages(context.session_id, context=context)

    assert messages == []


@pytest.mark.asyncio
async def test_probe_cleanup_deduplicates_exact_runner_task_ids():
    module = importlib.import_module("scripts.probe_hermes")

    class FakeCleanupClient:
        def __init__(self) -> None:
            self.task_ids: list[str] = []

        async def cleanup_task(self, task_id: str) -> None:
            self.task_ids.append(task_id)

    cleanup_client = FakeCleanupClient()
    await module.cleanup_probe_tasks(
        ["response-session-1", None, "response-session-1", "run-session-1"],
        cleanup_client,
    )

    assert cleanup_client.task_ids == ["response-session-1", "run-session-1"]


@pytest.mark.asyncio
async def test_probe_cleanup_attempts_every_task_before_reporting_failure():
    module = importlib.import_module("scripts.probe_hermes")

    class PartiallyFailingCleanupClient:
        def __init__(self) -> None:
            self.task_ids: list[str] = []

        async def cleanup_task(self, task_id: str) -> None:
            self.task_ids.append(task_id)
            if task_id == "response-session-1":
                raise RuntimeError("cleanup unavailable")

    cleanup_client = PartiallyFailingCleanupClient()
    with pytest.raises(RuntimeError, match="Failed to clean up 1 probe task"):
        await module.cleanup_probe_tasks(
            ["response-session-1", "run-session-1"],
            cleanup_client,
        )

    assert cleanup_client.task_ids == ["response-session-1", "run-session-1"]


def test_probe_associates_terminal_output_with_one_stable_history_message():
    module = importlib.import_module("scripts.probe_hermes")
    before = [{"id": "user-1", "role": "user", "content": "question"}]
    history = [
        *before,
        {"id": "assistant-tool", "role": "assistant", "content": ""},
        {"id": "assistant-final", "role": "assistant", "content": "answer"},
    ]
    streamed_events = [
        'event: response.completed\ndata: {"event":"run.completed","run_id":"run-1","output":"answer"}\n\n'
    ]

    message_id = module.associate_terminal_message(
        before_messages=before,
        history_reads=[history, list(history), list(history)],
        streamed_events=streamed_events,
    )

    assert message_id == "assistant-final"


@pytest.mark.parametrize("output", ["", "   "])
def test_terminal_association_rejects_blank_output(output):
    module = hermes_client_module()
    message = {"id": "assistant-empty", "role": "assistant", "content": output}

    with pytest.raises(module.HermesUpstreamError, match="non-empty terminal output"):
        module.associate_terminal_message(
            before_messages=[],
            history_reads=[[message], [dict(message)], [dict(message)]],
            streamed_events=[
                "event: response.completed\n"
                f"data: {json.dumps({'event': 'run.completed', 'output': output})}\n\n"
            ],
        )


@pytest.mark.parametrize(
    ("history_reads", "streamed_events", "error"),
    [
        (
            [
                [{"id": "assistant-1", "role": "assistant", "content": "answer"}],
                [{"id": "assistant-2", "role": "assistant", "content": "answer"}],
            ],
            ['event: response.completed\ndata: {"event":"run.completed","output":"answer"}\n\n'],
            "history message ids were not stable",
        ),
        (
            [
                [
                    {"id": "assistant-1", "role": "assistant", "content": "answer"},
                    {"id": "assistant-2", "role": "assistant", "content": "answer"},
                ]
            ],
            ['event: response.completed\ndata: {"event":"run.completed","output":"answer"}\n\n'],
            "terminal output did not match exactly one new assistant message",
        ),
    ],
)
def test_probe_rejects_unstable_or_ambiguous_message_association(
    history_reads, streamed_events, error
):
    module = importlib.import_module("scripts.probe_hermes")

    with pytest.raises(module.HermesUpstreamError, match=error):
        module.associate_terminal_message(
            before_messages=[],
            history_reads=history_reads,
            streamed_events=streamed_events,
        )


@pytest.mark.asyncio
async def test_http_adapter_maps_upstream_http_errors_without_leaking_body():
    module = hermes_client_module()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"secret": "provider-token", "error": "gateway down"})

    client = module.HermesHttpClient(
        "http://hermes:8642",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
        retry_backoff_seconds=0,
    )

    with pytest.raises(module.HermesUpstreamError) as caught:
        await client.create_response("hello", "platform-session-7")

    assert caught.value.status_code == 502
    assert "provider-token" not in str(caught.value)
