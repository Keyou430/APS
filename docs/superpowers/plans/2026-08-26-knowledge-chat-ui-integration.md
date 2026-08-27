# 知识库对话前端接入实施计划

> **供执行代理使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施。所有步骤使用复选框跟踪。

**目标：** 接通 React 对话页与现有知识会话、知识范围和引用接口，让用户可以通过对话框对授权知识库进行问答。

**架构：** 保留后端现有契约，由 `ChatPage` 统一承载普通对话和知识问答，但按 `surface` 隔离会话、缓存和知识范围。`KnowledgeService` 只负责知识列表、引用重新授权和内容预览；消息发送继续使用现有 SSE 服务，不在消息体中恢复旧版 `source_ids`。

**技术栈：** React 19、TypeScript、Vitest、Testing Library、现有 Chat/Knowledge API Service、SSE。

---

## 文件结构

- 修改 `web-platform/src/pages/ChatPage.tsx`：增加双模式会话、知识范围、引用和预览交互。
- 修改 `web-platform/src/pages/ChatPage.test.tsx`：覆盖知识会话、范围、引用、错误和普通会话回归。
- 修改 `web-platform/src/app/App.tsx`：向 `ChatPage` 注入现有 `KnowledgeService`。
- 修改 `web-platform/src/pages/KnowledgePage.tsx`：增加知识问答入口。
- 修改 `web-platform/src/pages/KnowledgePage.test.tsx`：验证入口链接。
- 修改 `web-platform/styles.css`：补充模式控制、知识范围和引用预览的响应式样式。

当前 `D:\Replica1.0` 没有 `.git` 元数据，因此任务中的提交动作无法执行。每个任务仍保持独立测试边界；如果后续恢复 Git 元数据，再按任务分别提交。

### 任务 1：隔离普通会话与知识会话

**文件：**

- 修改：`web-platform/src/pages/ChatPage.test.tsx`
- 修改：`web-platform/src/pages/ChatPage.tsx`
- 修改：`web-platform/src/app/App.tsx`

- [ ] **步骤 1：补充知识模式失败测试**

在 `ChatPage.test.tsx` 增加 `KnowledgeService` 测试桩，并添加以下行为测试：

```tsx
it("loads and creates knowledge sessions, then initializes all-visible scope", async () => {
  const service = chat({
    listSessions: vi.fn(async () => ({ items: [] })),
    createSession: vi.fn(async () => ({
      id: 2,
      title: "新会话",
      surface: "knowledge",
      knowledge_scope: "none",
      source_ids: [],
    })),
    setKnowledgeScope: vi.fn(async () => ({
      knowledge_scope: "all_visible",
      source_ids: [],
    })),
  });
  const user = userEvent.setup();

  render(
    <ChatPage
      cache={cache()}
      initialSurface="knowledge"
      knowledgeService={knowledge()}
      organizationId={7}
      service={service}
      stream={stream()}
    />,
  );

  expect(service.listSessions).toHaveBeenCalledWith({ surface: "knowledge" });
  await user.click(await screen.findByRole("button", { name: "新建会话" }));
  expect(service.createSession).toHaveBeenCalledWith({
    surface: "knowledge",
    title: "新会话",
  });
  expect(service.setKnowledgeScope).toHaveBeenCalledWith("2", {
    mode: "all_visible",
    source_ids: [],
  });
});
```

同时保留并更新原有普通对话测试，明确断言 `surface: "agent"`，证明修复没有改变普通会话。

- [ ] **步骤 2：运行测试并确认按预期失败**

运行：

```powershell
npx vitest run src/pages/ChatPage.test.tsx
```

预期：失败原因是 `ChatPage` 尚无 `initialSurface`、`knowledgeService` 属性，且只加载 `agent` 会话。

- [ ] **步骤 3：实现会话模式和模式级缓存**

在 `ChatPage.tsx` 中加入明确类型，并让映射保留后端字段：

```tsx
type ChatSurface = "agent" | "knowledge";
type KnowledgeScopeMode = "all_visible" | "selected" | "none";
type Session = {
  id: string;
  title: string;
  surface: ChatSurface;
  knowledgeScope: KnowledgeScopeMode;
  sourceIds: number[];
  createdAt: string;
  updatedAt: string;
};

type ChatPageProps = {
  cache: PageCache;
  initialSurface?: ChatSurface;
  knowledgeService: KnowledgeService;
  organizationId: number | null;
  service: ChatService;
  stream: ChatStreamService;
};
```

初始化模式时读取显式属性；未传属性时，仅当当前 URL 含 `surface=knowledge` 才进入知识模式：

```tsx
function surfaceFromLocation(): ChatSurface {
  if (typeof window === "undefined") return "agent";
  return new URLSearchParams(window.location.search).get("surface") === "knowledge"
    ? "knowledge"
    : "agent";
}
```

使用 `service.listSessions({ surface })` 加载当前模式会话，并将缓存键改为：

```tsx
const cacheKey = useMemo(() => ["chat", "sessions", surface], [surface]);
```

新建知识会话后立即执行：

```tsx
const scope = await service.setKnowledgeScope(created.id, {
  mode: "all_visible",
  source_ids: [],
});
```

只有范围保存成功后，才把本地会话标记为 `all_visible`。切换模式时调用 `abortRef.current?.abort()`，清空当前消息和选中会话，再由现有加载流程读取另一种会话。

在 `App.tsx` 将现有运行时知识服务传入：

```tsx
<ChatPage
  cache={appRuntime.auth.cache}
  knowledgeService={appRuntime.services.knowledge}
  organizationId={organizationId}
  service={appRuntime.services.chat}
  stream={appRuntime.services.chatStream}
/>
```

- [ ] **步骤 4：运行定向测试并确认通过**

运行：

```powershell
npx vitest run src/pages/ChatPage.test.tsx src/app/App.test.tsx
```

预期：两个测试文件全部通过，普通会话和知识会话分别使用正确的 `surface`。

### 任务 2：保存服务器持有的知识范围

**文件：**

- 修改：`web-platform/src/pages/ChatPage.test.tsx`
- 修改：`web-platform/src/pages/ChatPage.tsx`

- [ ] **步骤 1：补充指定知识范围失败测试**

添加测试，构造一个 `knowledge_scope: "all_visible"` 的知识会话和两个知识条目，切换为“指定知识”，选择“员工手册”，点击“应用知识范围”：

```tsx
expect(service.setKnowledgeScope).toHaveBeenCalledWith("1", {
  mode: "selected",
  source_ids: [11],
});
```

再添加一个 `knowledge_scope: "none"` 会话测试，断言消息输入框和发送按钮不可用，并显示“请先设置知识范围”。

- [ ] **步骤 2：运行测试并确认按预期失败**

运行：

```powershell
npx vitest run src/pages/ChatPage.test.tsx -t "knowledge scope"
```

预期：找不到知识范围控件，或者 `setKnowledgeScope` 没有被调用。

- [ ] **步骤 3：实现知识条目加载和范围草稿**

知识模式加载时调用：

```tsx
const payload = await knowledgeService.listEntries();
const entries = items(payload).map(mapKnowledgeEntry);
```

为当前会话维护 `scopeMode` 和 `draftSourceIds`。选择会话时，从该会话已确认的 `knowledgeScope` 和 `sourceIds` 恢复草稿。范围区域使用原生单选框和复选框，提供：

```tsx
<fieldset aria-label="知识范围">
  <label><input type="radio" value="all_visible" />全部可见知识</label>
  <label><input type="radio" value="selected" />指定知识</label>
</fieldset>
```

当模式为 `selected` 时展示知识条目复选框。选择第 51 条时阻止更新并显示“最多选择 50 条知识”。点击“应用知识范围”后调用：

```tsx
await service.setKnowledgeScope(selectedId, {
  mode: scopeMode,
  source_ids: scopeMode === "selected" ? draftSourceIds : [],
});
```

调用成功后更新 `sessions` 中当前会话的已确认范围；失败时从当前会话恢复草稿并显示错误。以下条件为真时禁用消息输入和发送：

```tsx
const knowledgeScopeUsable =
  surface === "agent" ||
  activeSession?.knowledgeScope === "all_visible" ||
  (activeSession?.knowledgeScope === "selected" && activeSession.sourceIds.length > 0);
```

- [ ] **步骤 4：运行测试并确认通过**

运行：

```powershell
npx vitest run src/pages/ChatPage.test.tsx
```

预期：知识范围测试和原有聊天测试全部通过。

### 任务 3：展示并重新授权知识引用

**文件：**

- 修改：`web-platform/src/pages/ChatPage.test.tsx`
- 修改：`web-platform/src/pages/ChatPage.tsx`

- [ ] **步骤 1：补充流式引用和历史引用失败测试**

添加流式事件测试数据：

```tsx
const response = {
  ok: true,
  text: async () => [
    'event: knowledge.context\ndata: {"turn_id":9,"mode":"hybrid","citations":[{"ordinal":0,"entry_id":11,"title":"员工手册"}]}',
    'event: response.output_text.delta\ndata: {"delta":"请假需要提前申请。"}',
    'event: response.completed\ndata: {}',
  ].join("\n\n"),
};
```

发送消息后断言出现“知识来源”和“员工手册”。点击引用后断言调用顺序和参数：

```tsx
expect(knowledgeService.resolveCitation).toHaveBeenCalledWith("9", 0);
expect(knowledgeService.previewContent).toHaveBeenCalledWith(11);
expect(await screen.findByText("员工请假应提前提交申请。"))
  .toBeInTheDocument();
```

再用 `getMessages` 返回 `turn_id` 和 `citations`，证明刷新后的历史回答也能展示引用。

- [ ] **步骤 2：运行测试并确认按预期失败**

运行：

```powershell
npx vitest run src/pages/ChatPage.test.tsx -t "citation"
```

预期：当前页面只把引用保存在未知数组中，没有渲染或解析动作。

- [ ] **步骤 3：实现引用模型和预览流程**

增加明确的引用和消息字段：

```tsx
type Citation = {
  ordinal: number;
  entryId?: number;
  title: string;
  contentSha256?: string;
  sourceLocator?: string;
};

type Message = {
  // 保留现有字段
  turnId?: number;
  references?: Citation[];
  retrievalMode?: "hybrid" | "degraded_full_text" | "empty";
  rejectedSourceCount?: number;
};
```

`mapMessage` 映射历史 `turn_id` 和 `citations`；`knowledge.context` 事件映射 `turn_id`、`mode`、`rejected_source_count` 和 `citations`。

在 AI 回答下方渲染来源按钮。点击时先清空旧预览，再执行：

```tsx
const resolved = asObject(
  await knowledgeService.resolveCitation(String(message.turnId), citation.ordinal),
);
const entryId = readNumber(resolved.entry_id, NaN);
if (!Number.isFinite(entryId)) throw new Error("知识来源缺少条目 ID");
const preview = asObject(await knowledgeService.previewContent(entryId));
```

预览区域显示标题、正文和可用的来源定位信息，并提供“关闭来源预览”按钮。任一步失败时清空旧内容并显示“知识来源当前不可用”或接口返回的具体错误。

- [ ] **步骤 4：运行测试并确认通过**

运行：

```powershell
npx vitest run src/pages/ChatPage.test.tsx
```

预期：流式和历史引用测试全部通过，引用解析始终先于内容预览。

### 任务 4：增加入口、补齐样式并完成回归验证

**文件：**

- 修改：`web-platform/src/pages/KnowledgePage.test.tsx`
- 修改：`web-platform/src/pages/KnowledgePage.tsx`
- 修改：`web-platform/styles.css`

- [ ] **步骤 1：补充知识问答入口失败测试**

在 `KnowledgePage.test.tsx` 添加：

```tsx
expect(await screen.findByRole("link", { name: "进入知识问答" }))
  .toHaveAttribute("href", "/chat?surface=knowledge");
```

- [ ] **步骤 2：运行测试并确认按预期失败**

运行：

```powershell
npx vitest run src/pages/KnowledgePage.test.tsx -t "知识问答"
```

预期：页面没有“进入知识问答”链接。

- [ ] **步骤 3：实现入口和响应式样式**

在知识库页面标题操作区增加：

```tsx
<a className="button-link" href="/chat?surface=knowledge">进入知识问答</a>
```

在 `web-platform/styles.css` 增加限定在 `.chat-page` 下的样式，覆盖：

- 固定高度的双模式分段控制；
- 知识范围字段组和最多 50 条的可滚动来源列表；
- 引用按钮的键盘焦点、换行和窄屏布局；
- 引用预览的可读宽度和长文本换行；
- 390px 宽度下模式控制、会话栏、范围区和输入区不重叠。

不改变全局配色，不引入新组件库，不把页面区块包装成嵌套卡片。

- [ ] **步骤 4：运行全部 React 测试**

运行：

```powershell
npx vitest run
```

预期：所有 Vitest 测试通过，失败数为 0。

- [ ] **步骤 5：运行旧版契约回归测试**

运行：

```powershell
npm test
```

预期：Node 契约测试全部通过，特别是普通 AI 会话仍不发送旧版 `source_ids`。

- [ ] **步骤 6：运行代码检查**

运行：

```powershell
npm run lint
```

预期：ESLint 退出码为 0，无错误。

- [ ] **步骤 7：运行生产构建**

运行：

```powershell
npm run build
```

预期：TypeScript 构建和 Vite 生产构建退出码均为 0。

- [ ] **步骤 8：检查最终改动范围**

运行：

```powershell
Get-ChildItem -LiteralPath src/pages/ChatPage.tsx,src/pages/ChatPage.test.tsx,src/pages/KnowledgePage.tsx,src/pages/KnowledgePage.test.tsx,src/app/App.tsx,styles.css | Select-Object FullName,Length,LastWriteTime
```

预期：只有计划内前端文件和已确认的设计/计划文档发生变化；没有生成新的后端或数据库文件。
