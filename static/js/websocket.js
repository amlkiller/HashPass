/**
 * WebSocket 连接和消息处理模块
 * 管理实时通信、心跳、消息分发、自动重连等功能
 */

import { state } from "./state.js";
import { log } from "./logger.js";
import { updateNetworkHashRate, resetNetworkHashRate } from "./hashrate.js";

/**
 * 更新 WebSocket 状态显示
 * @param {string} status - 状态 (connected, connecting, disconnected, error)
 * @param {string} text - 状态文本
 * @param {number|null} online - 在线人数
 */
function updateWsStatus(status, text, online = null) {
  const wsStatus = document.getElementById("wsStatus");
  const statusText = wsStatus.querySelector(".status-text");
  const statusDot = wsStatus.querySelector(".status-dot");

  wsStatus.setAttribute("data-status", status);

  // 更新状态点的动画类
  statusDot.classList.remove("animate-pulse-dot", "animate-pulse-dot-fast");
  if (status === "connected") {
    statusDot.classList.add("animate-pulse-dot");
  } else if (status === "connecting") {
    statusDot.classList.add("animate-pulse-dot-fast");
  }

  // 如果有在线人数，显示在状态文字中
  if (online !== null && status === "connected") {
    statusText.textContent = `${text} (${online})`;
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
    log("服务器计时已启动");
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
  // ===== 新增：处理 SESSION_TOKEN 消息 =====
  if (data.type === "SESSION_TOKEN") {
    state.sessionToken = data.token;
    log("会话令牌已接收");
    return;
  }
  // ===== 新增结束 =====

  if (data.type === "PONG") {
    // 更新在线人数
    state.onlineCount = data.online;
    updateWsStatus("connected", "已连接", state.onlineCount);
  } else if (data.type === "PUZZLE_RESET") {
    log("检测到新谜题，本轮已结束！", "error");
    log(`新种子: ${data.seed.substring(0, 16)}...`);

    // 更新难度显示
    document.getElementById("difficulty").textContent = data.difficulty;

    // 如果正在挖矿，自动重启挖矿（继续竞争）
    if (state.mining) {
      log("正在自动重启挖矿...");
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
 * @param {boolean} isReconnect - 是否为重连（默认 false）
 */
export function connectWebSocket(isReconnect = false) {
  // 优先使用 Session Token，否则使用 Turnstile Token
  const token = state.sessionToken || state.turnstileToken;

  if (!token) {
    log("WebSocket: 等待验证...", "warning");
    updateWsStatus("disconnected", "等待中");
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/api/ws?token=${encodeURIComponent(token)}`;

  // 设置连接中状态
  if (isReconnect) {
    log("正在重连 WebSocket...");
  } else {
    log("正在连接 WebSocket...");
  }
  updateWsStatus("connecting", "连接中");

  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    if (isReconnect) {
      log("WebSocket 已重连");
    } else {
      log("WebSocket 已连接");
    }
    updateWsStatus("connected", "已连接");

    // 清除重连计数器
    state.reconnectAttempts = 0;

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
      log(`WebSocket 解析错误: ${error.message}`, "error");
    }
  };

  state.ws.onerror = (error) => {
    log("WebSocket 连接错误", "error");
    updateWsStatus("error", "错误");
    stopWsPing();
  };

  state.ws.onclose = (event) => {
    log(`WebSocket 已断开 (代码: ${event.code})`, "warning");
    updateWsStatus("disconnected", "已断开");
    stopWsPing();
    resetNetworkHashRate();

    // 断开连接时停止挖矿（避免 Worker 继续消耗资源，提交结果也会因 session 失效而失败）
    if (state.mining) {
      import("./mining.js").then(({ stopMining }) => {
        stopMining();
        log("WebSocket 断开，挖矿已自动停止", "warning");
      });
    }

    // 检查是否是 Token 验证失败（1008 = Policy Violation）
    if (event.code === 1008) {
      log("会话已过期，请刷新页面", "error");
      updateWsStatus("error", "会话过期");

      const statusText = document.getElementById("statusText");
      if (statusText) {
        statusText.textContent = "会话过期，请刷新页面";
      }

      // 禁用挖矿功能
      document.getElementById("startBtn").disabled = true;
      document.getElementById("stopBtn").disabled = true;

      return; // 不再尝试自动重连
    }

    // 自动重连（使用指数退避策略）
    attemptReconnect();
  };
}

/**
 * 尝试重连 WebSocket
 */
function attemptReconnect() {
  // 检查是否有可用的 token（优先Session Token，否则用Turnstile Token）
  if (!state.sessionToken && !state.turnstileToken) {
    log("无有效令牌，请刷新页面", "error");
    updateWsStatus("error", "无令牌");

    const statusText = document.getElementById("statusText");
    if (statusText) {
      statusText.textContent = "会话过期，请刷新页面";
    }

    // 禁用挖矿功能
    document.getElementById("startBtn").disabled = true;
    document.getElementById("stopBtn").disabled = true;

    return;
  }

  // 初始化重连计数器
  if (state.reconnectAttempts === undefined) {
    state.reconnectAttempts = 0;
  }

  // 最大重连次数限制
  const maxAttempts = 10;
  if (state.reconnectAttempts >= maxAttempts) {
    log("已达最大重连次数，请刷新页面", "error");
    updateWsStatus("error", "重连失败");

    const statusText = document.getElementById("statusText");
    if (statusText) {
      statusText.textContent = "连接失败，请刷新页面";
    }

    // 禁用挖矿功能
    document.getElementById("startBtn").disabled = true;
    document.getElementById("stopBtn").disabled = true;

    return;
  }

  state.reconnectAttempts++;

  // 指数退避：2^n 秒，最大 30 秒
  const delay = Math.min(1000 * Math.pow(2, state.reconnectAttempts - 1), 30000);

  log(`${delay / 1000}秒后重连 (${state.reconnectAttempts}/${maxAttempts})`, "info");

  // 清除旧的重连定时器
  if (state.reconnectTimer) {
    clearTimeout(state.reconnectTimer);
  }

  state.reconnectTimer = setTimeout(() => {
    connectWebSocket(true); // isReconnect = true
  }, delay);
}
