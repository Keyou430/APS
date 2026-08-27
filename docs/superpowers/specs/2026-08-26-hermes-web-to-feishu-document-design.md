# Hermes 网络检索写入飞书文档设计

## 目标

让本地 AI 平台的 Agent Hermes 能在用户明确要求时完成“网络检索 -> 整理正文 -> 写入飞书文档”。写入内容是正常的飞书文档正文，来源 URL 仅作为可核验参考，不替代正文。

## 范围

- Agent Hermes API 服务启用 Hermes 原生 `web` 工具集和已有的 `hermes-lark-cli` MCP。
- 网络检索使用 `web_search` 和 `web_extract`，将来源 URL、标题和检索时间保留在平台已有的 Web evidence 事件中。
- 飞书文档写入通过 `lark_cli_execute` 调用受控的 `lark-cli docs +create` 或 `docs +update`，强制使用已授权的用户身份。
- 未指定目标文档时创建新文档；提供文档 URL 或 token 时更新该文档。
- 创建或更新动作必须来自用户明确的“写入/创建/更新飞书文档”意图。仅请求检索、讨论或生成草稿时不得写入。

## 非范围

- 不启用 Agent 的终端、文件、浏览器、代码执行或其他无关工具集。
- 不向 Knowledge Hermes 开放网络搜索、MCP 或飞书能力。
- 不增加每个飞书接口一个 MCP 工具；维持三个受控 lark-cli 控制工具。
- 不绕过飞书用户可见范围、应用 scope、文档权限或 lark-cli 的高风险确认门禁。

## 架构

Agent API profile 的 `platform_toolsets.api_server` 从仅 `hermes-lark-cli` 扩展为 `web` 和 `hermes-lark-cli`。现有后端已能消费并持久化 `tool.web_search` 证据事件，因此不为检索结果另建数据通路。

检索结果经模型整理为带标题和正文的文档 XML。正文应表达结论、背景、要点和必要的引用；末尾追加“参考来源”段落，列出实际检索得到的 URL。随后由现有 lark-cli MCP 调用创建或更新文档，并将返回的文档地址作为聊天结果返回。

## 安全和失败处理

- Web 工具必须在实际 Agent API 服务的 `/v1/toolsets` 中显示为 enabled；仅 CLI 全局目录显示可用不算生效。
- 若无可用 Web provider 或搜索未获得有效来源，助手必须说明检索不可用，不得编造来源或写入声称来自网络的结论。
- 用户没有表达写入意图时，只返回草稿和来源，不调用飞书写入。
- `docs +create` 和 `docs +update` 的普通正文写入按用户意图执行；若 lark-cli 将某次操作标为高风险，保留既有一次性 approval ticket 和显式确认流程。
- 飞书权限、文档可见性或 OAuth scope 不足时，返回经过脱敏的错误说明，不切换到 bot 身份或扩大权限。

## 验收标准

1. 运行中 Agent 网关的 `/v1/toolsets` 同时显示 `web` 和 `hermes-lark-cli` 可用；Knowledge 网关保持无 Web 和无 MCP。
2. 通过 API 聊天请求可以产生并显示经过验证的 `tool.web_search` 来源事件。
3. 用户明确要求“搜索并写入飞书文档”时，Agent 创建或更新包含正常文字正文和来源列表的飞书文档。
4. 仅请求“搜索”或“起草”时，Agent 不创建、不更新飞书文档。
5. 自动化测试覆盖配置白名单、正文写入意图约束和现有 Web evidence 契约；不在测试中创建或更新真实飞书资源。
