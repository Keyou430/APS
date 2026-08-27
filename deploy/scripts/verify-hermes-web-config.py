"""Static and credential-presence checks for the primary Hermes Web boundary.

This verifier never prints credential values. It intentionally reports ``present``/``absent``
only; live provider smoke tests require an explicitly authorized provider credential.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "hermes" / "config.yaml"
KNOWLEDGE_CONFIG = ROOT / "hermes" / "config.knowledge.yaml"
PROVIDER_KEYS = (
    "TAVILY_API_KEY",
    "EXA_API_KEY",
    "PARALLEL_API_KEY",
    "FIRECRAWL_API_KEY",
    "SEARXNG_URL",
)


def provider_availability(environ: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {key: "present" if source.get(key) else "absent" for key in PROVIDER_KEYS}


def tool_definitions(toolsets: list[str]) -> set[str]:
    definitions: set[str] = set()
    if "web" in toolsets:
        definitions.update(("web_search", "web_extract"))
    elif "search" in toolsets:
        definitions.add("web_search")
    return definitions


def main() -> int:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    knowledge = yaml.safe_load(KNOWLEDGE_CONFIG.read_text(encoding="utf-8"))
    api_toolsets = list(config["platform_toolsets"]["api_server"])
    knowledge_toolsets = list(knowledge["platform_toolsets"]["api_server"])
    assert "web" in api_toolsets
    assert {"web_search", "web_extract"} <= tool_definitions(api_toolsets)
    assert "web" not in knowledge_toolsets
    assert config.get("terminal", {}).get("docker_network") is False
    print({"toolsets": api_toolsets, "web_tools": sorted(tool_definitions(api_toolsets)), "providers": provider_availability()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
