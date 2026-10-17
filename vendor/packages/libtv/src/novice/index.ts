/**
 * 小白模式模块出口
 *
 * 设计取舍：小白模式不重建一张画布，而是复用同一个 ReactFlow 实例，
 * 只把「内置节点的卡面」整体换成矩形磁吸卡片，并把参数面板降维到 L1。
 * 这样 nodes / edges / 撤销重做 / 自动保存 / 入轨 全部原样复用，不存在两套数据。
 */

import type { NodeTypes } from "@xyflow/react";
import { NoviceCard } from "./NoviceCard";

/**
 * 基于专业模式的 nodeTypes 派生小白模式的 nodeTypes：
 * 内置节点（不含 ":" 的键）统一换成 NoviceCard，插件节点保留自己的渲染器。
 */
export function buildNoviceNodeTypes(base: NodeTypes): NodeTypes {
  const out: NodeTypes = {};
  for (const [key, Comp] of Object.entries(base)) {
    out[key] = key.includes(":") ? Comp : (NoviceCard as NodeTypes[string]);
  }
  return out;
}

export { NoviceCard } from "./NoviceCard";
export { default as NoviceInspector } from "./NoviceInspector";
export * from "./types";
