/**
 * 迁移与版本快照辅助（从 store.ts 拆出的共享数据契约逻辑）
 *
 * 纯函数、无 zustand 闭包依赖：
 * - upgradeSchemaV2toV3：旧工程连线 schema 升级（委托 schema-migrations，幂等）
 * - collectAiVersions：S6 版本锁定，收集项目内用到的 provider/model 快照
 *
 * 注意：collectAiVersions 仅 type-only 依赖 ../store 的 ProjectBundle，
 * 编译期消除，不产生运行时循环依赖。
 */
import type { Node, Edge } from "@xyflow/react";
import { migrateEdgesForCanvas } from "./schema-migrations";
import type { ProjectBundle } from "../store";

/** 旧工程（v1/v2）升级到 v3 连线 schema：委托 schema-migrations，保持幂等 */
export function upgradeSchemaV2toV3(nodes: Node[], edges: Edge[]): Edge[] {
  return migrateEdgesForCanvas(nodes as any, edges as any) as Edge[];
}

/** 从节点列表中收集出现过的 AI model → provider 映射（S6 版本锁定） */
export function collectAiVersions(nodes: Node[]): ProjectBundle["aiVersions"] {
  const providers: Record<string, string> = {};
  for (const n of nodes) {
    const d = (n.data || {}) as Record<string, any>;
    const model = d.model as string | undefined;
    const provider = (d.provider || "") as string;
    if (model) {
      providers[provider || "default"] = model;
    }
  }
  if (Object.keys(providers).length === 0) return undefined;
  return { providers };
}