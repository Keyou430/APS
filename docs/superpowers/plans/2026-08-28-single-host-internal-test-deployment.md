# Hermes 单机内部测试部署实施计划

## 目标

在 `codex/hermes-platform-full-chain` 分支上补齐 Ubuntu 24.04 单机云部署能力。只修改 `deploy/` 与部署文档，保持所有业务功能文件原样。

## 实施边界

- 不修改 `backend/`、`web-platform/`、`hermes/`。
- 不暂存或提交现有 `.tmp/`、`uploads/`、`backend/uploads/`、`hermes/scripts/` 内容。
- 所有运行密钥、证书、SSH 材料、上游源码和 attestation 写入已忽略的 `deploy/.runtime/` 或服务器 `deploy/.env`。
- 每个提交前用 `git diff --cached --name-only` 验证边界。

## 任务 1：单机 Compose override

新增 `deploy/compose.single-host.yaml`：

- Hermes runner 地址使用 `host.docker.internal`，通过 `extra_hosts: host.docker.internal:host-gateway` 稳定解析。
- API runner control URL 使用 mTLS `https://host.docker.internal:9443`。
- Agent 挂载生成的 `deploy/.runtime/single-host/hermes-agent-config.yaml`。
- API 注入 `HERMES_CRON_INTERNAL_KEY` 与容器内平台 URL。
- 将 sandbox 并发限制为 4/2/1。
- 为主服务配置资源上限和 `local` 日志轮转。

验证：

```bash
docker compose --env-file .env \
  -f compose.yaml -f compose.hermes.yaml -f compose.single-host.yaml config --quiet
```

## 任务 2：运行配置生成

新增 `deploy/scripts/render-single-host-config.py`：

- 使用 YAML 解析器读取 `deploy/hermes/config.yaml`。
- 保留原配置，补齐 `hermes-platform-pipeline` MCP 定义。
- 写入 `PLATFORM_API_URL=http://api:8000`。
- 从环境读取非占位 `HERMES_CRON_INTERNAL_KEY`。
- 使用临时文件与原子替换写入 `.runtime/single-host/hermes-agent-config.yaml`。
- 输出文件权限不包含密钥的额外副本。

验证：用临时目录和测试密钥运行，解析输出 YAML，并确认无旧 IP、开发密钥或 API loopback。

## 任务 3：单机 rootless runner 初始化

新增：

- `deploy/scripts/bootstrap-single-host.sh`
- `deploy/scripts/verify-single-host-runner.sh`
- `deploy/runner/hermes-runner-control-single-host.service`

初始化脚本：

- 要求 root 与 Ubuntu 24.04，但保留宿主机标准 Docker。
- 安装 rootless Docker 前置依赖、PyYAML、OpenSSL 和 OpenSSH。
- 创建无 sudo 权限的 `hermes-runner`，配置 subuid/subgid、linger 和 cgroup delegation。
- 初始化独立 rootless Docker daemon 与 10 MB 本地日志上限。
- 生成受限 SSH key、known_hosts、配置文件及强制 `docker system dial-stdio` 命令。
- 生成私有 CA、带 `host.docker.internal` SAN 的服务证书和 API 客户端证书。
- 安装 runner control 和 reaper systemd 单元。
- 将客户端材料分别设置为 Hermes UID 10000 与 API UID 10001 可读。

验证脚本同时确认标准 Docker 和 rootless Docker 健康、runner 无 sudo、SSH 无交互可达、mTLS health 可达、控制端点不监听公网地址。

## 任务 4：预检与启动编排

新增：

- `deploy/scripts/preflight-single-host.sh`
- `deploy/scripts/up-single-host.sh`
- `deploy/scripts/verify-single-host-deployment.sh`

预检项目：

- Ubuntu 24.04、至少 8 CPU、14 GiB 内存、15 GiB 可用磁盘。
- 当前分支为完整链路分支、基线提交 `4c66506` 是 HEAD 祖先、工作区无已跟踪改动。
- Docker/Compose、Python/PyYAML、curl、openssl 可用。
- `.env` 为 0600，必填密钥存在且不使用占位值。
- Web 绑定为 `0.0.0.0`，RAG 已启用并配置 provider。
- runner SSH、mTLS 和 runtime 文件均存在且权限正确。

启动脚本复用现有 Hermes 源码准备和 attestation 逻辑，但始终带三个 Compose 文件，按数据库、Hermes、attestation、其余服务的顺序启动。

验收脚本验证 Compose 服务状态、Web `/ready`、API health、runner mTLS、容器端口映射和最新数据库 migration head。需要真实用户操作的 AI、飞书和 pipeline 验收保留为明确的人工清单。

## 任务 5：飞书换绑

新增 `deploy/scripts/rebind-feishu.sh`：

- `bot` 模式校验机器人和平台凭证，备份 `.env`，只重新创建 `hermes`、`api`、`delivery-worker`，随后检查健康状态。
- `user` 模式备份 `lark_cli_data` 卷，在 Hermes 镜像的受控临时容器内执行交互式个人授权，并在成功后重建 Agent。
- `restore-user <archive>` 仅恢复 `lark_cli_data`。
- 所有模式拒绝数据库卷、上传卷或 `down --volumes` 操作。

## 任务 6：环境模板和文档

更新 `deploy/.env.example`：

- 恢复非弱口令管理员占位值。
- 增加单机部署所需 `HERMES_CRON_INTERNAL_KEY`、runner 地址/端口和部署基线说明。
- 明确飞书机器人与个人 OAuth 的不同持久化位置。

更新 `deploy/README.md`：

- 添加 Ubuntu 单机内部测试服务器的初始化、启动、状态、日志、备份和飞书换绑命令。
- 添加安全组端口矩阵和磁盘维护说明。
- 明确禁止公网开放 runner、数据库和 Hermes 端口。

## 任务 7：验证与提交

执行：

```bash
sh -n deploy/scripts/*.sh
python -m py_compile deploy/scripts/render-single-host-config.py
docker compose --env-file <validation-env> \
  -f deploy/compose.yaml \
  -f deploy/compose.hermes.yaml \
  -f deploy/compose.single-host.yaml config --quiet
```

在 Windows 本地无法执行 systemd、rootless Docker 和真实云网络验证，因此这些项目必须由服务器预检和验收脚本在 Ubuntu 上完成。静态验证通过后，只提交 `deploy/`、本实施计划和必要的设计勘误，并推送 `codex/hermes-platform-full-chain`。
