/**
 * OA subsystem view — Phase 2 implementation.
 * Registered on ``window.App.views.oa``.
 */
(function () {
  "use strict";

  function render(container, config) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;
    var system = (config && config.system) || { code: "oa", title: "OA系统" };

    container.innerHTML = (
      '<div class="subsystem-view-shell">' +
      '<button class="btn btn-primary" id="oaCreateBtn">+ 新建流程</button></div>' +
      '<div id="oaStats" class="subsystem-metrics" style="margin-bottom:16px"></div>' +
      '<div style="display:flex;gap:8px;margin-bottom:16px">' +
      '<button class="btn btn-sm active" data-oa-tab="all">全部</button>' +
      '<button class="btn btn-sm" data-oa-tab="pending">待我审批</button>' +
      '<button class="btn btn-sm" data-oa-tab="my-flows">我发起的</button>' +
      '<button class="btn btn-sm" data-oa-tab="history">我参与的</button>' +
      '</div>' +
      '<div id="oaTableContainer"><p style="text-align:center;padding:40px;color:var(--gray)">加载中...</p></div>' +
      '</div>'
    );

    _currentTab = "all";
    loadOaData();
    document.getElementById("oaCreateBtn").onclick = showCreateForm;
    document.querySelectorAll("[data-oa-tab]").forEach(function (btn) {
      btn.onclick = function () {
        document.querySelectorAll("[data-oa-tab]").forEach(function (b) { b.classList.remove("active"); });
        this.classList.add("active");
        _currentTab = this.dataset.oaTab;
        loadOaData();
      };
    });
  }

  var _currentTab = "all";
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

  async function loadOaData() {
    try {
      var endpoint = "/__frontend_missing_contract__/enterprise/oa/flows";
      if (_currentTab === "pending") endpoint = "/__frontend_missing_contract__/enterprise/oa/pending";
      else if (_currentTab === "my-flows") endpoint = "/__frontend_missing_contract__/enterprise/oa/my-flows";
      else if (_currentTab === "history") endpoint = "/__frontend_missing_contract__/enterprise/oa/history";

      var [flowsResp, statsResp] = await Promise.all([
        api(endpoint),
        api("/__frontend_missing_contract__/enterprise/oa/stats"),
      ]);
      var flows = flowsResp.ok ? (await flowsResp.json()).items || [] : [];
      var stats = statsResp.ok ? await statsResp.json() : { total: 0, by_status: {}, by_type: {} };
      renderStats(stats);
      renderTable(flows);
    } catch (e) {
      document.getElementById("oaTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">加载失败，请重试</p>';
    }
  }

  function renderStats(stats) {
    document.getElementById("oaStats").innerHTML =
      '<div class="subsystem-metric"><strong>' + (stats.total || 0) + '</strong><span>流程总数</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.pending || 0) + '</strong><span>待提交</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.processing || 0) + '</strong><span>审批中</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.approved || 0) + '</strong><span>已通过</span></div>';
  }

  function renderTable(flows) {
    if (!flows.length) {
      document.getElementById("oaTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">暂无流程</p>';
      return;
    }
    var html = '<table class="subsystem-record-table"><thead><tr><th>标题</th><th>类型</th><th>状态</th><th>当前处理人</th><th>操作</th></tr></thead><tbody>';
    flows.forEach(function (f) {
      html += '<tr><td>' + esc(f.title) + '</td><td>' + esc(f.flow_type || "-") + '</td><td>' + statusBadge(f.status) + '</td><td>' + esc(f.current_handler || "-") + '</td><td>' + actionButtons(f) + '</td></tr>';
    });
    html += '</tbody></table>';
    document.getElementById("oaTableContainer").innerHTML = html;
    bindActionButtons();
  }

  function statusBadge(status) {
    var colors = { pending: "#f0ad4e", processing: "#5bc0de", approved: "#5cb85c", rejected: "#d9534f" };
    return '<span style="padding:2px 8px;border-radius:4px;font-size:12px;background:' + (colors[status] || "#999") + ';color:white">' + esc(status || "-") + '</span>';
  }

  function actionButtons(flow) {
    var btns = "";
    if (flow.status === "pending") btns += '<button class="btn btn-sm" data-action="submit" data-id="' + flow.id + '">提交</button>';
    if (flow.status === "processing" && _currentTab === "pending") btns += '<button class="btn btn-sm" data-action="approve" data-id="' + flow.id + '">审批</button>';
    return btns || '<span style="color:var(--gray);font-size:12px">-</span>';
  }

  function bindActionButtons() {
    document.querySelectorAll("[data-action]").forEach(function (btn) {
      btn.onclick = function () {
        var action = this.dataset.action;
        var id = parseInt(this.dataset.id);
        if (action === "submit") showSubmitForm(id);
        else if (action === "approve") showApproveForm(id);
      };
    });
  }

  function showCreateForm() {
    showModal("新建OA流程",
      '<form id="oaForm"><div class="form-grid"><div class="field"><label>标题</label><input name="title" required maxlength="255"></div><div class="field"><label>流程类型</label><input name="flow_type" required maxlength="128"></div></div></form>',
      async function () {
        var fd = new FormData(document.getElementById("oaForm"));
        var payload = {}; fd.forEach(function (v, k) { payload[k] = v; });
        var resp = await api("/__frontend_missing_contract__/enterprise/oa/flows", { method: "POST", body: JSON.stringify(payload) });
        if (resp.ok) { closeModal(); loadOaData(); }
        else { var e = await resp.json(); alert(e.detail || "创建失败"); }
      }
    );
  }

  function showSubmitForm(id) {
    showModal("提交流程 — 设置审批人",
      '<form id="oaForm"><div class="form-grid"><div class="field"><label>审批人ID</label><input name="approver_ids" required placeholder="多个用逗号分隔，例如: 2,3,5"></div></div></form>',
      async function () {
        var idsStr = document.getElementById("oaForm").querySelector("input").value;
        var ids = idsStr.split(",").map(function (s) { return parseInt(s.trim()); }).filter(Boolean);
        var steps = ids.map(function (approverId, i) { return { approver_id: approverId, step_order: i + 1 }; });
        var resp = await api("/__frontend_missing_contract__/enterprise/oa/flows/" + id + "/submit", { method: "POST", body: JSON.stringify({ approval_steps: steps }) });
        if (resp.ok) { closeModal(); loadOaData(); }
        else { var e = await resp.json(); alert(e.detail || "提交失败"); }
      }
    );
  }

  function showApproveForm(id) {
    showModal("审批流程",
      '<form id="oaForm"><div class="form-grid"><div class="field"><label>操作</label><select name="action"><option value="approve">同意</option><option value="reject">驳回</option><option value="return">退回</option></select></div><div class="field"><label>意见</label><textarea name="comment" rows="2"></textarea></div></div></form>',
      async function () {
        var fd = new FormData(document.getElementById("oaForm"));
        var payload = {}; fd.forEach(function (v, k) { payload[k] = v; });
        var resp = await api("/__frontend_missing_contract__/enterprise/oa/flows/" + id + "/approve", { method: "POST", body: JSON.stringify(payload) });
        if (resp.ok) { closeModal(); loadOaData(); }
        else { var e = await resp.json(); alert(e.detail || "审批失败"); }
      }
    );
  }

  var _modalCb = null;
  function showModal(title, bodyHtml, cb) {
    _modalCb = cb;
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.id = "oaModal";
    overlay.innerHTML = '<div class="modal-content"><div class="modal-header"><h2>' + esc(title) + '</h2><button class="modal-close-btn" id="oaModalClose">&times;</button></div>' + bodyHtml + '<div class="modal-actions"><button class="btn" id="oaModalCancel">取消</button><button class="btn primary" id="oaModalSubmit">确认</button></div></div>';
    document.body.appendChild(overlay);
    function onKey(e) { if (e.key === "Escape") closeModal(); }
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });
    document.getElementById("oaModalClose").onclick = closeModal;
    document.getElementById("oaModalCancel").onclick = closeModal;
    document.getElementById("oaModalSubmit").onclick = function () { if (_modalCb) _modalCb(); };
  }

  function closeModal() {
    var m = document.getElementById("oaModal");
    if (m) m.remove();
    _modalCb = null;
  }

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.views = window.App.views || {};
    window.App.views.oa = { render: render };
  }
})();
