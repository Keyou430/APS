"""Controlled callback used by native Hermes cron jobs created by the platform."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
from fastmcp import FastMCP


def register_platform_pipeline_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="platform_pipeline_trigger",
        description="Trigger one platform pipeline task for a native Hermes cron slot.",
    )
    async def platform_pipeline_trigger(task_id: int, scheduled_for: str = "") -> str:
        if not scheduled_for or scheduled_for.startswith("{"):
            scheduled_for = datetime.now(UTC).isoformat()
        base_url = os.getenv("PLATFORM_API_URL", "http://127.0.0.1:8000").rstrip("/")
        key = os.getenv("HERMES_CRON_INTERNAL_KEY", "development-only")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/api/internal/pipeline/trigger",
                json={"task_id": task_id, "scheduled_for": scheduled_for},
                headers={"X-Hermes-Internal-Key": key},
            )
        if response.status_code not in (200, 202):
            return f"平台定时任务触发失败（{response.status_code}）"
        data = response.json()
        return f"平台定时任务已入队：运行 #{data.get('run_id')}"
