/**
 * 空间布局分析器
 *
 * 分析画布上节点的空间分布，识别布局模式：
 * - sequence  横排序列（镜头流）
 * - parallel  并行对照（AB 测试）
 * - loop      环状循环（迭代）
 * - branch    主线+支线（备选方案）
 * - cluster   场景组（聚堆的节点集合）
 * - free      自由布局
 *
 * 纯函数，无 React 依赖，可独立测试。
 */

import type { Node } from "@xyflow/react";
import { CARD_SIZE } from "./types";

/** 空间布局模式 */
export type SpatialPattern =
  | "sequence"    // 横排：镜头序列
  | "parallel"    // 并行：多版本对照
  | "loop"        // 环状：循环迭代
  | "branch"      // 主线+支线：备选方案
  | "cluster"     // 场景组：聚堆
  | "free";       // 自由：无模式

/** 场景组 — 空间上聚在一起的节点集合 */
export interface SceneCluster {
  id: string;
  nodeIds: string[];
  centerX: number;
  centerY: number;
  bounds: { x: number; y: number; width: number; height: number };
}

/** 分析结果 */
export interface SpatialAnalysisResult {
  pattern: SpatialPattern;
  clusters: SceneCluster[];
  description: string;
}

/**
 * 分析画布上所有节点的空间布局模式
 */
export function analyzeSpatialPattern(nodes: Node[]): SpatialAnalysisResult {
  if (nodes.length === 0) {
    return { pattern: "free", clusters: [], description: "空画布" };
  }
  if (nodes.length === 1) {
    return { pattern: "free", clusters: [], description: "单个节点" };
  }

  const clusters = detectClusters(nodes);

  // 2 个节点：判断关系
  if (nodes.length === 2) {
    const [a, b] = nodes;
    const dx = Math.abs(a.position.x - b.position.x);
    const dy = Math.abs(a.position.y - b.position.y);
    if (dx > dy * 1.5) {
      return { pattern: "sequence", clusters, description: "横向排列，可能是序列关系" };
    }
    if (dy > dx * 1.5) {
      return { pattern: "parallel", clusters, description: "纵向排列，可能是对照关系" };
    }
    return { pattern: "free", clusters, description: "两个节点" };
  }

  // 3+ 节点：更复杂的模式识别
  const pattern = detectPattern(nodes, clusters);

  const descriptions: Record<SpatialPattern, string> = {
    sequence: "节点横向排列，形成镜头序列",
    parallel: "节点纵向并行，可能是版本对照",
    loop: "节点形成环状，可能是循环迭代",
    branch: "有主线和支线，可能是备选方案",
    cluster: "节点聚集成组，可能是一场戏",
    free: "自由布局",
  };

  return { pattern, clusters, description: descriptions[pattern] };
}

/**
 * 使用简单的聚类算法检测场景组
 * 基于距离阈值的贪心聚类
 */
export function detectClusters(nodes: Node[]): SceneCluster[] {
  if (nodes.length <= 1) return [];

  const distanceThreshold = CARD_SIZE.width * 1.5; // 1.5 个卡片宽度
  const clusters: string[][] = [];
  const assigned = new Set<string>();

  for (const node of nodes) {
    if (assigned.has(node.id)) continue;

    const cluster: string[] = [node.id];
    assigned.add(node.id);

    // BFS 扩展
    const queue = [node];
    while (queue.length > 0) {
      const current = queue.shift()!;
      for (const other of nodes) {
        if (assigned.has(other.id)) continue;
        const dist = nodeDistance(current, other);
        if (dist < distanceThreshold) {
          cluster.push(other.id);
          assigned.add(other.id);
          queue.push(other);
        }
      }
    }

    if (cluster.length > 1) {
      clusters.push(cluster);
    }
  }

  // 计算每个簇的属性
  return clusters.map((nodeIds, idx) => {
    const clusterNodes = nodes.filter((n) => nodeIds.includes(n.id));
    const xs = clusterNodes.map((n) => n.position.x);
    const ys = clusterNodes.map((n) => n.position.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs) + CARD_SIZE.width;
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys) + CARD_SIZE.height;

    return {
      id: `cluster_${idx}`,
      nodeIds,
      centerX: (minX + maxX) / 2,
      centerY: (minY + maxY) / 2,
      bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
    };
  });
}

/**
 * 检测布局模式
 */
function detectPattern(nodes: Node[], clusters: SceneCluster[]): SpatialPattern {
  // 多个场景组 → cluster 模式
  if (clusters.length >= 2) {
    return "cluster";
  }

  // 单个大组：判断内部结构
  const xs = nodes.map((n) => n.position.x);
  const ys = nodes.map((n) => n.position.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const width = maxX - minX;
  const height = maxY - minY;

  // 环状检测：首尾靠近且分布在一个大致圆上
  if (nodes.length >= 4) {
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const avgRadius = (width + height) / 4;
    const radiusVariance = nodes.reduce((sum, n) => {
      const r = Math.sqrt(
        Math.pow(n.position.x + CARD_SIZE.width / 2 - centerX, 2) +
        Math.pow(n.position.y + CARD_SIZE.height / 2 - centerY, 2),
      );
      return sum + Math.pow(r - avgRadius, 2);
    }, 0) / nodes.length;

    if (radiusVariance < avgRadius * avgRadius * 0.15 && width > CARD_SIZE.width * 2) {
      return "loop";
    }
  }

  // 横排序列：宽度远大于高度，且节点大致在同一水平线上
  if (width > height * 2) {
    // 检查节点是否大致在同一水平线
    const avgY = (minY + maxY) / 2;
    const yVariance = nodes.reduce((sum, n) => sum + Math.pow(n.position.y - avgY, 2), 0) / nodes.length;
    if (yVariance < CARD_SIZE.height * CARD_SIZE.height) {
      return "sequence";
    }
  }

  // 并行对照：高度远大于宽度，且列数少
  if (height > width * 1.5) {
    return "parallel";
  }

  // 分支检测：有一个节点连接到多个节点（需要 edges 信息，这里简化为：有一个节点在左边，多个节点在右边不同高度）
  const leftNodes = nodes.filter((n) => n.position.x < minX + width * 0.3);
  const rightNodes = nodes.filter((n) => n.position.x > minX + width * 0.6);
  if (leftNodes.length === 1 && rightNodes.length >= 2) {
    return "branch";
  }

  return "free";
}

/** 两节点中心距离 */
function nodeDistance(a: Node, b: Node): number {
  const ax = a.position.x + CARD_SIZE.width / 2;
  const ay = a.position.y + CARD_SIZE.height / 2;
  const bx = b.position.x + CARD_SIZE.width / 2;
  const by = b.position.y + CARD_SIZE.height / 2;
  return Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2);
}

/**
 * 自动排列：按序列模式整理节点
 */
export function autoLayoutSequence(
  nodes: Node[],
  startX = 100,
  startY = 100,
  gap = 40,
): { id: string; x: number; y: number }[] {
  return nodes.map((n, i) => ({
    id: n.id,
    x: startX + i * (CARD_SIZE.width + gap),
    y: startY,
  }));
}

/**
 * 自动排列：按并行模式整理节点
 */
export function autoLayoutParallel(
  nodes: Node[],
  startX = 100,
  startY = 100,
  gap = 30,
): { id: string; x: number; y: number }[] {
  return nodes.map((n, i) => ({
    id: n.id,
    x: startX,
    y: startY + i * (CARD_SIZE.height + gap),
  }));
}
