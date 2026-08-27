from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.database import SessionLocal
from app.models import AuditEvent


pytestmark = pytest.mark.asyncio


async def test_audit_filters_cursor_and_redacts_sensitive_detail_keys(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    async with SessionLocal() as db:
        db.add_all(
            [
                AuditEvent(
                    organization_id=1,
                    actor_user_id=1,
                    action="knowledge.safe",
                    resource_type="knowledge_entry",
                    resource_id="501",
                    details={"count": 2, "query": "must not escape", "object_path": "/private"},
                ),
                AuditEvent(
                    organization_id=1,
                    actor_user_id=1,
                    action="knowledge.other",
                    resource_type="knowledge_entry",
                    resource_id="502",
                    details={"status": "ready"},
                ),
            ]
        )
        await db.commit()

    response = await client.get(
        "/api/audit-events",
        headers=admin_headers,
        params={"action": "knowledge.safe", "limit": 1},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["details"] == {"count": 2}
    assert "must not escape" not in response.text
    assert "/private" not in response.text
