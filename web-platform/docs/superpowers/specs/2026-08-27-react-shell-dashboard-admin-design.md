# React 壳层、驾驶舱与账号管理迁移设计

## 背景

当前前端是 Vite + React 19 + TypeScript 与 `index.html`、`app.js`、原生模块并存的混合架构。部分 pathname 已由 React 页面接管，但根路径驾驶舱和 admin 页面仍依赖原生 HTML/DOM 绑定。项目已有完整的 `styles.css`、服务层、认证运行时、缓存和测试基础。

本次迁移目标是建立唯一 React 壳层和 pathname 路由，优先迁移驾驶舱、完整 admin 页面和相关原生弹窗，同时保留现有 CSS 与视觉结构。迁移采用渐进式边界，未迁移页面暂时继续使用 legacy fallback。

## 目标与非目标

### 目标

- `/` 由 React 接管驾驶舱。
- `/admin` 由 React 接管完整账号管理页面。
- React 壳层统一承载顶部栏、主导航、侧栏、tab bar 和页面内容。
- 保留现有 DOM 结构语义、CSS class、尺寸、颜色、响应式规则和交互结果。
- 将驾驶舱和 admin 使用的原生弹窗迁移为 React 控制的共享弹窗。
- 以 `pathname` 作为页面路由唯一状态源，hash 仅用于页面内锚点。
- 未迁移功能继续通过明确的 legacy fallback 工作。

### 非目标

- 不一次性重写全部 legacy 页面。
- 不重新设计视觉主题，不直接套用 shadcn/ui 默认主题。
- 不凭空实现后端尚未提供正式契约的接口。
- 不在本阶段删除仍被 legacy 页面依赖的原生业务模块。

## 路由与壳层

React 新增 `AppShell`，复用现有以下 class 作为视觉和布局契约：

`app-shell`、`topbar`、`app-frame`、`layout`、`module-sidebar`、`content-area`、`tab-bar`、`main`、`sidebar-nav`、`nav-item`、`nav-main`、`side-link`、`sidebar-docs`、`sidebar-foot`。

迁移过程中，`index.html` 暂时保留未迁移 legacy 路由所需的业务 markup；React 接管的路由移除对应页面和弹窗 markup，改由 React 渲染。React 路由启用时，旧 `.app-shell/.app-frame` 不参与渲染，避免旧 DOM 与 React DOM 重叠。全部页面迁移完成后，`index.html` 再收敛为应用入口、全局样式和必要的静态资源宿主。

pathname 规则：

- `/`：React 驾驶舱。
- `/admin`：React 完整 admin 页面。
- 已有 React pathname：改为共用 `AppShell`，保持现有页面业务逻辑。
- 未迁移 pathname：继续使用 legacy fallback。
- `#admin`、`#workspace` 等历史入口转换为 `/admin`、`/`；其余 hash 只用于页面内滚动定位。

`legacy-entry.ts` 保留运行时初始化和 legacy fallback 的职责。React 路由不加载对应的 `app.js` 业务模块；legacy 路由仍按现有条件动态加载原生模块。

## 组件策略

项目当前没有 Tailwind、shadcn/ui 或 lucide 依赖，但已有自定义 CSS 组件和原生组件。第一阶段先建立本地 React UI 组件，使用现有 class；Tailwind/shadcn 作为组件组织和无障碍行为参考，不引入默认视觉主题。

| 现有界面 | React 组件边界 | 视觉策略 |
| --- | --- | --- |
| `.btn`、`.btn.primary`、`.btn-sm`、`.btn.icon-only` | `Button` | 保留现有 class、尺寸和状态 |
| `.card`、`.card-header`、`.card-title`、`.card-body` | `Card`、`CardHeader`、`CardTitle`、`CardBody` | 保留现有边框、阴影和标题装饰 |
| `.tabs/.tab`、`.admin-subtabs/.admin-subtab` | `Tabs` | React 管理选中状态，保留下划线样式 |
| `.data-table`、`table.js` | `DataTable` | 组件负责语义表格，业务负责排序、筛选和分页 |
| `.modal-backdrop/.modal`、`modal.js` | `Dialog` | 迁移 ESC、遮罩关闭、焦点回收和 ARIA |
| `.drawer-overlay/.drawer-panel`、`drawer.js` | `Sheet` | 保留右侧抽屉和移动端行为 |
| `window.confirm` | `AlertDialog` | 统一危险操作确认 |
| 通知下拉框 | `Popover` / `DropdownMenu` | 保留 `.notification-*` 样式和轮询 |
| 全局搜索下拉 | `Command` / `Popover` | 保留防抖、键盘导航、分组和高亮 |
| `.status-badge/.status-pill` | `Badge` | 抽取状态颜色和中文标签映射 |
| `.empty-state` | `EmptyState` | 保留现有 CSS 插画 |
| `.toast` | `Toast` | 第一阶段保留现有 toast 样式 |
| `.field/.form-grid` | React 表单控件 | 使用受控值和统一错误状态 |
| `.module-sidebar`、缩放、最近文档、tab bar | `AppShell` 内部组件 | 不直接套用 shadcn 默认 Sidebar |

`lucide-react` 可在后续图标专项中逐步替换 symbol sprite，但本阶段先保留现有 sprite，避免图标线宽、尺寸和对齐发生视觉漂移。

## 代码边界

- `src/app/AppShell.tsx`：壳层编排、导航事件和页面插槽。
- `src/app/Icon.tsx`、`src/app/SymbolSprite.tsx`：现有图标 sprite 的 React 封装。
- `src/components/ui/`：共享 Button、Card、Tabs、DataTable、Dialog、Sheet、AlertDialog、Badge、EmptyState、Toast 和表单控件。
- `src/components/dashboard/`：KPI、智能决策、待办、日程、文档、快捷入口和 GridStack 适配。
- `src/components/admin/`：六个 admin 面板、分页筛选、用户操作、角色授权、密码重置和资讯表单。
- `src/pages/DashboardPage.tsx`、`src/pages/AdminPage.tsx`：页面编排和页面级状态，不直接查询 DOM。
- `src/app/modalRegistry.tsx`：集中登记当前页面的 React 弹窗内容和打开状态。
- `src/app/routes.tsx`：增加 dashboard React ownership 和 `/admin` 路由，明确 legacy fallback。

## 数据流与契约边界

驾驶舱继续组合现有 `dashboard`、`enterprise`、`pipeline`、`workItems` 和 `knowledge` service，并保留现有 localStorage 适配。布局保存使用 revision/409 冲突语义，GridStack 的布局数据通过 typed mapper 转换。

admin 使用现有 service：

- 用户列表、创建、更新、删除和角色分配：`users` service。
- 审计日志：`audit` service。
- 资讯列表、发布、编辑和撤回：`enterprise` service。

AI 查询、会话、异常统计和重置密码目前使用明确标记为 `__frontend_missing_contract__` 的原生路径。React 迁移建立 typed compatibility adapter，保留请求失败和 fail-closed 行为，不伪造新的后端接口。

所有页面请求统一映射为 `loading`、`empty`、`error`、`forbidden`、`conflict`、`success`。组织切换继续通过现有 cache 失效机制隔离数据。React 不直接使用 `querySelector`、`innerHTML` 或 `classList` 管理业务状态。

## 弹窗迁移

第一阶段迁移驾驶舱和 admin 使用的弹窗：

- 驾驶舱日程新增/编辑/删除。
- 驾驶舱组件或布局相关操作需要的弹窗。
- admin 创建账号。
- admin 角色授权。
- admin 重置密码两步流程及一次性密码清理。
- admin 资讯编辑/发布。
- 共享危险操作确认和 toast。

弹窗必须支持 ESC、遮罩点击关闭、关闭后焦点回到触发按钮、移动端底部布局和敏感信息关闭清理。仍由未迁移页面使用的弹窗暂时保留在 legacy 边界。

## 测试与验收

采用测试先行：每个迁移单元先增加一个描述行为的失败测试，再实现最小行为，最后重构。

必须覆盖：

- pathname ownership、历史 hash 转换和 legacy fallback。
- 壳层导航、侧栏折叠/缩放、tab bar、登录态和组织切换。
- 共享组件的 class 保留、键盘操作、ESC、遮罩点击、焦点回收和 ARIA。
- 驾驶舱加载、空数据、403、普通错误、409 保存冲突、KPI、决策、待办、日程、文档、快捷入口和 GridStack 保存/恢复。
- admin 六个子面板、分页筛选、用户 CRUD、启用/禁用、角色授权、密码重置两步流程、资讯操作和缺失契约 fail-closed。
- Playwright 对 `/` 和 `/admin` 在桌面端及 390px 移动端进行截图和无溢出检查。
- React 路由下不出现旧壳层重复 DOM，且不加载对应 legacy 业务模块。

完成前运行 `npm test`、Vitest、TypeScript build、ESLint 和相关 Playwright 用例。

## 分阶段实施顺序

1. 建立 React `AppShell`、图标封装、pathname 路由接管和 legacy 路由边界。
2. 把已迁移 React 页面接入统一壳层，先验证视觉结构和导航行为。
3. 以测试先行为驾驶舱拆分组件，迁移数据、交互和 GridStack。
4. 以测试先行为 admin 拆分六个面板，迁移 service、分页、筛选和操作。
5. 迁移第一阶段弹窗和共享 UI 组件，删除 dashboard/admin 对应的 index 静态 markup 与原生绑定。
6. 运行完整验证，记录 CSS/截图差异，确认未迁移 legacy 页面仍可工作。

## 已确认约束

- 保留现有 CSS 和视觉结构。
- React pathname 是唯一页面路由状态源。
- 账号管理迁移整个 admin 六个子面板。
- 缺失后端契约保持 fail-closed，不假实现接口。
- Tailwind/shadcn/lucide 作为渐进式组件基础，不直接替换现有主题。
