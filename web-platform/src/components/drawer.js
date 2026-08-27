/**
 * Drawer — slide-in drawer from the right, intended for forms and detail panels.
 *
 * Registered as ``window.App.components.drawer``.
 * Usage:
 *   App.components.drawer.open({ title: "编辑", body: "<form>...</form>", onClose: fn })
 *   App.components.drawer.close()
 */

(function () {
  "use strict";

  var _overlay = null;
  var _drawer = null;
  var _onClose = null;
  var _lastFocus = null;

  function ensureElements() {
    if (_overlay) return;
    _overlay = document.createElement("div");
    _overlay.className = "drawer-overlay";
    _overlay.innerHTML = '<div class="drawer-panel" role="dialog" aria-modal="true" aria-labelledby="drawerTitle"><div class="drawer-header"><h2 class="drawer-title" id="drawerTitle"></h2><button class="drawer-close" data-drawer-close aria-label="关闭">' +
      '<svg class="icon" width="18" height="18"><use href="#i-xmark"/></svg></button></div><div class="drawer-body"></div></div>';
    document.body.appendChild(_overlay);
    _drawer = _overlay.querySelector(".drawer-panel");

    // Close on overlay click
    _overlay.addEventListener("click", function (e) {
      if (e.target === _overlay) close();
    });
    // Close on ESC
    _overlay.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); close(); }
    });
    // Close button
    _overlay.querySelector("[data-drawer-close]").addEventListener("click", function () {
      close();
    });
  }

  function open(config) {
    ensureElements();
    var opts = config || {};
    _lastFocus = document.activeElement;
    _overlay.querySelector(".drawer-title").textContent = opts.title || "";
    _overlay.querySelector(".drawer-body").innerHTML = opts.body || "";
    _onClose = opts.onClose || null;
    _overlay.classList.add("show");
    document.body.classList.add("drawer-open");

    // Focus first input
    var firstInput = _drawer.querySelector("input, textarea, select, button");
    if (firstInput) setTimeout(function () { firstInput.focus(); }, 100);
  }

  function close() {
    if (!_overlay) return;
    _overlay.classList.remove("show");
    document.body.classList.remove("drawer-open");
    if (_lastFocus && typeof _lastFocus.focus === "function") {
      try { _lastFocus.focus(); } catch (e) { /* element may be removed */ }
    }
    _lastFocus = null;
    if (_onClose) {
      var cb = _onClose;
      _onClose = null;
      cb();
    }
  }

  function isOpen() {
    return _overlay ? _overlay.classList.contains("show") : false;
  }

  function setBody(html) {
    if (_overlay) _overlay.querySelector(".drawer-body").innerHTML = html;
  }

  // ── Register ─────────────────────────────────────────────────────────
  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.components = window.App.components || {};
    window.App.components.drawer = {
      open: open,
      close: close,
      isOpen: isOpen,
      setBody: setBody,
    };
  }
})();
