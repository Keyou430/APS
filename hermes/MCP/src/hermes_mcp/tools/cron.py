"""Cron job management tools — create, list, delete scheduled tasks."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from hermes_mcp.backends.base import HermesBackend

logger = logging.getLogger(__name__)


def register_cron_tools(mcp: FastMCP, backend: HermesBackend) -> None:
    """Register cron job management tools."""

    @mcp.tool(
        name="create_cron_job",
        description="""Create a new cron job in Hermes.

Cron jobs run commands on a recurring schedule. Uses standard cron syntax:
  * * * * *   (minute hour day-of-month month day-of-week)

Examples:
  '0 9 * * *' = every day at 9:00 AM
  '*/5 * * * *' = every 5 minutes
  '0 9 * * 1-5' = weekdays at 9:00 AM""",
    )
    async def create_cron_job(
        schedule: str,
        command: str,
        name: str = "",
    ) -> str:
        """Create a cron job.

        Args:
            schedule: Cron schedule expression (5 fields: min hour dom month dow)
            command: Command to execute on the schedule
            name: Optional name/label for this job
        """
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        result = await backend.manage_cron(
            action="create",
            schedule=schedule,
            command=command,
        )

        if result.get("success"):
            data = result.get("data", result.get("stdout", ""))
            name_info = f" '{name}'" if name else ""
            return f"✅ Cron job{name_info} created\nSchedule: {schedule}\nCommand: {command}\n{data}"
        else:
            error = result.get("error") or result.get("stderr", "Unknown error")
            return f"❌ Failed to create cron job: {error}"

    @mcp.tool(
        name="list_cron_jobs",
        description="List all configured cron jobs in Hermes with their schedules and status.",
    )
    async def list_cron_jobs() -> str:
        """List all cron jobs."""
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        result = await backend.manage_cron(action="list")

        if result.get("success"):
            data = result.get("data", result.get("stdout", ""))
            if not data:
                return "No cron jobs configured."
            return f"Cron jobs:\n{data}"
        else:
            stdout = result.get("stdout", "")
            if stdout:
                return f"Cron jobs:\n{stdout}"
            return "No cron jobs configured or unable to list."

    @mcp.tool(
        name="delete_cron_job",
        description="Delete a cron job by its ID.",
    )
    async def delete_cron_job(job_id: str) -> str:
        """Delete a cron job.

        Args:
            job_id: ID of the cron job to delete
        """
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        result = await backend.manage_cron(action="delete", job_id=job_id)

        if result.get("success"):
            return f"✅ Cron job '{job_id}' deleted"
        else:
            error = result.get("error") or result.get("stderr", "Unknown error")
            return f"❌ Failed to delete cron job: {error}"
