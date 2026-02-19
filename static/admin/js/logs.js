/**
 * 日志查看器
 */
import { api } from "./api.js";
import { adminState } from "./state.js";

let statsLoaded = false;

export function initLogs() {
  loadLogs();
  if (!statsLoaded) {
    loadLogStats();
    statsLoaded = true;
  }
}

async function loadLogs() {
  try {
    const data = await api.getLogs(
      adminState.logsPage,
      50,
      adminState.logsSearch,
      adminState.logsFile,
    );
    renderLogs(data);
    renderFileSelector(data.files);
    renderPagination(data);
  } catch (_) {}
}

async function loadLogStats() {
  try {
    const stats = await api.getLogStats();
    const el = document.getElementById("log-stats-summary");
    if (!el) return;
    el.innerHTML = `
      <span>总计: <strong>${stats.total_codes}</strong></span>
      <span>访客: <strong>${stats.unique_visitors}</strong></span>
      <span>平均求解: <strong>${stats.avg_solve_time}秒</strong></span>
      <span>中位数: <strong>${stats.median_solve_time}秒</strong></span>
    `;
  } catch (_) {}
}

function renderLogs(data) {
  const tbody = document.getElementById("logs-tbody");
  if (!tbody) return;

  if (data.records.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-tertiary);padding:1.5rem;">未找到记录</td></tr>`;
    return;
  }

  tbody.innerHTML = data.records.map(r => {
    const ts = r.timestamp ? new Date(r.timestamp).toLocaleString() : "--";
    return `
      <tr>
        <td style="font-size:0.6875rem;white-space:nowrap;">${escapeHtml(ts)}</td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;white-space:nowrap;">${escapeHtml(r.invite_code || "")}</td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:0.6875rem;white-space:nowrap;" title="${escapeHtml(r.visitor_id || "")}">${escapeHtml(r.visitor_id || "")}</td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;white-space:nowrap;">${escapeHtml(r.real_ip || "")}</td>
        <td style="white-space:nowrap;">${r.difficulty ?? "--"}</td>
        <td style="white-space:nowrap;">${r.solve_time != null ? r.solve_time + "s" : "--"}</td>
        <td style="font-size:0.6875rem;white-space:nowrap;" title="${escapeHtml(r.adjustment_reason || "")}">${escapeHtml(r.adjustment_reason || "")}</td>
      </tr>
    `;
  }).join("");
}

function renderFileSelector(files) {
  const sel = document.getElementById("log-file-select");
  if (!sel || sel.dataset.loaded === "1") return;
  sel.dataset.loaded = "1";
  sel.innerHTML = files.map(f =>
    `<option value="${escapeHtml(f)}"${f === adminState.logsFile ? " selected" : ""}>${escapeHtml(f)}</option>`
  ).join("");
}

function renderPagination(data) {
  const el = document.getElementById("logs-pagination");
  if (!el) return;
  el.innerHTML = `
    <button onclick="window._logsPage(${data.page - 1})" ${data.page <= 1 ? "disabled" : ""}>上一页</button>
    <span class="page-info">${data.page} / ${data.pages}</span>
    <button onclick="window._logsPage(${data.page + 1})" ${data.page >= data.pages ? "disabled" : ""}>下一页</button>
  `;
}

// Expose to global
window._logsPage = function (p) {
  adminState.logsPage = Math.max(1, p);
  loadLogs();
};

window._logsSearch = function () {
  const el = document.getElementById("log-search-input");
  adminState.logsSearch = el ? el.value : "";
  adminState.logsPage = 1;
  loadLogs();
};

window._logsFileChange = function () {
  const el = document.getElementById("log-file-select");
  adminState.logsFile = el ? el.value : "verify.json";
  adminState.logsPage = 1;
  loadLogs();
};

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
