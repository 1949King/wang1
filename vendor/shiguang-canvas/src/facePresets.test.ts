/**
 * facePresets 单测（node 环境，无 DOM）。
 *
 * 覆盖：导入/导出文本往返、normalize 兜底、localStorage 不可用时静默降级。
 */
import { describe, it, expect } from "vitest";
import { DEFAULT_FACE_PARAMS, type FaceParams } from "./faceParams";
import { exportPresetText, importPresetText, loadFacePresets } from "./facePresets";

describe("facePresets · 导入导出", () => {
  it("导出的 JSON 可被 importPresetText 原样读回", () => {
    const preset = { name: "测试预设", serialized: JSON.stringify(DEFAULT_FACE_PARAMS), createdAt: Date.now() };
    const text = exportPresetText(preset);
    const res = importPresetText(text);
    expect(res.ok).toBe(true);
    if (!res.ok) throw new Error(res.error);
    expect(res.name).toBe("测试预设");
    expect(res.params).toEqual(DEFAULT_FACE_PARAMS);
  });

  it("接受纯 faceParams 对象作为兼容导入", () => {
    const raw: FaceParams = { ...DEFAULT_FACE_PARAMS, eyeColor: "violet", hairAccessory: "tiara" };
    const res = importPresetText(JSON.stringify(raw));
    expect(res.ok).toBe(true);
    if (!res.ok) throw new Error(res.error);
    expect(res.params.eyeColor).toBe("violet");
    expect(res.params.hairAccessory).toBe("tiara");
  });

  it("脏字段会被 normalize 兜底，不抛错", () => {
    const res = importPresetText(JSON.stringify({ eyeColor: "rainbow", hairAccessory: "nope" }));
    expect(res.ok).toBe(true);
    if (!res.ok) throw new Error(res.error);
    expect(res.params.eyeColor).toBe(DEFAULT_FACE_PARAMS.eyeColor);
    expect(res.params.hairAccessory).toBe("none");
  });

  it("非法 JSON 返回 ok:false 并带错误信息", () => {
    const res = importPresetText("{坏 json");
    expect(res.ok).toBe(false);
    if (res.ok) throw new Error("expected import error");
    expect(res.error).toContain("JSON");
  });
});

describe("facePresets · localStorage 降级", () => {
  it("node 环境无 window 时加载返回空数组", () => {
    expect(loadFacePresets()).toEqual([]);
  });
});
