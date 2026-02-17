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
    "重置谜题",
    "这将生成新种子并广播给所有矿工。所有当前挖矿进度将丢失。",
    async () => {
      try {
        const res = await api.resetPuzzle();
        showToast(res.message || "谜题已重置", "success");
      } catch (e) { showToast("失败: " + e.message, "error"); }
    },
  );
};

window.opKickAll = function () {
  showConfirm(
    "踢出所有矿工",
    "这将断开所有 WebSocket 连接。矿工需要重新连接。",
    async () => {
      try {
        const res = await api.kickAll();
        showToast(res.message || "完成", "success");
      } catch (e) { showToast("失败: " + e.message, "error"); }
    },
  );
};

window.opClearSessions = function () {
  showConfirm(
    "清除所有会话",
    "这将清除所有会话令牌。所有用户需要重新通过 Turnstile 验证。",
    async () => {
      try {
        const res = await api.clearSessions();
        showToast(res.message || "完成", "success");
      } catch (e) { showToast("失败: " + e.message, "error"); }
    },
  );
};

window.opRegenerateHmac = function () {
  const input = document.getElementById("op-hmac-input");
  const hex = (input?.value || "").trim();
  const action = hex ? "设置 HMAC 密钥" : "重新生成 HMAC 密钥";
  const warning = hex
    ? `将 HMAC 密钥设置为提供的密钥（${hex.length} 个十六进制字符）。这将使所有已签发的邀请码失效。`
    : "随机生成 256 位 HMAC 密钥。这将使所有已签发的邀请码失效。";
  showConfirm(
    action,
    "警告: " + warning,
    async () => {
      try {
        const body = hex ? { hmac_secret: hex } : {};
        const res = await api.regenerateHmac(body);
        showToast(res.message || "完成", "warning");
        if (input) input.value = "";
      } catch (e) { showToast("失败: " + e.message, "error"); }
    },
  );
};

window.opBanIp = function () {
  const input = document.getElementById("op-ban-ip-input");
  const ip = (input?.value || "").trim();
  if (!ip) { showToast("请输入 IP 地址", "error"); return; }
  showConfirm(
    "封禁 IP: " + ip,
    `封禁 IP ${ip} 并断开其所有连接。`,
    async () => {
      try {
        const res = await api.kickIp(ip);
        showToast(res.message || "完成", "success");
        input.value = "";
      } catch (e) { showToast("失败: " + e.message, "error"); }
    },
  );
};

window.opUnbanIp = function () {
  const input = document.getElementById("op-unban-ip-input");
  const ip = (input?.value || "").trim();
  if (!ip) { showToast("请输入 IP 地址", "error"); return; }
  showConfirm(
    "解封 IP: " + ip,
    `将 IP ${ip} 从黑名单中移除。`,
    async () => {
      try {
        const res = await api.unbanIp(ip);
        showToast(res.message || "完成", "success");
        input.value = "";
      } catch (e) { showToast("失败: " + e.message, "error"); }
    },
  );
};
