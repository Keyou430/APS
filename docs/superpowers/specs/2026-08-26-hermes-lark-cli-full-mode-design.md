# Hermes lark-cli 完整业务模式设计

## 目标

将 Hermes 从当前仅支持三个飞书群聊只读工具的 MCP，升级为可调用 lark-cli 完整飞书业务命令面的受控 MCP。模型可以读取和修改已授权用户有权访问的飞书业务资源，但高风险操作必须经过 lark-cli 的确认门禁；不开放本机 Shell、账号密钥管理或任意文件系统能力。

## 当前问题

当前 `hermes-feishu-readonly` MCP 只注册：

- `list_feishu_groups`
- `read_feishu_group_messages`
- `search_feishu_group_messages`

它可以安全地调用 lark-cli，但文档、任务、日历、邮件、知识库等业务域没有暴露给 Hermes。lark-cli 本身也没有可直接注册到 Hermes 的 `mcp` 子命令，因此必须由一个受控适配层完成工具声明、参数校验、进程调用和错误处理。

## 设计决策

### 1. 使用通用业务命令 MCP

创建 `hermes-lark-cli` FastMCP 服务，替换 `hermes-feishu-readonly`。服务提供三个工具：

| 工具 | 用途 |
| --- | --- |
| `lark_cli_help` | 查询 lark-cli 根命令或业务域帮助。只执行帮助命令，不访问飞书。 |
| `lark_cli_schema` | 查询一个已注册 OpenAPI 方法的参数、权限和风险描述。只执行 schema 命令，不访问飞书。 |
| `lark_cli_execute` | 以参数数组执行一个受控 lark-cli 业务命令。 |

工具使用参数数组，不接受 Shell 命令字符串，不调用 `cmd.exe`、PowerShell 或 `sh`。例如：

```json
{
  "argv": ["task", "+get-my-tasks", "--format", "json"]
}
```

### 2. 允许的命令面

`lark_cli_execute` 允许 lark-cli 的飞书业务域：

```text
approval apps attendance base calendar contact docs drive event im mail
markdown mindnotes minutes note okr sheets slides task vc whiteboard wiki
```

允许各业务域的 shortcut、typed API resource 和原生只读 schema 查询。`api` 原始 HTTP escape hatch、`auth`、`config`、`profile`、`update`、`doctor`、`skills`、`help` 等 CLI 管理命令不由模型执行。身份授权仍由操作者在终端完成。

### 3. 高风险操作确认

执行工具不得静默添加 `--yes`。流程如下：

1. 第一次执行原始参数，不附加 `--yes`；
2. lark-cli 返回 exit code 10 和 `confirmation_required` 时，MCP 返回结构化确认信息，包括 action、risk 和原始参数摘要；
3. 服务生成短期一次性 approval id；
4. 用户明确确认后，模型调用 `lark_cli_execute` 携带 approval id 和 `confirmed: true`；
5. 服务只对匹配的未过期 approval id 追加 `--yes`，并执行一次；
6. 任何参数变化、重复使用、过期或缺少确认都拒绝执行。

高风险范围包括发送、回复、转发、编辑、删除、上传、创建任务、完成任务、修改权限和原始 API 写入。普通只读命令不需要确认。lark-cli 自身的风险判断是最终门禁，MCP 不自行降低风险等级。

### 4. 文件和输出安全

- 子进程通过 `asyncio.create_subprocess_exec` 启动，禁止 Shell 解释。
- 所有参数必须是非空字符串，禁止 NUL 字符和超长参数。
- 对 `--file`、`--output`、`--output-dir` 等本地路径参数只接受项目工作目录下的相对路径；不接受磁盘根路径、用户目录或路径穿越。
- stdout/stderr 设置总大小上限，超限失败关闭。
- 返回和错误诊断统一脱敏 access token、refresh token、app secret、authorization、password、JWT 等凭据形态。
- 日志只记录业务域、非敏感参数摘要、退出状态和关联 id，不记录完整凭据或完整敏感内容。

### 5. Hermes 配置边界

Agent Hermes 的 API-server toolset 只连接 `hermes-lark-cli`。Knowledge Hermes 保持 `no_mcp`，不允许调用飞书。

旧 `hermes-mcp` 插件不再启用，避免其知识检索、JSON、Base64 和时间工具与本次飞书工具面混在一起。Hermes 原生 `feishu-platform` 不作为用户 OAuth 数据读取通道；它需要单独的机器人事件配置，保持关闭或不参与本功能。

### 6. 身份与授权

MCP 始终执行 `--as user` 语义下的用户业务请求，复用本机 lark-cli 凭据存储。MCP 不实现 OAuth 登录、退出登录、凭据刷新或应用配置。缺 scope、token 过期和用户无权访问资源时，返回可操作的结构化诊断，不伪造成功结果。

## 数据流

```text
Hermes model
  -> hermes-lark-cli MCP over stdio
  -> argv validation + command/risk policy
  -> lark-cli native executable via exec (no shell)
  -> Feishu OpenAPI using local user authorization
  -> bounded, redacted JSON result
```

## 错误契约

MCP 工具统一返回以下错误类别：

- `invalid_command`：业务域或参数结构不允许；
- `confirmation_required`：lark-cli 要求高风险确认；
- `confirmation_invalid`：approval id 不匹配、过期或已使用；
- `user_auth_required`：用户 OAuth 缺失或失效；
- `missing_scope`：应用或用户缺少 scope；
- `permission_denied`：当前用户无权访问资源；
- `cli_unavailable`、`timeout`、`output_too_large`、`invalid_json`：本地执行失败。

错误响应不包含 token、secret、完整命令环境或未经限制的 stderr。

## 测试验收

自动化测试必须覆盖：

- 三个工具注册结果；
- 业务域 allowlist 和管理命令拒绝；
- 参数数组执行不经过 Shell；
- schema/help 不触发业务 API；
- exit code 10 转换为确认请求；
- approval id 一次性、过期和参数绑定；
- `--yes` 未经服务确认时拒绝；
- 本地路径限制、输出大小限制和凭据脱敏；
- scope、认证和权限错误归一化；
- Agent 只连接 `hermes-lark-cli`，Knowledge 无 MCP；
- lark-cli 实际只读命令和一个高风险写命令的人工验收，确认没有静默写入。

## 非目标

- 不向 Hermes 暴露任意 Shell 或原始 OpenAPI escape hatch；
- 不自动完成 OAuth 授权；
- 不绕过飞书应用 scope、用户可见性或租户权限；
- 不承诺读取账号中飞书 API 不返回或当前用户无权看到的全部历史数据。
