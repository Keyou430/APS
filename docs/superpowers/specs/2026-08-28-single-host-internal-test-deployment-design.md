# Hermes 单机内部测试服务器部署设计

## 1. 目标与约束

将 `codex/hermes-platform-full-chain` 分支部署到一台 Ubuntu 24.04.4 LTS 云服务器，维持现有完整功能链路，同时不修改 `backend/`、`web-platform/` 或 `hermes/` 中的功能文件。

目标服务器配置为 8 核 CPU、15 GiB 内存、约 28 GiB 可用系统盘和 1.9 GiB Swap。测试人员通过公网 IP 访问，由云安全组限制为明确的测试 IP 白名单。内部测试阶段不配置域名和 HTTPS。

功能基线为提交 `4c665069236324cfeed1af6479e840cc4458310c`。部署脚本必须在启动前校验目标分支、确认该提交是当前发布提交的祖先，并拒绝带有已跟踪改动的工作区。

## 2. 范围

### 2.1 保留的功能链路

- Nginx 和 Web 前端
- FastAPI API
- PostgreSQL/pgvector
- RAG worker
- Hermes Agent gateway
- Hermes Knowledge gateway
- Pipeline worker
- Pipeline approval worker
- Delivery worker
- Hermes 定时任务桥接
- Hermes terminal/file 隔离执行
- 飞书机器人、平台读取与消息投递
- `hermes-lark-cli` 个人用户授权

### 2.2 允许修改的范围

只允许新增或修改：

- `deploy/` 下的 Compose override、初始化脚本、校验脚本、换绑脚本和运维文档
- 本设计文档及后续部署实施计划

严禁修改：

- `backend/` 功能代码、迁移和测试
- `web-platform/` 功能代码和测试
- `hermes/` 功能代码、MCP 实现和业务配置源文件

部署期间生成的证书、密钥、Hermes 源码、运行时配置和 attestation 只能写入已忽略的 `deploy/.runtime/`。服务器密钥只写入权限为 `0600` 的 `deploy/.env`。

## 3. 选定架构

采用单机双 Docker daemon：

1. 宿主机标准 Docker daemon 运行主平台 Compose，包括数据库、Web、API、RAG、双 Hermes gateway 和全部 worker。
2. 独立的 `hermes-runner` 系统用户运行 rootless Docker daemon，只承载 Hermes 临时隔离任务。
3. Hermes 通过受限 SSH 传输访问 rootless Docker；API 通过 mTLS 控制端点执行任务清理。
4. runner SSH 和控制端点仅允许主机及 Docker bridge 网络访问，不向公网开放。

现有 `bootstrap-hermes-runner.sh` 会屏蔽宿主机标准 Docker，不适用于单机模式。单机部署使用新的 bootstrap 脚本，保留标准 Docker，同时配置独立 rootless daemon。

## 4. Compose 结构

内部测试服务器使用：

```text
deploy/compose.yaml
+ deploy/compose.hermes.yaml
+ deploy/compose.single-host.yaml
```

`compose.single-host.yaml` 只覆盖部署环境差异：

- 将 `DOCKER_HOST` 从固定内网地址改为单机宿主机 gateway。
- 将 `SANDBOX_RUNNER_URL` 改为单机 mTLS 控制端点。
- 为需要访问宿主机的容器增加稳定的 host-gateway 别名。
- 挂载部署时生成的 Hermes 运行配置。
- 增加只在 Compose 内网监听的 Hermes cron bridge。它在共享 Hermes 状态上执行经过严格白名单校验的 `cron create/remove`，并为现有 API 提供 CLI 兼容入口，因此无需修改后端功能代码或把 Docker socket 挂入 API。
- 将 sandbox 并发限制为全局 4、每组织 2、每用户 1。
- 设置与 15 GiB 内存相符的容器资源和日志轮转上限。

不覆盖业务服务命令、数据库模型、API 路由、前端构建内容或 worker 行为。

## 5. 容器内配置投影

当前 Hermes 配置包含本机开发环境地址和开发密钥：

- `PLATFORM_API_URL=http://127.0.0.1:8000`
- `HERMES_CRON_INTERNAL_KEY=development-only`

容器中不能继续使用这些值。部署脚本从版本控制的源配置生成 `deploy/.runtime/single-host/` 下的运行配置，只替换部署边界：

- `PLATFORM_API_URL=http://api:8000`
- `HERMES_CRON_INTERNAL_KEY` 从 `deploy/.env` 注入

API 容器和 Hermes MCP 运行配置必须读取同一内部密钥。生成步骤必须可重复、原子写入，并在启动前验证配置中不存在 `development-only`、旧地址 `192.168.3.107` 或错误的 API loopback 地址。

## 6. 单机 runner

`bootstrap-single-host.sh` 负责：

- 确认系统为 Ubuntu 24.04。
- 保留并验证宿主机标准 Docker daemon。
- 创建无 sudo 权限、无密码登录权限的 `hermes-runner` 用户。
- 配置 subuid/subgid、用户 linger、cgroup delegation 和 rootless Docker。
- 为 SSH 公钥配置固定的 `docker system dial-stdio` 强制命令。
- 生成独立 CA、服务端和客户端证书，并限制私钥权限。
- 安装 runner control systemd service 和 reaper timer。
- 将 runner 控制服务限制到 Docker bridge 可达地址，并通过主机防火墙拒绝公网访问。
- 验证 rootless、安全选项、cgroup、socket 所有权和网络监听状态。

主 Compose 不挂载 rootful 或 rootless Docker socket。所有任务操作继续经过现有 SSH/mTLS 边界。

## 7. 启动流程

`up-single-host.sh` 按以下顺序执行：

1. 运行预检。
2. 验证当前 Git 分支和完整提交 SHA。
3. 验证 `deploy/.env` 权限及必填值，拒绝占位密码和开发密钥。
4. 验证 rootful 平台 Docker 与 rootless runner Docker 均健康。
5. 生成运行时 Hermes 配置。
6. 下载固定 Hermes 上游 commit 并构建固定版本镜像。
7. 启动 PostgreSQL 与 Hermes Agent。
8. 生成并验证 sandbox attestation。
9. 启动 RAG、API、Web、Knowledge gateway 和全部 worker。
10. 等待全部容器健康，并运行部署验收探测。

任一阶段失败时停止后续阶段，保留日志、容器状态和数据卷用于诊断。脚本不得自动执行 `docker compose down --volumes`、删除数据库、清除上传卷或重置飞书授权。

## 8. 网络与访问控制

- Web 测试端口绑定 `0.0.0.0`，端口值来自 `.env`。
- 云安全组只允许指定测试 IP 访问 Web 测试端口和管理员 SSH 端口。
- PostgreSQL、Hermes、RAG 和 worker 不映射宿主机公网端口。
- runner rootless Docker socket 不使用 TCP 暴露。
- runner control 端口仅允许 Docker bridge 和本机访问，并强制 mTLS。
- 飞书使用 WebSocket 连接，不增加公网 webhook 入站端口。

## 9. 资源与磁盘策略

- sandbox 并发上限：全局 4、每组织 2、每用户 1。
- runner 单任务继续使用既有 CPU、内存和 tmpfs 限制。
- 主服务使用 Compose 硬上限：PostgreSQL 1.5 GiB/1 CPU、API 1.5 GiB/2 CPU、RAG 1.5 GiB/2 CPU、Hermes Agent 2 GiB/2 CPU、Hermes Knowledge 1.5 GiB/1.5 CPU、Hermes cron bridge 512 MiB/0.5 CPU、Web 256 MiB/0.5 CPU、Pipeline worker 512 MiB/1 CPU、Approval worker 384 MiB/0.5 CPU、Delivery worker 384 MiB/0.5 CPU。
- 全部主服务内存上限合计约 10 GiB；最多四个既有 256 MiB sandbox 合计 1 GiB，为系统、双 Docker daemon、构建峰值和文件缓存保留约 4 GiB。
- Docker 和 runner 日志使用轮转，单文件上限 10 MB。
- 可用磁盘低于 15 GiB 时，预检拒绝首次构建或升级。
- 运维命令只能清理已停止的临时任务容器和明确标记的旧构建缓存，禁止自动清理命名卷。
- 数据库备份保存在 `deploy/backups/`，并监测其磁盘占用。

## 10. 飞书换绑

### 10.1 更换应用机器人

操作员在 `deploy/.env` 更新：

- `FEISHU_APP_ID`、`FEISHU_APP_SECRET`
- `FEISHU_ALLOWED_USERS`、`FEISHU_HOME_CHANNEL` 等机器人策略
- 如新应用承担平台读取或通知，再同步更新 `PLATFORM_FEISHU_APP_ID`、`PLATFORM_FEISHU_APP_SECRET`
- 平台读取授权列表和配置状态标志

`rebind-feishu.sh bot` 校验变量后定向重新创建 `hermes`、`api` 和 `delivery-worker`。每次成功部署保存权限为 `0600` 的 ignored last-known-good 环境快照；换绑失败时自动恢复该快照并重新创建原服务。脚本不得重新创建数据库或删除任何卷。飞书开放平台仍需为新应用配置相同权限、启用机器人/WebSocket，并授予目标群、文档、Wiki 和 Base 的访问权。

### 10.2 更换个人用户授权

个人 OAuth 状态保存在独立 `lark_cli_data` 卷中，不能仅通过 `.env` 更换。

`rebind-feishu.sh user` 执行以下流程：

1. 停止依赖个人授权的 Hermes Agent。
2. 备份 `lark_cli_data` 卷。
3. 在受控临时容器中执行 lark-cli 注销和新用户授权。
4. 验证 token 状态及一次只读飞书调用。
5. 重新启动 Hermes Agent 并验证 MCP 工具注册。

新授权失败时恢复原授权卷备份；PostgreSQL、上传卷、Knowledge gateway 和其他 Hermes 状态不受影响。

## 11. 故障处理与回滚

- 所有脚本使用非零退出码和明确的阶段错误信息。
- 配置和证书生成使用临时文件加原子替换。
- 升级前记录 Git SHA、Compose 配置摘要并创建数据库备份。
- 失败后不自动回退数据库迁移；操作员根据备份和发布 SHA 执行恢复。
- 飞书机器人换绑通过恢复 `.env` 备份回滚；个人授权换绑通过恢复 `lark_cli_data` 备份回滚。
- 日志必须覆盖 preflight、镜像构建、Compose、runner、attestation 和验收探测。

## 12. 验收标准

部署只有在以下项目全部通过后才算成功：

1. Compose 合并配置可解析，且不存在占位密钥、旧 runner IP 或错误的容器 API 地址。
2. PostgreSQL、RAG、Web、API、双 Hermes gateway 和全部 worker 健康。
3. 数据库迁移到分支最新 revision。
4. 测试用户可通过白名单 IP 登录并访问 Web/API；非白名单 IP 被云安全组拒绝。
5. AI 对话、知识检索和 RAG 返回有效结果。
6. Pipeline 创建、审批、重新生成、worker 消费和定时触发成功。
7. Hermes Agent 与 Knowledge gateway 保持配置和数据隔离。
8. terminal/file sandbox 可创建、执行和回收，并通过跨任务隔离验证。
9. 飞书机器人可接收消息，平台可发送通知并读取明确授权的资源。
10. `lark-cli` 个人授权有效，并通过一次只读调用。
11. 所有非 Web 服务均未暴露公网端口。

## 13. 非目标

本次不引入域名、HTTPS、负载均衡、多主机高可用、自动 CI/CD、集中监控平台或业务功能调整。这些能力可在内部测试稳定后单独设计。
