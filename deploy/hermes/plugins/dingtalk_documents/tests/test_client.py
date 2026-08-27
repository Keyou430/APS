from __future__ import annotations

import asyncio
import io
import zipfile

import httpx
import pytest

from dingtalk_documents.client import DingTalkApiError, DingTalkDocumentClient


def _client(handler, **kwargs) -> DingTalkDocumentClient:
    kwargs.setdefault("allowed_resource_hosts", ("download.example",))
    return DingTalkDocumentClient(
        client_id="client-id",
        client_secret="client-secret",
        operator_id="operator-id",
        transport=httpx.MockTransport(handler),
        poll_interval_seconds=0,
        **kwargs,
    )


def test_search_documents_returns_sanitized_results_and_reuses_token() -> None:
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/v1.0/oauth2/accessToken":
            token_calls += 1
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        assert request.url.params["operatorId"] == "operator-id"
        assert request.headers["x-acs-dingtalk-access-token"] == "token"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "dentryUuid": "doc-1",
                        "name": "人力资源周报",
                        "path": {"url": "https://alidocs.dingtalk.com/doc-1", "longPath": "/我的文件"},
                        "creator": {"name": "周敏", "userId": "must-not-leak"},
                        "modifier": {"name": "周敏", "userId": "must-not-leak"},
                        "lastModifyTime": 123,
                    }
                ]
            },
        )

    client = _client(handler)
    async def exercise():
        return await client.search_documents("周报"), await client.search_documents("培训")

    first, second = asyncio.run(exercise())

    assert token_calls == 1
    assert first["documents"] == [
        {
            "document_id": "doc-1",
            "title": "人力资源周报",
            "url": "https://alidocs.dingtalk.com/doc-1",
            "path": "/我的文件",
            "creator": "周敏",
            "modifier": "周敏",
            "last_modified": 123,
        }
    ]
    assert "must-not-leak" not in str(first)
    assert second["success"] is True


def test_permission_error_exposes_only_required_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        return httpx.Response(
            403,
            json={
                "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                "message": "contains implementation detail",
                "accessdenieddetail": {"requiredScopes": ["Storage.Dentry.Search"]},
            },
        )

    with pytest.raises(DingTalkApiError) as raised:
        asyncio.run(_client(handler).search_documents("周报"))

    assert raised.value.to_result()["required_scopes"] == ["Storage.Dentry.Search"]
    assert "client-secret" not in str(raised.value.to_result())


def test_search_resolves_staff_id_to_union_id_after_operator_error() -> None:
    calls: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        operator_id = request.url.params.get("operatorId")
        calls.append((request.url.path, operator_id))
        if request.url.host == "oapi.dingtalk.com" and request.url.path == "/gettoken":
            return httpx.Response(200, json={"access_token": "legacy-token", "errcode": 0})
        if request.url.host == "oapi.dingtalk.com" and request.url.path == "/topapi/v2/user/get":
            return httpx.Response(200, json={"errcode": 0, "result": {"unionid": "union-id"}})
        if operator_id == "operator-id":
            return httpx.Response(
                400,
                json={"code": "paramError", "message": "paramError-operatorId"},
            )
        return httpx.Response(200, json={"items": []})

    client = _client(handler)
    first, second = asyncio.run(
        _run_searches(client, "周报", "培训")
    )

    assert first["success"] is True
    assert second["success"] is True
    assert calls == [
        ("/v2.0/storage/dentries/search", "operator-id"),
        ("/gettoken", None),
        ("/topapi/v2/user/get", None),
        ("/v2.0/storage/dentries/search", "union-id"),
        ("/v2.0/storage/dentries/search", "union-id"),
    ]


async def _run_searches(
    client: DingTalkDocumentClient,
    first_query: str,
    second_query: str,
) -> tuple[dict, dict]:
    return (
        await client.search_documents(first_query),
        await client.search_documents(second_query),
    )


def test_permission_check_reports_contact_scope_when_union_id_resolution_is_denied() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        if request.url.path.startswith("/v2.0/"):
            return httpx.Response(
                400,
                json={"code": "paramError", "message": "paramError-operatorId"},
            )
        return httpx.Response(
            403,
            json={
                "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                "message": "contact denied",
                "accessdenieddetail": {"requiredScopes": ["Contact.User.Read"]},
            },
        )

    result = asyncio.run(_client(handler).check_permissions())

    assert result["confirmed_missing_scopes"] == ["Contact.User.Read"]
    assert result["checks"] == {
        "search": "permission_required",
        "read": "permission_required",
    }


def test_permission_check_treats_dummy_read_business_error_as_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        if request.url.host == "oapi.dingtalk.com" and request.url.path == "/gettoken":
            return httpx.Response(200, json={"access_token": "legacy-token", "errcode": 0})
        if request.url.host == "oapi.dingtalk.com" and request.url.path == "/topapi/v2/user/get":
            return httpx.Response(200, json={"errcode": 0, "result": {"unionid": "union-id"}})
        if request.url.path == "/v2.0/storage/dentries/search":
            if request.url.params.get("operatorId") == "operator-id":
                return httpx.Response(400, json={"code": "paramError", "message": "paramError-operatorId"})
            return httpx.Response(200, json={"items": []})
        return httpx.Response(500, json={"code": "unknownError", "message": "Unknown Error"})

    result = asyncio.run(_client(handler).check_permissions())

    assert result["confirmed_missing_scopes"] == []
    assert result["checks"] == {"search": "available", "read": "available"}


def test_legacy_user_lookup_reports_confirmed_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        if request.url.host == "oapi.dingtalk.com" and request.url.path == "/gettoken":
            return httpx.Response(200, json={"access_token": "legacy-token", "errcode": 0})
        if request.url.host == "api.dingtalk.com" and request.url.path.startswith("/v2.0/"):
            return httpx.Response(400, json={"code": "paramError", "message": "paramError-operatorId"})
        return httpx.Response(
            200,
            json={
                "errcode": 88,
                "errmsg": "ding talk error[subcode=60011,submsg=权限不足, {requiredScopes=[qyapi_get_member]}]",
            },
        )

    result = asyncio.run(_client(handler).check_permissions())

    assert result["confirmed_missing_scopes"] == ["qyapi_get_member"]


def test_permission_check_reports_only_scopes_confirmed_by_dingtalk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        if request.url.path == "/v2.0/storage/dentries/search":
            return httpx.Response(
                403,
                json={
                    "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                    "message": "search denied",
                    "accessdenieddetail": {"requiredScopes": ["Storage.Dentry.Search"]},
                },
            )
        return httpx.Response(
            403,
            json={
                "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                "message": "read denied",
                "accessdenieddetail": {"requiredScopes": ["Document.WorkspaceDocument.Read"]},
            },
        )

    result = asyncio.run(_client(handler).check_permissions())

    assert result["confirmed_missing_scopes"] == [
        "Storage.Dentry.Search",
        "Document.WorkspaceDocument.Read",
    ]
    assert result["checks"] == {
        "search": "permission_required",
        "read": "permission_required",
    }


def test_read_document_polls_and_downloads_signed_content_url() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        if request.url.path.endswith("/queryDentryId"):
            return httpx.Response(404, json={"code": "notFound", "message": "not found"})
        if request.method == "PUT":
            return httpx.Response(200, json={"taskId": 42})
        if request.url.host == "download.example":
            return httpx.Response(200, text="# 周报\n已完成招聘复盘。")
        return httpx.Response(200, json={"status": 2, "contentKey": "https://download.example/doc.md"})

    result = asyncio.run(_client(handler).read_document("doc-1"))

    assert result["content"].startswith("# 周报")
    assert result["truncated"] is False
    assert calls == [
        "/v1.0/oauth2/accessToken",
        "/v2.0/doc/dentries/doc-1/queryDentryId",
        "/v2.0/doc/contents/doc-1/jobs",
        "/v2.0/doc/contents/doc-1/jobStatuses",
        "/doc.md",
    ]


def test_read_document_downloads_and_extracts_docx() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>本周完成招聘复盘</w:t></w:r></w:p>
              <w:p><w:r><w:t>下周推进安全培训</w:t></w:r></w:p></w:body>
            </w:document>""",
        )
    docx_bytes = buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token", "expireIn": 7200})
        if request.url.host == "oapi.dingtalk.com" and request.url.path == "/gettoken":
            return httpx.Response(200, json={"access_token": "legacy-token", "errcode": 0})
        if request.url.host == "oapi.dingtalk.com" and request.url.path == "/topapi/v2/user/get":
            return httpx.Response(200, json={"errcode": 0, "result": {"unionid": "union-id"}})
        if request.url.path.endswith("/queryDentryId"):
            return httpx.Response(200, json={"spaceId": "space-1", "dentryId": "dentry-1"})
        if request.url.path.endswith("/downloadInfos/query"):
            return httpx.Response(
                200,
                json={
                    "headerSignatureInfo": {
                        "resourceUrls": ["https://download.example/report.docx"],
                        "headers": {"x-signed": "yes"},
                    }
                },
            )
        if request.url.host == "download.example":
            assert request.headers["x-signed"] == "yes"
            return httpx.Response(
                200,
                content=docx_bytes,
                headers={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    result = asyncio.run(_client(handler).read_document("doc-1"))

    assert result["content"] == "本周完成招聘复盘\n下周推进安全培训"
    assert result["format"] == "text"


def test_read_document_rejects_paths() -> None:
    client = _client(lambda _request: httpx.Response(500))
    with pytest.raises(ValueError, match="dentry UUID"):
        asyncio.run(client.read_document("../../etc/passwd"))
