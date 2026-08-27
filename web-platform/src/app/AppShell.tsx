import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import type { AppRuntime } from "./appRuntime";
import { Icon, type IconId } from "./Icon";
import { resolveRoute } from "./routes";
import { SymbolSprite } from "./SymbolSprite";

export type AppShellProps = {
  pathname: string;
  children: ReactNode;
  runtime?: AppRuntime;
};

type ShellNavigationItem = {
  icon: IconId;
  label: string;
  path: string;
};

const navigationItems: ShellNavigationItem[] = [
  { icon: "i-grid", label: "驾驶舱", path: "/" },
  { icon: "i-home", label: "企业门户", path: "/portal" },
  { icon: "i-book", label: "AI 服务", path: "/knowledge" },
  { icon: "i-user", label: "组织架构", path: "/organization" },
  { icon: "i-message", label: "会话", path: "/chat" },
  { icon: "i-settings", label: "账号管理", path: "/admin" },
];

const fallbackSidebarWidth = 230;
const minSidebarWidth = 180;
const maxSidebarWidth = 380;
const sidebarKeyboardStep = 10;

export function AppShell({ children, pathname, runtime }: AppShellProps) {
  const uiStore = runtime?.ui;
  const authStore = runtime?.auth.store;
  const subscribe = useCallback(
    (listener: () => void) => uiStore?.subscribe(listener) ?? (() => undefined),
    [uiStore],
  );
  const getSidebarWidth = useCallback(
    () => uiStore?.getState().sidebarWidth ?? fallbackSidebarWidth,
    [uiStore],
  );
  const sidebarWidth = useSyncExternalStore(
    subscribe,
    getSidebarWidth,
    getSidebarWidth,
  );
  const authSubscribe = useCallback(
    (listener: () => void) =>
      authStore?.subscribe(listener) ?? (() => undefined),
    [authStore],
  );
  const getAuthUsername = useCallback(
    () => authStore?.getState().user?.username ?? null,
    [authStore],
  );
  const username = useSyncExternalStore(
    authSubscribe,
    getAuthUsername,
    getAuthUsername,
  );
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const activeRoute = resolveRoute(pathname);
  const userLabel = username ?? "未登录";
  const resizeCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    document.body.classList.toggle("sidebar-collapsed", sidebarCollapsed);
    return () => document.body.classList.remove("sidebar-collapsed");
  }, [sidebarCollapsed]);

  useEffect(() => {
    return () => resizeCleanupRef.current?.();
  }, []);

  function navigate(path: string) {
    if (path === pathname) return;
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  function resizeSidebar(event: ReactPointerEvent<HTMLDivElement>) {
    if (!uiStore || sidebarCollapsed) return;
    event.preventDefault();
    resizeCleanupRef.current?.();
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    const handlePointerMove = (moveEvent: PointerEvent) => {
      uiStore.setSidebarWidth(
        Math.max(
          minSidebarWidth,
          Math.min(
            maxSidebarWidth,
            startWidth + moveEvent.clientX - startX,
          ),
        ),
      );
    };
    const stopResize = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
      if (resizeCleanupRef.current === stopResize) {
        resizeCleanupRef.current = null;
      }
    };
    resizeCleanupRef.current = stopResize;
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
  }

  function resizeSidebarWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!uiStore || sidebarCollapsed) return;
    let nextWidth: number | null = null;
    if (event.key === "ArrowLeft") nextWidth = sidebarWidth - sidebarKeyboardStep;
    if (event.key === "ArrowRight") nextWidth = sidebarWidth + sidebarKeyboardStep;
    if (event.key === "Home") nextWidth = minSidebarWidth;
    if (event.key === "End") nextWidth = maxSidebarWidth;
    if (nextWidth === null) return;
    event.preventDefault();
    uiStore.setSidebarWidth(
      Math.max(minSidebarWidth, Math.min(maxSidebarWidth, nextWidth)),
    );
  }

  const shellStyle = {
    "--sidebar": `${sidebarWidth}px`,
  } as CSSProperties;

  return (
    <div className="app-shell" style={shellStyle}>
      <SymbolSprite />
      <header className="topbar">
        <div className="topbar-row1">
          <div className="brand">
            <div className="brand-mark">星</div>
            <div className="brand-copy">
              <strong>星纪云1.0</strong>
              <span>Enterprise Workspace</span>
            </div>
          </div>
          <div className="top-actions">
            <button aria-label="搜索" className="top-icon" type="button">
              <Icon id="i-search" />
            </button>
            <button aria-label="通知" className="top-icon" type="button">
              <Icon id="i-bell" />
            </button>
            <button aria-label="个人入口" className="user-trigger" type="button">
              <span className="avatar">{userLabel.slice(0, 1)}</span>
              <span>{userLabel}</span>
              <Icon id="i-chevron-down" style={{ height: 14, width: 14 }} />
            </button>
          </div>
        </div>
      </header>

      <div className="app-frame">
        <div className="layout">
          <aside
            aria-label="主导航"
            className={`module-sidebar${sidebarCollapsed ? " collapsed" : ""}`}
          >
            <div className="sidebar-head">
              <div className="side-title">导航</div>
              <button
                aria-expanded={!sidebarCollapsed}
                aria-label={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
                className="sidebar-toggle"
                onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
                type="button"
              >
                <Icon id="i-chevron-left" />
              </button>
            </div>
            <nav className="sidebar-nav">
              {navigationItems.map((item) => {
                const active = pathname === item.path;
                return (
                  <div className="nav-item" key={item.path}>
                    <div className="nav-row">
                      <button
                        aria-current={active ? "page" : undefined}
                        className={`nav-main${active ? " active" : ""}`}
                        onClick={() => navigate(item.path)}
                        title={item.label}
                        type="button"
                      >
                        <Icon id={item.icon} />
                        <span>{item.label}</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </nav>
            <div className="sidebar-docs">
              <div className="sidebar-docs-title">最近文档</div>
              <div className="sidebar-docs-list">
                <div className="sidebar-docs-empty">暂无最近文档</div>
              </div>
            </div>
            <div className="sidebar-foot">
              <span className="sidebar-avatar">{userLabel.slice(0, 1)}</span>
              <span className="sidebar-name">{userLabel}</span>
            </div>
          </aside>
          <div
            aria-label="调整模块侧边栏宽度"
            aria-orientation="vertical"
            aria-valuemax={maxSidebarWidth}
            aria-valuemin={minSidebarWidth}
            aria-valuenow={sidebarWidth}
            className="sidebar-resizer"
            onKeyDown={resizeSidebarWithKeyboard}
            onPointerDown={resizeSidebar}
            role="separator"
            tabIndex={0}
          />
          <div className="content-area">
            <div className="tab-bar">
              <div className="tab-item active">
                <button className="tab-item-label" type="button">
                  {activeRoute.label}
                </button>
              </div>
            </div>
            <main className="main">{children}</main>
          </div>
        </div>
      </div>
    </div>
  );
}
