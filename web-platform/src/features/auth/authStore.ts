import type {
  AuthService,
  AuthSession,
  LoginRequest,
  SwitchOrganizationRequest,
} from "../../api/services/authService";

const authStorageKey = "agent-platform.auth";

type AuthStorage = {
  getItem(key: string): string | null;
  removeItem(key: string): unknown;
  setItem(key: string, value: string): unknown;
};

export type AuthState = {
  organizationId: number | null;
  session: AuthSession | null;
  status: "anonymous" | "authenticated";
  user: AuthSession["user"] | null;
};

export type AuthStore = {
  getState(): AuthState;
  subscribe(listener: () => void): () => void;
  commitUser(user: AuthSession["user"]): void;
  commitToken(token: AuthSession["token"]): void;
  login(request: LoginRequest): Promise<AuthSession>;
  logout(): Promise<void>;
  switchOrganization(request: SwitchOrganizationRequest): Promise<AuthSession>;
};

type AuthStoreOptions = {
  onOrganizationChange?: (previousOrganizationId: number, nextOrganizationId: number) => void;
  service: AuthService;
  storage?: AuthStorage;
};

function readInitialSession(storage: AuthStorage): AuthSession | null {
  try {
    const raw = storage.getItem(authStorageKey);
    return raw ? (JSON.parse(raw) as AuthSession) : null;
  } catch {
    storage.removeItem(authStorageKey);
    return null;
  }
}

function stateFromSession(session: AuthSession | null): AuthState {
  return {
    organizationId: session?.token.organization_id ?? null,
    session,
    status: session ? "authenticated" : "anonymous",
    user: session?.user ?? null,
  };
}

export function createAuthStore(options: AuthStoreOptions): AuthStore {
  const maybeStorage =
    options.storage ??
    (typeof window !== "undefined" ? window.sessionStorage : undefined);
  if (!maybeStorage) {
    throw new Error("Auth store requires sessionStorage in browser runtime.");
  }
  const storage: AuthStorage = maybeStorage;

  let state = stateFromSession(readInitialSession(storage));
  const listeners = new Set<() => void>();

  function notify() {
    listeners.forEach((listener) => listener());
  }

  function commitSession(session: AuthSession) {
    storage.setItem(authStorageKey, JSON.stringify(session));
    state = stateFromSession(session);
    notify();
  }

  function clearSession() {
    storage.removeItem(authStorageKey);
    state = stateFromSession(null);
    notify();
  }

  return {
    getState() {
      return state;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    commitUser(user) {
      if (state.session) {
        commitSession({ ...state.session, user });
        return;
      }
      state = {
        organizationId: user.organization_id,
        session: null,
        status: "authenticated",
        user,
      };
      notify();
    },
    commitToken(token) {
      if (!state.session) return;
      commitSession({ ...state.session, token });
    },
    async login(request) {
      const session = await options.service.login(request);
      commitSession(session);
      return session;
    },
    async logout() {
      const refreshToken = state.session?.token.refresh_token;
      try {
        if (refreshToken) {
          await options.service.logout({ refresh_token: refreshToken });
        }
      } finally {
        clearSession();
      }
    },
    async switchOrganization(request) {
      const previousOrganizationId = state.organizationId;
      const nextSession = await options.service.switchOrganization(request);
      commitSession(nextSession);
      if (
        previousOrganizationId !== null &&
        previousOrganizationId !== nextSession.token.organization_id
      ) {
        options.onOrganizationChange?.(
          previousOrganizationId,
          nextSession.token.organization_id,
        );
      }
      return nextSession;
    },
  };
}
