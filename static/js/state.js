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

  // WebSocket 状态
  ws: null,
  wsReconnectTimer: null,
  wsPingTimer: null,
  onlineCount: 0,

  // Turnstile 状态
  turnstileToken: null,
  turnstilesiteKey: null,
  turnstileWidgetId: null,
};
