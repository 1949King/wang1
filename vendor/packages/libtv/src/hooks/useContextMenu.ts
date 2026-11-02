/**
 * useWindowPanel 的兄弟：右键菜单的状态机（2026-11-02 · 画布 0.3.37）。
 *
 * ## 为什么菜单必须 portal 到 body
 *
 * 画布浮动面板（`.oh-panel`）在 CSS 模式下是 `position:fixed` + `translateX(-50%)`，
 * 拖过之后内联写 `left/top`。**有 transform 的祖先会成为 fixed 后代的包含块** ——
 * 菜单挂在面板里，`left: clientX` 就会变成「距面板左边缘」而不是「距视口左边」，
 * 菜单会飘到屏幕外（团队面板踩过同一个坑，见 2026-11-02 CHANGELOG）。
 * 所以调用方一律 `createPortal(<menu/>, document.body)`，本 hook 只管状态。
 *
 * ## 关闭时机
 *
 * Esc / 点别处 / 窗口失焦 / 再次右键到别处。菜单自身须 `onPointerDown` 停止冒泡，
 * 否则「按下即关闭」，click 永远不会触发。
 */
import { useCallback, useEffect, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";

export type CtxMenuState<T> = { x: number; y: number; target: T } | null;

export interface CtxMenuApi<T> {
  state: CtxMenuState<T>;
  /** 挂到目标的 onContextMenu：阻止默认菜单并记录坐标 + 该条数据。 */
  open: (e: ReactMouseEvent, target: T) => void;
  close: () => void;
}

/** 菜单宽 / 高估计值（用于贴边翻转；不必精确，偏差只影响 1~2px）。 */
const MENU_W = 208;
const MENU_H = 132;
const EDGE = 8;

export function useContextMenu<T>(): CtxMenuApi<T> {
  const [state, setState] = useState<CtxMenuState<T>>(null);

  const open = useCallback((e: ReactMouseEvent, target: T) => {
    e.preventDefault();
    e.stopPropagation();
    const vw = typeof window === "undefined" ? 1280 : window.innerWidth;
    const vh = typeof window === "undefined" ? 800 : window.innerHeight;
    // 贴边翻转：右下角右键时菜单不能跑到屏幕外
    const x = Math.max(EDGE, Math.min(e.clientX, vw - MENU_W - EDGE));
    const y = Math.max(EDGE, Math.min(e.clientY, vh - MENU_H - EDGE));
    setState({ x, y, target });
  }, []);

  const close = useCallback(() => setState(null), []);

  useEffect(() => {
    if (!state) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") close();
    };
    const onOutside = () => close();
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onOutside);
    window.addEventListener("blur", onOutside);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onOutside);
      window.removeEventListener("blur", onOutside);
    };
  }, [state, close]);

  return { state, open, close };
}
