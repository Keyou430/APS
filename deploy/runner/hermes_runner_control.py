#!/usr/bin/env python3
"""Private mTLS control endpoint for scoped rootless-Docker task cleanup."""

from __future__ import annotations

import argparse
import json
import re
import ssl
import subprocess
from collections.abc import Callable, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit


TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
CONTAINER_ID_PATTERN = re.compile(r"[0-9a-f]{12,64}\Z")


def _docker_run(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    return completed.stdout


class DockerTaskStore:
    """Remove only containers that match one exact, server-owned task label."""

    def __init__(self, run: Callable[[list[str]], str] = _docker_run) -> None:
        self._run = run

    @staticmethod
    def validate_task_id(task_id: str) -> str:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError("invalid task id")
        return task_id

    def cleanup(self, task_id: str) -> list[str]:
        task_id = self.validate_task_id(task_id)
        raw_ids = self._run(
            ["docker", "ps", "-aq", "--filter", f"label=hermes-task-id={task_id}"]
        )
        container_ids = [line.strip() for line in raw_ids.splitlines() if line.strip()]
        if any(not CONTAINER_ID_PATTERN.fullmatch(container_id) for container_id in container_ids):
            raise RuntimeError("Docker returned an invalid container id")
        if container_ids:
            self._run(["docker", "rm", "-f", *container_ids])
        return container_ids


class RunnerControlServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], task_store: DockerTaskStore) -> None:
        super().__init__(address, RunnerControlHandler)
        self.task_store = task_store


class RunnerControlHandler(BaseHTTPRequestHandler):
    server: RunnerControlServer

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/health":
            self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        self._json(HTTPStatus.OK, {"status": "ok"})

    def do_DELETE(self) -> None:  # noqa: N802
        parts = urlsplit(self.path).path.split("/")
        if len(parts) != 4 or parts[:3] != ["", "v1", "tasks"]:
            self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        task_id = unquote(parts[3])
        try:
            removed = self.server.task_store.cleanup(task_id)
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"detail": str(exc)})
            return
        except (OSError, subprocess.SubprocessError, RuntimeError):
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": "runner cleanup failed"})
            return
        self._json(HTTPStatus.OK, {"task_id": task_id, "removed": len(removed)})

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *args: object) -> None:
        del args


def tls_context(*, certificate: str, private_key: str, client_ca: str) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, private_key)
    context.load_verify_locations(cafile=client_ca)
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--client-ca", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    server = RunnerControlServer((args.bind, args.port), DockerTaskStore())
    server.socket = tls_context(
        certificate=args.certificate,
        private_key=args.private_key,
        client_ca=args.client_ca,
    ).wrap_socket(server.socket, server_side=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
