/**
 * 日志系统模块
 * 提供统一的日志输出功能，支持不同类型的日志样式
 */

import { escapeHtml } from "./utils.js";

/**
 * 输出日志到日志面板
 * @param {string} message - 日志消息
 * @param {string} type - 日志类型 (info, success, error, warning)
 */
export function log(message, type = "info") {
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
