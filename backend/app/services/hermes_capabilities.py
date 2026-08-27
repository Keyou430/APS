from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

REQUIRED_FEATURES = (
    "responses_api",
    "run_submission",
    "run_events_sse",
    "run_stop",
    "run_approval_response",
    "session_resources",
)
REQUIRED_ENDPOINTS = (
    "responses",
    "runs",
    "run_events",
    "run_stop",
    "run_approval",
    "session_messages",
)


class HermesCapabilityError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        missing_features: tuple[str, ...] = (),
        missing_endpoints: tuple[str, ...] = (),
    ) -> None:
        self.missing_features = missing_features
        self.missing_endpoints = missing_endpoints
        super().__init__(message)


@dataclass(frozen=True)
class HermesCapabilityReport:
    health: dict[str, Any]
    detailed_health: dict[str, Any]
    capabilities: dict[str, Any]
    missing_features: tuple[str, ...] = ()
    missing_endpoints: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        return not self.missing_features and not self.missing_endpoints


class HermesCapabilityClient:
    """Fail-closed probe for the pinned Hermes API server contract."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Hermes API key is required for capability probing")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = httpx.Timeout(timeout_seconds)
        self.transport = transport

    async def probe(self) -> HermesCapabilityReport:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                health = await self._get_json(client, "/health")
                detailed_health = await self._get_json(
                    client,
                    "/health/detailed",
                    authenticated=True,
                )
                capabilities = await self._get_json(
                    client,
                    "/v1/capabilities",
                    authenticated=True,
                )
        except HermesCapabilityError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise HermesCapabilityError(
                f"Hermes capability probe failed: {type(exc).__name__}"
            ) from exc

        raw_features = capabilities.get("features")
        features = raw_features if isinstance(raw_features, dict) else {}
        missing_features = tuple(
            name
            for name in REQUIRED_FEATURES
            if features.get(name) is not True
        )

        raw_endpoints = capabilities.get("endpoints")
        endpoints = raw_endpoints if isinstance(raw_endpoints, dict) else {}
        missing_endpoints = tuple(name for name in REQUIRED_ENDPOINTS if name not in endpoints)

        if health.get("status") != "ok":
            missing_features = ("health", *missing_features)
        if detailed_health.get("status") != "ok":
            missing_features = ("health_detailed", *missing_features)

        report = HermesCapabilityReport(
            health=health,
            detailed_health=detailed_health,
            capabilities=capabilities,
            missing_features=missing_features,
            missing_endpoints=missing_endpoints,
        )
        if not report.healthy:
            raise HermesCapabilityError(
                "Hermes API server is missing required capabilities",
                missing_features=report.missing_features,
                missing_endpoints=report.missing_endpoints,
            )
        return report

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = await client.get(path, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise HermesCapabilityError(
                f"Hermes capability endpoint returned HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HermesCapabilityError(
                f"Hermes capability endpoint failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict):
            raise HermesCapabilityError("Hermes capability endpoint returned a non-object payload")
        return payload
