/**
 * 配方 · 画布接线层（2026-10-19）
 * ==============================
 * 本文件只做一件事：把 `recipePure.ts` 的纯逻辑接到画布 store 上。
 *
 * 为什么这样拆：
 *   - `store.ts` 属 `canvas-magnetic-intent` 冻结区，但它已公开
 *     `addNode(kind,pos)` / `updateNodeData(id,patch)` / `setSelected(id)` 三个写入口
 *     ⇒ 配方**无需解冻、无需改 store**；
 *   - 纯逻辑放 `recipePure.ts`（零依赖）⇒ vitest 可直测，不必在 node 环境加载 three/react-flow。
 *
 * 两条诚实边界：
 *   1. **只建节点、不建连线**（胶囊卡片靠意图分组组织；专业模式的连线重建待 store 公开 setEdges）
 *   2. **masters 只存 id、暂不解析**（S2 母版层未实现，等它落地后在此接）
 */
import { useCanvasStore } from "./store";
import {
  PARAM_WHITELIST,
  canExtract,
  matchRecipeIn,
  nextOriginFrom,
  paramsFromNode,
  skeletonFromNodes,
  type NodeLike,
  type Recipe,
  type RecipeNode,
  type RecipeParams,
} from "./recipePure";

export type { Recipe, RecipeNode, RecipeParams } from "./recipePure";
export { recipeSummary } from "./recipePure";

export const RECIPES_KEY = "shiguang:recipes:v1";

function uid(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

function readAll(): Recipe[] {
  try {
    const raw = localStorage.getItem(RECIPES_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((r) => r && r.skeleton && r.intent) : [];
  } catch {
    return [];
  }
}

function writeAll(list: Recipe[]): void {
  try {
    localStorage.setItem(RECIPES_KEY, JSON.stringify(list));
  } catch {
    /* localStorage 不可用（隐私模式）不影响内存中的调用方 */
  }
}

/** 当前选中的卡片（与 saveSelectionTemplate 同一套选中语义） */
function currentSelection(): NodeLike[] {
  const st = useCanvasStore.getState();
  const sid = st.selectedId;
  return (st.nodes as unknown as NodeLike[]).filter((n) => n.selected || n.id === sid);
}

/**
 * 从「当前选中的一组卡片」提炼配方：只取**类型与相对位置**，
 * 丢弃 id / 生成结果 / 运行状态 —— 这是它与 `saveSelectionTemplate` 的分水岭。
 */
export function recipeFromSelection(meta: {
  name: string;
  stage: Recipe["intent"]["stage"];
  kind: string;
  goal: string;
}): Recipe | null {
  const picked = currentSelection();
  if (!canExtract(picked)) return null;

  return {
    id: uid("rcp"),
    name: meta.name.trim() || "未命名配方",
    createdAt: new Date().toISOString(),
    intent: { stage: meta.stage, kind: meta.kind, goal: meta.goal },
    params: paramsFromNode(picked[0]),
    masters: {},
    skeleton: { nodes: skeletonFromNodes(picked) },
    stats: { uses: 0 },
  };
}

/** 保存（同名覆盖，避免攒出「未命名配方 2/3/4」） */
export function saveRecipe(recipe: Recipe): void {
  const list = readAll();
  const idx = list.findIndex((r) => r.name === recipe.name);
  if (idx >= 0) list[idx] = recipe;
  else list.unshift(recipe);
  writeAll(list);
}

export function listRecipes(): Recipe[] {
  return readAll();
}

export function deleteRecipe(id: string): void {
  writeAll(readAll().filter((r) => r.id !== id));
}

/**
 * 把配方落到画布：逐张重建节点 + 写白名单参数。
 * **不替换画布**（与 `loadTemplate` 的第二个分水岭），落点在现有内容右侧。
 * 返回新建节点 id 列表（供选中 / 提示 / Agent 后续处理）。
 */
export function applyRecipe(
  recipe: Recipe,
  opts: { at?: { x: number; y: number } } = {},
): string[] {
  const st = useCanvasStore.getState();
  const origin = opts.at ?? nextOriginFrom(st.nodes.map((n) => n.position));
  const ids: string[] = [];

  for (const n of recipe.skeleton.nodes) {
    const id = st.addNode(n.kind as never, { x: origin.x + n.dx, y: origin.y + n.dy });
    const patch: Record<string, unknown> = {};
    for (const k of PARAM_WHITELIST) {
      const v = recipe.params[k];
      if (v !== undefined) patch[k] = v;
    }
    if (Object.keys(patch).length > 0) st.updateNodeData(id, patch);
    ids.push(id);
  }

  const list = readAll();
  const hit = list.find((r) => r.id === recipe.id);
  if (hit) {
    hit.stats.uses = (hit.stats.uses || 0) + 1;
    hit.stats.lastUsed = new Date().toISOString();
    writeAll(list);
  }

  if (ids.length > 0) st.setSelected(ids[0]);
  return ids;
}

/**
 * 一句话 → 配方（关键词匹配，不引 LLM）。
 * 匹配不到**诚实返回 null**，由调用方提示「要不要存一个」，绝不硬编凑数。
 */
export function matchRecipeByIntent(text: string): Recipe | null {
  return matchRecipeIn(readAll(), text);
}
