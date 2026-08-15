/** 节点定义注册表 — 内置节点 + 插件节点统一入口
 *
 * 内置节点在 App.tsx 启动时通过 registerBuiltinNodes() 注册；
 * 插件节点通过 plugin-loader 的 activatePlugin() 动态注册。
 * React Flow 的 nodeTypes prop 通过 useNodeTypes() hook 读取。
 */
import { create } from "zustand";
import type { Node } from "@xyflow/react";
import type { CanvasNodeDefinition } from "./types";

const definitions = new Map<string, CanvasNodeDefinition>();
const ownerByType = new Map<string, string>(); // type -> pluginId；内置节点用 "builtin"

/** registry 版本号——每次注册/取消注册 +1，驱动 UI 刷新 */
export const useNodeRegistryVersion = create<{ version: number }>(() => ({ version: 0 }));
function bump() {
  useNodeRegistryVersion.setState({ version: useNodeRegistryVersion.getState().version + 1 });
}

/** 内置节点 + 插件节点统一注册（幂等：同 type + 同 pluginId 重复调用跳过） */
export function registerNodeDefinitions(defs: CanvasNodeDefinition[], pluginId = "builtin") {
  let changed = false;
  defs.forEach((def) => {
    const existingOwner = ownerByType.get(def.type);
    if (existingOwner === pluginId && definitions.get(def.type) === def) {
      return; // 同插件同节点已注册，跳过（防 HMR 重复 bump）
    }
    definitions.set(def.type, def);
    ownerByType.set(def.type, pluginId);
    changed = true;
  });
  if (changed) bump();
}

/** 卸载/禁用插件时移除它注册的所有节点 */
export function unregisterPluginNodes(pluginId: string) {
  for (const [type, owner] of ownerByType) {
    if (owner !== pluginId) continue;
    definitions.delete(type);
    ownerByType.delete(type);
  }
  bump();
}

export function getNodeDefinition(type: string): CanvasNodeDefinition | undefined {
  return definitions.get(type);
}

export function listNodeDefinitions(): CanvasNodeDefinition[] {
  return Array.from(definitions.values());
}

export function isRegisteredNodeType(type: string): boolean {
  return definitions.has(type);
}

export function getNodeOwnerPluginId(type: string): string {
  return ownerByType.get(type) || "builtin";
}

/** 生成传给 @xyflow/react 的 nodeTypes 对象——所有注册表节点 */
export function buildNodeTypes(): Record<string, CanvasNodeDefinition["Component"]> {
  const out: Record<string, CanvasNodeDefinition["Component"]> = {};
  for (const [type, def] of definitions) {
    out[type] = def.Component;
  }
  return out;
}
