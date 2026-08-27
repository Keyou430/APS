# 平台自有 RAG 测试服务器部署检查点

日期：2026-07-30  
环境：192.168.3.131（测试服务器）  
范围：平台自有 RAG + pgvector，非生产环境

## 已通过

- 部署前 PostgreSQL custom-format 备份已生成，权限 600。
- 数据库由 `20260727_0004` 升级到 `20260729_0005`。
- PostgreSQL 16 使用 pgvector 0.8.5，chunk embedding 为 `vector(1024)`。
- API、Web、原 agent gateway、tool-less knowledge gateway、PostgreSQL 均健康。
- knowledge gateway 无 `DOCKER_HOST`、无 runner SSH 挂载；独立 config 与 SOUL 挂载存在。
- 真实 Chromium：登录、`/auth/me`、知识库内创建会话、Bearer SSE、history、刷新恢复、stop、delete 通过。
- 双账号会话列表和 history 404 隔离通过。
- 390px 无横向溢出，控制台无 error；侧边栏无“云枢助手”。
- 真实 RAG REST：创建资源、ingest 202、queued 状态、未就绪检索 empty、删除通过。
- 验收后临时用户、active run、queued job 均为 0。

## 本轮最终验证（2026-07-30）

- 本地后端回归：`147 passed`；Ruff、`git diff --check`、PowerShell/POSIX 启动脚本语法检查通过。
- 最终 release `20260730-final` 的 API、RAG worker、Web、两个 Hermes gateway 和 PostgreSQL 均 healthy；API/worker/Web 重启次数为 0；Compose config 校验通过。
- provider key 边界：API 仅有 query proxy URL/token；`RAG_EMBEDDING_API_KEY` 只出现在 worker；worker `8091` 仅 Compose `expose`，无 host port。
- 100 条无敏感合成评价集：100/100 hybrid，Hit@1 `0.75`，Recall@5 `0.93`，citation accuracy `0.2325`，hard-negative@5 `0.1825`，P95 `388.39 ms`，cross-tenant `0`；评测 entry/job/chunk 残留均为 0，删除传播 `0.395 s`。
- 100k/1M chunk 容量基准：向量查询 P95 分别 `1.12 ms` / `1.41 ms`；数据库峰值约 `1.41 GB` / `14.15 GB`，HNSW 索引约 `0.80 GB` / `8.14 GB`；两档 cross-scope 检查均为 0。全文选择性报告显示 1M 全匹配为顺序扫描，P95 约 `2.83 s`，不能按向量 SLO 估算。
- worker 故障注入：停止 5 秒时 ingestion 保持 `queued`；恢复后约 `1.04 s` 到 `ready`，hybrid citation 命中；删除传播 `27 ms`，entry/job/chunk 均为 0。
- 压测残留已清理：`knowledge_chunks=0`、active ingestion `0`、合成 entry/user `0`；表空间从压测膨胀恢复到约 64 KiB，数据库约 10.4 MB。

## 未授权或未执行的生产门禁

- 未购买云实例；生产 RDS/OSS、生产迁移和外部用户验收仍未授权执行。
- 尚未在生产 RDS 高可用版验证主备切换、应用重连和真实 RTO/RPO。
- 尚未在生产私有 OSS、正式域名/TLS 和外部网络入口执行验收。

这些生产项目保持为后续门禁，不能以本轮测试服务器、mock、单元测试或旧验证结果替代。
