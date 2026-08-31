import { GridStack } from "gridstack";
import "gridstack/dist/gridstack.min.css";
import { ApiError } from "./api/client";
import { installAppShellScale } from "./app/appShellScale.js";
import { installAppRuntime } from "./app/appRuntime";
import { mountReactApp } from "./app/mountReactApp";
import { isReactOwnedRoute } from "./app/routes";

const reactOwnedRoute =
  typeof window !== "undefined" && isReactOwnedRoute(window.location.pathname);

if (typeof window !== "undefined") {
  (window as unknown as { GridStack?: typeof GridStack }).GridStack = GridStack;
  installAppRuntime(window);
  if (
    reactOwnedRoute &&
    window.__agentRuntime?.auth.store.getState().organizationId === null
  ) {
    try {
      await window.__contractAuth?.fetchMe();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        window.location.replace("/");
      }
    }
  }
}

installAppShellScale();

if (typeof document !== "undefined") {
  const shellRoot = document.createElement("div");
  shellRoot.id = "reactAppRoot";
  shellRoot.hidden = !reactOwnedRoute;
  document.body.classList.toggle("react-route-active", reactOwnedRoute);
  document.body.prepend(shellRoot);
  mountReactApp(shellRoot);
}

if (!reactOwnedRoute) {
  await import("./components/status-badge.js");
  await import("./components/empty-state.js");
  await import("./components/modal.js");
  await import("./components/table.js");
  await import("./components/drawer.js");
  await import("./components/notification-bell.js");
  await import("./components/sidebar.js");
  await import("./components/search.js");
  await import("./views/repair.js");
  await import("./views/oa.js");
  await import("./views/hr.js");
  await import("./views/finance.js");
  await import("./views/data-portal.js");
  await import("./app.js");
}
