/**
 * 蓝图布局引擎单测（2026-10-31 · 修「Agent 只会摆 1~3 张随机卡片」）。
 *
 * 判据对应用户实锤的三个症状：
 *  ① 能不能一次铺出**完整 DAG**（多节点 + 多连线，不是 1~3 张）；
 *  ② 摆放**规整**（分层对齐、不叠压、坐标可预期）；
 *  ③ **确定性**（同输入恒同输出，绝不随机）。
 */
import { describe, expect, it } from "vitest";
import {
  BLUEPRINT_ORIGIN,
  BLUEPRINT_STEP,
  layoutBlueprint,
  type BlueprintSpec,
} from "./blueprintLayout";

/** 一条典型的「剧本 → 成片」完整链。 */
const FULL: BlueprintSpec = {
  goal: "做一集 60 秒漫剧",
  nodes: [
    { key: "n1", kind: "script", title: "剧本", prompt: "第一场：主角登场" },
    { key: "n2", kind: "directorCard", title: "导演卡" },
    { key: "n3", kind: "shot", title: "镜头 1", prompt: "中景，主角推门" },
    { key: "n4", kind: "image", title: "画面", prompt: "二次元少女推门" },
    { key: "n5", kind: "video", title: "片段", prompt: "推门推进" },
    { key: "n6", kind: "shotlist", title: "分镜表" },
    { key: "n7", kind: "codeVideo", title: "成片" },
  ],
  edges: [
    { from: "n1", to: "n2" },
    { from: "n2", to: "n3" },
    { from: "n3", to: "n4" },
    { from: "n4", to: "n5" },
    { from: "n5", to: "n6" },
    { from: "n6", to: "n7" },
  ],
};

describe("layoutBlueprint 分层", () => {
  it("完整链：7 节点 6 连线全部落地（一次铺出完整流程，不是 1~3 张）", () => {
    const r = layoutBlueprint(FULL);
    expect(r.nodes).toHaveLength(7);
    expect(r.edges).toHaveLength(6);
    expect(r.problems).toEqual([]);
  });

  it("链式图：层号严格递增 ⇒ x 递增 ⇒ 从左到右成流程", () => {
    const r = layoutBlueprint(FULL);
    const byKey = new Map(r.nodes.map((n) => [n.key, n]));
    expect(byKey.get("n1")!.layer).toBe(0);
    expect(byKey.get("n7")!.layer).toBe(6);
    for (const e of r.edges) {
      const s = byKey.get(e.from)!;
      const t = byKey.get(e.to)!;
      expect(t.layer).toBeGreaterThan(s.layer);
      expect(t.x).toBeGreaterThan(s.x);
    }
  });

  it("坐标规整：同一层的节点 x 相同、y 间隔恰好一个步长", () => {
    const r = layoutBlueprint({
      nodes: [
        { key: "a", kind: "script" },
        { key: "b", kind: "shot" },
        { key: "c", kind: "image" },
      ],
      edges: [
        { from: "a", to: "b" },
        { from: "a", to: "c" },
      ],
    });
    const b = r.nodes.find((n) => n.key === "b")!;
    const c = r.nodes.find((n) => n.key === "c")!;
    expect(b.layer).toBe(c.layer);
    expect(b.x).toBe(c.x);
    expect(Math.abs(b.y - c.y)).toBeCloseTo(BLUEPRINT_STEP.y, 6);
  });

  it("不叠压：任意两节点的坐标至少一个轴分开 ≥ 步长的 0.9 倍", () => {
    const r = layoutBlueprint(FULL);
    for (let i = 0; i < r.nodes.length; i++) {
      for (let j = i + 1; j < r.nodes.length; j++) {
        const dx = Math.abs(r.nodes[i].x - r.nodes[j].x);
        const dy = Math.abs(r.nodes[i].y - r.nodes[j].y);
        expect(dx >= BLUEPRINT_STEP.x * 0.9 || dy >= BLUEPRINT_STEP.y * 0.9).toBe(true);
      }
    }
  });

  it("起点与手工网格同源（视觉密度一致）", () => {
    const r = layoutBlueprint(FULL);
    const first = r.nodes.find((n) => n.layer === 0)!;
    expect(first.x).toBe(BLUEPRINT_ORIGIN.x);
  });

  it("确定性：同输入恒同输出（无随机、无时间戳）", () => {
    const a = layoutBlueprint(FULL);
    const b = layoutBlueprint(FULL);
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });
});

describe("layoutBlueprint 校验与降级", () => {
  it("空蓝图：如实报告，不抛异常", () => {
    const r = layoutBlueprint({ nodes: [], edges: [] });
    expect(r.nodes).toHaveLength(0);
    expect(r.problems.join()).toContain("没有节点");
  });

  it("重复 key：保留第一个并如实报告", () => {
    const r = layoutBlueprint({
      nodes: [
        { key: "a", kind: "script" },
        { key: "a", kind: "shot" },
      ],
      edges: [],
    });
    expect(r.nodes).toHaveLength(1);
    expect(r.problems.join()).toContain("重复");
  });

  it("悬空边：忽略并如实报告", () => {
    const r = layoutBlueprint({
      nodes: [{ key: "a", kind: "script" }],
      edges: [{ from: "a", to: "ghost" }],
    });
    expect(r.edges).toHaveLength(0);
    expect(r.problems.join()).toContain("悬空");
  });

  it("成环：剔除环边 ⇒ 落地的仍是 DAG（执行器要求无环）", () => {
    const r = layoutBlueprint({
      nodes: [
        { key: "a", kind: "script" },
        { key: "b", kind: "shot" },
        { key: "c", kind: "image" },
      ],
      edges: [
        { from: "a", to: "b" },
        { from: "b", to: "c" },
        { from: "c", to: "a" },
      ],
    });
    expect(r.problems.join()).toContain("成环");
    // 剩余边必须无环：层号严格递增
    const layerOf = new Map(r.nodes.map((n) => [n.key, n.layer]));
    for (const e of r.edges) {
      expect(layerOf.get(e.to)!).toBeGreaterThan(layerOf.get(e.from)!);
    }
  });

  it("自环：忽略并如实报告", () => {
    const r = layoutBlueprint({
      nodes: [{ key: "a", kind: "script" }],
      edges: [{ from: "a", to: "a" }],
    });
    expect(r.edges).toHaveLength(0);
    expect(r.problems.join()).toContain("自环");
  });
});
