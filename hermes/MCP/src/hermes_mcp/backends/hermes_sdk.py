"""Hermes SDK backend — direct Python import of hermes_cli modules.

This backend provides faster execution than CLI mode by importing Hermes modules
directly from the installed hermes-agent package.
"""

from __future__ import annotations

import logging
from typing import Any

from hermes_mcp.backends.base import HermesBackend

logger = logging.getLogger(__name__)


class HermesSDKBackend(HermesBackend):
    """Backend that uses Hermes Python modules directly.

    Requires hermes-agent to be installed and importable.
    Falls back to CLI mode if modules are not available.
    """

    def __init__(self):
        self._available: bool | None = None
        self._check_imports()

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def _check_imports(self) -> None:
        """Try importing hermes_cli to determine availability."""
        try:
            import hermes_cli  # noqa: F401
            self._available = True
            logger.info("Hermes SDK backend: hermes_cli imported successfully")
        except ImportError:
            self._available = False
            logger.info("Hermes SDK backend: hermes_cli not found")

    @property
    def is_available(self) -> bool:
        if self._available is None:
            self._check_imports()
        return self._available or False

    @property
    def mode(self) -> str:
        return "sdk" if self.is_available else "unavailable"

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(
        self,
        platform: str,
        content: str,
        *,
        channel: str | None = None,
        subject: str | None = None,
        **kwargs: Any,
    ) -> dict:
        try:
            import asyncio

            # Use hermes send command module
            from hermes_cli.send_cmd import send_message as _send

            # Build args similar to CLI
            args = ["--platform", platform, "--message", content]
            if channel:
                args.extend(["--channel", channel])
            if subject:
                args.extend(["--subject", subject])

            # send_cmd.send_message is typically sync; run in thread
            result = await asyncio.to_thread(_send, args)
            return {"success": True, "data": result}
        except ImportError:
            return {"success": False, "error": "hermes_cli.send_cmd not available"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def list_platforms(self) -> list[dict]:
        try:
            import asyncio

            from hermes_cli.gateway import list_profiles

            result = await asyncio.to_thread(list_profiles)
            if isinstance(result, list):
                return result
            return []
        except ImportError:
            logger.warning("hermes_cli.gateway not available for list_platforms")
            return []
        except Exception as exc:
            logger.warning("list_platforms failed: %s", exc)
            return []

    async def test_platform(self, platform: str) -> dict:
        try:
            import asyncio

            from hermes_cli.gateway import check_platform

            result = await asyncio.to_thread(check_platform, platform)
            return {"success": True, "data": result}
        except ImportError:
            return {"success": False, "error": "hermes_cli.gateway not available"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    async def manage_webhook(
        self,
        action: str,
        *,
        webhook_id: str | None = None,
        config: dict | None = None,
    ) -> dict:
        try:
            import asyncio

            from hermes_cli.webhook import create_webhook as _create
            from hermes_cli.webhook import delete_webhook as _delete
            from hermes_cli.webhook import list_webhooks as _list

            if action == "list":
                result = await asyncio.to_thread(_list)
                return {"success": True, "data": result}
            elif action == "create" and config:
                result = await asyncio.to_thread(_create, config.get("url", ""))
                return {"success": True, "data": result}
            elif action == "delete" and webhook_id:
                result = await asyncio.to_thread(_delete, webhook_id)
                return {"success": True, "data": result}
            else:
                return {"success": False, "error": f"Invalid webhook action: {action}"}
        except ImportError:
            return {"success": False, "error": "hermes_cli.webhook not available"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------

    async def manage_cron(
        self,
        action: str,
        *,
        job_id: str | None = None,
        schedule: str | None = None,
        command: str | None = None,
    ) -> dict:
        try:
            import asyncio

            from hermes_cli.cron import add_job as _add
            from hermes_cli.cron import list_jobs as _list
            from hermes_cli.cron import remove_job as _remove

            if action == "list":
                result = await asyncio.to_thread(_list)
                return {"success": True, "data": result}
            elif action == "create" and schedule and command:
                result = await asyncio.to_thread(_add, schedule, command)
                return {"success": True, "data": result}
            elif action == "delete" and job_id:
                result = await asyncio.to_thread(_remove, job_id)
                return {"success": True, "data": result}
            else:
                return {"success": False, "error": f"Invalid cron action: {action}"}
        except ImportError:
            return {"success": False, "error": "hermes_cli.cron not available"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Proxy
    # ------------------------------------------------------------------

    async def proxy_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        body: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        # Gateway proxy is complex — use HTTP directly for now
        import httpx

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                kwargs = {}
                if headers:
                    kwargs["headers"] = headers
                if body:
                    kwargs["json"] = body
                resp = await client.request(method, url, **kwargs)
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": resp.text[:50_000],
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
