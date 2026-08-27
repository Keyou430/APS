from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingInvalidDimension,
    EmbeddingUnavailable,
)


class QueryEmbeddingClient:
    """Calls the private worker proxy without holding the provider credential."""

    MAX_BATCH_SIZE = 10

    def __init__(
        self,
        *,
        base_url: str,
        auth_token: str | SecretStr,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        token = (
            auth_token.get_secret_value() if isinstance(auth_token, SecretStr) else auth_token
        )
        if not base_url.strip() or not token:
            raise ValueError("query embedding configuration is incomplete")
        self.base_url = base_url.rstrip("/")
        self._auth_token = token
        self.timeout = httpx.Timeout(timeout_seconds)
        self.transport = transport

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        normalized = [text.strip() for text in texts]
        if not normalized or any(not text for text in normalized):
            raise ValueError("embedding input must not be empty")
        if len(normalized) > self.MAX_BATCH_SIZE:
            raise ValueError("query embedding batch is too large")
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    "/v1/query-embeddings",
                    headers={"Authorization": f"Bearer {self._auth_token}"},
                    json={"texts": normalized},
                )
            if response.status_code >= 400:
                raise EmbeddingUnavailable("embedding_unavailable")
            body: Any = response.json()
            if not isinstance(body, dict):
                raise EmbeddingUnavailable("embedding_unavailable")
            vectors = body.get("vectors")
            return EmbeddingClient._vectors_from_response(
                {
                    "data": [
                        {"index": index, "embedding": vector}
                        for index, vector in enumerate(vectors)
                    ]
                    if isinstance(vectors, list)
                    else None
                },
                expected_count=len(normalized),
            )
        except EmbeddingInvalidDimension:
            raise
        except EmbeddingUnavailable:
            raise
        except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
            raise EmbeddingUnavailable("embedding_unavailable") from exc
