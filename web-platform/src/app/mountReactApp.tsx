import { createElement, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { App } from "./App";
import { normalizeLocation } from "./location";

let reactRoot: Root | null = null;

function MountedApp() {
  const [pathname, setPathname] = useState(() => normalizeLocation(window.location));

  useEffect(() => {
    const handlePopState = () => setPathname(normalizeLocation(window.location));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  return createElement(App, { pathname });
}

export function mountReactApp(target: HTMLElement): Root {
  reactRoot = createRoot(target);
  reactRoot.render(createElement(MountedApp));
  return reactRoot;
}

export function getMountedReactRoot(): Root | null {
  return reactRoot;
}
