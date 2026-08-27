# 本地 Hermes 接入项目 AI 服务设计

日期：2026-08-26（Asia/Shanghai）

## 目标

将 `D:\Replica1.0\hermes` 中的本地 Hermes Agent 接入项目现有 AI 服务，使浏览器 AI 工作台的通用对话由本地 Hermes 执行，并允许 Hermes 在对话中调用已经完成用户 OAuth 的飞书群聊只读 MCP。同时保留项目既有的知识会话工具隔离，不让知识网关访问飞书。

完成后，本地开发链路为：

```text
浏览器 :5173
  -> FastAPI :8000
    -> Hermes Agent :8642
      -> DeepSeek
      -> hermes-feishu-readonly MCP
        -> lark-cli --as user
    -> Hermes Knowledge :8643
      -> DeepSeek
      -> no_mcp
```

## 范围

### 包含

- 启动两个相互隔离的 Windows 本地 Hermes HTTP 网关。
- 让项目后端通过现有 `HermesHttpClient` 使用真实 Hermes，而不是兼容 Mock。
- 通用对话网关只允许使用已注册的三个飞书群聊只读工具。
- 知识网关不加载任何 MCP 服务。
- 启动项目 FastAPI 和 Vite 开发服务，并提供统一的启动、停止和状态检查脚本。
- 使用 `deploy/.env` 中现有的 DeepSeek 和 Hermes API 密钥，仅通过子进程环境变量传递。
- 自动化契约测试、Hermes 能力探针、真实对话和飞书只读验收。

### 不包含

- 不读取飞书私聊、附件或表情。
- 不向飞书发送、回复、转发、撤回或修改任何资源。
- 不把 `deploy/.env` 的密钥复制到其他配置文件、日志或工具结果中。
- 不启用通用 Shell、网络、文件写入或通用 `lark-cli` MCP 工具。
- 不改变生产 Compose 部署或远端正式环境。
- 不把知识网关和通用网关合并为同一 Profile。

## 方案选择

采用 Windows 本地双网关桥接：

- 通用网关复用 `D:\Replica1.0\hermes`，监听 `127.0.0.1:8642`。
- 知识网关使用独立的 `D:\Replica1.0\hermes\knowledge-home`，监听 `127.0.0.1:8643`。
- 两个网关复用同一个 Hermes 可执行文件和 DeepSeek 凭据，但使用不同的 `HERMES_HOME`、状态数据库、日志和工具配置。

不采用单网关方案，因为它会让知识会话获得飞书工具。不采用后端直接执行 Hermes CLI 的方案，因为它会绕过项目已经实现的状态化会话、SSE、停止运行和审批接口。

## 组件设计

### 通用 Hermes Profile

现有 `hermes/config.yaml` 保留 DeepSeek 模型和 `hermes-feishu-readonly` MCP 注册。新增 `platform_toolsets.api_server` 显式 allowlist，只包含 `hermes-feishu-readonly`。

因此，通过 HTTP API 创建的 Hermes Agent 只能看到：

- `list_feishu_groups`
- `read_feishu_group_messages`
- `search_feishu_group_messages`

CLI 或其他平台的工具配置不作为项目 AI 服务的授权来源。

### 知识 Hermes Profile

新增 `hermes/knowledge-home/config.yaml`，使用同一 DeepSeek 模型，并设置：

```yaml
platform_toolsets:
  api_server:
    - no_mcp
```

知识 Profile 不包含 `mcp_servers`、飞书插件或通用工具。它使用独立会话存储，避免通用对话和知识对话历史混用。

### 项目后端

不改写 `HermesHttpClient` 协议。启动 FastAPI 时通过进程环境注入：

```text
HERMES_USE_HTTP=true
HERMES_API_URL=http://127.0.0.1:8642
HERMES_KNOWLEDGE_API_URL=http://127.0.0.1:8643
HERMES_API_KEY=<deploy/.env 中的 HERMES_API_SERVER_KEY>
```

通用会话继续选择 `agent` backend，知识会话继续选择 `knowledge` backend。浏览器仍只调用现有 `/api/chat/*` 接口，不直接访问 Hermes 或持有 Hermes API 密钥。

### 本地运行脚本

新增：

- `deploy/scripts/start-local-ai.ps1`
- `deploy/scripts/stop-local-ai.ps1`
- `deploy/scripts/status-local-ai.ps1`

运行状态保存在已被忽略的 `deploy/.runtime/local-ai/`：

- `hermes-agent.pid`
- `hermes-knowledge.pid`
- `backend.pid`
- `frontend.pid`
- 对应 stdout/stderr 日志

启动顺序：

1. 解析并校验 `deploy/.env`，只读取 `DEEPSEEK_API_KEY`、可选 `DEEPSEEK_BASE_URL` 和 `HERMES_API_SERVER_KEY`。
2. 检查 `8000`、`8642`、`8643`、`5173` 是否空闲。发现既有监听器时报告 PID 并退出，不自动终止。
3. 必要时创建 `backend/.venv` 并安装后端依赖；必要时执行 `npm ci`。
4. 启动通用 Hermes，并等待 `http://127.0.0.1:8642/health`。
5. 启动知识 Hermes，并等待 `http://127.0.0.1:8643/health`。
6. 使用 SQLite 本地开发数据库执行 Alembic 迁移和 seed，然后启动 FastAPI。
7. 启动 Vite，并等待前端可访问。
8. 输出浏览器地址、API 地址和四个组件状态，不输出任何密钥。

停止脚本只处理 PID 文件记录且仍与预期可执行文件匹配的进程。PID 已复用或进程身份不匹配时只清理陈旧 PID 文件，不结束该进程。

## 凭据与安全边界

- `deploy/.env` 是唯一的项目本地密钥真源，已由 `deploy/.gitignore` 排除。
- 启动脚本不会生成新的明文密钥副本。
- DeepSeek 密钥仅注入两个 Hermes 子进程。
- Hermes API 密钥仅注入两个 Hermes 子进程和 FastAPI 子进程。
- Vite 和浏览器不获得上述密钥。
- 飞书用户令牌继续由 Lark CLI 本机凭据库管理；Hermes 配置不保存访问令牌或刷新令牌。
- 两个 Hermes API Server 只监听 `127.0.0.1`，即使配置了 API 密钥也不对局域网开放。
- 飞书 MCP 保持群 ID allowlist、固定 `--as user`、`--chat-type group`、无附件下载和无反应读取限制。

## 错误处理

- 缺少或仍为占位值的密钥：启动前失败，不创建进程。
- 端口被占用：报告端口和监听 PID，不停止已有服务。
- 任一组件健康检查超时：停止本次启动脚本创建的组件，保留日志用于诊断。
- Hermes 模型调用失败：项目后端返回现有的上游失败事件，不回退到兼容 Mock，避免伪装为真实回答。
- 飞书用户授权失效或缺少 scope：工具返回 `user_auth_required` 或 `missing_scope`，对话可以解释错误，但不得回退到 bot 身份。
- 知识网关出现 MCP 工具：能力验收失败，项目不进入可用状态。

## 测试与验收

### 自动化测试

- 配置测试：通用 Profile 的 API Server 只 allowlist 飞书 MCP；知识 Profile 明确 `no_mcp`。
- 启动脚本契约测试：密钥不落盘、不输出；端口冲突 fail closed；PID 身份校验后才停止。
- 后端回归：现有 Hermes HTTP adapter、chat session、SSE、停止和审批测试通过。
- 飞书 MCP 回归：三个工具注册、群聊 allowlist、错误归一化、凭据脱敏测试通过。

### 真机验收

1. `8642/health` 与 `8643/health` 均返回成功。
2. 通用网关能力面包含且只包含三个飞书只读 MCP 工具。
3. 知识网关能力面不包含 MCP 工具。
4. `backend/scripts/probe_hermes.py` 对两个网关完成健康和状态化接口探测。
5. 通过项目 API 登录、创建通用会话、发送普通问题，收到来自真实 Hermes/DeepSeek 的流式回答。
6. 通过同一项目会话要求列出当前账户群聊，Hermes 调用飞书 MCP 并返回群列表摘要。
7. 请求读取一个群最近一页消息或执行限定关键词搜索，结果可返回且不发送任何飞书消息。
8. 浏览器打开 `http://127.0.0.1:5173`，AI 工作台完成普通对话和飞书只读查询。

## 完成标准

- `status-local-ai.ps1` 显示四个组件健康。
- 项目 AI 工作台不再使用兼容 Mock。
- 普通对话、状态化历史和 SSE 均通过项目后端工作。
- 通用会话可以调用飞书群聊只读工具。
- 知识会话不能调用飞书或其他 MCP 工具。
- 没有密钥写入新增文件、日志、前端响应或测试快照。
