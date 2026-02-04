/**
 * 挖矿逻辑模块
 * 管理挖矿流程、Worker通信、计时器等核心功能
 */

import { state } from "./state.js";
import { log } from "./logger.js";
import { formatTime } from "./utils.js";
import { updateHashRate, resetHashRate } from "./hashrate.js";
import { sendHashrateToServer, notifyMiningStart, notifyMiningStop } from "./websocket.js";

/**
 * 更新挖矿时长显示
 */
function updateMiningTime() {
  const elapsed = Math.floor((Date.now() - state.miningStartTime) / 1000);
  document.getElementById("miningTime").textContent = formatTime(elapsed);
}

/**
 * 启动挖矿计时器
 */
function startMiningTimer() {
  state.miningStartTime = Date.now();
  document.getElementById("miningTime").textContent = "00:00:00";

  if (state.miningTimer) {
    clearInterval(state.miningTimer);
  }

  state.miningTimer = setInterval(updateMiningTime, 1000);
}

/**
 * 停止挖矿计时器
 */
function stopMiningTimer() {
  if (state.miningTimer) {
    clearInterval(state.miningTimer);
    state.miningTimer = null;
  }
  document.getElementById("miningTime").textContent = "--:--:--";
}

/**
 * 提交解决方案
 * @param {Object} result - 解决方案 {nonce, hash}
 * @param {string} submittedSeed - 提交的种子
 * @param {string} traceData - Cloudflare Trace 数据
 */
async function submitSolution(result, submittedSeed, traceData) {
  log("正在提交解决方案...");

  const response = await fetch("/api/verify", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${state.sessionToken}`  // ← 新增
    },
    body: JSON.stringify({
      visitorId: state.visitorId,
      nonce: result.nonce,
      submittedSeed: submittedSeed,
      traceData: traceData,
      hash: result.hash,
    }),
  });

  if (response.ok) {
    const data = await response.json();
    log(`🎉 获胜！邀请码: ${data.invite_code}`, "success");
    document.getElementById("result").classList.remove("hidden");
    document.getElementById("inviteCode").value = data.invite_code;
  } else if (response.status === 401) {
    // 处理 Session Token 失效
    log("会话已过期，请刷新页面", "error");
    alert("会话已过期，请刷新页面");
    stopMining();
  } else {
    const error = await response.json();
    log(`提交失败: ${error.detail}`, "error");
  }
}

/**
 * 开始挖矿
 */
export async function startMining() {
  if (state.mining) return;

  // 检查 Session Token（真正用于 API 请求的凭证）
  if (!state.sessionToken) {
    log("请先完成人机验证", "error");
    return;
  }

  state.mining = true;

  document.getElementById("startBtn").disabled = true;
  document.getElementById("stopBtn").disabled = false;
  document.getElementById("progress").classList.remove("hidden");
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

    // 2. 获取当前谜题（需要 Session Token）
    const puzzleResponse = await fetch("/api/puzzle", {
      headers: {
        "Authorization": `Bearer ${state.sessionToken}`
      }
    });

    // 处理 401 错误
    if (puzzleResponse.status === 401) {
      log("会话已过期，请刷新页面", "error");
      alert("会话已过期，请刷新页面");
      stopMining();
      return;
    }

    if (!puzzleResponse.ok) {
      throw new Error(`获取谜题失败: ${puzzleResponse.status} ${puzzleResponse.statusText}`);
    }

    const puzzle = await puzzleResponse.json();

    // 更新难度显示
    document.getElementById("difficulty").textContent = puzzle.difficulty;

    log(`谜题种子: ${puzzle.seed.substring(0, 16)}...`);
    log(`难度: ${puzzle.difficulty} (${puzzle.difficulty} 个前导零)`);
    log(`内存: ${puzzle.memory_cost / 1024}MB`);
    log(`Argon2: 时间=${puzzle.time_cost}, 并行度=${puzzle.parallelism}`);

    // 3. 创建并启动 Worker (使用 module 类型支持 ESM)
    state.miningWorker = new Worker("/static/worker.js", { type: "module" });

    // 4. 设置 Worker 消息监听
    state.miningWorker.onmessage = async function (e) {
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
          log(`找到解决方案！Nonce: ${nonce}, 哈希: ${hash}`, "success");
          log(`总耗时: ${elapsed}s`);
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

    state.miningWorker.onerror = function (error) {
      log(`Worker 错误: ${error.message}`, "error");
      stopMining();
    };

    // 5. 发送挖矿任务给 Worker
    state.miningWorker.postMessage({
      type: "START_MINING",
      data: {
        seed: puzzle.seed,
        visitorId: state.visitorId,
        traceData: traceData,
        difficulty: puzzle.difficulty,
        memoryCost: puzzle.memory_cost,
        timeCost: puzzle.time_cost,
        parallelism: puzzle.parallelism,
      },
    });

    // 6. 通知服务器开始挖矿（用于计时）
    notifyMiningStart();
  } catch (error) {
    log(`错误: ${error.message}`, "error");
    stopMining();
  }
}

/**
 * 停止挖矿
 */
export function stopMining() {
  state.mining = false;

  // 停止计时器
  stopMiningTimer();

  // 重置哈希速率显示
  resetHashRate();

  // 通知服务器停止挖矿（用于计时）
  notifyMiningStop();

  // 通知 Worker 停止
  if (state.miningWorker) {
    state.miningWorker.postMessage({ type: "STOP_MINING" });
    state.miningWorker.terminate(); // 终止 Worker
    state.miningWorker = null;
  }

  document.getElementById("startBtn").disabled = false;
  document.getElementById("stopBtn").disabled = true;
  document.getElementById("progress").classList.add("hidden");
  document.getElementById("statusText").textContent = "已停止";
}

/**
 * 复制邀请码
 */
export function copyCode() {
  const input = document.getElementById("inviteCode");
  input.select();
  document.execCommand("copy");
  log("邀请码已复制到剪贴板");
}
