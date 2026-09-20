import { describe, it, expect } from "vitest";
import { isComfyWorkflowJson, isComfyWorkflowText } from "./bridge";

describe("ComfyUI workflow 识别（前端入口）", () => {
  it("识别 UI 格式（含 nodes 数组）", () => {
    expect(isComfyWorkflowJson({ nodes: [], links: [] })).toBe(true);
  });

  it("识别 graph 格式（class_type 对象）", () => {
    expect(
      isComfyWorkflowJson({ "1": { class_type: "KSampler", inputs: {} } }),
    ).toBe(true);
  });

  it("拒绝非 workflow JSON（数组 / 空对象 / null）", () => {
    expect(isComfyWorkflowJson([])).toBe(false);
    expect(isComfyWorkflowJson({})).toBe(false);
    expect(isComfyWorkflowJson(null)).toBe(false);
    expect(isComfyWorkflowJson("hello")).toBe(false);
  });

  it("isComfyWorkflowText 识别剪贴板 JSON 文本", () => {
    const ui = JSON.stringify({ nodes: [{ id: 1, type: "SaveImage" }] });
    expect(isComfyWorkflowText(ui)).toBe(true);
  });

  it("isComfyWorkflowText 拒绝普通文本 / 非 JSON / 非 workflow", () => {
    expect(isComfyWorkflowText("")).toBe(false);
    expect(isComfyWorkflowText("普通文字")).toBe(false);
    expect(isComfyWorkflowText('{"foo": 1}')).toBe(false);
    expect(isComfyWorkflowText("{ 无效 json")).toBe(false);
  });
});
