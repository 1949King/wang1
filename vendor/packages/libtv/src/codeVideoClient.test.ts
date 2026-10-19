/**
 * codeVideo 客户端纯逻辑单测（V4.46 · 2026-10-20）。
 */
import { describe, expect, it } from "vitest";
import { parseCodeVideoInput } from "./codeVideoClient";

describe("parseCodeVideoInput", () => {
  it("数组 → storyboard", () => {
    const out = parseCodeVideoInput('[{"shot":1,"description":"雨夜","duration":6}]');
    expect(out.error).toBeUndefined();
    expect(out.payload?.storyboard).toHaveLength(1);
    expect(out.payload?.qc).toBe(true);
  });

  it("对象 → spec", () => {
    const out = parseCodeVideoInput('{"version":"1.0","canvas":{},"tracks":[]}');
    expect(out.error).toBeUndefined();
    expect(out.payload?.spec?.version).toBe("1.0");
  });

  it("空输入 / 非法 JSON / 标量 均诚实报错", () => {
    expect(parseCodeVideoInput("").error).toBeTruthy();
    expect(parseCodeVideoInput("{oops").error).toContain("JSON");
    expect(parseCodeVideoInput("42").error).toBeTruthy();
  });

  it("透传输出名与 QC 开关", () => {
    const out = parseCodeVideoInput("[]", { outputName: "a.mp4", qc: false });
    expect(out.payload?.output_name).toBe("a.mp4");
    expect(out.payload?.qc).toBe(false);
  });
});
