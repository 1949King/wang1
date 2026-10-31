/**
 * 工作流蓝图（Blueprint）· 分层拓扑布局引擎
 * ═══════════════════════════════════════════════════════════════════════
 * 2026-10-31 · 把「Agent 只能摆 1~3 张随机卡片」升级成「一次铺出一张完整 DAG」。
 *
 * ── 为什么是这个形状 ────────────────────────────────────────────────────
 * 用户实锤的原问题：Agent 收到需求后只能调出 1~3 张节点/意图卡片，
 * 而且**摆放随意、互相叠压**（store.addNode 无坐标时 `Math.random()` 撒在
 * 120~440 × 80~320 的小盒子里 —— store.ts 属冻结区不可改）。
 *
 * 三条开源启发（本模块的取舍依据）：
 *  1. **ComfyUI：图是一等公民** —— LLM 直接产出 graph JSON，执行器吃图。
 *     ⇒ 本模块的输入就是一张「蓝图」，不是一串零散指令。
 *  2. **React Flow + Dagre：拓扑 → 自动坐标** —— 布局由图结构算出来，
 *     而不是让 LLM 报像素。
 *     ⇒ 本模块实现 Dagre `getLayoutedElements` 的核心（分层 + 层内排序），
 *       但**零新依赖**（本仓无 dagre/elkjs/d3-force，且体积守卫严格）。
 *  3. **AiDiagram：LLM 永不输出像素坐标，只输出语义放置元数据** ——
 *     布局可换而不用重问 LLM，且对模型输出波动健壮。
 *     ⇒ 蓝图里**没有 x/y 字段**；坐标一律由本模块算。
 *
 * ── 算法（与 Dagre 的对应关系）───────────────────────────────────────────
 *  ① 分层：Kahn 拓扑 + 最长路径 ⇒ layer(v) = max(layer(pred)) + 1
 *     （Dagre 的 `rank`；我们只做「层号」，不做坐标）
 *  ② 层内排序：重心法（barycenter）迭代 2 轮
 *     （Dagre 的 `position/order` 阶段；重心法是 Eades–Sutherlands–Stoltz
 *       的经典交叉最小化启发式，2 轮在 ≤20 节点规模上足够）
 *  ③ 坐标：x = 列(layer) · 步长X，y = 行(order) · 步长Y，
 *     每层在纵向**居中**（Dagre 的 `align` 视觉直觉）
 *
 * ── 纪律 ────────────────────────────────────────────────────────────────
 *  - **纯函数**：零 React / 零 store / 零副作用 ⇒ vitest 直接可测；
 *  - **确定性**：同一蓝图永远得到同一坐标（无 Math.random、无 Date.now）；
 *  - **诚实**：环、悬空边、重复 key 全部**如实报告**（problems），
 *    不静默吞掉；成环边会被剔除以保证落到画布上的仍是 DAG；
 *  - **不越权**：不判业务合法性、不改节点内容，只负责「摆哪」。
 */

export interface BlueprintNodeSpec {
  /** 蓝图内唯一 key（edges 用它引用节点） */
  key: string;
  /** 节点类型（必须是 ports.ts 登记的 kind） */
  kind: string;
  /** 卡片标题 */
  title?: string;
  /** 正文 / 提示词（LLM 生成的画面描述、剧本片段……） */
  prompt?: string;
  /** 这张卡在流程里的作用（人话说明） */
  intent?: string;
  /** 自由字段，落到节点 data */
  data?: Record<string, unknown>;
}

export interface BlueprintEdgeSpec {
  from: string;
  to: string;
}

export interface BlueprintSpec {
  /** 一句话说明这条流程要产出什么 */
  goal?: string;
  nodes: BlueprintNodeSpec[];
  edges: BlueprintEdgeSpec[];
}

export interface LaidOutNode {
  key: string;
  kind: string;
  /** 画布坐标（左上角） */
  x: number;
  y: number;
  /** 拓扑层号（0 = 起点层） */
  layer: number;
  /** 层内序号（0 = 该层最上） */
  order: number;
}

export interface BlueprintEdge {
  from: string;
  to: string;
}

export interface BlueprintLayout {
  nodes: LaidOutNode[];
  /** 剔除成环边后仍然成立的边 */
  edges: BlueprintEdge[];
  /** 如实报告的问题（环 / 悬空边 / 重复 key / 空蓝图） */
  problems: string[];
  /** 层数（单层 = 1） */
  layers: number;
}

/** 布局起点（与 canvasSlot 的 SLOT_ORIGIN 对齐，画布左上角内侧）。 */
export const BLUEPRINT_ORIGIN = { x: 80, y: 80 };
/**
 * 步长（与 canvasSlot 的 SLOT_GAP_* 一致：卡宽 188~280 / 卡高 160~240）。
 * 复用同一套间距 ⇒ 蓝图铺出来的卡与手动拖出来的卡**视觉密度一致**。
 */
export const BLUEPRINT_STEP = { x: 300, y: 230 };

export interface LayoutOptions {
  origin?: { x: number; y: number };
  step?: { x: number; y: number };
}

/* ───────────────────────── 内部工具 ───────────────────────── */

function medianOf(values: number[]): number {
  if (!values.length) return 0;
  const s = [...values].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

interface KahnResult {
  layer: Map<string, number>;
  /** 拓扑处理到的节点（未处理完 ⇒ 有环） */
  seen: Set<string>;
  hasCycle: boolean;
  /** 仍在环上的节点 */
  inCycle: string[];
}

/** Kahn 拓扑 + 最长路径分层。**假定入边已去自环。** */
function kahn(order: string[], edges: BlueprintEdge[]): KahnResult {
  const indeg = new Map<string, number>();
  const adj = new Map<string, string[]>();
  for (const k of order) {
    indeg.set(k, 0);
    adj.set(k, []);
  }
  for (const e of edges) {
    adj.get(e.from)!.push(e.to);
    indeg.set(e.to, (indeg.get(e.to) ?? 0) + 1);
  }
  const layer = new Map<string, number>();
  for (const k of order) layer.set(k, 0);
  const q: string[] = order.filter((k) => (indeg.get(k) ?? 0) === 0);
  const seen = new Set<string>();
  while (q.length) {
    const n = q.shift()!;
    seen.add(n);
    for (const m of adj.get(n) ?? []) {
      layer.set(m, Math.max(layer.get(m) ?? 0, (layer.get(n) ?? 0) + 1));
      const d = (indeg.get(m) ?? 0) - 1;
      indeg.set(m, d);
      if (d === 0) q.push(m);
    }
  }
  const inCycle = order.filter((k) => !seen.has(k));
  return { layer, seen, hasCycle: inCycle.length > 0, inCycle };
}

/* ───────────────────────── 主入口 ───────────────────────── */

/**
 * 计算蓝图布局。
 *
 * @param spec 蓝图（节点 + 边；**不含坐标**）
 * @param opts 起点与步长（默认与手工网格一致）
 */
export function layoutBlueprint(
  spec: BlueprintSpec | null | undefined,
  opts: LayoutOptions = {},
): BlueprintLayout {
  const origin = opts.origin ?? BLUEPRINT_ORIGIN;
  const step = opts.step ?? BLUEPRINT_STEP;
  const problems: string[] = [];

  const rawNodes = Array.isArray(spec?.nodes) ? spec!.nodes : [];
  const rawEdges = Array.isArray(spec?.edges) ? spec!.edges : [];
  if (!rawNodes.length) {
    return { nodes: [], edges: [], problems: ["蓝图没有节点"], layers: 0 };
  }

  // ── ① key 归一：去重、丢弃空 key ──
  const byKey = new Map<string, BlueprintNodeSpec>();
  const order: string[] = [];
  for (const n of rawNodes) {
    const key = String(n?.key ?? "").trim();
    if (!key) {
      problems.push("存在没有 key 的节点，已跳过");
      continue;
    }
    if (byKey.has(key)) {
      problems.push(`节点 key 重复：${key}（保留第一个，忽略后一个）`);
      continue;
    }
    byKey.set(key, n);
    order.push(key);
  }
  if (!order.length) {
    return { nodes: [], edges: [], problems: [...problems, "蓝图没有有效节点"], layers: 0 };
  }

  // ── ② 边归一：剔悬空 / 自环 ──
  let workEdges: BlueprintEdge[] = [];
  for (const e of rawEdges) {
    const from = String(e?.from ?? "").trim();
    const to = String(e?.to ?? "").trim();
    if (!byKey.has(from) || !byKey.has(to)) {
      problems.push(`忽略悬空边 ${from || "?"} → ${to || "?"}（引用了不存在的节点）`);
      continue;
    }
    if (from === to) {
      problems.push(`忽略自环边 ${from}`);
      continue;
    }
    workEdges.push({ from, to });
  }
  // 同向重复边去重
  const edgeSeen = new Set<string>();
  workEdges = workEdges.filter((e) => {
    const k = `${e.from}→${e.to}`;
    if (edgeSeen.has(k)) {
      problems.push(`忽略重复边 ${k}`);
      return false;
    }
    edgeSeen.add(k);
    return true;
  });

  // ── ③ 去环：逐条剔除成环边，保留尽可能多的图 ──
  let res = kahn(order, workEdges);
  let guard = 0;
  while (res.hasCycle && guard < 64) {
    const victim = res.inCycle[res.inCycle.length - 1];
    let idx = -1;
    for (let i = workEdges.length - 1; i >= 0; i--) {
      if (workEdges[i].to === victim) {
        idx = i;
        break;
      }
    }
    if (idx < 0) break;
    const [dropped] = workEdges.splice(idx, 1);
    problems.push(`忽略成环边 ${dropped.from} → ${dropped.to}（数据流必须无环）`);
    res = kahn(order, workEdges);
    guard++;
  }

  // ── ④ 分层：拓扑层号（Kahn 已算好）──
  const layerOf = (k: string): number => res.layer.get(k) ?? 0;
  const layerMap = new Map<number, string[]>();
  for (const k of order) {
    const L = layerOf(k);
    const arr = layerMap.get(L);
    if (arr) arr.push(k);
    else layerMap.set(L, [k]);
  }

  // ── ⑤ 层内排序：重心法迭代 2 轮（减少连线交叉）──
  const posOf = new Map<string, number>();
  const reindex = () => {
    posOf.clear();
    for (const list of layerMap.values()) list.forEach((k, i) => posOf.set(k, i));
  };
  reindex();
  for (let iter = 0; iter < 2; iter++) {
    const next = new Map<number, string[]>();
    for (const [L, list] of layerMap) {
      const scored = list.map((k) => {
        const preds = workEdges
          .filter((e) => e.to === k)
          .map((e) => posOf.get(e.from))
          .filter((v): v is number => v !== undefined);
        // 无前驱 ⇒ 保持原位（不参与重排），避免孤立节点乱飘
        const bary = preds.length ? medianOf(preds) : (posOf.get(k) ?? 0);
        return { k, bary, tie: posOf.get(k) ?? 0 };
      });
      scored.sort((a, b) => a.bary - b.bary || a.tie - b.tie || a.k.localeCompare(b.k));
      next.set(L, scored.map((s) => s.k));
    }
    layerMap.clear();
    for (const [L, list] of next) layerMap.set(L, list);
    reindex();
  }

  // ── ⑥ 坐标：列 = 层，行 = 层内序；每层纵向居中 ──
  const maxRows = Math.max(...Array.from(layerMap.values()).map((l) => l.length));
  const laid: LaidOutNode[] = [];
  for (const [L, list] of layerMap) {
    const rowOffset = (maxRows - list.length) / 2;
    list.forEach((k, i) => {
      const row = rowOffset + i;
      laid.push({
        key: k,
        kind: String(byKey.get(k)?.kind ?? ""),
        x: origin.x + L * step.x,
        y: origin.y + row * step.y,
        layer: L,
        order: i,
      });
    });
  }

  return {
    nodes: laid,
    edges: workEdges,
    problems,
    layers: layerMap.size,
  };
}

/** 蓝图里的节点数（给提示/校验用）。 */
export function blueprintNodeCount(spec: BlueprintSpec | null | undefined): number {
  return Array.isArray(spec?.nodes) ? spec!.nodes.length : 0;
}
