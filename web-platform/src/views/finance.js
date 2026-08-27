/**
 * Finance subsystem view — Phase 3 implementation.
 * Registered on ``window.App.views.finance``.
 */
(function () {
  "use strict";

  function render(container, config) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;
    var system = (config && config.system) || { code: "finance", title: "财务系统" };

    container.innerHTML = (
      '<div class="subsystem-view-shell">' +
      '<button class="btn btn-primary" id="finCreateClaimBtn">+ 新建报销</button>' +
      '<button class="btn" id="finCreateBudgetBtn" style="margin-left:8px">+ 新建预算</button></div>' +
      '<div id="finStats" class="subsystem-metrics" style="margin-bottom:16px"></div>' +
      '<div style="display:flex;gap:8px;margin-bottom:16px">' +
      '<button class="btn btn-sm active" data-fin-tab="claims">全部报销</button>' +
      '<button class="btn btn-sm" data-fin-tab="my-pending">待我审批</button>' +
      '<button class="btn btn-sm" data-fin-tab="my-initiated">我的报销</button>' +
      '<button class="btn btn-sm" data-fin-tab="budgets">预算管理</button>' +
      '</div>' +
      '<div id="finTableContainer"><p style="text-align:center;padding:40px;color:var(--gray)">加载中...</p></div>' +
      '</div>'
    );

    _currentTab = "claims";
    loadFinData();
    document.getElementById("finCreateClaimBtn").onclick = showCreateClaimForm;
    document.getElementById("finCreateBudgetBtn").onclick = showCreateBudgetForm;
    document.querySelectorAll("[data-fin-tab]").forEach(function (btn) {
      btn.onclick = function () {
        document.querySelectorAll("[data-fin-tab]").forEach(function (b) { b.classList.remove("active"); });
        this.classList.add("active");
        _currentTab = this.dataset.finTab;
        loadFinData();
      };
    });
  }

  var _currentTab = "claims";
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

  async function loadFinData() {
    try {
      if (_currentTab === "budgets") {
        var [budgetResp, budgetStatsResp] = await Promise.all([
          api("/__frontend_missing_contract__/enterprise/finance/budgets"),
          api("/__frontend_missing_contract__/enterprise/finance/budgets/stats"),
        ]);
        var budgets = budgetResp.ok ? (await budgetResp.json()).items || [] : [];
        var bStats = budgetStatsResp.ok ? await budgetStatsResp.json() : { total: 0, total_amount: 0, total_used: 0 };
        renderBudgetStats(bStats);
        renderBudgetTable(budgets);
      } else {
        var endpoint = "/__frontend_missing_contract__/enterprise/finance/claims";
        if (_currentTab === "my-pending") endpoint = "/__frontend_missing_contract__/enterprise/finance/claims/my-pending";
        else if (_currentTab === "my-initiated") endpoint = "/__frontend_missing_contract__/enterprise/finance/claims/my-initiated";

        var [claimsResp, statsResp] = await Promise.all([
          api(endpoint),
          api("/__frontend_missing_contract__/enterprise/finance/claims/stats"),
        ]);
        var claims = claimsResp.ok ? (await claimsResp.json()).items || [] : [];
        var stats = statsResp.ok ? await statsResp.json() : { total: 0, by_status: {} };
        renderClaimStats(stats);
        renderClaimTable(claims);
      }
    } catch (e) {
      document.getElementById("finTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">加载失败，请重试</p>';
    }
  }

  function renderClaimStats(stats) {
    document.getElementById("finStats").innerHTML =
      '<div class="subsystem-metric"><strong>' + (stats.total || 0) + '</strong><span>报销总数</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.pending || 0) + '</strong><span>待提交</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.processing || 0) + '</strong><span>审批中</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_status?.approved || 0) + '</strong><span>已通过</span></div>';
  }

  function renderBudgetStats(stats) {
    document.getElementById("finStats").innerHTML =
      '<div class="subsystem-metric"><strong>' + (stats.total || 0) + '</strong><span>预算项目</span></div>' +
      '<div class="subsystem-metric"><strong>' + formatAmount(stats.total_amount) + '</strong><span>预算总额</span></div>' +
      '<div class="subsystem-metric"><strong>' + formatAmount(stats.total_used) + '</strong><span>已使用</span></div>' +
      '<div class="subsystem-metric"><strong>' + (stats.by_category ? Object.keys(stats.by_category).length : 0) + '</strong><span>分类</span></div>';
  }

  function formatAmount(val) {
    if (val == null) return "***";
    return "¥" + Number(val).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function renderClaimTable(claims) {
    if (!claims.length) {
      document.getElementById("finTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">暂无报销单</p>';
      return;
    }
    var html = '<table class="subsystem-record-table"><thead><tr><th>标题</th><th>金额</th><th>状态</th><th>当前处理人</th><th>操作</th></tr></thead><tbody>';
    claims.forEach(function (c) {
      html += '<tr><td>' + esc(c.title) + '</td><td>' + formatAmount(c.amount) + '</td><td>' + statusBadge(c.status) + '</td><td>' + esc(c.current_handler || "-") + '</td><td>' + claimActionButtons(c) + '</td></tr>';
    });
    html += '</tbody></table>';
    document.getElementById("finTableContainer").innerHTML = html;
    bindClaimActions();
  }

  function renderBudgetTable(budgets) {
    if (!budgets.length) {
      document.getElementById("finTableContainer").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">暂无预算项目</p>';
      return;
    }
    var html = '<table class="subsystem-record-table"><thead><tr><th>名称</th><th>分类</th><th>总额</th><th>已用</th><th>年度</th></tr></thead><tbody>';
    budgets.forEach(function (b) {
      html += '<tr><td>' + esc(b.name) + '</td><td>' + esc(b.category || "-") + '</td><td>' + formatAmount(b.amount_total) + '</td><td>' + formatAmount(b.amount_used) + '</td><td>' + esc(String(b.fiscal_year)) + '</td></tr>';
    });
    html += '</tbody></table>';
    document.getElementById("finTableContainer").innerHTML = html;
  }

  function statusBadge(status) {
    var colors = { pending: "#f0ad4e", processing: "#5bc0de", approved: "#5cb85c", rejected: "#d9534f" };
    return '<span style="padding:2px 8px;border-radius:4px;font-size:12px;background:' + (colors[status] || "#999") + ';color:white">' + esc(status || "-") + '</span>';
  }

  function claimActionButtons(claim) {
    var btns = "";
    if (claim.status === "pending") btns += '<button class="btn btn-sm" data-action="submit" data-id="' + claim.id + '">提交</button>';
    if (claim.status === "processing" && _currentTab === "my-pending") btns += '<button class="btn btn-sm" data-action="approve" data-id="' + claim.id + '">审批</button>';
    return btns || '<span style="color:var(--gray);font-size:12px">-</span>';
  }

  function bindClaimActions() {
    document.querySelectorAll("[data-action]").forEach(function (btn) {
      btn.onclick = function () {
        var action = this.dataset.action;
        var id = parseInt(this.dataset.id);
        if (action === "submit") showSubmitClaimForm(id);
        else if (action === "approve") showApproveClaimForm(id);
      };
    });
  }

  function showCreateClaimForm() {
    showModal("新建报销",
      '<form id="finForm"><div class="form-grid"><div class="field"><label>标题</label><input name="title" required maxlength="255"></div><div class="field"><label>金额</label><input name="amount" type="number" step="0.01"></div><div class="field"><label>预算ID</label><input name="budget_id" type="number"></div><div class="field"><label>说明</label><textarea name="description" rows="2"></textarea></div></div></form>',
      async function () {
        var fd = new FormData(document.getElementById("finForm"));
        var payload = {}; fd.forEach(function (v, k) { if (v) payload[k] = v; });
        if (payload.amount) payload.amount = parseFloat(payload.amount);
        if (payload.budget_id) payload.budget_id = parseInt(payload.budget_id);
        var resp = await api("/__frontend_missing_contract__/enterprise/finance/claims", { method: "POST", body: JSON.stringify(payload) });
        if (resp.ok) { closeModal(); loadFinData(); }
        else { var e = await resp.json(); alert(e.detail || "创建失败"); }
      }
    );
  }

  function showSubmitClaimForm(id) {
    showModal("提交报销 — 设置审批人",
      '<form id="finForm"><div class="form-grid"><div class="field"><label>审批人ID</label><input name="approver_ids" required placeholder="多个用逗号分隔，例如: 2,3,5"></div></div></form>',
      async function () {
        var idsStr = document.getElementById("finForm").querySelector("input").value;
        var ids = idsStr.split(",").map(function (s) { return parseInt(s.trim()); }).filter(Boolean);
        var steps = ids.map(function (approverId, i) { return { approver_id: approverId, step_order: i + 1 }; });
        var resp = await api("/__frontend_missing_contract__/enterprise/finance/claims/" + id + "/submit", { method: "POST", body: JSON.stringify({ approval_steps: steps }) });
        if (resp.ok) { closeModal(); loadFinData(); }
        else { var e = await resp.json(); alert(e.detail || "提交失败"); }
      }
    );
  }

  function showApproveClaimForm(id) {
    showModal("审批报销",
      '<form id="finForm"><div class="form-grid"><div class="field"><label>操作</label><select name="action"><option value="approve">同意</option><option value="reject">驳回</option><option value="return">退回</option></select></div><div class="field"><label>意见</label><textarea name="comment" rows="2"></textarea></div></div></form>',
      async function () {
        var fd = new FormData(document.getElementById("finForm"));
        var payload = {}; fd.forEach(function (v, k) { payload[k] = v; });
        var resp = await api("/__frontend_missing_contract__/enterprise/finance/claims/" + id + "/approve", { method: "POST", body: JSON.stringify(payload) });
        if (resp.ok) { closeModal(); loadFinData(); }
        else { var e = await resp.json(); alert(e.detail || "审批失败"); }
      }
    );
  }

  function showCreateBudgetForm() {
    showModal("新建预算",
      '<form id="finForm"><div class="form-grid"><div class="field"><label>名称</label><input name="name" required maxlength="255"></div><div class="field"><label>分类</label><input name="category" required maxlength="128"></div><div class="field"><label>预算总额</label><input name="amount_total" type="number" step="0.01" value="0"></div><div class="field"><label>年度</label><input name="fiscal_year" type="number" value="2026"></div><div class="field"><label>说明</label><textarea name="description" rows="2"></textarea></div></div></form>',
      async function () {
        var fd = new FormData(document.getElementById("finForm"));
        var payload = {}; fd.forEach(function (v, k) { if (v) payload[k] = v; });
        if (payload.amount_total) payload.amount_total = parseFloat(payload.amount_total);
        if (payload.fiscal_year) payload.fiscal_year = parseInt(payload.fiscal_year);
        var resp = await api("/__frontend_missing_contract__/enterprise/finance/budgets", { method: "POST", body: JSON.stringify(payload) });
        if (resp.ok) { closeModal(); loadFinData(); }
        else { var e = await resp.json(); alert(e.detail || "创建失败"); }
      }
    );
  }

  var _modalCb = null;
  function showModal(title, bodyHtml, cb) {
    _modalCb = cb;
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.id = "finModal";
    overlay.innerHTML = '<div class="modal-content"><div class="modal-header"><h2>' + esc(title) + '</h2><button class="modal-close-btn" id="finModalClose">&times;</button></div>' + bodyHtml + '<div class="modal-actions"><button class="btn" id="finModalCancel">取消</button><button class="btn primary" id="finModalSubmit">确认</button></div></div>';
    document.body.appendChild(overlay);
    function onKey(e) { if (e.key === "Escape") closeModal(); }
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });
    document.getElementById("finModalClose").onclick = closeModal;
    document.getElementById("finModalCancel").onclick = closeModal;
    document.getElementById("finModalSubmit").onclick = function () { if (_modalCb) _modalCb(); };
  }

  function closeModal() {
    var m = document.getElementById("finModal");
    if (m) m.remove();
    _modalCb = null;
  }

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.views = window.App.views || {};
    window.App.views.finance = { render: render };
  }
})();
