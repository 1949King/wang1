import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DOCK_RESERVE,
  PANEL_INSET,
  clampPanelLeft,
  clampPanelTop,
  denormPanelPos,
  focusInOrder,
  loadPanelPos,
  normalizePanelPos,
  savePanelPos,
  useWindowManager,
  zIndexOf,
  Z_BASE,
} from "./windowManager";

describe("z 派生（顺序数组）", () => {
  it("空 order 兜底 Z_BASE", () => {
    expect(zIndexOf([], "history")).toBe(Z_BASE);
  });

  it("z = Z_BASE + 层叠序", () => {
    expect(zIndexOf(["a" as never, "history"], "history")).toBe(Z_BASE + 1);
  });

  it("focusInOrder：入列 / 移顶 / 幂等", () => {
    expect(focusInOrder([], "history")).toEqual(["history"]);
    expect(focusInOrder(["history"], "gallery")).toEqual(["history", "gallery"]);
    expect(focusInOrder(["history", "gallery"], "history")).toEqual(["gallery", "history"]);
    // 已是最顶：原样返回（同一引用，触发零渲染）
    const top = ["gallery", "history"] as const;
    expect(focusInOrder(top, "history")).toBe(top);
  });

  it("4 面板轮转置顶 50 次：z 集合恒唯一且 ≤ 50", () => {
    const names = ["history", "gallery", "lighting", "director"] as const;
    type P = (typeof names)[number];
    let order: P[] = [];
    for (let i = 0; i < 50; i++) {
      const n = names[i % names.length];
      order = focusInOrder(order, n);
    }
    expect(order).toHaveLength(4);
    const zs = order.map((n, i) => Z_BASE + i);
    const set = new Set(zs);
    expect(set.size).toBe(4);
    expect(Math.max(...zs)).toBeLessThanOrEqual(50);
  });
});

describe("clamp 边界", () => {
  it("水平：INSET 下限 / 右侧留白", () => {
    expect(clampPanelLeft(-100, 1280, 560)).toBe(PANEL_INSET);
    expect(clampPanelLeft(1200, 1280, 560)).toBe(1280 - PANEL_INSET - 560);
  });

  it("垂直：上沿 INSET / 底边不进 dock 保留带", () => {
    expect(clampPanelTop(-50, 800, 300)).toBe(PANEL_INSET);
    expect(clampPanelTop(799, 800, 300)).toBe(800 - DOCK_RESERVE - 300);
  });

  it("小屏兜底：maxY 为负时贴上沿（不产生负 top）", () => {
    // 视口 500 高、面板 460 高：500-64-460 = -24 → maxY=0 → top 夹到 INSET
    expect(clampPanelTop(300, 500, 460)).toBe(PANEL_INSET);
  });

  it("小屏兜底：maxX 为 0 时贴左侧", () => {
    // 视口 596 宽、面板 580：maxX = 596-16-580 = 0 → left 夹到 INSET
    expect(clampPanelLeft(600, 596, 580)).toBe(PANEL_INSET);
  });
});

describe("normalize / denorm roundtrip", () => {
  it("归一化往返无漂移（浮点容差 1e-6）", () => {
    const w = 560;
    const h = 300;
    const vw = 1280;
    const vh = 800;
    for (const [left, top] of [
      [8, 8],
      [400, 200],
      [1280 - 8 - 560, 800 - DOCK_RESERVE - 300],
    ]) {
      const pos = normalizePanelPos(left, top, vw, vh, w, h);
      const back = denormPanelPos(pos, vw, vh, w, h);
      expect(back.left).toBeCloseTo(left, 6);
      expect(back.top).toBeCloseTo(top, 6);
    }
  });

  it("极小视口：比视口宽的分量归 0；够放但拖出界的分量 clamp 到 1", () => {
    // 面板 560 宽 > 视口 300 宽 → x=0；视口 400 高放得下(300)但 top=300 越上界 → y clamp 到 1
    const pos = normalizePanelPos(300, 300, 300, 400, 560, 300);
    expect(pos.x).toBe(0);
    expect(pos.y).toBe(1);
  });
});

describe("store 状态机", () => {
  beforeEach(() => {
    // 状态复位：直接 set 回初始
    useWindowManager.setState({ order: [], minimized: { history: false, gallery: false, lighting: false, director: false } });
  });

  it("minimize → restore：min 翻转 + restore 置顶", () => {
    useWindowManager.getState().focus("history");
    useWindowManager.getState().minimize("history");
    expect(useWindowManager.getState().minimized.history).toBe(true);

    useWindowManager.getState().restore("history");
    const s = useWindowManager.getState();
    expect(s.minimized.history).toBe(false);
    expect(s.order[s.order.length - 1]).toBe("history");
  });

  it("syncOpen(false)：清 minimized + 移出 order", () => {
    useWindowManager.getState().focus("history");
    useWindowManager.getState().minimize("history");
    useWindowManager.getState().syncOpen("history", false);
    const s = useWindowManager.getState();
    expect(s.minimized.history).toBe(false);
    expect(s.order).not.toContain("history");
  });

  it("syncOpen(true)：幂等无副作用（打开由挂载 focus 负责）", () => {
    const before = useWindowManager.getState();
    useWindowManager.getState().syncOpen("history", true);
    expect(useWindowManager.getState()).toBe(before);
  });

  it("focus 幂等：已是最顶不触发更新", () => {
    useWindowManager.getState().focus("history");
    const before = useWindowManager.getState();
    useWindowManager.getState().focus("history");
    expect(useWindowManager.getState()).toBe(before);
  });
});

describe("存储层（node 环境守卫）", () => {
  beforeEach(() => {
    const mem = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => mem.get(k) ?? null,
      setItem: (k: string, v: string) => void mem.set(k, v),
      removeItem: (k: string) => void mem.delete(k),
    });
  });

  it("save → load roundtrip", () => {
    savePanelPos("history", { x: 0.3, y: 0.7 });
    expect(loadPanelPos("history")).toEqual({ x: 0.3, y: 0.7 });
  });

  it("非法 JSON / 非法结构 → null", () => {
    localStorage.setItem("shiguang-canvas:panel-pos:history:v1", "{broken");
    expect(loadPanelPos("history")).toBeNull();
    localStorage.setItem("shiguang-canvas:panel-pos:history:v1", '{"x":"a","y":1}');
    expect(loadPanelPos("history")).toBeNull();
  });

  it("越界值 clamp 到 [0,1]", () => {
    localStorage.setItem("shiguang-canvas:panel-pos:history:v1", '{"x":-2,"y":5}');
    expect(loadPanelPos("history")).toEqual({ x: 0, y: 1 });
  });
});
