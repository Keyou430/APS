"""Hermes CLI backend — communicates via subprocess hermes.exe."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from hermes_mcp.backends.base import HermesBackend

logger = logging.getLogger(__name__)


class HermesCLIBackend(HermesBackend):
    """Backend that invokes hermes.exe via subprocess for each operation."""

    def __init__(
        self,
        exe_path: str = r"D:\Replica1.0\hermes\hermes.exe",
        timeout: float = 30.0,
    ):
        self.exe_path = exe_path
        self.timeout = timeout
        self._available: bool | None = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        if self._available is None:
            self._available = os.path.isfile(self.exe_path)
        return self._available

    @property
    def mode(self) -> str:
        return "cli" if self.is_available else "unavailable"

    # ------------------------------------------------------------------
    # Core subprocess runner
    # ------------------------------------------------------------------

    async def _run(self, *args: str) -> dict:
        """Run hermes.exe with arguments and return parsed JSON output."""
        cmd = [self.exe_path, *args]
        proc = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout,
            )
        except TimeoutError:
            logger.warning("Hermes CLI timeout on subcommand: %s", args[0] if args else "?")
            if proc is not None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    proc.kill()
            return {"success": False, "error": "Command timed out"}
        except FileNotFoundError:
            logger.warning("Hermes exe not found: %s", self.exe_path)
            return {"success": False, "error": f"Hermes executable not found: {self.exe_path}"}
        except Exception as exc:
            logger.warning("Hermes CLI error: %s", exc)
            return {"success": False, "error": str(exc)}

        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()

        result: dict = {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": output,
            "stderr": error_output,
        }

        # Try to parse JSON if output looks like JSON
        if output and output[0] in "{[":
            try:
                parsed = json.loads(output)
                result["data"] = parsed
            except json.JSONDecodeError:
                result["data"] = output

        return result

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
        args = ["send", "--platform", platform, "--message", content]
        if channel:
            args.extend(["--channel", channel])
        if subject:
            args.extend(["--subject", subject])
        return await self._run(*args)

    async def list_platforms(self) -> list[dict]:
        result = await self._run("gateway", "list")
        if result.get("success") and result.get("data"):
            return result["data"] if isinstance(result["data"], list) else []
        return []

    async def test_platform(self, platform: str) -> dict:
        result = await self._run("gateway", "status", platform)
        return result

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
        args = ["webhook"]
        if action == "list":
            pass
        elif action == "create" and config:
            args.extend(["create", "--url", config.get("url", "")])
            if config.get("name"):
                args.extend(["--name", config["name"]])
            if config.get("events"):
                args.extend(["--events", config["events"]])
        elif action == "delete" and webhook_id:
            args.extend(["delete", webhook_id])
        else:
            return {"success": False, "error": f"Missing arguments for webhook {action}"}
        return await self._run(*args)

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
        args = ["cron"]
        if action == "list":
            pass
        elif action == "create" and schedule and command:
            args.extend(["add", schedule, "--", command])
        elif action == "delete" and job_id:
            args.extend(["remove", job_id])
        else:
            return {"success": False, "error": f"Missing arguments for cron {action}"}
        return await self._run(*args)

    # ------------------------------------------------------------------
    # Proxy / Gateway
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
        # Hermes CLI doesn't have a direct proxy command,
        # so we use the gateway module if available.
        return {
            "success": False,
            "error": "proxy_request not available in CLI mode (use SDK mode or built-in http_request)",
        }
