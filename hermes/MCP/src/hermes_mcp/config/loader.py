"""Configuration loader with layered priority: defaults → yaml → env → CLI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from hermes_mcp.config.schema import HermesMCPConfig


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries. Override values win."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_env_overrides(prefix: str = "HERMES_MCP_") -> dict:
    """Load environment variables with HERMES_MCP_ prefix as nested dict."""
    result: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        # HERMES_MCP_SERVER_PORT → ["server", "port"]
        raw_parts = key[len(prefix):].lower().split("_")
        # Re-join consecutive parts as candidate multi-word field names.
        # Try the longest match first: for ["retrieval","base","url"],
        # try "retrieval" + "base_url" before falling back to individual keys.
        parts = _merge_multiword_keys(raw_parts)
        _set_nested(result, parts, _coerce_value(value))
    return result


# Known two-word field names in the config schema that env vars should fold into one key.
_MULTIWORD_FIELDS = frozenset({
    "base_url", "sdk_path", "exe_path", "cli_path", "log_level", "max_output_bytes",
    "feishu_readonly", "lark_cli_full", "approval_ttl",
    "default_top_k", "similarity_threshold", "experience_enabled",
    "database_enabled", "knowledge_enabled", "max_file_size",
    "allowed_commands", "allowed_directories", "allowed_extensions",
    "default_timeout", "rate_limit_requests", "rate_limit_period",
    "failure_threshold", "recovery_timeout", "circuit_breaker_failure_threshold",
    "circuit_breaker_recovery_timeout", "half_open_max_calls", "max_retries",
})


def _resolve_default_config_path() -> Path:
    """Resolve the default config file path.

    Tries importlib.resources first (works in wheel installs), falls back
    to a filesystem-relative path (works in editable installs / development).
    """
    try:
        from importlib.resources import files
        cfg = files("hermes_mcp") / ".." / ".." / "config" / "default.yaml"
        resolved = cfg.resolve()
        if resolved.exists():
            return resolved
    except Exception:
        pass
    # Fallback: assume we're in an editable install at src/hermes_mcp/config/loader.py
    return Path(__file__).parent.parent.parent.parent / "config" / "default.yaml"


def _merge_multiword_keys(parts: list[str]) -> list[str]:
    """Merge adjacent parts into known multi-word field names.

    E.g. ["retrieval", "base", "url"] → ["retrieval", "base_url"]
    """
    if len(parts) < 2:
        return list(parts)
    merged: list[str] = []
    i = 0
    while i < len(parts):
        # Try two-word merge
        if i + 1 < len(parts):
            candidate = f"{parts[i]}_{parts[i + 1]}"
            if candidate in _MULTIWORD_FIELDS:
                merged.append(candidate)
                i += 2
                continue
        # Try three-word merge (e.g. circuit_breaker_failure_threshold)
        if i + 2 < len(parts):
            candidate = f"{parts[i]}_{parts[i + 1]}_{parts[i + 2]}"
            if candidate in _MULTIWORD_FIELDS:
                merged.append(candidate)
                i += 3
                continue
        merged.append(parts[i])
        i += 1
    return merged


def _set_nested(d: dict, keys: list[str], value: Any) -> None:
    """Set a value at a nested key path."""
    current = d
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def _coerce_value(value: str) -> Any:
    """Coerce a string to int/float/bool if possible."""
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _load_yaml_file(path: Path) -> dict:
    """Load a YAML config file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except (yaml.YAMLError, OSError) as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to load config %s: %s", path, exc)
        return {}


def load_config(
    config_path: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> HermesMCPConfig:
    """Load configuration with full hierarchy resolution.

    Priority (lowest to highest):
    1. Pydantic model defaults
    2. config/default.yaml (shipped with package)
    3. config_path if provided
    4. Environment variables (HERMES_MCP_*)
    5. CLI overrides
    """
    raw: dict[str, Any] = {}

    # 1. Default config file (shipped with package)
    package_default = _resolve_default_config_path()
    raw = _deep_merge(raw, _load_yaml_file(package_default))

    # 2. User config file
    if config_path:
        raw = _deep_merge(raw, _load_yaml_file(config_path))

    # 3. Environment variable overrides
    raw = _deep_merge(raw, _load_env_overrides())

    # 4. CLI overrides
    if cli_overrides:
        raw = _deep_merge(raw, cli_overrides)

    try:
        return HermesMCPConfig.model_validate(raw)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Configuration validation failed: %s", exc)
        raise
