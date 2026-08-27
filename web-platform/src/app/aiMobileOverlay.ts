type AiMobileOverlayControllerGetters = {
  getLeft: () => HTMLElement | null;
  getOverlay: () => HTMLElement | null;
  getToggle: () => HTMLElement | null;
  isMobile: () => boolean;
};

function isMobileViewport() {
  if (typeof window === "undefined") return false;
  if (typeof window.matchMedia === "function") {
    return window.matchMedia("(max-width: 767px)").matches;
  }
  return window.innerWidth <= 767;
}

export function createAiMobileOverlayController(
  getters: AiMobileOverlayControllerGetters,
) {
  let lastFocus: Element | null = null;

  function syncState(isOpen: boolean) {
    const left = getters.getLeft();
    const overlay = getters.getOverlay();
    const toggle = getters.getToggle();
    const isMobile = getters.isMobile();
    const mobilePanelOpen = isMobile && isOpen;

    if (left) {
      left.classList.toggle("open", mobilePanelOpen);
      if (isMobile) {
        left.setAttribute("role", "dialog");
        left.setAttribute("aria-modal", "true");
      } else {
        left.removeAttribute("role");
        left.removeAttribute("aria-modal");
      }
      left.setAttribute("aria-hidden", String(isMobile && !mobilePanelOpen));
      left.inert = isMobile && !mobilePanelOpen;
    }
    if (overlay) {
      overlay.hidden = !mobilePanelOpen;
      overlay.setAttribute("aria-hidden", String(!mobilePanelOpen));
      overlay.inert = !mobilePanelOpen;
    }
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(mobilePanelOpen));
      toggle.setAttribute(
        "aria-label",
        mobilePanelOpen ? "关闭 AI 移动面板" : "打开 AI 移动面板",
      );
    }
  }

  function syncDesktopState() {
    const left = getters.getLeft();
    const overlay = getters.getOverlay();
    const toggle = getters.getToggle();

    if (left) {
      left.classList.remove("open");
      left.removeAttribute("role");
      left.removeAttribute("aria-modal");
      left.setAttribute("aria-hidden", "false");
      left.inert = false;
    }
    if (overlay) {
      overlay.hidden = true;
      overlay.setAttribute("aria-hidden", "true");
      overlay.inert = true;
    }
    if (toggle) {
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "打开 AI 移动面板");
    }
  }

  function focusPanel() {
    const left = getters.getLeft();
    if (!left) return;
    const firstFocusable = left.querySelector<HTMLElement>(
      "input, textarea, select, button, a[href], [tabindex]:not([tabindex='-1'])",
    );
    if (firstFocusable && typeof firstFocusable.focus === "function") {
      firstFocusable.focus();
    } else {
      left.setAttribute("tabindex", "-1");
      left.focus();
    }
  }

  function render() {
    const left = getters.getLeft();
    if (!left) return;
    if (isMobileViewport()) {
      syncState(left.classList.contains("open"));
      return;
    }
    syncDesktopState();
  }

  function toggle() {
    if (!getters.isMobile()) {
      syncState(false);
      return false;
    }
    const left = getters.getLeft();
    if (!left) return false;
    const isOpen = !left.classList.contains("open");
    if (isOpen) {
      lastFocus = document.activeElement;
      syncState(true);
      focusPanel();
      return true;
    }

    syncState(false);
    if (lastFocus instanceof HTMLElement) {
      try {
        lastFocus.focus();
      } catch {
        /* focus target may be removed */
      }
    }
    lastFocus = null;
    return false;
  }

  return {
    render,
    toggle,
  };
}
