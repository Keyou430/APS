import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  DashboardDataResponse,
  DashboardLayoutResponse,
  DashboardService,
} from "../api/services/dashboardService";
import {
  asObject,
  errorStatus,
  readArray,
  readNumber,
  readString,
  type PageCache,
} from "./pageUtils";

type DashboardPageProps = {
  cache: PageCache;
  organizationId: number | null;
  service: DashboardService;
};

type PageStatus = "loading" | "empty" | "error" | "forbidden" | "conflict" | "success";

type MetricCard = {
  id: string;
  label: string;
  value: string;
};

type DashboardViewModel = {
  calendarEvents: string[];
  layout: DashboardLayoutResponse;
  metrics: MetricCard[];
  notificationsCount: number;
  pipelinesCount: number;
  quickActionsCount: number;
  recentVisits: string[];
  todos: string[];
};

function mapMetric(value: unknown, index: number): MetricCard {
  const item = asObject(value);
  return {
    id: readString(item.id, `metric-${index}`),
    label: readString(item.label, readString(item.name, `指标 ${index + 1}`)),
    value: String(item.value ?? item.count ?? "--"),
  };
}

function mapDashboard(
  data: DashboardDataResponse,
  layout: DashboardLayoutResponse,
): DashboardViewModel {
  return {
    calendarEvents: readArray(data.calendarEvents)
      .slice(0, 5)
      .map((event, index) => {
        const item = asObject(event);
        return readString(item.title, readString(item.name, `日程 ${index + 1}`));
      }),
    layout,
    metrics: readArray(data.metrics).map(mapMetric),
    notificationsCount: readArray(data.notifications).length,
    pipelinesCount: readArray(data.pipelines).length,
    quickActionsCount: readArray(data.quickActions).length,
    recentVisits: readArray(data.recentVisits)
      .slice(0, 5)
      .map((visit, index) => {
        const item = asObject(visit);
        return readString(item.title, readString(item.name, `访问 ${index + 1}`));
      }),
    todos: readArray(data.todos)
      .slice(0, 5)
      .map((todo, index) => {
        const item = asObject(todo);
        return readString(item.title, readString(item.name, `待办 ${index + 1}`));
      }),
  };
}

function messageForError(error: unknown) {
  const status = errorStatus(error);
  if (status === 403) return "没有驾驶舱访问权限";
  if (status === 409) return "布局版本已被更新，请刷新后再保存";
  return "驾驶舱加载失败";
}

export function DashboardPage({
  cache,
  organizationId,
  service,
}: DashboardPageProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [viewModel, setViewModel] = useState<DashboardViewModel | null>(null);
  const cacheKey = useMemo(() => ["dashboard", "overview"], []);

  const loadDashboard = useCallback(async () => {
    if (organizationId === null) {
      setStatus("forbidden");
      setViewModel(null);
      setErrorMessage("没有驾驶舱访问权限");
      return;
    }

    setErrorMessage(null);
    try {
      const cached = cache.get<DashboardViewModel>(organizationId, cacheKey);
      const next =
        cached ??
        mapDashboard(await service.getDashboard(), await service.getLayout());
      if (!cached) cache.set(organizationId, cacheKey, next);
      setViewModel(next);
      setStatus(
        next.metrics.length ||
          next.todos.length ||
          next.calendarEvents.length ||
          next.recentVisits.length
          ? "success"
          : "empty",
      );
    } catch (error) {
      const statusCode = errorStatus(error);
      setStatus(statusCode === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
      setViewModel(null);
    }
  }, [cache, cacheKey, organizationId, service]);

  async function refreshDashboard() {
    if (organizationId === null) return;
    cache.invalidateOrganization(organizationId);
    setStatus("loading");
    await loadDashboard();
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadDashboard();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadDashboard]);

  async function saveLayout() {
    if (!viewModel || organizationId === null) return;
    setErrorMessage(null);
    try {
      const nextLayout = await service.saveLayout({
        expectedRevision: viewModel.layout.revision,
        layouts: viewModel.layout.layouts,
      });
      const next = { ...viewModel, layout: nextLayout };
      cache.invalidateOrganization(organizationId);
      cache.set(organizationId, cacheKey, next);
      setViewModel(next);
      setStatus("success");
    } catch (error) {
      if (errorStatus(error) === 409) setStatus("conflict");
      if (errorStatus(error) === 403) setStatus("forbidden");
      setErrorMessage(messageForError(error));
    }
  }

  async function resetLayout() {
    if (organizationId === null) return;
    setErrorMessage(null);
    try {
      const nextLayout = await service.resetLayout();
      cache.invalidateOrganization(organizationId);
      setViewModel((current) =>
        current ? { ...current, layout: nextLayout } : current,
      );
      setStatus("success");
    } catch (error) {
      if (errorStatus(error) === 403) setStatus("forbidden");
      setErrorMessage(messageForError(error));
    }
  }

  const canManageLayout =
    organizationId !== null && status !== "forbidden" && viewModel !== null;

  return (
    <main aria-labelledby="dashboard-title" className="page-view dashboard-page">
      <header className="page-header">
        <div>
          <h1 id="dashboard-title">驾驶舱</h1>
          <p>展示当前组织的关键指标、待办和运营状态。</p>
        </div>
      </header>

      <section aria-label="驾驶舱操作" className="toolbar">
        <button disabled={!canManageLayout} onClick={() => void saveLayout()} type="button">
          保存布局
        </button>
        <button disabled={!canManageLayout} onClick={() => void resetLayout()} type="button">
          重置布局
        </button>
        <button
          disabled={organizationId === null || status === "forbidden"}
          onClick={() => void refreshDashboard()}
          type="button"
        >
          刷新驾驶舱
        </button>
      </section>

      {errorMessage ? (
        <p className="error-message" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {status === "loading" ? <p>正在加载驾驶舱</p> : null}
      {status === "empty" ? <p>驾驶舱暂无数据</p> : null}

      {viewModel ? (
        <>
          <section aria-label="驾驶舱摘要">
            <p>布局版本 {readNumber(viewModel.layout.revision)}</p>
            <dl>
              <div>
                <dt>通知</dt>
                <dd>{viewModel.notificationsCount}</dd>
              </div>
              <div>
                <dt>流程</dt>
                <dd>{viewModel.pipelinesCount}</dd>
              </div>
              <div>
                <dt>快捷操作</dt>
                <dd>{viewModel.quickActionsCount}</dd>
              </div>
            </dl>
          </section>

          <section aria-label="关键指标">
            <h2>关键指标</h2>
            {viewModel.metrics.length ? (
              <ul>
                {viewModel.metrics.map((metric) => (
                  <li key={metric.id}>
                    <strong>{metric.label}</strong>
                    <span>{metric.value}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>暂无关键指标</p>
            )}
          </section>

          <section aria-label="当前待办">
            <h2>当前待办</h2>
            {viewModel.todos.length ? (
              <ul>
                {viewModel.todos.map((todo) => (
                  <li key={todo}>{todo}</li>
                ))}
              </ul>
            ) : (
              <p>暂无待办</p>
            )}
          </section>

          <section aria-label="今日日程">
            <h2>今日日程</h2>
            {viewModel.calendarEvents.length ? (
              <ul>
                {viewModel.calendarEvents.map((event) => (
                  <li key={event}>{event}</li>
                ))}
              </ul>
            ) : (
              <p>暂无日程</p>
            )}
          </section>

          <section aria-label="最近访问">
            <h2>最近访问</h2>
            {viewModel.recentVisits.length ? (
              <ul>
                {viewModel.recentVisits.map((visit) => (
                  <li key={visit}>{visit}</li>
                ))}
              </ul>
            ) : (
              <p>暂无访问记录</p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
