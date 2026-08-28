"""Read-only curated industry news feeds for the primary Hermes agent."""

from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable, Sequence

import httpx
from fastmcp import FastMCP

FeedFetcher = Callable[[str], Awaitable[str]]

CURATED_AI_FEEDS: tuple[tuple[str, str], ...] = (
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed"),
    ("AI News", "https://www.artificialintelligence-news.com/feed/"),
)

_MAX_FEED_BYTES = 2_000_000
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _plain_text(value: str, *, limit: int = 1200) -> str:
    text = html.unescape(_TAG.sub(" ", value))
    return _WHITESPACE.sub(" ", text).strip()[:limit]


def _latest_item(source: str, payload: str) -> dict[str, str] | None:
    root = ET.fromstring(payload)
    item = root.find("./channel/item")
    if item is None:
        return None
    title = _plain_text(item.findtext("title") or "", limit=500)
    url = (item.findtext("link") or "").strip()
    published_at = _plain_text(item.findtext("pubDate") or "", limit=200)
    description = item.findtext("description") or ""
    summary = _plain_text(description)
    if not title or not url.startswith(("https://", "http://")):
        return None
    return {
        "source": source,
        "title": title,
        "url": url,
        "published_at": published_at,
        "summary": summary,
    }


class IndustryNewsBackend:
    """Fetch one latest item from each fixed, curated RSS source."""

    def __init__(
        self,
        *,
        feeds: Sequence[tuple[str, str]] = CURATED_AI_FEEDS,
        fetcher: FeedFetcher | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.feeds = tuple(feeds)
        self.timeout = timeout
        self.fetcher = fetcher or self._fetch

    async def _fetch(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            response = await client.get(
                url,
                headers={"Accept": "application/rss+xml, application/xml"},
            )
            response.raise_for_status()
            content = response.content
        if len(content) > _MAX_FEED_BYTES:
            raise ValueError("feed response exceeds size limit")
        return content.decode("utf-8", errors="replace")

    async def _read_one(
        self, source: str, url: str
    ) -> tuple[dict[str, str] | None, str | None]:
        try:
            item = _latest_item(source, await self.fetcher(url))
        except (ET.ParseError, httpx.HTTPError, OSError, UnicodeError, ValueError):
            return None, source
        return (item, None) if item is not None else (None, source)

    async def latest(self) -> dict[str, object]:
        results = await asyncio.gather(
            *(self._read_one(source, url) for source, url in self.feeds)
        )
        items = [item for item, _ in results if item is not None]
        failed_sources = [source for _, source in results if source is not None]
        return {
            "ok": True,
            "data": {"items": items, "failed_sources": failed_sources},
        }


def create_industry_news_server(
    *, backend: IndustryNewsBackend | None = None
) -> FastMCP:
    news = backend or IndustryNewsBackend()
    server = FastMCP(
        name="hermes-industry-news",
        instructions=(
            "只读获取三个固定公开 AI 行业 RSS 的最新条目。工具不接受 URL，"
            "不得用于任意网络访问。"
        ),
    )

    @server.tool(
        name="industry_news_latest",
        description=(
            "从 TechCrunch AI、VentureBeat AI 和 AI News 固定 RSS 各读取最新一条，"
            "返回真实标题、发布日期、原文链接和原始摘要。只读，无参数。"
        ),
    )
    async def industry_news_latest() -> dict[str, object]:
        return await news.latest()

    return server


def main() -> None:
    create_industry_news_server().run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = [
    "CURATED_AI_FEEDS",
    "IndustryNewsBackend",
    "create_industry_news_server",
    "main",
]
