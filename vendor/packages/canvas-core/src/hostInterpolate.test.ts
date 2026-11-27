/**
 * hostInterpolate 纯函数契约测试（T4 项二，2026-11-20）。
 * vitest node 环境（无 jsdom）：只测 parseInterpolateResult 判读逻辑。
 */
import { describe, it, expect } from "vitest";
import { parseInterpolateResult } from "./hostInterpolate";

describe("parseInterpolateResult", () => {
  it("解析成功结果（rife 引擎）", () => {
    const r = parseInterpolateResult({
      ok: true,
      video_path: "/inbox/rife_1_2x.mp4",
      video_url: "/inbox_file/rife_1_2x.mp4",
      fps: 48,
      multiplier: 2,
      frames_added: 10,
      engine: "rife",
      degraded: false,
    });
    expect(r.ok).toBe(true);
    expect(r.video_url).toBe("/inbox_file/rife_1_2x.mp4");
    expect(r.fps).toBe(48);
    expect(r.multiplier).toBe(2);
    expect(r.frames_added).toBe(10);
    expect(r.engine).toBe("rife");
    expect(r.degraded).toBe(false);
  });

  it("解析降级结果（flow + reason）", () => {
    const r = parseInterpolateResult({
      ok: true,
      video_url: "/inbox_file/x.mp4",
      engine: "flow",
      degraded: true,
      reason: "显存不足，降级光流",
    });
    expect(r.ok).toBe(true);
    expect(r.engine).toBe("flow");
    expect(r.degraded).toBe(true);
    expect(r.reason).toBe("显存不足，降级光流");
  });

  it("模型缺失：ok:false 透传 guidance", () => {
    const r = parseInterpolateResult({
      ok: false,
      error: "未部署 RIFE 神经补帧模型",
      guidance: "请放置 rife49.pth …",
    });
    expect(r.ok).toBe(false);
    expect(r.error).toContain("未部署");
    expect(r.guidance).toContain("rife49.pth");
  });

  it("失败结果缺 error 时用 message 兜底", () => {
    const r = parseInterpolateResult({ ok: false, message: "编码失败" });
    expect(r.ok).toBe(false);
    expect(r.error).toBe("编码失败");
  });

  it("非对象输入降级为 ok:false（不崩）", () => {
    expect(parseInterpolateResult(null).ok).toBe(false);
    expect(parseInterpolateResult(undefined).ok).toBe(false);
    expect(parseInterpolateResult("x").ok).toBe(false);
    expect(parseInterpolateResult(42).ok).toBe(false);
  });

  it("缺 ok 字段视为失败", () => {
    const r = parseInterpolateResult({ video_url: "/x.mp4" });
    expect(r.ok).toBe(false);
  });

  it("数值字段容错（非数 ⇒ 默认）", () => {
    const r = parseInterpolateResult({ ok: true, fps: "bad", multiplier: null });
    expect(r.ok).toBe(true);
    expect(r.fps).toBe(0);
    expect(r.multiplier).toBe(2);
  });
});
