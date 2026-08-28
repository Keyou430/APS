from __future__ import annotations

import pytest

from hermes_mcp.industry_news import (
    CURATED_AI_FEEDS,
    IndustryNewsBackend,
    create_industry_news_server,
)


def rss_item(*, title: str, link: str, published: str, description: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>{title}</title><link>{link}</link><pubDate>{published}</pubDate>
<description><![CDATA[{description}]]></description>
</item></channel></rss>"""


def test_curated_venturebeat_feed_uses_its_non_redirecting_canonical_url() -> None:
    assert (
        dict(CURATED_AI_FEEDS)["VentureBeat AI"]
        == "https://venturebeat.com/category/ai/feed"
    )


@pytest.mark.asyncio
async def test_latest_returns_one_normalized_item_per_curated_feed() -> None:
    feeds = (
        ("Source A", "https://a.example/feed"),
        ("Source B", "https://b.example/feed"),
        ("Source C", "https://c.example/feed"),
    )
    payloads = {
        url: rss_item(
            title=f"{source} headline",
            link=f"https://news.example/{source[-1].lower()}",
            published="Fri, 28 Aug 2026 08:00:00 GMT",
            description=f"<p>{source} <b>summary</b></p>",
        )
        for source, url in feeds
    }

    async def fetch(url: str) -> str:
        return payloads[url]

    backend = IndustryNewsBackend(feeds=feeds, fetcher=fetch)

    result = await backend.latest()

    assert result == {
        "ok": True,
        "data": {
            "items": [
                {
                    "source": "Source A",
                    "title": "Source A headline",
                    "url": "https://news.example/a",
                    "published_at": "Fri, 28 Aug 2026 08:00:00 GMT",
                    "summary": "Source A summary",
                },
                {
                    "source": "Source B",
                    "title": "Source B headline",
                    "url": "https://news.example/b",
                    "published_at": "Fri, 28 Aug 2026 08:00:00 GMT",
                    "summary": "Source B summary",
                },
                {
                    "source": "Source C",
                    "title": "Source C headline",
                    "url": "https://news.example/c",
                    "published_at": "Fri, 28 Aug 2026 08:00:00 GMT",
                    "summary": "Source C summary",
                },
            ],
            "failed_sources": [],
        },
    }


@pytest.mark.asyncio
async def test_server_exposes_one_parameterless_read_only_tool() -> None:
    async def fetch(_: str) -> str:
        return rss_item(
            title="Headline",
            link="https://news.example/item",
            published="Fri, 28 Aug 2026 08:00:00 GMT",
            description="Summary",
        )

    server = create_industry_news_server(
        backend=IndustryNewsBackend(
            feeds=(("Source", "https://source.example/feed"),), fetcher=fetch
        )
    )

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == ["industry_news_latest"]
    assert tools[0].parameters["properties"] == {}
