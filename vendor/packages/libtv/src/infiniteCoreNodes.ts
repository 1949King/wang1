/** infinite-canvas 核心节点类型 ID（与 basketikun/infinite-canvas CanvasNodeType 对齐） */

export const INFINITE_CORE_NODE_TYPES = {
  image: "image",
  text: "text",
  config: "config",
  video: "video",
  audio: "audio",
  group: "group",
} as const;

export type InfiniteCoreNodeType =
  (typeof INFINITE_CORE_NODE_TYPES)[keyof typeof INFINITE_CORE_NODE_TYPES];

/** 拾光分镜扩展节点（infinite 无对应项，保留） */
export const SHIGUANG_EXTRA_NODE_TYPES = [
  "shot",
  "script",
  "prompt",
  "generator",
] as const;

/** 插件节点 type 推荐格式：`<pluginId>:<nodeName>` */
export function isPluginNodeType(type: string): boolean {
  return type.includes(":");
}

export const PLUGIN_SDK_VERSION = "1.0.0-infinite-compat";
