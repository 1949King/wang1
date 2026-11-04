/**
 * 配方纯逻辑层单测（2026-10-19）
 * ==============================
 * 只测 `recipePure.ts`（零依赖），不加载 store/three/react-flow。
 * 期望值全部从实现推导，不凭直觉。
 */
import { describe, expect, it } from "vitest";
import {
  canExtract,
  matchRecipeIn,
  nextOriginFrom,
  paramsFromNode,
  recipeSummary,
  skeletonFromNodes,
  type NodeLike,
  type Recipe,
} from "./recipePure";

const node = (
  id: string,
  kind: string,
  x: number,
  y: number,
  data: Record<string, unknown> = {},
): NodeLike => ({
  id,
  type: "canvasNode",
  position: { x, y },
  data: { kind, ...data },
});

describe("skeletonFromNodes：只取 kind 与相对坐标", () => {
  it("以左上角为原点", () => {
    const s = skeletonFromNodes([
      node("a", "image", 300, 500),
      node("b", "video", 420, 560),
    ]);
    expect(s).toEqual([
      { kind: "image", dx: 0, dy: 0 },
      { kind: "video", dx: 120, dy: 60 },
    ]);
  });

  it("空集返回空数组", () => {
    expect(skeletonFromNodes([])).toEqual([]);
  });

  it("data.kind 缺失时回落 node.type", () => {
    const n: NodeLike = { id: "x", type: "customType", position: { x: 0, y: 0 }, data: {} };
    expect(skeletonFromNodes([n])[0].kind).toBe("customType");
  });

  it("完全无 kind/type 时兜底 image", () => {
    const n: NodeLike = { id: "x", position: { x: 0, y: 0 } };
    expect(skeletonFromNodes([n])[0].kind).toBe("image");
  });
});

describe("paramsFromNode：白名单过滤", () => {
  it("只保留白名单字段", () => {
    const p = paramsFromNode(
      node("a", "image", 0, 0, {
        prompt: "电影感",
        quality: "fine",
        stack: [{ url: "x" }],
        status: "done",
      }),
    );
    expect(p).toEqual({ prompt: "电影感", quality: "fine" });
    expect("stack" in p).toBe(false);
    expect("status" in p).toBe(false);
  });

  it("无 data 返回空对象", () => {
    expect(paramsFromNode(undefined)).toEqual({});
  });
});

describe("canExtract", () => {
  it("空集不可提炼", () => expect(canExtract([])).toBe(false));
  it("有节点可提炼", () => expect(canExtract([node("a", "image", 0, 0)])).toBe(true));
});

describe("nextOriginFrom：不重叠落点", () => {
  it("空画布给默认原点", () => {
    expect(nextOriginFrom([])).toEqual({ x: 120, y: 120 });
  });

  it("放在最右列 +340", () => {
    expect(nextOriginFrom([{ x: 100, y: 50 }, { x: 420, y: 90 }])).toEqual({ x: 760, y: 50 });
  });
});

const mkRecipe = (over: Partial<Recipe> = {}): Recipe => ({
  id: "r1",
  name: "定妆照",
  createdAt: "2026-10-19T00:00:00Z",
  intent: { stage: "frame", kind: "image", goal: "电影感定妆照" },
  params: {},
  masters: {},
  skeleton: { nodes: [{ kind: "image", dx: 0, dy: 0 }] },
  stats: { uses: 0 },
  ...over,
});

describe("matchRecipeIn：关键词打分", () => {
  it("整句包含 → 命中", () => {
    expect(matchRecipeIn([mkRecipe()], "电影感定妆照")?.id).toBe("r1");
  });

  it("两字以上 token 命中 → 命中", () => {
    expect(matchRecipeIn([mkRecipe()], "来一张定妆")?.id).toBe("r1");
  });

  it("阶段词加成（说「画面」偏 frame）", () => {
    const audio = mkRecipe({
      id: "r2",
      name: "配音",
      intent: { stage: "audio", kind: "audio", goal: "配一句台词" },
    });
    // 「画面」不在 r2 文本里，但 frame 配方会 +2；两者都不到 3 分 ⇒ null
    const hit = matchRecipeIn([audio], "画面");
    expect(hit).toBeNull();
  });

  it("完全不相关 → null（诚实失败，不硬配）", () => {
    expect(matchRecipeIn([mkRecipe()], "量子物理")).toBeNull();
  });

  it("空输入 / 空库 → null", () => {
    expect(matchRecipeIn([mkRecipe()], "")).toBeNull();
    expect(matchRecipeIn([], "定妆照")).toBeNull();
  });

  it("多个候选取分最高", () => {
    const a = mkRecipe({ id: "a", intent: { stage: "frame", kind: "image", goal: "定妆照" } });
    const b = mkRecipe({ id: "b", intent: { stage: "frame", kind: "image", goal: "定妆照 电影感 暖色" } });
    expect(matchRecipeIn([a, b], "电影感")?.id).toBe("b");
  });
});

describe("recipeSummary", () => {
  it("带 goal / 卡数 / 次数", () => {
    expect(recipeSummary(mkRecipe({ stats: { uses: 7 } }))).toBe("电影感定妆照 · 1 张卡 · 用过 7 次");
  });

  it("无 goal 时回落 name", () => {
    const r = mkRecipe({ intent: { stage: "frame", kind: "image", goal: "" } });
    expect(recipeSummary(r)).toBe("定妆照 · 1 张卡 · 用过 0 次");
  });
});
