import { beforeEach, describe, expect, it } from "vitest";
import "./sidebar.js";

type SidebarComponent = {
  render: (
    container: HTMLElement,
    config: {
      items: Array<{ code: string; label: string }>;
      title: string;
    },
  ) => void;
};

function getSidebar(): SidebarComponent {
  return (window as unknown as { App: { components: { sidebar: SidebarComponent } } }).App
    .components.sidebar;
}

describe("legacy sidebar accessibility", () => {
  beforeEach(() => {
    document.body.className = "";
    document.body.innerHTML = "";
  });

  it("keeps collapsed state exposed to assistive technologies", () => {
    const shell = document.createElement("aside");
    shell.className = "module-sidebar";
    const container = document.createElement("div");
    shell.append(container);
    document.body.append(shell);

    getSidebar().render(container, {
      title: "服务中心",
      items: [{ code: "tickets", label: "工单" }],
    });

    const toggle = container.querySelector<HTMLButtonElement>(".sidebar-toggle");
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");
    expect(shell.getAttribute("aria-hidden")).toBe("false");
    expect(shell.inert).toBe(false);

    toggle?.click();

    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(shell.getAttribute("aria-hidden")).toBe("true");
    expect(shell.inert).toBe(true);
  });
});
