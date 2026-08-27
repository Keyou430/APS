from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingInvalidDimension,
    EmbeddingUnavailable,
)
from app.workers.rag_ingestion import build_embedding_client, run_worker


def test_settings_accepts_fixed_embedding_dimension_from_container_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_EMBEDDING_DIMENSIONS", "1024")

    settings = Settings(_env_file=None)

    assert settings.rag_embedding_dimensions == 1024


class RecordingEmbeddingTransport:
    def __init__(self, *, status_code: int = 200, invalid_dimension: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.status_code = status_code
        self.invalid_dimension = invalid_dimension

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        request_body = json.loads(request.content)
        if self.status_code != 200:
            return httpx.Response(
                self.status_code,
                json={"error": {"message": "provider-private-error-body"}},
            )
        dimension = 3 if self.invalid_dimension else request_body["dimensions"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [0.0] * dimension}
                    for index, _text in enumerate(request_body["input"])
                ]
            },
        )


@pytest.mark.asyncio
async def test_embedding_client_batches_at_most_ten_and_requires_1024_dimensions() -> None:
    recorder = RecordingEmbeddingTransport()
    client = EmbeddingClient(
        base_url="https://embedding.invalid/v1",
        api_key="unit-test-credential",
        transport=httpx.MockTransport(recorder),
    )

    vectors = await client.embed([f"chunk-{index}" for index in range(11)])

    assert [len(vector) for vector in vectors] == [1024] * 11
    assert len(recorder.requests) == 2
    assert recorder.requests[0].url.path == "/v1/embeddings"
    first_body = json.loads(recorder.requests[0].content)
    second_body = json.loads(recorder.requests[1].content)
    assert first_body["model"] == "text-embedding-v4"
    assert first_body["dimensions"] == 1024
    assert first_body["encoding_format"] == "float"
    assert len(first_body["input"]) == 10
    assert len(second_body["input"]) == 1


@pytest.mark.asyncio
async def test_embedding_failure_exposes_code_not_provider_body() -> None:
    recorder = RecordingEmbeddingTransport(status_code=429)
    client = EmbeddingClient(
        base_url="https://embedding.invalid/v1",
        api_key="unit-test-credential",
        transport=httpx.MockTransport(recorder),
    )

    with pytest.raises(EmbeddingUnavailable, match="^embedding_unavailable$") as error:
        await client.embed(["internal text"])

    assert "provider-private-error-body" not in str(error.value)


@pytest.mark.asyncio
async def test_embedding_client_rejects_wrong_vector_dimension() -> None:
    recorder = RecordingEmbeddingTransport(invalid_dimension=True)
    client = EmbeddingClient(
        base_url="https://embedding.invalid/v1",
        api_key="unit-test-credential",
        transport=httpx.MockTransport(recorder),
    )

    with pytest.raises(EmbeddingInvalidDimension, match="^embedding_invalid_dimension$"):
        await client.embed(["internal text"])


def test_worker_fails_closed_without_embedding_credential() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///./worker-test.db",
        jwt_secret_key="worker-test-secret",
        rag_embedding_api_url="https://embedding.invalid/v1",
        rag_embedding_api_key=None,
    )

    with pytest.raises(RuntimeError, match="RAG embedding configuration is incomplete"):
        build_embedding_client(settings)


@pytest.mark.asyncio
async def test_worker_waits_without_busy_loop_and_stops_promptly() -> None:
    first_call = asyncio.Event()

    class EmptyProcessor:
        calls = 0

        async def process_next(self) -> bool:
            self.calls += 1
            first_call.set()
            return False

    processor = EmptyProcessor()
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_worker(processor, stop_event=stop_event, poll_seconds=60.0)
    )
    await asyncio.wait_for(first_call.wait(), timeout=1.0)

    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert processor.calls == 1
