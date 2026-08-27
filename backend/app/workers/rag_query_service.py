from __future__ import annotations

import asyncio
import secrets
from collections.abc import Sequence
from typing import Annotated, Protocol

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.services.embedding_client import EmbeddingInvalidDimension, EmbeddingUnavailable


class QueryEmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


QueryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class QueryEmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texts: list[QueryText] = Field(min_length=1, max_length=10)


class QueryEmbeddingResponse(BaseModel):
    vectors: list[list[float]]


def create_query_embedding_app(
    *,
    provider: QueryEmbeddingProvider,
    auth_token: str,
) -> FastAPI:
    if not auth_token:
        raise RuntimeError("query embedding proxy authentication is incomplete")

    app = FastAPI(
        title="Private RAG Query Embedding Service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def authenticate(authorization: str | None) -> None:
        scheme, _, credential = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(credential, auth_token):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/query-embeddings", response_model=QueryEmbeddingResponse)
    async def query_embeddings(
        request: QueryEmbeddingRequest,
        authorization: str | None = Header(default=None),
    ) -> QueryEmbeddingResponse:
        authenticate(authorization)
        try:
            vectors = await provider.embed(request.texts)
        except (EmbeddingUnavailable, EmbeddingInvalidDimension):
            raise HTTPException(status_code=503, detail="embedding_unavailable") from None
        return QueryEmbeddingResponse(vectors=vectors)

    return app


async def run_query_embedding_service(
    app: FastAPI,
    *,
    stop_event: asyncio.Event,
    host: str,
    port: int,
) -> None:
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            access_log=False,
            log_level="warning",
        )
    )
    server_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {server_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if server_task in done:
            stop_event.set()
            await server_task
    finally:
        server.should_exit = True
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        if not server_task.done():
            await server_task
