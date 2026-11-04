/**
 * 空间索引 — Grid Hash
 *
 * 把节点按网格桶（bucket）组织，拖拽磁吸时只遍历所在格子及其 8 邻域，
 * 把 O(n²) 距离遍历降为近似 O(候选数)，节点多时显著提速。
 *
 * 纯函数/轻类，无 React 依赖，可独立测试。
 */

import type { Node } from "@xyflow/react";
import type { NodeSize } from "./MagneticEngine";
import { resolveNodeSize } from "./MagneticEngine";
import { CARD_SIZE } from "./types";

/** 网格单元格大小：略大于默认卡片对角线，保证邻节点落在相邻桶 */
const CELL_W = CARD_SIZE.width + 140;
const CELL_H = CARD_SIZE.height + 140;

interface Bucket {
  x: number;
  y: number;
  nodes: Node[];
}

export class SpatialIndex {
  private buckets: Map<string, Bucket> = new Map();
  private sizes: Map<string, NodeSize> = new Map();

  /** 由节点列表构建索引 */
  constructor(nodes: Node[]) {
    for (const node of nodes) {
      this.add(node);
    }
  }

  private key(cx: number, cy: number): string {
    return `${cx}:${cy}`;
  }

  private cellOf(x: number, y: number): { cx: number; cy: number } {
    return {
      cx: Math.floor(x / CELL_W),
      cy: Math.floor(y / CELL_H),
    };
  }

  /** 加入一个节点（按中心坐标落桶） */
  add(node: Node): void {
    const { cx, cy } = this.cellOf(node.position.x + (node.width ?? 0) / 2, node.position.y + (node.height ?? 0) / 2);
    const k = this.key(cx, cy);
    let bucket = this.buckets.get(k);
    if (!bucket) {
      bucket = { x: cx, y: cy, nodes: [] };
      this.buckets.set(k, bucket);
    }
    bucket.nodes.push(node);
    this.sizes.set(node.id, resolveNodeSize(node));
  }

  /** 查询给定节点中心附近的候选节点（当前桶 + 8 邻域，去重） */
  queryNear(
    x: number,
    y: number,
  ): Node[] {
    const { cx, cy } = this.cellOf(x, y);
    const seen = new Set<string>();
    const result: Node[] = [];
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        const bucket = this.buckets.get(this.key(cx + dx, cy + dy));
        if (!bucket) continue;
        for (const node of bucket.nodes) {
          if (seen.has(node.id)) continue;
          seen.add(node.id);
          result.push(node);
        }
      }
    }
    return result;
  }
}