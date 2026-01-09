/**
 * WebSocket 连接和消息处理模块
 * 管理实时通信、心跳、消息分发等功能
 */

import { state } from "./state.js";
import { log } from "./logger.js";
import { updateNetworkHashRate, resetNetworkHashRate } from "./hashrate.js";
import { turnstileManager } from "./turnstile.js";

/**
 * 更新 WebSocket 状态显示
 * @param {string} status - 状态 (connected, connecting, disconnected, error)
 * @param {string} text - 状态文本
 * @param {number|null} online - 在线人数
 */
function updateWsStatus(status, text, online = null) {
  const wsStatus = document.getElementById("wsStatus");
  const statusText = wsStatus.querySelector(".status-text");

  wsStatus.setAttribute("data-status", status);

  // 如果有在线人数，显示在状态文字中
  if (online !== null && status === "connected") {
    statusText.textContent = `${text} (${online}人)`;
  } else {
    statusText.textContent = text;
  }
}

/**
 * 开始 WebSocket 心跳
 */
function startWsPing() {
  // 清除旧的定时器
  if (state.wsPingTimer) {
    clearInterval(state.wsPingTimer);
  }

  // 每10秒发送一次 ping
  state.wsPingTimer = setInterval(() => {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send("ping");
    }
  }, 10000);
}

/**
 * 停止 WebSocket 心跳
 */
function stopWsPing() {
  if (state.wsPingTimer) {
    clearInterval(state.wsPingTimer);
    state.wsPingTimer = null;
  }
}

/**
 * 发送算力到服务器
 * @param {number} rate - 算力值
 */
export function sendHashrateToServer(rate) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN && state.mining) {
    state.ws.send(JSON.stringify({
      type: 'hashrate',
      payload: {
        rate: rate,
        timestamp: Date.now() / 1000
      }
    }));
  }
}

/**
 * 通知服务器开始挖矿
 */
export function notifyMiningStart() {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: "mining_start" }));
    log("⏱️ 已通知服务器开始计时");
  }
}

/**
 * 通知服务器停止挖矿
 */
export function notifyMiningStop() {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: "mining_stop" }));
  }
}

/**
 * 处理 WebSocket 消息
 * @param {Object} data - 消息数据
 */
function handleWebSocketMessage(data) {
  if (data.type === "PONG") {
    // 更新在线人数
    state.onlineCount = data.online;
    updateWsStatus("connected", "已连接", state.onlineCount);
  } else if (data.type === "PUZZLE_RESET") {
    log("🔄 检测到新的 Puzzle，本轮结束！", "error");
    log(`新 Seed: ${data.seed.substring(0, 16)}...`);

    // 更新难度显示
    document.getElementById("difficulty").textContent = data.difficulty;

    // 如果正在挖矿，自动重启挖矿（继续竞争）
    if (state.mining) {
      log("🔄 自动重新开始挖矿，继续竞争...");
      // 动态导入 mining.js 以避免循环依赖
      import("./mining.js").then(({ stopMining, startMining }) => {
        stopMining();
        // 延迟100ms后重新开始，确保停止完成
        setTimeout(() => {
          startMining();
        }, 100);
      });
    }
  } else if (data.type === "NETWORK_HASHRATE") {
    // 处理全网算力更新
    updateNetworkHashRate(data.total_hashrate, data.active_miners);
  }
}

/**
 * 连接 WebSocket
 */
export function connectWebSocket() {
  // 检查 Turnstile Token
  if (!state.turnstileToken) {
    log("WebSocket: 等待 Turnstile 验证...", "warning");
    updateWsStatus("disconnected", "等待验证");
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/api/ws?token=${encodeURIComponent(state.turnstileToken)}`;

  // 设置连接中状态
  updateWsStatus("connecting", "连接中");
  log("🔄 正在连接 WebSocket...");

  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    log("📡 WebSocket 已连接");
    updateWsStatus("connected", "已连接");

    // 清除重连定时器
    if (state.wsReconnectTimer) {
      clearTimeout(state.wsReconnectTimer);
      state.wsReconnectTimer = null;
    }

    // 启动心跳
    startWsPing();
    // 立即发送一次 ping 获取在线人数
    state.ws.send("ping");
  };

  state.ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWebSocketMessage(data);
    } catch (error) {
      log(`WebSocket 消息解析错误: ${error.message}`, "error");
    }
  };

  state.ws.onerror = (error) => {
    log("WebSocket 连接错误", "error");
    updateWsStatus("error", "错误");
    stopWsPing();
  };

  state.ws.onclose = (event) => {
    // 检查是否是 Token 验证失败（1008 错误码）
    if (event.code === 1008) {
      log("❌ Turnstile Token 验证失败，请刷新页面重新验证", "error");
      updateWsStatus("error", "验证失败");
      stopWsPing();
      // 禁用 UI，不自动重连
      turnstileManager.disableUI();
      resetNetworkHashRate();
      return;
    }

    log("⚠️ WebSocket 已断开，3秒后重连...");
    updateWsStatus("disconnected", "断开");
    stopWsPing();
    resetNetworkHashRate();

    // 3秒后重连
    state.wsReconnectTimer = setTimeout(() => {
      connectWebSocket();
    }, 3000);
  };
}
