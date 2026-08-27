from __future__ import annotations

import asyncio
import signal

from app.config import get_settings
from app.workers.rag_ingestion import build_embedding_client, build_processor, run_worker
from app.workers.rag_query_service import (
    create_query_embedding_app,
    run_query_embedding_service,
)


async def main() -> None:
    settings = get_settings()
    if settings.rag_query_embedding_token is None:
        raise RuntimeError("query embedding proxy authentication is incomplete")

    provider = build_embedding_client(settings)
    processor = build_processor(settings)
    app = create_query_embedding_app(
        provider=provider,
        auth_token=settings.rag_query_embedding_token.get_secret_value(),
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_value in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_value, stop_event.set)
        except NotImplementedError:
            pass

    async with asyncio.TaskGroup() as group:
        group.create_task(
            run_worker(
                processor,
                stop_event=stop_event,
                poll_seconds=settings.rag_worker_poll_seconds,
            )
        )
        group.create_task(
            run_query_embedding_service(
                app,
                stop_event=stop_event,
                host=settings.rag_query_embedding_host,
                port=settings.rag_query_embedding_port,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
