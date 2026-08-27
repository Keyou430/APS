import importlib.util
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER_CONTROL_PATH = ROOT / "deploy" / "runner" / "hermes_runner_control.py"


def load_runner_control_module():
    spec = importlib.util.spec_from_file_location("hermes_runner_control", RUNNER_CONTROL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_control_removes_only_exact_labeled_task_containers() -> None:
    module = load_runner_control_module()
    calls: list[list[str]] = []

    def run(command: list[str]) -> str:
        calls.append(command)
        if command[1] == "ps":
            return "a" * 64 + "\n" + "b" * 64 + "\n"
        return ""

    store = module.DockerTaskStore(run=run)
    removed = store.cleanup("session-abc_123")

    assert removed == ["a" * 64, "b" * 64]
    assert calls == [
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=hermes-task-id=session-abc_123",
        ],
        ["docker", "rm", "-f", "a" * 64, "b" * 64],
    ]


def test_runner_control_rejects_untrusted_task_identifiers_before_docker() -> None:
    module = load_runner_control_module()
    calls: list[list[str]] = []
    store = module.DockerTaskStore(run=lambda command: calls.append(command) or "")

    with pytest.raises(ValueError, match="task id"):
        store.cleanup("session;docker rm -f unrelated")

    assert calls == []


def test_runner_control_requires_mtls_and_never_uses_a_shell() -> None:
    source = RUNNER_CONTROL_PATH.read_text(encoding="utf-8")

    assert "ssl.CERT_REQUIRED" in source
    assert "hermes-task-id=" in source
    assert "shell=True" not in source
    assert "ThreadingHTTPServer" in source


@pytest.mark.asyncio
async def test_platform_runner_client_sends_idempotent_task_cleanup() -> None:
    from app.services.runner_client import SandboxRunnerClient

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"task_id": "session-abc", "removed": 1})

    client = SandboxRunnerClient(
        "https://runner.internal:9443",
        transport=httpx.MockTransport(handler),
    )

    result = await client.cleanup_task("session-abc")

    assert result.removed == 1
    assert requests[0].method == "DELETE"
    assert requests[0].url.path == "/v1/tasks/session-abc"


@pytest.mark.asyncio
async def test_stream_cleanup_runs_when_upstream_stream_fails() -> None:
    from app.services.runner_client import stream_with_runner_cleanup

    cleaned: list[str] = []

    class Runner:
        async def cleanup_task(self, task_id: str):
            cleaned.append(task_id)

    async def failing_stream():
        yield "event: run.created\n\n"
        raise RuntimeError("upstream failed")

    with pytest.raises(RuntimeError, match="upstream failed"):
        _ = [
            item
            async for item in stream_with_runner_cleanup(
                failing_stream(), "session-abc", Runner()
            )
        ]

    assert cleaned == ["session-abc"]
