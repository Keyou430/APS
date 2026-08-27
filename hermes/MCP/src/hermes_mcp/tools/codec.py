"""Codec tools — base64, hex encoding/decoding, JWT decode."""

from __future__ import annotations

import base64
import json
import logging

from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_codec_tools(mcp: FastMCP) -> None:
    """Register encoding/decoding tools."""

    @mcp.tool(
        name="base64",
        description="""Encode text to Base64 or decode Base64 to text.

Action can be 'encode' or 'decode'. For decoding, the output is UTF-8 text.
For binary data that can't be decoded as text, use 'decode' and check the result.""",
    )
    async def base64_codec(text: str, action: str = "encode") -> str:
        """Encode or decode Base64.

        Args:
            text: Text to encode, or Base64 string to decode
            action: 'encode' or 'decode'
        """
        try:
            if action == "encode":
                encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
                return encoded
            elif action == "decode":
                try:
                    decoded = base64.b64decode(text).decode("utf-8")
                    return decoded
                except UnicodeDecodeError:
                    # Return raw bytes as hex if not valid UTF-8
                    raw = base64.b64decode(text)
                    return f"[Binary data — {len(raw)} bytes]\n{raw.hex()}"
            else:
                return f"❌ Unknown action: '{action}'. Use 'encode' or 'decode'."
        except Exception as exc:
            return f"❌ Base64 {action} error: {exc}"

    @mcp.tool(
        name="hex_codec",
        description="""Encode text to hexadecimal or decode hex to text.""",
    )
    async def hex_codec(text: str, action: str = "encode") -> str:
        """Encode or decode hex.

        Args:
            text: Text to encode, or hex string to decode
            action: 'encode' or 'decode'
        """
        try:
            if action == "encode":
                encoded = text.encode("utf-8").hex()
                return encoded
            elif action == "decode":
                # Remove spaces, newlines, 0x prefixes
                cleaned = text.replace(" ", "").replace("\n", "").replace("0x", "")
                try:
                    decoded = bytes.fromhex(cleaned).decode("utf-8")
                    return decoded
                except UnicodeDecodeError:
                    raw = bytes.fromhex(cleaned)
                    return f"[Binary data — {len(raw)} bytes]\n{raw.hex()}"
            else:
                return f"❌ Unknown action: '{action}'. Use 'encode' or 'decode'."
        except ValueError as exc:
            return f"❌ Invalid hex string: {exc}"
        except Exception as exc:
            return f"❌ Hex {action} error: {exc}"

    @mcp.tool(
        name="jwt_decode",
        description="""Decode a JWT (JSON Web Token) without verification.

Returns the header and payload as formatted JSON. The signature section is
preserved but NOT verified — this tool is for inspection only, not validation.

Use this to inspect token claims, expiration, issuer, etc.""",
    )
    async def jwt_decode(token: str) -> str:
        """Decode a JWT token (without verification).

        Args:
            token: JWT token string (header.payload.signature)
        """
        try:
            parts = token.strip().split(".")
            if len(parts) != 3:
                return (
                    "❌ Not a valid JWT format. Expected header.payload.signature "
                    f"but got {len(parts)} parts."
                )

            # Decode header
            header_raw = parts[0]
            # Add padding if needed: (4 - len % 4) % 4 ensures 0 when already aligned
            header_raw += "=" * ((4 - len(header_raw) % 4) % 4)
            try:
                header = json.loads(base64.urlsafe_b64decode(header_raw).decode("utf-8"))
            except Exception:
                header = {"error": "Could not decode header"}

            # Decode payload
            payload_raw = parts[1]
            payload_raw += "=" * ((4 - len(payload_raw) % 4) % 4)
            try:
                payload = json.loads(base64.urlsafe_b64decode(payload_raw).decode("utf-8"))
            except Exception:
                payload = {"error": "Could not decode payload"}

            import time
            result = {
                "header": header,
                "payload": payload,
                "signature_present": bool(parts[2]),
                "_note": "⚠️ Signature NOT verified — for inspection only",
            }

            # Add human-readable timestamps
            if "iat" in payload:
                result["_issued_at"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S UTC", time.gmtime(payload["iat"])
                )
            if "exp" in payload:
                result["_expires_at"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S UTC", time.gmtime(payload["exp"])
                )
                if payload["exp"] < time.time():
                    result["_expired"] = True

            return json.dumps(result, indent=2, ensure_ascii=False)

        except Exception as exc:
            return f"❌ JWT decode error: {exc}"
