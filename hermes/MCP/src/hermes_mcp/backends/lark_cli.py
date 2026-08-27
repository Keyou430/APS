"""Restricted read-only backend for the local Lark/Feishu CLI."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

ProcessFactory = Callable[..., Awaitable[Any]]

_CHAT_ID_PATTERN = re.compile(r"oc_[A-Za-z0-9_-]+\Z")
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


class LarkCLIError(RuntimeError):
    """A safe, actionable failure from a read-only Lark CLI operation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def redact_diagnostic(value: str) -> str:
    """Remove credential-shaped values from CLI diagnostics."""

    value = _BEARER_HEADER.sub(rf"\1{_REDACTED}", value)
    value = _SECRET_ASSIGNMENT.sub(rf"\1{_REDACTED}", value)
    return _JWT_PATTERN.sub(_REDACTED, value)


def _bounded_text(value: bytes, limit: int) -> str:
    return value[:limit].decode("utf-8", errors="replace")


def _safe_code(value: object, default: str = "cli_error") -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _SAFE_ERROR_CODE.fullmatch(candidate) else default


def _scope_names(value: object) -> list[str]:
    """Extract declared Lark permission names from structured or textual hints."""

    if isinstance(value, list):
        return [redact_diagnostic(str(item)) for item in value[:20]]
    if isinstance(value, str):
        return re.findall(r"\b[a-z][a-z0-9_-]*:[a-z0-9_.:-]+\b", value.lower())[:20]
    return []


def _safe_json_value(value: object, *, key: str | None = None) -> object:
    """Redact only credential-bearing fields while preserving pagination tokens."""

    normalized_key = re.sub(r"[^a-z0-9]", "", str(key or "").lower())
    if normalized_key in {"pagetoken", "nextpagetoken"} and isinstance(value, str):
        return value

    secret_keys = {
        "accesstoken",
        "refreshtoken",
        "authtoken",
        "apikey",
        "apptoken",
        "appsecret",
        "clientsecret",
        "authorization",
        "bearer",
        "password",
        "secret",
        "secretvalue",
        "rawsecret",
        "keymaterial",
        "token",
    }
    if isinstance(value, dict):
        safe: dict[object, object] = {}
        for field, item in value.items():
            field_key = re.sub(r"[^a-z0-9]", "", str(field).lower())
            is_secret = field_key in secret_keys or field_key.endswith(
                ("accesstoken", "refreshtoken")
            )
            safe[field] = _REDACTED if is_secret else _safe_json_value(item, key=str(field))
        return safe
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_diagnostic(value)
    return value


def _validate_text(value: str, *, field: str, max_length: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
        or "\x00" in value
    ):
        raise LarkCLIError("invalid_parameter", f"{field} 参数无效。")
    return value.strip()


def _validate_time(value: str, *, field: str) -> str:
    normalized = _validate_text(value, field=field)
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LarkCLIError("invalid_parameter", f"{field} 必须是 ISO 8601 日期或时间。") from exc
    return normalized


def _validate_page_size(value: int, *, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise LarkCLIError("invalid_page_size", f"page_size 必须是 1 至 {maximum} 的整数。")
    return value


def _validate_chat_id(value: str) -> str:
    value = _validate_text(value, field="chat_id", max_length=128)
    if not _CHAT_ID_PATTERN.fullmatch(value):
        raise LarkCLIError("invalid_chat_id", "只允许访问格式为 oc_... 的飞书群聊。")
    return value


def _validate_id_list(values: Sequence[str] | None, *, field: str) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str | bytes):
        raise LarkCLIError("invalid_parameter", f"{field} 必须是 ID 列表。")
    if len(values) > 50:
        raise LarkCLIError("invalid_parameter", f"{field} 最多允许 50 个值。")
    result: list[str] = []
    for value in values:
        normalized = _validate_text(value, field=field, max_length=128)
        if "," in normalized:
            raise LarkCLIError("invalid_parameter", f"{field} 中不能包含逗号。")
        result.append(normalized)
    return result


class LarkCLIBackend:
    """Run only the three fixed, read-only Feishu shortcut commands."""

    def __init__(
        self,
        cli_path: str = "lark-cli",
        *,
        timeout: float = 30.0,
        max_output_bytes: int = 1_048_576,
        enabled: bool = True,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self.cli_path = _validate_text(cli_path, field="cli_path", max_length=1024)
        if os.name == "nt" and Path(self.cli_path).suffix.lower() in {".bat", ".cmd", ".ps1"}:
            raise ValueError("cli_path must point to an executable, not a Windows shell wrapper")
        if type(timeout) not in (int, float) or timeout <= 0:
            raise ValueError("timeout must be positive")
        if type(max_output_bytes) is not int or max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self.timeout = float(timeout)
        self.max_output_bytes = max_output_bytes
        self.enabled = bool(enabled)
        self._process_factory = process_factory or asyncio.create_subprocess_exec
        self._resolve_cli_path = process_factory is None
        self._group_ids: set[str] | None = None

    def _command_path(self) -> str:
        """Resolve npm-style Windows launchers without invoking a shell."""

        if not self._resolve_cli_path or os.name != "nt":
            return self.cli_path
        path = self.cli_path
        if Path(path).suffix.lower() == ".exe":
            return path
        configured_path = Path(path)
        if configured_path.is_file():
            return str(configured_path)
        for candidate in (f"{path}.exe", path):
            resolved = shutil.which(candidate)
            if resolved:
                resolved_path = Path(resolved)
                if resolved_path.suffix.lower() == ".exe":
                    return str(resolved_path)
                # npm installs a shell wrapper next to node_modules; use the
                # package's native executable instead of executing the wrapper.
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
        return path

    async def list_feishu_groups(
        self,
        *,
        page_size: int = 50,
        page_token: str | None = None,
        sort: str = "active_time",
    ) -> object:
        _validate_page_size(page_size, maximum=100)
        if sort not in {"create_time", "active_time"}:
            raise LarkCLIError("invalid_sort", "sort 只允许 create_time 或 active_time。")
        args = [
            "im",
            "+chat-list",
            "--as",
            "user",
            "--types",
            "group",
            "--page-size",
            str(page_size),
        ]
        if page_token is not None:
            args.extend(["--page-token", _validate_text(page_token, field="page_token")])
        args.extend(["--sort", sort, "--format", "json"])
        result = await self._run(args)
        self._cache_group_ids(result)
        return self._project_group_list(result)

    @staticmethod
    def _extract_group_ids(data: object) -> set[str]:
        if not isinstance(data, dict):
            return set()
        items = data.get("items") or data.get("chats")
        if not isinstance(items, list):
            return set()
        ids: set[str] = set()
        for item in items:
            if isinstance(item, dict):
                for key in ("chat_id", "chatId", "id"):
                    candidate = item.get(key)
                    if isinstance(candidate, str) and _CHAT_ID_PATTERN.fullmatch(candidate):
                        ids.add(candidate)
                        break
        return ids

    @staticmethod
    def _project_group_list(data: object) -> object:
        """Return only documented group fields and pagination metadata."""

        if not isinstance(data, dict):
            return data
        raw_items = data.get("items") or data.get("chats") or []
        items: list[dict[str, object]] = []
        if isinstance(raw_items, list):
            field_map = {
                "chat_id": ("chat_id", "chatId", "id"),
                "name": ("name",),
                "description": ("description",),
                "status": ("status", "chat_status", "chatStatus"),
            }
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                item: dict[str, object] = {}
                for output_key, input_keys in field_map.items():
                    for input_key in input_keys:
                        if input_key in raw_item:
                            item[output_key] = raw_item[input_key]
                            break
                if item:
                    items.append(item)
        result: dict[str, object] = {"items": items}
        for key in (
            "has_more",
            "hasMore",
            "page_token",
            "pageToken",
            "next_page_token",
            "nextPageToken",
        ):
            if key in data:
                result[key] = data[key]
        return result

    def _cache_group_ids(self, data: object) -> None:
        ids = self._extract_group_ids(data)
        if self._group_ids is None:
            self._group_ids = set()
        self._group_ids.update(ids)

    async def _refresh_group_ids(self) -> set[str]:
        """Read every page of the current user's group list for an allowlist."""

        ids: set[str] = set()
        page_token: str | None = None
        for _ in range(100):
            args = [
                "im",
                "+chat-list",
                "--as",
                "user",
                "--types",
                "group",
                "--page-size",
                "100",
            ]
            if page_token:
                args.extend(["--page-token", page_token])
            args.extend(["--sort", "active_time", "--format", "json"])
            data = await self._run(args)
            ids.update(self._extract_group_ids(data))
            if not isinstance(data, dict):
                break
            next_token = data.get("page_token") or data.get("next_page_token")
            if not isinstance(next_token, str) or not next_token:
                break
            page_token = next_token
        else:
            raise LarkCLIError("pagination_limit", "飞书群列表分页次数超过安全限制。")
        self._group_ids = ids
        return ids

    async def read_feishu_group_messages(
        self,
        chat_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
        order: str = "desc",
        page_size: int = 50,
        page_token: str | None = None,
    ) -> object:
        chat_id = _validate_chat_id(chat_id)
        _validate_page_size(page_size, maximum=50)
        if order not in {"asc", "desc"}:
            raise LarkCLIError("invalid_order", "order 只允许 asc 或 desc。")
        args = [
            "im",
            "+chat-messages-list",
            "--as",
            "user",
            "--chat-id",
            chat_id,
            "--no-reactions",
            "--order",
            order,
            "--page-size",
            str(page_size),
        ]
        optional_args = (
            ("--start", start, "start"),
            ("--end", end, "end"),
            ("--page-token", page_token, "page_token"),
        )
        for flag, value, field in optional_args:
            if value is not None:
                validator = _validate_time if field in {"start", "end"} else _validate_text
                args.extend([flag, validator(value, field=field)])
        if self._group_ids is None or chat_id not in self._group_ids:
            await self._refresh_group_ids()
        if self._group_ids is None or chat_id not in self._group_ids:
            raise LarkCLIError("chat_not_allowed", "chat_id 不在当前用户可访问的群聊列表中。")
        args.extend(["--format", "json"])
        return await self._run(args)

    async def search_feishu_group_messages(
        self,
        *,
        query: str | None = None,
        chat_ids: Sequence[str] | None = None,
        sender_ids: Sequence[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> object:
        _validate_page_size(page_size, maximum=50)
        normalized_query: str | None = None
        if query is not None:
            if not isinstance(query, str):
                _validate_text(query, field="query", max_length=512)
            if len(query) > 512 or "\x00" in query:
                _validate_text(query, field="query", max_length=512)
            if query.strip():
                normalized_query = _validate_text(query, field="query", max_length=512)
        normalized_chats = _validate_id_list(chat_ids, field="chat_ids")
        normalized_chats = [_validate_chat_id(value) for value in normalized_chats]
        normalized_senders = _validate_id_list(sender_ids, field="sender_ids")
        normalized_start = _validate_time(start, field="start") if start is not None else None
        normalized_end = _validate_time(end, field="end") if end is not None else None
        if not any(
            (
                normalized_query,
                normalized_chats,
                normalized_senders,
                normalized_start,
                normalized_end,
            )
        ):
            raise LarkCLIError(
                "search_filter_required",
                "跨群搜索至少需要关键词、群、发送人或时间范围中的一项。",
            )
        args = [
            "im",
            "+messages-search",
            "--as",
            "user",
            "--chat-type",
            "group",
            "--no-reactions",
            "--page-size",
            str(page_size),
        ]
        if normalized_query:
            args.extend(["--query", normalized_query])
        if normalized_chats:
            args.extend(["--chat-id", ",".join(normalized_chats)])
        if normalized_senders:
            args.extend(["--sender", ",".join(normalized_senders)])
        if normalized_start is not None:
            args.extend(["--start", normalized_start])
        if normalized_end is not None:
            args.extend(["--end", normalized_end])
        if page_token is not None:
            args.extend(["--page-token", _validate_text(page_token, field="page_token")])
        args.extend(["--format", "json"])
        return await self._run(args)

    async def _run(self, args: Sequence[str]) -> object:
        if not self.enabled:
            raise LarkCLIError("disabled", "飞书只读服务当前未启用。")
        process: Any | None = None
        command = [self._command_path(), *args]
        try:
            process = await self._process_factory(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            if process is not None:
                try:
                    process.terminate()
                except (OSError, ProcessLookupError):
                    pass
                else:
                    try:
                        await asyncio.wait_for(process.wait(), timeout=1.0)
                    except (TimeoutError, OSError, ProcessLookupError):
                        with suppress(ProcessLookupError):
                            process.kill()
            raise LarkCLIError("timeout", "飞书只读查询超时，请稍后重试。") from exc
        except FileNotFoundError as exc:
            raise LarkCLIError("cli_not_found", "找不到 lark-cli，请先安装并加入 PATH。") from exc
        except OSError as exc:
            raise LarkCLIError("cli_unavailable", "lark-cli 当前不可用，请检查本机安装。") from exc
        except Exception as exc:
            raise LarkCLIError("cli_unavailable", "lark-cli 当前不可用，请检查本机安装。") from exc

        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
            raise LarkCLIError("invalid_output", "lark-cli 返回了无法读取的输出。")
        if len(stdout) + len(stderr) > self.max_output_bytes:
            raise LarkCLIError("output_too_large", "lark-cli 返回内容超过大小限制。")
        stdout_text = _bounded_text(stdout, self.max_output_bytes)
        stderr_text = _bounded_text(stderr, self.max_output_bytes)
        payload: object | None = None
        if stdout_text.strip():
            try:
                payload = json.loads(stdout_text)
            except json.JSONDecodeError:
                payload = None

        if getattr(process, "returncode", 1) != 0:
            raise self._failure_from(payload, stderr_text)
        if not isinstance(payload, dict):
            diagnostic = redact_diagnostic(stderr_text).strip()
            message = "lark-cli 返回的不是有效 JSON。"
            if diagnostic:
                message = f"{message} 诊断：{diagnostic}"
            raise LarkCLIError("invalid_json", message[:2000])
        if payload.get("ok") is False or payload.get("success") is False:
            raise self._failure_from(payload, stderr_text)
        if "data" not in payload:
            raise LarkCLIError("invalid_envelope", "lark-cli 返回缺少 data 数据。")
        return _safe_json_value(payload["data"])

    @staticmethod
    def _failure_from(payload: object | None, stderr: str) -> LarkCLIError:
        error: object = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            raw_code = error.get("code")
            raw_type = error.get("type")
            raw_subtype = error.get("subtype")
            raw_hint = error.get("hint")
            raw_message = error.get("message") or error.get("detail") or raw_hint
            scopes = (
                error.get("missing_scopes")
                or error.get("missingScopes")
                or error.get("scopes")
            )
            if scopes is None and isinstance(error.get("details"), dict):
                details = error["details"]
                scopes = details.get("missing_scopes") or details.get("missingScopes")
            if scopes is None and isinstance(raw_hint, dict):
                hint = raw_hint
                scopes = (
                    hint.get("missing_scopes")
                    or hint.get("missingScopes")
                    or hint.get("scopes")
                )
            if scopes is None:
                scopes = _scope_names(raw_hint)
        else:
            raw_code = payload.get("code") if isinstance(payload, dict) else None
            raw_type = payload.get("type") if isinstance(payload, dict) else None
            raw_subtype = payload.get("subtype") if isinstance(payload, dict) else None
            raw_message = error or (payload.get("message") if isinstance(payload, dict) else None)
            scopes = payload.get("missing_scopes") if isinstance(payload, dict) else None
        combined = redact_diagnostic(str(raw_message or stderr or "lark-cli 请求失败。"))
        lowered = combined.lower()
        code = _safe_code(raw_code)
        error_type = _safe_code(raw_type, default="")
        error_subtype = _safe_code(raw_subtype, default="")
        if (error_type, error_subtype) == ("authentication", "token_missing"):
            code = "user_auth_required"
            combined = "请先完成本机 lark-cli 用户授权。"
        elif (error_type, error_subtype) == ("authorization", "scope_missing"):
            code = "missing_scope"
            scope_names = _scope_names(scopes)
            if scope_names:
                listed = ", ".join(scope_names)
                combined = (
                    "请在飞书应用或用户授权中补齐这些权限："
                    f"{listed}。"
                )
            else:
                combined = f"请在飞书应用或用户授权中补齐所需权限：{combined}"
        elif (error_type, error_subtype) == ("permission", "forbidden"):
            code = "permission_denied"
            combined = "已授权用户无权访问该飞书群。"
        elif code in {
            "unauthorized",
            "not_authenticated",
            "auth_required",
            "user_identity_missing",
        }:
            code = "user_auth_required"
            combined = "请先完成本机 lark-cli 用户授权。"
        elif code in {"forbidden", "permission_denied", "chat_not_member"}:
            code = "permission_denied"
            combined = "已授权用户无权访问该飞书群。"
        elif code == "missing_scope":
            scope_names = _scope_names(scopes)
            if scope_names:
                listed = ", ".join(scope_names)
                combined = (
                    "请在飞书应用或用户授权中补齐这些权限："
                    f"{listed}。"
                )
            else:
                combined = f"请在飞书应用或用户授权中补齐所需权限：{combined}"
        elif "user" in lowered and ("identity" in lowered or "authorize" in lowered):
            code = "user_auth_required"
            combined = "请先完成本机 lark-cli 用户授权。"
        elif (
            ("permission" in lowered and "denied" in lowered)
            or "not a member" in lowered
            or "not_member" in lowered
        ):
            code = "permission_denied"
            combined = "已授权用户无权访问该飞书群。"
        return LarkCLIError(code, combined[:2000])


__all__ = ["LarkCLIBackend", "LarkCLIError", "redact_diagnostic"]
