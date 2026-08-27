/**
 * DataTable — sortable, filterable, paginated table component.
 *
 * Registered as ``window.App.components.dataTable``.
 * Usage:
 *   App.components.dataTable.render(container, {
 *     columns: [{ key: "name", label: "名称", sortable: true, render: fn }],
 *     data: [...],
 *     page: 1, pageSize: 15, total: 100,
 *     onPageChange: fn, onSort: fn,
 *     emptyMessage: "暂无数据"
 *   })
 */

(function () {
  "use strict";

  /**
   * Render a data table into a container element.
   * @param {Element|string} container
   * @param {Object} config
   */
  function render(container, config) {
    if (typeof container === "string") {
      container = document.querySelector(container);
    }
    if (!container) return;

    var opts = config || {};
    var columns = opts.columns || [];
    var data = opts.data || [];
    var page = opts.page || 1;
    var pageSize = opts.pageSize || 15;
    var total = opts.total != null ? opts.total : data.length;

    var html = "";

    // Toolbar: count + search if filterable
    if (opts.showToolbar !== false) {
      html += '<div class="table-toolbar">';
      html += '<span class="table-count">共 <strong>' + total + '</strong> 条</span>';
      if (opts.filterable && opts.onFilter) {
        html += '<input class="table-filter-input" type="text" placeholder="搜索..." data-table-filter />';
      }
      html += '</div>';
    }

    // Table
    html += '<div class="table-wrap"><table class="data-table"><thead><tr>';
    var sortKey = opts.sortKey || "";
    var sortDir = opts.sortDir || "asc";
    for (var i = 0; i < columns.length; i++) {
      var col = columns[i];
      var sortIndicator = "";
      if (col.sortable) {
        var arrow = "";
        if (col.key === sortKey) {
          arrow = sortDir === "asc" ? ' <span class="sort-arrow asc">▲</span>' : ' <span class="sort-arrow desc">▼</span>';
        }
        sortIndicator = arrow;
        html += '<th data-sort-key="' + col.key + '" class="sortable">' + escapeHtml(col.label || col.key) + sortIndicator + '</th>';
      } else {
        html += '<th>' + escapeHtml(col.label || col.key) + '</th>';
      }
    }
    html += '</tr></thead><tbody>';

    if (data.length === 0) {
      var colSpan = columns.length;
      var emptyMsg = opts.emptyMessage || "暂无数据";
      html += '<tr><td colspan="' + colSpan + '" class="table-empty">' + emptyMsg + '</td></tr>';
    } else {
      for (var r = 0; r < data.length; r++) {
        var row = data[r];
        html += '<tr>';
        for (var c = 0; c < columns.length; c++) {
          var cellCol = columns[c];
          var value = row[cellCol.key];
          html += '<td>';
          if (cellCol.render) {
            html += cellCol.render(value, row, r);
          } else if (cellCol.statusBadge) {
            var badge = (window.App && window.App.components && window.App.components.statusBadge)
              ? window.App.components.statusBadge
              : null;
            html += badge ? badge.render(String(value != null ? value : "")) : escapeHtml(String(value != null ? value : ""));
          } else {
            html += escapeHtml(String(value != null ? value : ""));
          }
          html += '</td>';
        }
        html += '</tr>';
      }
    }
    html += '</tbody></table></div>';

    // Pagination
    if (opts.showPagination !== false && total > pageSize) {
      var totalPages = Math.max(1, Math.ceil(total / pageSize));
      html += '<div class="table-pagination">';
      html += '<span class="pagination-info">' + ((page - 1) * pageSize + 1) + '-' + Math.min(page * pageSize, total) + ' / ' + total + '</span>';
      html += '<button class="btn btn-sm" data-page="prev" ' + (page <= 1 ? "disabled" : "") + '>上一页</button>';
      html += '<span class="pagination-current">' + page + ' / ' + totalPages + '</span>';
      html += '<button class="btn btn-sm" data-page="next" ' + (page >= totalPages ? "disabled" : "") + '>下一页</button>';
      html += '</div>';
    }

    container.innerHTML = html;
    bindEvents(container, opts);
  }

  function bindEvents(container, opts) {
    // Sort
    container.querySelectorAll("th.sortable").forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-sort-key");
        if (opts.onSort) opts.onSort(key);
      });
    });

    // Filter
    var filterInput = container.querySelector("[data-table-filter]");
    if (filterInput && opts.onFilter) {
      var debounceTimer;
      filterInput.addEventListener("input", function () {
        clearTimeout(debounceTimer);
        var self = this;
        debounceTimer = setTimeout(function () {
          opts.onFilter(self.value);
        }, 300);
      });
    }

    // Pagination
    container.querySelectorAll("[data-page]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var dir = btn.getAttribute("data-page");
        if (opts.onPageChange) opts.onPageChange(dir);
      });
    });
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
    window.App.components.dataTable = {
      render: render,
    };
  }
})();
