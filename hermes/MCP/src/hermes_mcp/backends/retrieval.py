"""Three-source retrieval backend — calls the retrieval service on port 8001."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RetrievalBackend:
    """HTTP client for the three-source retrieval service (E/D/K knowledge bases)."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        timeout: float = 60.0,
        default_top_k: int = 3,
        similarity_threshold: float = 0.3,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_top_k = default_top_k
        self.similarity_threshold = similarity_threshold

    async def search(
        self,
        question: str,
        *,
        session_id: str = "",
        mode: str = "serial",
        experience_enabled: bool = True,
        database_enabled: bool = True,
        knowledge_enabled: bool = True,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """Call the /serial-retrieve endpoint.

        Returns normalized results with three sections:
        - experience: list of experience library matches
        - database: list of business database matches
        - knowledge: list of knowledge base chunks
        - meta: timing and error metadata
        """
        if top_k is None:
            top_k = self.default_top_k

        options = {
            "experience": {
                "enabled": experience_enabled,
                "top_k": top_k,
                "similarity_threshold": self.similarity_threshold,
            },
            "database": {
                "enabled": database_enabled,
                "top_k": top_k,
                "similarity_threshold": self.similarity_threshold,
            },
            "knowledge": {
                "enabled": knowledge_enabled,
                "top_k": top_k,
                "similarity_threshold": self.similarity_threshold,
            },
        }

        payload: dict[str, Any] = {
            "question": question,
            "session_id": session_id,
            "mode": mode,
            "options": options,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/serial-retrieve",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "success": True,
                    **data,
                }
        except httpx.ConnectError:
            logger.warning("Retrieval service unreachable at %s", self.base_url)
            return self._empty_result(f"Service unreachable at {self.base_url}")
        except httpx.TimeoutException:
            logger.warning("Retrieval service timeout at %s", self.base_url)
            return self._empty_result("Request timed out")
        except Exception as exc:
            logger.warning("Retrieval error: %s", exc)
            return self._empty_result(str(exc))

    async def health_check(self) -> dict[str, Any]:
        """Check if the retrieval service is responding."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/docs")
                return {
                    "available": resp.status_code == 200,
                    "base_url": self.base_url,
                    "status_code": resp.status_code,
                }
        except Exception as exc:
            return {
                "available": False,
                "base_url": self.base_url,
                "error": str(exc),
            }

    @staticmethod
    def _empty_result(error: str = "") -> dict[str, Any]:
        return {
            "success": False,
            "experience": {"is_empty": True, "results": []},
            "database": {"is_empty": True, "results": []},
            "knowledge": {"is_empty": True, "results": []},
            "meta": {"error": error},
        }
