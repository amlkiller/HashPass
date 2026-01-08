import { getFingerprint } from "https://cdn.jsdelivr.net/npm/@thumbmarkjs/thumbmarkjs/dist/thumbmark.esm.js";

let mining = false;
let visitorId = "";
let miningWorker = null;
let ws = null;
let wsReconnectTimer = null;
let wsPingTimer = null;
let onlineCount = 0;
let miningTimer = null; // 挖矿计时器
let miningStartTime = 0; // 挖矿开始时间

// Turnstile 相关
let turnstileToken = null;
let turnstilesiteKey = null;
let turnstileWidgetId = null;

// Turnstile 管理器
const turnstileManager = {
  async init() {
    try {
      log("正在初始化 Turnstile...");

      // 1. 获取 Site Key
      const config = await fetch("/api/turnstile/config").then((r) => r.json());
      turnstilesiteKey = config.siteKey;

      if (config.testMode) {
        log("⚠️ Turnstile 测试模式已启用", "warning");
      }

      // 2. 等待 Turnstile API 加载
      await this.waitForTurnstile();

      // 3. 渲染 Widget
      log("正在渲染 Turnstile Widget...");
      turnstileWidgetId = window.turnstile.render("#turnstileWidget", {
        sitekey: turnstilesiteKey,
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

  onSuccess(token) {
    turnstileToken = token;
    log("✅ Turnstile 验证成功", "success");
    this.enableUI();
  },

  onError() {
    log("Turnstile 验证失败", "error");
    this.disableUI();
  },

  onExpired() {
    log("Turnstile Token 已过期，正在重新验证...", "warning");
    turnstileToken = null;
    this.disableUI();

    // 重置 Widget
    if (turnstileWidgetId !== null) {
      window.turnstile.reset(turnstileWidgetId);
    }
  },

  onTimeout() {
    log("Turnstile 验证超时", "error");
    this.disableUI();
  },

  async enableUI() {
    // 启用挖矿按钮
    document.getElementById("startBtn").disabled = false;
    document.getElementById("statusText").textContent = "就绪";

    // 建立 WebSocket 连接
    connectWebSocket();
  },

  disableUI() {
    // 禁用所有功能
    document.getElementById("startBtn").disabled = true;
    document.getElementById("stopBtn").disabled = true;
    document.getElementById("statusText").textContent = "等待验证";
  },
};

// 格式化时间为 HH:MM:SS
function formatTime(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(
    2,
    "0",
  )}:${String(secs).padStart(2, "0")}`;
}

// 更新挖矿时长显示
function updateMiningTime() {
  const elapsed = Math.floor((Date.now() - miningStartTime) / 1000);
  document.getElementById("miningTime").textContent = formatTime(elapsed);
}

// 启动挖矿计时器
function startMiningTimer() {
  miningStartTime = Date.now();
  document.getElementById("miningTime").textContent = "00:00:00";

  if (miningTimer) {
    clearInterval(miningTimer);
  }

  miningTimer = setInterval(updateMiningTime, 1000);
}

// 停止挖矿计时器
function stopMiningTimer() {
  if (miningTimer) {
    clearInterval(miningTimer);
    miningTimer = null;
  }
  document.getElementById("miningTime").textContent = "--:--:--";
}

// 主题管理
const themeManager = {
  init() {
    // 从 localStorage 读取保存的主题偏好，默认为 dark
    const savedTheme = localStorage.getItem("theme") || "dark";
    this.setTheme(savedTheme);

    // 监听系统主题变化
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", (e) => {
        if (localStorage.getItem("theme") === "system") {
          this.applyTheme(e.matches ? "dark" : "light");
        }
      });

    // 绑定主题切换按钮
    document.querySelectorAll(".theme-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const theme = btn.dataset.theme;
        this.setTheme(theme);
      });
    });
  },

  setTheme(theme) {
    localStorage.setItem("theme", theme);

    // 更新按钮激活状态
    document.querySelectorAll(".theme-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.theme === theme);
    });

    // 应用主题
    if (theme === "system") {
      const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      this.applyTheme(isDark ? "dark" : "light");
    } else {
      this.applyTheme(theme);
    }
  },

  applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  },
};

// 初始化
(async function init() {
  try {
    // 初始化主题
    themeManager.init();

    // 初始状态禁用所有按钮（等待 Turnstile 验证）
    document.getElementById("startBtn").disabled = true;
    document.getElementById("stopBtn").disabled = true;
    document.getElementById("statusText").textContent = "初始化中...";

    log("正在获取设备指纹...");
    const fp = await getFingerprint();
    visitorId = fp.hash || fp;
    document.getElementById("fingerprint").textContent = visitorId;
    log(`设备指纹: ${visitorId}`);

    // 初始化 Turnstile（验证成功后会自动启用 UI 和建立 WebSocket）
    await turnstileManager.init();
  } catch (error) {
    log(`初始化错误: ${error.message}`, "error");
    document.getElementById("statusText").textContent = "初始化失败";
  }
})();

// WebSocket 状态更新
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

// 开始 WebSocket 心跳
function startWsPing() {
  // 清除旧的定时器
  if (wsPingTimer) {
    clearInterval(wsPingTimer);
  }

  // 每10秒发送一次 ping
  wsPingTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send("ping");
    }
  }, 10000);
}

// 停止 WebSocket 心跳
function stopWsPing() {
  if (wsPingTimer) {
    clearInterval(wsPingTimer);
    wsPingTimer = null;
  }
}

// 发送算力到服务器
function sendHashrateToServer(rate) {
  if (ws && ws.readyState === WebSocket.OPEN && mining) {
    ws.send(JSON.stringify({
      type: 'hashrate',
      payload: {
        rate: rate,
        timestamp: Date.now() / 1000
      }
    }));
  }
}

// WebSocket 连接管理
function connectWebSocket() {
  // 检查 Turnstile Token
  if (!turnstileToken) {
    log("WebSocket: 等待 Turnstile 验证...", "warning");
    updateWsStatus("disconnected", "等待验证");
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/api/ws?token=${encodeURIComponent(turnstileToken)}`;

  // 设置连接中状态
  updateWsStatus("connecting", "连接中");
  log("🔄 正在连接 WebSocket...");

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    log("📡 WebSocket 已连接");
    updateWsStatus("connected", "已连接");

    // 清除重连定时器
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }

    // 启动心跳
    startWsPing();
    // 立即发送一次 ping 获取在线人数
    ws.send("ping");
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWebSocketMessage(data);
    } catch (error) {
      log(`WebSocket 消息解析错误: ${error.message}`, "error");
    }
  };

  ws.onerror = (error) => {
    log("WebSocket 连接错误", "error");
    updateWsStatus("error", "错误");
    stopWsPing();
  };

  ws.onclose = (event) => {
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
    wsReconnectTimer = setTimeout(() => {
      connectWebSocket();
    }, 3000);
  };
}

// 处理 WebSocket 消息
function handleWebSocketMessage(data) {
  if (data.type === "PONG") {
    // 更新在线人数
    onlineCount = data.online;
    updateWsStatus("connected", "已连接", onlineCount);
  } else if (data.type === "PUZZLE_RESET") {
    log("🔄 检测到新的 Puzzle，本轮结束！", "error");
    log(`新 Seed: ${data.seed.substring(0, 16)}...`);

    // 更新难度显示
    document.getElementById("difficulty").textContent = data.difficulty;

    // 如果正在挖矿，自动重启挖矿（继续竞争）
    if (mining) {
      log("🔄 自动重新开始挖矿，继续竞争...");
      stopMining();
      // 延迟100ms后重新开始，确保停止完成
      setTimeout(() => {
        startMining();
      }, 100);
    }
  } else if (data.type === "NETWORK_HASHRATE") {
    // 处理全网算力更新
    updateNetworkHashRate(data.total_hashrate, data.active_miners);
  }
}

async function startMining() {
  if (mining) return;

  // 检查 Turnstile Token
  if (!turnstileToken) {
    log("请先完成人机验证", "error");
    return;
  }

  mining = true;

  document.getElementById("startBtn").disabled = true;
  document.getElementById("stopBtn").disabled = false;
  document.getElementById("progress").style.display = "block";
  document.getElementById("statusText").textContent = "挖矿中...";

  // 启动计时器
  startMiningTimer();

  try {
    // 1. 获取网络特征（关键步骤）
    log("正在获取 Cloudflare Trace...");
    // 开发模式：尝试 Cloudflare，失败则使用开发接口
    let traceData;
    const cfResponse = await fetch("/cdn-cgi/trace");
    if (cfResponse.ok) {
      traceData = await cfResponse.text();
    } else {
      log("Cloudflare Trace 不可用，使用开发模式");
      traceData = await fetch("/api/dev/trace").then((r) => r.text());
    }

    // 提取并显示关键信息
    const traceLines = traceData.split("\n");
    const ipLine = traceLines.find((line) => line.startsWith("ip="));
    const ip = ipLine ? ipLine.split("=")[1] : "未知";
    log(`网络身份: ${ip}`);

    // 2. 获取当前谜题（带 Authorization Header）
    const puzzle = await fetch("/api/puzzle", {
      headers: {
        Authorization: `Bearer ${turnstileToken}`,
      },
    }).then((r) => {
      if (!r.ok) {
        throw new Error(`获取谜题失败: ${r.status} ${r.statusText}`);
      }
      return r.json();
    });

    // 更新难度显示
    document.getElementById("difficulty").textContent = puzzle.difficulty;

    log(`谜题 Seed: ${puzzle.seed.substring(0, 16)}...`);
    log(`难度: ${puzzle.difficulty} (前${puzzle.difficulty}位为0)`);
    log(`内存需求: ${puzzle.memory_cost / 1024}MB`);
    log(`Argon2 参数: 时间=${puzzle.time_cost}, 并行度=${puzzle.parallelism}`);

    // 3. 创建并启动 Worker (使用 module 类型支持 ESM)
    miningWorker = new Worker("/static/worker.js", { type: "module" });

    // 4. 设置 Worker 消息监听
    miningWorker.onmessage = async function (e) {
      const { type, message, nonce, hash, elapsed, hashRate } = e.data;

      switch (type) {
        case "LOG":
          log(message);
          break;

        case "PROGRESS":
          log(`尝试 #${nonce}, 哈希: ${hash}... (${elapsed}s)`);
          break;

        case "HASH_RATE":
          // 更新哈希速率显示
          updateHashRate(hashRate);
          // 发送算力到服务器
          sendHashrateToServer(parseFloat(hashRate));
          break;

        case "SOLUTION_FOUND":
          log(`✅ 找到解! Nonce: ${nonce}, Hash: ${hash}`, "success");
          log(`总耗时: ${elapsed}秒`);
          // 立即停止挖矿，防止WebSocket消息触发重启
          stopMining();
          await submitSolution({ nonce, hash }, puzzle.seed, traceData);
          break;

        case "ERROR":
          log(`Worker 错误: ${message}`, "error");
          stopMining();
          break;

        case "STOPPED":
          log("挖矿已停止");
          break;
      }
    };

    miningWorker.onerror = function (error) {
      log(`Worker 错误: ${error.message}`, "error");
      stopMining();
    };

    // 5. 发送挖矿任务给 Worker
    miningWorker.postMessage({
      type: "START_MINING",
      data: {
        seed: puzzle.seed,
        visitorId: visitorId,
        traceData: traceData,
        difficulty: puzzle.difficulty,
        memoryCost: puzzle.memory_cost,
        timeCost: puzzle.time_cost,
        parallelism: puzzle.parallelism,
      },
    });

    // 6. 通知服务器开始挖矿（用于计时）
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "mining_start" }));
      log("⏱️ 已通知服务器开始计时");
    }
  } catch (error) {
    log(`错误: ${error.message}`, "error");
    stopMining();
  }
}

async function submitSolution(result, submittedSeed, traceData) {
  log("正在提交解...");

  const response = await fetch("/api/verify", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${turnstileToken}`,
    },
    body: JSON.stringify({
      visitorId: visitorId,
      nonce: result.nonce,
      submittedSeed: submittedSeed,
      traceData: traceData,
      hash: result.hash,
    }),
  });

  if (response.ok) {
    const data = await response.json();
    log(`🎉 获胜! 邀请码: ${data.invite_code}`, "success");
    document.getElementById("result").style.display = "block";
    document.getElementById("inviteCode").value = data.invite_code;
  } else {
    const error = await response.json();
    log(`提交失败: ${error.detail}`, "error");
  }
}

function stopMining() {
  mining = false;

  // 停止计时器
  stopMiningTimer();

  // 重置哈希速率显示
  resetHashRate();

  // 通知服务器停止挖矿（用于计时）
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "mining_stop" }));
  }

  // 通知 Worker 停止
  if (miningWorker) {
    miningWorker.postMessage({ type: "STOP_MINING" });
    miningWorker.terminate(); // 终止 Worker
    miningWorker = null;
  }

  document.getElementById("startBtn").disabled = false;
  document.getElementById("stopBtn").disabled = true;
  document.getElementById("progress").style.display = "none";
  document.getElementById("statusText").textContent = "已停止";
}

function copyCode() {
  const input = document.getElementById("inviteCode");
  input.select();
  document.execCommand("copy");
  log("邀请码已复制到剪贴板");
}

function log(message, type = "info") {
  const logBox = document.getElementById("logBox");
  const time = new Date().toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  // 智能识别日志类型
  if (type === "info") {
    if (
      message.includes("错误") ||
      message.includes("失败") ||
      message.includes("Error")
    ) {
      type = "error";
    } else if (
      message.includes("成功") ||
      message.includes("获胜") ||
      message.includes("✅") ||
      message.includes("🎉")
    ) {
      type = "success";
    } else if (message.includes("警告") || message.includes("⚠️")) {
      type = "warning";
    }
  }

  // 图标映射
  const icons = {
    info: "ℹ",
    success: "✓",
    error: "✕",
    warning: "⚠",
  };

  // 创建日志项
  const logEntry = document.createElement("div");
  logEntry.className = `log-entry log-${type}`;

  // 处理消息内容
  let processedMessage = escapeHtml(message);

  // 智能高亮：仅高亮特定模式
  // 1. 高亮 "标签: 值" 格式的哈希值
  processedMessage = processedMessage.replace(
    /(Seed|Hash|哈希|Nonce):\s*([a-f0-9]{16,})/gi,
    '$1: <span class="log-highlight">$2</span>',
  );

  // 2. 高亮 "标签: 数字" 或 "标签: 数字单位" 格式（如：难度: 1、内存: 64MB、总耗时: 5秒）
  processedMessage = processedMessage.replace(
    /(难度|内存需求|总耗时|耗时):\s*(\d+\.?\d*)(MB|秒|s)?/g,
    '$1: <span class="log-highlight">$2$3</span>',
  );

  // 3. 高亮设备指纹（8位十六进制且前后有明确边界）
  processedMessage = processedMessage.replace(
    /\b([a-f0-9]{8})\b/g,
    '<span class="log-highlight">$1</span>',
  );

  logEntry.innerHTML = `
    <div class="log-icon">${icons[type]}</div>
    <div class="log-content">
      <div class="log-time">${time}</div>
      <div class="log-message">${processedMessage}</div>
    </div>
  `;

  logBox.appendChild(logEntry);
  logBox.scrollTop = logBox.scrollHeight;
}

// HTML 转义函数，防止 XSS
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// 更新哈希速率显示
function updateHashRate(hashRate) {
  const hashRateValue = document.getElementById("hashRateValue");
  const hashRateDisplay = document.getElementById("hashRateDisplay");

  hashRateValue.textContent = hashRate;
  hashRateValue.classList.remove("inactive");
  hashRateDisplay.classList.add("active");
}

// 重置哈希速率显示
function resetHashRate() {
  const hashRateValue = document.getElementById("hashRateValue");
  const hashRateDisplay = document.getElementById("hashRateDisplay");

  hashRateValue.textContent = "--";
  hashRateValue.classList.add("inactive");
  hashRateDisplay.classList.remove("active");
}

// 更新全网算力显示
function updateNetworkHashRate(totalHashrate, activeMiners) {
  const networkHashRateValue = document.getElementById("networkHashRateValue");
  const networkHashRateDisplay = document.getElementById("networkHashRateDisplay");
  const networkMiners = document.getElementById("networkMiners");

  // 格式化算力值（自动单位转换）
  const formattedRate = formatHashRate(totalHashrate);

  networkHashRateValue.textContent = formattedRate.value;
  networkHashRateValue.classList.remove("inactive");
  networkHashRateDisplay.classList.add("active");
  networkMiners.textContent = `${activeMiners}人在线`;
}

// 格式化算力值
function formatHashRate(hashrate) {
  if (hashrate >= 1000000) {
    return { value: (hashrate / 1000000).toFixed(2), unit: "MH/s" };
  } else if (hashrate >= 1000) {
    return { value: (hashrate / 1000).toFixed(2), unit: "KH/s" };
  } else {
    return { value: hashrate.toFixed(2), unit: "H/s" };
  }
}

// 重置全网算力显示
function resetNetworkHashRate() {
  const networkHashRateValue = document.getElementById("networkHashRateValue");
  const networkHashRateDisplay = document.getElementById("networkHashRateDisplay");
  const networkMiners = document.getElementById("networkMiners");

  networkHashRateValue.textContent = "--";
  networkHashRateValue.classList.add("inactive");
  networkHashRateDisplay.classList.remove("active");
  networkMiners.textContent = "0人在线";
}

// 导出全局函数
window.startMining = startMining;
window.stopMining = stopMining;
window.copyCode = copyCode;
