/**
 * 咬合检测 — Bond
 *
 * 「咬合」= 两张卡已经真正贴合在一起（边距为 0、且贴合边上有足够的投影重叠）。
 * 它由几何关系推导，不落盘，因此刷新 / 重开工程后依然成立。
 *
 * 与「磁吸」的区别：
 *   - 磁吸（MagneticEngine.computeMagnetic）是拖拽过程中的动态吸引力；
 *   - 咬合是拖拽结束后的静态结果，用于渲染咬合缝、以及拖拽分离时的阻力手感。
 *
 * 纯计算，无 React 依赖。
 */

import type { Node } from "@xyflow/react";
import { rectOf } from "./MagneticEngine";
import { SpatialIndex } from "./SpatialIndex";
import {
  DEFAULT_MAG_CONFIG,
  type Bond,
  type MagneticConfig,
  type SpatialDirection,
} from "./types";

/** 判定咬合所需的最小投影重叠（px）：贴得太偏、只搭一个角不算咬合 */
const MIN_OVERLAP = 40;

/** 无向键：保证同一对卡片只产生一条咬合缝 */
export function bondKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * 判断两张卡是否咬合，并给出咬合缝的中心线
 *
 * 只有「一边贴合、另一边有足够重叠」才算咬合；两卡大幅重叠（层叠关系）
 * 不算咬合 —— 那种关系由层叠徽章承载，画一条缝反而误导。
 */
function makeBond(a: Node, b: Node, tol: number): Bond | null {
  const ra = rectOf(a);
  const rb = rectOf(b);

  const aRight = ra.x + ra.w;
  const aBottom = ra.y + ra.h;
  const bRight = rb.x + rb.w;
  const bBottom = rb.y + rb.h;

  /** 贴合边上的投影重叠段 */
  const oyStart = Math.max(ra.y, rb.y);
  const oyEnd = Math.min(aBottom, bBottom);
  const oxStart = Math.max(ra.x, rb.x);
  const oxEnd = Math.min(aRight, bRight);
  const overlapY = oyEnd - oyStart;
  const overlapX = oxEnd - oxStart;

  let side: SpatialDirection | null = null;
  let axis: Bond["axis"] = "vertical";
  let seam: Rect = { x: 0, y: 0, w: 0, h: 0 };

  if (Math.abs(rb.x - aRight) <= tol && overlapY >= MIN_OVERLAP) {
    // b 贴在 a 右侧
    side = "right";
    axis = "vertical";
    seam = { x: aRight, y: oyStart, w: 0, h: overlapY };
  } else if (Math.abs(ra.x - bRight) <= tol && overlapY >= MIN_OVERLAP) {
    side = "left";
    axis = "vertical";
    seam = { x: ra.x, y: oyStart, w: 0, h: overlapY };
  } else if (Math.abs(rb.y - aBottom) <= tol && overlapX >= MIN_OVERLAP) {
    side = "bottom";
    axis = "horizontal";
    seam = { x: oxStart, y: aBottom, w: overlapX, h: 0 };
  } else if (Math.abs(ra.y - bBottom) <= tol && overlapX >= MIN_OVERLAP) {
    side = "top";
    axis = "horizontal";
    seam = { x: oxStart, y: ra.y, w: overlapX, h: 0 };
  }

  if (!side) return null;

  return {
    key: bondKey(a.id, b.id),
    aId: a.id,
    bId: b.id,
    side,
    axis,
    seam,
  };
}

/**
 * 扫描全画布，返回所有咬合关系（用于渲染咬合缝）
 *
 * 用空间索引把每个节点的比较范围收敛到邻域，避免大画布上 O(n²)。
 */
export function computeBonds(
  nodes: Node[],
  config: MagneticConfig = DEFAULT_MAG_CONFIG,
): Bond[] {
  if (nodes.length < 2) return [];

  const index = new SpatialIndex(nodes);
  const seen = new Set<string>();
  const out: Bond[] = [];

  for (const node of nodes) {
    const r = rectOf(node);
    const candidates = index.queryNear(r.x + r.w / 2, r.y + r.h / 2);
    for (const other of candidates) {
      if (other.id === node.id) continue;
      const key = bondKey(node.id, other.id);
      if (seen.has(key)) continue;
      const bond = makeBond(node, other, config.bondTolerance);
      if (bond) {
        seen.add(key);
        out.push(bond);
      }
    }
  }

  return out;
}

/**
 * 查询某个节点当前的咬合关系（拖拽开始时用，只需扫一遍全表）
 *
 * 返回该节点参与的第一条咬合。一张卡理论上可以同时与多张卡咬合，
 * 但拖拽分离时只处理与拖拽方向最相关的一条，避免手感混乱。
 */
export function findBondFor(
  nodeId: string,
  nodes: Node[],
  config: MagneticConfig = DEFAULT_MAG_CONFIG,
  preferDirection?: { x: number; y: number },
): Bond | null {
  const node = nodes.find((n) => n.id === nodeId);
  if (!node) return null;

  const found: Bond[] = [];
  for (const other of nodes) {
    if (other.id === nodeId) continue;
    const bond = makeBond(node, other, config.bondTolerance);
    if (bond) found.push(bond);
  }
  if (found.length === 0) return null;
  if (found.length === 1 || !preferDirection) return found[0];

  // 多条咬合时，取「离拖拽方向最近」的那条，分离手感最符合直觉
  const len = Math.hypot(preferDirection.x, preferDirection.y) || 1;
  const ux = preferDirection.x / len;
  const uy = preferDirection.y / len;
  const dirVec: Record<SpatialDirection, { x: number; y: number }> = {
    left: { x: -1, y: 0 },
    right: { x: 1, y: 0 },
    top: { x: 0, y: -1 },
    bottom: { x: 0, y: 1 },
    stack: { x: 0, y: 0 },
  };
  let bestBond = found[0];
  let bestScore = -Infinity;
  for (const bond of found) {
    // side 描述的是「对方向量相对本节点」；分离方向与之相反
    const v = dirVec[bond.side];
    const score = -(ux * v.x + uy * v.y);
    if (score > bestScore) {
      bestScore = score;
      bestBond = bond;
    }
  }
  return bestBond;
}

/** 咬合中「另一方」的 id */
export function neighborOf(bond: Bond, nodeId: string): string {
  return bond.aId === nodeId ? bond.bId : bond.aId;
}

/** 四向取反：bond.side 描述「b 相对 a」，故 a 贴合边 = side，b 贴合边 = 反方向 */
const OPPOSITE_SIDE: Record<SpatialDirection, SpatialDirection> = {
  left: "right",
  right: "left",
  top: "bottom",
  bottom: "top",
  stack: "stack",
};

function addBondedSide(
  map: Record<string, SpatialDirection[]>,
  id: string,
  side: SpatialDirection,
): void {
  if (side === "stack") return; // 层叠不产生贴合边
  const arr = map[id];
  if (arr) {
    if (!arr.includes(side)) arr.push(side);
  } else {
    map[id] = [side];
  }
}

/**
 * 咬合侧隐形表（2026-09-16 用户裁定，对齐 Windows 磁贴观感）
 *
 * 两卡贴合后，贴合侧两条描边叠成一条实色线、圆角在贴合角留缺口——
 * 磁贴的做法是贴合边完全齐平无缝。渲染层（NoviceCard）按本表给贴合边
 * 加 border-*:transparent + 直角，两张卡在接缝处融为一块。
 *
 * 纯几何推导、不落盘，与 Bond 同源同刷新周期（computeBonds 的伴生视图）。
 */
export function bondedSidesMap(
  nodes: Node[],
  config: MagneticConfig = DEFAULT_MAG_CONFIG,
): Record<string, SpatialDirection[]> {
  const map: Record<string, SpatialDirection[]> = {};
  for (const bond of computeBonds(nodes, config)) {
    addBondedSide(map, bond.aId, bond.side);
    addBondedSide(map, bond.bId, OPPOSITE_SIDE[bond.side]);
  }
  return map;
}
