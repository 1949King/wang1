/**
 * 小白模式右侧参数面板生成入口回归（2026-11-17）。
 *
 * vitest 使用 node 环境，这里通过 React 服务端渲染验证真实组件输出，
 * 不引入 jsdom，也不复制一份面板实现。
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NodeActionsContext } from "../nodes";
import { useCanvasStore } from "../store";
import { makeNode } from "../stores/node-factory";
import NoviceInspector from "./NoviceInspector";

const GENERATABLE_KINDS = [
  "shot",
  "image",
  "video",
  "generator",
  "audio",
  "music",
  "director",
  "animation",
  "panorama",
  "digitalHuman",
] as const;

/** 用真实 store 选中指定类型卡片，并渲染带节点动作的右侧面板。 */
function renderInspector(
  kind: string,
  options: { generating?: boolean; withAction?: boolean } = {},
): string {
  const node = makeNode(kind as never, { x: 0, y: 0 });
  if (options.generating) {
    node.data = { ...node.data, status: "generating" };
  }
  useCanvasStore.setState({ nodes: [node], edges: [], selectedId: node.id });
  const actions = options.withAction === false ? {} : { generateNode: () => undefined };
  return renderToStaticMarkup(
    React.createElement(
      NodeActionsContext.Provider,
      { value: actions },
      React.createElement(NoviceInspector),
    ),
  );
}

/** 取生成按钮的完整开始标签，避免依赖 React 输出属性的顺序。 */
function generateButtonTag(html: string): string | undefined {
  return html.match(/<button[^>]*nv-insp-generate[^>]*>/)?.[0];
}

beforeEach(() => {
  // Zustand 在服务端渲染默认读取创建 store 时的 initialState，而非测试刚 setState 的当前态。
  // 仅替换 React 的服务端快照读取方式，真实 store、节点工厂和面板组件均保持原样。
  vi.spyOn(React, "useSyncExternalStore").mockImplementation(
    (_subscribe, getSnapshot) => getSnapshot(),
  );
  useCanvasStore.setState({ nodes: [], edges: [], selectedId: null });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("小白模式右侧生成入口", () => {
  it.each(GENERATABLE_KINDS)("%s 卡片显示生成按钮", (kind) => {
    const html = renderInspector(kind);
    expect(generateButtonTag(html), `kind=${kind} 缺少生成按钮`).toBeTruthy();
    if (kind === "digitalHuman") {
      expect(html).toContain("生成配音");
    }
  });

  it.each(["script", "text", "group", "config"])("%s 卡片不显示生成按钮", (kind) => {
    const html = renderInspector(kind);
    expect(html).toContain('class="nv-insp-head"');
    expect(generateButtonTag(html)).toBeUndefined();
  });

  it("生成中禁用按钮并显示真实进行态", () => {
    const html = renderInspector("shot", { generating: true });
    const button = generateButtonTag(html);
    expect(button, "生成中仍应保留禁用的生成按钮").toBeTruthy();
    expect(button!).toContain("disabled");
    expect(html).toContain("生成中…");
  });

  it("节点动作尚未注入时禁用按钮，不产生假成功", () => {
    const html = renderInspector("shot", { withAction: false });
    const button = generateButtonTag(html);
    expect(button, "动作未注入时仍应保留禁用的生成按钮").toBeTruthy();
    expect(button!).toContain("disabled");
  });
});
