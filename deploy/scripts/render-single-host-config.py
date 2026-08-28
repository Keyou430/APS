#!/usr/bin/env python3
"""Render the container-only Hermes config without changing source config."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path

import yaml


PLACEHOLDER_PREFIXES = (
    "change-this",
    "replace-with",
    "development-only",
    "your-",
)


def required_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith(PLACEHOLDER_PREFIXES):
        raise SystemExit(f"single-host-config=failed check={name.lower()}-missing")
    if not re.fullmatch(r"[A-Za-z0-9._~:-]{24,256}", value):
        raise SystemExit(f"single-host-config=failed check={name.lower()}-format")
    return value


def render(source: Path, destination: Path) -> None:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("single-host-config=failed check=source-config-shape")

    servers = payload.setdefault("mcp_servers", {})
    if not isinstance(servers, dict):
        raise SystemExit("single-host-config=failed check=mcp-config-shape")
    servers["hermes-platform-pipeline"] = {
        "command": "python",
        "args": ["-m", "hermes_mcp.platform_pipeline"],
        "env": {
            "PLATFORM_API_URL": "http://api:8000",
            "HERMES_CRON_INTERNAL_KEY": "${HERMES_CRON_INTERNAL_KEY}",
        },
        "enabled": True,
    }
    platform_toolsets = payload.setdefault("platform_toolsets", {})
    if not isinstance(platform_toolsets, dict):
        raise SystemExit("single-host-config=failed check=platform-toolsets-shape")
    api_server_tools = platform_toolsets.setdefault("api_server", [])
    if not isinstance(api_server_tools, list):
        raise SystemExit("single-host-config=failed check=api-toolset-shape")
    if "hermes-platform-pipeline" not in api_server_tools:
        api_server_tools.append("hermes-platform-pipeline")

    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    forbidden = ("192.168.3.107", "development-only", "http://127.0.0.1:8000")
    if any(value in rendered for value in forbidden):
        raise SystemExit("single-host-config=failed check=forbidden-runtime-value")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent, text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
        os.chmod(temporary, 0o644)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required_secret("HERMES_CRON_INTERNAL_KEY")
    render(args.source, args.output)
    print(f"single-host-config=passed path={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
