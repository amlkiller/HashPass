/**
 * HashPass - 主入口文件
 * 负责导入所有模块并初始化应用程序
 */

// ==================== 外部依赖 ====================
import { getFingerprint } from "https://cdn.jsdelivr.net/npm/@thumbmarkjs/thumbmarkjs/dist/thumbmark.esm.js";

// ==================== 内部模块 ====================
import { state } from "./js/state.js";
import { log } from "./js/logger.js";
import { themeManager } from "./js/theme.js";
import { turnstileManager } from "./js/turnstile.js";
import { startMining, stopMining, copyCode } from "./js/mining.js";

// ==================== 全局函数导出 ====================
// 将函数挂载到 window 对象，供 HTML 内联事件处理器使用
window.startMining = startMining;
window.stopMining = stopMining;
window.copyCode = copyCode;

// ==================== 应用初始化 ====================
/**
 * 应用初始化函数
 * 按顺序执行：主题初始化 → 设备指纹获取 → Turnstile验证
 */
(async function initApplication() {
  try {
    // 1. 初始化主题系统
    log("正在初始化主题系统...");
    themeManager.init();

    // 2. 初始状态禁用所有按钮（等待 Turnstile 验证）
    document.getElementById("startBtn").disabled = true;
    document.getElementById("stopBtn").disabled = true;
    document.getElementById("statusText").textContent = "初始化中...";

    // 3. 获取设备指纹
    log("正在获取设备指纹...");
    const fp = await getFingerprint();
    state.visitorId = fp.hash || fp;
    document.getElementById("fingerprint").textContent = state.visitorId;
    log(`设备 ID: ${state.visitorId}`);

    // 4. 初始化 Turnstile（验证成功后会自动启用 UI 和建立 WebSocket）
    await turnstileManager.init();
  } catch (error) {
    log(`初始化错误: ${error.message}`, "error");
    document.getElementById("statusText").textContent = "初始化失败";
  }
})();
