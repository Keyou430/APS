import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  EnterprisePortalResponse,
  EnterpriseService,
} from "../api/services/enterpriseService";
import {
  asObject,
  errorStatus,
  readArray,
  readNumber,
  readString,
  type PageCache,
} from "./pageUtils";

type PortalPageProps = {
  cache: PageCache;
  organizationId: number | null;
  service: EnterpriseService;
};

type PageStatus = "loading" | "empty" | "error" | "forbidden" | "success";

type PortalTodo = {
  completed: boolean;
  id: number;
  title: string;
};

type PortalLink = {
  id: string;
  title: string;
};

type PortalViewModel = {
  activities: string[];
  announcements: string[];
  collaborators: string[];
  companyName: string;
  currentUserName: string;
  departmentsCount: number;
  peopleCount: number;
  positionsCount: number;
  quickLinks: PortalLink[];
  slogan: string;
  todos: PortalTodo[];
};

function mapTodo(value: unknown, index: number): PortalTodo {
  const item = asObject(value);
  return {
    completed: item.completed === true || item.done === true,
    id: readNumber(item.id, index + 1),
    title: readString(item.title, readString(item.name, `待办 ${index + 1}`)),
  };
}

function mapPortal(data: EnterprisePortalResponse): PortalViewModel {
  const company = asObject(data.company);
  const currentUser = asObject(data.currentUser);
  return {
    activities: readArray(data.activities)
      .slice(0, 5)
      .map((activity, index) => {
        const item = asObject(activity);
        return readString(item.title, readString(item.name, `动态 ${index + 1}`));
      }),
    announcements: readArray(data.announcements)
      .slice(0, 5)
      .map((announcement, index) => {
        const item = asObject(announcement);
        return readString(
          item.title,
          readString(item.name, `公告 ${index + 1}`),
        );
      }),
    collaborators: readArray(data.collaborators)
      .slice(0, 5)
      .map((collaborator, index) => {
        const item = asObject(collaborator);
        return readString(
          item.name,
          readString(item.username, `协作者 ${index + 1}`),
        );
      }),
    companyName: readString(company.name, "企业门户"),
    currentUserName: readString(
      currentUser.name,
      readString(currentUser.username, "当前用户"),
    ),
    departmentsCount: readArray(data.departments).length,
    peopleCount: readArray(data.people).length,
    positionsCount: readArray(data.positions).length,
    quickLinks: readArray(data.quickLinks)
      .slice(0, 6)
      .map((link, index) => {
        const item = asObject(link);
        return {
          id: readString(item.id, `quick-link-${index}`),
          title: readString(item.title, readString(item.name, `快捷入口 ${index + 1}`)),
        };
      }),
    slogan: readString(company.slogan, "Enterprise Workspace"),
    todos: readArray(data.todos).slice(0, 5).map(mapTodo),
  };
}

function messageForError(error: unknown) {
  return errorStatus(error) === 403
    ? "没有企业门户访问权限"
    : "企业门户加载失败";
}

export function PortalPage({
  cache,
  organizationId,
  service,
}: PortalPageProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [status, setStatus] = useState<PageStatus>(
    organizationId === null ? "forbidden" : "loading",
  );
  const [viewModel, setViewModel] = useState<PortalViewModel | null>(null);
  const cacheKey = useMemo(() => ["portal", "overview"], []);

  const loadPortal = useCallback(async () => {
    if (organizationId === null) {
      setStatus("forbidden");
      setViewModel(null);
      setErrorMessage("没有企业门户访问权限");
      return;
    }

    setErrorMessage(null);
    setStatus("loading");
    try {
      const cached = cache.get<PortalViewModel>(organizationId, cacheKey);
      const next = cached ?? mapPortal(await service.getPortal());
      if (!cached) cache.set(organizationId, cacheKey, next);
      setViewModel(next);
      setStatus(
        next.announcements.length ||
          next.todos.length ||
          next.quickLinks.length ||
          next.activities.length
          ? "success"
          : "empty",
      );
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
      setViewModel(null);
    }
  }, [cache, cacheKey, organizationId, service]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadPortal();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadPortal]);

  async function refreshPortal() {
    if (organizationId === null) return;
    cache.invalidateOrganization(organizationId);
    await loadPortal();
  }

  async function completeTodo(todoId: number) {
    if (!viewModel || organizationId === null || status === "forbidden") return;
    setErrorMessage(null);
    try {
      await service.updatePortalTodo(todoId, { completed: true });
      const next = {
        ...viewModel,
        todos: viewModel.todos.map((todo) =>
          todo.id === todoId ? { ...todo, completed: true } : todo,
        ),
      };
      cache.invalidateOrganization(organizationId);
      cache.set(organizationId, cacheKey, next);
      setViewModel(next);
      setStatus("success");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
    }
  }

  const canManageTodos =
    organizationId !== null && status !== "forbidden" && viewModel !== null;

  return (
    <main aria-labelledby="portal-title" className="page-view portal-page">
      <header className="page-header">
        <div>
          <h1 id="portal-title">企业门户</h1>
          <p>
            {viewModel?.companyName ?? "当前组织"} ·{" "}
            {viewModel?.slogan ?? "Enterprise Workspace"}
          </p>
        </div>
        <button
          disabled={organizationId === null || status === "forbidden"}
          onClick={() => void refreshPortal()}
          type="button"
        >
          刷新企业门户
        </button>
      </header>

      {errorMessage ? (
        <p className="error-message" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {status === "loading" ? <p>正在加载企业门户</p> : null}
      {status === "empty" ? <p>企业门户暂无数据</p> : null}

      {viewModel ? (
        <>
          <section aria-label="门户摘要">
            <h2>{viewModel.companyName}</h2>
            <p>当前用户：{viewModel.currentUserName}</p>
            <dl>
              <div>
                <dt>部门</dt>
                <dd>{viewModel.departmentsCount}</dd>
              </div>
              <div>
                <dt>人员</dt>
                <dd>{viewModel.peopleCount}</dd>
              </div>
              <div>
                <dt>职位</dt>
                <dd>{viewModel.positionsCount}</dd>
              </div>
              <div>
                <dt>协作者</dt>
                <dd>{viewModel.collaborators.length}</dd>
              </div>
            </dl>
          </section>

          <section aria-label="门户协作者">
            <h2>协作者</h2>
            {viewModel.collaborators.length ? (
              <ul>
                {viewModel.collaborators.map((collaborator) => (
                  <li key={collaborator}>{collaborator}</li>
                ))}
              </ul>
            ) : (
              <p>暂无协作者</p>
            )}
          </section>

          <section aria-label="门户公告">
            <h2>公告</h2>
            {viewModel.announcements.length ? (
              <ul>
                {viewModel.announcements.map((announcement) => (
                  <li key={announcement}>{announcement}</li>
                ))}
              </ul>
            ) : (
              <p>暂无公告</p>
            )}
          </section>

          <section aria-label="门户待办">
            <h2>待办</h2>
            {viewModel.todos.length ? (
              <ul>
                {viewModel.todos.map((todo) => (
                  <li key={todo.id}>
                    <strong>{todo.title}</strong>
                    {todo.completed ? (
                      <span>已完成</span>
                    ) : (
                      <button
                        aria-label={`完成 ${todo.title}`}
                        disabled={!canManageTodos}
                        onClick={() => void completeTodo(todo.id)}
                        type="button"
                      >
                        完成
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p>暂无待办</p>
            )}
          </section>

          <section aria-label="快捷入口">
            <h2>快捷入口</h2>
            {viewModel.quickLinks.length ? (
              <ul>
                {viewModel.quickLinks.map((link) => (
                  <li key={link.id}>{link.title}</li>
                ))}
              </ul>
            ) : (
              <p>暂无快捷入口</p>
            )}
          </section>

          <section aria-label="最近动态">
            <h2>最近动态</h2>
            {viewModel.activities.length ? (
              <ul>
                {viewModel.activities.map((activity) => (
                  <li key={activity}>{activity}</li>
                ))}
              </ul>
            ) : (
              <p>暂无动态</p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
