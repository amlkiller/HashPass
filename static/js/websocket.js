/**
 * WebSocket 连接和消息处理模块
 * 管理实时通信、心跳、消息分发、自动重连等功能
 */

import { state } from "./state.js";
import { log } from "./logger.js";
import { updateNetworkHashRate, resetNetworkHashRate } from "./hashrate.js";

// 缓存 mining.js 动态导入结果，避免重复加载路径查找
let _miningModule = null;
async function getMining() {
  if (!_miningModule) {
    _miningModule = await import("./mining.js");
  }
  return _miningModule;
}

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

    // 初始化谜题统计（无需先点开始挖矿即可看到数据）
    fetch("/api/puzzle", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${data.token}`
      },
      body: JSON.stringify({ visitorId: state.visitorId })
    })
      .then(r => r.ok ? r.json() : null)
      .then(puzzle => {
        if (!puzzle) return;
        getMining().then(({ setRequiredDifficulty, startPuzzleDurationTimer, updateSolveTimeStats }) => {
          setRequiredDifficulty(puzzle.difficulty);
          if (puzzle.puzzle_start_time) startPuzzleDurationTimer(puzzle.puzzle_start_time);
          updateSolveTimeStats(puzzle.last_solve_time ?? null, puzzle.average_solve_time ?? null);
        });
      }).catch(() => {});
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

    // 更新谜题统计
    if (data.solve_time != null) {
      log(`上轮用时: ${data.solve_time}s`);
    }
    state.bestLeadingZeros = 0;
    getMining().then(({ setRequiredDifficulty, startPuzzleDurationTimer, updateSolveTimeStats }) => {
      setRequiredDifficulty(data.difficulty);
      updateSolveTimeStats(data.solve_time ?? null, data.average_solve_time ?? null);
      if (data.puzzle_start_time) startPuzzleDurationTimer(data.puzzle_start_time);
    });

    // 如果正在挖矿，自动重启挖矿（继续竞争）
    if (data.is_timeout && state.mining) {
      log("谜题超时！正在提交最优哈希...", "warning");
      getMining().then(async ({ stopMining, startMining, submitBestHash }) => {
        stopMining();
        await submitBestHash();
        setTimeout(() => startMining(), 100);
      });
    } else if (state.mining) {
      log("正在自动重启挖矿...");
      // 动态导入 mining.js 以避免循环依赖
      getMining().then(({ stopMining, startMining }) => {
        stopMining();
        // 延迟100ms后重新开始，确保停止完成
        setTimeout(() => {
          startMining();
        }, 100);
      });
    }
  } else if (data.type === "TIMEOUT_INVITE_CODE") {
    const code = data.invite_code;
    log(`超时奖励邀请码: ${code}`, "success");
    const resultEl = document.getElementById("result");
    const codeEl = document.getElementById("inviteCode");
    if (resultEl) resultEl.classList.remove("hidden");
    if (codeEl) codeEl.value = code;
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

    // 重连成功后，如果挖矿仍在进行，重新通知服务器
    if (isReconnect && state.mining) {
      log("重连成功，恢复挖矿状态");
      notifyMiningStart();
    }
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

    // 检查是否是 Token 验证失败（1008 = Policy Violation）
    if (event.code === 1008) {
      log("会话已过期，请刷新页面", "error");
      updateWsStatus("error", "会话过期");

      const statusText = document.getElementById("statusText");
      if (statusText) {
        statusText.textContent = "会话过期，请刷新页面";
      }

      // 会话过期，立即停止挖矿并禁用UI
      if (state.mining) {
        getMining().then(({ stopMining }) => {
          stopMining();
          log("会话过期，挖矿已自动停止", "warning");
        });
      }

      document.getElementById("startBtn").disabled = true;
      document.getElementById("stopBtn").disabled = true;

      return; // 不再尝试自动重连
    }

    // 非致命断开：尝试重连，挖矿继续（Worker 不依赖 WebSocket）
    if (state.mining) {
      log("WebSocket 断开，正在尝试重连（挖矿继续）...", "warning");
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

    // 无令牌，停止挖矿并禁用UI
    if (state.mining) {
      getMining().then(({ stopMining }) => {
        stopMining();
        log("无有效令牌，挖矿已自动停止", "warning");
      });
    }

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

    // 重连全部失败，停止挖矿并禁用UI
    if (state.mining) {
      getMining().then(({ stopMining }) => {
        stopMining();
        log("重连失败，挖矿已自动停止", "warning");
      });
    }

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
