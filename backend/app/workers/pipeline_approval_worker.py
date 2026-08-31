import asyncio

from app.config import get_settings
from app.database import SessionLocal
from app.services.pipeline_approval_reminders import (
    run_pipeline_approval_reminder_cycle,
)


async def main() -> None:
    settings = get_settings()
    while True:
        await run_pipeline_approval_reminder_cycle(SessionLocal)
        await asyncio.sleep(settings.pipeline_approval_worker_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
