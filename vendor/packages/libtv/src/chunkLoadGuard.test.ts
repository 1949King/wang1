import { describe, expect, it } from "vitest";

import { isChunkLoadError } from "./chunkLoadGuard";

describe("isChunkLoadError", () => {
  it("识别 Vite 动态 import 失败", () => {
    expect(
      isChunkLoadError(
        "Failed to fetch dynamically imported module: http://127.0.0.1:3011/assets/ImageStudio-DgQwIZ6p.js",
      ),
    ).toBe(true);
  });

  it("识别 Chromium 的模块脚本加载失败", () => {
    expect(isChunkLoadError("Importing a module script failed.")).toBe(true);
  });

  it("识别 CSS preload 失败（dist 换代常见）", () => {
    expect(
      isChunkLoadError(
        "Unable to preload CSS for http://127.0.0.1:3011/assets/AgentPanel-ssbn09LV.css",
      ),
    ).toBe(true);
  });

  it("识别 SPA 兜底把 HTML 当 ESM 的报错", () => {
    // 静态服务曾把缺失资源改写成 index.html ⇒ 前端 import 到 HTML
    expect(isChunkLoadError("Unexpected token '<'")).toBe(true);
  });

  it("普通业务报错不误判（避免把真实 bug 当产物问题刷新掉）", () => {
    expect(isChunkLoadError("Cannot read properties of undefined (reading 'id')")).toBe(false);
    expect(isChunkLoadError("")).toBe(false);
  });
});
