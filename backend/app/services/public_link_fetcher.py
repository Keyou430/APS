from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx


MAX_REDIRECTS = 5
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARACTERS = 120_000
RENDER_WAIT_MILLISECONDS = 12_000
COLLABORATION_HOST_SUFFIXES = (
    "feishu.cn",
    "larksuite.com",
    "dingtalk.com",
    "dingtalk.cn",
)
AUTHENTICATION_HOST_PREFIXES = ("accounts.", "login.", "passport.")
_browser_render_semaphore = asyncio.Semaphore(2)


class PublicLinkFetchError(RuntimeError):
    pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())


def is_collaboration_link(url: str) -> bool:
    host = (urlsplit(url).hostname or "").rstrip(".").casefold()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in COLLABORATION_HOST_SUFFIXES)


async def _resolve_addresses(host: str, port: int) -> list[str]:
    rows = await asyncio.to_thread(
        socket.getaddrinfo,
        host,
        port,
        socket.AF_UNSPEC,
        socket.SOCK_STREAM,
    )
    return list({row[4][0] for row in rows})


def _assert_public_address(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if not ip.is_global:
        raise PublicLinkFetchError("链接指向了不可访问的内部网络地址")


def _normalize_text(content_type: str, body: bytes) -> str:
    charset_match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    charset = charset_match.group(1).strip('"\'') if charset_match else "utf-8"
    try:
        decoded = body.decode(charset, errors="replace")
    except LookupError:
        decoded = body.decode("utf-8", errors="replace")
    if "html" not in content_type.casefold():
        return decoded.strip()[:MAX_TEXT_CHARACTERS]
    parser = _VisibleTextParser()
    parser.feed(decoded)
    return re.sub(r"\s+", " ", "\n".join(parser.parts)).strip()[:MAX_TEXT_CHARACTERS]


async def _render_public_collaboration_link(url: str) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:  # pragma: no cover - deployment dependency guard
        raise PublicLinkFetchError("公开页面需要浏览器渲染支持") from error

    resolved_hosts: set[tuple[str, int]] = set()

    async def validate_request(route: object) -> None:
        request_url = route.request.url  # type: ignore[attr-defined]
        parsed = urlsplit(request_url)
        if parsed.scheme in {"data", "blob", "about"}:
            await route.continue_()  # type: ignore[attr-defined]
            return
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            await route.abort()  # type: ignore[attr-defined]
            return
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host_key = (parsed.hostname.casefold(), port)
        try:
            if host_key not in resolved_hosts:
                for address in await _resolve_addresses(*host_key):
                    _assert_public_address(address)
                resolved_hosts.add(host_key)
        except (OSError, PublicLinkFetchError):
            await route.abort()  # type: ignore[attr-defined]
            return
        await route.continue_()  # type: ignore[attr-defined]

    async with _browser_render_semaphore:
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage", "--no-sandbox"],
                )
                try:
                    context = await browser.new_context(
                        locale="zh-CN",
                        service_workers="block",
                        viewport={"width": 1440, "height": 900},
                    )
                    page = await context.new_page()
                    await page.route("**/*", validate_request)
                    await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                    started_at = asyncio.get_running_loop().time()
                    deadline = started_at + RENDER_WAIT_MILLISECONDS / 1000
                    longest_text = ""
                    stable_polls = 0
                    while asyncio.get_running_loop().time() < deadline:
                        text = re.sub(r"\s+", " ", await page.locator("body").inner_text()).strip()
                        if len(text) > len(longest_text):
                            longest_text = text
                            stable_polls = 0
                        elif text == longest_text:
                            stable_polls += 1
                        elapsed = asyncio.get_running_loop().time() - started_at
                        if elapsed >= 4 and stable_polls >= 3 and len(longest_text) >= 80:
                            break
                        await page.wait_for_timeout(500)
                    if len(longest_text) >= 80 and not any(
                        marker in longest_text for marker in ("登录飞书", "登录钉钉", "扫码登录")
                    ):
                        return longest_text[:MAX_TEXT_CHARACTERS]
                finally:
                    await browser.close()
        except PublicLinkFetchError:
            raise
        except Exception as error:
            raise PublicLinkFetchError("公开页面浏览器渲染失败") from error

    raise PublicLinkFetchError("公开页面未提供可用于问答的正文")


async def fetch_public_collaboration_link(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Callable[[str, int], Awaitable[list[str]]] = _resolve_addresses,
    renderer: Callable[[str], Awaitable[str]] = _render_public_collaboration_link,
) -> str:
    if not is_collaboration_link(url):
        raise PublicLinkFetchError("仅支持公开的飞书、Lark 或钉钉链接")

    current_url = url
    async with httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(20.0, connect=5.0),
        follow_redirects=False,
        headers={"User-Agent": "YunshuKnowledgeFetcher/1.0"},
    ) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            parsed = urlsplit(current_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise PublicLinkFetchError("链接地址无效")
            host = parsed.hostname.rstrip(".").casefold()
            if not is_collaboration_link(current_url):
                raise PublicLinkFetchError("链接重定向到了不受支持的站点")
            for address in await resolver(host, parsed.port or (443 if parsed.scheme == "https" else 80)):
                _assert_public_address(address)

            async with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or redirect_count >= MAX_REDIRECTS:
                        raise PublicLinkFetchError("链接重定向次数过多")
                    next_url = urljoin(current_url, location)
                    next_host = (urlsplit(next_url).hostname or "").casefold()
                    if next_host.startswith(AUTHENTICATION_HOST_PREFIXES):
                        return await renderer(url)
                    current_url = next_url
                    continue
                if response.status_code in {401, 403}:
                    return await renderer(url)
                if response.status_code >= 400:
                    raise PublicLinkFetchError(f"链接读取失败（{response.status_code}）")

                content_type = response.headers.get("content-type", "").casefold()
                if not any(kind in content_type for kind in ("text/", "json", "html", "xml")):
                    raise PublicLinkFetchError("链接内容不是可读取的文本页面")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise PublicLinkFetchError("链接内容超过 2 MB 限制")
                    chunks.append(chunk)
                text = _normalize_text(content_type, b"".join(chunks))
                if len(text) < 40:
                    raise PublicLinkFetchError("公开页面未提供可用于问答的正文")
                return text

    raise PublicLinkFetchError("链接读取失败")
