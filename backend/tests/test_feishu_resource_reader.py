import httpx
import pytest

from app.config import Settings
from app.services import feishu_resource_reader as feishu_reader_module
from app.services.feishu_resource_reader import (
    FeishuResourceAccessPolicy,
    FeishuResourceReader,
    extract_feishu_chat_ids,
    extract_feishu_resource_links,
)


@pytest.mark.asyncio
async def test_reader_uses_tenant_credentials_for_private_docx_link() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            assert request.method == "POST"
            assert request.content == b'{"app_id":"cli_app","app_secret":"secret"}'
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tenant-token"})
        if request.url.path == "/open-apis/docx/v1/documents/doxcn123/raw_content":
            assert request.headers["authorization"] == "Bearer tenant-token"
            return httpx.Response(
                200,
                json={"code": 0, "data": {"content": "# 项目周报\n\n已完成飞书集成。"}},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    reader = FeishuResourceReader(
        app_id="cli_app",
        app_secret="secret",
        transport=httpx.MockTransport(handler),
    )

    content = await reader.read_link("https://example.feishu.cn/docx/doxcn123")

    assert "项目周报" in content
    assert "飞书集成" in content
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_reader_reads_group_messages_and_normalizes_text_bodies() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tenant-token"})
        if request.url.path == "/open-apis/im/v1/messages":
            assert request.url.params["container_id_type"] == "chat"
            assert request.url.params["container_id"] == "oc_group123"
            assert request.url.params["page_size"] == "50"
            assert request.headers["authorization"] == "Bearer tenant-token"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [
                            {
                                "msg_type": "text",
                                "sender": {"id": "ou_alice"},
                                "create_time": "1710000000000",
                                "body": {"content": '{"text":"请在周三前完成验收"}'},
                            }
                        ]
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    reader = FeishuResourceReader(
        app_id="cli_app",
        app_secret="secret",
        transport=httpx.MockTransport(handler),
    )

    content = await reader.read_chat_history("oc_group123")

    assert "ou_alice" in content
    assert "请在周三前完成验收" in content


def test_extract_feishu_chat_ids_accepts_shared_chat_urls_and_deduplicates() -> None:
    ids = extract_feishu_chat_ids(
        "请读取 oc_group123 的记录",
        [
            "https://applink.feishu.cn/client/chat?open_chat_id=oc_group456",
            "https://applink.feishu.cn/client/chat?chat_id=oc_group123",
        ],
    )

    assert ids == ["oc_group123", "oc_group456"]


def test_extract_feishu_resource_links_from_content_limits_to_feishu_and_lark_hosts() -> None:
    links = extract_feishu_resource_links(
        "请读取 https://docs.feishu.cn/docx/doxcn123，"
        "以及 https://acme.larksuite.com/wiki/wikiabc?from=share。"
        "不要读取 https://evilfeishu.cn/docx/doxcn456 或 https://example.com/docx/doxcn789。"
    )

    assert links == [
        "https://docs.feishu.cn/docx/doxcn123",
        "https://acme.larksuite.com/wiki/wikiabc?from=share",
    ]


def test_access_policy_requires_both_organization_and_explicit_resource_grant() -> None:
    policy = FeishuResourceAccessPolicy(
        allowed_organization_ids=frozenset({7}),
        allowed_document_tokens=frozenset({"doxcn123", "wikiabc"}),
        allowed_chat_ids=frozenset({"oc_group123"}),
    )

    assert policy.allows_document(7, "doxcn123") is True
    assert policy.allows_document(8, "doxcn123") is False
    assert policy.allows_document(7, "doxcn999") is False
    assert policy.allows_chat(7, "oc_group123") is True
    assert policy.allows_chat(8, "oc_group123") is False
    assert policy.allows_chat(7, "oc_group999") is False


def test_parse_feishu_base_link_preserves_table_and_view_ids() -> None:
    reference = feishu_reader_module.parse_feishu_resource_reference(
        "https://my.feishu.cn/base/FWVxbAjvia1LlzsBwxFcAEFrn8b"
        "?table=tblLQYPgSQV7SIEy&view=vewSZjyq3j"
    )

    assert reference is not None
    assert reference.kind == "base"
    assert reference.token == "FWVxbAjvia1LlzsBwxFcAEFrn8b"
    assert reference.table_id == "tblLQYPgSQV7SIEy"
    assert reference.view_id == "vewSZjyq3j"


@pytest.mark.parametrize(
    "url",
    [
        "http://my.feishu.cn/base/appExample?table=tblExample",
        "https://my.feishu.cn/x/base/appExample?table=tblExample",
        "https://my.feishu.cn/base/appExample/extra?table=tblExample",
        "https://my.feishu.cn//base/appExample?table=tblExample",
        "https://my.feishu.cn/base//appExample?table=tblExample",
        "https://my.feishu.cn/base/appExample?table=tblOne&table=tblTwo",
        "https://my.feishu.cn/base/appExample?table=&table=tblExample",
        "https://my.feishu.cn/base/appExample?table=tblExample&view=one&view=two",
        "https://my.feishu.cn/base/appExample?table=tblExample&view=&view=one",
    ],
)
def test_parse_feishu_base_link_rejects_noncanonical_urls(url: str) -> None:
    assert feishu_reader_module.parse_feishu_resource_reference(url) is None


def test_base_access_requires_organization_app_and_table_grant() -> None:
    settings = Settings(
        feishu_read_allowed_organization_ids="7,8",
        feishu_read_allowed_base_tables=(
            "7:FWVxbAjvia1LlzsBwxFcAEFrn8b:tblLQYPgSQV7SIEy,"
            "8:otherApp:tblOther"
        ),
    )
    policy = FeishuResourceAccessPolicy.from_settings(settings)
    allowed = feishu_reader_module.parse_feishu_resource_reference(
        "https://my.feishu.cn/base/FWVxbAjvia1LlzsBwxFcAEFrn8b"
        "?table=tblLQYPgSQV7SIEy"
    )
    other_table = feishu_reader_module.parse_feishu_resource_reference(
        "https://my.feishu.cn/base/FWVxbAjvia1LlzsBwxFcAEFrn8b"
        "?table=tblOther"
    )

    assert allowed is not None
    assert other_table is not None
    assert policy.allows_resource(7, allowed) is True
    assert policy.allows_resource(8, allowed) is False
    assert policy.allows_resource(7, other_table) is False


@pytest.mark.asyncio
async def test_reader_reads_base_records_with_view_and_pagination() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tenant-token"})
        assert request.url.path == (
            "/open-apis/bitable/v1/apps/FWVxbAjvia1LlzsBwxFcAEFrn8b/"
            "tables/tblLQYPgSQV7SIEy/records"
        )
        assert request.url.params["view_id"] == "vewSZjyq3j"
        assert request.url.params["page_size"] == "100"
        if "page_token" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "has_more": True,
                        "page_token": "page-2",
                        "items": [
                            {
                                "record_id": "rec1",
                                "fields": {
                                    "任务": "完成验收",
                                    "负责人": [{"name": "张三"}],
                                },
                            }
                        ],
                    },
                },
            )
        assert request.url.params["page_token"] == "page-2"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "has_more": False,
                    "items": [
                        {
                            "record_id": "rec2",
                            "fields": {"任务": "发布上线", "状态": "已完成"},
                        }
                    ],
                },
            },
        )

    reader = FeishuResourceReader(
        app_id="cli_app",
        app_secret="secret",
        transport=httpx.MockTransport(handler),
    )

    content = await reader.read_link(
        "https://my.feishu.cn/base/FWVxbAjvia1LlzsBwxFcAEFrn8b"
        "?table=tblLQYPgSQV7SIEy&view=vewSZjyq3j"
    )

    assert "飞书多维表格 tblLQYPgSQV7SIEy" in content
    assert "[rec1] 任务: 完成验收 | 负责人: [{\"name\": \"张三\"}]" in content
    assert "[rec2] 任务: 发布上线 | 状态: 已完成" in content
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_reader_truncates_oversized_first_base_record() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tenant-token"})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "has_more": False,
                    "items": [
                        {
                            "record_id": "rec-large",
                            "fields": {"正文": "A" * 60_000},
                        }
                    ],
                },
            },
        )

    reader = FeishuResourceReader(
        app_id="cli_app",
        app_secret="secret",
        transport=httpx.MockTransport(handler),
    )

    content = await reader.read_link(
        "https://my.feishu.cn/base/appExample?table=tblExample"
    )

    assert "[rec-large] 正文: AAAAA" in content
    assert content.endswith("（内容已截断）")
    assert len(content) <= 50_000
