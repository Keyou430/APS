"""Standalone FastMCP service for controlled lark-cli business access."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastmcp import Context, FastMCP

from hermes_mcp.backends.lark_cli_full import (
    LarkCLIFullBackend,
    LarkCLIFullError,
    redact_diagnostic,
)
from hermes_mcp.config.loader import load_config
from hermes_mcp.config.schema import HermesMCPConfig


def register_lark_cli_full_tools(mcp: Any, backend: LarkCLIFullBackend) -> None:
    """Register only the three controlled lark-cli tools."""

    @mcp.tool(
        name="lark_cli_help",
        description=(
            "查看 lark-cli 根帮助或已批准飞书业务域的帮助。优先寻找 +shortcut；"
            "查询 shortcut 时把域和命令放在同一个 topic，例如 docs +create。"
            "此工具不访问飞书业务数据。"
        ),
    )
    async def lark_cli_help(topic: str | None = None) -> object:
        try:
            return await backend.help(topic)
        except LarkCLIFullError as error:
            return error.as_envelope()

    @mcp.tool(
        name="lark_cli_schema",
        description=(
            "查看已批准飞书业务域中一个 typed OpenAPI 方法的参数、scope 和风险。"
            "调用 typed 方法前先检查 schema；+shortcut 应改用 lark_cli_help。"
            "此工具不访问飞书业务数据。"
        ),
    )
    async def lark_cli_schema(identifier: str) -> object:
        try:
            return await backend.schema(identifier)
        except LarkCLIFullError as error:
            return error.as_envelope()

    @mcp.tool(
        name="lark_cli_execute",
        description=(
            "以用户身份执行受控的 lark-cli 飞书业务参数数组。禁止 Shell、raw api、"
            "账号配置和直接 --yes。高风险写操作会由平台弹出审批，只有用户明确同意后"
            "才会执行。"
        ),
    )
    async def lark_cli_execute(
        argv: list[str],
        ctx: Context,
    ) -> object:
        try:
            result = await backend.execute(argv)
            error = result.get("error") if isinstance(result, dict) else None
            if not isinstance(error, dict) or error.get("code") != "confirmation_required":
                return result

            action = str(error.get("action") or "飞书写操作")
            risk = str(error.get("risk") or "high-risk-write")
            approval_id = error.get("approval_id")
            if not isinstance(approval_id, str) or not approval_id:
                raise LarkCLIFullError("confirmation_invalid", "高风险操作确认票据无效。")

            argv_summary = redact_diagnostic(json.dumps(argv, ensure_ascii=False))[:1500]
            approval = await ctx.elicit(
                f"高风险飞书操作：{action}\n风险：{risk}\n参数：{argv_summary}",
                None,
            )
            if getattr(approval, "action", None) != "accept":
                return {
                    "ok": False,
                    "error": {
                        "code": "confirmation_declined",
                        "message": "用户未批准该飞书高风险操作。",
                        "action": action,
                        "risk": risk,
                    },
                }
            return await backend.execute(
                argv,
                approval_id=approval_id,
                confirmed=True,
            )
        except LarkCLIFullError as error:
            return error.as_envelope()


def create_lark_cli_full_server(
    config: HermesMCPConfig | None = None,
    *,
    backend: LarkCLIFullBackend | None = None,
) -> FastMCP:
    if backend is None:
        config = config or load_config()
        settings = config.lark_cli_full
        workspace_root = Path(os.environ.get("HERMES_HOME") or Path.cwd()).resolve()
        backend = LarkCLIFullBackend(
            cli_path=settings.cli_path,
            workspace_root=workspace_root,
            timeout=settings.timeout,
            max_output_bytes=settings.max_output_bytes,
            enabled=settings.enabled,
            approval_ttl=settings.approval_ttl,
        )
    mcp = FastMCP(
        name="hermes-lark-cli",
        instructions=(
            "通过本机 lark-cli 用户授权访问已批准的飞书业务域。优先使用 +shortcut，"
            "typed API 调用前查询 schema。不得调用 raw api、CLI 管理命令、任意 Shell，"
            "也不得绕过 confirmation_required。Knowledge Hermes 不连接本服务。"
        ),
    )
    register_lark_cli_full_tools(mcp, backend)
    return mcp


def _is_loopback_host(host: str) -> bool:
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Hermes controlled lark-cli MCP server")
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
        raise SystemExit("lark-cli MCP 的 HTTP/SSE 监听地址必须是本机回环地址。")
    server = create_lark_cli_full_server(config)
    if transport == "stdio":
        server.run(transport="stdio")
    elif transport in {"streamable-http", "sse"}:
        server.run(transport=transport, host=host, port=port)
    else:
        raise SystemExit(f"Unknown transport: {transport}")


if __name__ == "__main__":
    main()


__all__ = [
    "LarkCLIFullBackend",
    "LarkCLIFullError",
    "create_lark_cli_full_server",
    "main",
    "register_lark_cli_full_tools",
]
