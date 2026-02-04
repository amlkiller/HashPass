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

    // 更新按钮激活状态 - 使用 Tailwind 类
    const inactiveClasses = "theme-btn flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 bg-transparent border-none rounded-md text-[var(--text-secondary)] cursor-pointer transition-all duration-200 hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]";
    const activeClasses = "theme-btn active flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 bg-[var(--bg-primary)] border-none rounded-md text-[var(--text-primary)] cursor-pointer transition-all duration-200 shadow-[var(--shadow-sm)]";

    document.querySelectorAll(".theme-btn").forEach((btn) => {
      btn.className = btn.dataset.theme === theme ? activeClasses : inactiveClasses;
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
