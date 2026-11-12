/**
 * G5 · 首屏三预设（2026-11-12）：结构自洽 + kind 非空。
 */
import { describe, expect, it } from "vitest";

import { STARTER_PRESETS, getPreset, validateSpec } from "./firstRun";

describe("首屏预设", () => {
  it("三条预设结构都自洽（key 唯一、边两端存在、kind 非空）", () => {
    for (const p of STARTER_PRESETS) {
      expect(validateSpec(p.build("测试主题"))).toEqual([]);
    }
  });

  it("预设覆盖三类产出且有链路", () => {
    const ids = STARTER_PRESETS.map((p) => p.id);
    expect(ids).toEqual(["drama", "talk", "product"]);
    for (const p of STARTER_PRESETS) {
      const spec = p.build("一个外卖员在雨夜捡到会说话的猫");
      expect(spec.nodes.length).toBeGreaterThanOrEqual(4);
      expect(spec.edges.length).toBeGreaterThanOrEqual(3);
      expect(spec.goal).toContain("外卖员");
    }
  });

  it("getPreset 回落到第一条", () => {
    expect(getPreset("nope").id).toBe(STARTER_PRESETS[0].id);
  });
});
