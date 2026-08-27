import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { HermesService } from "../api/services/hermesService";
import {
  asObject,
  errorStatus,
  readArray,
  readNumber,
  readString,
  type PageCache,
} from "./pageUtils";

type HermesPageProps = {
  cache: PageCache;
  organizationId: number | null;
  service: HermesService;
};

type PageStatus = "idle" | "loading" | "error" | "forbidden" | "success";

type HermesProfileView = {
  capabilities: string[];
  provider: string;
  status: string;
  userId: number;
};

type HermesHealthView = {
  checkedAt: string;
  status: string;
};

function mapProfile(value: unknown): HermesProfileView {
  const item = asObject(value);
  return {
    capabilities: readArray(item.capabilities)
      .map((capability) => readString(capability))
      .filter(Boolean),
    provider: readString(item.provider, "unknown"),
    status: readString(item.status, readString(item.state, "unknown")),
    userId: readNumber(item.user_id, readNumber(item.userId)),
  };
}

function mapHealth(value: unknown): HermesHealthView {
  const item = asObject(value);
  return {
    checkedAt: readString(item.last_checked_at, readString(item.checkedAt, "未检查")),
    status: readString(item.status, "unknown"),
  };
}

function messageForError(error: unknown, fallback: string) {
  const status = errorStatus(error);
  if (status === 403) return "没有 AI 服务管理权限";
  if (status === 404) return "Profile 不存在或已被隐藏";
  if (status === 409) return "Profile 状态已变化，请刷新后重试";
  return fallback;
}

export function HermesPage({ cache, organizationId, service }: HermesPageProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(
    organizationId === null ? "没有 AI 服务管理权限" : null,
  );
  const [health, setHealth] = useState<HermesHealthView | null>(null);
  const [profile, setProfile] = useState<HermesProfileView | null>(null);
  const [provider, setProvider] = useState("feishu");
  const [status, setStatus] = useState<PageStatus>(
    organizationId === null ? "forbidden" : "idle",
  );
  const [userId, setUserId] = useState("9");
  const profileCacheKey = useMemo(
    () => ["hermes", "profile", userId.trim()],
    [userId],
  );
  const healthCacheKey = useMemo(
    () => ["hermes", "health", userId.trim()],
    [userId],
  );

  function parseUserId() {
    const parsed = Number(userId);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }

  function ensureActionable() {
    const parsedUserId = parseUserId();
    if (organizationId === null) {
      setStatus("forbidden");
      setErrorMessage("没有 AI 服务管理权限");
      return null;
    }
    if (parsedUserId === null) {
      setErrorMessage("请填写有效的用户 ID");
      return null;
    }
    setErrorMessage(null);
    return parsedUserId;
  }

  async function loadProfile(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const parsedUserId = ensureActionable();
    if (parsedUserId === null || organizationId === null) return;

    setStatus("loading");
    try {
      const cached = cache.get<HermesProfileView>(organizationId, profileCacheKey);
      const next = cached ?? mapProfile(await service.getProfile(parsedUserId));
      if (!cached) cache.set(organizationId, profileCacheKey, next);
      setProfile(next);
      setStatus("success");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error, "Profile 加载失败"));
    }
  }

  async function createProfile() {
    const parsedUserId = ensureActionable();
    if (parsedUserId === null || organizationId === null) return;

    setStatus("loading");
    try {
      const next = mapProfile(
        await service.createProfile({
          provider,
          user_id: parsedUserId,
        }),
      );
      cache.invalidateOrganization(organizationId);
      cache.set(organizationId, profileCacheKey, next);
      setProfile(next);
      setStatus("success");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error, "Profile 创建失败"));
    }
  }

  async function checkHealth() {
    const parsedUserId = ensureActionable();
    if (parsedUserId === null) return;

    setStatus("loading");
    try {
      const cached = organizationId
        ? cache.get<HermesHealthView>(organizationId, healthCacheKey)
        : undefined;
      const next = cached ?? mapHealth(await service.getProfileHealth(parsedUserId));
      if (!cached && organizationId) {
        cache.set(organizationId, healthCacheKey, next);
      }
      setHealth(next);
      setStatus("success");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error, "健康检查失败"));
    }
  }

  async function deactivateProfile() {
    const parsedUserId = ensureActionable();
    if (parsedUserId === null || organizationId === null) return;

    setStatus("loading");
    try {
      await service.deactivateProfile(parsedUserId);
      cache.invalidateOrganization(organizationId);
      setProfile((current) =>
        current && current.userId === parsedUserId
          ? { ...current, status: "inactive" }
          : current,
      );
      setStatus("success");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error, "Profile 停用失败"));
    }
  }

  const canManage = organizationId !== null && status !== "forbidden";

  return (
    <main aria-labelledby="hermes-title" className="page-view hermes-page">
      <header className="page-header">
        <div>
          <h1 id="hermes-title">AI 服务</h1>
          <p>管理 Hermes Profile、服务健康和企业 AI 接入状态。</p>
        </div>
      </header>

      <form aria-label="AI 服务 Profile 查询" className="toolbar" onSubmit={loadProfile}>
        <label htmlFor="hermes-user-id">用户 ID</label>
        <input
          id="hermes-user-id"
          inputMode="numeric"
          onChange={(event) => setUserId(event.currentTarget.value)}
          value={userId}
        />
        <label htmlFor="hermes-provider">服务 Provider</label>
        <select
          id="hermes-provider"
          onChange={(event) => setProvider(event.currentTarget.value)}
          value={provider}
        >
          <option value="feishu">feishu</option>
          <option value="dingtalk">dingtalk</option>
          <option value="internal">internal</option>
        </select>
        <button disabled={!canManage} type="submit">
          查看 Profile
        </button>
        <button disabled={!canManage} onClick={() => void createProfile()} type="button">
          创建 Profile
        </button>
        <button disabled={!canManage} onClick={() => void checkHealth()} type="button">
          健康检查
        </button>
        <button disabled={!canManage} onClick={() => void deactivateProfile()} type="button">
          停用 Profile
        </button>
      </form>

      {errorMessage ? (
        <p className="error-message" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {status === "loading" ? <p>正在加载 AI 服务状态</p> : null}

      {profile ? (
        <section aria-label="Hermes Profile">
          <h2>Profile</h2>
          <dl>
            <div>
              <dt>用户 ID</dt>
              <dd>{profile.userId}</dd>
            </div>
            <div>
              <dt>Provider</dt>
              <dd>{profile.provider}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{profile.status}</dd>
            </div>
            <div>
              <dt>能力</dt>
              <dd>
                {profile.capabilities.length
                  ? profile.capabilities.map((capability) => (
                      <span key={capability}>{capability}</span>
                    ))
                  : "未声明"}
              </dd>
            </div>
          </dl>
        </section>
      ) : (
        <p>选择用户后查看 AI 服务 Profile。</p>
      )}

      {health ? (
        <section aria-label="Hermes 健康状态">
          <h2>健康状态</h2>
          <dl>
            <div>
              <dt>状态</dt>
              <dd>{health.status}</dd>
            </div>
            <div>
              <dt>检查时间</dt>
              <dd>{health.checkedAt}</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </main>
  );
}
