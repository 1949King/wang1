/**
 * CanvasOverlays.tsx — 画布浮层簇（2026-10-06）
 *
 * 为什么要有这一层
 * ================
 * 这些浮层都要挂在 `CanvasShell` 之外，而 `App.tsx` **已顶到单文件规模守卫上限（1998/2000 行）**
 * ⇒ 按项目纪律**拆模块**，而不是往里塞。于是把「画布上的浮层」收成**一个入口**：
 *
 *   App.tsx ──<CanvasOverlays />──┬─ 工具条（输出历史 / 灯位 / 导演指导 / 上游引用开关）
 *                                 └─ 对应面板（自持开关）
 *
 * 好处：App.tsx **净增 0 行**；浮层各自状态不外泄；本文件不 import CanvasShell（冻结区）⇒ **零解冻**。
 *
 * V4.40.54：Agent 侧栏打开时的让位/折叠改为 **JS 驱动**
 * =====================================================
 * 原先用 CSS `body:has(.workspace.agent-open) .ov-bar { right: 338px }` 让位，实测**不生效**：
 * 本机 Qt WebEngine（Chromium 134）对 `:has()` 的样式失效(invalidation)不可靠——给 `.workspace`
 * 加上 `agent-open` 后，`.ov-bar` 的 computed right 仍是 18px，必须等别的样式改动触发一次
 * 全量重算才会变成 338px（探针见 `.workbuddy/tmp/probe_has3.py`，三步对照实测）。
 * ⇒ 改为：盯 `.workspace` 的 class 变化（MutationObserver）→ 直接写 **内联样式** 定位，
 *    同时把 4 个入口收成一枚「🧰 工具」胶囊，避免让位后又压住画布底部工具条（`.libtv-dock`）。
 */
import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";

import DirectorPanel from "./DirectorPanel";
import LightingPanel from "./LightingPanel";
import OutputHistoryPanel from "./OutputHistoryPanel";
import { isTypingTarget } from "./CommandPalette";
import { useUpstreamRefsSync } from "./upstreamRefs";
import "./overlayBar.css";

const PIN_KEY = "shiguang-canvas:output-history:pinned";

/** Agent 侧栏让位量：面板宽上限 320（styles.css 的 minmax(280px,320px)）+ 18px 间距 */
const AGENT_DOCK_OFFSET_PX = 338;
/**
 * 抬到画布底部工具条（`.libtv-dock`：absolute, bottom:10, 高 45 ⇒ 占 bottom 10~55）之上。
 * 实测（.workbuddy/tmp/verify_ovbar.py）：默认 `bottom:44` 时与 dock **已相交 33×11px**
 * （工具条右端压在缩放条上沿）——这是存量问题，两态都要抬。
 */
const AGENT_DOCK_LIFT_PX = 62;

export default function CanvasOverlays() {
  const [showHistory, setShowHistory] = useState(() => {
    // 「固定面板」勾着 ⇒ 打开画布就显示（对标参考产品的固定语义，且**真的生效**）
    try {
      return localStorage.getItem(PIN_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [showLighting, setShowLighting] = useState(false);
  const [showDirector, setShowDirector] = useState(false);
  /** Agent 侧栏是否打开（决定让位 + 折叠） */
  const [agentOpen, setAgentOpen] = useState(false);
  /** Agent 打开时，工具胶囊是否展开 */
  const [toolsOpen, setToolsOpen] = useState(false);

  const toggleHistory = useCallback(() => setShowHistory((v) => !v), []);

  // 「连线上游素材引用」：默认关；开启后连线的上游产物会写进下游节点的真实引用字段
  // （firstFrameUrl —— 生成侧真的会用它，不是往提示词里塞 @ 装饰）。
  const upstreamRefs = useUpstreamRefsSync();

  // Agent 侧栏开合 ⇒ 让位（见文件头 V4.40.54 说明：不用 :has()，直接盯 class 写内联样式）
  useEffect(() => {
    let mo: MutationObserver | null = null;
    let timer = 0;
    let tries = 0;
    const attach = () => {
      const ws = document.querySelector(".workspace");
      if (!ws) {
        // 首帧时 CanvasShell 可能还没挂上，重试几轮（共 5s）
        if (tries++ < 20) timer = window.setTimeout(attach, 250);
        return;
      }
      const sync = () => {
        const open = ws.classList.contains("agent-open");
        setAgentOpen(open);
        if (!open) setToolsOpen(false);
      };
      sync();
      mo = new MutationObserver(sync);
      mo.observe(ws, { attributes: true, attributeFilter: ["class"] });
    };
    attach();
    return () => {
      mo?.disconnect();
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  // Ctrl+H 输出历史 · Ctrl+L 灯位 · Ctrl+D 导演指导（输入框内不触发）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.shiftKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      const k = (e.key || "").toLowerCase();
      if (k === "h") {
        e.preventDefault();
        toggleHistory();
      } else if (k === "l") {
        e.preventDefault();
        setShowLighting((v) => !v);
      } else if (k === "d") {
        e.preventDefault();
        setShowDirector((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleHistory]);

  const chips = (
    <>
      <button
        type="button"
        className={`oh-open-chip${showHistory ? " on" : ""}`}
        title="输出历史（Ctrl+H）"
        onClick={toggleHistory}
      >
        输出历史
      </button>
      <button
        type="button"
        className={`oh-open-chip${showLighting ? " on" : ""}`}
        title="电影级灯位：24 主光位 + 9 轮廓光（Ctrl+L）"
        onClick={() => setShowLighting((v) => !v)}
      >
        灯位
      </button>
      <button
        type="button"
        className={`oh-open-chip${showDirector ? " on" : ""}`}
        title="导演指导：诊断分镜缺什么并一键写回（Ctrl+D）"
        onClick={() => setShowDirector((v) => !v)}
      >
        导演指导
      </button>
      <button
        type="button"
        className={`oh-open-chip${upstreamRefs.enabled ? " on" : ""}`}
        title="连线上游素材引用：开启后连线的上游产物会写进下游节点的引用字段（不覆盖你已设的首帧）"
        onClick={upstreamRefs.toggle}
      >
        上游引用 {upstreamRefs.enabled ? "开" : "关"}
      </button>
    </>
  );

  // 两态都抬到画布底部工具条之上（否则右端压住缩放条）；Agent 打开时再让出面板那一列。
  // 全部走内联样式，不用 CSS（原因见文件头 V4.40.54 说明）。
  const barStyle: CSSProperties = agentOpen
    ? { right: AGENT_DOCK_OFFSET_PX, bottom: AGENT_DOCK_LIFT_PX }
    : { bottom: AGENT_DOCK_LIFT_PX };

  return (
    <>
      {/* 浮层工具条：四个入口收成一条，避免右下角一堆散胶囊 */}
      <div className="ov-bar" style={barStyle}>
        {agentOpen ? (
          <>
            <button
              type="button"
              className={`oh-open-chip${toolsOpen ? " on" : ""}`}
              title="画布工具：输出历史 / 灯位 / 导演指导 / 上游引用"
              onClick={() => setToolsOpen((v) => !v)}
            >
              🧰 工具 {toolsOpen ? "▾" : "▸"}
            </button>
            {toolsOpen ? chips : null}
          </>
        ) : (
          chips
        )}
      </div>
      {showHistory ? <OutputHistoryPanel onClose={() => setShowHistory(false)} /> : null}
      {showLighting ? <LightingPanel onClose={() => setShowLighting(false)} /> : null}
      {showDirector ? <DirectorPanel onClose={() => setShowDirector(false)} /> : null}
    </>
  );
}
