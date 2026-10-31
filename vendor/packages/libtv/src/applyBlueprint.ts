/**
 * 工作流蓝图 → 画布落图（原子应用）
 * ═══════════════════════════════════════════════════════════════════════
 * 2026-10-31 · 让 Agent 一次铺出「完整工作流程」而不是 1~3 张随机卡片。
 *
 * ── 与既有通道的关系（**不造第二条链路**）──────────────────────────────
 * 本模块**不新增任何画布写入口**，只用 store 已公开的三件套：
 *   addNode(kind, pos)  → updateNodeData(id, patch)  → onConnect({source,target})
 * 也就是说：蓝图落图 = 「批量调用既有单步动作」，与 AgentPanel 里
 * `addNode` / `updateNode` / `connectNodes` 三个 case **同一套语义**。
 *
 * `store.ts` 属冻结区 `canvas-magnetic-intent`（不可改），
 * 所以「坐标从哪来」必须由外部给 —— 这正是 blueprintLayout.ts 的职责。
 *
 * ── 为什么要单独一个模块（体积纪律）────────────────────────────────────
 * `AgentPanel.tsx` 已 1805 行（守卫上限 2000 + 容差 30）；
 * `store.ts` 2526 行且是冻结区；`CanvasShell.tsx` 3281 行已触顶。
 * ⇒ **新逻辑一律另开文件**，本文件只放「蓝图 → 画布」的纯逻辑，
 *   AgentPanel 只加一个 `case "applyBlueprint"` 分支。
 *
 * ── 正文落到哪个字段（同名不同义的高频坑）──────────────────────────────
 * 节点 data 里「正文」字段名**随 kind 变**：
 *   script / text / markdown / note → `content`
 *   prompt                          → `text`
 *   其余（shot/image/video/…）      → `prompt`
 * 写错字段 = 内容落空（用户看不到提示词）⇒ 统一走 `blueprintTextField()`。
 */
import {
  layoutBlueprint,
  type BlueprintSpec,
  type BlueprintLayout,
  type BlueprintNodeSpec,
} from "./blueprintLayout";

/** 某 kind 的正文落在哪个 data 字段。 */
export function blueprintTextField(kind: string): string {
  switch (kind) {
    case "script":
    case "text":
    case "markdown":
    case "note":
      return "content";
    case "prompt":
      return "text";
    default:
      return "prompt";
  }
}

/** 落图所需的画布能力（由 store 注入，便于单测）。 */
export interface ApplyBlueprintDeps {
  /** 建节点，返回新节点 id（失败返回空） */
  addNode: (kind: string, pos: { x: number; y: number }) => string | undefined | void;
  /** 写节点 data */
  updateNodeData: (id: string, patch: Record<string, unknown>) => void;
  /** 连线 */
  onConnect: (conn: { source: string; target: string }) => void;
  /** 已存在的节点（用于报告重叠，不强制） */
  existingNodes?: ReadonlyArray<{ id: string; position: { x: number; y: number } }>;
}

export interface ApplyBlueprintResult {
  ok: boolean;
  /** 新建节点 id（按蓝图节点顺序） */
  nodeIds: string[];
  /** 成功连上的边数 */
  edgesApplied: number;
  /** 如实报告的问题 */
  problems: string[];
  /** 布局结果（便于前端展示/调试） */
  layout: BlueprintLayout;
}

/** 组装某个蓝图节点的 data 补丁。 */
export function blueprintNodePatch(node: BlueprintNodeSpec): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  const title = String(node.title ?? "").trim();
  if (title) patch.title = title;
  const body = String(node.prompt ?? "").trim();
  if (body) patch[blueprintTextField(String(node.kind ?? ""))] = body;
  const intent = String(node.intent ?? "").trim();
  if (intent) patch.intent = intent;
  if (node.data && typeof node.data === "object") {
    for (const [k, v] of Object.entries(node.data)) {
      if (v !== undefined && v !== null) patch[k] = v;
    }
  }
  return patch;
}

/**
 * 把蓝图落到画布。
 *
 * 顺序：**先全部建节点 → 再写 data → 最后连线**。
 * 为什么不全建完就连：连线需要两端 id 都已存在，
 * 而 `addNode` 是同步返回 id 的，先建后连可避免半截图。
 */
export function applyBlueprint(
  spec: BlueprintSpec | null | undefined,
  deps: ApplyBlueprintDeps,
): ApplyBlueprintResult {
  const layout = layoutBlueprint(spec);
  const problems = [...layout.problems];
  const nodeIds: string[] = [];
  const idByKey = new Map<string, string>();
  const specByKey = new Map<string, BlueprintNodeSpec>();
  for (const n of Array.isArray(spec?.nodes) ? spec!.nodes : []) {
    const key = String(n?.key ?? "").trim();
    if (key && !specByKey.has(key)) specByKey.set(key, n);
  }

  // ── 建节点 + 写 data ──
  for (const laid of layout.nodes) {
    const id = deps.addNode(laid.kind, { x: laid.x, y: laid.y });
    if (!id) {
      problems.push(`节点「${laid.key}」(${laid.kind}) 创建失败，已跳过`);
      continue;
    }
    idByKey.set(laid.key, id);
    nodeIds.push(id);
    const patch = blueprintNodePatch(specByKey.get(laid.key) ?? { key: laid.key, kind: laid.kind });
    if (Object.keys(patch).length > 0) deps.updateNodeData(id, patch);
  }

  // ── 连线（两端都在蓝图里才连）──
  let edgesApplied = 0;
  for (const e of layout.edges) {
    const s = idByKey.get(e.from);
    const t = idByKey.get(e.to);
    if (!s || !t) {
      problems.push(`跳过连线 ${e.from} → ${e.to}（端点未创建成功）`);
      continue;
    }
    deps.onConnect({ source: s, target: t });
    edgesApplied++;
  }

  // ── 重叠体检（只报告，不强改）──
  if (deps.existingNodes?.length) {
    const boxes = deps.existingNodes.map((n) => n.position);
    for (const laid of layout.nodes) {
      const hit = boxes.find(
        (p) => Math.abs(p.x - laid.x) < 200 && Math.abs(p.y - laid.y) < 180,
      );
      if (hit) {
        problems.push(`蓝图节点「${laid.key}」与已有节点位置接近（可能被压住）`);
        break;
      }
    }
  }

  return {
    ok: nodeIds.length > 0,
    nodeIds,
    edgesApplied,
    problems,
    layout,
  };
}
