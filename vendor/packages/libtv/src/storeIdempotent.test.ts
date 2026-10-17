/**
 * storeIdempotent.test.ts — 幂等守卫的回归锚点（2026-10-14，React #185 根因修复）。
 *
 * 为什么只测纯函数
 * ================
 * 本项目 vitest 是 **node 环境无 jsdom**（见 vitest.config.ts），useEffect 逻辑零覆盖
 * （既有纪律）。store.ts / CanvasOverlays.tsx 里真正要防的是「effect→set→重渲染」闭环，
 * 组件层在 node 环境跑不起来；因此判定逻辑必须抽成纯函数，这里对**判定本身**逐条锁死。
 *
 * 覆盖三块：
 *   ① nodeDataPatchIsNoop —— updateNodeData 的守卫语义（含 undefined vs 键缺失）
 *   ② bondedSidesEqual    —— setBondedSides 的守卫语义（内容相等、引用可不同）
 *   ③ syncOpen 幂等       —— windowManager 重复 close 同一面板时引用不变（vanilla store，node 可用）
 */
import { beforeEach, describe, expect, it } from "vitest";

import { bondedSidesEqual, nodeDataPatchIsNoop } from "./storeIdempotent";
import { useWindowManager, type PanelName } from "./windowManager";

/* ────────────── ① nodeDataPatchIsNoop ────────────── */

describe("nodeDataPatchIsNoop（updateNodeData 守卫）", () => {
  it("同值 patch（逐键相同）⇒ 空转", () => {
    const data = { title: "A", score: 7, tags: ["x"] };
    expect(nodeDataPatchIsNoop(data, { title: "A" })).toBe(true);
    expect(nodeDataPatchIsNoop(data, { title: "A", score: 7 })).toBe(true);
  });

  it("空 patch ⇒ 空转", () => {
    expect(nodeDataPatchIsNoop({ a: 1 }, {})).toBe(true);
  });

  it("异值 patch ⇒ 不空转", () => {
    const data = { title: "A", score: 7 };
    expect(nodeDataPatchIsNoop(data, { title: "B" })).toBe(false);
    expect(nodeDataPatchIsNoop(data, { score: 8 })).toBe(false);
    expect(nodeDataPatchIsNoop(data, { title: "A", score: 8 })).toBe(false);
  });

  it("新增键 ⇒ 不空转（键原本不存在）", () => {
    expect(nodeDataPatchIsNoop({ a: 1 }, { b: 2 })).toBe(false);
    // 多键 patch 中只要一键是新增 ⇒ 整体不空转
    expect(nodeDataPatchIsNoop({ a: 1 }, { a: 1, b: 2 })).toBe(false);
  });

  it("删不了键：patch 无法表达删除（与展开语义一致，恒不空转判定）", () => {
    // {...data, ...patch} 只增不删，所以「data 有、patch 没有」不构成变化
    expect(nodeDataPatchIsNoop({ a: 1, b: 2 }, { a: 1 })).toBe(true);
  });

  describe("undefined 值 vs 键缺失（展开语义的红线）", () => {
    it("键已存在且值为 undefined + patch 给 undefined ⇒ 空转", () => {
      const data: Record<string, unknown> = { a: undefined };
      // {...data} 里 a 是自有键（值为 undefined），再展开 k:undefined 结果一致
      expect(nodeDataPatchIsNoop(data, { a: undefined })).toBe(true);
      expect({ ...data }).toHaveProperty("a");
    });

    it("键不存在 + patch 给 undefined ⇒ 不空转（展开会显式新增该键）", () => {
      const data: Record<string, unknown> = {};
      expect(nodeDataPatchIsNoop(data, { a: undefined })).toBe(false);
      // 关键差异：展开结果多了一个「自有但值为 undefined」的键
      expect(Object.keys({ ...data, ...{ a: undefined } })).toEqual(["a"]);
      expect(Object.keys({ ...data })).toEqual([]);
    });

    it("键不存在但原型链上有同名键 ⇒ 仍判不空转（展开只复制自有可枚举键）", () => {
      // 用 `k in data` 判定会误判成空转 ⇒ 漏写；故实现用 hasOwnProperty。
      const data: Record<string, unknown> = Object.create({ a: undefined });
      expect(nodeDataPatchIsNoop(data, { a: undefined })).toBe(false);
      expect(Object.keys({ ...data, ...{ a: undefined } })).toEqual(["a"]);
    });

    it("键存在为 undefined，被 patch 赋真值 ⇒ 不空转", () => {
      expect(nodeDataPatchIsNoop({ a: undefined }, { a: 1 })).toBe(false);
    });
  });

  it("NaN：Object.is 语义 ⇒ NaN→NaN 判为空转（与展开结果一致）", () => {
    expect(nodeDataPatchIsNoop({ a: NaN }, { a: NaN })).toBe(true);
    expect(Number.isNaN(NaN)).toBe(true);
  });

  it("0 / -0：按 Object.is 区分（-0 与 0 不相等 ⇒ 不空转）", () => {
    expect(nodeDataPatchIsNoop({ a: 0 }, { a: -0 })).toBe(false);
    expect(nodeDataPatchIsNoop({ a: -0 }, { a: -0 })).toBe(true);
  });

  it("引用不同但内容相同的对象/数组 ⇒ 不空转（展开确实换了引用）", () => {
    expect(nodeDataPatchIsNoop({ a: { x: 1 } }, { a: { x: 1 } })).toBe(false);
    expect(nodeDataPatchIsNoop({ a: [1, 2] }, { a: [1, 2] })).toBe(false);
  });

  it("对 null / undefined 的 data 容错（不炸，按空对象判）", () => {
    expect(nodeDataPatchIsNoop(null, { a: 1 })).toBe(false);
    expect(nodeDataPatchIsNoop(undefined, {})).toBe(true);
  });
});

/* ────────────── ② bondedSidesEqual ────────────── */

describe("bondedSidesEqual（setBondedSides 守卫）", () => {
  it("相同内容、不同引用 ⇒ 相等（这正是闭环的根：引用必变但内容不变）", () => {
    const a = { n1: ["left"] as never[], n2: ["top", "right"] as never[] };
    const b = { n1: ["left"] as never[], n2: ["top", "right"] as never[] };
    expect(a).not.toBe(b); // 引用确实不同（bondedSidesMap 每次新建对象）
    expect(bondedSidesEqual(a, b)).toBe(true);
  });

  it("空 map vs 空 map ⇒ 相等", () => {
    expect(bondedSidesEqual({}, {})).toBe(true);
  });

  it("key 数不同 ⇒ 不等", () => {
    expect(bondedSidesEqual({}, { n1: ["left"] as never[] })).toBe(false);
    expect(bondedSidesEqual({ n1: ["left"] as never[] }, {})).toBe(false);
    expect(bondedSidesEqual({ n1: [] as never[] }, { n1: [], n2: [] })).toBe(false);
  });

  it("同 key 不同值 ⇒ 不等", () => {
    expect(bondedSidesEqual({ n1: ["left"] as never[] }, { n1: ["right"] as never[] })).toBe(false);
  });

  it("同 key 同值但 key 集合不同 ⇒ 不等", () => {
    expect(bondedSidesEqual({ n1: ["left"] as never[] }, { n2: ["left"] as never[] })).toBe(false);
  });

  it("同 key 数组元素数不同 ⇒ 不等", () => {
    expect(bondedSidesEqual({ n1: ["left"] as never[] }, { n1: ["left", "top"] as never[] })).toBe(false);
  });

  it("空数组 vs 同 key 空数组 ⇒ 相等", () => {
    expect(bondedSidesEqual({ n1: [] as never[] }, { n1: [] as never[] })).toBe(true);
  });

  it("key 顺序无关（按 key 比，不按枚举序比）", () => {
    const a = { n1: ["left"] as never[], n2: ["top"] as never[] };
    const b = { n2: ["top"] as never[], n1: ["left"] as never[] };
    expect(bondedSidesEqual(a, b)).toBe(true);
  });

  it("数组顺序敏感（保守：顺序不同判不等，宁多写一次不漏写）", () => {
    const a = { n1: ["top", "left"] as never[] };
    const b = { n1: ["left", "top"] as never[] };
    expect(bondedSidesEqual(a, b)).toBe(false);
  });

  it("null / undefined 容错：与空 map 等价", () => {
    expect(bondedSidesEqual(null, {})).toBe(true);
    expect(bondedSidesEqual(undefined, undefined)).toBe(true);
    expect(bondedSidesEqual(null, { n1: ["left"] as never[] })).toBe(false);
  });
});

/* ────────────── ③ syncOpen 幂等（直测真store，node 环境不碰 DOM） ────────────── */

/**
 * 直接用**真的** `useWindowManager`（不是复刻）：zustand 的 `create` 不碰 DOM，
 * 既有 `windowManager.test.ts` 已在 node 环境跑通同一路径。这里测的是被改过的那段
 * `syncOpen` 本体——复刻只能证明复刻是对的，证明不了线上代码。
 * 断言点：重复 close 同一面板后，`minimized` / `order` 引用不再变（订阅者零额外通知）。
 */
describe("syncOpen 幂等（重复 close 同一面板，引用不再变）", () => {
  beforeEach(() => {
    // 状态复位：直接 set 回初始（与既有 windowManager.test.ts 同款）
    useWindowManager.setState({
      order: [],
      minimized: { history: false, gallery: false, lighting: false, director: false, generate: false },
    });
  });

  it("已在关闭态时重复 close：state / minimized / order 引用全部不变", () => {
    useWindowManager.getState().syncOpen("history", false); // 第一次：已是关闭态
    const s1 = useWindowManager.getState();
    useWindowManager.getState().syncOpen("history", false); // 第二次：空转
    const s2 = useWindowManager.getState();
    expect(s2).toBe(s1);
    expect(s2.minimized).toBe(s1.minimized);
    expect(s2.order).toBe(s1.order);
  });

  it("先 focus 入列 → close 生效（order 被清、minimized 复位）", () => {
    useWindowManager.setState({ order: ["history", "gallery"] });
    useWindowManager.getState().syncOpen("history", false);
    const s = useWindowManager.getState();
    expect(s.order).toEqual(["gallery"]);
    expect(s.minimized.history).toBe(false);
  });

  it("「在层叠序里」close 一次后，再 close 不再产生新引用", () => {
    useWindowManager.setState({ order: ["history", "gallery"] });
    useWindowManager.getState().syncOpen("history", false); // 有变化：真的写
    const after = useWindowManager.getState();
    useWindowManager.getState().syncOpen("history", false); // 无变化：空转
    expect(useWindowManager.getState()).toBe(after);
    expect(useWindowManager.getState().order).toBe(after.order);
    expect(useWindowManager.getState().minimized).toBe(after.minimized);
  });

  it("最小化态下 close：先清 minimized 再空转（第一拍必写，第二拍不写）", () => {
    useWindowManager.getState().focus("history");
    useWindowManager.getState().minimize("history");
    useWindowManager.getState().syncOpen("history", false); // 取消最小化：真的写
    const s1 = useWindowManager.getState();
    expect(s1.minimized.history).toBe(false);
    expect(s1.order).not.toContain("history");

    useWindowManager.getState().syncOpen("history", false); // 空转
    expect(useWindowManager.getState()).toBe(s1);
    expect(useWindowManager.getState().minimized).toBe(s1.minimized);
    expect(useWindowManager.getState().order).toBe(s1.order);
  });

  it("open=true 分支恒不 set（打开由挂载 focus 负责）", () => {
    const before = useWindowManager.getState();
    useWindowManager.getState().syncOpen("history", true);
    useWindowManager.getState().syncOpen("gallery", true);
    expect(useWindowManager.getState()).toBe(before);
  });

  it("连续 close 5 个面板：首次各自生效，之后全空转（订阅者零额外通知）", () => {
    const names: PanelName[] = ["history", "gallery", "lighting", "director", "generate"];
    useWindowManager.setState({ order: [...names] });
    for (const n of names) useWindowManager.getState().syncOpen(n, false);
    const drained = useWindowManager.getState();
    expect(drained.order).toEqual([]);
    // 再来一轮：状态已完全排空，引用一律不变
    for (const n of names) useWindowManager.getState().syncOpen(n, false);
    const s = useWindowManager.getState();
    expect(s).toBe(drained);
    expect(s.order).toBe(drained.order);
    expect(s.minimized).toBe(drained.minimized);
  });
});
