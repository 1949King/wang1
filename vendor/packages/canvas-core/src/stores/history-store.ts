/**
 * 画布图的 history 栈 + 剪贴板。
 * — 模块级可变状态（graphPast / graphFuture / clipboard）由本文件持有
 * — store.ts 通过 pushGraphHistory / cloneGraph 等函数与它交互
 * — 所有状态操作都是纯函数或对模块变量的直接 mutate（简洁、好追踪）
 */

import type { Edge, Node } from "@xyflow/react";

/** 画布某一时刻的图快照（用于 undo/redo） */
export type GraphSnap = {
  nodes: Node[];
  edges: Edge[];
  selectedId: string | null;
};

/** 剪贴板载荷（相对包围盒的边，粘贴时重映射 source/target id） */
export type ClipboardPayload = {
  nodes: Node[];
  edges: Edge[];
};

const MAX_HISTORY = 40;

/** 过去的历史栈（最新的在末尾） */
let graphPast: GraphSnap[] = [];
/** redo 栈 */
let graphFuture: GraphSnap[] = [];
/** 当前剪贴板（最近一次 copy 的内容） */
let clipboard: ClipboardPayload | null = null;

/** 深拷贝当前图快照（用 JSON 序列化，忽略 function / undefined） */
export function cloneGraph(
  nodes: Node[],
  edges: Edge[],
  selectedId: string | null,
): GraphSnap {
  return {
    nodes: JSON.parse(JSON.stringify(nodes)) as Node[],
    edges: JSON.parse(JSON.stringify(edges)) as Edge[],
    selectedId,
  };
}

/** 把当前图压入 undo 栈，并清空 redo 栈（任何新操作都会使 redo 失效） */
export function pushGraphHistory(get: () => { nodes: Node[]; edges: Edge[]; selectedId: string | null }): void {
  const snap = cloneGraph(get().nodes, get().edges, get().selectedId);
  graphPast.push(snap);
  if (graphPast.length > MAX_HISTORY) graphPast.shift();
  graphFuture = [];
}

/** 从 undo 栈弹出一帧并返回，同时压入 redo 栈；栈空返回 null */
export function popGraphPast(get: () => GraphSnap | null = () => null): GraphSnap | null {
  const prev = graphPast.pop();
  if (!prev) return null;
  const current = get();
  if (current) graphFuture.push(current);
  return prev;
}

/** 从 redo 栈弹出一帧并返回，同时压入 undo 栈；栈空返回 null */
export function popGraphFuture(get: () => GraphSnap | null = () => null): GraphSnap | null {
  const next = graphFuture.pop();
  if (!next) return null;
  const current = get();
  if (current) graphPast.push(current);
  return next;
}

/** ========== 状态读取器（store 主体的 undoGraph/redoGraph 等函数需要） ========== */

export function getGraphPast(): GraphSnap[] {
  return graphPast;
}
export function getGraphFuture(): GraphSnap[] {
  return graphFuture;
}
export function getClipboard(): ClipboardPayload | null {
  return clipboard;
}
export function setClipboard(payload: ClipboardPayload | null): void {
  clipboard = payload;
}
