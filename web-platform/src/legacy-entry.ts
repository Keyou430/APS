import { GridStack } from "gridstack";
import "gridstack/dist/gridstack.min.css";
import { installAppShellScale } from "./app/appShellScale.js";
import { installAppRuntime } from "./app/appRuntime";
import { normalizeLocation } from "./app/location";
import { mountReactApp } from "./app/mountReactApp";
import { isReactOwnedRoute } from "./app/routes";

const legacyModuleImports = [
  () => import("./components/status-badge.js"),
  () => import("./components/empty-state.js"),
  () => import("./components/modal.js"),
  () => import("./components/table.js"),
  () => import("./components/drawer.js"),
  () => import("./components/notification-bell.js"),
  () => import("./components/sidebar.js"),
  () => import("./components/search.js"),
  () => import("./views/repair.js"),
  () => import("./views/oa.js"),
  () => import("./views/hr.js"),
  () => import("./views/finance.js"),
  () => import("./views/data-portal.js"),
  () => import("./app.js"),
];

let legacyModulesPromise: Promise<unknown[]> | null = null;

function loadLegacyModules() {
  legacyModulesPromise ??= Promise.all(legacyModuleImports.map((load) => load()));
  return legacyModulesPromise;
}

function isCurrentRouteReactOwned() {
  return isReactOwnedRoute(normalizeLocation(window.location));
}

function syncRouteActivation(shellRoot: HTMLElement) {
  const reactOwnedRoute = isCurrentRouteReactOwned();
  shellRoot.hidden = !reactOwnedRoute;
  document.body.classList.toggle("react-route-active", reactOwnedRoute);
  if (!reactOwnedRoute) void loadLegacyModules();
}

const reactOwnedRoute =
  typeof window !== "undefined" && isCurrentRouteReactOwned();

if (typeof window !== "undefined") {
  (window as unknown as { GridStack?: typeof GridStack }).GridStack = GridStack;
  installAppRuntime(window);
}

installAppShellScale();

if (typeof document !== "undefined") {
  const shellRoot = document.createElement("div");
  shellRoot.id = "reactAppRoot";
  shellRoot.hidden = !reactOwnedRoute;
  document.body.classList.toggle("react-route-active", reactOwnedRoute);
  document.body.prepend(shellRoot);
  mountReactApp(shellRoot);
  window.addEventListener("popstate", () => syncRouteActivation(shellRoot));
}

if (!reactOwnedRoute) {
  await loadLegacyModules();
}
