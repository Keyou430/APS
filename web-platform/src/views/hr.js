/**
 * HR subsystem view — Phase 3 implementation.
 * Registered on ``window.App.views.hr``.
 */
(function () {
  "use strict";

  function render(container, config) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;
    var system = (config && config.system) || { code: "hr", title: "人事系统" };

    container.innerHTML = (
      '<div class="subsystem-view-shell">' +
      '<button class="btn btn-primary" id="hrCreateBtn">+ 新建申请</button></div>' +
      '<div id="hrStats" class="subsystem-metrics" style="margin-bottom:16px"></div>' +
      '<div style="display:flex;gap:8px;margin-bottom:16px">' +
      '<button class="btn btn-sm active" data-hr-tab="all">全部</button>' +
      '<button class="btn btn-sm" data-hr-tab="my-pending">待我审批</button>' +
      '<button class="btn btn-sm" data-hr-tab="my-initiated">我发起的</button>' +
      '<button class="btn btn-sm" data-hr-tab="staff">人员档案</button>' +
      '</div>' +
      '<div id="hrTableContainer"><p style="text-align:center;padding:40px;color:var(--gray)">加载中...</p></div>' +
      '</div>'
    );

    _currentTab = "all";
    loadHrData();
    document.getElementById("hrCreateBtn").onclick = showCreateForm;
    document.querySelectorAll("[data-hr-tab]").forEach(function (btn) {
      btn.onclick = function () {
        document.querySelectorAll("[data-hr-tab]").forEach(function (b) { b.classList.remove("active"); });
        this.classList.add("active");
        _currentTab = this.dataset.hrTab;
        loadHrData();
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

  async function loadHrData() {
    try {
      var endpoint = "/__frontend_missing_contract__/enterprise/hr/requests";
      if (_currentTab === "my-pending") endpoint = "/__frontend_missing_contract__/enterprise/hr/requests/my-pending";
      else if (_currentTab === "my-initiated") endpoint = "/__frontend_missing_contract__/enterprise/hr/requests/my-initiated";
      else if (_currentTab === "staff") endpoint = "/__frontend_missing_contract__/enterprise/hr/staff";

      var [dataResp, statsResp] = await Promise.all([
        api(endpoint),
        api("/__frontend_missing_contract__/enterprise/hr/stats"),
      ]);
      var items = dataResp.ok ? (await dataResp.json()).items || [] : [];
      var stats = statsResp.ok ? await statsResp.json() : { total: 0, by_status: {}, by_type: {} };
      renderStats(stats);
      if (_currentTab === "staff") renderStaffTable(items);
      else renderTable(items);
    } catch (e) {
      document.getElementById("hrTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">加载失败，请重试</p>';
    }
  }

  function renderStats(stats) {
    document.getElementById("hrStats").innerHTML =
      '<div class="subsystem-metric"><strong>' + (stats.total || 0) + '</strong><span>申请总数</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.processing || 0) + '</strong><span>处理中</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.approved || 0) + '</strong><span>已通过</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.rejected || 0) + '</strong><span>已驳回</span></div>';
  }

  function renderTable(requests) {
    if (!requests.length) {
      document.getElementById("hrTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">暂无申请</p>';
      return;
    }
    var html = '<table class="subsystem-record-table"><thead><tr><th>标题</th><th>类型</th><th>状态</th><th>审批人</th><th>操作</th></tr></thead><tbody>';
    requests.forEach(function (r) {
      html += '<tr><td>' + esc(r.title) + '</td><td>' + typeLabel(r.request_type) + '</td><td>' + statusBadge(r.status) + '</td><td>' + esc(r.approved_by || "-") + '</td><td>' + actionButtons(r) + '</td></tr>';
    });
    html += '</tbody></table>';
    document.getElementById("hrTableContainer").innerHTML = html;
    bindActionButtons();
  }

  function typeLabel(t) {
    var labels = { certificate: "证明申请", attendance: "考勤补签", leave: "请假申请" };
    return labels[t] || t || "-";
  }

  function renderStaffTable(users) {
    if (!users.length) {
      document.getElementById("hrTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">暂无人员数据</p>';
      return;
    }
    var html = '<table class="subsystem-record-table"><thead><tr><th>姓名</th><th>用户名</th><th>邮箱</th><th>手机</th><th>状态</th></tr></thead><tbody>';
    users.forEach(function (u) {
      html += '<tr><td>' + esc(u.display_name) + '</td><td>' + esc(u.username) + '</td><td>' + esc(u.email || "-") + '</td><td>' + esc(u.phone || "-") + '</td><td>' + (u.is_active ? '<span style="color:#5cb85c">在职</span>' : '<span style="color:#999">停用</span>') + '</td></tr>';
    });
    html += '</tbody></table>';
    document.getElementById("hrTableContainer").innerHTML = html;
  }

  function statusBadge(status) {
    var colors = { pending: "#f0ad4e", processing: "#5bc0de", approved: "#5cb85c", rejected: "#d9534f" };
    return '<span style="padding:2px 8px;border-radius:4px;font-size:12px;background:' + (colors[status] || "#999") + ';color:white">' + esc(status || "-") + '</span>';
  }

  function actionButtons(request) {
    var btns = "";
    if (request.status === "processing" && _currentTab === "my-pending") btns += '<button class="btn btn-sm" data-action="approve" data-id="' + request.id + '">审批</button>';
    return btns || '<span style="color:var(--gray);font-size:12px">-</span>';
  }

  function bindActionButtons() {
    document.querySelectorAll("[data-action]").forEach(function (btn) {
      btn.onclick = function () {
        var action = this.dataset.action;
        var id = parseInt(this.dataset.id);
        if (action === "approve") showApproveForm(id);
      };
    });
  }

  function showCreateForm() {
    showModal("新建申请",
      '<form id="hrForm"><div class="form-grid"><div class="field"><label>标题</label><input name="title" required maxlength="255"></div><div class="field"><label>申请类型</label><select name="request_type"><option value="certificate">证明申请</option><option value="attendance">考勤补签</option><option value="leave">请假申请</option></select></div><div class="field"><label>审批人ID</label><input name="approved_by" type="number"></div><div class="field"><label>备注</label><textarea name="content_json" rows="2" placeholder=\'{"reason":"..."}\'></textarea></div></div></form>',
      async function () {
        var fd = new FormData(document.getElementById("hrForm"));
        var payload = {}; fd.forEach(function (v, k) { if (v) payload[k] = v; });
        if (payload.approved_by) payload.approved_by = parseInt(payload.approved_by);
        var resp = await api("/__frontend_missing_contract__/enterprise/hr/requests", { method: "POST", body: JSON.stringify(payload) });
        if (resp.ok) { closeModal(); loadHrData(); }
        else { var e = await resp.json(); alert(e.detail || "创建失败"); }
      }
    );
  }

  function showApproveForm(id) {
    showModal("审批申请",
      '<form id="hrForm"><div class="form-grid"><div class="field"><label>操作</label><select name="action"><option value="approve">同意</option><option value="reject">驳回</option></select></div><div class="field"><label>意见</label><textarea name="comment" rows="2"></textarea></div></div></form>',
      async function () {
        var fd = new FormData(document.getElementById("hrForm"));
        var payload = {}; fd.forEach(function (v, k) { payload[k] = v; });
        var resp = await api("/__frontend_missing_contract__/enterprise/hr/requests/" + id + "/approve", { method: "POST", body: JSON.stringify(payload) });
        if (resp.ok) { closeModal(); loadHrData(); }
        else { var e = await resp.json(); alert(e.detail || "审批失败"); }
      }
    );
  }

  var _modalCb = null;
  function showModal(title, bodyHtml, cb) {
    _modalCb = cb;
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.id = "hrModal";
    overlay.innerHTML = '<div class="modal-content"><div class="modal-header"><h2>' + esc(title) + '</h2><button class="modal-close-btn" id="hrModalClose">&times;</button></div>' + bodyHtml + '<div class="modal-actions"><button class="btn" id="hrModalCancel">取消</button><button class="btn primary" id="hrModalSubmit">确认</button></div></div>';
    document.body.appendChild(overlay);
    function onKey(e) { if (e.key === "Escape") closeModal(); }
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });
    document.getElementById("hrModalClose").onclick = closeModal;
    document.getElementById("hrModalCancel").onclick = closeModal;
    document.getElementById("hrModalSubmit").onclick = function () { if (_modalCb) _modalCb(); };
  }

  function closeModal() {
    var m = document.getElementById("hrModal");
    if (m) m.remove();
    _modalCb = null;
  }

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.views = window.App.views || {};
    window.App.views.hr = { render: render };
  }
})();
