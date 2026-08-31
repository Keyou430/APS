import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { App } from "./App";

let reactRoot: Root | null = null;

export function mountReactApp(target: HTMLElement): Root {
  reactRoot = createRoot(target);
  reactRoot.render(createElement(App, { pathname: window.location.pathname }));
  return reactRoot;
}

export function getMountedReactRoot(): Root | null {
  return reactRoot;
}
