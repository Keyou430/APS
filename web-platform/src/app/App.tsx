import { useCallback, useSyncExternalStore } from "react";
import { LegacyWorkspaceHost } from "./LegacyWorkspaceHost";
import { AppShell } from "./AppShell";
import type { AppRuntime } from "./appRuntime";
import { isReactOwnedRoute, resolveRoute, type AppRoute } from "./routes";
import { DashboardPage } from "../pages/DashboardPage";
import { HermesPage } from "../pages/HermesPage";
import { InvitationsPage } from "../pages/InvitationsPage";
import { OrganizationPage } from "../pages/OrganizationPage";
import { PipelinePage } from "../pages/PipelinePage";
import { PortalPage } from "../pages/PortalPage";
import { UsersPage } from "../pages/UsersPage";
import { ChatPage } from "../pages/ChatPage";
import { KnowledgePage } from "../pages/KnowledgePage";

export type AppProps = {
  pathname?: string;
  runtime?: AppRuntime;
};

function resolveRuntime(runtime?: AppRuntime): AppRuntime | null {
  if (runtime) return runtime;
  return typeof window === "undefined" ? null : window.__agentRuntime ?? null;
}

export function App({ pathname = "/", runtime }: AppProps) {
  const activeRoute: AppRoute = resolveRoute(pathname);
  const appRuntime = resolveRuntime(runtime);
  const authStore = appRuntime?.auth.store;
  const subscribe = useCallback(
    (listener: () => void) => authStore?.subscribe(listener) ?? (() => undefined),
    [authStore],
  );
  const getOrganizationId = useCallback(
    () => authStore?.getState().organizationId ?? null,
    [authStore],
  );
  const organizationId = useSyncExternalStore(
    subscribe,
    getOrganizationId,
    getOrganizationId,
  );

  if (
    !appRuntime ||
    activeRoute.status !== "react-ready" ||
    !isReactOwnedRoute(pathname)
  ) {
    return (
      <div data-active-route={activeRoute.id} data-entry="react-route-shell">
        <LegacyWorkspaceHost routeId={activeRoute.id} />
      </div>
    );
  }

  const routeContent = (() => {

    if (activeRoute.id === "dashboard") {
      return (
        <DashboardPage
          cache={appRuntime.auth.cache}
          organizationId={organizationId}
          service={appRuntime.services.dashboard}
        />
      );
    }

    if (activeRoute.id === "portal") {
      return (
        <PortalPage
          cache={appRuntime.auth.cache}
          organizationId={organizationId}
          service={appRuntime.services.enterprise}
        />
      );
    }

    if (activeRoute.id === "chat") {
      return <ChatPage cache={appRuntime.auth.cache} knowledgeService={appRuntime.services.knowledge} organizationId={organizationId} service={appRuntime.services.chat} stream={appRuntime.services.chatStream} />;
    }

    if (activeRoute.id === "knowledge") {
      return <KnowledgePage cache={appRuntime.auth.cache} organizationId={organizationId} service={appRuntime.services.knowledge} />;
    }

    if (activeRoute.id === "pipeline") {
      return (
        <PipelinePage
          cache={appRuntime.auth.cache}
          organizationId={organizationId}
          service={appRuntime.services.pipeline}
        />
      );
    }

    if (activeRoute.id === "hermes") {
      return (
        <HermesPage
          cache={appRuntime.auth.cache}
          organizationId={organizationId}
          service={appRuntime.services.hermes}
        />
      );
    }

    if (activeRoute.id === "organization") {
      return (
        <OrganizationPage
          cache={appRuntime.auth.cache}
          organizationId={organizationId}
          service={appRuntime.services.organization}
        />
      );
    }

    if (activeRoute.id === "users") {
      return (
        <UsersPage
          cache={appRuntime.auth.cache}
          organizationId={organizationId}
          service={appRuntime.services.users}
        />
      );
    }

    if (activeRoute.id === "invitations") {
      return (
        <InvitationsPage
          cache={appRuntime.auth.cache}
          organizationId={organizationId}
          service={appRuntime.services.invitations}
        />
      );
    }

    return <LegacyWorkspaceHost routeId={activeRoute.id} />;
  })();

  return (
    <div
      data-entry="react-route-shell"
      data-active-route={activeRoute.id}
    >
      <AppShell pathname={pathname} runtime={appRuntime}>
        {routeContent}
      </AppShell>
    </div>
  );
}
