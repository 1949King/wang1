/**
 * previewPlayer.ts — 连线时序预览的纯函数层（V4.41.16）。
 *
 * 「预览」按钮此前是占位（fitView + 提示），本刀做成真功能：
 * 按连线的拓扑层级从上游到下游逐节点高亮，播放当前工作流的执行顺序。
 *
 * 为什么单独纯函数层（同 mascotMotion 的分层理由）：
 * 排序正确性可以在 vitest 里毫秒级验证，不用起画布。
 *
 * 排序口径
 * ========
 *  - Kahn 分层：入度 0 的节点为第 1 层，逐层剥除；同层内按**画布位置**
 *    （y 主 x 辅）排序 —— 与人眼看画布的阅读顺序一致；
 *  - 环：连线成环时剩余节点不再有入度 0，**不丢弃**，按位置序附在末尾
 *    （预览是视觉辅助，宁可将环整体走一遍也不静默漏掉节点）；
 *  - 自环 / 指向不存在节点的边：直接忽略（坏数据不炸预览）。
 */

export interface PreviewNode {
  id: string;
  x: number;
  y: number;
}

export interface PreviewEdge {
  source: string;
  target: string;
}

/**
 * 返回按拓扑层级排好的节点 id 序列（上游 → 下游）。
 * 空画布返回 []。
 */
export function previewOrder(nodes: PreviewNode[], edges: PreviewEdge[]): string[] {
  const ids = (nodes || []).filter((n) => n?.id).map((n) => String(n.id));
  if (!ids.length) return [];

  const byPos = new Map<string, PreviewNode>();
  for (const n of nodes) byPos.set(String(n.id), n);

  const idSet = new Set(ids);
  // 邻接表 + 入度（忽略坏边）
  const indeg = new Map<string, number>();
  const out = new Map<string, string[]>();
  for (const id of ids) {
    indeg.set(id, 0);
    out.set(id, []);
  }
  for (const e of edges || []) {
    const s = String(e?.source || "");
    const t = String(e?.target || "");
    if (!idSet.has(s) || !idSet.has(t) || s === t) continue;
    out.get(s)!.push(t);
    indeg.set(t, (indeg.get(t) || 0) + 1);
  }

  const byCanvasPos = (a: string, b: string) => {
    const na = byPos.get(a);
    const nb = byPos.get(b);
    const ya = na?.y ?? 0;
    const yb = nb?.y ?? 0;
    if (ya !== yb) return ya - yb;
    return (na?.x ?? 0) - (nb?.x ?? 0);
  };

  // Kahn 分层：每层内按画布位置排序
  let layer = ids.filter((id) => (indeg.get(id) || 0) === 0);
  const order: string[] = [];
  const seen = new Set<string>();
  while (layer.length) {
    layer.sort(byCanvasPos);
    for (const id of layer) {
      if (!seen.has(id)) {
        seen.add(id);
        order.push(id);
      }
    }
    const next: string[] = [];
    for (const id of layer) {
      for (const t of out.get(id) || []) {
        const d = (indeg.get(t) || 0) - 1;
        indeg.set(t, d);
        if (d === 0) next.push(t);
      }
    }
    layer = next.filter((id) => !seen.has(id));
  }

  // 环上的节点：按位置序附在末尾（不丢弃）
  for (const id of ids) {
    if (!seen.has(id)) {
      seen.add(id);
      order.push(id);
    }
  }
  return order;
}

/** 预览推进间隔（ms/节点）。够人看清每个节点，又不至于太拖沓。 */
export const PREVIEW_STEP_MS = 900;
