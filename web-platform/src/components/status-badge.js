/**
 * StatusBadge — colored status chip component.
 *
 * Registered as ``window.App.components.statusBadge``.
 * Usage:
 *   App.components.statusBadge.render("active")           → HTML string
 *   App.components.statusBadge.render("active", "small")  → with size variant
 */

(function () {
  "use strict";

  // ── Color map ────────────────────────────────────────────────────────
  var STATUS_COLORS = {
    // Status
    active:     { bg: "var(--green-soft)", fg: "var(--green)" },
    inactive:   { bg: "#f1f3f5",           fg: "var(--subtle)" },
    disabled:   { bg: "#f1f3f5",           fg: "var(--subtle)" },
    pending:    { bg: "var(--orange-soft)", fg: "var(--orange)" },
    completed:  { bg: "var(--green-soft)", fg: "var(--green)" },
    processing: { bg: "var(--blue-soft)",  fg: "var(--blue)" },
    cancelled:  { bg: "var(--red-soft)",   fg: "var(--red)" },
    closed:     { bg: "#f1f3f5",           fg: "var(--muted)" },

    // Decision
    allow:      { bg: "var(--green-soft)", fg: "var(--green)" },
    deny:       { bg: "var(--red-soft)",   fg: "var(--red)" },
    blocked:    { bg: "var(--red-soft)",   fg: "var(--red)" },
    passed:     { bg: "var(--green-soft)", fg: "var(--green)" },

    // Role / type
    system:     { bg: "#ede9fe",           fg: "var(--purple)" },
    custom:     { bg: "var(--blue-soft)",  fg: "var(--blue)" },
    admin:      { bg: "var(--red-soft)",   fg: "var(--red)" },
    user:       { bg: "var(--blue-soft)",  fg: "var(--blue)" },

    // Generic
    true:       { bg: "var(--green-soft)", fg: "var(--green)" },
    false:      { bg: "var(--red-soft)",   fg: "var(--red)" },
  };

  var LABELS = {
    active: "激活", inactive: "停用", disabled: "禁用",
    pending: "待处理", completed: "已完成", processing: "处理中",
    cancelled: "已取消", closed: "已关闭",
    allow: "允许", deny: "拒绝", blocked: "已拦截", passed: "通过",
    system: "系统", custom: "自定义", admin: "管理员", user: "用户",
    "true": "是", "false": "否",
  };

  /**
   * Render a status badge.
   * @param {string} status - The status key (e.g. "active", "pending")
   * @param {string} [size=""] - Optional size variant: "small", "large"
   * @param {string} [label] - Override the display label
   * @returns {string} HTML string
   */
  function render(status, size, label) {
    var key = String(status || "").toLowerCase();
    var colors = STATUS_COLORS[key] || { bg: "#f1f3f5", fg: "var(--subtle)" };
    var text = label || LABELS[key] || key || "—";
    var sizeClass = size ? " badge-" + size : "";
    return (
      '<span class="status-badge' + sizeClass + '" style="background:' + colors.bg + ';color:' + colors.fg + ';">' +
      escapeHtml(text) +
      "</span>"
    );
  }

  /**
   * Render a boolean badge (true/false).
   */
  function renderBool(value, trueLabel, falseLabel) {
    var key = value ? "true" : "false";
    var colors = STATUS_COLORS[key];
    var text = value ? (trueLabel || "是") : (falseLabel || "否");
    return (
      '<span class="status-badge" style="background:' + colors.bg + ';color:' + colors.fg + ';">' +
      escapeHtml(text) +
      "</span>"
    );
  }

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
    window.App.components.statusBadge = {
      render: render,
      renderBool: renderBool,
      COLORS: STATUS_COLORS,
      LABELS: LABELS,
    };
  }
})();
