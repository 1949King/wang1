/**
 * G4 · 工程依赖清单（2026-11-12）：导出时记录"要装什么"，导入时原样带回。
 */
import { describe, expect, it } from "vitest";

import { collectRequirements } from "./projectZip";

type N = { id: string; type?: string; data?: Record<string, unknown> };

function nodes(list: N[]): Parameters<typeof collectRequirements>[0] {
  return list as unknown as Parameters<typeof collectRequirements>[0];
}

describe("collectRequirements", () => {
  it("收集节点里引用的模型并去重", () => {
    const r = collectRequirements(nodes([
      { id: "a", type: "image", data: { kind: "image", imageModel: "local::sd15" } },
      { id: "b", type: "image", data: { kind: "image", imageModel: "local::sd15" } },
      { id: "c", type: "video", data: { kind: "video", videoModel: "local::svd" } },
    ]));
    expect(r.models.sort()).toEqual(["local::sd15", "local::svd"]);
    expect(r.schema).toBe(1);
    expect(r.app).toBe("shiguang");
  });

  it("识别 ComfyUI 与 3D 依赖并写进 notes", () => {
    const r = collectRequirements(nodes([
      { id: "x", type: "image", data: { kind: "image", comfyWorkflow: { nodes: [] } } },
      { id: "y", type: "stage3d", data: { kind: "stage3d", stage3d: {} } },
    ]));
    expect(r.engines).toContain("comfyui");
    expect(r.engines).toContain("three.js");
    expect(r.notes.join(" ")).toContain("ComfyUI");
  });

  it("没有模型引用时给出诚实提示（不假装齐备）", () => {
    const r = collectRequirements(nodes([{ id: "t", type: "text", data: { kind: "text" } }]));
    expect(r.models).toEqual([]);
    expect(r.notes.join(" ")).toContain("未记录模型引用");
  });
});
