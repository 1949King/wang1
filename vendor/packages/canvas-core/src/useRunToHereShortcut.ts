/**
 * useRunToHereShortcut.ts — 「运行到此处」的快捷键注册（刀 A4 第 3 项，2026-10-05）。
 *
 * 为什么单独成文件：`App.tsx` 已顶到单文件规模守卫（2000 行），新增必然破门禁。
 * 按项目规矩**拆模块**，而不是放宽基线。
 *
 * 入口选快捷键的原因：画布 UI 文件（`CanvasShell.tsx`）属冻结区
 * `canvas-magnetic-intent`，往画布加按钮需单独解冻授权；快捷键零解冻、不碰冻结文件，
 * 功能本身完全不受影响。
 */
import { useEffect } from "react";

import { isTypingTarget } from "./CommandPalette";

/** Ctrl+Shift+Enter = 运行到此处。输入框内不触发（避免抢输入）。 */
export function useRunToHereShortcut(handler: () => void): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey || !e.shiftKey || e.key !== "Enter") return;
      if (isTypingTarget(e.target)) return;
      e.preventDefault();
      handler();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handler]);
}
