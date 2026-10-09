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
 * 桌宠挂在本文件：这里已经知道 Agent 侧栏开没开（MutationObserver 盯 `.workspace.agent-open`），
 * 正好就是桌宠需要的 `mini` 信号（面板打开 → 桌宠隐藏，V4.41.14）。
 * 本文件不在冻结区，零解冻；桌宠**懒载**，`fallback={null}` 期间画布零影响。
 */
import { Suspense, lazy, useCallback, useEffect, useState } from "react";

import DirectorPanel from "./DirectorPanel";
import GalleryPanel from "./GalleryPanel";
import LightingPanel from "./LightingPanel";
import OutputHistoryPanel from "./OutputHistoryPanel";
import { usePetStatus } from "./mascot/usePetStatus";
import { isTypingTarget } from "./CommandPalette";
import { PREVIEW_STEP_MS, previewOrder } from "./previewPlayer";
import { useCanvasStore } from "./store";
import { useUpstreamRefsSync } from "./upstreamRefs";
import { useToolboxStore } from "./toolboxStore";

const AgentPet = lazy(() => import("./mascot/AgentPet"));

export default function CanvasOverlays() {
  const showHistory = useToolboxStore((s) => s.historyOpen);
  const showLighting = useToolboxStore((s) => s.lightingOpen);
  const showDirector = useToolboxStore((s) => s.directorOpen);
  const showGallery = useToolboxStore((s) => s.galleryOpen);
  const toggleHistory = useToolboxStore((s) => s.toggleHistory);
  const toggleLighting = useToolboxStore((s) => s.toggleLighting);
  const toggleDirector = useToolboxStore((s) => s.toggleDirector);
  const toggleGallery = useToolboxStore((s) => s.toggleGallery);

  /** Agent 侧栏是否打开（决定桌宠隐藏态） */
  const [agentOpen, setAgentOpen] = useState(false);

  // 桌宠状态：由画布真实状态派生（节点在跑生成 / 弹了确认框在等你 / 刚失败）。
  // 详见 mascot/petActivity.ts（纯函数状态机）与 mascot/usePetStatus.ts（订阅源）。
  const petStatus = usePetStatus();

  /**
   * 点桌宠 = 进入 Agent 对话画面。
   * 不碰冻结的 `CanvasShell.tsx`：直接驱动它自己那个 `.libtv-agent-btn`（它内部 toggle 状态）。
   * 只在「还没开」时点，避免点一下反而把面板关掉。
   */
  const openAgent = useCallback(() => {
    const workspace = document.querySelector(".workspace");
    const isOpen = Boolean(workspace?.classList.contains("agent-open"));
    if (!isOpen) {
      document.querySelector<HTMLButtonElement>(".libtv-agent-btn")?.click();
      return;
    }
    // 已开：直接把焦点交给输入框，「进入对话画面」才算真的到位
    document.querySelector<HTMLTextAreaElement>(".sg-agent-input textarea")?.focus();
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

  // Agent 侧栏开合 ⇒ 桌宠隐藏/回归（盯 class，不用 :has() —— Chromium 134 样式失效坑）
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
      const sync = () => setAgentOpen(ws.classList.contains("agent-open"));
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
      {showHistory ? <OutputHistoryPanel onClose={toggleHistory} /> : null}
      {showLighting ? <LightingPanel onClose={toggleLighting} /> : null}
      {showDirector ? <DirectorPanel onClose={toggleDirector} /> : null}
      {showGallery ? <GalleryPanel onClose={toggleGallery} /> : null}
      {/* Agent 桌宠（Q 版狐狸「拾岚」）：Agent 面板打开时隐藏（V4.41.14）。
          懒载 + fallback=null —— 加载期间画布零影响。 */}
      <Suspense fallback={null}>
        <AgentPet status={petStatus} mini={agentOpen} onActivate={openAgent} />
      </Suspense>
    </>
  );
}
