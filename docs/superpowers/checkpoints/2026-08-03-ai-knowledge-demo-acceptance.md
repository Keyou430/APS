# AI 与知识库演示验收检查点

日期：2026-08-03

环境：192.168.3.131（测试服务器）

分支：`codex/hermes-platform-integration`

范围：平台 AI 工作台、知识上传与解析、授权检索、回答引用和知识详情；非生产环境

## 验收结论

- AI 与知识库演示链路已在真实 Hermes HTTP 模式和同一 Browser 登录会话中完成。
- 知识轮次只在 Hermes 返回可关联的非空终态消息时完成；空白输出、无终止事件和关联失败不会再显示为空白成功回答。
- 会话刷新后可从服务端历史恢复检索模式、轮次状态、引用和当前不可用来源计数；未引入数据库迁移。
- 对话页具备明确的检索状态、回答失败态和独立引用区；知识详情页具备资源摘要、正文、权限和活动记录四个层次。
- 文件解析后的 chunk 正文可在详情页预览；用户停用的 PostgreSQL 行锁已限定到明确表，避免外连接锁错误。

## 交付提交

- `88c269e`：拒绝空 Hermes 回答并收紧轮次终态。
- `70b9c1e`：固定知识上下文事件顺序并恢复刷新态。
- `8e133ee`：前端 store 恢复知识轮次状态。
- `ac760aa`：优化知识对话工作区。
- `a2367a3`：优化知识详情工作区。
- `ca71964`：限定 PostgreSQL 用户停用行锁范围。
- `66294ed`：使用已解析 chunk 正文补全文件内容预览。

## 本地验证

- 后端完整回归：`204 passed in 30.24s`。
- Web 完整回归：`36 passed` test files、`169 passed` tests。
- Web lint：通过，退出码 0。
- Web production build：通过，退出码 0；保留既有的单 chunk 大于 500 kB 警告。
- 工作区边界：除受保护的 `.superpowers/` 外无待提交文件；未提交 `.secret/`、runtime 报告、上传内容或凭据。

## 测试服务器部署

- 使用独立 clean release 目录部署，没有覆盖远端已有脏工作区。
- Web 和完整 Hermes 栈来自 `ca71964`；仅包含后端预览修复的 API 来自 `66294ed`。
- `api`、`web`、`rag-worker`、`hermes`、`hermes-knowledge`、`db` 均为 healthy。
- API 使用 Hermes HTTP，知识请求指向独立 tool-less `hermes-knowledge:8643` 服务。
- 外部 guest 功能保持关闭；未开启外部投递、匿名分享或生产入口。
- 本轮没有新增或执行生产迁移。

## 固定消息关联探针

通过公共 API 创建一次性内部账号、授权来源和知识会话，显式触发 ingest，并使用该次请求的固定 run/message id 验证关联，未使用“最新消息”猜测：

- `session_id=63`
- `turn_id=11`
- `run_id=run_afe0f999d52048daa39f30737d8031fb`
- `assistant_message_id=36`
- Hermes history 连续读取 3 次均关联到相同消息。
- 回答长度 55 个字符，内容非空；持久化引用 1 条，且只引用该轮授权来源。
- 探针结束后 session、entry 和临时 active user 均清理为 0。

## Browser 实际验收

- 在同一认证 Browser 会话内进入工作台、AI 问答入口和知识会话，没有出现门户 404。
- 上传合成文本后，进度从 20% 到 100%，资源进入 `ready`；详情页可读取解析正文和唯一演示标记。
- 详情页资源摘要包含类型、状态、可见性、获取方式、所有者和更新时间；正文、访问权限、活动记录均可切换，活动记录包含成功的 upload/ingest 事件。
- 新建知识会话后选择恰好 1 个来源。提问时先显示“正在检索授权知识”，完成后显示“已检索 1 个来源”和“当前不可用来源 0”。
- AI 返回非空 grounded answer，正文包含上传内容中的唯一标记；独立引用区显示 1 项，引用可打开对应知识详情。
- 1440、1024、768、390 四档宽度均无横向溢出或控件重叠；390 宽度下详情抽屉覆盖完整可视宽度。
- 页面 console error/warn 为空。最终保留一个 `deliverable` tab，没有关闭最后一个 tab，也没有调用空 keep 的 finalize。
- Browser 验收结束后删除 1 个会话、1 个知识资源并停用 1 个临时账号；数据库复核对应活动数据均为 0。

## 实施中发现并修复的问题

- PostgreSQL 对含 eager outer join 的用户查询直接 `FOR UPDATE` 会返回 500；现已通过明确锁定 `User`、`OrganizationMembership` 和 `Role` 表修复，并增加 SQL 编译契约测试。
- 文件型知识正文存放在 `KnowledgeChunk` 而非 entry content；详情预览现按授权和 ordinal 读取解析正文，并设置 12,000 字符上限。
- 首次冷启动 Web 全量测试中，3 个动态导入契约测试超过 Vitest 默认 5 秒；相同用例单独运行通过，完全相同的全量命令复跑为 169/169。未以放宽超时掩盖契约问题。

## 保留门禁与已知风险

- 生产数据库迁移、正式 guest/email delivery、匿名分享和真实外部用户仍需单独授权。
- Web 主 bundle 仍有大于 500 kB 的构建警告；不影响本轮功能演示，但后续应按路由或功能域拆包。
- 保留的 Browser deliverable tab 是验收后的缓存画面；临时账号和演示数据已清理，刷新后不再具备访问权限。
