/**
 * aestheticPresets 单测（node 环境，无 DOM）。
 *
 * 覆盖：导入/导出文本往返、prompt 幂等拼接、镜头语言补丁、脏字段 normalize 兜底、
 * localStorage 不可用时静默降级。
 */
import { describe, it, expect } from "vitest";
import {
  buildAestheticPatch,
  composeAestheticPrompt,
  exportAestheticText,
  importAestheticText,
  loadAestheticPresets,
  normalizeAestheticPreset,
  type AestheticPreset,
} from "./aestheticPresets";

const SAMPLE: AestheticPreset = {
  name: "王家卫 · 复古港风",
  styleWords: "电影感，港风复古，颗粒噪点",
  camera: { shotSize: "中景", movement: "push-in", focalLength: 35, aperture: 2.8, cameraYaw: -45, cameraPitch: 0 },
  tone: "青橙色调，低饱和",
  rhythm: "前紧后松",
  musicStyle: "港式电子",
  createdAt: 1,
};

describe("aestheticPresets · 导入导出", () => {
  it("导出的 JSON 可被 importAestheticText 读回（四维度齐全）", () => {
    const res = importAestheticText(exportAestheticText(SAMPLE));
    expect(res.ok).toBe(true);
    if (!res.ok) throw new Error(res.error);
    expect(res.preset.name).toBe(SAMPLE.name);
    expect(res.preset.styleWords).toBe(SAMPLE.styleWords);
    expect(res.preset.camera.focalLength).toBe(35);
    expect(res.preset.tone).toBe(SAMPLE.tone);
    expect(res.preset.musicStyle).toBe(SAMPLE.musicStyle);
  });

  it("脏字段会被 normalize 兜底，不抛错", () => {
    const p = normalizeAestheticPreset({ name: 123, camera: { focalLength: "abc" }, tone: null });
    expect(p.name).toBe("未命名预设");
    expect(p.camera.focalLength).toBeUndefined();
    expect(p.tone).toBe("");
  });

  it("无 DOM 时读取返回空数组，不抛错", () => {
    expect(loadAestheticPresets()).toEqual([]);
  });
});

describe("aestheticPresets · 套用", () => {
  it("composeAestheticPrompt 幂等：重复套用同一预设不产生重复片段", () => {
    const once = composeAestheticPrompt("主角站在天台", SAMPLE);
    const twice = composeAestheticPrompt(once, SAMPLE);
    expect(twice).toBe(once);
    expect(once.startsWith(SAMPLE.styleWords)).toBe(true);
    expect(once).toContain("主角站在天台");
  });

  it("buildAestheticPatch 写入 prompt 与镜头语言字段", () => {
    const patch = buildAestheticPatch("", SAMPLE);
    expect(typeof patch.prompt).toBe("string");
    expect(patch.shotSize).toBe("中景");
    expect(patch.movement).toBe("push-in");
    expect(patch.focalLength).toBe(35);
    expect(patch.cameraYaw).toBe(-45);
  });

  it("未设置的镜头语言字段不写入补丁（不覆盖节点既有值）", () => {
    const patch = buildAestheticPatch("x", { ...SAMPLE, camera: {} });
    expect(patch.shotSize).toBeUndefined();
    expect(patch.focalLength).toBeUndefined();
    expect(patch.cameraYaw).toBeUndefined();
    expect(String(patch.prompt)).toContain("x");
  });
});
