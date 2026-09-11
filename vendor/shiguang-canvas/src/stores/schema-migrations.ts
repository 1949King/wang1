/**
 * Schema 迁移层 — 独立于 Zustand store，负责处理 localStorage / 导入 JSON 的版本升级。
 *
 * 设计原则：
 * - 完全无依赖（只操作原始 JSON 对象），任何模块都能复用
 * - 每个迁移函数都是纯函数（输入输出都是 data，不产生副作用）
 * - 迁移链在 migrateBundle 中串行调用，保证可追踪
 * - 加 down() 反向迁移入口位（预留，便于未来 schema 回滚）
 *
 * 当前版本线：V1（旧单工程，无 version 字段）→ V2（早期 v2）→ V3（当前）
 */

/** 当前 schema 版本号 — 任何 writeProjectBundle 都会写这个值 */
export const CURRENT_SCHEMA_VERSION = 3 as const;

/** 简化的连线类型，用于 V2→V3 迁移 */
export type MigrateEdge = {
  id?: string;
  source: string;
  target: string;
  data?: { type?: string; [k: string]: unknown };
  /** 旧版可能用 style、label 等字段 */
  [k: string]: unknown;
};

/** 简化的节点类型，用于迁移时读取 kind */
export type MigrateNode = {
  id: string;
  type?: string;
  data?: { kind?: string; [k: string]: unknown };
  /** 插件注册的节点可能带 "pluginId:xxx" 格式的 type */
  [k: string]: unknown;
};

/** 简化的工程 bundle 结构 */
export type MigrateBundle = {
  version?: number;
  schemaVersion?: number;
  nodes?: MigrateNode[];
  edges?: MigrateEdge[];
  canvases?: { nodes?: MigrateNode[]; edges?: MigrateEdge[]; [k: string]: unknown }[];
  activeCanvasId?: string;
  dramaTitle?: string;
  episode?: string;
  name?: string;
  id?: string;
  savedAt?: string;
  stage3d?: unknown;
  [k: string]: unknown;
};

/** 识别 source/target 节点的 kind，用于推断连线类型 */
function _getKind(nodes: MigrateNode[], id: string | undefined): string | undefined {
  if (!id) return undefined;
  const src = nodes.find((n) => n && n.id === id);
  if (!src) return undefined;
  // plugin 注册节点的 type 可能是 "pluginId:nodeName" 格式
  if (typeof src.type === "string" && src.type.includes(":")) {
    const pluginKind = src.type.split(":")[1];
    return pluginKind || undefined;
  }
  if (src.data && typeof (src.data as Record<string, unknown>).kind === "string") {
    return (src.data as { kind: string }).kind;
  }
  return undefined;
}

/**
 * 根据两端节点 kind 推断连线 data.type（prompt/image/video/audio/data）
 * — 完全对齐 store.ts 里的 inferEdgeType 逻辑
 */
function _inferEdgeType(srcKind: string | undefined, tgtKind: string | undefined): "prompt" | "image" | "video" | "audio" | "data" {
  const setKind = (s: string | undefined) => {
    if (!s) return "";
    return s;
  };
  const sk = setKind(srcKind);
  const tk = setKind(tgtKind);
  const promptKinds = ["script", "prompt"];
  const imageKinds = ["shot", "image"];
  const videoKinds = ["video"];
  const audioKinds = ["audio"];
  if (promptKinds.includes(sk) && (tk === "shot" || tk === "image" || tk === "generator")) return "prompt";
  if (imageKinds.includes(sk) && (tk === "shot" || tk === "image" || tk === "generator")) return "image";
  if (videoKinds.includes(sk) && (tk === "shot" || tk === "generator")) return "video";
  if (audioKinds.includes(sk) && tk === "generator") return "audio";
  return "data";
}

/**
 * V2 → V3：给缺失 data.type 的连线自动补齐
 * 仅当 data.type 不存在时才补齐，已有则保留（幂等）
 */
export function _migrateEdgesV2toV3(nodes: MigrateNode[], edges: MigrateEdge[] | undefined): MigrateEdge[] {
  if (!Array.isArray(edges)) return [];
  return edges.map((e) => {
    if (!e || typeof e !== "object") return e;
    const hasType = e.data && typeof (e.data as Record<string, unknown>).type === "string";
    if (hasType) return e; // 已是 v3，跳过（幂等）
    const srcKind = _getKind(nodes, e.source);
    const tgtKind = _getKind(nodes, e.target);
    const type = srcKind && tgtKind ? _inferEdgeType(srcKind, tgtKind) : "data";
    return {
      ...e,
      data: { ...(e.data || {}), type },
    };
  });
}

/**
 * 读取 bundle 的 schema 版本号
 * - 优先读 schemaVersion（新字段）
 * - 其次读 version（旧字段，store.ts 里 ProjectBundle.version=3）
 * - 都没有 → 视为 V1（最老版本，需要全链路升级）
 */
export function _readVersion(bundle: MigrateBundle): number {
  if (typeof bundle.schemaVersion === "number") return bundle.schemaVersion;
  if (typeof bundle.version === "number") return bundle.version;
  return 1; // V1 — 还没 version 字段
}

/**
 * V1 → V2：最老版本可能没有 edges、nodes 可能不是数组
 * — 这个函数目前基本是 NOP，因为 _migrateBundle 里后面有 filter
 * — 但保留以便未来 V1 升级需要加字段
 */
export function _migrateV1toV2(raw: MigrateBundle): MigrateBundle {
  const result: MigrateBundle = { ...raw };
  if (!Array.isArray(result.nodes)) result.nodes = [];
  if (!Array.isArray(result.edges)) result.edges = [];
  return result;
}

/**
 * V2 → V3：主迁移入口 — 补齐连线 data.type
 */
export function _migrateV2toV3(raw: MigrateBundle): MigrateBundle {
  const result: MigrateBundle = { ...raw };
  const topEdges = _migrateEdgesV2toV3(result.nodes || [], result.edges);
  result.edges = topEdges;
  // 每个 canvas 内的连线也要升级
  if (Array.isArray(result.canvases)) {
    result.canvases = result.canvases.map((c) => ({
      ...c,
      edges: _migrateEdgesV2toV3((c.nodes || []) as MigrateNode[], (c.edges || []) as MigrateEdge[]),
    }));
  }
  return result;
}

/**
 * 从任意版本的 JSON 迁移到当前版本
 * — 这是所有 localStorage 读操作、importProjectJSON、loadProjectBundle 的统一入口
 *
 * @param rawData 从 localStorage.getItem 或 JSON.parse 拿到的原始对象
 * @returns 迁移后的合法 bundle；如果 rawData 完全非法（null/undefined/不是对象），返回 null
 */
export function migrateBundle(rawData: unknown): MigrateBundle | null {
  if (!rawData || typeof rawData !== "object") return null;
  const raw = rawData as MigrateBundle;
  let result: MigrateBundle = { ...raw };
  const from = _readVersion(result);

  // 从 from 一路升到 CURRENT_SCHEMA_VERSION
  if (from < 2) {
    result = _migrateV1toV2(result);
  }
  if (from < CURRENT_SCHEMA_VERSION) {
    result = _migrateV2toV3(result);
  }
  // 强制写入当前版本号（双写，兼容 version 和 schemaVersion）
  result.version = CURRENT_SCHEMA_VERSION;
  result.schemaVersion = CURRENT_SCHEMA_VERSION;
  return result;
}

/**
 * 类型守卫：判断一个未知对象是否像一个可迁移的工程 bundle
 * — 用于 importProjectJSON 里替代硬编码的 data.version === 3 检查
 */
export function isProjectBundleLike(raw: unknown): boolean {
  if (!raw || typeof raw !== "object") return false;
  const obj = raw as Record<string, unknown>;
  const hasNodes = Array.isArray(obj.nodes);
  // 兼容 V1 老工程（没有 version，但有 nodes）
  const hasVersion = typeof obj.version === "number" || typeof obj.schemaVersion === "number";
  return hasNodes || hasVersion;
}

/**
 * 仅升级某画布快照的 edges（用于 openProject / switchCanvas 等只处理单个 canvas 的场景）
 * — 保持幂等，重复调用无副作用
 */
export function migrateEdgesForCanvas(nodes: MigrateNode[] | undefined, edges: MigrateEdge[] | undefined): MigrateEdge[] {
  return _migrateEdgesV2toV3(nodes || [], edges);
}
