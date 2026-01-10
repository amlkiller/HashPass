/**
 * Cloudflare Turnstile 验证管理模块
 * 处理人机验证的初始化、回调和状态管理
 */

import { state } from "./state.js";
import { log } from "./logger.js";
import { connectWebSocket } from "./websocket.js";

/**
 * Turnstile 管理器对象
 */
export const turnstileManager = {
  /**
   * 初始化 Turnstile
   */
  async init() {
    try {
      log("正在初始化 Turnstile...");

      // 1. 获取 Site Key
      const config = await fetch("/api/turnstile/config").then((r) => r.json());
      state.turnstilesiteKey = config.siteKey;

      if (config.testMode) {
        log("⚠️ Turnstile 测试模式已启用", "warning");
      }

      // 2. 等待 Turnstile API 加载
      await this.waitForTurnstile();

      // 3. 渲染 Widget
      log("正在渲染 Turnstile Widget...");
      state.turnstileWidgetId = window.turnstile.render("#turnstileWidget", {
        sitekey: state.turnstilesiteKey,
        callback: (token) => this.onSuccess(token),
        "error-callback": () => this.onError(),
        "expired-callback": () => this.onExpired(),
        "timeout-callback": () => this.onTimeout(),
        theme:
          document.documentElement.getAttribute("data-theme") === "light"
            ? "light"
            : "dark",
      });

      log("Turnstile Widget 已加载");
    } catch (error) {
      log(`Turnstile 初始化失败: ${error.message}`, "error");
      this.disableUI();
    }
  },

  /**
   * 等待 Turnstile API 加载
   */
  async waitForTurnstile() {
    // 轮询等待 window.turnstile 可用
    for (let i = 0; i < 50; i++) {
      if (window.turnstile) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error("Turnstile script 加载超时");
  },

  /**
   * 验证成功回调
   * @param {string} token - Turnstile Token
   */
  onSuccess(token) {
    state.turnstileToken = token;
    log("✅ Turnstile 验证成功", "success");
    this.enableUI();

    // 验证成功后隐藏 Turnstile 组件
    setTimeout(() => {
      const turnstileContainer = document.getElementById("turnstileContainer");
      if (turnstileContainer) {
        turnstileContainer.classList.add("hidden");
      }
    }, 1000); // 延迟1秒后隐藏，让用户看到成功状态
  },

  /**
   * 验证失败回调
   */
  onError() {
    log("Turnstile 验证失败", "error");
    this.disableUI();
  },

  /**
   * Token 过期回调
   * 注意：由于使用 Session Token 机制，Turnstile Token 过期不影响功能
   */
  onExpired() {
    log("Turnstile Token 已过期（不影响功能，使用 Session Token 维持连接）", "info");
    // 不再禁用UI或重置Widget
    // Session Token 会保持 WebSocket 连接和所有功能正常运行

    // 确保容器保持隐藏状态
    const turnstileContainer = document.getElementById("turnstileContainer");
    if (turnstileContainer && !turnstileContainer.classList.contains("hidden")) {
      turnstileContainer.classList.add("hidden");
    }
  },

  /**
   * 验证超时回调
   */
  onTimeout() {
    log("Turnstile 验证超时", "error");
    this.disableUI();
  },

  /**
   * 启用 UI
   */
  async enableUI() {
    // 启用挖矿按钮
    document.getElementById("startBtn").disabled = false;
    document.getElementById("statusText").textContent = "就绪";

    // 建立 WebSocket 连接
    connectWebSocket();
  },

  /**
   * 禁用 UI
   */
  disableUI() {
    // 禁用所有功能
    document.getElementById("startBtn").disabled = true;
    document.getElementById("stopBtn").disabled = true;
    document.getElementById("statusText").textContent = "等待验证";
  },
};
