/**
 * 主题管理模块
 * 管理应用的主题切换（浅色、深色、系统）
 */

/**
 * 主题管理器对象
 */
export const themeManager = {
  /**
   * 初始化主题管理器
   */
  init() {
    // 从 localStorage 读取保存的主题偏好，默认为 dark
    const savedTheme = localStorage.getItem("theme") || "dark";
    this.setTheme(savedTheme);

    // 监听系统主题变化
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", (e) => {
        if (localStorage.getItem("theme") === "system") {
          this.applyTheme(e.matches ? "dark" : "light");
        }
      });

    // 绑定主题切换按钮
    document.querySelectorAll(".theme-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const theme = btn.dataset.theme;
        this.setTheme(theme);
      });
    });
  },

  /**
   * 设置主题
   * @param {string} theme - 主题名称 (light, dark, system)
   */
  setTheme(theme) {
    localStorage.setItem("theme", theme);

    // 更新按钮激活状态 - 只切换 active 类
    document.querySelectorAll(".theme-btn").forEach((btn) => {
      if (btn.dataset.theme === theme) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    // 应用主题
    if (theme === "system") {
      const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      this.applyTheme(isDark ? "dark" : "light");
    } else {
      this.applyTheme(theme);
    }
  },

  /**
   * 应用主题到 DOM
   * @param {string} theme - 主题名称 (light, dark)
   */
  applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  },
};
