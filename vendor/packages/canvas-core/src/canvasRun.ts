/**
 * canvasRun.ts — 「运行到此处」桥（刀 A4 第 3 项，2026-10-05）。
 *
 * **后端早就建好了，缺的是前端调用**：
 *   · `POST /host/canvas-run` → `app/core/canvas_workflow_runner.run_graph`
 *     —— 已具备拓扑序（`topo_order`/`is_dag`）、**指纹增量缓存**（`canvas_node_cache`：
 *     同参数不重抽、改一处只重跑下游）、端口问题报告、`counters` 统计、
 *     以及**默认 `dry_run=True`（只出计划、不烧额度）**的「确认后执行」语义。
 *   · 配套 `POST /host/canvas-cache`（stats/clear）管理增量缓存。
 *
 * 所以本文件**只是接线**，不重算任何图逻辑（图推理的单一真源在后端）。
 * 参数形状与画布工程一致：`{graph: {nodes, edges}}`。
 *
 * 「确认」闸门：`dry_run` 缺省 true ⇒ 只拿计划；用户确认后才以 `dry_run:false` 真跑。
 * ⚠️ 注意后端按「**显式 false**」判定（`bool("false") === true` 是 JS/Python 都踩过的坑），
 * 故这里只在明示执行时才发 `false`。
 */
import { BRIDGE, bridgeToken } from "./bridge";

export interface RunCounters {
  total: number;
  planned: number;
  skipped: number;
  done: number;
  cached: number;
  failed: number;
}

export interface RunNodeRef {
  node_id?: string;
  id?: string;
  kind?: string;
  title?: string;
  status?: string;
  reason?: string;
  [k: string]: unknown;
}

export interface RunResult {
  ok: boolean;
  dry_run?: boolean;
  use_cache?: boolean;
  order?: string[];
  planned?: RunNodeRef[];
  executed?: RunNodeRef[];
  skipped?: RunNodeRef[];
  outputs?: Record<string, unknown>;
  counters?: RunCounters;
  port_problems?: Array<Record<string, unknown>>;
  cyclic?: string[];
  cache?: Record<string, unknown> | null;
  note?: string;
  message?: string;
}

export interface RunGraphArgs {
  graph: { nodes: unknown[]; edges: unknown[] };
  /** true（默认）= 只出计划；false = 真执行（消耗额度） */
  dryRun?: boolean;
  /** 增量缓存：同参数不重抽（默认开） */
  useCache?: boolean;
  quality?: string;
  aspect?: string;
}

/** 调后端跑图（或只出计划）。网络/契约异常一律返回 `ok:false`，不抛。 */
export async function runCanvasGraph(args: RunGraphArgs): Promise<RunResult> {
  try {
    const payload: Record<string, unknown> = {
      graph: args.graph,
      use_cache: args.useCache !== false,
    };
    // 只在明示执行时发 dry_run=false（后端按「显式 false」判定）
    if (args.dryRun === false) payload.dry_run = false;
    if (args.quality) payload.quality = args.quality;
    if (args.aspect) payload.aspect = args.aspect;

    const res = await fetch(`${BRIDGE}/host/canvas-run`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Shiguang-Token": bridgeToken() },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data || typeof data !== "object") {
      return { ok: false, message: "后端返回非法数据" };
    }
    return data as RunResult;
  } catch (e) {
    return { ok: false, message: `运行请求失败: ${e instanceof Error ? e.message : String(e)}` };
  }
}

/**
 * 把 dry_run 计划格式化成「给用户看的一屏」文本（**纯函数，可单测**）。
 *
 * 为什么单独抽出来：计划明细要摆给用户看（付费几个、增量跳过几个、哪些节点），
 * 而不是问一句"要执行吗"。抽成纯函数后 App.tsx 只负责调用，也便于测试措辞稳定性。
 */
export function formatPlanForConfirm(plan: RunResult): string {
  const c = plan.counters || {
    total: 0, planned: 0, skipped: 0, done: 0, cached: 0, failed: 0,
  };
  const lines = [
    `执行计划（共 ${c.total} 个节点）`,
    `  待执行 ${c.planned} · 增量跳过 ${c.skipped}`,
    ...(plan.planned || [])
      .slice(0, 12)
      .map((n, i) => `  ${i + 1}. [${n.kind || "?"}] ${n.title || n.node_id || ""}`),
  ];
  if ((plan.planned || []).length > 12) {
    lines.push(`  …另有 ${(plan.planned || []).length - 12} 个`);
  }
  if (plan.port_problems && plan.port_problems.length) {
    lines.push(`⚠️ 端口问题 ${plan.port_problems.length} 处（只报告不阻断）`);
  }
  lines.push("", "确认执行？将真实消耗生成额度，可能耗时数分钟。");
  return lines.join("\n");
}

/** 执行结果摘要（纯函数）。 */
export function summarizeResult(res: RunResult): string {
  const c = res.counters || {
    total: 0, planned: 0, skipped: 0, done: 0, cached: 0, failed: 0,
  };
  if (!res.ok) return `执行失败：${res.message || "未知原因"}`;
  return `执行完成：成功 ${c.done} · 命中缓存 ${c.cached} · 跳过 ${c.skipped} · 失败 ${c.failed}`;
}

/** 把执行结果映射成「节点 id → 状态补丁」（纯函数；前端只负责写回 store）。 */
export function resultToNodePatches(
  res: RunResult,
): Array<{ id: string; patch: Record<string, unknown> }> {
  const out: Array<{ id: string; patch: Record<string, unknown> }> = [];
  for (const e of res.executed || []) {
    const id = String(e.node_id || e.id || "");
    if (!id) continue;
    if (e.status === "done" || e.status === "cached") {
      out.push({ id, patch: { status: "success" } });
    } else if (e.status === "failed") {
      out.push({
        id,
        patch: {
          status: "failed",
          errorMessage: String(e.reason || e.message || "失败").slice(0, 200),
        },
      });
    }
  }
  return out;
}

export interface RunWithConfirmHooks {
  getGraph: () => { nodes: unknown[]; edges: unknown[] };
  /** 确认回调（返回 false 表示用户取消） */
  confirm: (text: string) => boolean;
  onStatus: (text: string) => void;
  onNodePatch: (id: string, patch: Record<string, unknown>) => void;
  onBusy?: (busy: boolean) => void;
}

/**
 * 「运行到此处」完整编排：**出计划 → 确认 → 执行 → 回写节点状态**。
 *
 * 放在本模块而不是 App.tsx 的原因（两件都真实发生）：
 *  ① App.tsx 已顶到单文件规模守卫 2000 行，新增必然破门禁 ⇒ 按项目规矩**拆模块**；
 *  ② 编排本身是纯逻辑（只通过 hooks 与 UI 交互）⇒ 可单测，不必拉 React。
 * 图推理/执行仍在后端（`run_graph`），这里只是**接线 + 确认闸门**。
 */
export async function runGraphWithConfirm(
  hooks: RunWithConfirmHooks,
): Promise<{ ok: boolean; message: string }> {
  const graph = hooks.getGraph();
  if (!graph.nodes.length) {
    const msg = "画布为空，无从运行";
    hooks.onStatus(msg);
    return { ok: false, message: msg };
  }
  hooks.onStatus("正在向后端要执行计划（dry_run，不消耗额度）…");
  const plan = await runCanvasGraph({ graph, dryRun: true });
  if (!plan.ok) {
    const msg = `无法出计划：${plan.message || "未知原因"}`;
    hooks.onStatus(msg);
    return { ok: false, message: msg };
  }
  const planned = plan.counters?.planned ?? (plan.planned || []).length;
  if (planned === 0) {
    const msg = `没有需要执行的节点（跳过 ${plan.counters?.skipped ?? 0} 个）`;
    hooks.onStatus(msg);
    return { ok: true, message: msg };
  }
  if (!hooks.confirm(formatPlanForConfirm(plan))) {
    const msg = "已取消（未产生任何调用）";
    hooks.onStatus(msg);
    return { ok: false, message: msg };
  }
  hooks.onStatus(`正在执行（${planned} 个节点，可能数分钟）…`);
  hooks.onBusy?.(true);
  try {
    const res = await runCanvasGraph({ graph, dryRun: false, useCache: true });
    for (const { id, patch } of resultToNodePatches(res)) {
      hooks.onNodePatch(id, patch);
    }
    const msg = summarizeResult(res);
    hooks.onStatus(msg);
    return { ok: Boolean(res.ok), message: msg };
  } finally {
    hooks.onBusy?.(false);
  }
}

/**
 * 增量缓存统计（供设置面板/诊断展示）。
 *
 * ⚠️ 契约：后端 `/host/canvas-cache` 注册的是 **POST**（body `{action:"stats"|"clear"}`），
 * 不是 GET —— 我第一版写成 GET，被升级后的路由守卫当场拦下（`[1b] 方法错配`）。
 */
export async function fetchCanvasCacheStats(): Promise<Record<string, unknown>> {
  try {
    const res = await fetch(`${BRIDGE}/host/canvas-cache`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Shiguang-Token": bridgeToken() },
      body: JSON.stringify({ action: "stats" }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: String(e) };
  }
}
