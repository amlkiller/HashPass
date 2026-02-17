/**
 * Admin WebSocket — 实时状态推送
 */
import { adminState } from "./state.js";
import { renderDashboardUpdate } from "./dashboard.js";

let reconnectTimer = null;

export function connectAdminWs() {
  if (adminState.ws) {
    try { adminState.ws.close(); } catch (_) {}
  }

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/api/admin/ws?token=${encodeURIComponent(adminState.token)}`;

  const ws = new WebSocket(url);
  adminState.ws = ws;

  ws.onopen = () => {
    console.log("[Admin WS] Connected");
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
      // 自动重连
      reconnectTimer = setTimeout(connectAdminWs, 3000);
    }
  };

  ws.onerror = () => {
    console.error("[Admin WS] Error");
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
}
