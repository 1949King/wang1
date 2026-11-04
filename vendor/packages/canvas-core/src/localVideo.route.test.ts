import { describe, expect, it } from "vitest";

import { AUTO_CHANNEL_ID, buildVideoChain, mergeLocalVideoModels } from "./localVideo";

describe("视频双路（执行层计划 → 实际尝试顺序）", () => {
  it("有首帧 + 云端可用：严格按计划顺序", () => {
    expect(buildVideoChain({ chain: ["local", "cloud"] }, { hasReference: true, cloudFallback: true }).chain)
      .toEqual(["local", "cloud"]);
    expect(buildVideoChain({ chain: ["cloud", "local"] }, { hasReference: true, cloudFallback: true }).chain)
      .toEqual(["cloud", "local"]);
  });

  it("没有首帧：不排本地，并给出原因（SVD 是 i2v）", () => {
    const r = buildVideoChain({ chain: ["local", "cloud"] }, { hasReference: false, cloudFallback: true });
    expect(r.chain).toEqual(["cloud"]);
    expect(r.reasons.join("")).toContain("首帧");
  });

  it("没有云端兜底模型：跳过云端", () => {
    const r = buildVideoChain({ chain: ["cloud"] }, { hasReference: true, cloudFallback: false });
    expect(r.chain).toEqual([]);
    expect(r.reasons.join("")).toContain("云端");
  });

  it("计划缺失或非法：按云端兜底（不中断生成）", () => {
    expect(buildVideoChain(null, { hasReference: true, cloudFallback: true }).chain).toEqual(["cloud"]);
    expect(buildVideoChain({ chain: ["bogus"] }, { hasReference: true, cloudFallback: true }).chain).toEqual(["cloud"]);
  });

  it("模型列表前置「自动」选项（唯一入口）", () => {
    const merged = mergeLocalVideoModels(
      [{ channel_id: "c1", channel_name: "云端", model: "m1", label: "c1" }],
      { models: [], downloaded: [] },
    );
    expect(merged[0].channel_id).toBe(AUTO_CHANNEL_ID);
    expect(merged).toHaveLength(2);
  });
});
