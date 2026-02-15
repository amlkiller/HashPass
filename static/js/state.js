/**
 * 全局状态管理模块
 * 集中管理应用的所有状态变量
 */

export const state = {
  // 挖矿状态
  mining: false,
  visitorId: "",
  miningWorker: null,
  miningTimer: null,
  miningStartTime: 0,
  miningElapsed: 0, // 累计挖矿时长（毫秒），刷新页面才重置

  // WebSocket 状态
  ws: null,
  wsPingTimer: null,
  onlineCount: 0,
  reconnectAttempts: 0,
  reconnectTimer: null,

  // Turnstile 状态
  turnstileToken: null,
  turnstilesiteKey: null,
  turnstileWidgetId: null,

  // Session Token 状态
  sessionToken: null,
};
