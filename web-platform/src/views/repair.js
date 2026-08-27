/**
 * Repair subsystem view — Phase 2 implementation.
 * Registered on ``window.App.views.repair``.
 */
(function () {
  "use strict";

  function render(container, config) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;
    var system = (config && config.system) || { code: "repair", title: "报修系统" };

    container.innerHTML = (
      '<div class="subsystem-view-shell">' +
      '<button class="btn btn-primary" id="repairCreateBtn">+ 新建工单</button></div>' +
      '<div id="repairStats" class="subsystem-metrics" style="margin-bottom:16px"></div>' +
      '<div id="repairTableContainer"><p style="text-align:center;padding:40px;color:var(--gray)">加载中...</p></div>' +
      '</div>'
    );

    loadRepairData();
    document.getElementById("repairCreateBtn").onclick = showCreateForm;
  }

  var apiBase = window.COLLAB_API_BASE_URL || (window.location.protocol === "file:" ? "http://localhost:8000" : "");

  async function api(path, opts) {
    if (path && path.startsWith("/__frontend_missing_contract__/")) {
      throw new Error("该功能后端接口尚未纳入前端契约");
    }
    opts = opts || {};
    var headers = opts.headers || {};
    if (!(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
    var token = (window.App && window.App._authToken) || (window.__auth && window.__auth.getToken && window.__auth.getToken());
    if (token) headers["Authorization"] = "Bearer " + token;
    return fetch(apiBase + path, Object.assign({}, opts, { headers: headers }));
  }

  async function loadRepairData() {
    try {
      var [ticketsResp, statsResp] = await Promise.all([
        api("/__frontend_missing_contract__/enterprise/repair/tickets"),
        api("/__frontend_missing_contract__/enterprise/repair/stats"),
      ]);
      var tickets = ticketsResp.ok ? (await ticketsResp.json()).items || [] : [];
      var stats = statsResp.ok ? await statsResp.json() : { total: 0, by_status: {}, by_priority: {} };
      renderStats(stats);
      renderTable(tickets);
    } catch (e) {
      document.getElementById("repairTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">加载失败，请重试</p>';
    }
  }

  function renderStats(stats) {
    document.getElementById("repairStats").innerHTML =
      '<div class="subsystem-metric"><strong>' + (stats.total || 0) + '</strong><span>工单总数</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.submitted || 0) + '</strong><span>待处理</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.processing || 0) + '</strong><span>处理中</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.completed || 0) + '</strong><span>已完成</span></div>';
  }

  function renderTable(tickets) {
    if (!tickets.length) {
      document.getElementById("repairTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">暂无工单</p>';
      return;
    }
    var html = '<table class="subsystem-record-table"><thead><tr><th>ID</th><th>标题</th><th>位置</th><th>状态</th><th>优先级</th><th>负责人</th><th>操作</th></tr></thead><tbody>';
    tickets.forEach(function (t) {
      html += '<tr><td>' + t.id + '</td><td>' + esc(t.title) + '</td><td>' + esc(t.location || "-") + '</td><td>' + statusBadge(t.status) + '</td><td>' + esc(t.priority || "-") + '</td><td>' + esc(t.assignee || "-") + '</td><td>' + actionButtons(t) + '</td></tr>';
    });
    html += '</tbody></table>';
    document.getElementById("repairTableContainer").innerHTML = html;
    bindActionButtons();
  }

  function statusBadge(status) {
    var colors = { submitted: "#f0ad4e", processing: "#5bc0de", completed: "#5cb85c", rated: "#337ab7" };
    return '<span style="padding:2px 8px;border-radius:4px;font-size:12px;background:' + (colors[status] || "#999") + ';color:white">' + esc(status || "-") + '</span>';
  }

  function actionButtons(ticket) {
    var btns = "";
    if (ticket.status === "submitted") btns += '<button class="btn btn-sm" data-action="assign" data-id="' + ticket.id + '">派单</button>';
    if (ticket.status === "processing") btns += '<button class="btn btn-sm" data-action="complete" data-id="' + ticket.id + '">完成</button>';
    if (ticket.status === "completed") btns += '<button class="btn btn-sm" data-action="rate" data-id="' + ticket.id + '">评价</button>';
    return btns || '<span style="color:var(--gray);font-size:12px">-</span>';
  }

  function bindActionButtons() {
    document.querySelectorAll("[data-action]").forEach(function (btn) {
      btn.onclick = function () {
        var action = this.dataset.action;
        var id = parseInt(this.dataset.id);
        if (action === "assign") showAssignForm(id);
        else if (action === "complete") completeTicket(id);
        else if (action === "rate") showRateForm(id);
      };
    });
  }

  function showCreateForm() {
    showModal("新建报修工单",
      '<form id="repairForm"><div class="form-grid"><div class="field"><label>标题</label><input name="title" required maxlength="255"></div><div class="field"><label>位置</label><input name="location" required maxlength="255"></div><div class="field"><label>描述</label><textarea name="description" required rows="3"></textarea></div><div class="field"><label>优先级</label><select name="priority"><option value="normal">普通</option><option value="low">低</option><option value="high">高</option><option value="urgent">紧急</option></select></div></div></form>',
      async function () {
        var fd = new FormData(document.getElementById("repairForm"));
        var payload = {}; fd.forEach(function (v, k) { payload[k] = v; });
        var resp = await api("/__frontend_missing_contract__/enterprise/repair/tickets", { method: "POST", body: JSON.stringify(payload) });
        if (resp.ok) { closeModal(); loadRepairData(); }
        else { var e = await resp.json(); alert(e.detail || "创建失败"); }
      }
    );
  }

  function showAssignForm(id) {
    showModal("派单",
      '<form id="repairForm"><div class="form-grid"><div class="field"><label>处理人</label><input name="assignee" required maxlength="128"></div></div></form>',
      async function () {
        var assignee = document.getElementById("repairForm").querySelector("input").value;
        var resp = await api("/__frontend_missing_contract__/enterprise/repair/tickets/" + id + "/assign", { method: "POST", body: JSON.stringify({ assignee: assignee }) });
        if (resp.ok) { closeModal(); loadRepairData(); }
        else { var e = await resp.json(); alert(e.detail || "派单失败"); }
      }
    );
  }

  async function completeTicket(id) {
    if (!confirm("确认完成此工单？")) return;
    var resp = await api("/__frontend_missing_contract__/enterprise/repair/tickets/" + id + "/complete", { method: "POST" });
    if (resp.ok) loadRepairData();
    else { var e = await resp.json(); alert(e.detail || "操作失败"); }
  }

  function showRateForm(id) {
    showModal("评价工单",
      '<form id="repairForm"><div class="form-grid"><div class="field"><label>评分</label><select name="rating"><option value="5">5 - 非常满意</option><option value="4">4 - 满意</option><option value="3">3 - 一般</option><option value="2">2 - 不满意</option><option value="1">1 - 非常不满意</option></select></div></div></form>',
      async function () {
        var rating = parseInt(document.getElementById("repairForm").querySelector("select").value);
        var resp = await api("/__frontend_missing_contract__/enterprise/repair/tickets/" + id + "/rate", { method: "POST", body: JSON.stringify({ rating: rating }) });
        if (resp.ok) { closeModal(); loadRepairData(); }
        else { var e = await resp.json(); alert(e.detail || "评价失败"); }
      }
    );
  }

  var _modalCb = null;
  function showModal(title, bodyHtml, cb) {
    _modalCb = cb;
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.id = "repairModal";
    overlay.innerHTML = '<div class="modal-content"><div class="modal-header"><h2>' + esc(title) + '</h2><button class="modal-close-btn" id="repairModalClose">&times;</button></div>' + bodyHtml + '<div class="modal-actions"><button class="btn" id="repairModalCancel">取消</button><button class="btn primary" id="repairModalSubmit">确认</button></div></div>';
    document.body.appendChild(overlay);
    function onKey(e) { if (e.key === "Escape") closeModal(); }
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });
    document.getElementById("repairModalClose").onclick = closeModal;
    document.getElementById("repairModalCancel").onclick = closeModal;
    document.getElementById("repairModalSubmit").onclick = function () { if (_modalCb) _modalCb(); };
  }

  function closeModal() {
    var m = document.getElementById("repairModal");
    if (m) m.remove();
    _modalCb = null;
  }

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.views = window.App.views || {};
    window.App.views.repair = { render: render };
  }
})();
