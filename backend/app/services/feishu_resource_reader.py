"""Server-owned reader for authorized Feishu documents and group messages.

The chat provider receives only the resulting text. Tenant credentials remain
inside the platform API process and are never placed in chat instructions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import SecretStr

from app.config import Settings


_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
_DOCX_RAW_CONTENT_PATH = "/open-apis/docx/v1/documents/{token}/raw_content"
_WIKI_NODE_PATH = "/open-apis/wiki/v2/spaces/get_node"
_BASE_RECORDS_PATH = "/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
_MESSAGES_PATH = "/open-apis/im/v1/messages"
_TOKEN_EXPIRY_MARGIN_SECONDS = 120
_MAX_BASE_PAGES = 5
_MAX_BASE_RECORDS = 500
_MAX_BASE_CONTENT_CHARS = 50_000
_CHAT_ID_PATTERN = re.compile(r"\boc_[A-Za-z0-9_-]+\b")
_RESOURCE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_BASE_PATH_PATTERN = re.compile(r"^/base/(?P<token>[A-Za-z0-9_-]{1,255})$")
_URL_PATTERN = re.compile(
    r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", re.IGNORECASE
)
_FEISHU_HOST_SUFFIXES = ("feishu.cn", "larksuite.com")


class FeishuResourceReadError(RuntimeError):
    """Sanitized failure that is safe to put in transient chat context."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FeishuResourceReference:
    kind: Literal["docx", "wiki", "base"]
    token: str
    table_id: str | None = None
    view_id: str | None = None


@dataclass(frozen=True)
class FeishuResourceAccessPolicy:
    """Explicit tenant-resource grants required before using app credentials."""

    allowed_organization_ids: frozenset[int]
    allowed_document_tokens: frozenset[str]
    allowed_chat_ids: frozenset[str]
    allowed_base_tables: frozenset[tuple[int, str, str]] = frozenset()

    @classmethod
    def from_settings(cls, settings: Settings) -> "FeishuResourceAccessPolicy":
        return cls(
            allowed_organization_ids=_parse_organization_ids(
                settings.feishu_read_allowed_organization_ids
            ),
            allowed_document_tokens=_parse_resource_tokens(
                settings.feishu_read_allowed_document_tokens
            ),
            allowed_chat_ids=frozenset(
                token
                for token in _parse_resource_tokens(settings.feishu_read_allowed_chat_ids)
                if _CHAT_ID_PATTERN.fullmatch(token)
            ),
            allowed_base_tables=_parse_base_table_grants(
                settings.feishu_read_allowed_base_tables
            ),
        )

    def allows_document(self, organization_id: int, token: str) -> bool:
        return (
            organization_id in self.allowed_organization_ids
            and token in self.allowed_document_tokens
        )

    def allows_chat(self, organization_id: int, chat_id: str) -> bool:
        return (
            organization_id in self.allowed_organization_ids
            and chat_id in self.allowed_chat_ids
        )

    def allows_resource(
        self, organization_id: int, reference: FeishuResourceReference
    ) -> bool:
        if organization_id not in self.allowed_organization_ids:
            return False
        if reference.kind == "base":
            return (
                reference.table_id is not None
                and (organization_id, reference.token, reference.table_id)
                in self.allowed_base_tables
            )
        return reference.token in self.allowed_document_tokens


def _parse_organization_ids(value: str) -> frozenset[int]:
    allowed: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if item.isdecimal():
            organization_id = int(item)
            if organization_id > 0:
                allowed.add(organization_id)
    return frozenset(allowed)


def _parse_resource_tokens(value: str) -> frozenset[str]:
    return frozenset(
        item
        for raw_item in value.split(",")
        if (item := raw_item.strip()) and _RESOURCE_TOKEN_PATTERN.fullmatch(item)
    )


def _parse_base_table_grants(value: str) -> frozenset[tuple[int, str, str]]:
    grants: set[tuple[int, str, str]] = set()
    for raw_item in value.split(","):
        parts = raw_item.strip().split(":")
        if (
            len(parts) == 3
            and parts[0].isdecimal()
            and int(parts[0]) > 0
            and _RESOURCE_TOKEN_PATTERN.fullmatch(parts[1])
            and _RESOURCE_TOKEN_PATTERN.fullmatch(parts[2])
        ):
            grants.add((int(parts[0]), parts[1], parts[2]))
    return frozenset(grants)


def is_feishu_resource_link(url: str) -> bool:
    host = (urlsplit(url).hostname or "").rstrip(".").casefold()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _FEISHU_HOST_SUFFIXES)


def extract_feishu_resource_links(content: str) -> list[str]:
    """Return unique Feishu/Lark HTTP(S) URLs embedded in user message text."""
    candidates = (
        match.group(0).rstrip(".,;:!?，。；：！？）】》")
        for match in _URL_PATTERN.finditer(content)
    )
    return list(dict.fromkeys(url for url in candidates if is_feishu_resource_link(url)))


def parse_feishu_resource_reference(url: str) -> FeishuResourceReference | None:
    if not is_feishu_resource_link(url):
        return None
    parsed = urlsplit(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if "docx" in path_parts:
        index = path_parts.index("docx")
        if index + 1 < len(path_parts):
            token = path_parts[index + 1]
            if _RESOURCE_TOKEN_PATTERN.fullmatch(token):
                return FeishuResourceReference(kind="docx", token=token)
    if "wiki" in path_parts:
        query = parse_qs(parsed.query)
        token = next(
            (
                values[0]
                for key in ("node_token", "wiki_token", "token")
                if (values := query.get(key))
            ),
            path_parts[-1] if path_parts else "",
        )
        if _RESOURCE_TOKEN_PATTERN.fullmatch(token):
            return FeishuResourceReference(kind="wiki", token=token)
    if "base" in path_parts:
        base_path_match = _BASE_PATH_PATTERN.fullmatch(parsed.path)
        if parsed.scheme.casefold() != "https" or base_path_match is None:
            return None
        token = base_path_match.group("token")
        query = parse_qs(parsed.query, keep_blank_values=True)
        table_values = query.get("table", [])
        view_values = query.get("view", [])
        if len(table_values) != 1 or len(view_values) > 1:
            return None
        table_id = table_values[0]
        view_id = view_values[0] if view_values else None
        if not _RESOURCE_TOKEN_PATTERN.fullmatch(token):
            return None
        if table_id is not None and not _RESOURCE_TOKEN_PATTERN.fullmatch(table_id):
            return None
        if view_id is not None and not _RESOURCE_TOKEN_PATTERN.fullmatch(view_id):
            return None
        return FeishuResourceReference(
            kind="base",
            token=token,
            table_id=table_id,
            view_id=view_id,
        )
    return None


def extract_feishu_document_token(url: str) -> str | None:
    reference = parse_feishu_resource_reference(url)
    if reference is None or reference.kind == "base":
        return None
    return reference.token


def extract_feishu_chat_ids(content: str, links: list[str]) -> list[str]:
    """Extract explicit chat ids without treating arbitrary link text as an id."""
    candidates = list(_CHAT_ID_PATTERN.findall(content))
    for link in links:
        candidates.extend(_CHAT_ID_PATTERN.findall(link))
        query = parse_qs(urlsplit(link).query)
        for key in ("open_chat_id", "chat_id"):
            candidates.extend(value for value in query.get(key, []) if _CHAT_ID_PATTERN.fullmatch(value))
    return list(dict.fromkeys(candidates))


class FeishuResourceReader:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str | SecretStr,
        domain: str = "https://open.feishu.cn",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        secret = app_secret.get_secret_value() if isinstance(app_secret, SecretStr) else app_secret
        if not app_id or not secret:
            raise ValueError("Feishu resource reader requires both app id and secret")
        self._app_id = app_id
        self._app_secret = secret
        self._base = domain.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base,
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _tenant_access_token(self, client: httpx.AsyncClient) -> str:
        now = datetime.now(UTC)
        if self._token and self._token_expires_at and now < self._token_expires_at:
            return self._token
        try:
            response = await client.post(
                _TOKEN_PATH,
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
        except httpx.HTTPError as exc:
            raise FeishuResourceReadError("feishu_network_error") from exc
        if response.status_code != 200:
            raise FeishuResourceReadError("feishu_auth_failed")
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise FeishuResourceReadError("feishu_auth_failed") from exc
        token = body.get("tenant_access_token") if isinstance(body, dict) else None
        if not isinstance(body, dict) or body.get("code") != 0 or not isinstance(token, str) or not token:
            raise FeishuResourceReadError("feishu_auth_failed")
        try:
            ttl = float(body.get("expire") or 7200)
        except (TypeError, ValueError):
            ttl = 7200
        self._token = token
        self._token_expires_at = now + timedelta(
            seconds=max(ttl - _TOKEN_EXPIRY_MARGIN_SECONDS, 60)
        )
        return token

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        token = await self._tenant_access_token(client)
        try:
            response = await client.get(
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise FeishuResourceReadError("feishu_network_error") from exc
        if response.status_code == 403:
            raise FeishuResourceReadError("feishu_access_denied")
        if response.status_code == 404:
            raise FeishuResourceReadError("feishu_resource_not_found")
        if response.status_code != 200:
            raise FeishuResourceReadError("feishu_read_failed")
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise FeishuResourceReadError("feishu_read_failed") from exc
        if not isinstance(body, dict):
            raise FeishuResourceReadError("feishu_read_failed")
        if body.get("code") != 0:
            if body.get("code") in {91403, 1254302, 99991663, 99991661}:
                raise FeishuResourceReadError("feishu_access_denied")
            raise FeishuResourceReadError("feishu_read_failed")
        return body

    async def read_link(self, url: str) -> str:
        reference = parse_feishu_resource_reference(url)
        if reference is None:
            raise FeishuResourceReadError("unsupported_feishu_link")
        if reference.kind == "docx":
            return await self._read_docx(reference.token)
        if reference.kind == "wiki":
            return await self._read_wiki(reference.token)
        return await self._read_base(reference)

    async def _read_docx(self, token: str) -> str:
        if not _RESOURCE_TOKEN_PATTERN.fullmatch(token):
            raise FeishuResourceReadError("unsupported_feishu_link")
        async with self._client() as client:
            body = await self._get_json(client, _DOCX_RAW_CONTENT_PATH.format(token=token))
        data = body.get("data")
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise FeishuResourceReadError("feishu_empty_content")
        return content.strip()

    async def _read_wiki(self, token: str) -> str:
        async with self._client() as client:
            body = await self._get_json(client, _WIKI_NODE_PATH, params={"token": token})
        data = body.get("data")
        node = data.get("node") if isinstance(data, dict) else None
        if not isinstance(node, dict):
            raise FeishuResourceReadError("feishu_resource_not_found")
        if node.get("obj_type") != "docx" or not isinstance(node.get("obj_token"), str):
            raise FeishuResourceReadError("unsupported_feishu_link")
        return await self._read_docx(node["obj_token"])

    async def _read_base(self, reference: FeishuResourceReference) -> str:
        if reference.table_id is None:
            raise FeishuResourceReadError("unsupported_feishu_link")
        header = f"飞书多维表格 {reference.table_id}：\n"
        truncation_marker = "\n（内容已截断）"
        body_char_limit = (
            _MAX_BASE_CONTENT_CHARS - len(header) - len(truncation_marker)
        )
        lines: list[str] = []
        content_chars = 0
        record_count = 0
        page_token: str | None = None
        truncated = False
        async with self._client() as client:
            for page_index in range(_MAX_BASE_PAGES):
                params = {"page_size": "100"}
                if reference.view_id is not None:
                    params["view_id"] = reference.view_id
                if page_token is not None:
                    params["page_token"] = page_token
                body = await self._get_json(
                    client,
                    _BASE_RECORDS_PATH.format(
                        app_token=reference.token,
                        table_id=reference.table_id,
                    ),
                    params=params,
                )
                data = body.get("data")
                items = data.get("items") if isinstance(data, dict) else None
                if not isinstance(items, list):
                    raise FeishuResourceReadError("feishu_read_failed")
                for item in items:
                    line = _format_base_record(item) if isinstance(item, dict) else ""
                    if not line:
                        continue
                    separator_chars = 1 if lines else 0
                    remaining_chars = body_char_limit - content_chars - separator_chars
                    if record_count >= _MAX_BASE_RECORDS or remaining_chars <= 0:
                        truncated = True
                        break
                    if len(line) > remaining_chars:
                        lines.append(line[:remaining_chars])
                        content_chars += separator_chars + remaining_chars
                        record_count += 1
                        truncated = True
                        break
                    lines.append(line)
                    content_chars += separator_chars + len(line)
                    record_count += 1
                if truncated:
                    break
                has_more = isinstance(data, dict) and data.get("has_more") is True
                if not has_more:
                    break
                next_page_token = data.get("page_token") if isinstance(data, dict) else None
                if not isinstance(next_page_token, str) or not next_page_token:
                    raise FeishuResourceReadError("feishu_read_failed")
                if page_index + 1 >= _MAX_BASE_PAGES:
                    truncated = True
                    break
                page_token = next_page_token
        if not lines:
            raise FeishuResourceReadError("feishu_empty_content")
        result = header + "\n".join(lines)
        if truncated:
            result += truncation_marker
        return result

    async def read_chat_history(self, chat_id: str) -> str:
        if not _CHAT_ID_PATTERN.fullmatch(chat_id):
            raise FeishuResourceReadError("invalid_feishu_chat_id")
        async with self._client() as client:
            body = await self._get_json(
                client,
                _MESSAGES_PATH,
                params={
                    "container_id_type": "chat",
                    "container_id": chat_id,
                    "page_size": "50",
                },
            )
        data = body.get("data")
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise FeishuResourceReadError("feishu_read_failed")
        messages = [_format_message(item) for item in items if isinstance(item, dict)]
        readable = [message for message in messages if message]
        if not readable:
            raise FeishuResourceReadError("feishu_empty_content")
        return f"飞书群聊 {chat_id} 最近消息：\n" + "\n".join(readable)


def _format_message(item: dict[str, Any]) -> str:
    sender = item.get("sender")
    sender_id = sender.get("id") if isinstance(sender, dict) else None
    text = _message_text(item.get("body"))
    if not text:
        return ""
    create_time = _format_message_time(item.get("create_time"))
    author = sender_id if isinstance(sender_id, str) and sender_id else "unknown"
    prefix = f"[{create_time}] " if create_time else ""
    return f"{prefix}{author}: {text}"


def _format_base_record(item: dict[str, Any]) -> str:
    fields = item.get("fields")
    if not isinstance(fields, dict):
        return ""
    values = [
        f"{name}: {_format_base_cell(value)}"
        for name, value in fields.items()
        if isinstance(name, str)
    ]
    if not values:
        return ""
    record_id = item.get("record_id")
    prefix = f"[{record_id}] " if isinstance(record_id, str) and record_id else ""
    return prefix + " | ".join(values)


def _format_base_cell(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _format_message_time(value: object) -> str:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _message_text(body: object) -> str:
    content = body.get("content") if isinstance(body, dict) else None
    if not isinstance(content, str):
        return ""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content.strip()
    if isinstance(parsed, dict) and isinstance(parsed.get("text"), str):
        return parsed["text"].strip()
    parts: list[str] = []
    _collect_text(parsed, parts)
    return " ".join(part for part in parts if part).strip()


def _collect_text(value: object, parts: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"text", "content", "title"} and isinstance(nested, str):
                parts.append(nested)
            elif isinstance(nested, (dict, list)):
                _collect_text(nested, parts)
    elif isinstance(value, list):
        for nested in value:
            _collect_text(nested, parts)


def build_feishu_resource_reader(settings: Settings) -> FeishuResourceReader | None:
    """Opt in explicitly before API-side credentials can read user resources."""
    if not (
        settings.feishu_read_configured
        and settings.feishu_app_id
        and settings.feishu_app_secret
    ):
        return None
    return FeishuResourceReader(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        domain=settings.feishu_api_domain,
    )


__all__ = [
    "FeishuResourceReadError",
    "FeishuResourceAccessPolicy",
    "FeishuResourceReference",
    "FeishuResourceReader",
    "build_feishu_resource_reader",
    "extract_feishu_document_token",
    "extract_feishu_chat_ids",
    "extract_feishu_resource_links",
    "is_feishu_resource_link",
    "parse_feishu_resource_reference",
]
