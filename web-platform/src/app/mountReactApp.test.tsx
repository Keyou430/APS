import { act, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { getMountedReactRoot, mountReactApp } from "./mountReactApp";

describe("mountReactApp", () => {
  afterEach(() => {
    act(() => {
      getMountedReactRoot()?.unmount();
    });
    window.history.replaceState({}, "", "/");
  });

  it("updates the active route when browser history emits popstate", async () => {
    window.history.replaceState({}, "", "/portal");
    const target = document.createElement("div");
    document.body.append(target);
    act(() => {
      mountReactApp(target);
    });

    await waitFor(() =>
      expect(target.firstElementChild).toHaveAttribute(
        "data-active-route",
        "portal",
      ),
    );

    act(() => {
      window.history.pushState({}, "", "/admin");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    await waitFor(() =>
      expect(target.firstElementChild).toHaveAttribute(
        "data-active-route",
        "admin",
      ),
    );
    target.remove();
  });
});
