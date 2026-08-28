"""Standalone MCP entrypoint exposing only the platform cron callback."""

from __future__ import annotations

from fastmcp import FastMCP

from hermes_mcp.tools.platform_pipeline import register_platform_pipeline_tools


def create_server() -> FastMCP:
    server = FastMCP(name="hermes-platform-pipeline")
    register_platform_pipeline_tools(server)
    return server


if __name__ == "__main__":
    create_server().run()
