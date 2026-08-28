#!/usr/bin/env python3
"""Private command sidecar for the backend's existing Hermes cron CLI contract."""

from __future__ import annotations

import json
import os
import re
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
SCRIPT_NAME = re.compile(r"platform_pipeline_task_[0-9]+\.py\Z")
HERMES = "/opt/hermes/.venv/bin/hermes"
SCRIPTS = Path("/opt/data/scripts")


def validated_args(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("args must be a string list")
    if len(value) == 8 and value[:2] == ["cron", "create"]:
        if value[3] != "--name" or value[5] != "--script" or value[7] != "--no-agent":
            raise ValueError("unsupported cron create arguments")
        script_name = value[6]
        if not SCRIPT_NAME.fullmatch(script_name) or not (SCRIPTS / script_name).is_file():
            raise ValueError("invalid cron script")
        if not value[2].strip() or not value[4].strip():
            raise ValueError("schedule and name are required")
        return value
    if len(value) == 3 and value[:2] == ["cron", "remove"]:
        if not JOB_ID.fullmatch(value[2]):
            raise ValueError("invalid cron job id")
        return value
    raise ValueError("unsupported Hermes command")


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesCronBridge/1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json(HTTPStatus.OK, {"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/cron":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        expected = os.getenv("HERMES_CRON_INTERNAL_KEY", "")
        if not expected or self.headers.get("X-Hermes-Internal-Key") != expected:
            self._json(HTTPStatus.UNAUTHORIZED, {"detail": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 16384:
                raise ValueError("invalid payload size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            args = validated_args(payload.get("args") if isinstance(payload, dict) else None)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"detail": str(exc)})
            return

        try:
            completed = subprocess.run(
                [HERMES, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.SubprocessError):
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": "Hermes command failed"})
            return
        self._json(
            HTTPStatus.OK,
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout[-65536:],
                "stderr": completed.stderr[-65536:],
            },
        )

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *args: object) -> None:
        del args


def main() -> int:
    host = os.getenv("HERMES_CRON_COMMAND_HOST", "0.0.0.0")
    port = int(os.getenv("HERMES_CRON_COMMAND_PORT", "8765"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
