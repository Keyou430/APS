#!/usr/bin/env python3
"""Hermes CLI-compatible client for the private cron command sidecar."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    endpoint = os.getenv("HERMES_CRON_BRIDGE_URL", "").rstrip("/")
    internal_key = os.getenv("HERMES_CRON_INTERNAL_KEY", "")
    if not endpoint or not internal_key:
        print("Hermes cron bridge is not configured", file=sys.stderr)
        return 1

    request = Request(
        f"{endpoint}/v1/cron",
        data=json.dumps({"args": sys.argv[1:]}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Hermes-Internal-Key": internal_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=130) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Hermes cron bridge request failed: {exc}", file=sys.stderr)
        return 1

    stdout = payload.get("stdout", "")
    stderr = payload.get("stderr", "")
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
    return int(payload.get("returncode", 1))


if __name__ == "__main__":
    raise SystemExit(main())
