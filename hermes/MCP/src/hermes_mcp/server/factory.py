"""Server factory — assembles the FastMCP server with all tools registered."""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

from hermes_mcp.backends.base import HermesBackend
from hermes_mcp.backends.hermes_cli import HermesCLIBackend
from hermes_mcp.backends.retrieval import RetrievalBackend
from hermes_mcp.config.schema import HermesMCPConfig

logger = logging.getLogger(__name__)


def _resolve_hermes_backend(config: HermesMCPConfig) -> HermesBackend:
    """Resolve the Hermes backend based on config mode.

    Priority: SDK (try import) → CLI (fallback).
    """
    mode = config.hermes.mode

    if mode == "sdk":
        try:
            sdk_path = config.hermes.sdk_path
            if sdk_path and sdk_path not in sys.path:
                sys.path.insert(0, sdk_path)
            # Lazy import — will be created when SDK backend is implemented
            from hermes_mcp.backends.hermes_sdk import HermesSDKBackend
            backend = HermesSDKBackend()
            if backend.is_available:
                logger.info("Using Hermes SDK backend")
                return backend
        except ImportError:
            logger.info("Hermes SDK backend not available, falling back to CLI")
        except Exception as exc:
            logger.warning("SDK backend init failed: %s, falling back to CLI", exc)

    if mode in ("sdk", "auto"):
        # In auto mode, try SDK first, then fall back to CLI
        if mode == "auto":
            try:
                sdk_path = config.hermes.sdk_path
                if sdk_path and sdk_path not in sys.path:
                    sys.path.insert(0, sdk_path)
                from hermes_mcp.backends.hermes_sdk import HermesSDKBackend
                backend = HermesSDKBackend()
                if backend.is_available:
                    logger.info("Using Hermes SDK backend (auto-detected)")
                    return backend
            except (ImportError, Exception):
                logger.info("SDK not available in auto mode, using CLI")
            finally:
                # Clean up sys.path regardless of success/failure
                if sdk_path and sdk_path in sys.path:
                    sys.path.remove(sdk_path)

    # CLI fallback
    backend = HermesCLIBackend(
        exe_path=config.hermes.exe_path,
        timeout=config.hermes.timeout,
    )
    if backend.is_available:
        logger.info("Using Hermes CLI backend: %s", config.hermes.exe_path)
    else:
        logger.warning(
            "Hermes CLI backend unavailable: %s not found. "
            "Hermes-dependent tools will return errors.",
            config.hermes.exe_path,
        )
    return backend


def _build_instructions(config: HermesMCPConfig) -> str:
    """Build the server instructions string for MCP clients."""
    return f"""Hermes MCP Server v{config.server.version}

Available capabilities:
- Knowledge Retrieval — Search across three knowledge sources (Experience/Database/Knowledge base)
- Messaging — Send messages via Hermes gateway (Slack, Email, WeChat, DingTalk, etc.)
- Webhook Management — Create/list/delete webhook subscriptions
- Cron Jobs — Schedule recurring tasks through Hermes cron
- File Operations — Read, write, glob, and search files
- Text Processing — Regex, JSON/YAML/XML parsing, diff
- Codec — Base64, Hex encoding/decoding, JWT decode
- Network — HTTP requests, DNS lookups
- Time — Current time, format/parse datetime
"""


def register_builtin_tools(
    mcp: FastMCP,
    config: HermesMCPConfig,
    retrieval: RetrievalBackend,
) -> None:
    """Register all built-in tools that don't depend on Hermes backend."""
    from hermes_mcp.tools.codec import register_codec_tools
    from hermes_mcp.tools.files import register_file_tools
    from hermes_mcp.tools.network import register_network_tools
    from hermes_mcp.tools.retrieval import register_retrieval_tools
    from hermes_mcp.tools.text import register_text_tools
    from hermes_mcp.tools.time import register_time_tools

    register_retrieval_tools(mcp, retrieval, config)
    register_file_tools(mcp, config)
    register_text_tools(mcp)
    register_codec_tools(mcp)
    register_network_tools(mcp)
    register_time_tools(mcp)


def register_hermes_tools(
    mcp: FastMCP,
    backend: HermesBackend,
    config: HermesMCPConfig,
) -> None:
    """Register tools that depend on Hermes backend."""
    from hermes_mcp.tools.cron import register_cron_tools
    from hermes_mcp.tools.messaging import register_messaging_tools
    from hermes_mcp.tools.webhook import register_webhook_tools

    register_messaging_tools(mcp, backend)
    register_webhook_tools(mcp, backend)
    register_cron_tools(mcp, backend)


def create_server(config: HermesMCPConfig | None = None) -> FastMCP:
    """Create and configure the Hermes MCP server.

    This is the central assembly point:
    1. Resolve backends (Hermes + Retrieval)
    2. Create FastMCP instance
    3. Register all tools from all domains
    4. Return ready-to-run server
    """
    if config is None:
        from hermes_mcp.config.loader import load_config
        config = load_config()

    # Resolve backends
    hermes_backend = _resolve_hermes_backend(config)
    retrieval_backend = RetrievalBackend(
        base_url=config.retrieval.base_url,
        timeout=config.retrieval.timeout,
        default_top_k=config.retrieval.default_top_k,
        similarity_threshold=config.retrieval.similarity_threshold,
    )

    # Create FastMCP server
    mcp = FastMCP(
        name=config.server.name,
        instructions=_build_instructions(config),
    )

    # Register all tools
    register_builtin_tools(mcp, config, retrieval_backend)
    register_hermes_tools(mcp, hermes_backend, config)

    logger.info(
        "Hermes MCP Server created: %s (Hermes: %s, Retrieval: %s)",
        config.server.version,
        hermes_backend.mode,
        f"{config.retrieval.base_url}",
    )

    return mcp
