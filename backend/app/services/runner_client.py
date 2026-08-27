from __future__ import annotations

import re
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx


TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class RunnerControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxCleanupResult:
    task_id: str
    removed: int


class SandboxTaskCleaner(Protocol):
    async def cleanup_task(self, task_id: str) -> SandboxCleanupResult: ...


class DisabledSandboxRunnerClient:
    async def cleanup_task(self, task_id: str) -> SandboxCleanupResult:
        return SandboxCleanupResult(task_id=task_id, removed=0)


class SandboxRunnerClient:
    def __init__(
        self,
        base_url: str,
        *,
        ca_certificate: Path | None = None,
        client_certificate: Path | None = None,
        client_private_key: Path | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.transport = transport
        self.ssl_context: ssl.SSLContext | None = None
        if transport is None:
            if not (ca_certificate and client_certificate and client_private_key):
                raise ValueError("Runner mTLS certificates are required")
            context = ssl.create_default_context(cafile=str(ca_certificate))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(client_certificate), str(client_private_key))
            self.ssl_context = context

    async def cleanup_task(self, task_id: str) -> SandboxCleanupResult:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise RunnerControlError("Runner task id is invalid")
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                verify=self.ssl_context,
            ) as client:
                response = await client.delete(f"/v1/tasks/{task_id}")
        except httpx.HTTPError as exc:
            raise RunnerControlError("Runner cleanup request failed") from exc
        if response.status_code != 200:
            raise RunnerControlError(f"Runner cleanup rejected with HTTP {response.status_code}")
        try:
            payload = response.json()
            removed = payload["removed"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RunnerControlError("Runner cleanup returned an invalid response") from exc
        if type(removed) is not int or removed < 0:
            raise RunnerControlError("Runner cleanup returned an invalid response")
        return SandboxCleanupResult(task_id=task_id, removed=removed)


async def stream_with_runner_cleanup(
    events: AsyncIterator[str], task_id: str, runner: SandboxTaskCleaner
) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield event
    finally:
        await runner.cleanup_task(task_id)


def _build_sandbox_runner_client() -> SandboxTaskCleaner:
    from app.config import get_settings

    settings = get_settings()
    if not settings.sandbox_runner_enabled:
        return DisabledSandboxRunnerClient()
    return SandboxRunnerClient(
        settings.sandbox_runner_url,
        ca_certificate=settings.sandbox_runner_ca_certificate,
        client_certificate=settings.sandbox_runner_client_certificate,
        client_private_key=settings.sandbox_runner_client_private_key,
        timeout_seconds=settings.sandbox_runner_timeout_seconds,
    )


sandbox_runner_client = _build_sandbox_runner_client()
