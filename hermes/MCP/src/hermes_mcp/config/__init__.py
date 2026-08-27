"""Hermes MCP configuration package."""

from hermes_mcp.config.loader import load_config
from hermes_mcp.config.schema import HermesMCPConfig

__all__ = ["HermesMCPConfig", "load_config"]
