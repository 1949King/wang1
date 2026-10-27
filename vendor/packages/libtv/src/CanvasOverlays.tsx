/**
 * CanvasOverlays.tsx — 画布浮层簇（2026-10-06 建 · 2026-10-10 V4.41.15 精简）
 *
 * 为什么要有这一层
 * ================
 * 这些浮层都要挂在 `CanvasShell` 之外，而 `App.tsx` **已顶到单文件规模守卫上限（1998/2000 行）**
 * ⇒ 按项目纪律**拆模块**，而不是往里塞。于是把「画布上的浮层」收成**一个入口**：
 *
 *   App.tsx ──<CanvasOverlays />──┬─ 面板（输出历史 / 灯位 / 导演指导）
 *                                 └─ Agent 桌宠「拾岚」
 *
 * 好处：App.tsx **净增 0 行**；浮层各自状态不外泄；本文件不 import CanvasShell（冻结区）⇒ **零解冻**。
 *
 * V4.41.15：浮层工具条（ov-bar）整体退役
 * =====================================
 * 用户实测反馈画布底部三套控件叠加混乱（dock 13 图标 + ov-bar 4 胶囊 + ReactFlow Controls）。
 * 底部工具栏按 C 方案重做（见 `LibTvChrome.tsx`）：入口全部收进「⚡工具」横向工具板，
 * 面板开关迁移到 `toolboxStore.ts`（zustand）—— 工具板按钮与这里的面板渲染共享同一份 state，
 * 快捷键（Ctrl+H/L/D）改写 store，行为不变。本文件只剩「面板本体 + 桌宠」。
 *
 * V4.41.9：挂载 Agent 桌宠（Q 版狐狸「拾岚」）
 * ==========================================
 * 桌宠挂在本文件：这里订阅 Agent 侧栏开合态，正好就是桌宠需要的 `mini` 信号
 * （面板打开 → 桌宠隐藏，V4.41.14）。
 * 2026-10-14 用户授权：开合态改由**类型化事件** `sg-agent-state` 回播（不再 MutationObserver
 * 嗅 `.workspace.agent-open`）；点桌宠发 `sg-toggle-agent` 交由 CanvasShell 统一翻转，
 * 多画布 / DOM 重挂时不再失准。
 * 本文件不在冻结区，零解冻；桌宠**懒载**，`fallback={null}` 期间画布零影响。
 */
import { Suspense, lazy, useCallback, useEffect, useState } from "react";

import DirectorPanel from "./DirectorPanel";
import GalleryPanel from "./GalleryPanel";
import LightingPanel from "./LightingPanel";
import OutputHistoryPanel from "./OutputHistoryPanel";
// V4.41.20：生成/入轨浮动面板（顶栏 🚀 生成；agent 面板开着也能用）
import GeneratePanel from "./GeneratePanel";
import { SectionErrorBoundary } from "./AppErrorBoundary";
import { usePetStatus } from "./mascot/usePetStatus";
import { isTypingTarget } from "./CommandPalette";
import { PREVIEW_STEP_MS, previewOrder } from "./previewPlayer";
import { useCanvasStore } from "./store";
import { useUpstreamRefsSync } from "./upstreamRefs";
import { useToolboxStore } from "./toolboxStore";
import { useWindowManager } from "./windowManager";
import "./canvasOverlayLayout.css";

const AgentPet = lazy(() => import("./mascot/AgentPet"));

export default function CanvasOverlays() {
  const showHistory = useToolboxStore((s) => s.historyOpen);
  const showLighting = useToolboxStore((s) => s.lightingOpen);
  const showDirector = useToolboxStore((s) => s.directorOpen);
  const showGallery = useToolboxStore((s) => s.galleryOpen);
  const showGenerate = useToolboxStore((s) => s.generateOpen);
  // 窗口管理（AgentOS S1）：最小化的面板不渲染本体（dock 上有恢复入口）
  const minimized = useWindowManager((s) => s.minimized);
  const toggleHistory = useToolboxStore((s) => s.toggleHistory);
  const toggleLighting = useToolboxStore((s) => s.toggleLighting);
  const toggleDirector = useToolboxStore((s) => s.toggleDirector);
  const toggleGallery = useToolboxStore((s) => s.toggleGallery);
  const toggleGenerate = useToolboxStore((s) => s.toggleGenerate);

  /** Agent 侧栏是否打开（决定桌宠隐藏态） */
  const [agentOpen, setAgentOpen] = useState(false);

  // 桌宠状态：由画布真实状态派生（节点在跑生成 / 弹了确认框在等你 / 刚失败）。
  // 详见 mascot/petActivity.ts（纯函数状态机）与 mascot/usePetStatus.ts（订阅源）。
  const petStatus = usePetStatus();

  /**
   * 点桌宠 = 进入 Agent 对话画面。
   * 2026-10-14 用户授权：改走**类型化事件通道**，交给 CanvasShell 自己 toggle。
   * 旧实现「嗅 `.workspace.agent-open` + 按文字猜 `.libtv-agent-btn` 强点」有两个硬伤：
   *   1. 猜 DOM：顶栏两个同 class 按钮（🚀 生成 / 💬 Agent），多画布、DOM 重挂时命不中；
   *   2. 单向：桌宠只会「打开」，没有回到桌宠的入口——回桌宠只能靠关闭面板间接触发。
   * 现在桌宠只发 `sg-toggle-agent`，由 CanvasShell（持有 agentPanelOpen 真相源）统一翻转，
   * 状态再经 `sg-agent-state` 事件回播给本组件 → 桌宠隐藏/回归与面板开合永远一致。
   */
  const openAgent = useCallback(() => {
    window.dispatchEvent(new CustomEvent("sg-toggle-agent"));
    // 面板由事件驱动开启，输入框挂载后（下一帧）再交接焦点，「进入对话画面」才算到位
    window.setTimeout(() => {
      document.querySelector<HTMLTextAreaElement>(".sg-agent-input textarea")?.focus();
    }, 120);
  }, []);

  // 「连线上游素材引用」订阅同步仍在（开关状态已进 toolboxStore，这里只保留 apply 副作用）
  useUpstreamRefsSync();

  /* 连线时序预览（V4.41.16 真功能）：按拓扑层级从上游到下游逐节点高亮。
     推进用 interval + store.advancePreview（播完自动停）；每步把画布状态栏
     写成进度（store.setStatus 已有机制），用户随时能读「播到哪了」。 */
  const previewPlaying = useToolboxStore((s) => s.previewPlaying);
  useEffect(() => {
    if (!previewPlaying) return;
    const nodes = useCanvasStore.getState().nodes;
    const edges = useCanvasStore.getState().edges;
    const order = previewOrder(
      (nodes || []).map((n: { id: string; position: { x: number; y: number } }) => ({
        id: n.id,
        x: n.position?.x ?? 0,
        y: n.position?.y ?? 0,
      })),
      (edges || []).map((e2: { source: string; target: string }) => ({ source: e2.source, target: e2.target })),
    );
    if (!order.length) {
      useCanvasStore.getState().setStatus("画布上没有节点可预览");
      useToolboxStore.getState().stopPreview();
      return;
    }
    const { setSelected, setStatus, advancePreview } = {
      setSelected: useCanvasStore.getState().setSelected,
      setStatus: useCanvasStore.getState().setStatus,
      advancePreview: useToolboxStore.getState().advancePreview,
    };
    let step = 0;
    const tick = () => {
      // 越界守卫：step 用完 order 后 interval 仍在跑，若不拦就会反复 dispatch
      // sg-preview-focus（detail=undefined）⇒ CanvasShell 反复 fitView ⇒ 相机抖动。
      // 播完只需把 progress 收尾（advancePreview 幂等），不再派发相机跟随。
      if (step >= order.length) {
        advancePreview(order.length);
        return;
      }
      setSelected(order[step]);
      setStatus(`时序预览 ${step + 1}/${order.length}`);
      // 相机跟随（V4.41.17）：CanvasShell 监听此事件 fitView 到当前节点，
      // 否则节点跑到视窗外就成了「白高亮」。冻结区只加了一个监听器（已授权）。
      window.dispatchEvent(new CustomEvent("sg-preview-focus", { detail: order[step] }));
      step += 1;
      advancePreview(order.length);
    };
    tick(); // 立即高亮第一个
    const timer = window.setInterval(tick, PREVIEW_STEP_MS);
    return () => window.clearInterval(timer);
  }, [previewPlaying]);

  // Agent 侧栏开合 ⇒ 桌宠隐藏/回归。
  // 2026-10-14 用户授权：不再 MutationObserver 盯 `.workspace` 的 class（DOM 嗅探、多画布易失准），
  // 改为订阅 CanvasShell 回播的**类型化事件** `sg-agent-state`；挂载后主动请求一次首帧回播，
  // 保证「刷新后 Agent 已开着」时桌宠也能立刻进入隐藏态。
  useEffect(() => {
    const onState = (e: Event) => {
      const detail = (e as CustomEvent<{ open?: boolean }>).detail || {};
      setAgentOpen(Boolean(detail.open));
    };
    window.addEventListener("sg-agent-state", onState as EventListener);
    window.dispatchEvent(new CustomEvent("sg-agent-state-request"));
    return () => window.removeEventListener("sg-agent-state", onState as EventListener);
  }, []);

  // Ctrl+H 输出历史 · Ctrl+L 灯位 · Ctrl+D 导演指导（输入框内不触发）—— 写 store，与工具板同源
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
        toggleLighting();
      } else if (k === "d") {
        e.preventDefault();
        toggleDirector();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleHistory, toggleLighting, toggleDirector]);

  return (
    <>
      {/* 浮动面板各自隔离：单个面板渲染崩溃只降级该面板，不再拖垮整块画布 */}
      <SectionErrorBoundary label="浮动面板">
        {showHistory && !minimized.history ? <OutputHistoryPanel onClose={toggleHistory} /> : null}
        {showLighting && !minimized.lighting ? <LightingPanel onClose={toggleLighting} /> : null}
        {showDirector && !minimized.director ? <DirectorPanel onClose={toggleDirector} /> : null}
        {showGallery && !minimized.gallery ? <GalleryPanel onClose={toggleGallery} /> : null}
        {showGenerate && !minimized.generate ? <GeneratePanel onClose={toggleGenerate} /> : null}
      </SectionErrorBoundary>
      {/* Agent 桌宠（Q 版狐狸「拾岚」）：Agent 面板打开时隐藏（V4.41.14）。
          懒载 + fallback=null —— 加载期间画布零影响。 */}
      {/* 混合算力滑块已并入 Agent「模型」页，底部不再常驻胶囊遮挡 dock。 */}
      <Suspense fallback={null}>
        <AgentPet status={petStatus} mini={agentOpen} onActivate={openAgent} />
      </Suspense>
    </>
  );
}
