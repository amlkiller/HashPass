/**
 * 算力显示管理模块
 * 管理本地算力和全网算力的显示更新
 */

import { formatHashRate } from "./utils.js";

/**
 * 更新本地哈希速率显示
 * @param {string} hashRate - 哈希速率字符串
 */
export function updateHashRate(hashRate) {
  const hashRateValue = document.getElementById("hashRateValue");
  const hashRateDisplay = document.getElementById("hashRateDisplay");

  hashRateValue.textContent = hashRate;
  hashRateValue.classList.remove("inactive");
  hashRateDisplay.classList.add("active");
}

/**
 * 重置本地哈希速率显示
 */
export function resetHashRate() {
  const hashRateValue = document.getElementById("hashRateValue");
  const hashRateDisplay = document.getElementById("hashRateDisplay");

  hashRateValue.textContent = "--";
  hashRateValue.classList.add("inactive");
  hashRateDisplay.classList.remove("active");
}

/**
 * 更新全网算力显示
 * @param {number} totalHashrate - 全网总算力
 * @param {number} activeMiners - 活跃矿工数量
 */
export function updateNetworkHashRate(totalHashrate, activeMiners) {
  const networkHashRateValue = document.getElementById("networkHashRateValue");
  const networkHashRateDisplay = document.getElementById("networkHashRateDisplay");
  const networkMiners = document.getElementById("networkMiners");

  // 格式化算力值（自动单位转换）
  const formattedRate = formatHashRate(totalHashrate);

  networkHashRateValue.textContent = formattedRate.value;
  networkHashRateValue.classList.remove("inactive");
  networkHashRateDisplay.classList.add("active");
  networkMiners.textContent = `${activeMiners} 人在线`;
}

/**
 * 重置全网算力显示
 */
export function resetNetworkHashRate() {
  const networkHashRateValue = document.getElementById("networkHashRateValue");
  const networkHashRateDisplay = document.getElementById("networkHashRateDisplay");
  const networkMiners = document.getElementById("networkMiners");

  networkHashRateValue.textContent = "--";
  networkHashRateValue.classList.add("inactive");
  networkHashRateDisplay.classList.remove("active");
  networkMiners.textContent = "0 人在线";
}
