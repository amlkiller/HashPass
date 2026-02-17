/**
 * Admin 全局状态管理
 */
export const adminState = {
  token: sessionStorage.getItem("admin_token") || "",
  ws: null,
  currentTab: "dashboard",
  logsPage: 1,
  logsFile: "verify.json",
  logsSearch: "",
};
