"""Delivery outbox worker entrypoint (Phase 1 C1).

Consumes delivery_outbox rows and delivers light notifications through the
configured provider adapters. Missing credentials are reported honestly per
row (feishu_not_configured) instead of faking success.
"""

import asyncio
import socket
from uuid import uuid4

from app.config import get_settings
from app.database import SessionLocal
from app.services.delivery_outbox_worker import run_delivery_cycle
from app.services.feishu_delivery import build_feishu_delivery_adapter
from app.services.routing import ChannelDeliveryAdapter


def build_delivery_adapters() -> dict[str, ChannelDeliveryAdapter]:
    settings = get_settings()
    adapters: dict[str, ChannelDeliveryAdapter] = {}
    feishu = build_feishu_delivery_adapter(settings)
    if feishu is not None:
        adapters["feishu"] = feishu
    return adapters


async def main() -> None:
    settings = get_settings()
    adapters = build_delivery_adapters()
    worker_id = f"delivery-{socket.gethostname()}-{uuid4().hex[:12]}"
    while True:
        await run_delivery_cycle(SessionLocal, adapters=adapters, worker_id=worker_id)
        await asyncio.sleep(settings.delivery_worker_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
