/**
 * useWindowPanel.ts — 面板窗口化 hook（AgentOS S1，V4.41.18）。
 *
 * 三件事：拖 header 移动 / 点击置顶 / 最小化。
 *
 * 定位模型（关键设计，防拖拽跳动）
 * ==============================
 *   - **CSS 模式**（从未拖过）：不写任何定位 style，面板保持样式表的
 *     `left:50% + translateX(-50%) + bottom:58px` 底部居中。resize 自动保持居中。
 *   - **JS 模式**（拖过 5px 阈值，或 localStorage 有存储位置）：内联
 *     `left/top + transform:none + bottom:auto`（必须一次写全 —— top/bottom 双锚会拉伸，
 *     translateX 残留会偏半面板宽）。
 *   - 切换点在 pointermove 检测跨越 DRAG_THRESHOLD 那一刻，用 getBoundingClientRect
 *     拿**当前视觉位置**做起点 —— fixed 面板且无 transform 祖先（CanvasOverlays 挂 App 根），
 *     rect 视口坐标 = fixed 定位坐标，逐像素相等 ⇒ 零跳动。
 *     ⚠️ 不能用 offsetLeft（fixed+translateX 下它是未平移的 CSS left，差半面板宽）。
 *
 * 拖拽零重渲染：left/top 命令式直写 el.style（照 usePetDrag 范式），React style 只含
 * zIndex —— React 不 diff 自己没渲染过的 style key，重渲染不会把面板打回旧位置。
 */
import { useCallback, useEffect, useRef, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";

import {
  DOCK_RESERVE,
  DRAG_THRESHOLD,
  PANEL_INSET,
  clampPanelLeft,
  clampPanelTop,
  denormPanelPos,
  loadPanelPos,
  normalizePanelPos,
  savePanelPos,
  useWindowManager,
  zIndexOf,
  type PanelName,
} from "../windowManager";

export interface WindowPanelApi {
  panelRef: React.RefObject<HTMLDivElement | null>;
  /** 只含 zIndex —— left/top 永不进 React style（见文件头）。 */
  style: CSSProperties;
  /** 挂外层 div 的 onPointerDown：点击置顶（幂等）。 */
  focusPanel: () => void;
  /** 挂 header 的 onPointerDown：拖拽起点（自动排除 header 内的按钮/输入控件）。 */
  startDrag: (e: ReactPointerEvent<HTMLElement>) => void;
  minimize: () => void;
}

export function useWindowPanel(name: PanelName): WindowPanelApi {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const z = useWindowManager((s) => zIndexOf(s.order, name));
  const focus = useWindowManager((s) => s.focus);
  const minimizeFn = useWindowManager((s) => s.minimize);

  /** 定位唯一写入点：一次写全 left/top/transform/bottom（JS 模式）。 */
  const place = useCallback((left: number, top: number, clampHeight: boolean) => {
    const el = panelRef.current;
    if (!el) return;
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    el.style.bottom = "auto";
    el.style.right = "auto";
    el.style.transform = "none";
    if (clampHeight) {
      // 内容长高（搜索结果变多/缩略图加载）不越进 dock 带；同时尊重各面板 CSS 的 vh 上限。
      const cssMax = parseFloat(getComputedStyle(el).maxHeight);
      const cap = window.innerHeight - DOCK_RESERVE - top;
      el.style.maxHeight = `${Math.max(180, Math.min(Number.isNaN(cssMax) ? Infinity : cssMax, cap))}px`;
    }
  }, []);

  /* 挂载：读存储位置（有则直接 JS 模式落位）+ 入层叠序置顶 */
  useEffect(() => {
    focus(name);
    const pos = loadPanelPos(name);
    const el = panelRef.current;
    if (pos && el) {
      const { left, top } = denormPanelPos(pos, window.innerWidth, window.innerHeight, el.offsetWidth, el.offsetHeight);
      place(left, top, true);
    }
    // focus 幂等（已最顶零渲染）；name 是字面量联合类型，依赖只挂 focus
  }, [name, focus, place]);

  /* resize：JS 模式按归一化重落位（CSS 模式不管，样式表自动保持居中） */
  useEffect(() => {
    const onResize = () => {
      const el = panelRef.current;
      const pos = loadPanelPos(name);
      if (!el || !pos) return;
      const { left, top } = denormPanelPos(pos, window.innerWidth, window.innerHeight, el.offsetWidth, el.offsetHeight);
      place(left, top, true);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [name, place]);

  /* 拖拽：header onPointerDown 起手，window 级 move/up/capture 收尾（照 usePetDrag 范式） */
  const gesture = useRef({
    pointerId: -1,
    startClientX: 0,
    startClientY: 0,
    startLeft: 0,
    startTop: 0,
    moved: false,
  });

  const startDrag = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      // header 内的按钮/勾选/输入控件不触发拖拽（关闭/最小化/pin 天然互斥，无需 consumeClick）
      if ((e.target as HTMLElement).closest("button,input,label,a,select,textarea")) return;
      const el = panelRef.current;
      if (!el) return;
      focus(name); // 抓起来就置顶
      const g = gesture.current;
      g.pointerId = e.pointerId;
      g.startClientX = e.clientX;
      g.startClientY = e.clientY;
      g.moved = false;
      // 起点先按 CSS 模式记录（未切换时 rect 就是视觉位置）；跨阈值时再切换并覆写
      const rect = el.getBoundingClientRect();
      g.startLeft = rect.left;
      g.startTop = rect.top;

      const onMove = (ev: PointerEvent) => {
        if (ev.pointerId !== g.pointerId) return;
        const dx = ev.clientX - g.startClientX;
        const dy = ev.clientY - g.startClientY;
        if (!g.moved) {
          if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
          g.moved = true;
          // CSS → JS 模式切换：此刻 rect 仍是原始视觉位置（还没写过 style），零跳动
          const cur = el.getBoundingClientRect();
          el.style.left = `${cur.left}px`;
          el.style.top = `${cur.top}px`;
          el.style.bottom = "auto";
          el.style.right = "auto";
          el.style.transform = "none";
          g.startLeft = cur.left;
          g.startTop = cur.top;
        }
        const left = clampPanelLeft(g.startLeft + dx, window.innerWidth, el.offsetWidth);
        const top = clampPanelTop(g.startTop + dy, window.innerHeight, el.offsetHeight);
        el.style.left = `${left}px`;
        el.style.top = `${top}px`;
      };

      const finish = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
        if (!g.moved) return; // 只是点了一下 header：不动位置不落盘
        const pos = normalizePanelPos(
          parseFloat(el.style.left),
          parseFloat(el.style.top),
          window.innerWidth,
          window.innerHeight,
          el.offsetWidth,
          el.offsetHeight,
        );
        savePanelPos(name, pos);
      };

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
    },
    [name, focus],
  );

  const focusPanel = useCallback(() => focus(name), [focus]);
  const minimize = useCallback(() => minimizeFn(name), [minimizeFn, name]);

  return { panelRef, style: { zIndex: z }, focusPanel, startDrag, minimize };
}
