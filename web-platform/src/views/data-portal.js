/**
 * Data Portal subsystem view — Phase 3 implementation.
 * Registered on ``window.App.views["data-portal"]``.
 */
(function () {
  "use strict";

  function render(container, config) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;
    var system = (config && config.system) || { code: "data-portal", title: "数据门户" };

    container.innerHTML = (
      '<div class="subsystem-view-shell">' +
      '<div id="dpMetrics" class="subsystem-metrics" style="margin-bottom:16px"></div>' +
      '<div class="internal-card"><div class="card-header"><div class="card-title">数据概览</div></div>' +
      '<div class="card-body"><canvas id="dpChart" style="max-height:300px;width:100%"></canvas></div></div>' +
      '</div>'
    );

    loadOverview();
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

  async function loadOverview() {
    try {
      var resp = await api("/__frontend_missing_contract__/enterprise/data-portal/overview");
      if (!resp.ok) throw new Error("加载失败");
      var data = await resp.json();
      renderMetrics(data);
      renderChart(data);
    } catch (e) {
      document.getElementById("dpMetrics").innerHTML = '<p style="text-align:center;padding:40px;color:var(--gray)">加载失败，请重试</p>';
    }
  }

  function renderMetrics(data) {
    document.getElementById("dpMetrics").innerHTML =
      '<div class="subsystem-metric"><strong>' + (data.subsystem_count || 0) + '</strong><span>子系统数</span></div>' +
      '<div class="subsystem-metric"><strong>' + (data.active_users || 0) + '</strong><span>用户</span></div>' +
      '<div class="subsystem-metric"><strong>' + (data.total_tickets || 0) + '</strong><span>工单</span></div>' +
      '<div class="subsystem-metric"><strong>' + (data.total_assets || 0) + '</strong><span>资产</span></div>' +
      '<div class="subsystem-metric"><strong>' + (data.total_flows || 0) + '</strong><span>流程</span></div>' +
      '<div class="subsystem-metric"><strong>' + (data.notices_count || 0) + '</strong><span>公告</span></div>' +
      '<div class="subsystem-metric"><strong>' + (data.documents_count || 0) + '</strong><span>文档</span></div>';
  }

  function renderChart(data) {
    var canvas = document.getElementById("dpChart");
    if (!canvas) return;
    var ctx = canvas.getContext("2d");

    var labels = ["子系统", "用户", "工单", "资产", "流程", "公告", "文档"];
    var values = [
      data.subsystem_count || 0,
      data.active_users || 0,
      data.total_tickets || 0,
      data.total_assets || 0,
      data.total_flows || 0,
      data.notices_count || 0,
      data.documents_count || 0,
    ];

    var maxVal = Math.max.apply(null, values.concat([1]));
    var w = Math.max(400, canvas.parentElement.clientWidth - 40);
    var h = 260;
    canvas.width = w;
    canvas.height = h;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";

    var barW = Math.max(18, (w - 80) / labels.length - 14);
    var colors = ["#4dabf7", "#20c997", "#ff922b", "#845ef7", "#f06595", "#339af0", "#94d82d"];

    ctx.strokeStyle = "#eee";
    ctx.lineWidth = 1;
    for (var i = 0; i < 5; i++) {
      var gy = 30 + (h - 60) * i / 4;
      ctx.beginPath(); ctx.moveTo(50, gy); ctx.lineTo(w - 20, gy); ctx.stroke();
    }

    for (var j = 0; j < labels.length; j++) {
      var barH = (values[j] / maxVal) * (h - 80);
      var x = 50 + j * (barW + 14) + (w - 80 - labels.length * (barW + 14)) / 2;
      var by = h - 40 - barH;

      ctx.fillStyle = colors[j];
      ctx.fillRect(x, by, barW, barH);

      ctx.fillStyle = "#333";
      ctx.font = "11px system-ui";
      ctx.textAlign = "center";
      ctx.fillText(values[j], x + barW / 2, by - 6);

      ctx.fillStyle = "#666";
      ctx.font = "10px system-ui";
      ctx.fillText(labels[j], x + barW / 2, h - 20);
    }
  }

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  if (typeof window !== "undefined") {
    window.App = window.App || {};
    window.App.views = window.App.views || {};
    window.App.views["data-portal"] = { render: render };
  }
})();
