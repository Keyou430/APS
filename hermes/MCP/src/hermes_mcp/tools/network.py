"""Network tools — HTTP requests, DNS lookups."""

from __future__ import annotations

import json
import logging
import socket

import httpx
from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_network_tools(mcp: FastMCP) -> None:
    """Register network utility tools."""

    @mcp.tool(
        name="http_request",
        description="""Make an HTTP request and return the response.

Supports GET, POST, PUT, DELETE, PATCH methods. Headers and body can be provided
as JSON strings. Response includes status code, headers, and body.""",
    )
    async def http_request(
        url: str,
        method: str = "GET",
        headers: str = "{}",
        body: str = "",
        timeout: float = 30.0,
    ) -> str:
        """Make an HTTP request.

        Args:
            url: Full URL to request
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            headers: JSON object of request headers
            body: Request body (JSON string for POST/PUT/PATCH)
            timeout: Request timeout in seconds
        """
        try:
            parsed_headers = json.loads(headers)
            if not isinstance(parsed_headers, dict):
                return "❌ headers must be a JSON object"
        except json.JSONDecodeError:
            return "❌ Invalid headers JSON"

        method = method.upper()
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            return f"❌ Unsupported HTTP method: {method}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                kwargs = {"headers": parsed_headers} if parsed_headers else {}
                if body and method in ("POST", "PUT", "PATCH"):
                    kwargs["content"] = body

                resp = await client.request(method, url, **kwargs)

                # Format response
                result_parts = [
                    f"HTTP {resp.status_code} {resp.reason_phrase}",
                    f"URL: {url}",
                    "",
                ]

                # Response headers
                result_parts.append("--- Response Headers ---")
                for key, value in resp.headers.items():
                    result_parts.append(f"  {key}: {value}")

                # Response body
                result_parts.append("")
                result_parts.append("--- Response Body ---")
                content_type = resp.headers.get("content-type", "")
                if "json" in content_type:
                    try:
                        formatted = json.dumps(resp.json(), indent=2, ensure_ascii=False)
                        result_parts.append(formatted)
                    except Exception:
                        result_parts.append(resp.text[:10_000])
                else:
                    result_parts.append(resp.text[:10_000])

                if len(resp.text) > 10_000:
                    result_parts.append(f"\n... [truncated — {len(resp.text):,} bytes total]")

                return "\n".join(result_parts)

        except httpx.ConnectError:
            return f"❌ Connection failed: Could not connect to {url}"
        except httpx.TimeoutException:
            return f"❌ Request timed out after {timeout}s"
        except Exception as exc:
            return f"❌ HTTP request error: {exc}"

    @mcp.tool(
        name="dns_lookup",
        description="""Resolve a hostname to IP addresses (A and AAAA records).

Returns both IPv4 and IPv6 addresses for the given hostname.""",
    )
    async def dns_lookup(hostname: str) -> str:
        """Perform DNS lookup for a hostname.

        Args:
            hostname: Hostname to resolve (e.g., 'github.com')
        """
        try:
            # Get all address info
            addrinfo = socket.getaddrinfo(hostname, None)

            ipv4 = []
            ipv6 = []
            seen = set()

            for family, _, _, _, sockaddr in addrinfo:
                ip = sockaddr[0]
                if ip in seen:
                    continue
                seen.add(ip)

                if family == socket.AF_INET:
                    ipv4.append(ip)
                elif family == socket.AF_INET6:
                    ipv6.append(ip)

            parts = [f"DNS lookup for: {hostname}", ""]
            if ipv4:
                parts.append(f"IPv4 addresses ({len(ipv4)}):")
                for ip in ipv4:
                    parts.append(f"  {ip}")
            if ipv6:
                parts.append(f"IPv6 addresses ({len(ipv6)}):")
                for ip in ipv6:
                    parts.append(f"  {ip}")
            if not ipv4 and not ipv6:
                parts.append("No addresses found.")

            return "\n".join(parts)

        except socket.gaierror as exc:
            return f"❌ DNS lookup failed: {exc}"
        except Exception as exc:
            return f"❌ Error: {exc}"
