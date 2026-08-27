/**
 * App entry point — sets up the shared runtime before the inline script runs.
 *
 * Vite serves this as a module; it executes after DOM parse but before
 * DOMContentLoaded.  The inline <script> further down index.html reads
 * window.__auth and window.__agentRuntime once they're ready.
 */

import { installAppRuntime } from "./app/appRuntime";
import { installAppShellScale } from "./app/appShellScale.js";
import { mountReactApp } from "./app/mountReactApp";

// Import authContext to trigger the side-effect that creates window.__auth
import './auth/authContext';

// Import permissions module for side-effect (exposes helpers)
import { hasPermission, hasRole, isAuthenticated, PERM, ROLE } from './auth/permissions';

// Import Gridstack CSS for portal system grid
import 'gridstack/dist/gridstack.min.css';

if (typeof window !== "undefined") {
  installAppRuntime(window);
  installAppShellScale();
}

if (typeof document !== "undefined") {
  const root = document.getElementById("reactAppRoot");
  if (root) {
    mountReactApp(root);
  }
}

// Expose permissions globally for vanilla JS access in index.html
if (typeof window !== "undefined") {
  const win = window as unknown as Record<string, unknown>;
  win.__perm = { hasPermission, hasRole, isAuthenticated, PERM, ROLE };
}
