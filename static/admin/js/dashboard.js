/**
 * 仪表盘渲染
 */
import { api } from "./api.js";
import { showToast, showConfirm } from "../app.js";

let minersRefreshTimer = null;

// ===== Chart.js trend charts =====
const MAX_POINTS = 50;
const _hashrateData = [];
const _solveTimeData = [];
let _hashrateChart = null;
let _solveTimeChart = null;

function _makeChartDefaults() {
  return {
    type: "line",
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: true,
      interaction: { mode: "nearest", intersect: false },
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
      scales: {
        x: { display: false },
        y: {
          display: true,
          grid: { color: "rgba(128,128,128,0.15)" },
          ticks: {
            color: "rgba(128,128,128,0.8)",
            font: { size: 10, family: "'JetBrains Mono', monospace" },
            maxTicksLimit: 5,
          },
        },
      },
    },
  };
}

function _initCharts() {
  const hrCanvas = document.getElementById("chart-hashrate");
  const stCanvas = document.getElementById("chart-solve-time");
  if (!hrCanvas || !stCanvas || typeof Chart === "undefined") return;

  // Destroy existing if re-initialising
  if (_hashrateChart) { _hashrateChart.destroy(); _hashrateChart = null; }
  if (_solveTimeChart) { _solveTimeChart.destroy(); _solveTimeChart = null; }

  const hrDef = _makeChartDefaults();
  hrDef.data = {
    labels: _hashrateData.map((_, i) => i),
    datasets: [{
      data: _hashrateData,
      borderColor: "#22c55e",
      backgroundColor: "rgba(34,197,94,0.1)",
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 1.5,
    }],
  };
  _hashrateChart = new Chart(hrCanvas, hrDef);

  const stDef = _makeChartDefaults();
  stDef.data = {
    labels: _solveTimeData.map((_, i) => i),
    datasets: [{
      data: _solveTimeData,
      borderColor: "#6366f1",
      backgroundColor: "rgba(99,102,241,0.1)",
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 1.5,
    }],
  };
  _solveTimeChart = new Chart(stCanvas, stDef);
}

function _pushChartPoint(arr, chart, value) {
  arr.push(value);
  if (arr.length > MAX_POINTS) arr.shift();
  if (!chart) return;
  chart.data.labels = arr.map((_, i) => i);
  chart.data.datasets[0].data = [...arr];
  chart.update("none");
}
// ===== end charts =====

export function initDashboard() {
  // 首次加载矿工列表和黑名单
  refreshMiners();
  refreshBlacklist();
  // 每 5 秒刷新矿工列表和黑名单
  minersRefreshTimer = setInterval(() => {
    refreshMiners();
    refreshBlacklist();
  }, 5000);

  // 初始化趋势图（Chart.js 通过 CDN 同步加载，无需等待）
  _initCharts();
}

export function destroyDashboard() {
  if (minersRefreshTimer) {
    clearInterval(minersRefreshTimer);
    minersRefreshTimer = null;
  }
}

export function renderDashboardUpdate(data) {
  // 更新统计卡片（由 WebSocket STATUS_UPDATE 驱动）
  setText("stat-miners", data.active_miners ?? "--");
  setText("stat-connections", data.active_connections ?? "--");
  setText("stat-hashrate", formatHR(data.total_hashrate || 0));
  setText("stat-last-solve", data.last_solve_time != null ? `${data.last_solve_time.toFixed(1)}s` : "--");
  setText("stat-avg-solve", data.average_solve_time != null ? `${data.average_solve_time.toFixed(1)}s` : "--");
  setText("stat-difficulty", data.difficulty ?? "--");
  setText("stat-banned", data.banned_ips_count ?? "0");

  // 谜题信息
  setText("info-seed", (data.current_seed || "").slice(0, 16) + "...");
  setText("info-mining-time", formatTime(data.mining_time || 0));
  setText("info-mining-status", data.is_mining_active ? "挖矿中" : "空闲");

  const statusEl = document.getElementById("info-mining-status");
  if (statusEl) {
    statusEl.style.color = data.is_mining_active ? "var(--success)" : "var(--text-tertiary)";
  }

  // 更新趋势图
  _pushChartPoint(_hashrateData, _hashrateChart, data.total_hashrate || 0);
  _pushChartPoint(_solveTimeData, _solveTimeChart, data.average_solve_time || 0);
}

async function refreshMiners() {
  try {
    const miners = await api.getMiners();
    const tbody = document.getElementById("miners-tbody");
    if (!tbody) return;

    if (miners.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-tertiary);padding:1.5rem;">暂无活跃矿工</td></tr>`;
      return;
    }

    tbody.innerHTML = miners.map(m => `
      <tr>
        <td style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;">${escapeHtml(m.ip)}</td>
        <td style="font-family:'JetBrains Mono',monospace;">${m.hashrate.toFixed(2)} H/s</td>
        <td>${m.last_seen.toFixed(0)}秒前</td>
        <td style="text-align:center;"><button class="admin-btn danger" style="padding:0.25rem 0.625rem;font-size:0.6875rem;" onclick="banMinerIp('${escapeHtml(m.ip)}')">封禁</button></td>
      </tr>
    `).join("");
  } catch (_) {}
}

async function refreshBlacklist() {
  try {
    const ips = await api.getBlacklist();
    const tbody = document.getElementById("blacklist-tbody");
    if (!tbody) return;

    if (ips.length === 0) {
      tbody.innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--text-tertiary);padding:1.5rem;">暂无封禁 IP</td></tr>`;
      return;
    }

    tbody.innerHTML = ips.map(ip => `
      <tr>
        <td style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;">${escapeHtml(ip)}</td>
        <td style="text-align:center;"><button class="admin-btn warning" style="padding:0.25rem 0.625rem;font-size:0.6875rem;" onclick="unbanIp('${escapeHtml(ip)}')">解封</button></td>
      </tr>
    `).join("");
  } catch (_) {}
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function formatTime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatHR(rate) {
  if (rate >= 1000) return (rate / 1000).toFixed(2) + " KH/s";
  return rate.toFixed(2) + " H/s";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

window.banMinerIp = function (ip) {
  showConfirm(
    "封禁 IP: " + ip,
    `封禁并断开来自 IP ${ip} 的所有连接。该 IP 将被阻止重新连接。`,
    async () => {
      try {
        const res = await api.kickIp(ip);
        showToast(res.message || "完成", "success");
        refreshMiners();
        refreshBlacklist();
      } catch (e) { showToast("失败: " + e.message, "error"); }
    },
  );
};

window.unbanIp = function (ip) {
  showConfirm(
    "解封 IP: " + ip,
    `将 IP ${ip} 从黑名单中移除。该 IP 将可以重新连接。`,
    async () => {
      try {
        const res = await api.unbanIp(ip);
        showToast(res.message || "完成", "success");
        refreshBlacklist();
      } catch (e) { showToast("失败: " + e.message, "error"); }
    },
  );
};
