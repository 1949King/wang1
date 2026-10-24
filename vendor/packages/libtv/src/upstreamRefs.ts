/**
 * upstreamRefs.ts — 「连线上游素材引用」（2026-10-06 对标 AI Canvas 0.9.21 / LibTV 智能引用）。
 *
 * 上游怎么做（参考产品 0.9.21）：「连线后自动 @ 上游素材，开启后自动把上游素材引用写入提示词；
 * 删除连线时同步移除提示词里的引用」。
 *
 * **我们不做它那种"往提示词里塞 @ 文本"** —— 因为那是装饰：模型看不到。
 * 我们的生成侧有**真实引用通道**（`App.tsx` 里 `reference_image = data.firstFrameUrl || assetRef`
 * 会真的传给模型）⇒ 所以这里做的是：**把上游节点的产物写进下游节点的 `firstFrameUrl`**。
 * 这才是"引用"，而不是"提示词里写了个 @ 名字"。
 *
 * 三条安全规则（都不可省）
 * ======================
 *  ① **绝不覆盖用户选的**：只在 `firstFrameUrl` 为空时才写；已有值就跳过（那是用户的选择）。
 *  ② **可对称撤销**：写的时候打标记 `refUpstreamOf = <上游 id>`；连线断了**只清我们自己写的**
 *     （标记对得上才清），用户自己设的首帧永远不动。
 *  ③ **幂等收敛**：`planUpstreamRefs` 只产出"真的有变化"的补丁 ⇒ 订阅重算不会自激。
 *
 * 默认**关闭**（`enabled=false`）：这是**行为变更**，不该在用户没同意时偷偷改提示词/首帧。
 */
export interface RefNode {
  id: string;
  data?: Record<string, unknown>;
}

export interface RefEdge {
  source: string;
  target: string;
}

export interface NodePatch {
  id: string;
  patch: Record<string, unknown>;
}

export const REF_MARK = "refUpstreamOf";

/** 能"提供素材"的产物字段（按优先级）。 */
function productOf(data: Record<string, unknown>): string {
  return (
    str(data.imageUrl) ||
    str(data.posterUrl) ||
    str(data.videoUrl) ||
    str(data.audioUrl)
  );
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

/** 能"接受引用"的节点 kind（与生成侧一致：shot / video / image 会用 firstFrameUrl）。 */
const CAN_REF = new Set(["shot", "video", "image"]);

/**
 * 计算需要写入的补丁（**纯函数**）。
 *
 * 返回的每个补丁都已确认"当前值与目标值不同"，直接 apply 即可收敛。
 */
export function planUpstreamRefs(
  nodes: RefNode[],
  edges: RefEdge[],
  opts: { enabled: boolean } = { enabled: false },
): NodePatch[] {
  if (!opts.enabled) return [];
  const byId = new Map<string, RefNode>();
  for (const n of nodes || []) if (n?.id) byId.set(String(n.id), n);

  // 每个节点取"第一条有效的上游产物"（多条上游时以边的出现顺序为准，稳定可预期）
  const want = new Map<string, { url: string; from: string }>();
  for (const e of edges || []) {
    const s = String(e?.source || "");
    const t = String(e?.target || "");
    if (!s || !t || s === t) continue;
    const src = byId.get(s);
    const dst = byId.get(t);
    if (!src || !dst) continue;
    const dstData = (dst.data || {}) as Record<string, unknown>;
    if (!CAN_REF.has(str(dstData.kind))) continue;
    const url = productOf((src.data || {}) as Record<string, unknown>);
    if (!url) continue; // 上游还没产物 ⇒ 什么都不做（等它生成完再连）
    if (!want.has(t)) want.set(t, { url, from: s });
  }

  const patches: NodePatch[] = [];
  for (const n of nodes || []) {
    const id = String(n?.id || "");
    if (!id) continue;
    const d = (n.data || {}) as Record<string, unknown>;
    const current = str(d.firstFrameUrl);
    const marked = str(d[REF_MARK]);
    const wantOne = want.get(id);

    if (wantOne) {
      // 规则①：已有值且**不是我们写的** ⇒ 不动（尊重用户选择）
      if (current && !marked) continue;
      if (current === wantOne.url && marked === wantOne.from) continue; // 已收敛
      patches.push({ id, patch: { firstFrameUrl: wantOne.url, [REF_MARK]: wantOne.from } });
      continue;
    }
    // 规则②：连线没了 ⇒ 只清"我们写过的那一条"
    if (marked && current) {
      patches.push({ id, patch: { firstFrameUrl: "", [REF_MARK]: "" } });
    } else if (marked) {
      patches.push({ id, patch: { [REF_MARK]: "" } });
    }
  }
  return patches;
}

// ── 开关（持久化；默认关）────────────────────────────────────────────
const ENABLED_KEY = "shiguang-canvas:upstream-refs:enabled";

export function isUpstreamRefsEnabled(): boolean {
  try {
    return localStorage.getItem(ENABLED_KEY) === "1";
  } catch {
    return false;
  }
}

export function setUpstreamRefsEnabled(on: boolean): void {
  try {
    localStorage.setItem(ENABLED_KEY, on ? "1" : "0");
  } catch {
    /* ignore */
  }
}

// ── 订阅同步（imperative shell）：边一变就重算，只写"真有变化"的补丁 ────────

import { useCallback, useEffect, useState } from "react";

import { useCanvasStore } from "./store";

/**
 * 把「连线 → 下游引用」挂到画布 store 上。
 *
 * ⚠️ 幂等性：`planUpstreamRefs` 只返回真正需要变的补丁，apply 完再算就是空数组
 * ⇒ effect 里写 store 不会自激（这也是它敢直接放在 effect 里的原因）。
 */
export function useUpstreamRefsSync(): { enabled: boolean; toggle: () => void } {
  const [enabled, setEnabled] = useState<boolean>(() => isUpstreamRefsEnabled());
  const nodes = useCanvasStore((s) => s.nodes);
  const edges = useCanvasStore((s) => s.edges);

  useEffect(() => {
    if (!enabled) return;
    let patches: NodePatch[] = [];
    try {
      patches = planUpstreamRefs(
        (nodes || []) as never,
        (edges || []) as never,
        { enabled: true },
      );
    } catch {
      return; // 画布数据异常时不影响画布本身
    }
    if (!patches.length) return;
    for (const { id, patch } of patches) {
      useCanvasStore.getState().updateNodeData(id, patch);
    }
  }, [enabled, nodes, edges]);

  const toggle = useCallback(() => {
    const next = !isUpstreamRefsEnabled();
    setUpstreamRefsEnabled(next);
    setEnabled(next);
  }, []);

  return { enabled, toggle };
}
