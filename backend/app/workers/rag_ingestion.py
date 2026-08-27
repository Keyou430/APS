from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from typing import Any, Protocol

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.services.document_parser import DoclingDocumentParser
from app.services.embedding_client import EmbeddingClient
from app.services.knowledge_ingestion import KnowledgeIngestionProcessor
from app.services.object_storage import LocalPrivateObjectStorage


class IngestionJobProcessor(Protocol):
    async def process_next(self) -> bool: ...


def build_embedding_client(settings: Settings | None = None) -> EmbeddingClient:
    resolved = settings or get_settings()
    configured_key = resolved.rag_embedding_api_key
    api_key = (
        configured_key.get_secret_value()
        if hasattr(configured_key, "get_secret_value")
        else str(configured_key or "")
    )
    if not resolved.rag_embedding_api_url or not api_key.strip():
        raise RuntimeError("RAG embedding configuration is incomplete")
    return EmbeddingClient(
        base_url=resolved.rag_embedding_api_url,
        api_key=resolved.rag_embedding_api_key,
        timeout_seconds=resolved.rag_embedding_timeout_seconds,
    )


def build_processor(
    settings: Settings | None = None,
    *,
    session_factory: Callable[[], Any] = SessionLocal,
) -> KnowledgeIngestionProcessor:
    resolved = settings or get_settings()
    return KnowledgeIngestionProcessor(
        session_factory,
        storage=LocalPrivateObjectStorage(resolved.upload_dir),
        parser=DoclingDocumentParser(),
        embedding_client=build_embedding_client(resolved),
    )


async def run_worker(
    processor: IngestionJobProcessor,
    *,
    stop_event: asyncio.Event,
    poll_seconds: float,
) -> None:
    while not stop_event.is_set():
        processed = await processor.process_next()
        if processed:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue


async def main(*, stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    if not settings.rag_embedding_enabled:
        raise RuntimeError("RAG embedding worker is disabled")
    processor = build_processor(settings)
    resolved_stop_event = stop_event or asyncio.Event()
    if stop_event is None:
        loop = asyncio.get_running_loop()
        for signal_value in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signal_value, resolved_stop_event.set)
            except NotImplementedError:
                pass
    await run_worker(
        processor,
        stop_event=resolved_stop_event,
        poll_seconds=settings.rag_worker_poll_seconds,
    )


if __name__ == "__main__":
    asyncio.run(main())
