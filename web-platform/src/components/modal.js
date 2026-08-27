/**
 * Modal — accessible modal dialog with focus trap, ESC close, and ARIA.
 *
 * Registered as ``window.App.components.modal``.
 * Usage:
 *   App.components.modal.open("myModal")
 *   App.components.modal.close("myModal")
 *   App.components.modal.closeTop()
 */

(function () {
  "use strict";

  var _openModals = [];
  var _lastFocus = null;

  // ── Public API ───────────────────────────────────────────────────────

  /** Open a modal by its backdrop id. */
  function open(id) {
    var backdrop = getEl(id);
    if (!backdrop) return;
    _lastFocus = document.activeElement;
    backdrop.classList.add("show");
    _openModals.push(id);
    trapFocus(backdrop);
    bindClose(backdrop, id);
    document.addEventListener("keydown", onKeyDown);
  }

  /** Close a modal by its backdrop id. */
  function close(id) {
    var backdrop = getEl(id);
    if (!backdrop) return;
    backdrop.classList.remove("show");
    _openModals = _openModals.filter(function (x) { return x !== id; });
    if (_openModals.length === 0) {
      document.removeEventListener("keydown", onKeyDown);
    }
    if (_lastFocus) {
      try { _lastFocus.focus(); } catch (e) { /* element may be removed */ }
      _lastFocus = null;
    }
  }

  /** Close the top-most open modal. */
  function closeTop() {
    if (_openModals.length > 0) {
      close(_openModals[_openModals.length - 1]);
    }
  }

  /** Check if a modal is currently open. */
  function isOpen(id) {
    var backdrop = getEl(id);
    return backdrop ? backdrop.classList.contains("show") : false;
  }

  // ── Focus trap ───────────────────────────────────────────────────────

  function trapFocus(backdrop) {
    var focusable = backdrop.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length > 0) {
      setTimeout(function () { focusable[0].focus(); }, 50);
    }
    backdrop._focusable = focusable;
  }

  function onKeyDown(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeTop();
      return;
    }
    if (e.key === "Tab" && _openModals.length > 0) {
      var id = _openModals[_openModals.length - 1];
      var backdrop = getEl(id);
      if (!backdrop || !backdrop._focusable || backdrop._focusable.length === 0) return;
      var items = backdrop._focusable;
      var idx = Array.prototype.indexOf.call(items, document.activeElement);
      if (e.shiftKey) {
        if (idx <= 0) { e.preventDefault(); items[items.length - 1].focus(); }
      } else {
        if (idx >= items.length - 1 || idx === -1) { e.preventDefault(); items[0].focus(); }
      }
    }
  }

  // ── Close binding ────────────────────────────────────────────────────

  function bindClose(backdrop, id) {
    if (backdrop._closeBound) return;
    // Click backdrop (not modal content) to close
    backdrop.addEventListener("click", function (e) {
      if (e.target === backdrop) close(id);
    });
    // Close buttons inside the modal
    backdrop.querySelectorAll("[data-modal-close]").forEach(function (btn) {
      btn.addEventListener("click", function () { close(id); });
    });
    backdrop._closeBound = true;
  }

  // ── Helpers ──────────────────────────────────────────────────────────

  function getEl(id) {
    return typeof id === "string" ? document.getElementById(id) : id;
  }

  // ── Register ─────────────────────────────────────────────────────────
  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.components = window.App.components || {};
    window.App.components.modal = {
      open: open,
      close: close,
      closeTop: closeTop,
      isOpen: isOpen,
    };
  }
})();
