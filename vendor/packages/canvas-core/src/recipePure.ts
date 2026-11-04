/**
 * 配方 · 纯逻辑层（2026-10-19）
 * ============================
 * 零依赖（不 import store / three / react），只做数据变换 ⇒ vitest 可直接跑。
 * 依赖画布的那一半在 `recipe.ts`（读 store、调 addNode/updateNodeData）。
 *
 * 拆这一层的理由：`recipe.ts` 顶部 import store，而 store 依赖 three + react-flow，
 * 本项目 vitest 是 `environment: "node"`（无 DOM）⇒ 单测必须绕开 store。
 * 与 `stage3dScene.ts` / `stage3dPoseLibrary.ts` 的"纯数据 + 纯函数"分层一致。
 */
import type { Aspect, NoviceStage, QualityTier } from "./novice/types";

/** 配方里的节点骨架：只要类型与相对位置，不要实例数据 */
export type RecipeNode = { kind: string; dx: number; dy: number };

/** 可调参数：载入时写进节点 data（只写白名单字段） */
export type RecipeParams = {
  prompt?: string;
  negative?: string[];
  quality?: QualityTier;
  aspect?: Aspect;
  duration?: number;
};

export type Recipe = {
  id: string;
  name: string;
  createdAt: string;
  intent: { stage: NoviceStage; kind: string; goal: string };
  params: RecipeParams;
  masters: { character?: string[]; scene?: string[]; style?: string[] };
  skeleton: { nodes: RecipeNode[] };
  stats: { uses: number; lastUsed?: string };
};

/** 只允许写进节点 data 的字段（白名单，防旧配方带脏字段） */
export const PARAM_WHITELIST: (keyof RecipeParams)[] = [
  "prompt",
  "negative",
  "quality",
  "aspect",
  "duration",
];

/** 只描述「配方需要知道」的节点形状，避免 import 整个 Node 类型 */
export type NodeLike = {
  id: string;
  selected?: boolean;
  type?: string;
  position: { x: number; y: number };
  data?: Record<string, unknown>;
};

/** 从一组节点提炼骨架（纯函数：只取 kind 与相对坐标） */
export function skeletonFromNodes(picked: NodeLike[]): RecipeNode[] {
  if (picked.length === 0) return [];
  const minX = Math.min(...picked.map((n) => n.position.x));
  const minY = Math.min(...picked.map((n) => n.position.y));
  return picked.map((n) => ({
    kind: String(n.data?.kind ?? n.type ?? "image"),
    dx: n.position.x - minX,
    dy: n.position.y - minY,
  }));
}

/** 从第一个节点抽参数（同组卡片通常共享生成参数） */
export function paramsFromNode(node?: NodeLike): RecipeParams {
  const out: RecipeParams = {};
  const d = node?.data;
  if (!d) return out;
  for (const k of PARAM_WHITELIST) {
    if (d[k] !== undefined) (out as Record<string, unknown>)[k] = d[k];
  }
  return out;
}

/** 选中集是否够提炼一个配方 */
export function canExtract(picked: NodeLike[]): boolean {
  return picked.length > 0;
}

/** 落点：放在现有卡片最右侧一列之后（纯函数，便于断言） */
export function nextOriginFrom(
  positions: { x: number; y: number }[],
): { x: number; y: number } {
  if (positions.length === 0) return { x: 120, y: 120 };
  const maxX = Math.max(...positions.map((p) => p.x));
  const minY = Math.min(...positions.map((p) => p.y));
  return { x: maxX + 340, y: minY };
}

const STAGE_KEYWORDS: Record<string, string> = {
  start: "开始",
  frame: "画面",
  audio: "声音",
  stage: "摆位",
  batch: "批量",
  notes: "素材",
  organize: "整理",
};

/** 最长公共子串长度（中文无空格，按标点切 token 会失效 ⇒ 用 LCS 兜底） */
export function lcsLen(a: string, b: string): number {
  if (!a || !b) return 0;
  let best = 0;
  let prev = new Array(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) {
    const cur = new Array(b.length + 1).fill(0);
    for (let j = 1; j <= b.length; j++) {
      if (a[i - 1] === b[j - 1]) {
        cur[j] = prev[j - 1] + 1;
        if (cur[j] > best) best = cur[j];
      }
    }
    prev = cur;
  }
  return best;
}

/**
 * 一句话 → 配方（关键词 + 最长公共子串打分，不引 LLM）。
 *
 * 为什么不只按标点切 token：中文没有空格，「来一张定妆」整串是一个 token，
 * 永远匹配不到「定妆照」——2026-10-19 单测抓到的真实缺陷。改用 LCS：
 * 公共子串 ≥2 字才计分（2 字 → 3 分，正好过阈值）。
 *
 * 匹配不到就返回 null —— **诚实失败**，由调用方提示「要不要存一个」。
 */
export function matchRecipeIn(list: Recipe[], text: string): Recipe | null {
  const q = (text || "").trim();
  if (!q || list.length === 0) return null;

  let best: { r: Recipe; score: number } | null = null;
  for (const r of list) {
    let score = 0;
    const hay = `${r.name} ${r.intent.goal} ${r.intent.kind}`;
    if (hay.includes(q)) score += 10;
    for (const token of q.split(/[\s,，、。]+/).filter((t) => t.length >= 2)) {
      if (hay.includes(token)) score += 3;
    }
    const l = lcsLen(q, hay);
    if (l >= 2) score += l * 1.5;
    if (q.includes(STAGE_KEYWORDS[r.intent.stage] || "\u0000")) score += 2;
    if (!best || score > best.score) best = { r, score };
  }
  return best && best.score >= 3 ? best.r : null;
}

/** 摘要行（UI 各处复用，避免各自拼字符串） */
export function recipeSummary(r: Recipe): string {
  return `${r.intent.goal || r.name} · ${r.skeleton.nodes.length} 张卡 · 用过 ${r.stats.uses || 0} 次`;
}
