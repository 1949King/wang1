/**
 * 时间线回滚编排（Wave 0 #13 第 5 条，2026-10-15）
 * ======================================================
 * 为什么单独成文件：`App.tsx` 已 1964/2000 顶格（余量36 行）⇒ 按纪律
 * 「超容差必须拆模块、不得放宽基线」，回滚的交互编排整块搬这里，
 * `App.tsx` 只留一行薄调用（与 `editorIngress` / `hostBatchOps` 同一套路）。
 *
 * 交互流程（全部如实呈现，不夸大能力）：
 *  1. 拉回滚栈；空 ⇒ **如实说「暂无回滚点」并告诉用户怎么产生**（导一次工程包），
 *     不弹一个空列表让人干瞪眼。
 *  2. 用 `window.prompt` 让用户从列表里选一个（节点/面板级功能，不值得单开一个浮层；
 *     且项目内已有 prompt/confirm 先例）。
 *  3. **红线自检**（`snapshotRestoreBlocker`）拦下不安全的目标（0 片段会清空时间线）。
 *  4. 二次确认，且**必须写明「回滚不可再回滚」** ——
 *     🔴 `restore` 端点自己不 push，前端也没有 push 端点
 *     ⇒ 回滚前的时间线状态**找不回来了**，唯一兜底是先导出工程包。
 */
import {
  listSnapshots,
  restoreSnapshot,
  snapshotRestoreBlocker,
  snapshotRestoreHeadline,
  snapshotRowLabel,
  type SnapshotRow,
} from "./hostSnapshots";

export type RollbackDeps = {
  /** 统一走画布状态栏（与工程级其它操作同一条文案通道） */
  setStatus: (s: string) => void;
  /** 拉工程包（用于「先导出再回滚」的兜底建议）；不可用时降级为只提示 */
  onExportZip?: () => void;
};

export type RollbackOutcome =
  | { action: "none"; reason: "empty" | "cancelled" | "blocked" | "failed" }
  | { action: "restored"; message: string; row: SnapshotRow };

/** 把栈渲染成 prompt 可读的编号列表（纯函数，便于测试与复用）。 */
export function renderStackChoices(rows: SnapshotRow[]): string {
  return rows
    .map((r, i) => `${i + 1}. ${snapshotRowLabel(r)}`)
    .join("\n");
}

/** 从用户输入里解析出目标行（纯函数）。 */
export function parseChoice(input: string, rows: SnapshotRow[]): SnapshotRow | null {
  const raw = String(input || "").trim();
  if (!raw) return null;
  const n = Number(raw);
  if (Number.isInteger(n) && n >= 1 && n <= rows.length) return rows[n - 1];
  // 也接受直接贴 id
  return rows.find((r) => r.id === raw) || null;
}

/**
 * 在「刚直导完时间线」的时刻问用户要不要回滚。
 * 返回实际发生了什么（UI/日志可据此提示），**永不抛**。
 */
export async function offerTimelineRollback(deps: RollbackDeps): Promise<RollbackOutcome> {
  const { setStatus } = deps;
  const list = await listSnapshots();
  if (!list.ok && !list.snapshots.length) {
    setStatus(`回滚栈拉取失败：${list.message || "未知错误"}`);
    return { action: "none", reason: "failed" };
  }
  if (!list.snapshots.length) {
    // ⚠️ 如实说，并给出**可执行**的下一步（导一次工程包就会产生回滚点）
    setStatus(
      "暂无回滚点（回滚栈只在「导入工程包直导时间线」时自动生成；下次导入后这里就能退）",
    );
    return { action: "none", reason: "empty" };
  }

  setStatus(
    `刚直导了时间线。后端已留 ${list.snapshots.length} 个回滚点（只增不改）：\n${renderStackChoices(list.snapshots)}\n输入编号回滚，直接回车放弃。`,
  );
  const answer = window.prompt("回滚到哪个快照？（输入编号；回车放弃）", "");
  if (answer === null) {
    setStatus("已放弃回滚（时间线保持直导后的状态）");
    return { action: "none", reason: "cancelled" };
  }
  const row = parseChoice(answer, list.snapshots);
  if (!row) {
    setStatus(`未识别「${answer}」，已放弃回滚`);
    return { action: "none", reason: "cancelled" };
  }

  const blocker = snapshotRestoreBlocker(list.snapshots, row.id);
  if (blocker) {
    setStatus(`不能回滚：${blocker}`);
    return { action: "none", reason: "blocked" };
  }

  //🔴 二次确认必须写明不可逆 + 唯一兜底
  const warn =
    `回滚到「${snapshotRowLabel(row)}」？\n\n` +
    `⚠️ 回滚会**覆盖**剪辑器当前整条时间线。\n` +
    `⚠️ 且**回滚不可再回滚**：后端没有「压快照」端点，回滚前的状态找不回来。\n` +
    `唯一兜底：如果还没导出，建议先导出工程包（含完整时间线）再回滚。`;
  if (!window.confirm(warn)) {
    setStatus("已放弃回滚（时间线未改动）");
    return { action: "none", reason: "cancelled" };
  }

  const res = await restoreSnapshot(row.id);
  const msg = snapshotRestoreHeadline(res);
  setStatus(res.ok ? `⏪ ${msg}` : `回滚失败：${msg}`);
  if (!res.ok) return { action: "none", reason: "failed" };
  // 成功后建议导一份（此刻时间线是回滚后的状态，导出即新的安全点）
  if (deps.onExportZip) {
    setStatus(`⏪ ${msg} · 建议现在导出一份工程包（它会成为新的回滚参照）`);
  }
  return { action: "restored", message: msg, row };
}