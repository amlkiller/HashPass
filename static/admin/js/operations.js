/**
 * 手动操作面板
 */
import { api } from "./api.js";
import { showToast, showConfirm } from "../app.js";

export function initOperations() {
  // 绑定按钮事件
}

window.opResetPuzzle = function () {
  showConfirm(
    "Reset Puzzle",
    "This will generate a new seed and broadcast to all miners. All current mining progress will be lost.",
    async () => {
      try {
        const res = await api.resetPuzzle();
        showToast(res.message || "Puzzle reset", "success");
      } catch (e) { showToast("Failed: " + e.message, "error"); }
    },
  );
};

window.opKickAll = function () {
  showConfirm(
    "Kick All Miners",
    "This will disconnect all WebSocket connections. Miners will need to reconnect.",
    async () => {
      try {
        const res = await api.kickAll();
        showToast(res.message || "Done", "success");
      } catch (e) { showToast("Failed: " + e.message, "error"); }
    },
  );
};

window.opClearSessions = function () {
  showConfirm(
    "Clear All Sessions",
    "This will clear all session tokens. All users will need to re-verify through Turnstile.",
    async () => {
      try {
        const res = await api.clearSessions();
        showToast(res.message || "Done", "success");
      } catch (e) { showToast("Failed: " + e.message, "error"); }
    },
  );
};

window.opRegenerateHmac = function () {
  const input = document.getElementById("op-hmac-input");
  const hex = (input?.value || "").trim();
  const action = hex ? "Set HMAC Secret" : "Regenerate HMAC Secret";
  const warning = hex
    ? `Set HMAC secret to the provided key (${hex.length} hex chars). This will invalidate ALL previously issued invite codes.`
    : "Generate a random 256-bit HMAC secret. This will invalidate ALL previously issued invite codes.";
  showConfirm(
    action,
    "WARNING: " + warning,
    async () => {
      try {
        const body = hex ? { hmac_secret: hex } : {};
        const res = await api.regenerateHmac(body);
        showToast(res.message || "Done", "warning");
        if (input) input.value = "";
      } catch (e) { showToast("Failed: " + e.message, "error"); }
    },
  );
};

window.opBanIp = function () {
  const input = document.getElementById("op-ban-ip-input");
  const ip = (input?.value || "").trim();
  if (!ip) { showToast("Please enter an IP address", "error"); return; }
  showConfirm(
    "Ban IP: " + ip,
    `Ban IP ${ip} and disconnect all its connections.`,
    async () => {
      try {
        const res = await api.kickIp(ip);
        showToast(res.message || "Done", "success");
        input.value = "";
      } catch (e) { showToast("Failed: " + e.message, "error"); }
    },
  );
};

window.opUnbanIp = function () {
  const input = document.getElementById("op-unban-ip-input");
  const ip = (input?.value || "").trim();
  if (!ip) { showToast("Please enter an IP address", "error"); return; }
  showConfirm(
    "Unban IP: " + ip,
    `Remove IP ${ip} from the blacklist.`,
    async () => {
      try {
        const res = await api.unbanIp(ip);
        showToast(res.message || "Done", "success");
        input.value = "";
      } catch (e) { showToast("Failed: " + e.message, "error"); }
    },
  );
};
