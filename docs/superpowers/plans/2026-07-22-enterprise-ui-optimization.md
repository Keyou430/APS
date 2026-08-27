# 云枢企业智能平台 UI 优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变后端契约、工作台网格业务结构和兼容标识的前提下，完成云枢品牌替换、知识 AI 会话化、平台固定视口工具栏和工作台/知识库视觉优化。

**Architecture:** 以 `brand.ts` 集中管理用户可见品牌；保留现有服务、Mock 数据流和 `useAIQuery`，由 `knowledgeStore` 持久化资源筛选、视图和 AI 会话，新增一个对话视图组件承载会话 CRUD。平台页继续复用 `PlatformPageLayout`，通过 `uiStore` 持久化工具栏模式，桌面使用 hover/固定状态，移动使用抽屉；工作台只调整页面与 Widget 样式。

**Tech Stack:** React 19、Arco Design、Zustand persist、CSS Modules、Vitest、现有 Vite/Playwright 配置。

---

### Task 1: 品牌配置与确定性 Mock

**Files:**
- Create: `web-platform/src/config/brand.ts`
- Modify: `web-platform/index.html`, `web-platform/src/components/AppLayout.tsx`, `web-platform/src/pages/LoginPage.tsx`, `web-platform/src/pages/CalendarPage.tsx`
- Modify: `web-platform/src/mock/runtime.ts`, `web-platform/src/mock/handlers/knowledge.ts`
- Modify: `web-platform/src/mock/generators/enterprise.ts`, `web-platform/src/mock/generators/knowledge.ts`, `web-platform/src/shared/types/mock.ts`
- Test: `web-platform/src/mock/mockServices.test.ts`, `web-platform/src/mock/knowledgeExtended.test.ts`

- [ ] **Step 1: 先写确定性行为断言**：将 Mock 测试改为查询 `云枢`/`yunshu.example`，并新增一次 `configureMockRuntime({ errorRate: 1, failuresRemaining: 1 })` 后仍正常返回、延迟仍被调用的断言；运行 `npm exec vitest run src/mock/mockServices.test.ts src/mock/knowledgeExtended.test.ts`，先确认旧实现失败。
- [ ] **Step 2: 添加集中式配置并替换可见内容**：`brand.ts` 导出 `{ fullName: '云枢企业智能平台', shortName: '云枢', exampleDomain: 'yunshu.example' }`；页面标题、导航、登录、日历、企业/知识 Mock、legacy Mock 邮箱和链接使用配置或对应值，`hermes-*` key、`__HERMES_*` 全局名、API 字段和历史 id 保持不变。
- [ ] **Step 3: 移除 Mock 失败分支**：`withMockNetwork` 和 `withAIQueryDelay` 只读取 `random` 计算延迟并调用 `sleep`，不根据 `errorRate`/`failuresRemaining` 抛错或递减；兼容字段和校验继续保留。
- [ ] **Step 4: 运行同一组 Vitest，确认正常数据、延迟和现有错误 UI 契约均可继续使用。**

### Task 2: 会话 Store 与 AI 查询持久化（TDD）

**Files:**
- Modify: `web-platform/src/stores/knowledgeStore.ts`
- Modify: `web-platform/src/stores/__tests__/knowledgeStore.test.ts`, `web-platform/src/pages/KnowledgePage.test.tsx`
- Modify: `web-platform/src/hooks/useAIQuery.ts`, `web-platform/src/hooks/__tests__/useAIQuery.test.tsx`

- [ ] **Step 1: 先写失败测试**：覆盖默认 3 个示例会话、`resources/chat` 切换、创建/切换/重命名、删除当前会话选择邻近会话、首问标题截取 20 个字符、消息追加和 persist rehydrate；运行 `npm exec vitest run src/stores/__tests__/knowledgeStore.test.ts src/hooks/__tests__/useAIQuery.test.tsx src/pages/KnowledgePage.test.tsx`，确认新增行为失败。
- [ ] **Step 2: 实现 Store**：保留 `KnowledgeAIConversation` 历史类型和 `hermes-knowledge` key，增加 `aiSessions`、`activeSessionId`、`knowledgeView` 及对应 action；首次无持久化数据时生成固定的 3 个示例会话，已有 `aiConversations` 数据在 `merge` 中迁移，删除/空会话时 active id 归零。
- [ ] **Step 3: 最小适配 `useAIQuery`**：增加按会话 id 重置初始消息的可选参数和回答完成回调；保留现有流式分段、引用和 retry 行为，回答完成时把最终内容/引用交给当前会话持久化。
- [ ] **Step 4: 运行上述测试，确认红绿循环完成且旧 hook 行为不回归。**

### Task 3: 知识库资源/AI 双视图

**Files:**
- Create: `web-platform/src/components/knowledge/KnowledgeAIView.tsx`, `web-platform/src/components/knowledge/KnowledgeAIView.module.css`
- Modify: `web-platform/src/components/knowledge/AIPanel.tsx`, `web-platform/src/components/knowledge/AIPanel.module.css`
- Modify: `web-platform/src/pages/KnowledgePage.tsx`, `web-platform/src/pages/KnowledgePage.module.css`

- [ ] **Step 1: 资源视图保留现有分类、搜索、筛选、上传、分页、批量操作、详情和筛选状态，只把 `AIPanel` 改成“进入知识 AI”入口；入口调用 `ensureActiveSession` 后切到 `chat`。**
- [ ] **Step 2: 新增对话视图**：桌面显示语义化会话列表与消息区；支持新建、切换、重命名、确认删除、首次提问自动标题、流式回答和引用；顶部提供“退出对话”，返回资源视图而不重置已有本地筛选状态。
- [ ] **Step 3: 移动端将会话列表放入可开关 Drawer，消息/输入区只在内部滚动；所有图标按钮补 `aria-label`/`title`，长标题和 390px 宽度不溢出。**
- [ ] **Step 4: 运行受影响 Vitest，并用现有 Mock 服务验证入口、退出和会话状态变化。**

### Task 4: 飞书/钉钉固定视口与边缘工具栏

**Files:**
- Modify: `web-platform/src/shared/types/platform.ts`, `web-platform/src/stores/uiStore.ts`
- Modify: `web-platform/src/components/platform/PlatformPageLayout.tsx`, `web-platform/src/components/platform/PlatformPageLayout.module.css`
- Modify: `web-platform/src/components/platform/PlatformPageLayout.test.tsx`, `web-platform/tests/frontend-refactor-platform.spec.ts`

- [ ] **Step 1: 先补 Store/组件失败断言**：旧持久化数据自动得到 `toolbarMode: 'auto'`，固定/手动收起可保存；组件默认只显示窄工具栏，hover/固定/收起和移动按钮切换展开层，页面高度不触发 document 滚动。
- [ ] **Step 2: 增加 `toolbarMode: auto | pinned | collapsed` 并给 Zod schema 默认值，确保旧 `hermes-ui` 数据可解析；操作仅写平台自己的 `uiStore` 状态。**
- [ ] **Step 3: 将访问设置、最近访问、通知放进边缘工具栏分组，桌面 hover 临时展开、固定后保持展开、收起优先级高于 hover；移动用按钮打开覆盖式 Drawer，嵌入区保持剩余高度并独立滚动。**
- [ ] **Step 4: 运行平台 Vitest，随后用现有平台 E2E/短浏览器烟测覆盖固定、hover、移动 Drawer、iframe 状态和无 window scroll。**

### Task 5: 工作台与知识库样式收束

**Files:**
- Modify: `web-platform/src/pages/WorkspacePage.module.css`
- Modify: `web-platform/src/components/dashboard/Dashboard.module.css`
- Modify: `web-platform/src/pages/KnowledgePage.module.css`

- [ ] **Step 1: 只在现有容器和 Widget frame 上调整中性背景、细边框、低阴影、标题栏、内边距、工具栏边界和响应式换行；不改 `DashboardGrid`、7 个 Widget、注册表、拖拽缩放或持久化。**
- [ ] **Step 2: 用 1440px/390px 浏览器视口检查工作台和知识资源页，确认无水平溢出、控件/长标题不重叠，亮暗主题均可读。**

### Task 6: 总体验证与本地提交

**Files:**
- No backend changes; do not stage `web-platform/src/stores/chatStore.ts` or `.superpowers/`.

- [ ] **Step 1: 运行 `npm run build`、`npm run lint` 和所有受影响 Vitest；记录任何既有失败或未验证项。**
- [ ] **Step 2: 启动 `web-platform` dev server，用真实浏览器短测品牌、工作台样式、知识 AI 进出/会话切换、平台固定布局/工具栏展开；截图放在 repo 外，不新增大规模 Playwright 套件。**
- [ ] **Step 3:** 运行 `rg -n -i 'Hermes' web-platform/src web-platform/index.html`，逐项区分用户可见文本与允许的兼容标识，确认用户可见界面无 Hermes；检查 `git diff -- backend`、`git status`，确认 backend 无 diff 且 `chatStore.ts` 未暂存。
- [ ] **Step 4: 只暂存本轮明确前端文件和计划文件，创建一个边界清晰的本地提交；不推送、不合并、不创建 PR。**
