from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr


class EmbeddingUnavailable(RuntimeError):
    pass


class EmbeddingInvalidDimension(RuntimeError):
    pass


class EmbeddingClient:
    MODEL = "text-embedding-v4"
    DIMENSIONS = 1024
    MAX_BATCH_SIZE = 10

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | SecretStr,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        secret = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not base_url.strip() or not secret:
            raise ValueError("embedding configuration is incomplete")
        self.base_url = base_url.rstrip("/")
        self._api_key = secret
        self.timeout = httpx.Timeout(timeout_seconds)
        self.transport = transport

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        normalized = [text.strip() for text in texts]
        if any(not text for text in normalized):
            raise ValueError("embedding input must not be empty")
        vectors: list[list[float]] = []
        for start in range(0, len(normalized), self.MAX_BATCH_SIZE):
            batch = normalized[start : start + self.MAX_BATCH_SIZE]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    "/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.MODEL,
                        "input": texts,
                        "dimensions": self.DIMENSIONS,
                        "encoding_format": "float",
                    },
                )
            if response.status_code >= 400:
                raise EmbeddingUnavailable("embedding_unavailable")
            body = response.json()
            vectors = self._vectors_from_response(body, expected_count=len(texts))
        except EmbeddingInvalidDimension:
            raise
        except EmbeddingUnavailable:
            raise
        except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
            raise EmbeddingUnavailable("embedding_unavailable") from exc
        return vectors

    @classmethod
    def _vectors_from_response(
        cls,
        body: dict[str, Any],
        *,
        expected_count: int,
    ) -> list[list[float]]:
        items = body.get("data")
        if not isinstance(items, list) or len(items) != expected_count:
            raise EmbeddingUnavailable("embedding_unavailable")

        ordered: list[list[float] | None] = [None] * expected_count
        for item in items:
            if not isinstance(item, dict):
                raise EmbeddingUnavailable("embedding_unavailable")
            index = item.get("index")
            vector = item.get("embedding")
            if type(index) is not int or not 0 <= index < expected_count or ordered[index] is not None:
                raise EmbeddingUnavailable("embedding_unavailable")
            if not isinstance(vector, list):
                raise EmbeddingUnavailable("embedding_unavailable")
            if len(vector) != cls.DIMENSIONS:
                raise EmbeddingInvalidDimension("embedding_invalid_dimension")
            if not all(type(value) in {int, float} for value in vector):
                raise EmbeddingUnavailable("embedding_unavailable")
            ordered[index] = [float(value) for value in vector]

        if any(vector is None for vector in ordered):
            raise EmbeddingUnavailable("embedding_unavailable")
        return [vector for vector in ordered if vector is not None]
