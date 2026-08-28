"""Platform-owned Feishu delivery adapter (Phase 1 C1).

Sends light status notifications through the official Feishu OpenAPI using
credentials injected exclusively from environment/settings. The payload never
contains model text, prompts, outputs, decision evidence or secrets — only a
generic status line plus an optional platform link.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import DeliveryTarget
from app.services.routing import ChannelDeliveryAdapter, DeliveryResult

_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
_SEND_PATH = "/open-apis/im/v1/messages"
_TOKEN_EXPIRY_MARGIN_SECONDS = 120

_EVENT_STATUS_TEXT = {
    "pipeline.decision.approved": "已批准",
    "pipeline.decision.rejected": "已拒绝",
    "pipeline.decision.changes_requested": "已要求修改并重新生成",
    "pipeline.decision.pending": "待审批",
    "pipeline.decision.reminder": "待审批提醒",
    "pipeline.decision.escalation": "审批升级提醒",
}


class FeishuDeliveryError(RuntimeError):
    """Sanitized delivery failure; never carries provider bodies or secrets."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _notification_text(event_type: str, payload: dict[str, Any], base_url: str | None) -> str:
    status_text = _EVENT_STATUS_TEXT.get(event_type, "有更新")
    lines = [f"智能决策通知：您有一条决策{status_text}。"]
    if base_url:
        lines.append(f"查看详情：{base_url.rstrip('/')}/pipeline")
    return "\n".join(lines)


class FeishuDeliveryAdapter(ChannelDeliveryAdapter):
    provider = "feishu"

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str | SecretStr,
        domain: str = "https://open.feishu.cn",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
        platform_base_url: str | None = None,
    ) -> None:
        secret = app_secret.get_secret_value() if isinstance(app_secret, SecretStr) else app_secret
        if not app_id or not secret:
            raise ValueError("Feishu delivery requires both app id and secret")
        self._app_id = app_id
        self._app_secret = secret
        self._base = domain.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport
        self._platform_base_url = platform_base_url
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base, timeout=self._timeout, transport=self._transport
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
            raise FeishuDeliveryError("feishu_network_error") from exc
        if response.status_code != 200:
            raise FeishuDeliveryError("feishu_auth_failed")
        body = response.json()
        if body.get("code") != 0 or not body.get("tenant_access_token"):
            raise FeishuDeliveryError("feishu_auth_failed")
        self._token = str(body["tenant_access_token"])
        try:
            ttl = float(body.get("expire") or 7200)
        except (TypeError, ValueError):
            ttl = 7200
        self._token_expires_at = now + timedelta(seconds=max(ttl - _TOKEN_EXPIRY_MARGIN_SECONDS, 60))
        return self._token

    async def send(
        self,
        target: DeliveryTarget,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> DeliveryResult:
        receive_id_type = "chat_id"
        details = getattr(target, "details", None) or {}
        if isinstance(details, dict) and isinstance(details.get("receive_id_type"), str):
            receive_id_type = details["receive_id_type"]
        receive_id = target.external_conversation_id
        text = _notification_text(event_type, payload, self._platform_base_url)
        async with self._client() as client:
            token = await self._tenant_access_token(client)
            try:
                response = await client.post(
                    f"{_SEND_PATH}?receive_id_type={quote(receive_id_type)}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "receive_id": receive_id,
                        "msg_type": "text",
                        "content": json.dumps({"text": text}, ensure_ascii=False),
                    },
                )
            except httpx.HTTPError as exc:
                raise FeishuDeliveryError("feishu_network_error") from exc
        if response.status_code == 429:
            raise FeishuDeliveryError("feishu_rate_limited")
        if response.status_code != 200:
            raise FeishuDeliveryError("feishu_send_failed")
        body = response.json()
        if body.get("code") != 0:
            raise FeishuDeliveryError("feishu_send_failed")
        data = body.get("data")
        message_id = data.get("message_id") if isinstance(data, dict) else None
        if not isinstance(message_id, str) or not message_id:
            raise FeishuDeliveryError("feishu_send_failed")
        return DeliveryResult(provider=self.provider, external_message_id=message_id)


def build_feishu_delivery_adapter(settings: Settings) -> FeishuDeliveryAdapter | None:
    """Returns None (feishu_not_configured) unless both credentials exist."""
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        return None
    return FeishuDeliveryAdapter(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        domain=settings.feishu_api_domain,
        platform_base_url=settings.platform_public_base_url,
    )


def feishu_configuration_status(settings: Settings | None = None) -> str:
    from app.config import get_settings

    resolved = settings or get_settings()
    if (
        resolved.feishu_delivery_configured
        or (resolved.feishu_app_id and resolved.feishu_app_secret)
    ):
        return "configured"
    return "feishu_not_configured"


def delivery_settings_snapshot(db: Session | None = None) -> dict[str, str]:  # pragma: no cover
    del db
    return {"feishu": feishu_configuration_status()}
