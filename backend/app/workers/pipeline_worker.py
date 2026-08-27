import asyncio
import socket
from uuid import uuid4

from app.database import SessionLocal
from app.services.pipeline_executor import build_pipeline_executor, run_pipeline_cycle


async def main() -> None:
    executor = build_pipeline_executor()
    if executor is None:
        raise RuntimeError("Pipeline worker requires the real Hermes HTTP provider")
    worker_id = f"{socket.gethostname()}-{uuid4().hex[:12]}"
    while True:
        await run_pipeline_cycle(
            SessionLocal, executor=executor, worker_id=worker_id, limit=10
        )
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
