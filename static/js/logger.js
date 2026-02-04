/**
 * 日志系统模块
 * 提供统一的日志输出功能，支持不同类型的日志样式
 */

import { escapeHtml } from "./utils.js";

// 日志配置
const MAX_LOG_ENTRIES = 200; // 最大日志条目数，超过后自动删除旧日志

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
      message.includes("Error") ||
      message.includes("error") ||
      message.includes("failed") ||
      message.includes("Failed")
    ) {
      type = "error";
    } else if (
      message.includes("成功") ||
      message.includes("获胜") ||
      message.includes("✅") ||
      message.includes("🎉") ||
      message.includes("Success") ||
      message.includes("success") ||
      message.includes("Win") ||
      message.includes("verified") ||
      message.includes("connected") ||
      message.includes("found")
    ) {
      type = "success";
    } else if (message.includes("警告") || message.includes("⚠️") || message.includes("warning") || message.includes("Warning")) {
      type = "warning";
    }
  }

  // 图标映射 + 颜色类
  const iconConfig = {
    info: { icon: "ℹ", colorClass: "text-blue-500" },
    success: { icon: "✓", colorClass: "text-emerald-500" },
    error: { icon: "✕", colorClass: "text-red-500" },
    warning: { icon: "⚠", colorClass: "text-amber-500" },
  };

  // 创建日志项
  const logEntry = document.createElement("div");

  // Tailwind base classes for log entry
  const baseClasses = "log-entry flex items-start gap-2 sm:gap-3 py-2 sm:py-3 px-3 sm:px-4 mb-1.5 sm:mb-2 rounded-md border-l-[3px] bg-[var(--bg-tertiary)] animate-log-fade-in transition-all duration-200 hover:bg-[var(--bg-hover)] hover:translate-x-0.5";

  // Type-specific classes
  const typeClasses = {
    info: "border-l-blue-500",
    success: "border-l-emerald-500 bg-emerald-500/5",
    error: "border-l-red-500 bg-red-500/5",
    warning: "border-l-amber-500 bg-amber-500/5"
  };

  logEntry.className = `${baseClasses} ${typeClasses[type] || typeClasses.info}`;

  // 处理消息内容
  let processedMessage = escapeHtml(message);

  // 智能高亮：仅高亮特定模式
  // 1. 高亮 "标签: 值" 格式的哈希值
  processedMessage = processedMessage.replace(
    /(Seed|Hash|哈希|Nonce):\s*([a-f0-9]{16,})/gi,
    '$1: <span class="log-highlight text-[var(--text-primary)] font-semibold bg-[var(--bg-primary)] px-1 sm:px-1.5 py-0.5 rounded font-mono text-[0.65rem] sm:text-xs">$2</span>',
  );

  // 2. 高亮 "标签: 数字" 或 "标签: 数字单位" 格式（如：难度: 1、内存: 64MB、总耗时: 5秒）
  processedMessage = processedMessage.replace(
    /(难度|内存需求|总耗时|耗时|Difficulty|Memory|Time):\s*(\d+\.?\d*)(MB|秒|s)?/gi,
    '$1: <span class="log-highlight text-[var(--text-primary)] font-semibold bg-[var(--bg-primary)] px-1 sm:px-1.5 py-0.5 rounded font-mono text-[0.65rem] sm:text-xs">$2$3</span>',
  );

  // 3. 高亮设备指纹（8位十六进制且前后有明确边界）
  processedMessage = processedMessage.replace(
    /\b([a-f0-9]{8})\b/g,
    '<span class="log-highlight text-[var(--text-primary)] font-semibold bg-[var(--bg-primary)] px-1 sm:px-1.5 py-0.5 rounded font-mono text-[0.65rem] sm:text-xs">$1</span>',
  );

  const { icon, colorClass } = iconConfig[type] || iconConfig.info;

  logEntry.innerHTML = `
    <div class="log-icon flex-shrink-0 w-4 h-4 sm:w-5 sm:h-5 flex items-center justify-center text-xs sm:text-sm font-semibold mt-0.5 ${colorClass}">${icon}</div>
    <div class="log-content flex-1 min-w-0">
      <div class="log-time text-[0.65rem] sm:text-xs text-[var(--text-tertiary)] mb-0.5 sm:mb-1 font-medium">${time}</div>
      <div class="log-message text-xs sm:text-[0.8125rem] leading-relaxed text-[var(--text-secondary)] break-words ${type === 'success' ? 'text-emerald-500 font-medium' : ''} ${type === 'error' ? 'text-red-500 font-medium' : ''} ${type === 'warning' ? 'text-amber-500' : ''}">${processedMessage}</div>
    </div>
  `;

  logBox.appendChild(logEntry);

  // 限制日志条目数量，防止 DOM 过大导致浏览器卡死
  while (logBox.children.length > MAX_LOG_ENTRIES) {
    logBox.removeChild(logBox.firstChild); // 删除最旧的日志
  }

  logBox.scrollTop = logBox.scrollHeight;
}
