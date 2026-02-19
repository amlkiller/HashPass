/**
 * HashPass Admin — Entry Point
 * Login flow + Tab initialization
 */
import { adminState } from "./js/state.js";
import { connectAdminWs, disconnectAdminWs } from "./js/websocket.js";
import { initDashboard, destroyDashboard } from "./js/dashboard.js";
import { initParams } from "./js/params.js";
import { initLogs } from "./js/logs.js";
import { initOperations } from "./js/operations.js";
import { initAppLogs } from "./js/applogs.js";

// ===== Toast System =====

const toastContainer = document.getElementById("toast-container");

export function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("fade-out");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ===== Confirm Modal =====

export function showConfirm(title, message, onConfirm) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-card">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(message)}</p>
      <div class="modal-actions">
        <button class="admin-btn" id="modal-cancel">取消</button>
        <button class="admin-btn danger" id="modal-confirm">确认</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  overlay.querySelector("#modal-cancel").onclick = () => overlay.remove();
  overlay.querySelector("#modal-confirm").onclick = async () => {
    overlay.remove();
    await onConfirm();
  };
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ===== Theme =====

function initTheme() {
  const saved = localStorage.getItem("hashpass-theme") || "dark";
  applyTheme(saved);

  document.querySelectorAll(".theme-btn").forEach(btn => {
    if (btn.dataset.theme === saved) btn.classList.add("active");
    btn.addEventListener("click", () => {
      document.querySelectorAll(".theme-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      applyTheme(btn.dataset.theme);
      localStorage.setItem("hashpass-theme", btn.dataset.theme);
    });
  });
}

function applyTheme(theme) {
  if (theme === "system") {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", prefersDark ? "dark" : "light");
  } else {
    document.documentElement.setAttribute("data-theme", theme);
  }
}

// ===== Login =====

function showLogin() {
  document.getElementById("login-view").style.display = "flex";
  document.getElementById("admin-view").style.display = "none";
}

function showAdmin() {
  document.getElementById("login-view").style.display = "none";
  document.getElementById("admin-view").style.display = "flex";
  connectAdminWs();
  switchTab("dashboard");
}

window.adminLogin = async function () {
  const input = document.getElementById("login-token");
  const errorEl = document.getElementById("login-error");
  const token = input.value.trim();

  if (!token) {
    errorEl.textContent = "请输入管理员令牌";
    errorEl.style.display = "block";
    return;
  }

  // 验证 token
  try {
    const res = await fetch("/api/admin/status", {
      headers: { "Authorization": `Bearer ${token}` },
    });
    if (res.ok) {
      adminState.token = token;
      sessionStorage.setItem("admin_token", token);
      errorEl.style.display = "none";
      showAdmin();
    } else {
      errorEl.textContent = "令牌无效";
      errorEl.style.display = "block";
    }
  } catch (e) {
    errorEl.textContent = "连接错误";
    errorEl.style.display = "block";
  }
};

window.adminLogout = function () {
  sessionStorage.removeItem("admin_token");
  adminState.token = "";
  disconnectAdminWs();
  showLogin();
};

// ===== Tab System =====

let currentCleanup = null;

function switchTab(tab) {
  adminState.currentTab = tab;

  // Update tab buttons
  document.querySelectorAll(".admin-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.tab === tab);
  });

  // Show/hide panels
  document.querySelectorAll(".tab-panel").forEach(p => {
    p.style.display = p.dataset.panel === tab ? "block" : "none";
  });

  // Cleanup previous tab
  if (currentCleanup) {
    currentCleanup();
    currentCleanup = null;
  }

  // Init current tab
  if (tab === "dashboard") {
    initDashboard();
    currentCleanup = destroyDashboard;
  } else if (tab === "params") {
    initParams();
  } else if (tab === "logs") {
    initLogs();
  } else if (tab === "applogs") {
    initAppLogs();
  } else if (tab === "operations") {
    initOperations();
  }
}

window.switchTab = switchTab;

// ===== Init =====

document.addEventListener("DOMContentLoaded", () => {
  initTheme();

  // 按 Enter 登录
  const loginInput = document.getElementById("login-token");
  if (loginInput) {
    loginInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") window.adminLogin();
    });
  }

  // Check saved token
  if (adminState.token) {
    // Validate saved token
    fetch("/api/admin/status", {
      headers: { "Authorization": `Bearer ${adminState.token}` },
    }).then(res => {
      if (res.ok) {
        showAdmin();
      } else {
        sessionStorage.removeItem("admin_token");
        adminState.token = "";
        showLogin();
      }
    }).catch(() => showLogin());
  } else {
    showLogin();
  }
});
