"""Time utility tools — current time, format, parse, timezone conversion."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_time_tools(mcp: FastMCP) -> None:
    """Register time utility tools."""

    @mcp.tool(
        name="now",
        description="""Get the current date and time in various formats and timezones.

Returns ISO 8601 UTC, local time, Unix timestamp, and human-readable formats.""",
    )
    async def now(timezone_name: str = "UTC") -> str:
        """Get the current date and time.

        Args:
            timezone_name: Timezone name (e.g., 'UTC', 'Asia/Shanghai', 'America/New_York')
                          Use 'local' for system local time
        """
        try:
            from zoneinfo import ZoneInfo

            now_utc = datetime.now(UTC)

            if timezone_name.upper() == "UTC":
                now_tz = now_utc
                tz_label = "UTC"
            elif timezone_name.lower() == "local":
                now_tz = datetime.now().astimezone()
                tz_label = "Local"
            else:
                try:
                    tz = ZoneInfo(timezone_name)
                    now_tz = now_utc.astimezone(tz)
                    tz_label = timezone_name
                except Exception:
                    return (
                        f"❌ Unknown timezone: '{timezone_name}'\n"
                        f"Use 'UTC', 'local', or IANA timezone like 'Asia/Shanghai'"
                    )

            timestamp = int(now_utc.timestamp())
            iso_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            iso_tz = now_tz.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            human = now_tz.strftime("%A, %B %d, %Y %I:%M:%S %p")
            date_str = now_tz.strftime("%Y-%m-%d")
            weekday = now_tz.strftime("%A")

            return (
                f"📅 {date_str} ({weekday})\n"
                f"🕐 {human} [{tz_label}]\n"
                f"🌐 ISO 8601 (UTC): {iso_utc}\n"
                f"📌 ISO 8601 ({tz_label}): {iso_tz}\n"
                f"🔢 Unix timestamp: {timestamp}"
            )
        except Exception as exc:
            return f"❌ Error: {exc}"

    @mcp.tool(
        name="format_datetime",
        description="""Format a datetime string into a different format.

Useful for converting between time formats or extracting specific parts.""",
    )
    async def format_datetime(
        datetime_str: str,
        output_format: str = "%Y-%m-%d %H:%M:%S",
        input_format: str = "",
    ) -> str:
        """Format a datetime string.

        Args:
            datetime_str: The datetime string to format (ISO 8601 or custom)
            output_format: Python strftime format for output
            input_format: Python strftime format for parsing (auto-detect if empty)
        """
        try:
            # Try common formats if no input format specified
            if not input_format:
                parsed = _auto_parse_datetime(datetime_str)
                if parsed is None:
                    return (
                        f"❌ Could not auto-parse datetime: '{datetime_str}'\n"
                        f"Provide an input_format parameter with Python strftime codes."
                    )
            else:
                parsed = datetime.strptime(datetime_str, input_format)

            return parsed.strftime(output_format)
        except ValueError as exc:
            return f"❌ Format error: {exc}"
        except Exception as exc:
            return f"❌ Error: {exc}"


def _auto_parse_datetime(s: str) -> datetime | None:
    """Try to parse a datetime string with common formats."""

    # ISO 8601 variants
    iso_formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%B %d, %Y %H:%M:%S",
        "%b %d, %Y %H:%M:%S",
    ]

    for fmt in iso_formats:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue

    return None
