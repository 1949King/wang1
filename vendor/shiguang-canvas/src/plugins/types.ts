/** 画布节点插件 SDK — 类型定义
 *
 * 插件是一个独立 JS bundle（rollup/esbuild 打包时 external 掉 react、@xyflow/react），
 * default export 一个 CanvasPlugin 对象。宿主通过 Blob URL + import() 动态加载。
 *
 * 兼容 infinite-canvas 插件：Content + defaultMetadata + minAppVersion
 */
import type { ComponentType, ReactNode } from "react";
import type { Node, NodeProps } from "@xyflow/react";

export type PluginModelKind = "image" | "video" | "audio" | "text";

/** 插件声明的节点定义 */
export type CanvasNodeDefinition = {
  /** 节点 type，内置节点直接用名字（如 "shot"），插件节点推荐 "<pluginId>:<name>" */
  type: string;
  /** 节点卡默认标题 */
  title: string;
  /** 左侧节点面板图标（emoji 或 ReactNode） */
  icon: ReactNode;
  description?: string;
  defaultSize?: { width: number; height: number };
  /** 节点卡主体组件，接收 @xyflow/react 的 NodeProps */
  Component?: ComponentType<NodeProps<Node>>;
  /** infinite 风格：Content(ctx) 替代 Component */
  Content?: ComponentType<{ ctx: unknown }>;
  defaultMetadata?: Record<string, unknown>;
  hasSourceHandle?: boolean;
  /** 是否在创建菜单显示，默认 true */
  showInCreateMenu?: boolean;
};

/** 宿主注入给插件的运行时 AI 能力 */
export type PluginRuntimeAI = {
  generateImage: (
    prompt: string,
    opts?: { references?: string[]; model?: string; count?: number; size?: string },
  ) => Promise<string[]>;
  generateVideo: (
    prompt: string,
    opts?: { references?: string[]; model?: string; duration?: number },
  ) => Promise<string>;
  generateText: (
    prompt: string,
    opts?: { model?: string; channel_id?: string },
  ) => Promise<string>;
  listModels: (kind?: PluginModelKind) => string[];
  defaultModel: (kind?: PluginModelKind) => string;
};

/** 宿主注入给插件的运行时 */
export type PluginRuntime = {
  /** 宿主 React — 避免插件 bundle 再打包一份 React */
  React: typeof import("react");
  /** 注入插件样式，同 key 替换；返回 cleanup */
  injectCSS: (css: string, key?: string) => () => void;
  /** 事件总线：画布级广播 */
  emit: (event: string, payload?: unknown) => void;
  on: (event: string, handler: (payload: unknown) => void) => () => void;
  /** 宿主 AI 能力（走 /host/generate-* 桥） */
  ai?: PluginRuntimeAI;
  /** 宿主版本号（infinite 插件可读 minAppVersion） */
  version: string;
};

/** 插件包默认导出 */
export type CanvasPlugin = {
  id: string;
  name: string;
  version: string;
  description?: string;
  /** infinite 兼容：最低宿主版本 */
  minAppVersion?: string;
  /** 必填：节点定义数组 */
  nodes: CanvasNodeDefinition[];
  /** 可选：注入全局 CSS（启用时注入，卸载/禁用时移除） */
  css?: string;
  /** 可选：启动时回调，返回 cleanup 函数 */
  setup?: (runtime: PluginRuntime) => void | (() => void);
};
