/**
 * EmptyState — actionable empty state with illustration and CTA button.
 *
 * Registered as ``window.App.components.emptyState``.
 * Usage:
 *   App.components.emptyState.render({ message: "暂无数据", action: "新建", onClick: fn })
 *   App.components.emptyState.render({ message: "暂无数据" })  // no action button
 */

(function () {
  "use strict";

  /**
   * @param {Object} config
   * @param {string} config.message - Primary message (e.g. "暂无工单")
   * @param {string} [config.description] - Secondary description
   * @param {string} [config.action] - CTA button label
   * @param {string} [config.actionClass] - Additional button classes (e.g. "primary")
   * @param {string} [config.icon] - SVG icon href (without #)
   * @returns {string} HTML string
   */
  function render(config) {
    var opts = config || {};
    var message = escapeHtml(opts.message || "暂无数据");
    var description = opts.description ? '<div>' + escapeHtml(opts.description) + '</div>' : "";
    var actionHtml = "";
    if (opts.action) {
      var cls = "empty-action" + (opts.actionClass ? " " + opts.actionClass : "");
      var iconHtml = opts.icon ? icon(opts.icon) : "";
      actionHtml = '<button class="' + cls + '" data-empty-action>' + iconHtml + escapeHtml(opts.action) + '</button>';
    }
    return (
      '<div class="empty-state">' +
      "<div>" +
      '<div class="empty-illustration"></div>' +
      "<strong>" + message + "</strong>" +
      description +
      actionHtml +
      "</div>" +
      "</div>"
    );
  }

  /** Render into a DOM element, returning the CTA button for binding. */
  function renderInto(container, config) {
    if (typeof container === "string") {
      container = document.querySelector(container);
    }
    if (!container) return null;
    container.innerHTML = render(config);
    return container.querySelector("[data-empty-action]");
  }

  var ICON_SVG = '<svg class="icon"><use href="#%s"></use></svg>';
  function icon(id) { return ICON_SVG.replace("%s", id); }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Register ─────────────────────────────────────────────────────────
  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.components = window.App.components || {};
    window.App.components.emptyState = {
      render: render,
      renderInto: renderInto,
    };
  }
})();
