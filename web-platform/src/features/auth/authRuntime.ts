import { createApiClient, type ApiClient } from "../../api/client";
import {
  createOrganizationAbortRegistry,
  createOrganizationCache,
} from "../../api/cache";
import {
  createAuthService,
  type AuthSession,
  type TokenResponse,
} from "../../api/services/authService";
import { createAuthStore, type AuthStore } from "./authStore";

type AuthStorage = {
  getItem(key: string): string | null;
  removeItem(key: string): unknown;
  setItem(key: string, value: string): unknown;
};

export type AuthRuntimeOptions = {
  baseUrl?: string;
  fetchFn?: typeof fetch;
  onOrganizationChange?: (
    previousOrganizationId: number,
    nextOrganizationId: number,
  ) => void;
  storage?: AuthStorage;
};

export type AuthRuntime = {
  abortRegistry: ReturnType<typeof createOrganizationAbortRegistry>;
  cache: ReturnType<typeof createOrganizationCache>;
  client: ApiClient;
  refreshSession(): Promise<void>;
  store: AuthStore;
};

export function createAuthRuntime(options: AuthRuntimeOptions = {}): AuthRuntime {
  const cache = createOrganizationCache();
  const abortRegistry = createOrganizationAbortRegistry();
  const runtimeState: { store?: AuthStore } = {};
  let pendingToken: TokenResponse | null = null;

  function getStore() {
    if (!runtimeState.store) {
      throw new Error("Auth runtime store has not been initialized.");
    }
    return runtimeState.store;
  }

  async function refreshSession() {
    const refreshToken = getStore().getState().session?.token.refresh_token;
    if (!refreshToken) return;
    pendingToken = await service.refresh({ refresh_token: refreshToken });
    getStore().commitToken(pendingToken);
  }

  const client = createApiClient({
    baseUrl: options.baseUrl,
    clearSession: () => {
      void getStore().logout();
      // The legacy app.js layer keeps its own in-memory token; without this
      // event it would keep calling APIs with the expired session.
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("agent-platform:session-cleared"));
      }
    },
    fetchFn: options.fetchFn,
    getAccessToken: () =>
      pendingToken?.access_token ??
      getStore().getState().session?.token.access_token ??
      null,
    mockMode: import.meta.env.VITE_USE_MOCK === "true",
    refresh: refreshSession,
  });

  const service = createAuthService({
    request: client.request,
    setPendingAccessToken: (token) => {
      const currentStore = getStore();
      pendingToken = {
        access_token: token,
        expires_in: 0,
        organization_id: currentStore.getState().organizationId ?? 0,
        refresh_token: currentStore.getState().session?.token.refresh_token ?? "",
        token_type: "bearer",
      };
    },
  });

  runtimeState.store = createAuthStore({
    onOrganizationChange: (previousOrganizationId, nextOrganizationId) => {
      cache.invalidateOrganization(previousOrganizationId);
      abortRegistry.abortOrganization(previousOrganizationId);
      options.onOrganizationChange?.(previousOrganizationId, nextOrganizationId);
    },
    service: {
      ...service,
      async login(request): Promise<AuthSession> {
        const session = await service.login(request);
        pendingToken = null;
        return session;
      },
      async switchOrganization(request): Promise<AuthSession> {
        const session = await service.switchOrganization(request);
        pendingToken = null;
        return session;
      },
    },
    storage: options.storage,
  });

  return { abortRegistry, cache, client, refreshSession, store: getStore() };
}
