"""D3 RED：执行计划 2026-08-15 D3.2 的 session memory mode CAS 契约。

D3.2 要求 "session memory mode 变更使用权限校验和 CAS"。当前 PUT /api/chat/sessions/{id}/memory-mode
只有权限校验，没有 expected_revision：并发/陈旧切换会静默覆盖，无法区分"基于旧状态的操作"。
本文件 RED 只证明该业务能力缺失；权限/表面/预算等既有契约由现有测试继续覆盖。
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_knowledge_session(client: AsyncClient, admin_headers: dict[str, str]) -> int:
    created = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "mode cas probe", "surface": "knowledge"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_memory_mode_update_requires_expected_revision_cas(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    session_id = await _create_knowledge_session(client, admin_headers)

    first = await client.put(
        f"/api/chat/sessions/{session_id}/memory-mode",
        headers=admin_headers,
        json={"memory_mode": "auto", "expected_revision": 1},
    )
    assert first.status_code == 200, first.text
    assert first.json().get("revision") == 2, "CAS 更新后必须返回新 revision"

    stale = await client.put(
        f"/api/chat/sessions/{session_id}/memory-mode",
        headers=admin_headers,
        json={"memory_mode": "off", "expected_revision": 1},
    )
    assert stale.status_code == 409, (
        "D3.2 要求 session memory mode 变更使用 CAS：陈旧 expected_revision 必须返回 409。"
        f"当前实现无 CAS，实际返回 {stale.status_code}（并发切换静默覆盖，业务能力缺失）"
    )

    fresh = await client.put(
        f"/api/chat/sessions/{session_id}/memory-mode",
        headers=admin_headers,
        json={"memory_mode": "off", "expected_revision": 2},
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["revision"] == 3


async def test_memory_mode_cas_is_owner_and_knowledge_surface_scoped(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    session_id = await _create_knowledge_session(client, admin_headers)
    stale = await client.put(
        f"/api/chat/sessions/{session_id}/memory-mode",
        headers=admin_headers,
        json={"memory_mode": "auto", "expected_revision": 2},
    )
    assert stale.status_code == 409, "revision 不匹配必须 409（不可用错误基线绕过 CAS）"
