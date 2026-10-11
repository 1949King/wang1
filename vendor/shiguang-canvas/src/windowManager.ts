/**
 * windowManager.ts — AgentOS S1「窗口管理」的状态层（V4.41.18）。
 *
 * 与 toolboxStore 的分工
 * ====================
 *   toolboxStore 持「面板开没开」（xOpen，语义不变）；
 *   本 store 持「窗口形态」：minimized（最小化）+ order（层叠顺序，尾部 = 最顶）。
 *   两层用**模块级 subscribe** 联动：open=false ⇒ 自动清 minimized + 移出 order，
 *   面板组件与 CanvasOverlays 零感知。
 *
 * z 分配为什么是顺序数组而不是计数器
 * ==================================
 * 计数器方案（47 递增 + 夹上限 59）在多面板轮转置顶后会触顶撞车（多个面板同 z，
 * 上下关系退化为 DOM 顺序）。顺序数组把 z 变成**派生值**：z = 47 + indexOf(name)，
 * 4 面板恒在 47..50，永不触顶、永不撞车、无需重整。根级竞争者全在安全距离：
 * ltd-board/sg-agent-fab(60) / sg-agent-panel(70) / lightbox(9000) / modal(10000)。
 *
 * 持久化口径
 * ==========
 *   - **位置持久化**（拖过 = 用户摆过 = 尊重）：归一化 (x,y) ∈ [0,1]²，
 *     与桌宠 usePetDrag 同一范式（换窗口尺寸按比例落位，不跑到屏外）。
 *   - **最小化不持久化**：刷新还原正常态，避免「我的面板哪去了」。
 *
 * 存储层安全：vitest 是 node 环境无 localStorage/window ⇒ 全部 typeof 守卫，
 * 测试用 vi.stubGlobal 注入内存实现。
 */
import { create } from "zustand";

import { useToolboxStore } from "./toolboxStore";

export type PanelName = "history" | "gallery" | "lighting" | "director" | "generate";
export const PANEL_NAMES: readonly PanelName[] = ["history", "gallery", "lighting", "director", "generate"];

/** dock 最小化图标与恢复 title 的元数据（图标与工具板 ltd-item 同源，零新资产）。 */
export const PANEL_META: Record<PanelName, { title: string; icon: string }> = {
  history: { title: "输出历史", icon: "⏱" },
  gallery: { title: "图库", icon: "▤" },
  lighting: { title: "电影级灯位", icon: "💡" },
  director: { title: "导演指导", icon: "🎬" },
  generate: { title: "生成/入轨", icon: "🚀" },
};

export const Z_BASE = 47;
/** 面板距视口边最小留白（同桌宠 usePetDrag 的 INSET）。 */
export const PANEL_INSET = 8;
/** dock 保留带（dock bottom:10 + 按钮高 ~32 + 余量）：面板拖不进这条带。 */
export const DOCK_RESERVE = 64;
/** 拖动阈值（px）：超过才算「用户摆过」，切换 CSS 居中 → JS 定位。 */
export const DRAG_THRESHOLD = 5;

export interface PanelPos {
  x: number;
  y: number;
}

/* ────────────── 纯函数层（单测锚点，全部参数化，不碰 window/localStorage） ────────────── */

/** 面板 z = 47 + 层叠序（不在 order 的兜底 Z_BASE）。 */
export const zIndexOf = (order: readonly PanelName[], name: PanelName): number =>
  Z_BASE + Math.max(0, order.indexOf(name));

/** 把 name 移到层叠序末尾（= 置顶）。已是最顶则原样返回（幂等，零渲染）。
 *  纯实现：不原地修改，返回新数组。 */
export const focusInOrder = (order: readonly PanelName[], name: PanelName): PanelName[] => {
  const idx = order.indexOf(name);
  if (idx === -1) return [...order, name];
  if (idx === order.length - 1) return order as PanelName[];
  return [...order.slice(0, idx), ...order.slice(idx + 1), name];
};

/** 水平 clamp：视口内 [INSET, innerWidth - INSET - w]。 */
export const clampPanelLeft = (left: number, innerWidth: number, w: number): number =>
  Math.min(Math.max(left, PANEL_INSET), Math.max(PANEL_INSET, innerWidth - PANEL_INSET - w));

/** 垂直 clamp：上沿 ≥ INSET；底边不得进入 dock 保留带（innerHeight - DOCK_RESERVE）。 */
export const clampPanelTop = (top: number, innerHeight: number, h: number): number =>
  Math.min(Math.max(top, PANEL_INSET), Math.max(PANEL_INSET, innerHeight - DOCK_RESERVE - h));

/** 像素 → 归一化。分母为 0 时（极小窗口）该分量归 0；结果各分量恒在 [0,1]。 */
export const normalizePanelPos = (left: number, top: number, innerWidth: number, innerHeight: number, w: number, h: number): PanelPos => {
  const maxX = Math.max(0, innerWidth - PANEL_INSET * 2 - w);
  const maxY = Math.max(0, innerHeight - DOCK_RESERVE - PANEL_INSET - h);
  const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
  return {
    x: maxX > 0 ? clamp01((left - PANEL_INSET) / maxX) : 0,
    y: maxY > 0 ? clamp01((top - PANEL_INSET) / maxY) : 0,
  };
};

/** 归一化 → 像素（与 normalizePanelPos 分母严格一致，roundtrip 无漂移）。 */
export const denormPanelPos = (pos: PanelPos, innerWidth: number, innerHeight: number, w: number, h: number): { left: number; top: number } => {
  const maxX = Math.max(0, innerWidth - PANEL_INSET * 2 - w);
  const maxY = Math.max(0, innerHeight - DOCK_RESERVE - PANEL_INSET - h);
  return {
    left: PANEL_INSET + pos.x * maxX,
    top: PANEL_INSET + pos.y * maxY,
  };
};

/* ────────────── 存储层（node 测试环境守卫） ────────────── */

const posKey = (name: PanelName) => `shiguang-canvas:panel-pos:${name}:v1`;

export const loadPanelPos = (name: PanelName): PanelPos | null => {
  try {
    if (typeof localStorage === "undefined") return null;
    const raw = localStorage.getItem(posKey(name));
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<PanelPos>;
    if (typeof p?.x !== "number" || typeof p?.y !== "number") return null;
    return { x: Math.min(Math.max(p.x, 0), 1), y: Math.min(Math.max(p.y, 0), 1) };
  } catch {
    return null;
  }
};

export const savePanelPos = (name: PanelName, pos: PanelPos): void => {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(posKey(name), JSON.stringify(pos));
  } catch {
    /* 存储不可用（隐私模式/配额）不炸拖拽 */
  }
};

/* ────────────── store ────────────── */

export interface WindowManagerState {
  /** 层叠顺序（尾部 = 最顶）。z 由 zIndexOf 派生，不单独存。 */
  order: PanelName[];
  minimized: Record<PanelName, boolean>;
  /** 置顶（幂等：已是最顶不触发渲染）。 */
  focus: (name: PanelName) => void;
  minimize: (name: PanelName) => void;
  /** 恢复 = 取消最小化 + 置顶。 */
  restore: (name: PanelName) => void;
  /** open 联动：open=false 时清 minimized + 移出 order；open=true 由面板挂载时 focus 负责。 */
  syncOpen: (name: PanelName, open: boolean) => void;
}

const minimizedInit = (): Record<PanelName, boolean> => ({
  history: false,
  gallery: false,
  lighting: false,
  director: false,
  generate: false,
});

export const useWindowManager = create<WindowManagerState>((set, get) => ({
  order: [],
  minimized: minimizedInit(),
  focus: (name) => {
    const cur = get().order;
    const next = focusInOrder(cur, name);
    if (next !== cur) set({ order: next });
  },
  minimize: (name) =>
    set((s) => ({ minimized: { ...s.minimized, [name]: true } })),
  restore: (name) =>
    set((s) => ({
      minimized: { ...s.minimized, [name]: false },
      order: focusInOrder(s.order, name),
    })),
  syncOpen: (name, open) => {
    if (open) return; // 打开由面板挂载 focus 入列，这里不管
    set((s) => ({
      minimized: { ...s.minimized, [name]: false },
      order: s.order.filter((n) => n !== name),
    }));
  },
}));

/* ────────────── 模块级联动（单一订阅，组件零感知） ──────────────
 * toolboxStore 的 xOpen 翻转 → syncOpen 善后（关闭面板时最小化态和层叠序自动清理）。
 * zustand v5 的 subscribe 回调签名是 (state, prevState)，比较四个 open 键即可。 */
const OPEN_TO_PANEL: Array<["historyOpen" | "galleryOpen" | "lightingOpen" | "directorOpen", PanelName]> = [
  ["historyOpen", "history"],
  ["galleryOpen", "gallery"],
  ["lightingOpen", "lighting"],
  ["directorOpen", "director"],
];

useToolboxStore.subscribe((state, prev) => {
  const wm = useWindowManager.getState();
  for (const [openKey, panel] of OPEN_TO_PANEL) {
    if (state[openKey] !== prev[openKey]) {
      wm.syncOpen(panel, Boolean(state[openKey]));
    }
  }
});
