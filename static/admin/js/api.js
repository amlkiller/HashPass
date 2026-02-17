/**
 * Admin API 客户端（自动携带 Auth header）
 */
import { adminState } from "./state.js";

const BASE = "/api/admin";

async function request(path, options = {}) {
  const headers = {
    "Authorization": `Bearer ${adminState.token}`,
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (res.status === 401 || res.status === 403) {
    // Token 失效，回到登录
    sessionStorage.removeItem("admin_token");
    adminState.token = "";
    window.location.reload();
    throw new Error("Unauthorized");
  }

  return res.json();
}

export const api = {
  getStatus: () => request("/status"),
  getMiners: () => request("/miners"),
  getSessions: () => request("/sessions"),
  getLogs: (page, perPage, search, file) =>
    request(`/logs?page=${page}&per_page=${perPage}&search=${encodeURIComponent(search)}&file=${encodeURIComponent(file)}`),
  getLogStats: () => request("/logs/stats"),

  updateDifficulty: (data) => request("/difficulty", { method: "POST", body: JSON.stringify(data) }),
  updateTargetTime: (data) => request("/target-time", { method: "POST", body: JSON.stringify(data) }),
  updateArgon2: (data) => request("/argon2", { method: "POST", body: JSON.stringify(data) }),
  updateWorkerCount: (data) => request("/worker-count", { method: "POST", body: JSON.stringify(data) }),

  resetPuzzle: () => request("/reset-puzzle", { method: "POST" }),
  kickAll: () => request("/kick-all", { method: "POST" }),
  kickIp: (ip) => request("/kick", { method: "POST", body: JSON.stringify({ ip }) }),
  unbanIp: (ip) => request("/unban", { method: "POST", body: JSON.stringify({ ip }) }),
  getBlacklist: () => request("/blacklist"),
  clearSessions: () => request("/clear-sessions", { method: "POST" }),
  regenerateHmac: (data) => request("/regenerate-hmac", { method: "POST", body: JSON.stringify(data || {}) }),
};
