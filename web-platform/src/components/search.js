/**
 * Search — async typeahead with debounce, keyboard navigation, and category grouping.
 *
 * Registered as ``window.App.components.search``.
 * Usage:
 *   App.components.search.init(inputElement, {
 *     onSearch: async function(query) { return [{ title, type, href, status }]; },
 *     minChars: 2, debounceMs: 250, maxResults: 20,
 *   })
 */

(function () {
  "use strict";

  var _input = null;
  var _dropdown = null;
  var _config = {};
  var _debounceTimer = null;
  var _selectedIndex = -1;
  var _results = [];

  var TYPE_ICONS = {
    subsystem: "i-grid", notice: "i-bullhorn", document: "i-file",
    resource: "i-folder", service: "i-briefcase", repair: "i-wrench",
    asset: "i-box", oa: "i-clipboard", hr: "i-users",
    finance: "i-credit-card", news: "i-newspaper",
  };

  var TYPE_LABELS = {
    subsystem: "子系统", notice: "公告", document: "文档", resource: "资源",
    service: "服务", repair: "报修", asset: "资产", oa: "OA流程",
    hr: "人事", finance: "财务", news: "资讯",
  };

  function init(inputEl, config) {
    _input = typeof inputEl === "string" ? document.querySelector(inputEl) : inputEl;
    if (!_input) return;
    _config = config || {};
    ensureDropdown();

    _input.addEventListener("input", function () {
      var q = _input.value.trim();
      if (q.length < (_config.minChars || 2)) { hideDropdown(); return; }
      clearTimeout(_debounceTimer);
      _debounceTimer = setTimeout(function () {
        if (_config.onSearch) {
          _config.onSearch(q).then(function (results) {
            _results = results || [];
            _selectedIndex = -1;
            renderDropdown(_results);
          });
        }
      }, _config.debounceMs || 250);
    });

    _input.addEventListener("keydown", function (e) {
      if (!_dropdown.classList.contains("show")) return;
      if (e.key === "ArrowDown") { e.preventDefault(); _selectedIndex = Math.min(_selectedIndex + 1, _results.length - 1); updateSelection(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); _selectedIndex = Math.max(_selectedIndex - 1, -1); updateSelection(); }
      else if (e.key === "Enter") { e.preventDefault(); if (_selectedIndex >= 0 && _selectedIndex < _results.length) selectResult(_results[_selectedIndex]); }
      else if (e.key === "Escape") { hideDropdown(); }
    });

    _input.addEventListener("blur", function () { setTimeout(hideDropdown, 200); });
  }

  function ensureDropdown() {
    if (_dropdown) return;
    _dropdown = document.createElement("div");
    _dropdown.className = "search-dropdown";
    _dropdown.style.display = "none";
    _input.parentNode.appendChild(_dropdown);
  }

  function renderDropdown(results) {
    if (!results || results.length === 0) { hideDropdown(); return; }

    var groups = {};
    for (var i = 0; i < results.length; i++) {
      var type = results[i].type || "other";
      if (!groups[type]) groups[type] = [];
      groups[type].push(results[i]);
    }

    var html = "";
    var groupKeys = Object.keys(groups);
    for (var g = 0; g < groupKeys.length; g++) {
      var type = groupKeys[g];
      var items = groups[type];
      var label = TYPE_LABELS[type] || type;
      html += '<div class="search-group-label">' + label + '</div>';
      for (var j = 0; j < items.length; j++) {
        var item = items[j];
        var iconId = TYPE_ICONS[type] || "i-search";
        var badge = window.App && window.App.components && window.App.components.statusBadge
          ? window.App.components.statusBadge.render(item.status, "small") : "";
        html += (
          '<div class="search-result-item" data-search-idx="' + j + '" data-search-group="' + type + '">' +
          '<svg class="icon"><use href="#' + iconId + '"/></svg>' +
          '<div class="search-result-text">' +
          '<div class="search-result-title">' + highlight(item.title || "", _input.value) + '</div>' +
          (item.subtitle ? '<div class="search-result-subtitle">' + esc(item.subtitle) + '</div>' : "") +
          '</div>' + badge + '</div>'
        );
      }
    }

    _dropdown.innerHTML = html;
    _dropdown.style.display = "";
    _dropdown.classList.add("show");

    _dropdown.querySelectorAll(".search-result-item").forEach(function (el) {
      el.addEventListener("mousedown", function (e) {
        e.preventDefault();
        var idx = parseInt(el.getAttribute("data-search-idx"), 10);
        var grp = el.getAttribute("data-search-group");
        if (idx >= 0 && grp && groups[grp] && groups[grp][idx]) selectResult(groups[grp][idx]);
      });
    });
  }

  function updateSelection() {
    _dropdown.querySelectorAll(".search-result-item").forEach(function (el) { el.classList.remove("active"); });
    var active = _dropdown.querySelector('[data-search-idx="' + _selectedIndex + '"]');
    if (active) active.classList.add("active");
  }

  function selectResult(result) {
    hideDropdown();
    _input.value = result.title || "";
    if (_config.onSelect) _config.onSelect(result);
    else if (result.href) window.location.hash = result.href;
  }

  function hideDropdown() {
    if (_dropdown) { _dropdown.classList.remove("show"); _dropdown.style.display = "none"; }
    _selectedIndex = -1; _results = [];
  }

  function highlight(text, query) {
    if (!query) return esc(text);
    var escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return esc(text).replace(new RegExp("(" + escaped + ")", "gi"), '<mark>$1</mark>');
  }

  function esc(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── Register ─────────────────────────────────────────────────────────
  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.components = window.App.components || {};
    window.App.components.search = { init: init, hideDropdown: hideDropdown };
  }
})();
