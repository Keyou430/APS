"""Webhook management tools — create, list, delete webhook subscriptions."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from hermes_mcp.backends.base import HermesBackend

logger = logging.getLogger(__name__)


def register_webhook_tools(mcp: FastMCP, backend: HermesBackend) -> None:
    """Register webhook management tools."""

    @mcp.tool(
        name="create_webhook",
        description="""Create a new webhook subscription in Hermes.

Webhooks allow external services to send events to Hermes via HTTP callbacks.
Returns the webhook URL and ID on success.""",
    )
    async def create_webhook(
        url: str,
        name: str = "",
        events: str = "",
    ) -> str:
        """Create a webhook subscription.

        Args:
            url: The webhook URL to subscribe to
            name: Optional name for this webhook
            events: Comma-separated event types to listen for (empty = all)
        """
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        config = {"url": url}
        if name:
            config["name"] = name
        if events:
            config["events"] = events.split(",")

        result = await backend.manage_webhook(action="create", config=config)

        if result.get("success"):
            data = result.get("data", result.get("stdout", ""))
            return f"✅ Webhook created\n{data}"
        else:
            error = result.get("error") or result.get("stderr", "Unknown error")
            return f"❌ Failed to create webhook: {error}"

    @mcp.tool(
        name="list_webhooks",
        description="List all active webhook subscriptions in Hermes.",
    )
    async def list_webhooks() -> str:
        """List all webhook subscriptions."""
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        result = await backend.manage_webhook(action="list")

        if result.get("success"):
            data = result.get("data", result.get("stdout", ""))
            if not data:
                return "No webhooks configured."
            return f"Webhook subscriptions:\n{data}"
        else:
            # hermes webhook might just print the list even with non-zero exit
            stdout = result.get("stdout", "")
            if stdout:
                return f"Webhook subscriptions:\n{stdout}"
            return "No webhooks configured or unable to list."

    @mcp.tool(
        name="delete_webhook",
        description="Delete a webhook subscription by ID.",
    )
    async def delete_webhook(webhook_id: str) -> str:
        """Delete a webhook subscription.

        Args:
            webhook_id: ID of the webhook to delete
        """
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        result = await backend.manage_webhook(action="delete", webhook_id=webhook_id)

        if result.get("success"):
            return f"✅ Webhook '{webhook_id}' deleted"
        else:
            error = result.get("error") or result.get("stderr", "Unknown error")
            return f"❌ Failed to delete webhook: {error}"
