from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.services.embedding_client import EmbeddingUnavailable
from app.services.query_embedding import QueryEmbeddingClient
from app.workers.rag_query_service import create_query_embedding_app


class RecordingInternalTransport:
    def __init__(self, *, status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.status_code = status_code

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx.Response(
                self.status_code,
                json={"detail": "provider-private-error-body"},
            )
        return httpx.Response(200, json={"vectors": [[0.25] * 1024]})


@pytest.mark.asyncio
async def test_api_query_client_uses_only_private_proxy_contract() -> None:
    recorder = RecordingInternalTransport()
    client = QueryEmbeddingClient(
        base_url="http://rag-worker:8091",
        auth_token="internal-query-token",
        transport=httpx.MockTransport(recorder),
    )

    vectors = await client.embed(["annual leave policy"])

    assert [len(vector) for vector in vectors] == [1024]
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.url == "http://rag-worker:8091/v1/query-embeddings"
    assert request.headers["authorization"] == "Bearer internal-query-token"
    assert json.loads(request.content) == {"texts": ["annual leave policy"]}
    assert "text-embedding-v4" not in request.content.decode()


@pytest.mark.asyncio
async def test_query_client_failure_exposes_only_stable_error_code() -> None:
    recorder = RecordingInternalTransport(status_code=503)
    client = QueryEmbeddingClient(
        base_url="http://rag-worker:8091",
        auth_token="internal-query-token",
        transport=httpx.MockTransport(recorder),
    )

    with pytest.raises(EmbeddingUnavailable, match="^embedding_unavailable$") as error:
        await client.embed(["internal query"])

    assert "provider-private-error-body" not in str(error.value)


@pytest.mark.asyncio
async def test_query_client_rejects_non_object_json_as_stable_unavailable() -> None:
    client = QueryEmbeddingClient(
        base_url="http://rag-worker:8091",
        auth_token="internal-query-token",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
    )

    with pytest.raises(EmbeddingUnavailable, match="^embedding_unavailable$"):
        await client.embed(["internal query"])


@pytest.mark.asyncio
async def test_query_service_authenticates_before_provider_and_redacts_failures() -> None:
    class FailingProvider:
        calls: list[list[str]] = []

        async def embed(self, texts):
            self.calls.append(list(texts))
            raise EmbeddingUnavailable("provider-private-error-body")

    provider = FailingProvider()
    app = create_query_embedding_app(provider=provider, auth_token="proxy-auth-token")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://worker") as client:
        unauthenticated = await client.post(
            "/v1/query-embeddings", json={"texts": ["private question"]}
        )
        failed = await client.post(
            "/v1/query-embeddings",
            headers={"Authorization": "Bearer proxy-auth-token"},
            json={"texts": ["private question"]},
        )

    assert unauthenticated.status_code == 401
    assert provider.calls == [["private question"]]
    assert failed.status_code == 503
    assert failed.json() == {"detail": "embedding_unavailable"}
    assert "provider-private-error-body" not in failed.text
    assert "proxy-auth-token" not in failed.text


def _compose_service_block(compose: str, service: str, next_service: str | None) -> str:
    start = compose.index(f"  {service}:")
    end = compose.index(f"  {next_service}:", start) if next_service else compose.index("networks:")
    return compose[start:end]


def test_compose_keeps_provider_key_only_in_private_worker_boundary() -> None:
    compose_path = Path(__file__).parents[2] / "deploy" / "compose.yaml"
    compose = compose_path.read_text(encoding="utf-8")
    api = _compose_service_block(compose, "api", "rag-worker")
    worker = _compose_service_block(compose, "rag-worker", "web")

    assert "RAG_EMBEDDING_API_KEY" not in api
    assert "RAG_EMBEDDING_API_URL" not in api
    assert "RAG_QUERY_EMBEDDING_URL" in api
    assert "RAG_QUERY_EMBEDDING_TOKEN" in api
    assert len(
        [line for line in worker.splitlines() if line.strip().startswith("RAG_EMBEDDING_API_KEY:")]
    ) == 1
    assert "RAG_QUERY_EMBEDDING_TOKEN" in worker
    assert "JWT_SECRET_KEY" in worker
    assert "ADMIN_PASSWORD" in worker
    assert "RAG_QUERY_AUDIT_HMAC_KEY" in worker
    assert "ports:" not in worker
    assert '\n    expose:\n      - "8091"' in worker
