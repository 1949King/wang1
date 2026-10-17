/**
 * upstreamRefs.test.ts — 「连线上游素材引用」回归（2026-10-06）。
 *
 * 这个功能会**往用户节点里写数据**，所以安全规则必须逐条钉死：
 *  ① 默认关（没同意就不动）
 *  ② **绝不覆盖用户自己设的首帧**（只在空的时候写）
 *  ③ 连线断开**只清我们写过的那条**（靠 `refUpstreamOf` 标记对称撤销）
 *  ④ 幂等收敛（apply 完再算必须是空补丁，否则会自激刷爆 store）
 */
import { describe, expect, it } from "vitest";

import { planUpstreamRefs, REF_MARK } from "./upstreamRefs";

const N = (id: string, data: Record<string, unknown>) => ({ id, data });
const E = (source: string, target: string) => ({ source, target });

function apply(nodes: ReturnType<typeof N>[], patches: ReturnType<typeof planUpstreamRefs>) {
  return nodes.map((n) => {
    const p = patches.find((x) => x.id === n.id);
    return p ? { ...n, data: { ...n.data, ...p.patch } } : n;
  });
}

describe("开关与前置条件", () => {
  it("默认关 ⇒ 一个补丁都不出（不在用户没同意时改节点）", () => {
    const nodes = [N("a", { kind: "image", imageUrl: "u1" }), N("b", { kind: "video" })];
    expect(planUpstreamRefs(nodes, [E("a", "b")], { enabled: false })).toEqual([]);
  });

  it("上游还没产物 ⇒ 什么都不做（等它生成完再连）", () => {
    const nodes = [N("a", { kind: "image" }), N("b", { kind: "video" })];
    expect(planUpstreamRefs(nodes, [E("a", "b")], { enabled: true })).toEqual([]);
  });

  it("下游不是可引用类型（如文本/分组）⇒ 不写", () => {
    const nodes = [N("a", { kind: "image", imageUrl: "u1" }), N("t", { kind: "text", prompt: "x" })];
    expect(planUpstreamRefs(nodes, [E("a", "t")], { enabled: true })).toEqual([]);
  });

  it("自环忽略", () => {
    const nodes = [N("a", { kind: "image", imageUrl: "u1" })];
    expect(planUpstreamRefs(nodes, [E("a", "a")], { enabled: true })).toEqual([]);
  });
});

describe("写入（真实引用通道）", () => {
  it("下游首帧为空 ⇒ 写入上游产物并打标记", () => {
    const nodes = [N("a", { kind: "image", imageUrl: "u1" }), N("b", { kind: "video" })];
    expect(planUpstreamRefs(nodes, [E("a", "b")], { enabled: true })).toEqual([
      { id: "b", patch: { firstFrameUrl: "u1", [REF_MARK]: "a" } },
    ]);
  });

  it("★ 绝不覆盖用户自己设的首帧（没有我们的标记就跳过）", () => {
    const nodes = [
      N("a", { kind: "image", imageUrl: "u1" }),
      N("b", { kind: "video", firstFrameUrl: "user-frame.png" }),
    ];
    expect(planUpstreamRefs(nodes, [E("a", "b")], { enabled: true })).toEqual([]);
  });

  it("上游是视频节点时取封面/成片作为引用", () => {
    const nodes = [N("a", { kind: "video", posterUrl: "p.png" }), N("b", { kind: "shot" })];
    expect(planUpstreamRefs(nodes, [E("a", "b")], { enabled: true })[0].patch.firstFrameUrl).toBe("p.png");
  });

  it("多条上游 ⇒ 以第一条有效边为准（稳定可预期）", () => {
    const nodes = [
      N("a", { kind: "image", imageUrl: "u1" }),
      N("c", { kind: "image", imageUrl: "u2" }),
      N("b", { kind: "video" }),
    ];
    const p = planUpstreamRefs(nodes, [E("a", "b"), E("c", "b")], { enabled: true });
    expect(p[0].patch.firstFrameUrl).toBe("u1");
  });
});

describe("撤销（对称清理）", () => {
  it("连线断开且是我们写的 ⇒ 清掉首帧与标记", () => {
    const nodes = [
      N("a", { kind: "image", imageUrl: "u1" }),
      N("b", { kind: "video", firstFrameUrl: "u1", [REF_MARK]: "a" }),
    ];
    expect(planUpstreamRefs(nodes, [], { enabled: true })).toEqual([
      { id: "b", patch: { firstFrameUrl: "", [REF_MARK]: "" } },
    ]);
  });

  it("★ 用户自己设的首帧（无标记）断线后**不动**", () => {
    const nodes = [N("b", { kind: "video", firstFrameUrl: "user-frame.png" })];
    expect(planUpstreamRefs(nodes, [], { enabled: true })).toEqual([]);
  });

  it("有标记但首帧已空 ⇒ 只清标记", () => {
    const nodes = [N("b", { kind: "video", [REF_MARK]: "a" })];
    expect(planUpstreamRefs(nodes, [], { enabled: true })).toEqual([
      { id: "b", patch: { [REF_MARK]: "" } },
    ]);
  });
});

describe("幂等收敛（防自激）", () => {
  it("apply 之后再算 ⇒ 空补丁", () => {
    const nodes = [N("a", { kind: "image", imageUrl: "u1" }), N("b", { kind: "video" })];
    const edges = [E("a", "b")];
    const p1 = planUpstreamRefs(nodes, edges, { enabled: true });
    expect(p1).toHaveLength(1);
    const after = apply(nodes, p1);
    expect(planUpstreamRefs(after, edges, { enabled: true })).toEqual([]);
  });

  it("撤销后也已收敛", () => {
    const nodes = [
      N("a", { kind: "image", imageUrl: "u1" }),
      N("b", { kind: "video", firstFrameUrl: "u1", [REF_MARK]: "a" }),
    ];
    const p = planUpstreamRefs(nodes, [], { enabled: true });
    const after = apply(nodes, p);
    expect(planUpstreamRefs(after, [], { enabled: true })).toEqual([]);
  });

  it("空输入不炸", () => {
    expect(planUpstreamRefs([], [], { enabled: true })).toEqual([]);
    expect(planUpstreamRefs(undefined as never, undefined as never, { enabled: true })).toEqual([]);
  });
});
