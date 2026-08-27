"""Messaging tools — send messages via Hermes gateway."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from hermes_mcp.backends.base import HermesBackend

logger = logging.getLogger(__name__)


def register_messaging_tools(mcp: FastMCP, backend: HermesBackend) -> None:
    """Register messaging tools that depend on Hermes backend."""

    @mcp.tool(
        name="send_message",
        description="""Send a message through Hermes messaging gateway to a configured platform.

Supported platforms: Slack, Email, WeChat Work, DingTalk, Feishu, Telegram, WhatsApp, Discord, etc.
The target platform must be configured in Hermes gateway first (via 'hermes gateway setup').""",
    )
    async def send_message(
        platform: str,
        content: str,
        channel: str = "",
        subject: str = "",
    ) -> str:
        """Send a message to a platform via Hermes gateway.

        Args:
            platform: Target platform (e.g., 'slack', 'telegram', 'email')
            content: Message content to send (supports markdown)
            channel: Specific channel/chat ID (platform-dependent)
            subject: Email subject (only relevant for email platform)
        """
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        result = await backend.send_message(
            platform=platform,
            content=content,
            channel=channel or None,
            subject=subject or None,
        )

        if result.get("success"):
            return f"✅ Message sent to {platform}" + (f" ({channel})" if channel else "")
        else:
            error = result.get("error") or result.get("stderr", "Unknown error")
            return f"❌ Failed to send message: {error}"

    @mcp.tool(
        name="list_platforms",
        description="""List all messaging platforms configured in Hermes gateway.

Shows platform name, type, connection status, and configuration summary.""",
    )
    async def list_platforms() -> str:
        """List configured messaging platforms."""
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        platforms = await backend.list_platforms()

        if not platforms:
            return (
                "No messaging platforms configured.\n"
                "Set up platforms with: hermes gateway setup"
            )

        lines = [f"Configured platforms ({len(platforms)}):", ""]
        for p in platforms:
            if isinstance(p, dict):
                name = p.get("name", p.get("platform", "unknown"))
                ptype = p.get("type", p.get("platform_type", "?"))
                status = "✅" if p.get("enabled", True) else "⏸️"
                lines.append(f"  {status} {name} ({ptype})")
            else:
                lines.append(f"  • {p}")

        return "\n".join(lines)

    @mcp.tool(
        name="test_platform",
        description="""Test connectivity to a configured messaging platform.

Sends a test message to verify the platform configuration works.""",
    )
    async def test_platform(platform: str) -> str:
        """Test a messaging platform connection.

        Args:
            platform: Platform name to test (e.g., 'slack', 'telegram')
        """
        if not backend.is_available:
            return (
                "❌ Hermes backend is not available.\n"
                "Make sure hermes.exe is installed and accessible."
            )

        result = await backend.test_platform(platform)

        if result.get("success"):
            return f"✅ Platform '{platform}' is connected and operational"
        else:
            error = result.get("error") or result.get("stderr", "Connection failed")
            return f"❌ Platform '{platform}' test failed: {error}"
