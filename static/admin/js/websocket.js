/**
 * Admin WebSocket — 实时状态推送
 */
import { adminState } from "./state.js";
import { renderDashboardUpdate } from "./dashboard.js";

let reconnectTimer = null;

function setWsStatus(status) {
  const dot = document.getElementById("ws-status-dot");
  const text = document.getElementById("ws-status-text");
  if (!dot || !text) return;

  const styles = {
    connected:    { color: "#22c55e", label: "已连接" },
    disconnected: { color: "#ef4444", label: "已断线，数据过时" },
    reconnecting: { color: "#f59e0b", label: "重连中…" },
  };
  const s = styles[status] || styles.disconnected;
  dot.style.background = s.color;
  text.textContent = s.label;
  text.style.color = status === "connected" ? "var(--success, #22c55e)" :
                     status === "reconnecting" ? "var(--warning, #f59e0b)" :
                     "var(--danger, #ef4444)";
}

function showWsToast(message, type) {
  // Reuse the global showToast if available (defined in app.js and exposed on window)
  if (typeof window.showToast === "function") {
    window.showToast(message, type);
  }
}

export function connectAdminWs() {
  if (adminState.ws) {
    try { adminState.ws.close(); } catch (_) {}
  }

  setWsStatus("reconnecting");

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/api/admin/ws?token=${encodeURIComponent(adminState.token)}`;

  const ws = new WebSocket(url);
  adminState.ws = ws;

  ws.onopen = () => {
    console.log("[Admin WS] Connected");
    setWsStatus("connected");
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === "STATUS_UPDATE") {
        renderDashboardUpdate(data);
      }
    } catch (_) {}
  };

  ws.onclose = (e) => {
    console.log("[Admin WS] Closed", e.code);
    adminState.ws = null;
    if (e.code !== 1008) {
      setWsStatus("reconnecting");
      showWsToast("Admin WebSocket 断线，正在重连…", "warning");
      // 自动重连
      reconnectTimer = setTimeout(connectAdminWs, 3000);
    } else {
      setWsStatus("disconnected");
      showWsToast("Admin WebSocket 已断开（认证失败）", "error");
    }
  };

  ws.onerror = () => {
    console.error("[Admin WS] Error");
    setWsStatus("disconnected");
  };
}

export function disconnectAdminWs() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (adminState.ws) {
    adminState.ws.close();
    adminState.ws = null;
  }
  setWsStatus("disconnected");
}
