/**
 * Model3dNode SSR 冒烟回归（T5 图片转3D，2026-11-20）。
 *
 * vitest node 环境无 jsdom/WebGL：renderToStaticMarkup 验证首帧输出与降级路径。
 * 真机 WebGL 行为（OrbitControls 环绕/截图）走人工验收（诚实标注）。
 * 注：项目 vitest include 仅 src/**\/*.test.ts，故用 .ts（React.createElement 无 JSX）。
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ReactFlowProvider } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { Model3dNode, MODEL3D_NOTE } from "./model3dNode";

/** 构造最小 NodeProps（SSR 只读 id/data/selected）。 */
function props(data: Record<string, unknown>) {
  return { id: "m1", data, selected: false } as never;
}

/** Handle/NodeResizer 需 ReactFlowProvider 祖先（error #001）⇒ SSR 包裹。 */
function render(data: Record<string, unknown>): string {
  return renderToStaticMarkup(
    React.createElement(ReactFlowProvider, null, React.createElement(Model3dNode, props(data))),
  );
}

describe("Model3dNode SSR 首帧", () => {
  it("无模型 ⇒ 渲染待生成占位（不冒充已有 3D）", () => {
    const html = render({ kind: "model3d", title: "3D模型", status: "idle" });
    expect(html).toContain("待生成");
  });

  it("有模型但 node 无 WebGL ⇒ 诚实降级静态预览标记", () => {
    const html = render({
      kind: "model3d", title: "3D模型", status: "success",
      modelUrl: "/inbox_file/img3d_1.glb",
      sourceImageUrl: "data:image/png;base64,AAAA",
    });
    expect(html).toContain("sg-model3d-fallback");
    expect(html).toContain("WebGL 不可用");
  });

  it("有模型 ⇒ 显著展示 2.5D 诚实标注（不冒充真体积/泼溅）", () => {
    const html = render({
      kind: "model3d", title: "3D模型", status: "success",
      modelUrl: "/inbox_file/img3d_1.glb",
    });
    expect(html).toContain("2.5D");
    expect(html).toContain("非真体积重建");
  });

  it("失败 + guidance ⇒ 透传引导（模型缺失自取提示）", () => {
    const html = render({
      kind: "model3d", title: "3D模型", status: "failed",
      errorMessage: "未找到深度模型（.onnx）",
      guidance: "请下载 Depth-Anything-V2-Small …",
    });
    expect(html).toContain("未找到深度模型");
    expect(html).toContain("Depth-Anything");
  });

  it("MODEL3D_NOTE 与后端诚实口径一致", () => {
    expect(MODEL3D_NOTE).toContain("2.5D");
    expect(MODEL3D_NOTE).toContain("高斯泼溅");
  });
});
