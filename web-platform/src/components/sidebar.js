/**
 * Sidebar — data-driven module sidebar.
 *
 * Registered as ``window.App.components.sidebar``.
 * Renders from a subsystem list and menu_items_json config.
 *
 * Usage:
 *   App.components.sidebar.render(container, {
 *     title: "报修系统",
 *     items: [{ code: "tickets", label: "工单管理", icon: "i-ticket", href: "#subsystem/repair/tickets" }],
 *     sections: [{ label: "业务操作", items: [...] }],
 *     onNavigate: function(item) { ... }
 *   })
 */

(function () {
  "use strict";

  function render(container, config) {
    if (typeof container === "string") {
      container = document.querySelector(container);
    }
    if (!container) return;

    var opts = config || {};
    var html = "";

    // Header
    html += '<div class="sidebar-head">';
    html += '<span class="side-title">' + esc(opts.title || "") + '</span>';
    html += '<button class="sidebar-toggle" aria-expanded="true" aria-label="折叠侧栏"><svg class="icon" width="14" height="14"><use href="#i-chevron-left"/></svg></button>';
    html += '</div>';

    // Items
    if (opts.sections && opts.sections.length > 0) {
      for (var s = 0; s < opts.sections.length; s++) {
        var section = opts.sections[s];
        html += '<div class="side-section">' + esc(section.label || "") + '</div>';
        for (var i = 0; i < (section.items || []).length; i++) {
          html += renderItem(section.items[i], opts);
        }
      }
    } else if (opts.items && opts.items.length > 0) {
      for (var j = 0; j < opts.items.length; j++) {
        html += renderItem(opts.items[j], opts);
      }
    }

    // Footer
    if (opts.footer) {
      html += '<div class="sidebar-foot">';
      html += '<div class="sidebar-avatar">' + esc(opts.footer.avatar || "?") + '</div>';
      html += '<span class="sidebar-name">' + esc(opts.footer.name || "") + '</span>';
      html += '</div>';
    }

    container.innerHTML = html;
    bindEvents(container, opts);
  }

  function renderItem(item, opts) {
    var activeClass = (opts.activeCode && item.code === opts.activeCode) ? " active" : "";
    var iconHtml = item.icon ? '<svg class="icon"><use href="#' + item.icon + '"/></svg>' : "";
    var badgeHtml = item.badge ? '<small>' + esc(String(item.badge)) + '</small>' : "";
    var href = item.href || "";
    return (
      '<button class="side-link' + activeClass + '" data-nav-code="' + esc(item.code || "") + '" data-nav-href="' + esc(href) + '">' +
      iconHtml + '<span>' + esc(item.label || item.code || "") + '</span>' + badgeHtml +
      '</button>'
    );
  }

  function bindEvents(container, opts) {
    var toggleBtn = container.querySelector(".sidebar-toggle");
    syncCollapsedState(container, false);
    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        document.body.classList.toggle("sidebar-collapsed");
        var sidebar = container.closest(".module-sidebar");
        var collapsed = sidebar ? sidebar.classList.toggle("collapsed") : document.body.classList.contains("sidebar-collapsed");
        syncCollapsedState(container, collapsed);
      });
    }

    container.querySelectorAll("[data-nav-code]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var code = btn.getAttribute("data-nav-code");
        var href = btn.getAttribute("data-nav-href");

        container.querySelectorAll(".side-link.active").forEach(function (el) {
          el.classList.remove("active");
        });
        btn.classList.add("active");

        if (opts.onNavigate) {
          opts.onNavigate({ code: code, href: href });
        } else if (href) {
          window.location.hash = href;
        }
      });
    });
  }

  function syncCollapsedState(container, collapsed) {
    var sidebar = container.closest(".module-sidebar");
    var toggleBtn = container.querySelector(".sidebar-toggle");
    if (toggleBtn) {
      toggleBtn.setAttribute("aria-expanded", String(!collapsed));
      toggleBtn.setAttribute("aria-label", collapsed ? "展开侧栏" : "折叠侧栏");
    }
    if (sidebar) {
      sidebar.setAttribute("aria-hidden", String(collapsed));
      sidebar.inert = Boolean(collapsed);
    }
  }

  function setActive(container, code) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;
    container.querySelectorAll(".side-link.active").forEach(function (el) {
      el.classList.remove("active");
    });
    var target = container.querySelector('[data-nav-code="' + code + '"]');
    if (target) target.classList.add("active");
  }

  function esc(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── Register ─────────────────────────────────────────────────────────
  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.components = window.App.components || {};
    window.App.components.sidebar = {
      render: render,
      setActive: setActive,
    };
  }
})();
