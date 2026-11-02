/**
 * videoFallback 单测（2026-11-02）
 *
 * 组件本身测不了（vitest 跑在 node，没有 jsdom ⇒ 没有 <video> 事件），
 * 但「该拿哪张图当替身」是纯判断，必须锁住 —— 选错就是一片空白代替另一片空白。
 */
import { describe, expect, it } from "vitest";
import { pickVideoPoster } from "./videoFallback";

describe("videoFallback · 替身封面选哪张", () => {
  it("显式封面优先，其次首帧，最后尾帧", () => {
    expect(pickVideoPoster("/inbox_file/p.jpg", "/inbox_file/f.png", "/inbox_file/l.png"))
      .toBe("/inbox_file/p.jpg");
    expect(pickVideoPoster("", "/inbox_file/f.png", "/inbox_file/l.png"))
      .toBe("/inbox_file/f.png");
    expect(pickVideoPoster(undefined, null, "/inbox_file/l.png"))
      .toBe("/inbox_file/l.png");
  });

  it("三个都没有 ⇒ 空串（调用方退回图标底板，不是空 img）", () => {
    expect(pickVideoPoster()).toBe("");
    expect(pickVideoPoster("", "", "")).toBe("");
    expect(pickVideoPoster("   ", null, undefined)).toBe("");
  });

  it("blob: 一律跳过：它只在当次会话有效，存下来就是死链", () => {
    expect(pickVideoPoster("blob:http://127.0.0.1/abc", "/inbox_file/f.png"))
      .toBe("/inbox_file/f.png");
    expect(pickVideoPoster("blob:http://127.0.0.1/abc")).toBe("");
  });

  it("前后空格会被裁掉（节点数据里常见 ' ' 占位）", () => {
    expect(pickVideoPoster("  /inbox_file/p.jpg  ")).toBe("/inbox_file/p.jpg");
  });
});
