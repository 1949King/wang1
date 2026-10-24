/**
 * 软连接系统 — 纯函数核心
 *
 * 磁吸吸附到 strong 时，自动检测一段"潜在血缘"关系并生成软连接（虚线）。
 * 用户可在虚线上点"固化"转为正式 edge；不固化则软连接仅作提示，不落盘。
 *
 * 软连接不修改节点 schema，也不修改 store，由画布层持有并渲染。
 */

import type { SpatialDirection, SoftConnection } from "./types";

let _connId = 0;
function genConnectionId(): string {
  _connId += 1;
  return `soft_${Date.now()}_${_connId}`;
}

/** 判断两个节点间是否允许建立软连接（非 self） */
export function canCreateConnection(sourceId: string, targetId: string): boolean {
  return Boolean(sourceId && targetId && sourceId !== targetId);
}

/** 创建一条软连接（不查重），方向来自磁吸结果 */
export function createSoftConnection(
  sourceId: string,
  targetId: string,
  direction: SpatialDirection,
): SoftConnection {
  return {
    id: genConnectionId(),
    sourceId,
    targetId,
    direction,
    createdAt: Date.now(),
  };
}

/** 去重：判断画布上是否已存在相同节点对的软连接（忽略方向） */
export function hasExistingConnection(
  list: SoftConnection[],
  aId: string,
  bId: string,
): boolean {
  return list.some((c) =>
    (c.sourceId === aId && c.targetId === bId) ||
    (c.sourceId === bId && c.targetId === aId),
  );
}

/** 添加软连接（自动去重 + 防 self） */
export function pushSoftConnection(
  list: SoftConnection[],
  candidate: { sourceId: string; targetId: string; direction: SpatialDirection },
): SoftConnection[] {
  if (!canCreateConnection(candidate.sourceId, candidate.targetId)) return list;
  if (hasExistingConnection(list, candidate.sourceId, candidate.targetId)) return list;
  return [...list, createSoftConnection(candidate.sourceId, candidate.targetId, candidate.direction)];
}

/** 移除软连接 */
export function removeSoftConnection(list: SoftConnection[], id: string): SoftConnection[] {
  return list.filter((c) => c.id !== id);
}