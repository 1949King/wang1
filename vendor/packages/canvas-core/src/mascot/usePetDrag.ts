/**
 * 桌宠拖拽与位置记忆。
 *
 * 为什么不照抄参考实现的 `useMascotDrag`
 * =====================================
 * 参考实现依赖 `framer-motion` 的 `useMotionValue` 来「拖拽逐帧不触发 React 重渲染」，顺手还白拿了
 * 惯性与约束。我们仓库没有这个依赖（package.json 只有 react/react-dom/three/zustand/@xyflow/react），
 * 为一个桌宠引入 40KB 级动画库不划算 —— 改成：**原生 pointer 事件 + 直接写元素 style**，
 * 同样做到逐帧零重渲染，反而更少依赖。
 *
 * 位置存储口径与参考实现一致：存**归一化 (x, y) ∈ [0,1]²**，而不是像素。
 * 换窗口尺寸/换分辨率时位置按比例跟着走，不会出现「在 4K 上贴右下角、切回 1080p 时跑到屏幕外」。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

export interface PetDragForce {
  x: number;
  y: number;
  active: boolean;
}

export interface PetDragApi {
  rootRef: React.RefObject<HTMLDivElement | null>;
  dragging: boolean;
  getDragForce: () => PetDragForce;
  /** 挂在**拖拽把手**上（容器 div 或其内的 button 都行，故用 HTMLElement 而非 HTMLDivElement）。 */
  onPointerDown: (e: ReactPointerEvent<HTMLElement>) => void;
  /** 单击是否应被吞掉（刚拖拽过，别把拖拽收尾当成点击）。 */
  consumeClick: () => boolean;
  /** 回到默认位置（右键菜单「复位」用）。 */
  resetPosition: () => void;
}

const STORAGE_KEY = "shiguang-canvas:agent-pet:v1";
const INSET = 8;
const DEFAULT_RIGHT = 22;
const DEFAULT_BOTTOM = 172;
const DRAG_THRESHOLD = 5;
/** 速度归一到受力 [-1,1] 的参考值（px/ms → 视觉上「甩得狠」的临界）。 */
const DRAG_FORCE_VELOCITY = 1.1;
/** 拖拽后多久内的 click 视为拖拽收尾。 */
const CLICK_SUPPRESS_MS = 300;

const clamp = (v: number, min: number, max: number) => Math.min(Math.max(v, min), max);

const movementBounds = (size: number) => {
  if (typeof window === "undefined") return { maxX: 0, maxY: 0 };
  return {
    maxX: Math.max(0, window.innerWidth - INSET * 2 - size),
    maxY: Math.max(0, window.innerHeight - INSET * 2 - size),
  };
};

const defaultNormalized = (size: number, reserveRight: number) => {
  const { maxX, maxY } = movementBounds(size);
  const rightGap = DEFAULT_RIGHT + reserveRight;
  return {
    x: maxX > 0 ? clamp(maxX - (rightGap - INSET), 0, maxX) / maxX : 0,
    y: maxY > 0 ? clamp(maxY - (DEFAULT_BOTTOM - INSET), 0, maxY) / maxY : 0,
  };
};

const normalizeStored = (raw: unknown): { x: number; y: number } | null => {
  if (!raw || typeof raw !== "object") return null;
  const { x, y } = raw as { x?: unknown; y?: unknown };
  if (typeof x !== "number" || typeof y !== "number") return null;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { x: clamp(x, 0, 1), y: clamp(y, 0, 1) };
};

const loadStored = (): { x: number; y: number } | null => {
  try {
    return normalizeStored(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"));
  } catch {
    return null;
  }
};

const saveStored = (position: { x: number; y: number }) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(position));
  } catch {
    /* 存储不可用（隐私模式/配额满）时静默：桌宠位置不值得打断用户 */
  }
};

interface GestureState {
  pointerId: number;
  startX: number;
  startY: number;
  startLeft: number;
  startTop: number;
  lastX: number;
  lastY: number;
  lastT: number;
  moved: boolean;
}

/**
 * @param size         当前形态的像素边长（展开 132 / 迷你 56）。尺寸变化会按同一归一化位置重新落位。
 * @param reserveRight 右侧需要让出的宽度（px）。Agent 侧栏展开时通常 280~320px —— 桌宠默认落位必须
 *                     躲开它，否则「打开 Agent 后桌宠被面板压住」。
 */
export function usePetDrag(size: number, reserveRight = 0): PetDragApi {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const gestureRef = useRef<GestureState | null>(null);
  const forceRef = useRef<PetDragForce>({ x: 0, y: 0, active: false });
  const suppressClickUntilRef = useRef(0);
  const normalizedRef = useRef<{ x: number; y: number } | null>(null);
  const hasCustomRef = useRef(false);
  const reserveRightRef = useRef(reserveRight);
  reserveRightRef.current = reserveRight;

  /** 按归一化位置把元素放到像素位置（唯一写入点）。 */
  const place = useCallback((position: { x: number; y: number }) => {
    const el = rootRef.current;
    if (!el) return;
    const { maxX, maxY } = movementBounds(size);
    el.style.left = `${INSET + position.x * maxX}px`;
    el.style.top = `${INSET + position.y * maxY}px`;
  }, [size]);

  // 首帧落位：读存储 → 没有就右下角默认位
  useLayoutEffect(() => {
    const stored = loadStored();
    hasCustomRef.current = Boolean(stored);
    const position = stored ?? defaultNormalized(size, reserveRightRef.current);
    normalizedRef.current = position;
    place(position);
  }, [place, size]);

  // 尺寸 / 让位宽度变化：**没被用户手动摆过**才跟着走（用户摆过就尊重用户）
  useLayoutEffect(() => {
    if (hasCustomRef.current) {
      if (normalizedRef.current) place(normalizedRef.current);
      return;
    }
    const position = defaultNormalized(size, reserveRight);
    normalizedRef.current = position;
    place(position);
  }, [place, reserveRight, size]);

  // 窗口尺寸变化：按归一化位置重新落位（自定义位与默认位都要跟）
  useEffect(() => {
    const onResize = () => {
      const position = hasCustomRef.current
        ? normalizedRef.current ?? defaultNormalized(size, reserveRightRef.current)
        : defaultNormalized(size, reserveRightRef.current);
      normalizedRef.current = position;
      place(position);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [place, size]);

  // 拖拽期间在 window 上听（元素自己可能被裁切/指针移出元素），拖完摘掉
  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const gesture = gestureRef.current;
      const el = rootRef.current;
      if (!gesture || !el || e.pointerId !== gesture.pointerId) return;
      e.preventDefault();

      const dx = e.clientX - gesture.startX;
      const dy = e.clientY - gesture.startY;
      if (!gesture.moved && Math.hypot(dx, dy) >= DRAG_THRESHOLD) {
        gesture.moved = true;
        suppressClickUntilRef.current = Date.now() + CLICK_SUPPRESS_MS;
      }

      const now = performance.now();
      const dt = Math.max(now - gesture.lastT, 1);
      forceRef.current = {
        x: clamp((e.clientX - gesture.lastX) / dt / DRAG_FORCE_VELOCITY, -1, 1),
        y: clamp((e.clientY - gesture.lastY) / dt / DRAG_FORCE_VELOCITY, -1, 1),
        active: true,
      };
      gesture.lastX = e.clientX;
      gesture.lastY = e.clientY;
      gesture.lastT = now;

      const { maxX, maxY } = movementBounds(size);
      el.style.left = `${clamp(gesture.startLeft + dx, INSET, INSET + maxX)}px`;
      el.style.top = `${clamp(gesture.startTop + dy, INSET, INSET + maxY)}px`;
    };

    const finish = (e: PointerEvent) => {
      const gesture = gestureRef.current;
      if (!gesture || e.pointerId !== gesture.pointerId) return;
      const el = rootRef.current;
      if (el && gesture.moved) {
        const { maxX, maxY } = movementBounds(size);
        const position = {
          x: maxX > 0 ? clamp((el.offsetLeft - INSET) / maxX, 0, 1) : 0,
          y: maxY > 0 ? clamp((el.offsetTop - INSET) / maxY, 0, 1) : 0,
        };
        normalizedRef.current = position;
        hasCustomRef.current = true;
        saveStored(position);
      }
      gestureRef.current = null;
      forceRef.current = { x: 0, y: 0, active: false };
      setDragging(false);
    };

    window.addEventListener("pointermove", onMove, true);
    window.addEventListener("pointerup", finish, true);
    window.addEventListener("pointercancel", finish, true);
    return () => {
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("pointerup", finish, true);
      window.removeEventListener("pointercancel", finish, true);
    };
  }, [dragging, size]);

  const onPointerDown = useCallback((e: ReactPointerEvent<HTMLElement>) => {
    if (!e.isPrimary || e.button !== 0) return;
    const el = rootRef.current;
    if (!el) return;
    const now = performance.now();
    gestureRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startLeft: el.offsetLeft,
      startTop: el.offsetTop,
      lastX: e.clientX,
      lastY: e.clientY,
      lastT: now,
      moved: false,
    };
    setDragging(true);
  }, []);

  const consumeClick = useCallback(() => {
    if (Date.now() > suppressClickUntilRef.current) return false;
    suppressClickUntilRef.current = 0;
    return true;
  }, []);

  // ⚠️ 必须用 useCallback 稳定引用：调用方（AgentPet）把它放进「建 WebGL 场景」那个 effect 里，
  //    每次渲染换一个新函数会让场景被反复重建（桌宠闪一下 + 泄漏 WebGL 上下文）。
  const getDragForce = useCallback(() => forceRef.current, []);

  const resetPosition = useCallback(() => {
    const position = defaultNormalized(size, reserveRightRef.current);
    normalizedRef.current = position;
    hasCustomRef.current = false;
    place(position);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* 同上：存储不可用不打断 */
    }
  }, [place, size]);

  return { rootRef, dragging, getDragForce, onPointerDown, consumeClick, resetPosition };
}
