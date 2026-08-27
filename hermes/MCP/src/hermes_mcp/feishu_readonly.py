"""Standalone FastMCP service exposing only read-only Feishu group tools."""

from __future__ import annotations

import argparse
import ipaddress
import logging
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from hermes_mcp.backends.lark_cli import LarkCLIBackend, LarkCLIError
from hermes_mcp.config.loader import load_config
from hermes_mcp.config.schema import HermesMCPConfig


def _tool_error(error: LarkCLIError) -> dict[str, str]:
    return {"error": error.code, "message": error.message}


def register_feishu_readonly_tools(mcp: Any, backend: LarkCLIBackend) -> None:
    """Register the exact three safe group-reading tools."""

    @mcp.tool(
        name="list_feishu_groups",
        description="列出当前已授权飞书用户加入的群聊。仅返回群列表，不包含私聊。",
    )
    async def list_feishu_groups(
        page_size: int = 50,
        page_token: str | None = None,
        sort: str = "active_time",
    ) -> object:
        try:
            return await backend.list_feishu_groups(
                page_size=page_size,
                page_token=page_token,
                sort=sort,
            )
        except LarkCLIError as error:
            return _tool_error(error)

    @mcp.tool(
        name="read_feishu_group_messages",
        description="读取一个飞书群的一页历史消息。禁止私聊、反应和附件下载。",
    )
    async def read_feishu_group_messages(
        chat_id: str,
        start: str | None = None,
        end: str | None = None,
        order: str = "desc",
        page_size: int = 50,
        page_token: str | None = None,
    ) -> object:
        try:
            return await backend.read_feishu_group_messages(
                chat_id,
                start=start,
                end=end,
                order=order,
                page_size=page_size,
                page_token=page_token,
            )
        except LarkCLIError as error:
            return _tool_error(error)

    @mcp.tool(
        name="search_feishu_group_messages",
        description="在飞书群聊范围内搜索消息文本。必须提供关键词、群、发送人或时间筛选。",
    )
    async def search_feishu_group_messages(
        query: str | None = None,
        chat_ids: list[str] | None = None,
        sender_ids: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> object:
        try:
            return await backend.search_feishu_group_messages(
                query=query,
                chat_ids=chat_ids,
                sender_ids=sender_ids,
                start=start,
                end=end,
                page_size=page_size,
                page_token=page_token,
            )
        except LarkCLIError as error:
            return _tool_error(error)


def create_feishu_readonly_server(
    config: HermesMCPConfig | None = None,
    *,
    backend: LarkCLIBackend | None = None,
) -> FastMCP:
    config = config or load_config()
    backend = backend or LarkCLIBackend(
        cli_path=config.feishu_readonly.cli_path,
        timeout=config.feishu_readonly.timeout,
        max_output_bytes=config.feishu_readonly.max_output_bytes,
        enabled=config.feishu_readonly.enabled,
    )
    mcp = FastMCP(
        name="hermes-feishu-readonly",
        instructions=(
            "仅允许读取已授权用户可见的飞书群。不得发送、回复、转发、撤回、"
            "读取私聊、下载附件、监听事件或执行任意命令。"
        ),
    )
    register_feishu_readonly_tools(mcp, backend)
    return mcp


def _is_loopback_host(host: str) -> bool:
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Hermes Feishu read-only MCP server")
    parser.add_argument("--config", type=Path, default=None, help="Path to config YAML file")
    parser.add_argument("--http", action="store_true", help="Use streamable-http transport")
    parser.add_argument("--sse", action="store_true", help="Use SSE transport")
    parser.add_argument("--host", default=None, help="HTTP/SSE bind host")
    parser.add_argument("--port", type=int, default=None, help="HTTP/SSE bind port")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level or "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    config = load_config(config_path=args.config)
    transport = "streamable-http" if args.http else "sse" if args.sse else config.server.transport
    host = args.host or config.server.host
    port = args.port or config.server.port
    if transport != "stdio" and not _is_loopback_host(host):
        raise SystemExit("只读飞书服务的 HTTP/SSE 监听地址必须是本机回环地址。")
    server = create_feishu_readonly_server(config)
    if transport == "stdio":
        server.run(transport="stdio")
    elif transport in {"streamable-http", "sse"}:
        server.run(transport=transport, host=host, port=port)
    else:
        raise SystemExit(f"Unknown transport: {transport}")


if __name__ == "__main__":
    main()


__all__ = [
    "LarkCLIBackend",
    "LarkCLIError",
    "create_feishu_readonly_server",
    "main",
    "register_feishu_readonly_tools",
]
