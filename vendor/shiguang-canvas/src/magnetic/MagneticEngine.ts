/**
 * 磁吸引擎 — 纯计算核心
 *
 * 负责拖拽节点与目标节点之间的磁力计算：
 * - 距离判断 → 磁吸等级
 * - 方向判断 → 空间语义
 * - 吸附位置 → 目标坐标
 *
 * 无 React 依赖，纯函数，可独立测试。
 */

import type { Node } from "@xyflow/react";
import {
  type MagneticConfig,
  type MagneticResult,
  type SpatialDirection,
  DEFAULT_MAG_CONFIG,
  CARD_SIZE,
} from "./types";

export interface NodeSize {
  width: number;
  height: number;
}

/**
 * 解析节点实际尺寸（优先 measured / style，兜底 CARD_SIZE 默认值）
 * 不同节点类型尺寸不同，动态获取可避免磁吸中心点偏移失真
 */
export function resolveNodeSize(node: Node): NodeSize {
  const m = (node as { measured?: { width?: number; height?: number } }).measured;
  if (m && m.width && m.height) {
    return { width: m.width, height: m.height };
  }
  const styleW = (node.style as { width?: number | string } | undefined)?.width;
  const styleH = (node.style as { height?: number | string } | undefined)?.height;
  if (typeof styleW === "number" && typeof styleH === "number") {
    return { width: styleW, height: styleH };
  }
  return { width: CARD_SIZE.width, height: CARD_SIZE.height };
}

/**
 * 计算拖拽节点与候选节点间的磁吸关系
 *
 * @param draggingNode 当前拖拽节点
 * @param allNodes 画布上所有节点（candidates 为空时的兜底）
 * @param config 磁吸配置
 * @param candidates 空间索引筛选出的候选节点（可选，性能优化）
 * @returns 最强磁吸结果（level=none 表示无磁吸）
 */
export function computeMagnetic(
  draggingNode: Node,
  allNodes: Node[],
  config: MagneticConfig = DEFAULT_MAG_CONFIG,
  candidates?: Node[],
): MagneticResult {
  let best: MagneticResult = {
    level: "none",
    targetId: null,
    direction: null,
    snapX: draggingNode.position.x,
    snapY: draggingNode.position.y,
    distance: Infinity,
  };

  const dragSize = resolveNodeSize(draggingNode);
  const dragCx = draggingNode.position.x + dragSize.width / 2;
  const dragCy = draggingNode.position.y + dragSize.height / 2;

  // 有候选集则只遍历候选（减少 O(n²) 全量扫描）
  const pool = candidates && candidates.length > 0 ? candidates : allNodes;

  for (const other of pool) {
    if (other.id === draggingNode.id) continue;

    const otherSize = resolveNodeSize(other);
    const otherCx = other.position.x + otherSize.width / 2;
    const otherCy = other.position.y + otherSize.height / 2;
    const dx = otherCx - dragCx;
    const dy = otherCy - dragCy;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist > config.weakDistance) continue;

    // 判断磁吸等级
    let level: MagneticResult["level"] = "none";
    if (dist < config.strongDistance) level = "strong";
    else if (dist < config.mediumDistance) level = "medium";
    else level = "weak";

    // 只保留最强的磁吸
    const levelRank = { none: 0, weak: 1, medium: 2, strong: 3 };
    if (levelRank[level] <= levelRank[best.level]) continue;

    const direction = getDirection(dx, dy);
    // 用「拖拽节点尺寸」计算吸附落点，保证不同规格节点吸附不进内部
    const snapPos = getSnapPosition(other.position, otherSize, dragSize, direction);

    best = {
      level,
      targetId: other.id,
      direction,
      snapX: snapPos.x,
      snapY: snapPos.y,
      distance: dist,
    };
  }

  return best;
}

/**
 * 判断空间方向
 * 根据两节点中心点的偏移量判断方向语义
 */
function getDirection(dx: number, dy: number): SpatialDirection {
  const absDx = Math.abs(dx);
  const absDy = Math.abs(dy);

  // 基本重叠 → 层叠
  if (absDx < 60 && absDy < 40) {
    return "stack";
  }

  // 水平主导
  if (absDx > absDy) {
    return dx > 0 ? "right" : "left";
  }
  // 垂直主导
  return dy > 0 ? "bottom" : "top";
}

/**
 * 计算吸附目标位置
 * 根据方向语义，在目标节点的对应方向放置拖拽节点
 * @param targetPos 目标节点左上角
 * @param targetSize 目标节点尺寸
 * @param dragSize 拖拽节点尺寸（防止吸附进内部）
 * @param direction 空间方向
 */
function getSnapPosition(
  targetPos: { x: number; y: number },
  targetSize: NodeSize,
  dragSize: NodeSize,
  direction: SpatialDirection,
): { x: number; y: number } {
  /** 卡片间距：0 = 紧密贴合（像 Windows 磁贴），对齐 spec 与小白使用者直觉 */
  const gap = 0;

  switch (direction) {
    case "left":
      return { x: targetPos.x - dragSize.width - gap, y: targetPos.y };
    case "right":
      return { x: targetPos.x + targetSize.width + gap, y: targetPos.y };
    case "top":
      return { x: targetPos.x, y: targetPos.y - dragSize.height - gap };
    case "bottom":
      return { x: targetPos.x, y: targetPos.y + targetSize.height + gap };
    case "stack":
      return { x: targetPos.x + 8, y: targetPos.y + 8 };
    default:
      return { x: targetPos.x, y: targetPos.y };
  }
}

/**
 * 计算磁吸偏移量
 * 根据磁吸等级和配置，计算拖拽节点应该向目标偏移多少
 */
export function getMagneticOffset(
  currentX: number,
  currentY: number,
  snapX: number,
  snapY: number,
  level: MagneticResult["level"],
): { x: number; y: number } {
  if (level === "none") return { x: 0, y: 0 };

  // 磁吸强度：越强偏移越大
  const strength =
    level === "weak" ? 0.15 :
    level === "medium" ? 0.35 : 0.7;

  return {
    x: (snapX - currentX) * strength,
    y: (snapY - currentY) * strength,
  };
}
