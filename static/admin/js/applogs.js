/**
 * Admin — App Logs Viewer
 */
import { api } from "./api.js";

let currentPage = 1;
let currentSearch = "";
let currentFile = "hashpass.log";
let currentLevel = "";

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function getLevelClass(line) {
  if (/ CRITICAL | ERROR /.test(line)) return "applog-error";
  if (/ WARNING /.test(line)) return "applog-warning";
  if (/ DEBUG /.test(line)) return "applog-debug";
  return "";
}

async function loadAppLogs() {
  const tbody = document.getElementById("applog-tbody");
  const paginationEl = document.getElementById("applog-pagination");

  if (tbody) tbody.innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--text-tertiary);padding:1.5rem;">加载中...</td></tr>`;

  try {
    const data = await api.getAppLogs(currentPage, 100, currentSearch, currentFile, currentLevel);

    // Populate file selector
    const fileSelect = document.getElementById("applog-file-select");
    if (fileSelect && data.files && data.files.length > 0) {
      const prevValue = fileSelect.value;
      fileSelect.innerHTML = data.files.map(f =>
        `<option value="${escapeHtml(f)}"${f === currentFile ? " selected" : ""}>${escapeHtml(f)}</option>`
      ).join("");
      // Keep current selection if still valid
      if (data.files.includes(prevValue)) {
        fileSelect.value = prevValue;
      }
    }

    if (!data.lines || data.lines.length === 0) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--text-tertiary);padding:1.5rem;">暂无日志</td></tr>`;
      if (paginationEl) paginationEl.innerHTML = "";
      return;
    }

    // Render rows
    if (tbody) {
      const offset = (data.page - 1) * 100;
      tbody.innerHTML = data.lines.map((line, i) => {
        const cls = getLevelClass(line);
        return `<tr class="${cls}">
          <td style="text-align:right;color:var(--text-tertiary);width:3.5rem;user-select:none;">${offset + i + 1}</td>
          <td class="applog-line">${escapeHtml(line)}</td>
        </tr>`;
      }).join("");
    }

    // Pagination
    if (paginationEl) {
      paginationEl.innerHTML = renderPagination(data.page, data.pages, data.total);
    }
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--text-tertiary);padding:1.5rem;">加载失败</td></tr>`;
  }
}

function renderPagination(page, pages, total) {
  if (pages <= 1) return `<span class="page-info">共 ${total} 行</span>`;
  return `
    <button class="admin-btn" onclick="_appLogsPage(${page - 1})" ${page <= 1 ? "disabled" : ""}>上一页</button>
    <span class="page-info">第 ${page} / ${pages} 页，共 ${total} 行</span>
    <button class="admin-btn" onclick="_appLogsPage(${page + 1})" ${page >= pages ? "disabled" : ""}>下一页</button>
  `;
}

export function initAppLogs() {
  currentPage = 1;
  currentSearch = document.getElementById("applog-search-input")?.value?.trim() || "";
  currentFile = document.getElementById("applog-file-select")?.value || "hashpass.log";
  currentLevel = document.getElementById("applog-level-select")?.value || "";
  loadAppLogs();
}

// Globals for inline event handlers in HTML
window._appLogsPage = function (page) {
  currentPage = page;
  loadAppLogs();
};

window._appLogsSearch = function () {
  currentPage = 1;
  currentSearch = document.getElementById("applog-search-input")?.value?.trim() || "";
  loadAppLogs();
};

window._appLogsFileChange = function () {
  currentPage = 1;
  currentFile = document.getElementById("applog-file-select")?.value || "hashpass.log";
  loadAppLogs();
};

window._appLogsLevelChange = function () {
  currentPage = 1;
  currentLevel = document.getElementById("applog-level-select")?.value || "";
  loadAppLogs();
};
