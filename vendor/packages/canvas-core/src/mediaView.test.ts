/**
 * 双击媒体查看器（2026-11-12）：标签识别为纯函数，便于单测。
 */
import { describe, expect, it } from "vitest";

import { classifyMedia } from "./mediaView";

describe("classifyMedia", () => {
  it("img → image，video → video", () => {
    expect(classifyMedia("IMG", "data:image/png;base64,AAA")).toEqual({ kind: "image", src: "data:image/png;base64,AAA" });
    expect(classifyMedia("video", "http://127.0.0.1:18765/inbox_file/a.mp4")).toEqual({
      kind: "video",
      src: "http://127.0.0.1:18765/inbox_file/a.mp4",
    });
  });

  it("其它标签或空地址 → null（不劫持双击）", () => {
    expect(classifyMedia("div", "x")).toBeNull();
    expect(classifyMedia("img", "   ")).toBeNull();
    expect(classifyMedia("img", null)).toBeNull();
  });
});
