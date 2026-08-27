from __future__ import annotations

import asyncio
import io
import re
import zipfile
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import httpx


API_BASE_URL = "https://api.dingtalk.com"
MAX_DOCUMENT_CONTENT_CHARS = 40_000
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
PERMISSION_PROBE_DOCUMENT_ID = "00000000-0000-0000-0000-000000000000"
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@dataclass
class DingTalkApiError(RuntimeError):
    status_code: int
    code: str
    message: str
    required_scopes: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.required_scopes:
            scopes = ", ".join(self.required_scopes)
            return f"DingTalk permission required: {scopes}"
        return self.message or self.code or f"DingTalk API returned HTTP {self.status_code}"

    def to_result(self) -> dict[str, Any]:
        return {
            "success": False,
            "error": "dingtalk_permission_required" if self.required_scopes else "dingtalk_api_error",
            "status_code": self.status_code,
            "code": self.code,
            "message": str(self),
            "required_scopes": list(self.required_scopes),
            "scope_rule": "Only required_scopes is confirmed; do not infer or add other scopes.",
        }


class DingTalkDocumentClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        operator_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 0.5,
        max_poll_attempts: int = 12,
        allowed_resource_hosts: tuple[str, ...] = (),
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.operator_id = operator_id.strip()
        if not self.client_id or not self.client_secret or not self.operator_id:
            raise ValueError(
                "DINGTALK_CLIENT_ID, DINGTALK_CLIENT_SECRET, and "
                "DINGTALK_DOC_OPERATOR_ID are required"
            )
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_attempts = max_poll_attempts
        self.allowed_resource_hosts = {
            host.strip().casefold().rstrip(".")
            for host in allowed_resource_hosts
            if host.strip()
        }
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._resolved_operator_id: str | None = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["x-acs-dingtalk-access-token"] = await self._access_token()
        async with httpx.AsyncClient(
            base_url=API_BASE_URL,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.request(
                method,
                path,
                params=params,
                json=json_body,
                headers=headers,
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code >= 400 or payload.get("code") or payload.get("errcode") not in (None, 0, "0"):
            required = self._required_scopes(payload)
            raise DingTalkApiError(
                status_code=response.status_code,
                code=str(payload.get("code") or payload.get("errcode") or "http_error"),
                message=str(payload.get("message") or payload.get("errmsg") or response.reason_phrase),
                required_scopes=required,
            )
        return payload

    @staticmethod
    def _required_scopes(payload: dict[str, Any]) -> tuple[str, ...]:
        detail = payload.get("accessdenieddetail")
        scopes: list[str] = []
        if isinstance(detail, dict):
            scopes.extend(str(scope) for scope in detail.get("requiredScopes") or [] if scope)
        scopes.extend(str(scope) for scope in payload.get("requiredScopes") or [] if scope)
        error_text = " ".join(
            str(payload.get(key) or "") for key in ("message", "errmsg")
        )
        match = re.search(r"requiredScopes\s*=\s*[\[{]([^}\]]+)[}\]]", error_text)
        if match:
            scopes.extend(part.strip(" '\"") for part in match.group(1).split(",") if part.strip())
        return tuple(dict.fromkeys(scopes))

    async def _access_token(self) -> str:
        if self._token and monotonic() < self._token_expires_at:
            return self._token
        async with self._token_lock:
            if self._token and monotonic() < self._token_expires_at:
                return self._token
            payload = await self._request(
                "POST",
                "/v1.0/oauth2/accessToken",
                authenticated=False,
                json_body={"appKey": self.client_id, "appSecret": self.client_secret},
            )
            token = payload.get("accessToken")
            if not isinstance(token, str) or not token:
                raise DingTalkApiError(502, "token_missing", "DingTalk token response was invalid")
            expires_in = payload.get("expireIn")
            try:
                lifetime = max(60, int(expires_in))
            except (TypeError, ValueError):
                lifetime = 7_200
            self._token = token
            self._token_expires_at = monotonic() + lifetime - 60
            return token

    async def _operator_union_id(self) -> str:
        if self._resolved_operator_id:
            return self._resolved_operator_id
        token_payload = await self._legacy_request(
            "GET",
            "/gettoken",
            params={"appkey": self.client_id, "appsecret": self.client_secret},
            authenticated=False,
        )
        token = token_payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise DingTalkApiError(502, "legacy_token_missing", "DingTalk legacy token response was invalid")
        payload = await self._legacy_request(
            "POST",
            "/topapi/v2/user/get",
            params={"access_token": token},
            json_body={"userid": self.operator_id, "language": "zh_CN"},
            authenticated=False,
        )
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        union_id = result.get("unionid") or result.get("unionId")
        if not isinstance(union_id, str) or not union_id.strip():
            raise DingTalkApiError(
                502,
                "union_id_missing",
                "DingTalk user response did not include unionId",
            )
        self._resolved_operator_id = union_id.strip()
        return self._resolved_operator_id

    async def _legacy_request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        async with httpx.AsyncClient(
            base_url="https://oapi.dingtalk.com",
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.request(
                method,
                path,
                params=params,
                json=json_body,
                headers=headers,
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code >= 400 or payload.get("errcode") not in (None, 0, "0"):
            raise DingTalkApiError(
                status_code=response.status_code,
                code=str(payload.get("code") or payload.get("errcode") or "http_error"),
                message=str(payload.get("message") or payload.get("errmsg") or response.reason_phrase),
                required_scopes=self._required_scopes(payload),
            )
        return payload

    @staticmethod
    def _is_operator_id_error(error: DingTalkApiError) -> bool:
        return error.status_code == 400 and "operatorId" in error.message

    async def _request_as_operator(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = {"operatorId": self._resolved_operator_id or self.operator_id}
        params.update(extra_params or {})
        try:
            return await self._request(method, path, params=params, json_body=json_body)
        except DingTalkApiError as error:
            if self._resolved_operator_id or not self._is_operator_id_error(error):
                raise
        params["operatorId"] = await self._operator_union_id()
        return await self._request(method, path, params=params, json_body=json_body)

    async def search_documents(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        normalized = query.strip()
        if not normalized:
            raise ValueError("query is required")
        bounded_limit = max(1, min(int(limit), 10))
        payload = await self._request_as_operator(
            "POST",
            "/v2.0/storage/dentries/search",
            json_body={"keyword": normalized, "option": {"maxResults": bounded_limit}},
        )
        items = []
        for raw in payload.get("items") or []:
            if not isinstance(raw, dict):
                continue
            path = raw.get("path") if isinstance(raw.get("path"), dict) else {}
            creator = raw.get("creator") if isinstance(raw.get("creator"), dict) else {}
            modifier = raw.get("modifier") if isinstance(raw.get("modifier"), dict) else {}
            items.append(
                {
                    "document_id": raw.get("dentryUuid"),
                    "title": raw.get("name"),
                    "url": path.get("url"),
                    "path": path.get("longPath") or path.get("path"),
                    "creator": creator.get("name"),
                    "modifier": modifier.get("name"),
                    "last_modified": raw.get("lastModifyTime"),
                }
            )
        return {
            "success": True,
            "query": normalized,
            "count": len(items),
            "documents": items,
            "next_token": payload.get("nextToken"),
        }

    async def check_permissions(self) -> dict[str, Any]:
        missing_scopes: list[str] = []
        checks: dict[str, str] = {}

        try:
            await self.search_documents("__xingjinian_permission_probe__", limit=1)
            checks["search"] = "available"
        except DingTalkApiError as error:
            if error.required_scopes:
                missing_scopes.extend(error.required_scopes)
                checks["search"] = "permission_required"
            else:
                raise

        try:
            await self._request_as_operator(
                "PUT",
                f"/v2.0/doc/contents/{PERMISSION_PROBE_DOCUMENT_ID}/jobs",
                extra_params={"targetFormat": "markdown"},
            )
            checks["read"] = "available"
        except DingTalkApiError as error:
            if error.required_scopes:
                missing_scopes.extend(error.required_scopes)
                checks["read"] = "permission_required"
            elif error.status_code in {400, 404, 500, 503}:
                checks["read"] = "available"
            else:
                raise

        confirmed = list(dict.fromkeys(missing_scopes))
        return {
            "success": True,
            "checks": checks,
            "confirmed_missing_scopes": confirmed,
            "message": (
                "当前已确认需要开通：" + "、".join(confirmed) + "。"
                if confirmed
                else "钉钉文档搜索与正文读取权限均已可用。"
            ),
            "scope_rule": "Only confirmed_missing_scopes is verified; do not add or infer other scopes.",
        }

    async def read_document(self, document_id: str) -> dict[str, Any]:
        normalized_id = self._normalize_document_id(document_id)
        try:
            content = await self._download_file_content(normalized_id)
            return {
                "success": True,
                "document_id": normalized_id,
                "format": "text",
                "content": content[:MAX_DOCUMENT_CONTENT_CHARS],
                "truncated": len(content) > MAX_DOCUMENT_CONTENT_CHARS,
            }
        except DingTalkApiError as error:
            if error.required_scopes or error.status_code not in {400, 404, 415, 422}:
                raise

        submitted = await self._request_as_operator(
            "PUT",
            f"/v2.0/doc/contents/{normalized_id}/jobs",
            extra_params={"targetFormat": "markdown"},
        )
        task_id = submitted.get("taskId")
        if task_id is None:
            raise DingTalkApiError(502, "task_missing", "DingTalk did not return a content task ID")

        for attempt in range(self.max_poll_attempts):
            result = await self._request_as_operator(
                "GET",
                f"/v2.0/doc/contents/{normalized_id}/jobStatuses",
                extra_params={"taskId": task_id},
            )
            content_key = result.get("contentKey")
            if isinstance(content_key, str) and content_key:
                content = await self._resolve_content_key(content_key)
                return {
                    "success": True,
                    "document_id": normalized_id,
                    "format": "markdown",
                    "content": content[:MAX_DOCUMENT_CONTENT_CHARS],
                    "truncated": len(content) > MAX_DOCUMENT_CONTENT_CHARS,
                }
            status = result.get("status")
            if status in {3, "3", "FAILED", "failed"}:
                raise DingTalkApiError(502, "content_job_failed", "DingTalk document export failed")
            if attempt + 1 < self.max_poll_attempts:
                await asyncio.sleep(self.poll_interval_seconds)
        raise DingTalkApiError(504, "content_job_timeout", "DingTalk document export timed out")

    async def _download_file_content(self, document_id: str) -> str:
        mapping = await self._request_as_operator(
            "GET",
            f"/v2.0/doc/dentries/{document_id}/queryDentryId",
        )
        operator_id = self._resolved_operator_id or self.operator_id
        space_id = mapping.get("spaceId")
        dentry_id = mapping.get("dentryId")
        if not isinstance(space_id, str) or not space_id or not isinstance(dentry_id, str) or not dentry_id:
            raise DingTalkApiError(422, "dentry_mapping_missing", "DingTalk did not return file location data")

        download_info = await self._request(
            "POST",
            (
                f"/v1.0/storage/spaces/{quote(space_id, safe='')}"
                f"/dentries/{quote(dentry_id, safe='')}/downloadInfos/query"
            ),
            params={"unionId": operator_id},
            json_body={},
        )
        signature = download_info.get("headerSignatureInfo")
        if not isinstance(signature, dict):
            raise DingTalkApiError(422, "download_info_missing", "DingTalk did not return download information")
        urls = signature.get("resourceUrls")
        url = urls[0] if isinstance(urls, list) and urls and isinstance(urls[0], str) else None
        if not url:
            raise DingTalkApiError(422, "download_url_missing", "DingTalk did not return a file download URL")
        self._validate_resource_url(url)
        signed_headers = signature.get("headers") if isinstance(signature.get("headers"), dict) else {}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
            response = await client.get(url, headers={str(key): str(value) for key, value in signed_headers.items()})
        if response.status_code >= 400:
            raise DingTalkApiError(response.status_code, "file_download_failed", "DingTalk file download failed")
        if len(response.content) > MAX_DOWNLOAD_BYTES:
            raise DingTalkApiError(413, "file_download_too_large", "DingTalk file download exceeded the 10 MB limit")
        return self._extract_document_text(response.content, response.headers.get("content-type", ""))

    def _validate_resource_url(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme != "https" or not host or host not in self.allowed_resource_hosts:
            raise DingTalkApiError(422, "download_host_not_allowed", "DingTalk returned an unapproved download host")

    @staticmethod
    def _extract_document_text(content: bytes, content_type: str) -> str:
        if zipfile.is_zipfile(io.BytesIO(content)):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                try:
                    document_xml = archive.read("word/document.xml")
                except KeyError as error:
                    raise DingTalkApiError(415, "unsupported_zip", "Downloaded file is not a DOCX document") from error
            root = ElementTree.fromstring(document_xml)
            paragraphs = []
            for paragraph in root.iter(f"{{{WORD_NAMESPACE}}}p"):
                text = "".join(node.text or "" for node in paragraph.iter(f"{{{WORD_NAMESPACE}}}t")).strip()
                if text:
                    paragraphs.append(text)
            extracted = "\n".join(paragraphs).strip()
            if extracted:
                return extracted
            raise DingTalkApiError(422, "empty_docx", "DingTalk DOCX contained no readable text")

        normalized_type = content_type.split(";", 1)[0].strip().lower()
        if normalized_type.startswith("text/") or normalized_type in {"application/json", "application/xml"}:
            return content.decode("utf-8", errors="replace").strip()
        raise DingTalkApiError(415, "unsupported_file_type", "Downloaded file type is not currently readable")

    async def _resolve_content_key(self, content_key: str) -> str:
        self._validate_resource_url(content_key)
        async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
            response = await client.get(content_key)
        if response.status_code >= 400:
            raise DingTalkApiError(
                response.status_code,
                "content_download_failed",
                "DingTalk document content could not be downloaded",
            )
        if len(response.content) > MAX_DOWNLOAD_BYTES:
            raise DingTalkApiError(413, "file_download_too_large", "DingTalk file download exceeded the 10 MB limit")
        return response.text

    @staticmethod
    def _normalize_document_id(value: str) -> str:
        normalized = value.strip()
        if not normalized or "/" in normalized or "\\" in normalized or len(normalized) > 160:
            raise ValueError("document_id must be a DingTalk dentry UUID returned by search")
        return normalized
