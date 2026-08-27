/**
 * NotificationBell — unread-count badge + dropdown panel.
 *
 * Registered as ``window.App.components.notificationBell``.
 * Usage:
 *   App.components.notificationBell.init({ buttonId: "notificationButton", ... })
 *   App.components.notificationBell.setCount(5)
 *   App.components.notificationBell.renderList([...])
 *   App.components.notificationBell.startPolling(60000)
 */

(function () {
  "use strict";

  var _buttonId = "notificationButton";
  var _badgeId = "notificationBadge";
  var _dropdownId = "notificationDropdown";
  var _unreadCount = 0;
  var _pollTimer = null;
  var _onFetch = null;
  var _onMarkRead = null;
  var _onMarkAllRead = null;

  function init(config) {
    var opts = config || {};
    _buttonId = opts.buttonId || _buttonId;
    _badgeId = opts.badgeId || _badgeId;
    _dropdownId = opts.dropdownId || _dropdownId;
    _onFetch = opts.onFetch || null;
    _onMarkRead = opts.onMarkRead || null;
    _onMarkAllRead = opts.onMarkAllRead || null;

    var btn = document.getElementById(_buttonId);
    if (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        toggleDropdown();
      });
    }
    var dropdown = document.getElementById(_dropdownId);
    if (dropdown) {
      dropdown.addEventListener("click", function (e) {
        e.stopPropagation();
      });
    }

    // Close dropdown on outside click
    document.addEventListener("click", function () {
      closeDropdown();
    });
  }

  function setCount(count) {
    _unreadCount = count || 0;
    var badge = document.getElementById(_badgeId);
    if (badge) {
      if (_unreadCount > 0) {
        badge.textContent = _unreadCount > 99 ? "99+" : String(_unreadCount);
        badge.style.display = "";
      } else {
        badge.style.display = "none";
      }
    }
  }

  function getCount() {
    return _unreadCount;
  }

  function renderList(items) {
    var dropdown = document.getElementById(_dropdownId);
    if (!dropdown) return;

    if (!items || items.length === 0) {
      dropdown.innerHTML = '<div class="notification-header"><strong>通知</strong><span>暂无待处理提醒</span></div><div class="notification-empty">暂无通知</div>';
      return;
    }

    var unreadCount = items.filter(function (x) { return !x.is_read; }).length;
    var html =
      '<div class="notification-header"><strong>通知</strong><span>' +
      unreadCount +
      ' 条待处理提醒</span></div><div class="notification-list">';
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var unreadClass = item.is_read ? "" : " unread";
      var timeStr = item.created_at ? formatTime(item.created_at) : "";
      html += (
        '<div class="notification-item' + unreadClass + '" data-notif-id="' + item.id + '">' +
        '<div class="notification-item-title">' + esc(item.title || "") + '</div>' +
        '<div class="notification-item-content">' + esc(item.content || "") + '</div>' +
        (timeStr ? '<div class="notification-item-time">' + timeStr + '</div>' : "") +
        '</div>'
      );
    }
    html += '</div>';

    if (!items.every(function (x) { return x.is_read; })) {
      var actionLabel = items[0].action_label || "全部标为已读";
      html += '<div class="notification-actions"><button data-mark-all-read>' + esc(actionLabel) + '</button></div>';
    }

    dropdown.innerHTML = html;

    // Bind click — mark as read
    dropdown.querySelectorAll("[data-notif-id]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = el.getAttribute("data-notif-id");
        if (_onMarkRead) _onMarkRead(id);
        closeDropdown();
      });
    });

    // Mark all read
    var markAllBtn = dropdown.querySelector("[data-mark-all-read]");
    if (markAllBtn) {
      markAllBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (_onMarkAllRead) _onMarkAllRead();
      });
    }
  }

  function toggleDropdown() {
    var dropdown = document.getElementById(_dropdownId);
    if (!dropdown) return;
    if (dropdown.classList.contains("show")) {
      closeDropdown();
    } else {
      if (_onFetch) _onFetch();
      dropdown.classList.add("show");
    }
  }

  function closeDropdown() {
    var dropdown = document.getElementById(_dropdownId);
    if (dropdown) dropdown.classList.remove("show");
  }

  function startPolling(intervalMs) {
    stopPolling();
    if (_onFetch) _onFetch();
    _pollTimer = setInterval(function () {
      if (_onFetch) _onFetch();
    }, intervalMs || 60000);
  }

  function stopPolling() {
    if (_pollTimer) {
      clearInterval(_pollTimer);
      _pollTimer = null;
    }
  }

  function formatTime(isoStr) {
    try { return String(isoStr).replace("T", " ").substring(0, 16); } catch (e) { return ""; }
  }

  function esc(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── Register ─────────────────────────────────────────────────────────
  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.components = window.App.components || {};
    window.App.components.notificationBell = {
      init: init, setCount: setCount, getCount: getCount,
      renderList: renderList, startPolling: startPolling,
      stopPolling: stopPolling, closeDropdown: closeDropdown,
    };
  }
})();
