/**
 * teamDiffText.ts — 把版本差异摘要变成人话（2026-11-02）
 *
 * 为什么单独成文件：`TeamPanel.tsx` 已经背了面板 + 上传 + 素材三段逻辑，
 * 再塞文案拼装就该拆了；而且这段是**纯函数**，可以单测（面板里没法测）。
 *
 * 写作纪律：**先说「你要不要紧」，再说细节**。使用者点「拉取」那一瞬间最想知道的
 * 是「我会不会丢掉正在做的事」，不是「added=3 removed=1」。
 */
import type { TeamDiff } from "./teamClient";

/** 差异是否为空（只有版本号变了、内容没变）。 */
export function diffIsEmpty(d: TeamDiff): boolean {
  if (!d || d.same) return true;
  const n = d.nodes || ({} as NonNullable<TeamDiff["nodes"]>);
  const e = d.edges || { added: 0, removed: 0 };
  const t = d.timeline || { before: 0, after: 0, added: 0, removed: 0, changed: 0 };
  return (
    !n.added && !n.removed && !n.changed &&
    !e.added && !e.removed &&
    !t.added && !t.removed && !t.changed &&
    !d.title?.changed
  );
}

/** 一句话说清「落后多少」。 */
export function diffHeadline(d: TeamDiff, myRev: number): string {
  if (d.same) return "服务器和你手上是同一版，没有新东西";
  if (!myRev) {
    return `本地没有版本记录（可能在别处改过），服务器最新是 rev ${d.to_rev}`;
  }
  if (d.revisions <= 0) return `你在 rev ${myRev}，服务器 rev ${d.to_rev}`;
  return `你在 rev ${myRev}，服务器已经到 rev ${d.to_rev} —— 别人改了 ${d.revisions} 版`;
}

/**
 * 多行差异摘要（直接丢进 confirm / 状态行）。
 *
 * 标题只列前 6 个（后端已经截断），超出由后端计数兜住 —— 不在这里编「等 N 个」，
 * 因为后端没回被截掉的名单长度。
 */
export function formatTeamDiff(d: TeamDiff, myRev: number): string {
  const lines: string[] = [diffHeadline(d, myRev)];
  if (diffIsEmpty(d)) return lines[0];

  const n = d.nodes || ({} as NonNullable<TeamDiff["nodes"]>);
  if (n.added || n.removed || n.changed) {
    const bits: string[] = [];
    if (n.added) bits.push(`新增 ${n.added}`);
    if (n.removed) bits.push(`删除 ${n.removed}`);
    if (n.changed) bits.push(`改动 ${n.changed}`);
    lines.push(`· 节点：${bits.join("、")}`);
    if (n.added_titles?.length) lines.push(`    新增：${n.added_titles.join("、")}`);
    if (n.changed_titles?.length) lines.push(`    改过：${n.changed_titles.join("、")}`);
    if (n.removed_titles?.length) lines.push(`    删掉：${n.removed_titles.join("、")}`);
  } else {
    lines.push("· 节点：没动");
  }

  const e = d.edges;
  if (e && (e.added || e.removed)) {
    lines.push(`· 连线：+${e.added} / -${e.removed}`);
  }

  const t = d.timeline;
  if (t && (t.added || t.removed || t.changed)) {
    const bits: string[] = [];
    if (t.added) bits.push(`新增 ${t.added} 段`);
    if (t.removed) bits.push(`删除 ${t.removed} 段`);
    if (t.changed) bits.push(`改动 ${t.changed} 段`);
    lines.push(`· 剪辑时间线：${bits.join("、")}（${t.before} → ${t.after} 段）`);
  } else if (t && (t.before || t.after)) {
    lines.push(`· 剪辑时间线：${t.before} 段，没动`);
  }

  if (d.title?.changed) {
    lines.push(`· 工程名：${d.title.before || "（空）"} → ${d.title.after || "（空）"}`);
  }
  return lines.join("\n");
}
