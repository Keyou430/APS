"""Pydantic configuration models for Hermes MCP Server."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HermesBackendConfig(BaseModel):
    """Configuration for Hermes backend connection."""

    mode: Literal["sdk", "cli", "auto"] = "auto"
    sdk_path: str = r"C:\Users\86135\AppData\Roaming\uv\tools\hermes-agent\Lib\site-packages"
    exe_path: str = r"D:\Replica1.0\hermes\hermes.exe"
    timeout: float = 30.0


class RetrievalConfig(BaseModel):
    """Configuration for three-source retrieval service."""

    base_url: str = "http://localhost:8001"
    timeout: float = 60.0
    experience_enabled: bool = True
    database_enabled: bool = True
    knowledge_enabled: bool = True
    default_top_k: int = 3
    similarity_threshold: float = 0.3


class SandboxConfig(BaseModel):
    """Sandbox configuration for command execution."""

    enabled: bool = True
    allowed_commands: list[str] = Field(default_factory=lambda: [
        "python", "node", "echo", "cat", "ls", "dir",
        "head", "tail", "wc", "grep", "sort", "uniq", "cut", "tr",
    ])
    allowed_directories: list[str] = Field(default_factory=lambda: ["./data", "/tmp/hermes"])
    default_timeout: float = 30.0
    max_output_bytes: int = 1_048_576  # 1 MB


class FileOpsConfig(BaseModel):
    """File operations configuration."""

    max_file_size: int = 10_485_760  # 10 MB
    allowed_directories: list[str] = Field(default_factory=lambda: [
        ".", "./data", "/tmp/hermes",
    ])


class FeishuReadonlyConfig(BaseModel):
    """Configuration for the isolated, read-only Feishu MCP service."""

    enabled: bool = True
    cli_path: str = Field(default="lark-cli", min_length=1)
    timeout: float = Field(default=30.0, gt=0)
    max_output_bytes: int = Field(default=1_048_576, gt=0)


class LarkCLIFullConfig(BaseModel):
    """Configuration for the controlled full-business lark-cli MCP service."""

    enabled: bool = True
    cli_path: str = Field(default="lark-cli", min_length=1)
    timeout: float = Field(default=30.0, gt=0)
    max_output_bytes: int = Field(default=1_048_576, gt=0)
    approval_ttl: float = Field(default=300.0, gt=0)


class ServerConfig(BaseModel):
    """Server configuration."""

    name: str = "hermes-mcp"
    version: str = "0.1.0"
    transport: Literal["stdio", "streamable-http", "sse"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 9200
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class HermesMCPConfig(BaseModel):
    """Complete Hermes MCP Server configuration."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    hermes: HermesBackendConfig = Field(default_factory=HermesBackendConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    file_ops: FileOpsConfig = Field(default_factory=FileOpsConfig)
    feishu_readonly: FeishuReadonlyConfig = Field(default_factory=FeishuReadonlyConfig)
    lark_cli_full: LarkCLIFullConfig = Field(default_factory=LarkCLIFullConfig)
