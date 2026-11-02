/**
 * 团队协作 · 入口按钮（2026-10-31 · V4.49.1；2026-11-02 上移到常驻导航栏）
 *
 * 为什么单独成文件：`CanvasShell.tsx` 长期贴着体积守卫上限（基线 3251 行 / 容差 30），
 * 项目既有先例就是这么处理的（`canvasTierSeg.tsx` 注释原文：
 * 「组件单独成文件以避开本文件的体积守卫上限」）。
 *
 * 状态也一起搬进来：`open` 只服务于这个入口，放在 CanvasShell 里等于
 * 让每加一个入口都去挤那 30 行容差。
 *
 * 🔴 2026-11-02 用户实锤「项目里看不到团队入口」后换的位置：
 *   原先只挂在 `WorkspaceCanvasMenus`（= 画布视图第二条顶栏），而那条顶栏被
 *   `CanvasShell.tsx:929 showWorkspace = viewMode === "canvas"` 包着 ⇒
 *   首页落地页 / 我的画布 / 生图工作台 / 视频创作台 / 提示词库 / 我的资产 /
 *   配置 / 3D 导演台 **八个界面全都没有入口**；而开机默认就落在首页
 *   （`App.tsx:141-149` 强制 setViewMode("home")）⇒ 按默认路径打开即看不见。
 *   团队是「工作区级」能力、不依赖画布视图 ⇒ 唯一入口改挂常驻的 `AppNav`
 *   （`CanvasShell.tsx:978`，所有视图都渲染），收成左侧竖排栏里的 28px 图标
 *   按钮（复用 `.ic-shortcut-btn` 的尺寸与主题变体）。
 *
 * ⚠️ 名字沿用历史：它最初长在画布顶栏，所以叫 `TeamTopBarButton`。
 *   现在只有「竖排导航栏图标」一种形态 —— 上轮那套带字的 `bar` 形态已删，
 *   因为挂载点唯一，留着就是无调用方的死分支。
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { TeamPanel } from "./TeamPanel";

const TITLE = "团队协作：启动服务 / 连接 / 上传画布 / 交接给同事";

/** PyQt 主程序顶栏「👥 团队」经 QWebEngine `runJavaScript` 调用的全局钩子。 */
type TeamOpenHook = { __sgTeamOpen?: () => void };

export function TeamTopBarButton() {
  const [open, setOpen] = useState(false);

  // 2026-11-02（用户要求「放到主程序顶栏『登录』那一排」）：
  // PyQt 那颗按钮要能打开这个面板。通道刻意选「全局函数」而不是 window 事件 ——
  // `runJavaScript("window.dispatchEvent(...)")` 在画布还没加载时**照样成功返回**，
  // 结果是「点了没反应但也不报错」；而全局函数可以让 PyQt 先问
  // `typeof window.__sgTeamOpen === 'function'`，拿到 true 才发，能如实告诉用户
  // 「画布还没就绪」。
  useEffect(() => {
    const w = window as unknown as TeamOpenHook;
    w.__sgTeamOpen = () => setOpen(true);
    return () => {
      delete w.__sgTeamOpen;
    };
  }, []);

  return (
    <>
      <button
        type="button"
        className={`ic-shortcut-btn${open ? " on" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title={TITLE}
        aria-label="团队协作"
      >
        <span aria-hidden>👥</span>
      </button>
      {/* 🔴 2026-11-02 用户实锤「就这么小一个窗口，你觉得谁能看到？」——
          面板必须 portal 到 body，不能就地渲染在导航栏里。
          原因：`.ic-nav` 有 `backdrop-filter: blur(10px)`，而 **backdrop-filter
          会让该元素成为 `position: fixed` 后代的包含块**（和 transform/filter
          同一类）。于是 `.sg-team-panel` 的 `right:18px` 变成「距 64px 宽导航栏
          右边缘 18px」⇒ 420px 的面板整块被推到屏幕左外侧，只剩约 46px 一条
          窄缝露在窗口左边缘，看起来就像个「小窗口」。portal 到 body 后包含块
          回到视口，与祖先的 filter 彻底解耦。 */}
      {open
        ? createPortal(<TeamPanel onClose={() => setOpen(false)} />, document.body)
        : null}
    </>
  );
}

export default TeamTopBarButton;
