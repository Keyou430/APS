import { useCallback, useEffect, useMemo, useState } from "react";
import type { UsersService, UserListResponse } from "../api/services/usersService";
import {
  asObject,
  errorStatus,
  readArray,
  readNumber,
  readString,
  type PageCache,
} from "./pageUtils";

type UsersPageProps = {
  cache: PageCache;
  organizationId: number | null;
  service: UsersService;
};

type PageStatus = "loading" | "empty" | "error" | "forbidden" | "success";

type UserRow = {
  email: string;
  id: number;
  isActive: boolean;
  memberType: string;
  role: string;
  username: string;
};

type UsersViewModel = {
  page: number;
  pageSize: number;
  total: number;
  users: UserRow[];
};

function mapUser(value: unknown, index: number): UserRow {
  const item = asObject(value);
  return {
    email: readString(item.email),
    id: readNumber(item.id, index + 1),
    isActive: item.is_active !== false,
    memberType: readString(item.member_type, "internal"),
    role: readString(item.role, "user"),
    username: readString(item.username, `用户 ${index + 1}`),
  };
}

function mapUsers(response: UserListResponse): UsersViewModel {
  return {
    page: readNumber(response.page, 1),
    pageSize: readNumber(response.page_size, 20),
    total: readNumber(response.total, readArray(response.items).length),
    users: readArray(response.items).map(mapUser),
  };
}

function messageForError(error: unknown) {
  const status = errorStatus(error);
  if (status === 403) return "没有用户管理访问权限";
  if (status === 404) return "用户不存在或已被隐藏";
  if (status === 409) return "用户状态已变化，请刷新后再试";
  return "用户列表加载失败";
}

export function UsersPage({ cache, organizationId, service }: UsersPageProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [status, setStatus] = useState<PageStatus>(
    organizationId === null ? "forbidden" : "loading",
  );
  const [viewModel, setViewModel] = useState<UsersViewModel | null>(null);
  const cacheKey = useMemo(() => ["users", "directory"], []);

  const loadUsers = useCallback(async () => {
    if (organizationId === null) {
      setStatus("forbidden");
      setViewModel(null);
      setErrorMessage("没有用户管理访问权限");
      return;
    }

    setErrorMessage(null);
    setStatus("loading");
    try {
      const cached = cache.get<UsersViewModel>(organizationId, cacheKey);
      const next =
        cached ??
        mapUsers(await service.listUsers({ page: 1, page_size: 20 }));
      if (!cached) cache.set(organizationId, cacheKey, next);
      setViewModel(next);
      setStatus(next.users.length ? "success" : "empty");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
      setViewModel(null);
    }
  }, [cache, cacheKey, organizationId, service]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadUsers();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadUsers]);

  async function refreshUsers() {
    if (organizationId === null) return;
    cache.invalidateOrganization(organizationId);
    await loadUsers();
  }

  async function assignManager(user: UserRow) {
    if (!viewModel || organizationId === null || status === "forbidden") return;
    setErrorMessage(null);
    try {
      const updated = mapUser(await service.assignRoles(user.id, { role: "manager" }), 0);
      cache.invalidateOrganization(organizationId);
      setViewModel({
        ...viewModel,
        users: viewModel.users.map((item) => (item.id === user.id ? updated : item)),
      });
      setStatus("success");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
    }
  }

  async function deleteUser(user: UserRow) {
    if (!viewModel || organizationId === null || status === "forbidden") return;
    setErrorMessage(null);
    try {
      await service.deleteUser(user.id);
      cache.invalidateOrganization(organizationId);
      setViewModel({
        ...viewModel,
        total: Math.max(0, viewModel.total - 1),
        users: viewModel.users.filter((item) => item.id !== user.id),
      });
      setStatus(viewModel.users.length > 1 ? "success" : "empty");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
    }
  }

  const canManage = organizationId !== null && status !== "forbidden" && viewModel !== null;

  return (
    <main aria-labelledby="users-title" className="page-view users-page">
      <header className="page-header">
        <div>
          <h1 id="users-title">用户管理</h1>
          <p>查看当前组织成员并管理角色。</p>
        </div>
        <button
          disabled={organizationId === null || status === "forbidden"}
          onClick={() => void refreshUsers()}
          type="button"
        >
          刷新用户列表
        </button>
      </header>

      {errorMessage ? (
        <p className="error-message" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {status === "loading" ? <p>正在加载用户列表</p> : null}
      {status === "empty" ? <p>当前组织暂无用户</p> : null}

      {viewModel ? (
        <>
          <section aria-label="用户摘要">
            <p>共 {viewModel.total} 位用户</p>
          </section>

          {viewModel.users.length ? (
            <div className="table-wrap">
              <table aria-label="当前组织用户列表" className="data-table">
                <thead>
                  <tr>
                    <th scope="col">用户名</th>
                    <th scope="col">邮箱</th>
                    <th scope="col">角色</th>
                    <th scope="col">成员类型</th>
                    <th scope="col">状态</th>
                    <th scope="col">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {viewModel.users.map((user) => (
                    <tr key={user.id}>
                      <td data-label="用户名">{user.username}</td>
                      <td data-label="邮箱">{user.email}</td>
                      <td data-label="角色">{user.role}</td>
                      <td data-label="成员类型">{user.memberType}</td>
                      <td data-label="状态">{user.isActive ? "启用" : "停用"}</td>
                      <td data-label="操作">
                        <button
                          disabled={!canManage}
                          onClick={() => void assignManager(user)}
                          type="button"
                        >
                          设为 manager
                        </button>
                        <button
                          aria-label={`删除 ${user.username}`}
                          disabled={!canManage}
                          onClick={() => void deleteUser(user)}
                          type="button"
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
