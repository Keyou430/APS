"""Entry point for Hermes MCP Server.

Usage:
    python -m hermes_mcp                        # stdio transport (default)
    python -m hermes_mcp --http --port 9200     # streamable-http transport
    python -m hermes_mcp --sse --port 9200      # SSE transport
    python -m hermes_mcp --config config/dev.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main() -> None:
    """Parse arguments, load config, create and run the MCP server."""
    parser = argparse.ArgumentParser(
        description="Hermes MCP Server — Unified MCP interface for Hermes Agent",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config YAML file",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use streamable-http transport (default: stdio)",
    )
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Use SSE transport (default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind for HTTP/SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9200,
        help="Port to bind for HTTP/SSE transport (default: 9200)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Log level override",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    args = parser.parse_args()

    if args.version:
        from hermes_mcp._version import __version__
        print(f"hermes-mcp v{__version__}")
        return

    # Setup logging
    log_level = args.log_level or "INFO"
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("hermes_mcp")

    # Load configuration
    from hermes_mcp.config.loader import load_config

    config = load_config(config_path=args.config)

    # Apply CLI overrides
    if args.log_level:
        config.server.log_level = args.log_level
        logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Determine transport
    if args.http:
        transport = "streamable-http"
    elif args.sse:
        transport = "sse"
    else:
        transport = config.server.transport

    host = args.host or config.server.host
    port = args.port or config.server.port

    # Create and run server
    from hermes_mcp.server.factory import create_server

    mcp = create_server(config)

    logger.info("Starting Hermes MCP Server v%s on %s://%s:%s",
                config.server.version, transport, host, port)

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport in ("streamable-http", "sse"):
        mcp.run(transport=transport, host=host, port=port)
    else:
        logger.error("Unknown transport: %s", transport)
        sys.exit(1)


if __name__ == "__main__":
    main()
