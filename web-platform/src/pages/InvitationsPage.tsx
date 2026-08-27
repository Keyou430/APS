import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import type {
  InvitationListResponse,
  InvitationsService,
} from "../api/services/invitationsService";

type InvitationRecord = {
  email: string;
  expiresAt: string | null;
  id: number;
  isActionable: boolean;
  role: string;
  status: string;
};

type InvitationsPageProps = {
  cache: {
    get<T>(organizationId: number, parts: string[]): T | undefined;
    invalidateOrganization(organizationId: number): void;
    set<T>(organizationId: number, parts: string[], value: T): void;
  };
  organizationId: number | null;
  service: InvitationsService;
};

type PageStatus = "loading" | "empty" | "error" | "forbidden" | "success";

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function readString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function readNumber(value: unknown, fallback = 0) {
  return typeof value === "number" ? value : fallback;
}

function mapInvitation(value: unknown): InvitationRecord {
  const item = asObject(value);
  const id = readNumber(item.id, readNumber(item.invitation_id));
  const email = readString(item.email, readString(item.invitee_email, "未命名邀请"));

  return {
    email,
    expiresAt:
      readString(
        item.token_expires_at,
        readString(item.expires_at, readString(item.expiresAt, "")),
      ) || null,
    id,
    isActionable: id > 0,
    role: readString(item.role, readString(item.member_type, "guest")),
    status: readString(item.status, "pending"),
  };
}

function mapInvitationList(response: InvitationListResponse): InvitationRecord[] {
  const payload = asObject(response);
  const items = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload.invitations)
      ? payload.invitations
      : [];
  return items.map(mapInvitation);
}

function errorStatus(error: unknown): number | null {
  const value = asObject(error);
  return readNumber(value.status, readNumber(value.statusCode, 0)) || null;
}

function messageForError(error: unknown, fallback: string) {
  const status = errorStatus(error);
  if (status === 403) return "没有邀请成员权限";
  if (status === 404) return "邀请记录不存在或已被隐藏";
  if (status === 409) return "邀请状态已变化，请刷新后重试";
  return fallback;
}

function parseResourceIds(value: string) {
  const ids = value
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((id) => Number.isInteger(id) && id > 0);
  return Array.from(new Set(ids));
}

function defaultExpiration() {
  const date = new Date();
  date.setDate(date.getDate() + 7);
  date.setSeconds(0, 0);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function InvitationsPage({
  cache,
  organizationId,
  service,
}: InvitationsPageProps) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [invitations, setInvitations] = useState<InvitationRecord[]>([]);
  const [resourceIds, setResourceIds] = useState("");
  const [status, setStatus] = useState<PageStatus>("loading");
  const [tokenExpiresAt, setTokenExpiresAt] = useState(defaultExpiration);

  const cacheKey = useMemo(() => ["invitations"], []);

  const loadInvitations = useCallback(async () => {
    if (organizationId === null) {
      setStatus("forbidden");
      setInvitations([]);
      return;
    }

    setActionError(null);
    try {
      const cached = cache.get<InvitationRecord[]>(organizationId, cacheKey);
      const nextInvitations =
        cached ?? mapInvitationList(await service.listInvitations());
      if (!cached) cache.set(organizationId, cacheKey, nextInvitations);
      setInvitations(nextInvitations);
      setStatus(nextInvitations.length ? "success" : "empty");
    } catch (error) {
      setInvitations([]);
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setActionError(messageForError(error, "邀请记录加载失败"));
    }
  }, [cache, cacheKey, organizationId, service]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadInvitations();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadInvitations]);

  async function submitInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedEmail = email.trim();
    const parsedResourceIds = parseResourceIds(resourceIds);
    const expiresAt = new Date(tokenExpiresAt);
    if (!trimmedEmail || !parsedResourceIds.length || Number.isNaN(expiresAt.valueOf())) {
      setActionError("请填写邀请邮箱、有效期和至少一个知识资源 ID");
      return;
    }

    setActionError(null);
    try {
      await service.createInvitation({
        email: trimmedEmail,
        resource_ids: parsedResourceIds,
        token_expires_at: expiresAt.toISOString(),
      });
      if (organizationId !== null) cache.invalidateOrganization(organizationId);
      setEmail("");
      setStatus("loading");
      await loadInvitations();
    } catch (error) {
      if (errorStatus(error) === 403) setStatus("forbidden");
      setActionError(messageForError(error, "邀请创建失败"));
    }
  }

  async function revokeInvitation(invitation: InvitationRecord) {
    setActionError(null);
    try {
      await service.revokeInvitation(invitation.id);
      if (organizationId !== null) cache.invalidateOrganization(organizationId);
      setStatus("loading");
      await loadInvitations();
    } catch (error) {
      if (errorStatus(error) === 403) setStatus("forbidden");
      setActionError(messageForError(error, "邀请撤销失败"));
    }
  }

  async function regenerateInvitation(invitation: InvitationRecord) {
    setActionError(null);
    try {
      await service.regenerateInvitation(invitation.id, {
        token_expires_at: new Date(tokenExpiresAt).toISOString(),
      });
      if (organizationId !== null) cache.invalidateOrganization(organizationId);
      setStatus("loading");
      await loadInvitations();
    } catch (error) {
      if (errorStatus(error) === 403) setStatus("forbidden");
      setActionError(messageForError(error, "邀请重新生成失败"));
    }
  }

  const hasRows = invitations.length > 0;
  const canManageInvitations = organizationId !== null && status !== "forbidden";

  return (
    <main aria-labelledby="invitations-title" className="page-view invitations-page">
      <header className="page-header">
        <div>
          <h1 id="invitations-title">邀请管理</h1>
          <p>管理当前组织的成员邀请和访客入口。</p>
        </div>
      </header>

      <form aria-label="创建邀请" className="toolbar" onSubmit={submitInvitation}>
        <label htmlFor="invitation-email">邀请邮箱</label>
        <input
          id="invitation-email"
          name="email"
          onChange={(event) => setEmail(event.currentTarget.value)}
          placeholder="name@example.com"
          type="email"
          value={email}
        />
        <label htmlFor="invitation-resource-ids">知识资源 ID</label>
        <input
          id="invitation-resource-ids"
          inputMode="numeric"
          name="resourceIds"
          onChange={(event) => setResourceIds(event.currentTarget.value)}
          placeholder="例如：12, 18"
          value={resourceIds}
        />
        <label htmlFor="invitation-expires-at">邀请有效至</label>
        <input
          id="invitation-expires-at"
          name="tokenExpiresAt"
          onChange={(event) => setTokenExpiresAt(event.currentTarget.value)}
          type="datetime-local"
          value={tokenExpiresAt}
        />
        <button disabled={!canManageInvitations} type="submit">
          创建邀请
        </button>
      </form>

      {actionError ? (
        <p className="error-message" role="alert">
          {actionError}
        </p>
      ) : null}

      {status === "loading" ? <p>正在加载邀请记录</p> : null}
      {status === "forbidden" && !actionError ? (
        <p>没有邀请成员权限</p>
      ) : null}
      {status === "error" ? <p>邀请记录加载失败</p> : null}
      {status === "empty" ? <p>还没有邀请记录</p> : null}

      {hasRows ? (
        <table>
          <caption>当前组织邀请记录</caption>
          <thead>
            <tr>
              <th scope="col">邮箱</th>
              <th scope="col">角色</th>
              <th scope="col">状态</th>
              <th scope="col">过期时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {invitations.map((invitation) => (
              <tr key={invitation.id}>
                <td>{invitation.email}</td>
                <td>{invitation.role}</td>
                <td>{invitation.status}</td>
                <td>{invitation.expiresAt ?? "未设置"}</td>
                <td>
                  <button
                    aria-label={`撤销 ${invitation.email} 的邀请`}
                    disabled={!canManageInvitations || !invitation.isActionable}
                    onClick={() => void revokeInvitation(invitation)}
                    type="button"
                  >
                    撤销
                  </button>
                  <button
                    aria-label={`重新生成 ${invitation.email} 的邀请`}
                    disabled={!canManageInvitations || !invitation.isActionable}
                    onClick={() => void regenerateInvitation(invitation)}
                    type="button"
                  >
                    重发
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </main>
  );
}
