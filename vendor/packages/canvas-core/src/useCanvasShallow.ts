/**
 * useCanvasShallow —— 画布「派生状态」的统一浅比较入口（2026-10-14 新增）。
 *
 * 背景（React error #185 = Maximum update depth exceeded）
 * ======================================================
 * zustand v5 + React 19 内部走 `useSyncExternalStore`。若 selector 每次调用都返回
 * **新引用**（新数组 / 新对象），React 判定「快照一直在变」⇒ 无限重渲染 ⇒
 * 画布白屏「画布遇到渲染错误」。
 *
 * 铁律
 * ====
 * 只要想在 selector 里**返回数组或对象**（哪怕只是 `{ a: s.a, b: s.b }`，
 * 或 `s.items.filter(...)` / `s.items.map(...)` / `s.x ?? []`），
 * 一律用本 hook 包一层：
 *
 *   const rows = useCanvasStore(useCanvasShallow((s) => s.nodes.filter((n) => n.selected)));
 *
 * 直接取存储里的**稳定引用**（`s.nodes`、`s.characters`、动作函数）不用包。
 * 漏包会被守卫 `_verify/check_canvas_selectors.py` 静态拦下（随守卫一起跑）。
 */
import { useShallow } from "zustand/react/shallow";

/**
 * 包裹 selector，使返回值按**浅比较**决定是否触发重渲染。
 * 与 zustand v5 的 `useShallow` 同源，只是给本项目一个唯一、可被守卫识别的入口。
 */
export const useCanvasShallow = useShallow;
