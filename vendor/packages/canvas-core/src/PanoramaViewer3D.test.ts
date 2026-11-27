/**
 * PanoramaViewer3D SSR 冒烟回归（2026-11-20 · 本地三项优化项三）。
 *
 * vitest node 环境无 jsdom/WebGL：用 renderToStaticMarkup 验证首帧输出与降级路径，
 * 不引入 jsdom。真机 WebGL 行为（拖拽环视/滚轮缩放/取景截图）走人工验收（诚实标注）。
 * 截图复用 stage3dGlUtils.readRenderTargetToDataURL（WebGLRenderTarget 路径，
 * 避开 preserveDrawingBuffer+toDataURL 在 NVIDIA 上的 GPU stall，见 Stage3D.tsx:978）。
 * 注：项目 vitest include 仅 src/**\/*.test.ts，故本测试用 .ts（React.createElement 无 JSX）。
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import { PanoramaViewer3D } from "./PanoramaViewer3D";

const BASE_PROPS = {
  imageUrl: "data:image/png;base64,AAAA",
  yaw: 0,
  pitch: 0,
  onYawPitch: () => undefined,
};

/** 记录原始 WebGLRenderingContext，测试后恢复，避免污染其它用例。 */
const originalWebGL = (globalThis as Record<string, unknown>).WebGLRenderingContext;
afterEach(() => {
  if (originalWebGL === undefined) {
    delete (globalThis as Record<string, unknown>).WebGLRenderingContext;
  } else {
    (globalThis as Record<string, unknown>).WebGLRenderingContext = originalWebGL;
  }
});

describe("PanoramaViewer3D SSR 首帧", () => {
  it("node 无 WebGL ⇒ 渲染传入的 fallback（旧 2D）", () => {
    const html = renderToStaticMarkup(
      React.createElement(PanoramaViewer3D, {
        ...BASE_PROPS,
        fallback: React.createElement("div", { className: "pano-fallback-marker" }),
      }),
    );
    expect(html).toContain("pano-fallback-marker");
  });

  it("node 无 WebGL 且未传 fallback ⇒ 输出默认降级标记", () => {
    const html = renderToStaticMarkup(React.createElement(PanoramaViewer3D, BASE_PROPS));
    expect(html).toContain("sg-pano-3d-fallback");
  });

  it("WebGL 可用 ⇒ 首帧渲染 sg-pano-3d 容器（而非 fallback）", () => {
    (globalThis as Record<string, unknown>).WebGLRenderingContext = class {};
    const html = renderToStaticMarkup(
      React.createElement(PanoramaViewer3D, {
        ...BASE_PROPS,
        fallback: React.createElement("div", { className: "pano-fallback-marker" }),
      }),
    );
    expect(html).toContain("sg-pano-3d");
    expect(html).not.toContain("pano-fallback-marker");
  });

  it("是 forwardRef 组件（暴露 capture 句柄形状）", () => {
    expect(typeof PanoramaViewer3D).toBe("object");
    expect(typeof (PanoramaViewer3D as { render?: unknown }).render).toBe("function");
  });
});
