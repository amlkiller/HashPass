/**
 * 工具函数模块
 * 提供时间格式化、HTML转义等通用工具函数
 */

/**
 * 格式化时间为 HH:MM:SS
 * @param {number} seconds - 秒数
 * @returns {string} 格式化后的时间字符串
 */
export function formatTime(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(
    2,
    "0",
  )}:${String(secs).padStart(2, "0")}`;
}

/**
 * HTML 转义函数，防止 XSS
 * @param {string} text - 需要转义的文本
 * @returns {string} 转义后的文本
 */
export function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/**
 * 格式化算力值，自动选择单位
 * @param {number} hashrate - 算力值（H/s）
 * @returns {{value: string, unit: string}} 格式化后的值和单位
 */
export function formatHashRate(hashrate) {
  if (hashrate >= 1000000) {
    return { value: (hashrate / 1000000).toFixed(2), unit: "MH/s" };
  } else if (hashrate >= 1000) {
    return { value: (hashrate / 1000).toFixed(2), unit: "KH/s" };
  } else {
    return { value: hashrate.toFixed(2), unit: "H/s" };
  }
}
