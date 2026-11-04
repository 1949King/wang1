/**
 * 画布「工程快照回滚栈」桥（Wave 0 #13 孤儿端点接线第 5 条，2026-10-15）
 * ======================================================
 * 缺口证据：
 *  - `app/core/canvas_server.py:1366` `@_route_get("/host/project-snapshot/history")`
 *    返回 `SnapshotStore.list()`（回滚栈列表，最新在前）。
 *  - `app/core/canvas_server.py:1373` `@_route_post("/host/project-snapshot/restore")`
 *    按 `snapshot_id` 把整条时间线写回剪辑器（`write_clips`）。
 *  两端点前端**零调用**。
 *
 * 为什么这是真缺口（不是「后端备着不用」的冗余）：
 *  `project-snapshot/import`（前端 `projectZip.ts:300pushTimelineToEditor` 走它）
 *  是**破坏性操作** —— 它调 `write_clips(clips)` **整体覆盖**剪辑器时间线
 *  （真相源 `EditorModule._clips`）。后端很清楚这一点，所以在 import 里
 *  **自动 push 了一条「导入前自动快照」**（canvas_server.py:1353-1354）——
 *  后端自己都认为「导错了要能退」，但**前端没有任何回滚入口**。
 *  ⇒ 用户导入错了只能重开工程包。
 *
 * ⚠️ 诚实边界（本文件的硬纪律）：
 *  1. 🔴 **后端文档漂移，实测以代码为准**：`SnapshotStore` 的类docstring
 *     （`app/core/project_snapshot.py:130-131`）说「每次『导出工程快照』自动 push 一条」，
 *     但 `canvas_server.py` 的 `/host/project-snapshot/export` 端点**并没有**调 `push`
 *     —— 全库 `get_snapshot_store()` 只有 3 处调用，全在 history / restore / import。
 *     ⇒ **实际上只有 `import` 会长栈**（且 label 固定「导入前自动快照」）。
 *     所以栈通常是**空的或只有 1 条**，这是真实状态不是 bug。UI 要如实说「暂无回滚点」
 *     并**告诉用户怎么产生回滚点**（导一次工程包），不能让人干等。
 *     （本文件不去改后端 —— 那是另一个话题：要么补 export 的 push，要么改 docstring。
 *     先让前端把已有能力露出来。）
 *  2. `list()` 返回的字段只有 `id` / `label` / `taken_at` / `clip_count` / `meta`，
 *     **没有 clips**（`SnapshotStore.list` 白名单裁剪）—— 前端不能指望从列表拿到片段。
 *  3. 🔴 **回滚不可再回滚**：`restore` 端点**自己不push**，前端也没有 push 端点
 *     ⇒ 一旦回滚，**回滚前的时间线状态就找不回来了**。
 *     这是真实且不可绕过的限制（除非给后端补一个 push 端点）。
 *     ⇒ UI **必须在回滚前显式警告这一点**，不能只写「确定回滚吗」。
 *     唯一的兜底路径是「先导出工程包」—— `exportProjectZip` 会带上完整时间线
 *     （`projectZip.ts:279fetchProjectTimeline`），导错了还能再导回来。
 */
import { BRIDGE, authHeaders, bridgeToken } from "./bridge";

/** 一条回滚点（镜像 `SnapshotStore.list()` 的行 —— 注意**不含 clips**） */
export type SnapshotRow = {
  id: string;
  label: string;
  taken_at?: string;
  clip_count?: number;
  meta?: Record<string, unknown>;
};

export type SnapshotListResult = {
  ok: boolean;
  snapshots: SnapshotRow[];
  message?: string;
};

export type SnapshotRestoreResult = {
  ok: boolean;
  message?: string;
  restored?: number;
};

/** 拉回滚栈。**永不抛**：拿不到返回空栈 + message，UI 回落到「暂无回滚点」。 */
export async function listSnapshots(): Promise<SnapshotListResult> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/project-snapshot/history?token=${encodeURIComponent(token)}`,
      { headers: authHeaders(false) },
    );
    const data = await res.json();
    // ⚠️ 后端 list() 返回的是 list 而非 {snapshots:[...]}？—— 端点自己包了一层
    //   {"ok": True, "snapshots": store.list()}。这里仍做**双形态兼容**：
    //   后端若哪天改成直接返回数组，前端也不炸。
    const rows = Array.isArray(data) ? data : Array.isArray(data?.snapshots) ? data.snapshots : [];
    return { ok: data?.ok !== false, snapshots: rows.filter((r: SnapshotRow) => r && r.id) };
  } catch (e) {
    return { ok: false, snapshots: [], message: `回滚栈拉取失败: ${e}` };
  }
}

/** 回滚到某条快照（**破坏性**：覆盖剪辑器整条时间线，UI 必须先显式确认）。 */
export async function restoreSnapshot(snapshotId: string): Promise<SnapshotRestoreResult> {
  const id = String(snapshotId || "").trim();
  if (!id) return { ok: false, message: "缺少 snapshot_id" };
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/project-snapshot/restore?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ snapshot_id: id }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `回滚失败: ${e}` };
  }
}

// ── 纯函数（vitest 无 jsdom，逻辑抽出来才可测）────────────────────────

/**
 * 一行回滚点的展示文案。
 * ⚠️ `taken_at` 是 ISO 串；解析失败**如实显示原串**，不显示「Invalid Date」。
 */
export function snapshotRowLabel(row: SnapshotRow): string {
  const label = String(row?.label || "").trim() || "未命名快照";
  const n = row?.clip_count;
  const count = typeof n === "number" ? `${n} 片段` : "";
  const raw = String(row?.taken_at || "").trim();
  let time = "";
  if (raw) {
    const d = new Date(raw);
    // Number.isNaN(d.getTime()) ⇒ 无效日期，回落原串（不编造时间）
    time = Number.isNaN(d.getTime()) ? raw : d.toLocaleString();
  }
  return [label, count, time].filter(Boolean).join(" · ");
}

/**
 * 回滚前的**红线自检**（纯函数）：这个快照能不能安全回滚？
 * 返回不可回滚的原因；`null` = 可回滚。
 *
 * 三条判据（少一条都必须拦下）：
 *  ① 栈为空 ⇒ 没什么可回滚（防用户点了空栈的「回滚」按钮）。
 *  ② 目标 id 不在栈里 ⇒ 后端会回 404「快照不存在」，不如前端先拦并说清。
 *  ③ 目标 clip_count 为 0 ⇒ 回滚等于「清空时间线」。这可能是有意的
 *     （导入了坏包想清干净），但**必须让用户明确确认** ⇒ 交 UI 二次确认。
 */
export function snapshotRestoreBlocker(
  snapshots: SnapshotRow[] | undefined,
  targetId: string,
): string | null {
  const rows = snapshots || [];
  if (!rows.length) return "暂无回滚点（回滚栈只在导入/导出工程包时生成）";
  const id = String(targetId || "").trim();
  if (!id) return "未选择回滚点";
  const hit = rows.find((r) => r && r.id === id);
  if (!hit) return "该回滚点已不在栈中（可能栈已超出上限被裁掉）";
  if (hit.clip_count === 0) return "⚠️ 该回滚点记录的是 0 片段，回滚会清空整条时间线";
  return null;
}

/**
 * 是否需要**二次确认**（破坏性操作）。
 * 判据：任何回滚都是覆盖式写入 ⇒ 一律要确认；
 * 若 blocker 里带 ⚠️（0 片段/清空时间线），提示文案要更重（由 UI 负责加前缀）。
 */
export function snapshotRestoreNeedsConfirm(snapshots: SnapshotRow[] | undefined, targetId: string): boolean {
  // 有 blocker ⇒ 根本不该进确认流程（先拦下）
  if (snapshotRestoreBlocker(snapshots, targetId)) return false;
  return true;
}

/** 一行状态文案：成功逐字用后端 message（后端已带「已回滚到快照「x」（N 片段）」）。 */
export function snapshotRestoreHeadline(res: SnapshotRestoreResult | null): string {
  if (!res) return "";
  if (!res.ok) return res.message || "回滚失败";
  return res.message || (typeof res.restored === "number" ? `已回滚（${res.restored} 片段）` : "已回滚");
}