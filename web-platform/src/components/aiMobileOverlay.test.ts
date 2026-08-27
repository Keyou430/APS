import { beforeEach, describe, expect, it } from "vitest";
import { createAiMobileOverlayController } from "../app/aiMobileOverlay";

describe("ai mobile overlay accessibility", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="aiLeft"></div>
      <button id="aiMobileToggle">Open</button>
      <div id="aiMobileOverlay" hidden></div>
    `;
  });

  it("keeps the left panel interactive on desktop render", () => {
    const trigger = document.getElementById("aiMobileToggle") as HTMLButtonElement;
    const left = document.getElementById("aiLeft") as HTMLDivElement;
    const overlay = document.getElementById("aiMobileOverlay") as HTMLDivElement;

    const controller = createAiMobileOverlayController({
      getLeft: () => left,
      getOverlay: () => overlay,
      getToggle: () => trigger,
      isMobile: () => false,
    });

    controller.render();

    expect(left.inert).toBe(false);
    expect(left.getAttribute("aria-hidden")).toBe("false");
    expect(left.getAttribute("role")).toBeNull();
    expect(overlay.hidden).toBe(true);
  });

  it("exposes open and closed state for assistive tech and restores focus", async () => {
    const trigger = document.getElementById("aiMobileToggle") as HTMLButtonElement;
    const left = document.getElementById("aiLeft") as HTMLDivElement;
    const overlay = document.getElementById("aiMobileOverlay") as HTMLDivElement;
    trigger.focus();

    const controller = createAiMobileOverlayController({
      getLeft: () => left,
      getOverlay: () => overlay,
      getToggle: () => trigger,
      isMobile: () => true,
    });

    controller.toggle();
    expect(left.classList.contains("open")).toBe(true);
    expect(overlay.hidden).toBe(false);
    expect(overlay.getAttribute("aria-hidden")).toBe("false");
    expect(overlay.inert).toBe(false);

    controller.toggle();
    expect(left.classList.contains("open")).toBe(false);
    expect(overlay.hidden).toBe(true);
    expect(overlay.getAttribute("aria-hidden")).toBe("true");
    expect(overlay.inert).toBe(true);
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps the desktop panel interactive", () => {
    const trigger = document.getElementById("aiMobileToggle") as HTMLButtonElement;
    const left = document.getElementById("aiLeft") as HTMLDivElement;
    const overlay = document.getElementById("aiMobileOverlay") as HTMLDivElement;
    const controller = createAiMobileOverlayController({
      getLeft: () => left,
      getOverlay: () => overlay,
      getToggle: () => trigger,
      isMobile: () => false,
    });

    controller.render();

    expect(left.inert).toBe(false);
    expect(left.getAttribute("aria-hidden")).toBe("false");
    expect(left.hasAttribute("aria-modal")).toBe(false);
    expect(overlay.hidden).toBe(true);
  });
});
