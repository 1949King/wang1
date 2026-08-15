/**
 * 工程 bundle 的 localStorage 读写层 + bundle 辅助函数。
 * — 纯函数/副作用函数，不持有 Zustand store 引用
 * — 所有 localStorage 操作集中在此，store.ts 主体只负责调用
 */

import type { Edge, Node } from "@xyflow/react";

/** 以下类型由 store.ts 定义，这里用 import type 避免循环依赖（编译后擦除） */
import type {
  ProjectMeta,
  ProjectBundle,
  CanvasSnapshot,
  CanvasMeta,
} from "../store";

/** ========== localStorage key 常量 ========== */

/** 旧版单项目（兜底迁移用，可在 2026Q4 之后删除） */
export const PROJECT_KEY = "shiguang-canvas:project:v3";
export const PROJECT_KEY_OLD = "shiguang-canvas:project:v1";
export const TEMPLATES_KEY = "shiguang-canvas:templates:v1";
/** 多项目元数据索引 */
export const PROJECTS_KEY = "shiguang-canvas:projects:v1";
/** 每个项目完整 bundle 存储 key 前缀 */
export const PROJECT_BUNDLE_PREFIX = "shiguang-canvas:bundle:";

/** ========== 工具函数 ========== */

/** 生成稳定但不可猜的短 id（前缀 + 随机 7 位 base36） */
export function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
}

/** ========== localStorage 读写 ========== */

export function readProjectsIndex(): ProjectMeta[] {
  try {
    const raw = localStorage.getItem(PROJECTS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function writeProjectsIndex(list: ProjectMeta[]): void {
  try {
    localStorage.setItem(PROJECTS_KEY, JSON.stringify(list));
  } catch (e) {
    if (e instanceof DOMException && e.name === "QuotaExceededError") {
      console.warn("[storage] quota exceeded saving projects index");
    }
  }
}

export function readProjectBundle(id: string): ProjectBundle | null {
  try {
    const raw = localStorage.getItem(PROJECT_BUNDLE_PREFIX + id);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function writeProjectBundle(bundle: ProjectBundle): void {
  try {
    localStorage.setItem(PROJECT_BUNDLE_PREFIX + bundle.id, JSON.stringify(bundle));
  } catch (e) {
    const msg =
      e instanceof DOMException && e.name === "QuotaExceededError"
        ? "本地配额不足，请用「导出 JSON」备份后清理叠卡大图"
        : `保存失败: ${e}`;
    throw new Error(msg);
  }
}

export function deleteProjectBundle(id: string): void {
  localStorage.removeItem(PROJECT_BUNDLE_PREFIX + id);
}

/** ========== bundle 辅助函数 ========== */

const FLOW_NODE_TYPES = new Set([
  "shot", "script", "image", "video", "prompt", "text", "config", "generator", "group", "audio",
]);

/** 过滤出已知节点类型（忽略未知插件节点和残留垃圾） */
export function filterFlowNodes(nodes: Node[]): Node[] {
  return nodes.filter((n) => {
    if (!n) return false;
    const t = String(n.type || "");
    if (t.includes(":")) return true; // pluginId:nodeName 格式的插件节点
    return FLOW_NODE_TYPES.has(t);
  });
}

/** 确保 bundle 有 canvases 数组，没有则用顶层 nodes/edges 构造一个「画布 1」 */
export function ensureProjectCanvases(bundle: ProjectBundle): CanvasSnapshot[] {
  if (bundle.canvases?.length) return bundle.canvases;
  const id = uid("canvas");
  return [
    {
      id,
      name: "画布 1",
      nodes: Array.isArray(bundle.nodes) ? bundle.nodes : [],
      edges: Array.isArray(bundle.edges) ? bundle.edges : [],
      savedAt: bundle.savedAt || new Date().toISOString(),
    },
  ];
}

/** 根据 bundle.activeCanvasId 找到对应画布，找不到则返回第一个 */
export function pickActiveCanvas(
  bundle: ProjectBundle,
  canvases: CanvasSnapshot[],
): CanvasSnapshot {
  const hit = canvases.find((c) => c.id === bundle.activeCanvasId);
  return hit || canvases[0];
}

/** 用新的画布快照 patch 回 bundle（更新 canvases 数组 + 顶层 nodes/edges + activeCanvasId） */
export function patchActiveCanvas(
  bundle: ProjectBundle,
  snapshot: CanvasSnapshot,
): ProjectBundle {
  const canvases = ensureProjectCanvases(bundle).map((c) =>
    c.id === snapshot.id ? snapshot : c,
  );
  return {
    ...bundle,
    canvases,
    activeCanvasId: snapshot.id,
    nodes: snapshot.nodes,
    edges: snapshot.edges,
    savedAt: snapshot.savedAt,
  };
}

/** 一步到位：读 bundle + ensure canvases + pick active canvas */
export function readBundleWithActiveCanvas(projectId: string): {
  bundle: ProjectBundle;
  canvas: CanvasSnapshot;
  canvases: CanvasSnapshot[];
} | null {
  const bundle = readProjectBundle(projectId);
  if (!bundle) return null;
  const canvases = ensureProjectCanvases(bundle);
  const canvas = pickActiveCanvas(bundle, canvases);
  return { bundle, canvas, canvases };
}

/** 把 CanvasSnapshot 序列化成 ProjectBundle（用于 createCanvas / duplicateCanvas 等场景） */
export function snapshotToBundle(
  snapshot: CanvasSnapshot,
  meta: { name: string; dramaTitle?: string; episode?: string; stage3d?: unknown },
): ProjectBundle {
  return {
    id: uid("proj"),
    name: meta.name,
    dramaTitle: meta.dramaTitle || "",
    episode: meta.episode || "",
    nodes: snapshot.nodes,
    edges: snapshot.edges,
    savedAt: snapshot.savedAt,
    stage3d: meta.stage3d,
  };
}
