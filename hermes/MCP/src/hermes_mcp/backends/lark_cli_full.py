"""Controlled full-business adapter for the local Lark/Feishu CLI."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ProcessFactory = Callable[..., Awaitable[Any]]
TimeSource = Callable[[], float]
IdFactory = Callable[[], str]

ALLOWED_BUSINESS_DOMAINS = frozenset(
    {
        "approval",
        "apps",
        "attendance",
        "base",
        "calendar",
        "contact",
        "docs",
        "drive",
        "event",
        "im",
        "mail",
        "markdown",
        "mindnotes",
        "minutes",
        "note",
        "okr",
        "sheets",
        "slides",
        "task",
        "vc",
        "whiteboard",
        "wiki",
    }
)

_BLOCKED_FLAGS = frozenset({"--as", "--format", "--jq", "--json", "--profile", "--yes"})
_LOCAL_PATH_FLAGS = frozenset({"--file", "--output", "--output-dir"})
_SCHEMA_IDENTIFIER = re.compile(
    r"(?P<domain>[a-z][a-z0-9_-]*)\.[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+\Z"
)
_MAX_ARGUMENTS = 256
_MAX_ARGUMENT_LENGTH = 32_768
_MAX_ARGUMENT_BYTES = 262_144
_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:access[_ -]?token|refresh[_ -]?token|api[_ -]?key|app[_ -]?secret|"
    r"client[_ -]?secret|authorization|password|secret|accessToken|refreshToken|"
    r"appSecret|clientSecret)\b\s*[:=]\s*[\"']?)([^\s,;\"'}]+)"
)
_BEARER_HEADER = re.compile(
    r"(?i)(\b(?:authorization|proxy-authorization)\b\s*[:=]\s*bearer\s+)([^\s,;\"'}]+)"
)
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_REDACTED = "<redacted>"


def redact_diagnostic(value: str) -> str:
    """Remove credential-shaped values from text returned by lark-cli."""

    value = _BEARER_HEADER.sub(rf"\1{_REDACTED}", value)
    value = _SECRET_ASSIGNMENT.sub(rf"\1{_REDACTED}", value)
    return _JWT_PATTERN.sub(_REDACTED, value)


def _safe_json_value(value: object) -> object:
    """Redact credentials while retaining Feishu resource and pagination tokens."""

    secret_keys = {
        "accesstoken",
        "refreshtoken",
        "tenantaccesstoken",
        "useraccesstoken",
        "authtoken",
        "apikey",
        "appsecret",
        "clientsecret",
        "authorization",
        "bearer",
        "password",
        "secret",
        "secretvalue",
        "rawsecret",
        "keymaterial",
    }
    if isinstance(value, dict):
        safe: dict[object, object] = {}
        for field, item in value.items():
            field_key = re.sub(r"[^a-z0-9]", "", str(field).lower())
            is_secret = field_key in secret_keys or field_key.endswith(
                ("accesstoken", "refreshtoken")
            )
            safe[field] = _REDACTED if is_secret else _safe_json_value(item)
        return safe
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_diagnostic(value)
    return value


def _decode_json(value: bytes) -> object | None:
    if not value.strip():
        return None
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    starts = [match.end() - 1 for match in re.finditer(r"(?m)^[ \t]*\{", text)]
    for start in reversed(starts):
        try:
            payload, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if not text[end:].strip():
            return payload
    return None


def _safe_error_code(value: object, *, default: str = "cli_error") -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _SAFE_ERROR_CODE.fullmatch(candidate) else default


class LarkCLIFullError(RuntimeError):
    """A safe failure from the controlled lark-cli adapter."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def as_envelope(self) -> dict[str, object]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


@dataclass
class _ApprovalTicket:
    argv: tuple[str, ...]
    expires_at: float
    used: bool = False


class _ConfirmationRequiredError(RuntimeError):
    def __init__(self, action: str, risk: str) -> None:
        self.action = action
        self.risk = risk
        super().__init__(action)


class LarkCLIFullBackend:
    """Run approved lark-cli business commands without a shell."""

    def __init__(
        self,
        cli_path: str = "lark-cli",
        *,
        workspace_root: str | Path = ".",
        timeout: float = 30.0,
        max_output_bytes: int = 1_048_576,
        enabled: bool = True,
        process_factory: ProcessFactory | None = None,
        approval_ttl: float = 300.0,
        time_source: TimeSource | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        if not isinstance(cli_path, str) or not cli_path.strip() or "\x00" in cli_path:
            raise ValueError("cli_path must be a non-empty executable name")
        if type(timeout) not in (int, float) or timeout <= 0:
            raise ValueError("timeout must be positive")
        if type(max_output_bytes) is not int or max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        if type(approval_ttl) not in (int, float) or approval_ttl <= 0:
            raise ValueError("approval_ttl must be positive")
        self.cli_path = cli_path.strip()
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout = float(timeout)
        self.max_output_bytes = max_output_bytes
        self.enabled = bool(enabled)
        self._process_factory = process_factory or asyncio.create_subprocess_exec
        self._resolve_cli_path = process_factory is None
        self.approval_ttl = float(approval_ttl)
        self._time_source = time_source or time.monotonic
        self._id_factory = id_factory or (lambda: secrets.token_urlsafe(18))
        self._approval_tickets: dict[str, _ApprovalTicket] = {}

    async def help(self, topic: str | None = None) -> dict[str, object]:
        command = [self._command_path()]
        if topic is not None:
            normalized = self._validate_topic(topic)
            command.append(normalized)
        else:
            normalized = "root"
        command.append("--help")
        content = await self._run_text(command)
        return {"ok": True, "data": {"topic": normalized, "content": content}}

    async def schema(self, identifier: str) -> dict[str, object]:
        if not isinstance(identifier, str):
            raise LarkCLIFullError("invalid_command", "schema 标识符无效。")
        match = _SCHEMA_IDENTIFIER.fullmatch(identifier.strip())
        if match is None or match.group("domain") not in ALLOWED_BUSINESS_DOMAINS:
            raise LarkCLIFullError("invalid_command", "schema 只允许已批准的飞书业务域。")
        return await self._run_json(
            [self._command_path(), "schema", identifier.strip()],
            allow_raw=True,
        )

    async def execute(
        self,
        argv: Sequence[str],
        *,
        approval_id: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, object]:
        normalized = self._validate_execute_argv(argv)
        self._validate_local_paths(normalized)
        command = [self._command_path(), *normalized, "--as", "user", "--format", "json"]
        confirmed_retry = approval_id is not None or confirmed
        if confirmed_retry:
            if not confirmed or not isinstance(approval_id, str) or not approval_id:
                raise LarkCLIFullError(
                    "confirmation_invalid",
                    "确认请求必须同时提供 approval_id 和 confirmed=true。",
                )
            self._consume_approval(approval_id, normalized)
            command.append("--yes")
        try:
            return await self._run_json(command)
        except _ConfirmationRequiredError as confirmation:
            if confirmed_retry:
                raise LarkCLIFullError(
                    "confirmation_invalid",
                    "lark-cli 在确认重试后仍拒绝执行，操作已终止。",
                ) from confirmation
            return self._create_confirmation(normalized, confirmation)

    def _create_confirmation(
        self,
        argv: tuple[str, ...],
        confirmation: _ConfirmationRequiredError,
    ) -> dict[str, object]:
        now = self._time_source()
        for ticket_id, ticket in list(self._approval_tickets.items()):
            if ticket.used or ticket.expires_at < now:
                del self._approval_tickets[ticket_id]
        approval_id = ""
        for _ in range(10):
            candidate = self._id_factory()
            if isinstance(candidate, str) and candidate and candidate not in self._approval_tickets:
                approval_id = candidate
                break
        if not approval_id:
            raise LarkCLIFullError("cli_unavailable", "无法创建一次性确认请求。")
        self._approval_tickets[approval_id] = _ApprovalTicket(
            argv=argv,
            expires_at=now + self.approval_ttl,
        )
        safe_argv = [redact_diagnostic(argument)[:1024] for argument in argv]
        return {
            "ok": False,
            "error": {
                "code": "confirmation_required",
                "message": "该飞书操作属于高风险写操作，需要用户明确确认。",
                "approval_id": approval_id,
                "action": confirmation.action,
                "risk": confirmation.risk,
                "argv": safe_argv,
            },
        }

    def _consume_approval(self, approval_id: str, argv: tuple[str, ...]) -> None:
        ticket = self._approval_tickets.get(approval_id)
        now = self._time_source()
        if (
            ticket is None
            or ticket.used
            or ticket.expires_at < now
            or ticket.argv != argv
        ):
            raise LarkCLIFullError(
                "confirmation_invalid",
                "确认请求无效、已过期、已使用或参数不匹配。",
            )
        ticket.used = True

    def _command_path(self) -> str:
        """Resolve npm Windows launchers to the native executable without a shell."""

        if not self._resolve_cli_path or os.name != "nt":
            return self.cli_path
        configured = Path(self.cli_path)
        if configured.suffix.lower() == ".exe":
            return str(configured)
        for candidate in (f"{self.cli_path}.exe", self.cli_path):
            resolved = shutil.which(candidate)
            if not resolved:
                continue
            resolved_path = Path(resolved)
            if resolved_path.suffix.lower() == ".exe":
                return str(resolved_path)
            native = (
                resolved_path.parent
                / "node_modules"
                / "@larksuite"
                / "cli"
                / "bin"
                / "lark-cli.exe"
            )
            if native.is_file():
                return str(native)
        return self.cli_path

    @staticmethod
    def _validate_topic(topic: str) -> str:
        if not isinstance(topic, str) or topic.strip() not in ALLOWED_BUSINESS_DOMAINS:
            raise LarkCLIFullError("invalid_command", "帮助查询只允许已批准的飞书业务域。")
        return topic.strip()

    @staticmethod
    def _validate_execute_argv(argv: Sequence[str]) -> tuple[str, ...]:
        if isinstance(argv, str | bytes) or not isinstance(argv, Sequence):
            raise LarkCLIFullError("invalid_command", "argv 必须是参数数组。")
        if not 1 <= len(argv) <= _MAX_ARGUMENTS:
            raise LarkCLIFullError("invalid_command", "argv 参数数量无效。")
        normalized: list[str] = []
        total_length = 0
        for index, argument in enumerate(argv):
            is_empty_query_value = (
                isinstance(argument, str)
                and argument == ""
                and index > 0
                and argv[index - 1] == "--query"
            )
            if (
                not isinstance(argument, str)
                or (not argument and not is_empty_query_value)
                or "\x00" in argument
                or len(argument) > _MAX_ARGUMENT_LENGTH
            ):
                raise LarkCLIFullError("invalid_command", "argv 包含无效参数。")
            total_length += len(argument.encode("utf-8"))
            if total_length > _MAX_ARGUMENT_BYTES:
                raise LarkCLIFullError("invalid_command", "argv 总长度超过限制。")
            normalized.append(argument)
        if normalized[0] not in ALLOWED_BUSINESS_DOMAINS:
            raise LarkCLIFullError("invalid_command", "只允许已批准的飞书业务域命令。")
        for argument in normalized[1:]:
            flag = argument.split("=", 1)[0].lower()
            if flag in _BLOCKED_FLAGS:
                raise LarkCLIFullError("invalid_command", f"不允许模型设置 {flag}。")
        return tuple(normalized)

    def _validate_local_paths(self, argv: Sequence[str]) -> None:
        index = 1
        while index < len(argv):
            argument = argv[index]
            if argument.startswith("@") and len(argument) > 1:
                self._validate_local_path(argument[1:])
            flag, separator, inline_value = argument.partition("=")
            if flag.lower() not in _LOCAL_PATH_FLAGS:
                index += 1
                continue
            if separator:
                self._validate_local_path(inline_value)
            else:
                if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                    raise LarkCLIFullError("invalid_path", f"{flag} 缺少相对路径参数。")
                self._validate_local_path(argv[index + 1])
                index += 1
            index += 1

    def _validate_local_path(self, value: str) -> None:
        if not value or "\x00" in value or value.startswith("~"):
            raise LarkCLIFullError("invalid_path", "本地路径必须是工作目录内的相对路径。")
        candidate = Path(value)
        if candidate.is_absolute():
            raise LarkCLIFullError("invalid_path", "本地路径必须是工作目录内的相对路径。")
        resolved = (self.workspace_root / candidate).resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise LarkCLIFullError(
                "invalid_path",
                "本地路径必须位于工作目录内。",
            ) from exc

    async def _communicate(self, command: Sequence[str]) -> tuple[Any, bytes, bytes]:
        if not self.enabled:
            raise LarkCLIFullError("disabled", "lark-cli MCP 当前未启用。")
        process: Any | None = None
        try:
            process = await self._process_factory(
                *command,
                cwd=self.workspace_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            if process is not None:
                with suppress(OSError, ProcessLookupError):
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=1.0)
                except (TimeoutError, OSError, ProcessLookupError):
                    with suppress(OSError, ProcessLookupError):
                        process.kill()
            raise LarkCLIFullError("timeout", "lark-cli 请求超时，请稍后重试。") from exc
        except FileNotFoundError as exc:
            raise LarkCLIFullError("cli_unavailable", "找不到 lark-cli 原生可执行文件。") from exc
        except OSError as exc:
            raise LarkCLIFullError("cli_unavailable", "lark-cli 当前不可用。") from exc
        except Exception as exc:
            raise LarkCLIFullError("cli_unavailable", "lark-cli 当前不可用。") from exc
        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
            raise LarkCLIFullError("invalid_json", "lark-cli 返回了无法读取的输出。")
        if len(stdout) + len(stderr) > self.max_output_bytes:
            raise LarkCLIFullError("output_too_large", "lark-cli 返回内容超过大小限制。")
        return process, stdout, stderr

    async def _run_text(self, command: Sequence[str]) -> str:
        process, stdout, stderr = await self._communicate(command)
        if getattr(process, "returncode", 1) != 0:
            raise self._failure_from_output(stdout, stderr)
        return redact_diagnostic(stdout.decode("utf-8", errors="replace"))

    async def _run_json(
        self,
        command: Sequence[str],
        *,
        allow_raw: bool = False,
    ) -> dict[str, object]:
        process, stdout, stderr = await self._communicate(command)
        if getattr(process, "returncode", 1) != 0:
            payload = _decode_json(stderr) or _decode_json(stdout)
            if getattr(process, "returncode", 1) == 10 and isinstance(payload, dict):
                confirmation = self._confirmation_from_payload(payload)
                if confirmation is not None:
                    raise confirmation
            raise self._failure_from_output(stdout, stderr)
        payload = _decode_json(stdout)
        if not isinstance(payload, dict):
            raise self._invalid_json_error(stderr)
        if payload.get("ok") is False:
            raise self._failure_from_payload(payload)
        if payload.get("ok") is True:
            if "data" not in payload:
                raise LarkCLIFullError("invalid_json", "lark-cli 返回缺少 data 数据。")
            data = payload["data"]
        elif allow_raw:
            data = payload
        else:
            raise LarkCLIFullError("invalid_json", "lark-cli 返回的业务信封无效。")
        return {"ok": True, "data": _safe_json_value(data)}

    @staticmethod
    def _confirmation_from_payload(
        payload: dict[str, object],
    ) -> _ConfirmationRequiredError | None:
        raw_error = payload.get("error")
        if not isinstance(raw_error, dict):
            return None
        if (
            raw_error.get("type") != "confirmation"
            or raw_error.get("subtype") != "confirmation_required"
        ):
            return None
        action = redact_diagnostic(str(raw_error.get("action") or "飞书写操作"))[:256]
        risk = redact_diagnostic(str(raw_error.get("risk") or "high-risk-write"))[:128]
        return _ConfirmationRequiredError(action, risk)

    def _failure_from_output(self, stdout: bytes, stderr: bytes) -> LarkCLIFullError:
        payload = _decode_json(stderr) or _decode_json(stdout)
        if isinstance(payload, dict):
            return self._failure_from_payload(payload)
        return self._invalid_json_error(stderr or stdout)

    def _invalid_json_error(self, diagnostic: bytes) -> LarkCLIFullError:
        safe_diagnostic = redact_diagnostic(
            diagnostic[: min(self.max_output_bytes, 1500)].decode("utf-8", errors="replace")
        ).strip()
        message = "lark-cli 返回的不是有效 JSON。"
        if safe_diagnostic:
            message = f"{message} 诊断：{safe_diagnostic}"
        return LarkCLIFullError("invalid_json", message[:2000])

    @staticmethod
    def _failure_from_payload(payload: dict[str, object]) -> LarkCLIFullError:
        raw_error = payload.get("error")
        error = raw_error if isinstance(raw_error, dict) else payload
        error_type = _safe_error_code(error.get("type"), default="")
        subtype = _safe_error_code(error.get("subtype"), default="")
        code = _safe_error_code(error.get("code"))
        raw_message = error.get("message") or error.get("detail") or error.get("hint")
        message = redact_diagnostic(str(raw_message or "lark-cli 请求失败。"))

        if (error_type, subtype) == ("authentication", "token_missing") or code in {
            "unauthorized",
            "auth_required",
            "not_authenticated",
            "user_identity_missing",
        }:
            return LarkCLIFullError(
                "user_auth_required",
                "请先完成本机 lark-cli 用户授权。",
            )
        if (error_type, subtype) == ("authorization", "scope_missing") or code == "missing_scope":
            scopes = error.get("missing_scopes") or error.get("missingScopes")
            scope_names = []
            if isinstance(scopes, list):
                scope_names = [
                    redact_diagnostic(str(scope))
                    for scope in scopes[:20]
                    if isinstance(scope, str)
                ]
            suffix = f"：{', '.join(scope_names)}" if scope_names else ""
            return LarkCLIFullError(
                "missing_scope",
                f"请在飞书应用和用户授权中补齐所需权限{suffix}。",
            )
        if (error_type, subtype) == ("permission", "forbidden") or code in {
            "forbidden",
            "permission_denied",
        }:
            return LarkCLIFullError(
                "permission_denied",
                "当前已授权用户无权访问该飞书资源。",
            )
        return LarkCLIFullError(code, message[:2000])


__all__ = [
    "ALLOWED_BUSINESS_DOMAINS",
    "LarkCLIFullBackend",
    "LarkCLIFullError",
    "redact_diagnostic",
]
