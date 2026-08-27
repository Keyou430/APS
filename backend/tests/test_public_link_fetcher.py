import httpx
import pytest

from app.services.public_link_fetcher import (
    PublicLinkFetchError,
    fetch_public_collaboration_link,
)


async def public_resolver(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.asyncio
async def test_fetch_public_collaboration_link_extracts_visible_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "docs.feishu.cn"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><body><h1>项目周报</h1><p>本周完成组织架构导入、知识问答附件支持和日历接口修复，下周继续完善固定流水线任务。</p><script>secret()</script></body></html>",
        )

    text = await fetch_public_collaboration_link(
        "https://docs.feishu.cn/public/page",
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
    )

    assert "项目周报" in text
    assert "secret" not in text


@pytest.mark.asyncio
async def test_fetch_public_collaboration_link_renders_public_login_redirect() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://accounts.feishu.cn/login"})

    rendered = "经营分析仪表盘 项目总金额 178,000 项目总成本 66,000 项目已付成本 21,000"

    async def renderer(url: str) -> str:
        assert url == "https://feishu.feishu.cn/app/public"
        return rendered

    text = await fetch_public_collaboration_link(
        "https://feishu.feishu.cn/app/public",
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
        renderer=renderer,
    )

    assert text == rendered


@pytest.mark.asyncio
async def test_fetch_public_collaboration_link_surfaces_renderer_failure() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    async def renderer(_url: str) -> str:
        raise PublicLinkFetchError("公开页面浏览器渲染失败")

    with pytest.raises(PublicLinkFetchError, match="浏览器渲染失败"):
        await fetch_public_collaboration_link(
            "https://feishu.feishu.cn/app/public",
            transport=httpx.MockTransport(handler),
            resolver=public_resolver,
            renderer=renderer,
        )
