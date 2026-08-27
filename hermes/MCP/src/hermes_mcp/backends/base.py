"""Abstract base backend for Hermes operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class HermesBackend(ABC):
    """Unified backend interface for Hermes Agent operations.

    Backend resolution order:
    1. SDK mode — direct Python import of hermes_cli modules
    2. CLI mode — subprocess calls to hermes.exe
    """

    @abstractmethod
    async def send_message(
        self,
        platform: str,
        content: str,
        *,
        channel: str | None = None,
        subject: str | None = None,
        **kwargs: Any,
    ) -> dict:
        """Send a message to a configured platform."""
        ...

    @abstractmethod
    async def list_platforms(self) -> list[dict]:
        """List configured messaging platforms/channels."""
        ...

    @abstractmethod
    async def test_platform(self, platform: str) -> dict:
        """Test connectivity to a messaging platform."""
        ...

    @abstractmethod
    async def manage_webhook(
        self,
        action: str,
        *,
        webhook_id: str | None = None,
        config: dict | None = None,
    ) -> dict:
        """Manage webhook subscriptions (create/list/delete)."""
        ...

    @abstractmethod
    async def manage_cron(
        self,
        action: str,
        *,
        job_id: str | None = None,
        schedule: str | None = None,
        command: str | None = None,
    ) -> dict:
        """Manage cron jobs (create/list/delete)."""
        ...

    @abstractmethod
    async def proxy_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        body: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """Make an HTTP proxy request through Hermes gateway."""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend is operational."""
        ...

    @property
    @abstractmethod
    def mode(self) -> str:
        """Return the active backend mode (sdk/cli/unavailable)."""
        ...
