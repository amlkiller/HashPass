/**
 * 挖矿逻辑模块
 * 管理挖矿流程、Worker通信、计时器等核心功能
 */

import { state } from "./state.js";
import { log } from "./logger.js";
import { formatTime } from "./utils.js";
import { updateHashRate, resetHashRate } from "./hashrate.js";
import { sendHashrateToServer, notifyMiningStart, notifyMiningStop } from "./websocket.js";

// 模块级变量：要求难度 & 最佳难度刷新定时器
let _requiredDifficulty = null;
let _bestDifficultyTimer = null;

/**
 * 格式化解题时间
 * @param {number} seconds - 秒数
 * @returns {string} 格式化后的字符串
 */
function formatSolveTime(seconds) {
  if (seconds == null) return "--";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m${s}s`;
}

/**
 * 启动谜题持续时间计时器
 * @param {number} serverStartTime - 服务器端谜题开始时间（Unix秒）
 */
export function startPuzzleDurationTimer(serverStartTime) {
  state.puzzleStartTime = serverStartTime;

  // 清除旧 interval
  if (state.puzzleDurationTimer) {
    clearInterval(state.puzzleDurationTimer);
  }

  // 激活动画样式
  const display = document.getElementById("puzzleStatsDisplay");
  const value = document.getElementById("puzzleDuration");
  if (display) display.classList.add("active");
  if (value) value.classList.remove("inactive");

  // 立即更新一次
  updatePuzzleDuration();
  state.puzzleDurationTimer = setInterval(updatePuzzleDuration, 1000);
}

/**
 * 更新谜题持续时间显示
 */
function updatePuzzleDuration() {
  if (!state.puzzleStartTime) return;

  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - state.puzzleStartTime));
  const el = document.getElementById("puzzleDuration");
  if (!el) return;

  if (elapsed >= 3600) {
    const h = Math.floor(elapsed / 3600);
    const m = Math.floor((elapsed % 3600) / 60);
    const s = elapsed % 60;
    el.textContent = `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  } else {
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    el.textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
}

/**
 * 更新解题时间统计显示
 * @param {number|null} last - 上次解题耗时
 * @param {number|null} avg - 平均解题耗时
 */
export function updateSolveTimeStats(last, avg) {
  state.lastSolveTime = last;
  state.averageSolveTime = avg;

  const el = document.getElementById("solveTimeStats");
  if (!el) return;

  el.textContent = `上次 ${formatSolveTime(last)} / 平均 ${formatSolveTime(avg)}`;
}

/**
 * 更新难度显示（要求难度 / 最佳难度）
 */
export function updateDifficultyDisplay() {
  const req = _requiredDifficulty != null ? _requiredDifficulty : "-";
  const best = state.bestLeadingZeros > 0 ? state.bestLeadingZeros : "-";
  const el = document.getElementById("difficulty");
  if (el) el.textContent = `${req} / ${best}`;
}

/**
 * 设置要求难度并立即刷新显示
 * @param {number|null} difficulty - 要求难度
 */
export function setRequiredDifficulty(difficulty) {
  _requiredDifficulty = difficulty;
  updateDifficultyDisplay();
}

/**
 * 更新挖矿时长显示
 */
function updateMiningTime() {
  const elapsed = Math.floor((state.miningElapsed + Date.now() - state.miningStartTime) / 1000);
  document.getElementById("miningTime").textContent = formatTime(elapsed);
}

/**
 * 启动挖矿计时器（累计计时，暂停后继续）
 */
function startMiningTimer() {
  state.miningStartTime = Date.now();

  if (state.miningTimer) {
    clearInterval(state.miningTimer);
  }

  // 立即更新一次显示
  updateMiningTime();
  state.miningTimer = setInterval(updateMiningTime, 1000);
}

/**
 * 停止挖矿计时器（暂停，保留累计时长）
 */
function stopMiningTimer() {
  if (state.miningTimer) {
    // 累加本次挖矿时长
    state.miningElapsed += Date.now() - state.miningStartTime;
    clearInterval(state.miningTimer);
    state.miningTimer = null;
  }
}

/**
 * 聚合所有 Worker 算力并更新 UI / 上报服务器
 */
function aggregateAndReportHashrate() {
  const rates = Object.values(state.workerHashrates);
  if (rates.length === 0) return;

  const totalRate = rates.reduce((sum, r) => sum + r, 0);
  const totalRateStr = totalRate.toFixed(2);

  updateHashRate(totalRateStr);
  sendHashrateToServer(totalRate);
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
      "Authorization": `Bearer ${state.sessionToken}`
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
    log(`🎉 获胜！兑换码: ${data.invite_code}`, "success");
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

  // 重置超时奖励跟踪
  state.bestHash = null;
  state.bestNonce = -1;
  state.bestLeadingZeros = 0;

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
    state.traceData = traceData;
    const traceLines = traceData.split("\n");
    const ipLine = traceLines.find((line) => line.startsWith("ip="));
    const ip = ipLine ? ipLine.slice(3).trim() : "未知";
    log(`网络身份: ${ip}`);

    // 2. 获取当前谜题（需要 Session Token）
    const puzzleResponse = await fetch("/api/puzzle", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.sessionToken}`
      },
      body: JSON.stringify({ visitorId: state.visitorId })
    });

    // 处理 401 错误
    if (puzzleResponse.status === 401) {
      log("会话已过期，请刷新页面", "error");
      alert("会话已过期，请刷新页面");
      stopMining();
      return;
    }

    if (puzzleResponse.status === 403) {
      const error = await puzzleResponse.json();
      log(`访问被拒绝: ${error.detail}`, "error");
      stopMining();
      return;
    }

    if (!puzzleResponse.ok) {
      throw new Error(`获取谜题失败: ${puzzleResponse.status} ${puzzleResponse.statusText}`);
    }

    const puzzle = await puzzleResponse.json();
    state.currentSeed = puzzle.seed;
    state.timedOutSeed = null;
    const workerCount = puzzle.worker_count || 1;

    // 更新难度显示，启动 10s 定时刷新最佳难度
    setRequiredDifficulty(puzzle.difficulty);
    if (_bestDifficultyTimer) clearInterval(_bestDifficultyTimer);
    _bestDifficultyTimer = setInterval(updateDifficultyDisplay, 10000);

    // 初始化谜题统计
    if (puzzle.puzzle_start_time) startPuzzleDurationTimer(puzzle.puzzle_start_time);
    updateSolveTimeStats(puzzle.last_solve_time ?? null, puzzle.average_solve_time ?? null);

    log(`谜题种子: ${puzzle.seed.substring(0, 16)}...`);
    log(`难度: ${puzzle.difficulty} (${puzzle.difficulty} 位前导零比特)`);
    log(`内存: ${puzzle.memory_cost / 1024}MB`);
    log(`Argon2: 时间=${puzzle.time_cost}, 并行度=${puzzle.parallelism}`);
    if (workerCount > 1) {
      log(`并行 Worker: ${workerCount} 个`);
    }

    // 3. 初始化 Worker 算力跟踪
    state.workerHashrates = {};

    // 4. 创建并启动多个 Worker
    for (let i = 0; i < workerCount; i++) {
      const worker = new Worker("/static/worker.js", { type: "module" });

      // 设置 Worker 消息监听
      worker.onmessage = async function (e) {
        const { type, message, nonce, hash, elapsed, hashRate, workerId } = e.data;

        switch (type) {
          case "LOG":
            // 仅 Worker 0 输出日志（避免 N 倍刷屏）
            if (workerId === 0) {
              log(message);
            }
            break;

          case "PROGRESS":
            // 仅 Worker 0 输出进度
            if (workerId === 0) {
              log(`尝试 #${nonce}, 哈希: ${hash}... (${elapsed}s)`);
            }
            break;

          case "HASH_RATE":
            // 存入各 Worker 算力，聚合后上报
            state.workerHashrates[workerId] = parseFloat(hashRate);
            aggregateAndReportHashrate();
            break;

          case "SOLUTION_FOUND":
            log(`找到解决方案！Nonce: ${nonce}, 哈希: ${hash}`, "success");
            log(`总耗时: ${elapsed}s`);
            // 立即停止挖矿，防止WebSocket消息触发重启
            stopMining();
            await submitSolution({ nonce, hash }, puzzle.seed, traceData);
            break;

          case "ERROR":
            log(`Worker ${workerId} 错误: ${message}`, "error");
            stopMining();
            break;

          case "BEST_HASH_UPDATE":
            if (
              e.data.bestLeadingZeros > state.bestLeadingZeros ||
              (e.data.bestLeadingZeros === state.bestLeadingZeros &&
                (state.bestNonce === -1 || e.data.bestNonce < state.bestNonce))
            ) {
              state.bestLeadingZeros = e.data.bestLeadingZeros;
              state.bestHash = e.data.bestHash;
              state.bestNonce = e.data.bestNonce;
            }
            break;

          case "STOPPED":
            // 静默处理
            break;
        }
      };

      worker.onerror = function (error) {
        log(`Worker ${i} 错误: ${error.message}`, "error");
        stopMining();
      };

      // 发送挖矿任务给 Worker
      worker.postMessage({
        type: "START_MINING",
        data: {
          seed: puzzle.seed,
          visitorId: state.visitorId,
          ip: ip,
          difficulty: puzzle.difficulty,
          memoryCost: puzzle.memory_cost,
          timeCost: puzzle.time_cost,
          parallelism: puzzle.parallelism,
          workerId: i,
          workerCount: workerCount,
        },
      });

      state.miningWorkers.push(worker);
    }

    // 5. 通知服务器开始挖矿（用于计时）
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

  // 停止最佳难度刷新定时器
  if (_bestDifficultyTimer) {
    clearInterval(_bestDifficultyTimer);
    _bestDifficultyTimer = null;
  }

  // 重置哈希速率显示
  resetHashRate();

  // 通知服务器停止挖矿（用于计时）
  notifyMiningStop();

  // 终止所有 Worker
  for (const worker of state.miningWorkers) {
    worker.postMessage({ type: "STOP_MINING" });
    worker.terminate();
  }
  state.miningWorkers = [];
  state.workerHashrates = {};

  document.getElementById("startBtn").disabled = false;
  document.getElementById("stopBtn").disabled = true;
  document.getElementById("progress").classList.add("hidden");
  document.getElementById("statusText").textContent = "已停止";
}

/**
 * 复制兑换码
 */
export async function copyCode() {
  const input = document.getElementById("inviteCode");
  try {
    await navigator.clipboard.writeText(input.value);
    log("兑换码已复制到剪贴板");
  } catch {
    input.select();
    document.execCommand("copy");
    log("兑换码已复制到剪贴板");
  }
}

/**
 * 超时奖励：提交当前最优哈希
 * @param {string | null} timedOutSeed - 超时时的种子
 */
export async function submitBestHash(timedOutSeed = null) {
  if (!state.bestHash || state.bestNonce < 0 || state.bestLeadingZeros < 1) {
    log("超时: 无有效哈希可提交", "warning");
    return;
  }
  if (!state.traceData) {
    log("超时: 无 TraceData，跳过提交", "warning");
    return;
  }

  log(`超时: 正在提交最优哈希 (${state.bestLeadingZeros} 前导零, nonce=${state.bestNonce})...`);

  try {
    const submittedSeed = timedOutSeed || state.timedOutSeed || state.currentSeed;
    const response = await fetch("/api/submit", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${state.sessionToken}`,
      },
      body: JSON.stringify({
        visitorId: state.visitorId,
        nonce: state.bestNonce,
        submittedSeed: submittedSeed,
        traceData: state.traceData,
        hash: state.bestHash,
        leadingZeros: state.bestLeadingZeros,
      }),
    });

    if (response.ok) {
      const data = await response.json();
      log(`超时提交成功 (${data.status})`, "info");
    } else if (response.status === 409) {
      log("超时提交: 窗口已关闭或种子不匹配", "warning");
    } else {
      const err = await response.json().catch(() => ({}));
      log(`超时提交失败: ${err.detail || response.status}`, "error");
    }
  } catch (e) {
    log(`超时提交网络错误: ${e.message}`, "error");
  }
}
