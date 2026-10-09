/**
 * toolboxStore.ts — 底部工具板的跨组件开关（zustand）。
 *
 * 为什么需要它
 * ============
 * 「输出历史 / 灯位 / 导演指导 / 上游引用」的面板本体渲染在 `CanvasOverlays.tsx`
 * （历史上有 ov-bar 四胶囊入口），而新工具板按钮渲染在 `LibTvChrome.tsx`
 * （由冻结区 CanvasShell 挂载、props 不能动）—— 两个组件没有共同父级，
 * 把开关收进 store 才能让「按钮点击」和「面板渲染」解耦且不重复 state。
 *
 * 上游引用的持久化仍走 `upstreamRefs.ts` 的 localStorage（默认关），
 * store 里的 `upstreamRefs` 只是它的镜像；toggle 时双写保持一致。
 * 快捷键（Ctrl+H/L/D）在 CanvasOverlays 里改为写 store，行为不变。
 */
import { create } from "zustand";

import { isUpstreamRefsEnabled, setUpstreamRefsEnabled } from "./upstreamRefs";

const PIN_KEY = "shiguang-canvas:output-history:pinned";

export interface ToolboxState {
  historyOpen: boolean;
  lightingOpen: boolean;
  directorOpen: boolean;
  upstreamRefs: boolean;
  toggleHistory: () => void;
  toggleLighting: () => void;
  toggleDirector: () => void;
  toggleUpstreamRefs: () => void;
}

export const useToolboxStore = create<ToolboxState>((set) => ({
  historyOpen: (() => {
    try {
      return localStorage.getItem(PIN_KEY) === "1";
    } catch {
      return false;
    }
  })(),
  lightingOpen: false,
  directorOpen: false,
  upstreamRefs: isUpstreamRefsEnabled(),
  toggleHistory: () => set((s) => ({ historyOpen: !s.historyOpen })),
  toggleLighting: () => set((s) => ({ lightingOpen: !s.lightingOpen })),
  toggleDirector: () => set((s) => ({ directorOpen: !s.directorOpen })),
  toggleUpstreamRefs: () => {
    const next = !isUpstreamRefsEnabled();
    setUpstreamRefsEnabled(next);
    set({ upstreamRefs: next });
  },
}));
