import { describe, expect, it } from "vitest";

import { biasMode, biasModeHint, biasModeLabel } from "./executionBias";

describe("executionBias（三档边界与文案）", () => {
  it("边界与 compute_bias 一致：≤24 本地 / 25-74 混合 / ≥75 云端", () => {
    expect(biasMode(0)).toBe("local");
    expect(biasMode(24)).toBe("local");
    expect(biasMode(25)).toBe("engine");
    expect(biasMode(50)).toBe("engine");
    expect(biasMode(74)).toBe("engine");
    expect(biasMode(75)).toBe("cloud");
    expect(biasMode(100)).toBe("cloud");
  });

  it("非法值回落动态混合（不抛错）", () => {
    expect(biasMode(Number.NaN)).toBe("engine");
  });

  it("文案：三档都有标签与说明", () => {
    for (const b of [0, 50, 100]) {
      expect(biasModeLabel(b).length).toBeGreaterThan(0);
      expect(biasModeHint(b).length).toBeGreaterThan(0);
    }
    expect(biasModeLabel(0)).toBe("本地优先");
    expect(biasModeLabel(100)).toBe("云端优先");
  });
});
