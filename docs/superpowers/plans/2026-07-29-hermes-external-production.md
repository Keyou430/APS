# 云枢平台自有 RAG + pgvector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not stage, commit, push, open a PR, modify `main`/`test`, or perform database/schema changes without the separate confirmation gate in Task 4.

**Goal:** 在既有知识库资源和组织权限模型内，实现平台自有的文档解析、1024 维 pgvector 混合检索、授权引用和 Hermes 知识上下文，而不改变已确认前端设计。

**Architecture:** 原始文件进入私有 OSS，PostgreSQL 保存资源元数据、任务、版本化文本切片和向量；独立 Docling worker 领取 PostgreSQL 任务并调用百炼 `text-embedding-v4`。检索先按服务器派生的 organization/user/resource scope 过滤，再执行向量和全文召回、RRF 合并并将限量引用注入 Hermes。Hermes 和浏览器永不访问原始文件、对象存储凭据或未授权资料。

**Tech Stack:** FastAPI、SQLAlchemy async、Alembic、PostgreSQL 16、pgvector、PostgreSQL FTS、Docling worker、OSS 私有 bucket、阿里云百炼 OpenAI-compatible embedding API、pytest、Docker Compose。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `backend/app/models/entities.py` | 新增 ingestion job、chunk、retrieval event ORM 模型；保留 `KnowledgeEntry`。 |
| `backend/app/models/__init__.py` | 导出新增模型给 Alembic metadata。 |
| `backend/migrations/versions/20260729_0005_platform_rag.py` | 唯一的 RAG schema 迁移；只能在 Task 4 确认后创建和运行。 |
| `backend/app/schemas/knowledge.py` | 新增 ingestion/retrieve/citation 契约，保留旧响应类型和 `provider` 字段。 |
| `backend/app/services/object_storage.py` | 私有对象存储协议及本地测试替身；不向 API 返回 object key。 |
| `backend/app/services/document_parser.py` | Docling 格式白名单、结构文本提取和确定性切片。 |
| `backend/app/services/embedding_client.py` | 仅服务端的 `text-embedding-v4` 1024 维适配器和可替换测试 fake。 |
| `backend/app/services/knowledge_ingestion.py` | 入队、领取、重试、版本替换、删除清理。 |
| `backend/app/services/knowledge_retrieval.py` | 授权过滤、向量/全文候选、RRF、上下文预算和 citations。 |
| `backend/app/services/chat_context.py` | 将授权 citations 与不可覆盖 instructions 组装成 Hermes 输入。 |
| `backend/app/services/hermes_client.py` | 允许平台提供 `instructions`，并按服务端会话字段路由 agent/knowledge gateway；不改变现有 Hermes key/兼容接口。 |
| `backend/app/routers/knowledge.py` | 资源 CRUD 保持；追加 ingest/status/retrieve；旧 search 复用检索服务。 |
| `backend/app/routers/chat.py` | 在创建 Hermes run 前构建授权知识上下文；保留 SSE/stop/approval/delete。 |
| `backend/app/config.py` | RAG、OSS、embedding、worker 的非敏感配置名和安全默认值。 |
| `backend/app/workers/rag_ingestion.py` | 轮询 PostgreSQL 任务、有限并发、优雅停止的独立 worker 入口。 |
| `backend/tests/test_knowledge_ingestion.py` | 入队、版本、失败、删除和幂等性测试。 |
| `backend/tests/test_knowledge_retrieval.py` | 混合检索、RRF、预算、授权隔离和撤权测试。 |
| `backend/tests/test_chat_knowledge_context.py` | 证明 Hermes 仅收到授权片段和平台 instructions。 |
| `backend/tests/test_rag_migration.py` | PostgreSQL 专用扩展、索引和迁移/降级验证。 |
| `backend/tests/fixtures/rag/` | 不含客户资料的最小 PDF/DOCX/XLSX/Markdown 和标注查询集。 |
| `deploy/compose.yaml` | OSS/RDS 环境变量引用、worker 服务及健康/启动顺序。 |
| `deploy/compose.hermes.yaml` | 知识模式 Hermes policy/SOUL 只读挂载和 API 运行参数。 |
| `deploy/hermes/config.knowledge.yaml` | 固定 provider/model 且 `api_server` toolsets 为空的知识网关配置。 |
| `deploy/hermes/SOUL.md` | 云枢知识助理全局人格；不含业务凭据。 |
| `.sisyphus/drafts/cloud-cost-quotation-v2.md` | 改为 RDS 高可用规格与私有 OSS/worker 成本项，价格只以目标地域实时报价填写。 |

## Task 1: 冻结范围并建立 RAG 契约测试（已完成）

**Files:**
- Create: `backend/tests/test_knowledge_retrieval.py`
- Create: `backend/tests/test_chat_knowledge_context.py`
- Create: `backend/app/services/knowledge_retrieval.py`
- Create: `backend/app/services/chat_context.py`
- Modify: `backend/app/schemas/knowledge.py`
- Modify: `backend/tests/test_api.py`

- [x] **Step 1: 写入不会触碰数据库的失败契约测试**

覆盖以下固定断言：

```python
async def test_retrieve_rejects_foreign_source_before_embedding() -> None:
    result = await retriever.retrieve(
        scope=RetrievalScope(organization_id=1, user_id=10),
        query="年度制度",
        source_ids=[20],
    )
    assert result.citations == []
    assert candidates.calls == []

def test_chat_context_contains_only_authorized_citations() -> None:
    context = build_chat_context(question="制度是什么？", citations=[owned_citation])
    assert "AUTHORIZED_KNOWLEDGE" in context.instructions
    assert owned_citation.text in context.user_input
    assert "oss://" not in context.user_input
```

- [x] **Step 2: 验证测试先失败**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_retrieval.py tests/test_chat_knowledge_context.py -q`  
Expected: FAIL，因为 `retrieve`、`Citation` 和 `build_chat_context` 尚不存在。

- [x] **Step 3: 定义 additive API 模型**

在 `backend/app/schemas/knowledge.py` 增加以下模型，保留 `KnowledgeSearchRequest`、`KnowledgeSearchResponse` 和其 `provider` 字段：

```python
class KnowledgeRetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    source_ids: list[int] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=8, ge=1, le=8)

class KnowledgeCitation(BaseModel):
    entry_id: int
    title: str
    content_sha256: str
    source_locator: str | None
    text: str
    score: float

class KnowledgeRetrieveResponse(BaseModel):
    citations: list[KnowledgeCitation]
    mode: Literal["hybrid", "degraded_full_text", "empty"]
```

同时实现不依赖 PostgreSQL schema 的检索边界：`RetrievalScope`、`AuthorizedKnowledgeSource`、`AuthorizedSourceRepository` protocol、`CandidateRetriever` protocol 和 `KnowledgeRetriever`。`KnowledgeRetriever.retrieve` 必须先调用 repository 的 `authorized_sources(scope, source_ids)`；结果为空时直接返回 `mode="empty"`，不得调用候选检索器。Task 6 只增加 PostgreSQL repository 和包含 embedding/向量/全文查询的候选检索器，不重写该授权顺序。

`chat_context.py` 实现不可变的 `HermesChatInput(user_input, instructions)` 和 `build_chat_context`，只接受已经授权的 `KnowledgeCitation`。它拒绝 `oss://`、`file://`、绝对平台路径和空 citation text，并在总长度超过 12,000 字符时按 citation 顺序截断。

- [x] **Step 4: 运行契约测试与旧 API 回归**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_retrieval.py tests/test_chat_knowledge_context.py tests/test_api.py::test_knowledge_and_skills_contracts -q`  
Expected: PASS；旧 `/api/knowledge/search` 仍返回原有响应 shape。

## Task 2: 完成资料存储与解析的纯服务层（已完成）

**Files:**
- Create: `backend/app/services/object_storage.py`
- Create: `backend/app/services/document_parser.py`
- Create: `backend/tests/test_document_parser.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/routers/knowledge.py`

- [x] **Step 1: 写入文件安全与切片失败测试**

```python
def test_chunker_preserves_order_and_overlap_without_empty_chunks() -> None:
    chunks = chunk_text("第一段。\n\n第二段。", max_chars=8, overlap_chars=2)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert all(0 < len(chunk.text) <= 8 for chunk in chunks)

async def test_upload_uses_private_storage_and_never_returns_object_key(client) -> None:
    response = await client.post(
        "/api/knowledge/upload",
        data={"title": "Private notes"},
        files={"file": ("notes.txt", b"private text", "text/plain")},
    )
    assert response.status_code == 201
    assert "object_key" not in response.json()
```

- [x] **Step 2: 验证测试先失败**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_document_parser.py -q`  
Expected: FAIL，因为 `chunk_text` 与私有 storage adapter 尚不存在。

- [x] **Step 3: 实现私有对象存储和 Docling 解析器**

实现 `ObjectStorage` protocol 的 `put_bytes`, `open_read`, `delete`，并只让数据库保存不透明 object key。测试使用临时目录 fake；生产实现使用私有 OSS。`DocumentParser` 只接受 `pdf`, `docx`, `xlsx`, `pptx`, `txt`, `md`, `html`, `csv`，将 Docling 输出转换为 `ParsedDocument(markdown, source_blocks)`；拒绝格式时抛出 `UnsupportedDocumentFormat`。

切片算法固定为 `max_chars=800`、`overlap_chars=120`，先按标题/段落，后按句子/换行拆分。输入为空、超过限制或不能解析时必须产生稳定错误代码，不把原始异常内容返回给 API。

- [x] **Step 4: 运行解析、上传和隔离测试**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_document_parser.py tests/test_api.py::test_knowledge_and_skills_contracts tests/test_api.py::test_cross_user_resource_isolation -q`  
Expected: PASS；文件路径和对象 key 不出现在 API body。

## Task 3: 完成 1024 维 embedding 适配器和 worker 协议（已完成）

**Files:**
- Create: `backend/app/services/embedding_client.py`
- Create: `backend/app/workers/rag_ingestion.py`
- Create: `backend/tests/test_embedding_client.py`
- Modify: `backend/app/config.py`
- Modify: `backend/requirements.txt`

- [x] **Step 1: 写入 embedding 维度、批次和脱敏失败测试**

```python
async def test_embedding_client_batches_at_most_ten_texts_and_requires_1024_dimensions() -> None:
    vectors = await client.embed([f"chunk-{index}" for index in range(11)])
    assert [len(vector) for vector in vectors] == [1024] * 11
    assert transport.requests[0].json()["dimensions"] == 1024
    assert len(transport.requests[0].json()["input"]) == 10

async def test_embedding_failure_exposes_code_not_provider_body() -> None:
    with pytest.raises(EmbeddingUnavailable, match="embedding_unavailable"):
        await client.embed(["internal text"])
```

- [x] **Step 2: 验证失败状态**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_embedding_client.py -q`  
Expected: FAIL，因为 embedding adapter 尚不存在。

- [x] **Step 3: 实现服务端 embedding adapter**

`EmbeddingClient` 使用 `httpx.AsyncClient` 调用 `/embeddings`，固定请求体：

```python
{
    "model": "text-embedding-v4",
    "input": texts,
    "dimensions": 1024,
    "encoding_format": "float",
}
```

从 `RAG_EMBEDDING_API_KEY: SecretStr | None` 读取凭据；缺失凭据时在 worker 启动阶段 fail closed。日志仅记录 `embedding_unavailable`、HTTP 状态类别、批次大小和 correlation id，不记录 Authorization header、文本或上游响应正文。worker 不启动 HTTP server，只循环领取任务并响应 SIGTERM 停止领取新任务。

- [x] **Step 4: 运行适配器测试**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_embedding_client.py -q`  
Expected: PASS；网络测试使用 `httpx.MockTransport`，不使用真实凭据或付费调用。

## Task 4: 数据库迁移确认关卡（测试服务器隔离验证已完成）

**Files:**
- Create: `backend/migrations/versions/20260729_0005_platform_rag.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_rag_migration.py`

**Stop condition:** 本任务开始前必须获得用户对“已备份、已验证恢复、允许 schema 变更”的本轮明确确认；没有确认时不得创建、运行或尝试迁移。

- [x] **Step 1: 生成备份与隔离恢复证据**

在目标实例外执行由运维批准的 `pg_dump`，在隔离 PostgreSQL 16 + pgvector 恢复，并记录：备份时间、数据库对象数量、`vector` extension 可用性、restore 成功和恢复时长。证据不得包含连接串、用户名、密码、token、对象路径或文档正文。

- [x] **Step 2: 写入 PostgreSQL 专用失败测试**

```python
async def test_rag_schema_has_fixed_dimension_and_tenant_indexes(pg_session) -> None:
    row = await pg_session.execute(
        text(
            "SELECT format_type(a.atttypid, a.atttypmod) "
            "FROM pg_attribute AS a "
            "JOIN pg_class AS c ON c.oid = a.attrelid "
            "WHERE c.relname = 'knowledge_chunks' AND a.attname = 'embedding'"
        )
    )
    assert row.scalar_one() == "vector(1024)"
    indexes = await pg_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = 'knowledge_chunks'"
        )
    )
    assert {"ix_knowledge_chunks_scope", "ix_knowledge_chunks_embedding_hnsw"}.issubset(
        {item[0] for item in indexes}
    )
```

- [x] **Step 3: 创建可回滚迁移**

迁移先执行 `CREATE EXTENSION IF NOT EXISTS vector`，再创建 `knowledge_ingestion_jobs`、`knowledge_chunks`、`knowledge_retrieval_events`。`knowledge_chunks.embedding` 使用 `vector(1024)`，HNSW 使用 `vector_cosine_ops`，全文索引使用 `to_tsvector('simple', text)`。所有 RAG 外键指向 `knowledge_entries`，均为 `ON DELETE CASCADE`。同时给 `chat_sessions` additive 增加 `hermes_backend VARCHAR(20)`：现有行回填 `agent`，随后设为非空，新会话默认由应用明确写入 `knowledge`；升级/降级不得修改或删除其他既有列。

- [x] **Step 4: 隔离环境验证升级、降级和 schema/index**

Run: `cd backend; .\.venv\Scripts\alembic.exe upgrade head; .\.venv\Scripts\python.exe -m pytest tests/test_rag_migration.py -q; .\.venv\Scripts\alembic.exe downgrade -1`  
Expected: upgrade PASS、索引存在、downgrade PASS；100k chunk 固定数据集的检索结果不跨 tenant。

- [x] **Step 5: 测试服务器授权已确认；生产迁移仍保持未授权**

提交迁移 diff、隔离验证和回滚证据给负责人。只在获得本轮确认后运行生产 `alembic upgrade head`；否则保持 schema 不变。

## Task 5: 实现任务化 ingestion 与版本替换

**Files:**
- Create: `backend/app/services/knowledge_ingestion.py`
- Create: `backend/tests/test_knowledge_ingestion.py`
- Modify: `backend/app/routers/knowledge.py`
- Modify: `backend/app/services/object_storage.py`

- [x] **Step 1: 写入生命周期失败测试**

```python
async def test_same_entry_and_hash_is_idempotent(db) -> None:
    first = await service.enqueue(entry, content_sha256="a" * 64)
    second = await service.enqueue(entry, content_sha256="a" * 64)
    assert first.id == second.id

async def test_ready_version_replaces_old_chunks_atomically(db) -> None:
    await service.complete(job, new_chunks)
    assert await chunks_for(entry, old_hash) == []
    assert len(await chunks_for(entry, new_hash)) == len(new_chunks)
```

- [x] **Step 2: 验证失败状态**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_ingestion.py -q`  
Expected: FAIL，因为 job/chunk persistence 和 service 尚不存在。

- [x] **Step 3: 实现状态机和 worker 领取逻辑**

状态只允许 `queued -> processing -> ready | failed | cancelled`。worker 用 `SELECT id FROM knowledge_ingestion_jobs WHERE status = 'queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1` 领取最早 queued job，最大尝试次数为 3；可重试错误退避，非白名单格式立即 failed。成功事务内插入新 chunks、删除同资源旧 hash chunks、标记 job ready；任何异常 rollback，不能出现一半新索引。

- [x] **Step 4: 添加 ingestion API 并运行测试**

新增 `POST /api/knowledge/{id}/ingest` 和 `GET /api/knowledge/{id}/ingestion`。两者均先走既有 `owned_entry`。  
Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_ingestion.py tests/test_api.py -q`  
Expected: PASS；跨用户和跨组织均为 404，重复入队不重复解析。

## Task 6: 实现授权混合检索与可核验引用

**Files:**
- Create: `backend/app/services/knowledge_retrieval.py`
- Modify: `backend/app/routers/knowledge.py`
- Modify: `backend/tests/test_knowledge_retrieval.py`

- [x] **Step 1: 增加 RRF、预算和撤权失败测试**

```python
def test_rrf_prefers_items_returned_by_both_retrievers() -> None:
    merged = fuse_rrf(vector_ids=[1, 2], full_text_ids=[2, 3], k=60)
    assert [item.chunk_id for item in merged] == [2, 1, 3]

async def test_revoked_or_foreign_chunks_never_reach_candidates() -> None:
    result = await retriever.retrieve(member_a, query="机密", source_ids=[])
    assert all(citation.entry_id != revoked_entry.id for citation in result.citations)
```

- [x] **Step 2: 验证失败状态**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_retrieval.py -q`  
Expected: FAIL，因为 PostgreSQL vector/FTS query 和 RRF 尚不存在。

- [x] **Step 3: 实现权限优先检索**

在每一个 vector/FTS query 上固定谓词：`organization_id == membership.organization_id`、`user_id == membership.user_id`、`knowledge_entry_id IN authorized_sources`。source ids 为空时由该谓词生成所有当前用户 ready 资源；source ids 非空时取交集。向量和全文各取 24，RRF `k=60`，最终最多 8 个，单资源最多 2 个，总文本最多 12,000 字符。

- [x] **Step 4: 增加 retrieve endpoint 与兼容 search 映射**

`POST /api/knowledge/retrieve` 返回 `KnowledgeRetrieveResponse`。旧 `/search` 使用同一 retriever 并保留 `KnowledgeSearchResponse` shape，provider 改为 `platform-pgvector`。向量异常时同一授权集合内全文降级，返回 `mode="degraded_full_text"`。

- [x] **Step 5: 运行检索和隔离测试**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_retrieval.py tests/test_api.py::test_cross_user_resource_isolation -q`  
Expected: PASS；未授权 source 永不调用 embedding，撤权后无候选、无 citation。

## Task 7: 将授权上下文注入 Hermes，完成知识人格

**Files:**
- Create: `backend/app/services/chat_context.py`
- Modify: `backend/app/services/hermes_client.py`
- Modify: `backend/app/routers/chat.py`
- Create: `deploy/hermes/SOUL.md`
- Create: `deploy/hermes/config.knowledge.yaml`
- Modify: `deploy/compose.hermes.yaml`
- Modify: `backend/tests/test_chat_knowledge_context.py`
- Modify: `backend/tests/test_hermes_boundary.py`

- [x] **Step 1: 写入反泄漏失败测试**

```python
async def test_chat_adapter_never_sends_unapproved_document_or_storage_metadata(client, monkeypatch) -> None:
    recorded = await send_with_recording_hermes(client, source_ids=[owned_entry.id])
    assert owned_chunk.text in recorded.instructions
    assert foreign_chunk.text not in recorded.instructions
    assert "object_key" not in recorded.instructions
    assert "file_path" not in recorded.instructions

async def test_knowledge_session_uses_gateway_with_no_enabled_toolsets(client) -> None:
    recorded = await send_with_recording_hermes(client, source_ids=[owned_entry.id])
    assert recorded.backend == "knowledge"
    assert recorded.capabilities["toolsets"] == []
```

- [x] **Step 2: 验证失败状态**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_chat_knowledge_context.py tests/test_hermes_boundary.py -q`  
Expected: FAIL，因为 `HermesChatInput` 和 instructions 参数尚不存在。

- [x] **Step 3: 扩展 Hermes 协议但保留兼容调用**

为 `HermesProvider.create_response` 和 `HermesHttpClient.create_response` 增加可选 `instructions: str | None = None`。旧调用仍只传 `content` 和 `session_id`。HTTP adapter 仅在 instructions 非空时添加 `/v1/runs` 的 `instructions` 字段；其值只来自 `chat_context.py`，不能从 HTTP 请求 body 透传。增加 `HermesClientRouter`，根据服务端读取的 `ChatSession.hermes_backend` 在 agent 与 knowledge 两个固定私网 endpoint 中选取客户端；浏览器不能提交或覆盖 backend。

- [x] **Step 4: 组装上下文和部署 SOUL**

`build_chat_context` 生成固定平台 instructions、编号 citations 和用户问题。知识模式 instructions 明确禁止直接上传文件、编造引用和执行未批准操作。新增 `hermes-knowledge` 服务，使用独立 volume、`deploy/hermes/config.knowledge.yaml`、相同固定镜像/provider/model，且 `platform_toolsets.api_server: []`；不设置 `DOCKER_HOST`，不挂载 runner SSH 或 terminal/file policy。将 `deploy/hermes/SOUL.md` 只读挂载到 knowledge gateway 的 `/opt/data/SOUL.md`；SOUL 仅放全局云枢知识助理人格，不放组织规则、路径、密钥或业务数据。现有 agent gateway、runner 和历史 session 保持，不重复建设。

- [x] **Step 5: 回归 SSE 生命周期**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_chat_knowledge_context.py tests/test_hermes_boundary.py tests/test_api.py -q`  
Expected: PASS；现有 agent 会话的 SSE、stop、approval、delete、runner cleanup 均保持；knowledge 会话只路由 tool-less gateway，Hermes 只收到已授权上下文。

## Task 8: 部署、容量验证与报价修订

**Files:**
- Modify: `deploy/compose.yaml`
- Modify: `deploy/compose.hermes.yaml`
- Modify: `backend/README.md`
- Modify: `backend/docs/api-integration-guide.md`
- Modify: `.sisyphus/drafts/cloud-cost-quotation-v2.md`
- Create: `backend/tests/fixtures/rag/evaluation.jsonl`

- [x] **Step 1: 建立不含客户内容的评价集**

创建至少 100 条 JSONL 标注查询，每条包含 `query`、`expected_entry_ids`、`tenant`，并用合成文档覆盖制度、表格、中文段落、英文术语、更新和删除。不得放入真实客户文档、API key、密码或 token。

- [x] **Step 2: 添加 worker 部署与健康约束**

在 Compose 增加 `rag-worker`，与 API 使用同一受控数据库和对象存储配置；API 先可用，worker 不健康时 ingestion 显示 queued/failed 而不阻塞资源 CRUD。生产环境使用私网 RDS/OSS；embedding API key 仅 worker 注入。

- [x] **Step 3: 更新成本报价事实而非估算宣传**

将 RDS 从基础版改为 PostgreSQL 16 高可用版，明确 `4C16G/100GB` 为待实时报价的生产测算基线，`4C8G/100GB` 仅试运行。补列私有 OSS、独立 worker 资源、备份恢复和 embedding 调用成本；单 ECS 无负载均衡标注为“可恢复单机”，不得标注为高可用。

- [x] **Step 4: 在隔离环境执行容量与故障验证**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q`  
Run: `cd backend; .\.venv\Scripts\python.exe scripts/evaluate_rag.py --dataset tests/fixtures/rag/evaluation.jsonl --report .runtime/rag-evaluation.json`  
Expected: 所有测试 PASS；报告包含 Recall@5、citation accuracy、P95 检索延迟、100k/1M chunk 资源占用、零跨 tenant 结果、worker 中断恢复和删除传播时间。

- [x] **Step 5: 真实验收必须重新执行并记录本轮证据**

在已批准的部署环境验证：登录 -> `/auth/me` -> 上传 -> ingest -> authorized retrieve -> Hermes SSE -> history -> stop -> delete -> runner cleanup。使用双账号/双组织证明隔离，验证没有 chat Mock，且只报告无敏感值的状态和计数；不得将历史验收结果冒充本轮验证。

## 延期工作记录

完成本计划并通过真实授权检索验收后，才重新开启前端设计稿、交互状态机、知识共享业务规则、运营页面和外部用户产品功能的详细设计。届时 AI 仍位于知识库，不新增侧边栏“云枢助手”。
