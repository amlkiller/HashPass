/**
 * 参数调整面板
 */
import { api } from "./api.js";
import { showToast } from "../app.js";

export function initParams() {
  // 加载当前状态填充表单
  loadCurrentParams();
}

async function loadCurrentParams() {
  try {
    const status = await api.getStatus();
    setVal("param-difficulty", status.difficulty);
    setVal("param-min-difficulty", status.min_difficulty);
    setVal("param-max-difficulty", status.max_difficulty);
    setVal("param-target-min", status.target_time_min);
    setVal("param-target-max", status.target_time_max);
    setVal("param-time-cost", status.argon2_time_cost);
    setVal("param-memory-cost", status.argon2_memory_cost);
    setVal("param-parallelism", status.argon2_parallelism);
    setVal("param-worker-count", status.worker_count);
  } catch (_) {}
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function getNum(id) {
  const el = document.getElementById(id);
  return el ? parseInt(el.value, 10) : NaN;
}

// Expose to global for onclick handlers
window.applyDifficulty = async function () {
  try {
    const data = {};
    const d = getNum("param-difficulty");
    const min = getNum("param-min-difficulty");
    const max = getNum("param-max-difficulty");
    if (!isNaN(d)) data.difficulty = d;
    if (!isNaN(min)) data.min_difficulty = min;
    if (!isNaN(max)) data.max_difficulty = max;
    const res = await api.updateDifficulty(data);
    if (res.error) { showToast(res.error, "error"); return; }
    showToast(`Difficulty: ${res.difficulty} (${res.min_difficulty}-${res.max_difficulty})`, "success");
    loadCurrentParams();
  } catch (e) { showToast("Failed: " + e.message, "error"); }
};

window.applyTargetTime = async function () {
  try {
    const data = {};
    const min = getNum("param-target-min");
    const max = getNum("param-target-max");
    if (!isNaN(min)) data.target_time_min = min;
    if (!isNaN(max)) data.target_time_max = max;
    const res = await api.updateTargetTime(data);
    if (res.error) { showToast(res.error, "error"); return; }
    showToast(`Target time: ${res.target_time_min}-${res.target_time_max}s`, "success");
  } catch (e) { showToast("Failed: " + e.message, "error"); }
};

window.applyArgon2 = async function () {
  try {
    const data = {};
    const tc = getNum("param-time-cost");
    const mc = getNum("param-memory-cost");
    const p = getNum("param-parallelism");
    if (!isNaN(tc)) data.time_cost = tc;
    if (!isNaN(mc)) data.memory_cost = mc;
    if (!isNaN(p)) data.parallelism = p;
    const res = await api.updateArgon2(data);
    if (res.error) { showToast(res.error, "error"); return; }
    showToast(`Argon2: t=${res.time_cost} m=${res.memory_cost}KB p=${res.parallelism}`, "success");
  } catch (e) { showToast("Failed: " + e.message, "error"); }
};

window.applyWorkerCount = async function () {
  try {
    const wc = getNum("param-worker-count");
    if (isNaN(wc)) return;
    const res = await api.updateWorkerCount({ worker_count: wc });
    if (res.error) { showToast(res.error, "error"); return; }
    showToast(`Worker count: ${res.worker_count}`, "success");
  } catch (e) { showToast("Failed: " + e.message, "error"); }
};
