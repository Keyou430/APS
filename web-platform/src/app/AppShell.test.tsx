import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AppRuntime } from "./appRuntime";
import { AppShell } from "./AppShell";
import { createUiStore } from "./uiStore";

function createRuntime(initialUsername = "alice") {
  let username: string | null = initialUsername;
  const authListeners = new Set<() => void>();
  const ui = createUiStore({ sidebarWidth: 230 });
  const runtime = {
    auth: {
      store: {
        getState: () => ({
          organizationId: 7,
          session: null,
          status: username ? "authenticated" : "anonymous",
          user: username ? { username } : null,
        }),
        subscribe: (listener: () => void) => {
          authListeners.add(listener);
          return () => authListeners.delete(listener);
        },
      },
    },
    ui,
  } as unknown as AppRuntime;

  return {
    runtime,
    setUsername(nextUsername: string | null) {
      username = nextUsername;
      act(() => authListeners.forEach((listener) => listener()));
    },
  };
}

describe("AppShell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the legacy visual shell structure", () => {
    const { container } = render(
      <AppShell pathname="/">
        <div>Dashboard content</div>
      </AppShell>,
    );

    expect(container.querySelector(".app-shell")).toBeInTheDocument();
    expect(container.querySelector(".module-sidebar")).toBeInTheDocument();
    expect(container.querySelector(".content-area")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("navigates to account management through browser history", async () => {
    const user = userEvent.setup();
    const pushState = vi.spyOn(window.history, "pushState");
    render(<AppShell pathname="/">Dashboard content</AppShell>);

    await user.click(screen.getByRole("button", { name: "账号管理" }));

    expect(pushState).toHaveBeenCalledWith({}, "", "/admin");
  });

  it("updates the signed-in user without an organization change", () => {
    const auth = createRuntime();
    render(
      <AppShell pathname="/" runtime={auth.runtime}>
        Dashboard content
      </AppShell>,
    );

    expect(screen.getAllByText("alice")).toHaveLength(2);
    auth.setUsername("bob");
    expect(screen.getAllByText("bob")).toHaveLength(2);
  });

  it("resizes the sidebar with keyboard controls and respects bounds", async () => {
    const user = userEvent.setup();
    const { runtime } = createRuntime();
    render(
      <AppShell pathname="/" runtime={runtime}>
        Dashboard content
      </AppShell>,
    );
    const separator = screen.getByRole("separator", {
      name: "调整模块侧边栏宽度",
    });

    separator.focus();
    await user.keyboard("{ArrowRight}");
    expect(separator).toHaveAttribute("aria-valuenow", "240");
    await user.keyboard("{Home}");
    expect(separator).toHaveAttribute("aria-valuenow", "180");
    await user.keyboard("{ArrowLeft}");
    expect(separator).toHaveAttribute("aria-valuenow", "180");
    await user.keyboard("{End}");
    expect(separator).toHaveAttribute("aria-valuenow", "380");
    await user.keyboard("{ArrowRight}");
    expect(separator).toHaveAttribute("aria-valuenow", "380");
  });

  it("removes active resize listeners when the shell unmounts", () => {
    const { runtime } = createRuntime();
    const setSidebarWidth = vi.spyOn(runtime.ui, "setSidebarWidth");
    const view = render(
      <AppShell pathname="/" runtime={runtime}>
        Dashboard content
      </AppShell>,
    );
    const separator = screen.getByRole("separator", {
      name: "调整模块侧边栏宽度",
    });

    fireEvent.pointerDown(separator, { clientX: 100 });
    view.unmount();
    fireEvent.pointerMove(window, { clientX: 200 });

    expect(setSidebarWidth).not.toHaveBeenCalled();
  });
});
