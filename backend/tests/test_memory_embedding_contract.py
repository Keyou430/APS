"""D1 RED：2026-08-15 复审后计划冻结的 Memory embedding 与事务回滚契约。

权威依据（master 2026-08-15）：
- §7.2：0013 为 Memory 增加 nullable embedding、embedding_state=not_configured|pending|ready|failed、
  model/version，以及可被 worker claim 的 embedding job；手工创建、candidate confirm 和 Decision
  approve 的业务事务只写 Memory 行与 embedding job；pending/failed/not_configured 只从 vector 分支
  排除，不从 owner-scoped FTS 分支排除；业务事务回滚必须同时消除 Memory、embedding job、audit 和
  outbox，不得留下孤儿向量或孤儿 job。
- §7.2（R5 已冻结）：Memory 内容经 CAS update 变更时，embedding_state 必须重置为 pending 并重新
  enqueue embedding job。
- 执行计划 D1.1：create/confirm 写入 embedding_state=pending|not_configured 和 embedding job；
  delete 204 且正文、version、source link、embedding 物理清除；业务事务回滚后不存在 Memory、
  embedding job、audit 或孤儿向量。

本文件只证明业务能力缺失：除一处记录现有 rollback 纪律的文档性测试外，所有断言都因
embedding_state 列 / embedding job 表缺失而失败，不使用 import、fixture、拼写或环境错误制造红灯。
"""

from __future__ import annotations

from sqlalchemy import select, text

import pytest
from httpx import AsyncClient

from app.database import Base, SessionLocal
from app.models import MemoryRecord, OrganizationMembership
from app.services import memory_repository
from app.services.audit import record_audit
from app.services.memory_retrieval import (
    MemoryEmbeddingProvider,
    MemoryRetrievalScope,
    _bounded_exact_vector_candidates,
    retrieve_authorized_memories,
)

pytestmark = pytest.mark.asyncio

EMBEDDING_STATES = {"not_configured", "pending", "ready", "failed"}
EMBEDDING_JOB_TABLE = "memory_embedding_jobs"


async def create_memory(
    client: AsyncClient,
    headers: dict[str, str],
    content: str,
) -> dict:
    response = await client.post(
        "/api/memory",
        headers=headers,
        json={"content": content, "type": "fact", "metadata": {"source": "manual"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


class _FakeEmbedding(MemoryEmbeddingProvider):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]


# --- embedding 状态与 job schema（master §7.2 / 执行 D1.1） ---


async def test_memory_record_declares_embedding_state_column() -> None:
    columns = set(MemoryRecord.__table__.columns.keys())
    assert "embedding_state" in columns, (
        "master §7.2 要求 0013 为 Memory 增加 embedding_state="
        "not_configured|pending|ready|failed；当前 memory_records 无该列，"
        "无法表达 vector 分支排除与 R5 重置语义"
    )


async def test_embedding_job_table_is_declared_and_claimable() -> None:
    table = Base.metadata.tables.get(EMBEDDING_JOB_TABLE)
    assert table is not None, (
        "master §7.2 要求 0013 提供可被 worker claim 的 embedding job；"
        f"当前 metadata 无 {EMBEDDING_JOB_TABLE} 表"
    )
    columns = {column.name for column in table.columns}
    assert "status" in columns, "embedding job 表必须含 status 列"
    assert "claimed_by" in columns, "embedding job 表必须含 claim 字段（可被 worker 领取）"


async def test_create_writes_embedding_state_without_provider(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await create_memory(client, admin_headers, "embedding state probe")
    async with SessionLocal() as db:
        row = await db.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_id == created["memory_id"])
        )
        state = getattr(row, "embedding_state", None)
    assert state in EMBEDDING_STATES, (
        "执行 D1.1 要求 create 写入 embedding_state=pending|not_configured；"
        f"实际 {state!r}（embedding_state 列缺失）"
    )
    assert state == "not_configured", (
        "无 embedding provider 时状态必须为 not_configured，且 Memory 立即进入 FTS 检索"
    )


async def test_content_update_resets_embedding_state_and_reenqueues_job(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """R5 冻结：内容 CAS update 后 embedding_state 重置 pending 并重新 enqueue。"""
    created = await create_memory(client, admin_headers, "initial content")
    memory_id = created["memory_id"]
    async with SessionLocal() as db:
        row = await db.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_id == memory_id)
        )
        assert getattr(row, "embedding_state", None) is not None, (
            "R5 冻结契约要求 0013 提供 embedding_state；当前列缺失，"
            "内容变更后无法表达 ready -> pending 重置"
        )
        # 模拟 embedding worker 已写回向量的 ready 状态（GREEN 前置）
        row.embedding = [0.0] * 1024
        row.embedding_state = "ready"
        row.embedding_model = "text-embedding-v4"
        await db.commit()

    updated = await client.put(
        f"/api/memory/{memory_id}",
        headers=admin_headers,
        json={"content": "changed content", "expected_revision": 1},
    )
    assert updated.status_code == 200, updated.text

    async with SessionLocal() as db:
        row = await db.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_id == memory_id)
        )
        assert row.embedding_state == "pending", "内容变更后 embedding_state 必须重置为 pending"
        job_count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM memory_embedding_jobs "
                    "WHERE memory_id = :memory_id AND status IN ('queued', 'processing')"
                ),
                {"memory_id": memory_id},
            )
        ).scalar_one()
        assert job_count >= 1, "内容变更后必须重新 enqueue embedding job"


async def test_delete_physically_clears_embedding_and_job_rows(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await create_memory(client, admin_headers, "delete probe")
    memory_id = created["memory_id"]
    async with SessionLocal() as db:
        row = await db.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_id == memory_id)
        )
        row.embedding = [0.0] * 1024
        await db.commit()

    assert Base.metadata.tables.get(EMBEDDING_JOB_TABLE) is not None, (
        "执行 D1.1 要求 delete 物理清除 embedding 与 embedding job；"
        "当前 embedding job 表缺失，删除契约无法成立"
    )

    deleted = await client.delete(
        f"/api/memory/{memory_id}?expected_revision=1",
        headers=admin_headers,
    )
    assert deleted.status_code == 204, deleted.text

    async with SessionLocal() as db:
        remaining = await db.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_id == memory_id)
        )
        assert remaining is None, "删除后 memory_records 不得残留正文行"
        version_count = (
            await db.execute(
                text("SELECT COUNT(*) FROM memory_versions WHERE memory_id = :memory_id"),
                {"memory_id": memory_id},
            )
        ).scalar_one()
        assert version_count == 0, "删除后不得残留 memory_versions 行"
        link_count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM memory_source_links WHERE memory_id = :memory_id"
                ),
                {"memory_id": memory_id},
            )
        ).scalar_one()
        assert link_count == 0, "删除后不得残留 memory_source_links 行"
        job_count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM memory_embedding_jobs WHERE memory_id = :memory_id"
                ),
                {"memory_id": memory_id},
            )
        ).scalar_one()
        assert job_count == 0, "删除后不得残留 embedding job 行"


async def test_non_ready_embeddings_are_excluded_from_vector_ranking() -> None:
    assert "embedding_state" in set(MemoryRecord.__table__.columns.keys()), (
        "master §7.2：pending/failed/not_configured 必须从 vector 分支排除且保留在 FTS 分支；"
        "当前无 embedding_state 列，vector 分支只能按 embedding IS NOT NULL 过滤，"
        "pending 状态的陈旧向量会被错误纳入 vector ranking"
    )
    # GREEN 契约（列存在后可达）：pending/failed/not_configured 只从 vector 分支排除，
    # 仍可从 owner-scoped FTS 分支检索到。
    async with SessionLocal() as db:
        membership = await db.scalar(select(OrganizationMembership).limit(1))
        assert membership is not None
        scope = MemoryRetrievalScope(
            organization_id=membership.organization_id,
            user_id=membership.user_id,
        )
        for memory_id, content, state in (
            ("pending" + "a" * 29, "pending vector needle", "pending"),
            ("ready" + "b" * 27, "ready vector needle", "ready"),
        ):
            db.add(
                MemoryRecord(
                    memory_id=memory_id,
                    organization_id=scope.organization_id,
                    user_id=scope.user_id,
                    content=content,
                    type="fact",
                    layer="L1",
                    status="active",
                    origin="manual",
                    revision=1,
                    embedding=[0.5] * 1024,
                    embedding_state=state,
                )
            )
        await db.commit()

        vector_records = await _bounded_exact_vector_candidates(
            db,
            scope=scope,
            vector=[0.5] * 1024,
            limit=10,
            memory_types=None,
            layers=None,
        )
        vector_ids = {record.memory_id for record in vector_records}
        assert "ready" + "b" * 27 in vector_ids, "ready 向量应进入 vector 分支"
        assert "pending" + "a" * 29 not in vector_ids, (
            "pending 状态的陈旧向量不得进入 vector 分支"
        )

        fts_items = await retrieve_authorized_memories(
            db,
            scope=scope,
            query="needle",
            embedding_provider=None,
        )
        fts_ids = {record.memory_id for record in fts_items}
        assert "pending" + "a" * 29 in fts_ids, "pending 记录必须仍可被 owner-scoped FTS 检索"


# --- 事务回滚契约（master §7.2 / 执行 D1.1） ---


async def test_rollback_contract_includes_embedding_job_table() -> None:
    assert Base.metadata.tables.get(EMBEDDING_JOB_TABLE) is not None, (
        "master §7.2：业务事务回滚必须同时消除 Memory、embedding job、audit；"
        "当前 embedding job 表缺失，回滚契约无法覆盖 job 行"
    )


async def test_rollback_of_existing_writes_leaves_no_memory_version_or_audit_rows() -> None:
    """文档性测试：现有写路径（Memory + version + audit）共享同一 unit of work。"""
    memory_id: str | None = None
    async with SessionLocal() as db:
        membership = await db.scalar(select(OrganizationMembership).limit(1))
        assert membership is not None
        record = await memory_repository.create_manual_memory(
            db,
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            content="rollback probe",
            memory_type="fact",
            metadata={},
        )
        memory_id = record.memory_id
        await record_audit(
            db,
            membership,
            action="memory.create",
            resource_type="memory",
            resource_id=memory_id,
            details={"status": record.status},
        )
        await db.flush()
        await db.rollback()

    assert memory_id is not None
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text("SELECT COUNT(*) FROM memory_records WHERE memory_id = :id"),
                {"id": memory_id},
            )
        ).scalar_one()
        versions = (
            await db.execute(
                text("SELECT COUNT(*) FROM memory_versions WHERE memory_id = :id"),
                {"id": memory_id},
            )
        ).scalar_one()
        audits = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM audit_events "
                    "WHERE resource_id = :id AND resource_type = 'memory'"
                ),
                {"id": memory_id},
            )
        ).scalar_one()
        assert rows == 0, "回滚后 memory_records 不得残留"
        assert versions == 0, "回滚后 memory_versions 不得残留"
        assert audits == 0, "回滚后 audit_events 不得残留"
