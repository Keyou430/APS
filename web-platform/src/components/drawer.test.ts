import { beforeEach, describe, expect, it, vi } from "vitest";
import "./drawer.js";

type DrawerComponent = {
  close: () => void;
  open: (config: { body: string; onClose?: () => void; title: string }) => void;
};

function getDrawer(): DrawerComponent {
  return (window as unknown as { App: { components: { drawer: DrawerComponent } } }).App
    .components.drawer;
}

describe("legacy drawer accessibility", () => {
  beforeEach(() => {
    document.body.className = "";
    document.body.innerHTML = "";
  });

  it("uses modal dialog semantics and restores focus after close", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Open";
    document.body.append(trigger);
    trigger.focus();

    const onClose = vi.fn();
    getDrawer().open({
      body: '<input aria-label="标题" />',
      onClose,
      title: "编辑项目",
    });

    const panel = document.querySelector<HTMLElement>(".drawer-panel");
    expect(panel?.getAttribute("role")).toBe("dialog");
    expect(panel?.getAttribute("aria-modal")).toBe("true");
    expect(panel?.getAttribute("aria-labelledby")).toBe("drawerTitle");
    expect(document.querySelector("#drawerTitle")?.textContent).toBe("编辑项目");

    getDrawer().close();

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(trigger);
  });
});
