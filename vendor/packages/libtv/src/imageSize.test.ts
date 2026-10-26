import { describe, expect, it } from "vitest";
import { describeImageSize, estimateImageSize, QUALITY_MAX_SIDE } from "./imageSize";

describe("imageSize · 画质档 → 分辨率（与后端同口径）", () => {
  it("方图按档位取长边", () => {
    expect(estimateImageSize("1:1", "draft")).toEqual({ width: 768, height: 768 });
    expect(estimateImageSize("1:1", "standard")).toEqual({ width: 832, height: 832 });
    expect(estimateImageSize("1:1", "cinema")).toEqual({ width: 1024, height: 1024 });
  });

  it("竖屏等比且长边受档位约束", () => {
    const { width, height } = estimateImageSize("9:16", "standard");
    expect(height).toBe(832);
    expect(width).toBeLessThan(height);
    expect(width % 64).toBe(0);
    expect(height % 64).toBe(0);
  });

  it("未知档位回落 standard，不抛异常", () => {
    expect(estimateImageSize("1:1", "nonsense")).toEqual({ width: 832, height: 832 });
    expect(describeImageSize("16:9", "standard")).toMatch(/^\d+×\d+$/);
    expect(QUALITY_MAX_SIDE.cinema).toBe(1024);
  });
});
