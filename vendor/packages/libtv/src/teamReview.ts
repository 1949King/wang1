/**
 * 评审意见的纯计算（2026-11-04）
 *
 * 面板只管画，判断放这里 —— 这样「哪些算待处理」「一条意见说的是哪个节点」
 * 这些容易写错的逻辑能单测，而不用起 Qt 去点。
 *
 * 三个必须说准的地方：
 *   ① **未解决 vs 已解决要分开**，而且默认只看未解决 —— 混在一起时人永远在
 *      一屏里翻旧账，最后干脆不看；
 *   ② **锚点要说人话**：`node_id` 是 `n1` 这种机器 id，界面上得能说成
 *      「镜 03」；说不出来就说「整份画布」，别把 id 糊到脸上；
 *   ③ **时间要说相对**：「12 分钟前」比「11-04 20:31」有用，但**不能出现
 *      「0 分钟前」**（刚提的就是「刚刚」）。
 */
import type { TeamComment } from "./teamClient";

export type CommentBuckets = {
  open: TeamComment[];
  done: TeamComment[];
};

/** 按「解决没解决」分组，各自按时间正序（先说的事先看）。 */
export function groupComments(list: TeamComment[] | undefined): CommentBuckets {
  const open: TeamComment[] = [];
  const done: TeamComment[] = [];
  for (const c of list || []) {
    if (!c) continue;
    (c.resolved ? done : open).push(c);
  }
  const byTime = (a: TeamComment, b: TeamComment) => (a.created_at || 0) - (b.created_at || 0);
  open.sort(byTime);
  done.sort(byTime);
  return { open, done };
}

/** 「3 条待处理 · 12 条已解决」；都为 0 时说「还没有人提意见」。 */
export function reviewSummary(list: TeamComment[] | undefined): string {
  const { open, done } = groupComments(list);
  if (!open.length && !done.length) return "还没有人提意见";
  const parts: string[] = [];
  if (open.length) parts.push(`${open.length} 条待处理`);
  if (done.length) parts.push(`${done.length} 条已解决`);
  return parts.join(" · ");
}

/**
 * 一条意见挂在哪：有 `nodeLabel` 就用它（「镜 03」），没有就给「整份画布」。
 *
 * 特意**不回退到 node_id**：`n1` 对用户是没有意义的字符串，显示它只会让人
 * 以为哪里坏了。丢了标签就是「某一处」，也比露出内部 id 强。
 */
export function anchorText(c: TeamComment | undefined, nodeLabel = ""): string {
  if (!c) return "整份画布";
  if (!c.node_id) return "整份画布";
  return nodeLabel || "某一处";
}

/** 相对时间。超过 7 天给日期 —— 「23 天前」没人换算得过来。 */
export function agoText(sec: number, nowSec: number): string {
  const t = Number(sec) || 0;
  const now = Number(nowSec) || 0;
  if (t <= 0) return "";
  const gap = Math.max(0, now - t);
  if (gap < 60) return "刚刚";
  if (gap < 3600) return `${Math.floor(gap / 60)} 分钟前`;
  if (gap < 86400) return `${Math.floor(gap / 3600)} 小时前`;
  if (gap < 86400 * 7) return `${Math.floor(gap / 86400)} 天前`;
  const d = new Date(t * 1000);
  if (!Number.isFinite(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 意见出现在哪一版：「第 2 版」；0（不知道）时说空串，不编一个版本号出来。 */
export function revText(c: TeamComment | undefined): string {
  const rev = Number(c?.rev) || 0;
  return rev > 0 ? `第 ${rev} 版` : "";
}

/**
 * 当前能对哪个节点提意见：有选中节点就说「这个节点」，没有就是整份画布。
 *
 * 注意**不阻止**没选中时提意见 —— 「整体色调偏冷」这种意见本来就针对整份画布，
 * 强行要求先选一个节点会把最正常的一类意见挡掉。
 */
export function composeTarget(selectedId: string | null | undefined, nodeLabel = ""): {
  nodeId: string;
  label: string;
} {
  const id = String(selectedId || "").trim();
  if (!id) return { nodeId: "", label: "整份画布" };
  return { nodeId: id, label: nodeLabel || "选中这一处" };
}
