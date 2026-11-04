/**
 * 蓝图落图单测（2026-10-31）。
 *
 * 验证「蓝图 → 画布」这条链路的**语义**，不碰真实 store：
 *  建节点 → 写 data（正文落到正确字段）→ 连线。
 */
import { describe, expect, it } from "vitest";
import { applyBlueprint, blueprintTextField, blueprintNodePatch } from "./applyBlueprint";
import type { BlueprintSpec } from "./blueprintLayout";

function makeDeps() {
  const created: Array<{ id: string; kind: string; pos: { x: number; y: number } }> = [];
  const patches: Array<{ id: string; patch: Record<string, unknown> }> = [];
  const connects: Array<{ source: string; target: string }> = [];
  let seq = 0;
  return {
    created,
    patches,
    connects,
    deps: {
      addNode: (kind: string, pos: { x: number; y: number }) => {
        const id = `id_${++seq}`;
        created.push({ id, kind, pos });
        return id;
      },
      updateNodeData: (id: string, patch: Record<string, unknown>) => {
        patches.push({ id, patch });
      },
      onConnect: (c: { source: string; target: string }) => {
        connects.push(c);
      },
    },
  };
}

describe("blueprintTextField 正文落点", () => {
  it("按 kind 落到正确字段（同名不同义坑）", () => {
    expect(blueprintTextField("script")).toBe("content");
    expect(blueprintTextField("text")).toBe("content");
    expect(blueprintTextField("markdown")).toBe("content");
    expect(blueprintTextField("note")).toBe("content");
    expect(blueprintTextField("prompt")).toBe("text");
    expect(blueprintTextField("shot")).toBe("prompt");
    expect(blueprintTextField("image")).toBe("prompt");
    expect(blueprintTextField("video")).toBe("prompt");
  });
});

describe("blueprintNodePatch", () => {
  it("标题 + 正文 + 意图 + 自由字段", () => {
    const p = blueprintNodePatch({
      key: "a",
      kind: "shot",
      title: "镜头 1",
      prompt: "中景推门",
      intent: "开场",
      data: { duration: 3 },
    });
    expect(p.title).toBe("镜头 1");
    expect(p.prompt).toBe("中景推门");
    expect(p.intent).toBe("开场");
    expect(p.duration).toBe(3);
  });

  it("空字段不写入（不覆盖默认值）", () => {
    const p = blueprintNodePatch({ key: "a", kind: "shot" });
    expect(Object.keys(p)).toHaveLength(0);
  });
});

describe("applyBlueprint 落图", () => {
  const SPEC: BlueprintSpec = {
    goal: "完整漫剧流程",
    nodes: [
      { key: "n1", kind: "script", title: "剧本", prompt: "第一场" },
      { key: "n2", kind: "directorCard", title: "导演卡" },
      { key: "n3", kind: "shot", title: "镜头", prompt: "中景" },
      { key: "n4", kind: "image", title: "画面", prompt: "少女推门" },
      { key: "n5", kind: "video", title: "片段", prompt: "推进" },
    ],
    edges: [
      { from: "n1", to: "n2" },
      { from: "n2", to: "n3" },
      { from: "n3", to: "n4" },
      { from: "n4", to: "n5" },
    ],
  };

  it("一次建出全部节点 + 全部连线（不是 1~3 张）", () => {
    const { created, connects, deps } = makeDeps();
    const r = applyBlueprint(SPEC, deps);
    expect(r.ok).toBe(true);
    expect(created).toHaveLength(5);
    expect(r.nodeIds).toHaveLength(5);
    expect(connects).toHaveLength(4);
    expect(r.edgesApplied).toBe(4);
  });

  it("连线引用真实节点 id（不是蓝图 key）", () => {
    const { created, connects, deps } = makeDeps();
    applyBlueprint(SPEC, deps);
    const ids = new Set(created.map((c) => c.id));
    for (const c of connects) {
      expect(ids.has(c.source)).toBe(true);
      expect(ids.has(c.target)).toBe(true);
    }
  });

  it("正文写进正确字段：script→content，shot→prompt", () => {
    const { patches, deps } = makeDeps();
    applyBlueprint(SPEC, deps);
    const scriptPatch = patches.find((p) => p.patch.content === "第一场");
    const shotPatch = patches.find((p) => p.patch.prompt === "中景");
    expect(scriptPatch).toBeTruthy();
    expect(shotPatch).toBeTruthy();
  });

  it("坐标规整：相邻层 x 递增、层内不叠压", () => {
    const { created, deps } = makeDeps();
    applyBlueprint(SPEC, deps);
    const xs = created.map((c) => c.pos.x);
    expect(new Set(xs).size).toBe(5); // 5 层 ⇒ 5 个不同 x
    for (let i = 0; i < created.length; i++) {
      for (let j = i + 1; j < created.length; j++) {
        const dx = Math.abs(created[i].pos.x - created[j].pos.x);
        const dy = Math.abs(created[i].pos.y - created[j].pos.y);
        expect(dx >= 270 || dy >= 207).toBe(true);
      }
    }
  });

  it("成环蓝图：环边被剔除 ⇒ 画布上仍是 DAG", () => {
    const { connects, deps } = makeDeps();
    const r = applyBlueprint(
      {
        nodes: [
          { key: "a", kind: "script" },
          { key: "b", kind: "shot" },
        ],
        edges: [
          { from: "a", to: "b" },
          { from: "b", to: "a" },
        ],
      },
      deps,
    );
    expect(connects.length).toBeLessThanOrEqual(1);
    expect(r.problems.join()).toContain("成环");
  });

  it("建节点失败：如实报告，不假装成功", () => {
    const { deps } = makeDeps();
    const broken = { ...deps, addNode: () => undefined };
    const r = applyBlueprint(SPEC, broken);
    expect(r.ok).toBe(false);
    expect(r.problems.join()).toContain("创建失败");
  });
});
