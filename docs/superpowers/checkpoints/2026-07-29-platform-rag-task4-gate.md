# 平台 RAG Task 4 数据库变更关卡

日期：2026-07-29  
状态：测试服务器备份与隔离恢复已通过，已获准执行  
当前分支：`codex/hermes-platform-integration`

## 已完成且不涉及 schema 的工作

- 授权检索编排边界：未授权 source 在候选检索前被截断。
- Hermes 知识上下文构建：只接受授权 citation，拒绝对象存储和绝对路径 locator。
- 私有本地对象存储适配器：新上传保存不透明 `private/...` key，API 兼容 `file_path` 字段固定返回 `null`。
- 历史上传兼容：仅允许删除 `upload_dir` 内的旧路径，目录外路径 fail closed。
- Docling `v2.112.0` 解析适配、格式白名单、文本规范化和确定性切片。
- 本地运行时已安装并成功导入 Docling `2.112.0`；其依赖要求使 `pydantic-settings` 从 `2.10.1` 升至 `2.14.2`，完整回归已验证兼容。
- 百炼 `text-embedding-v4`、1024 维、每批最多 10 条的服务端适配器。
- embedding 异常脱敏、错误维度拒绝、缺失凭据时 worker fail closed、空队列等待和停止协议。

验证证据：

```text
新增测试：14 passed
后端完整回归：93 passed
Ruff：All checks passed
pip check：No broken requirements found
Docling DocumentConverter import：ok
```

测试使用 SQLite、临时文件、注入 converter 和 `httpx.MockTransport`。Docling 完成真实包导入，但未下载解析模型或处理客户文档。未连接真实 RDS、OSS、百炼或 Hermes，未读取或输出任何凭据。

## Task 4 拟议 schema 变更

只有获得本轮确认后才能创建迁移文件：

- 创建 `knowledge_ingestion_jobs`。
- 创建 `knowledge_chunks`，其中 `embedding vector(1024)`。
- 创建 `knowledge_retrieval_events`。
- 创建 organization/user/resource B-tree、全文 GIN 和 cosine HNSW 索引。
- 给 `chat_sessions` additive 增加非空 `hermes_backend`；现有行回填 `agent`，新知识会话由应用写入 `knowledge`。
- 不删除或重命名 `knowledge_entries`、ChatSession 既有列、`hermes-*` key、兼容字段或历史类型名。

## 进入 Task 4 前必须提供的证据

1. 明确目标数据库实例和维护窗口。
2. 确认 PostgreSQL 16 目标小版本与 `vector` extension 可用版本。
3. 完成逻辑备份，并在隔离 PostgreSQL 16 + pgvector 环境恢复成功。
4. 记录无敏感的备份时间、对象数量、校验结果、恢复用时和恢复结论。
5. 确认失败回滚窗口、停止 RAG worker 的方式以及应用版本回退点。

## 明确确认语句

完成上述证据后，负责人需明确回复：

> 已确认目标数据库备份及隔离恢复成功，授权创建并在隔离环境验证 Task 4 RAG migration；生产迁移仍需验证后再次确认。

在收到该确认前，不创建 `20260729_0005_platform_rag.py`，不执行 `CREATE EXTENSION`、Alembic upgrade/downgrade、建表、建索引或数据导入。

## 2026-07-29 测试服务器授权与证据

负责人已明确指定测试服务器 `192.168.3.131`，授权创建所需数据库并继续完成计划。本授权仅适用于测试服务器，不授权任何未来生产实例迁移。

迁移前证据：

```text
PostgreSQL: 16.14
pgvector: 0.8.5
Alembic: 20260727_0004
public base tables: 19
source counts (users, knowledge_entries, chat_sessions): 1,0,3
backup mode: 600
```

逻辑备份已写入测试服务器受限目录 `deploy/backups/rag-task4-20260729/`，并计算 SHA-256；校验值只保存在本轮执行证据中，不写入应用日志。备份已恢复到全新隔离数据库 `agent_platform_rag_restore_20260729_1458`，恢复后的 Alembic、表数、pgvector 版本和上述记录计数与源库一致。

执行顺序固定为：先在该隔离恢复数据库验证 upgrade -> schema/index -> downgrade -> restore invariants -> upgrade；验证通过后才允许对测试应用数据库执行 upgrade。生产迁移仍需单独备份和再次确认。

隔离数据库验证结果：

```text
upgrade: 20260727_0004 -> 20260729_0005 passed
downgrade: 20260729_0005 -> 20260727_0004 passed
second upgrade: 20260727_0004 -> 20260729_0005 passed
tables after upgrade: 22
embedding type: vector(1024)
job status default: queued, NOT NULL
chunk indexes: BTREE scope, GIN simple FTS, HNSW vector_cosine_ops
existing chat backends: agent=3, null=0
source counts after round trip: 1,0,3
```

测试应用数据库尚未迁移；它将在包含 Task 5--7 代码的新 API 镜像部署时执行一次 `alembic upgrade head`，避免旧 API 模型与新 schema 长时间错配。
