/**
 * 整列让位 — Reflow（纯计算）
 *
 * 「让位」= 拖拽卡准备落进某个空位时，把挡在它前面的**同一行 / 同一列**的卡片
 * 顺次推开一格，给拖拽卡腾出位置。
 *
 * 这是 2026-09-18 用户裁定「借鉴手机主屏拖拽手感」的第二条机制：
 * 手机主屏上把一个图标拖到已有图标的位置，那排图标会横向让开一格，
 * 而不是让你把图标叠上去。
 *
 * ── 与既有模块的分工 ──────────────────────────────────────────────
 *   computeMagnetic  → 「松手会吸附到哪」（一对一的吸附落点）
 *   computeBonds     → 「哪些卡已经贴合」（静态咬合关系）
 *   analyzeSpatialPattern → 「这片区域是什么布局」（sequence/parallel/loop…）
 *   planReflow（本模块）→「要让出位置，谁该往哪挪」（一对多的位移规划）
 *
 * SpatialAnalyzer 只做布局模式**识别**，不返回可执行的推挤位移，因此让位
 * 必须独立成模块，不能复用它。
 *
 * ── 三条硬红线（违反任何一条都会变成「卡片自己乱跑」）────────────────
 *   ① 只推同一行 / 同一列：垂直于让位方向的轴上，投影重叠必须 ≥ MIN_OVERLAP(40px)。
 *      斜对角的卡绝不推 —— 那在视觉上不构成「挡住」，推了就是莫名其妙的位移。
 *   ② 链式只推一格：碰到的卡往让位方向挪一格；**再往后的卡一概不动**。
 *      不递归传递，否则一次拖拽可能推走半张画布。
 *   ③ 撞上「非链上的卡」立即断链：如果被推的卡身后紧贴着第三张卡，
 *      那么整条链都不推（宁可不让位，也不能把别人的布局撞乱）。
 *
 * 纯计算，无 React 依赖，可独立测试。
 */

import type { Node } from "@xyflow/react";
import { rectOf, type NodeSize } from "./MagneticEngine";
import { DEFAULT_MAG_CONFIG, type MagneticConfig } from "./types";

/**
 * 判定「同一行 / 同一列」所需的最小投影重叠（px）。
 *
 * 与 bonds.ts 的 MIN_OVERLAP 取同一把尺子（40px）：只有「挡得够正」的卡才让，
 * 只搭一个角的不算挡住。两处保持一致可避免出现「算作咬合但不算挡路」这类
 * 自相矛盾的状态。
 */
const MIN_OVERLAP = 40;

/**
 * 让位规划里的「让位轴」。
 * - `x`：在水平方向被挡住 → 沿 x 推（同一行的卡左右让）
 * - `y`：在垂直方向被挡住 → 沿 y 推（同一列的卡上下让）
 */
export type ReflowAxis = "x" | "y";

/** 被推开的卡片及其目标位置 */
export interface ReflowShift {
  id: string;
  /** 推开后的目标左上角（流坐标） */
  x: number;
  y: number;
}

export interface ReflowPlan {
  /**
   * 拖拽卡松手后将落到的位置；`null` 表示这次拖拽不产生让位
   * （没被挡住 / 判定为层叠 / 链断）。
   */
  ghost: { x: number; y: number; w: number; h: number } | null;
  /** 需要一起挪动的卡片（不含拖拽卡自身）；空数组表示原地可落 */
  shifts: ReflowShift[];
  /**
   * 本次让位的轴；`null` 表示不让位。
   * 供 UI 决定画横向还是纵向的让位指示。
   */
  axis: ReflowAxis | null;
  /**
   * 因「链上撞到非链卡」而放弃让位（红线③）。
   * 与「压根没被挡住」区分开，便于测试与调试。
   */
  blocked: boolean;
}

const EMPTY_PLAN: ReflowPlan = { ghost: null, shifts: [], axis: null, blocked: false };

/** 吸附落位的统一卡间距（与 MagneticEngine.getSnapPosition 的 gap 保持一致） */
const LANDING_GAP = -2;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 沿轴投影重叠长度（返回「垂直于该轴」的重叠，即判定同一行/列用的量） */
function overlapOn(a: Rect, b: Rect, axis: ReflowAxis): number {
  if (axis === "x") {
    // 沿 x 推 ⇒ 要求 y 轴投影重叠（同一行）
    return Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  }
  // 沿 y 推 ⇒ 要求 x 轴投影重叠（同一列）
  return Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
}

/**
 * 沿轴**本身**的投影重叠长度。
 *
 * 与 overlapOn 的区别：overlapOn 量的是「垂直于让位轴」的重叠（同一行/列的判据），
 * 本函数量的是「让位轴自己」的重叠——用于判断落位点是否**已经插进**了卡里
 * （即层叠），这是两个方向的正交概念，不可混用。
 */
function overlapAlong(a: Rect, b: Rect, axis: ReflowAxis): number {
  if (axis === "x") {
    return Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  }
  return Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
}

/** 沿轴上的分离量：已重叠时为 0 */
function gapOn(a: Rect, b: Rect, axis: ReflowAxis): number {
  if (axis === "x") {
    return Math.max(a.x - (b.x + b.w), b.x - (a.x + a.w), 0);
  }
  return Math.max(a.y - (b.y + b.h), b.y - (a.y + a.h), 0);
}

/** b 是否位于 a 的正方向一侧（沿轴） */
function isAfter(a: Rect, b: Rect, axis: ReflowAxis): boolean {
  if (axis === "x") return b.x + b.w / 2 >= a.x + a.w / 2;
  return b.y + b.h / 2 >= a.y + a.h / 2;
}

/** 沿轴的一格步进 = 卡片实尺寸 + 落位间距 */
function stepOn(size: NodeSize, axis: ReflowAxis): number {
  const dimension = axis === "x" ? size.width : size.height;
  return dimension + LANDING_GAP;
}

/** 沿轴平移一个位移 */
function shiftRect(r: Rect, delta: number, axis: ReflowAxis): Rect {
  return axis === "x" ? { ...r, x: r.x + delta } : { ...r, y: r.y + delta };
}

/**
 * 计算一次「整列让位」的完整规划。
 *
 * @param draggingRect 拖拽卡松手后**打算落到的**矩形（通常是磁吸算出的 snapPos；
 *                     无磁吸时传当前拖拽位置即可）
 * @param others       画布上除拖拽卡外的所有节点
 * @param config       磁吸配置（仅用 weakDistance 作为「算不算挨着」的感知半径）
 * @returns 让位规划；`ghost` 为 null 表示不需要让位
 *
 * 行为大纲：
 *   1. 找出所有「与落位矩形在垂直轴上投影重叠 ≥ 40px」（同一行/列）且
 *      「沿轴间隙 ≤ weakDistance」的邻居 —— 这些是候选挡路者。
 *   2. 在候选里挑**离落位点最近的正方向那一个**作为锚点（假定它才是被撞的卡）。
 *   3. 沿轴逐个检查紧贴在锚点身后的卡，决定「推一格 / 断链」。
 *   4. 链一旦撞上不在候选集里的卡，整条链放弃（红线③）。
 */
export function planReflow(
  draggingRect: Rect,
  others: Node[],
  config: MagneticConfig = DEFAULT_MAG_CONFIG,
): ReflowPlan {
  if (others.length === 0) return EMPTY_PLAN;

  const rects = others.map((node) => ({ node, rect: rectOf(node) }));

  /**
   * 先判让位轴，并排除「层叠」。
   *
   * 判据是「沿哪一轴插进了别人的位置」：
   *   - y 轴投影重叠（同一行） → 落位点横着插进了这一行 → 沿 x 推
   *   - x 轴投影重叠（同一列） → 落位点竖着插进了这一列 → 沿 y 推
   *
   * ⚠️ 层叠（stack）必须前置排除：若同一个邻居在两轴上都有足够重叠，
   * 说明落位点几乎压在它身上，那是「层叠」语义、由层叠徽章承载，
   * 让位机制不得介入（否则想把卡叠上去时会莫名把邻居推开）。
   */
  let axis: ReflowAxis | null = null;
  let maxOverlap = 0;
  for (const candidateAxis of ["x", "y"] as const) {
    let overlap = 0;
    for (const { rect } of rects) {
      // 沿 candidateAxis 推 ⇒ 看对侧轴的重叠
      overlap = Math.max(overlap, overlapOn(draggingRect, rect, candidateAxis === "x" ? "y" : "x"));
    }
    if (overlap >= MIN_OVERLAP && overlap > maxOverlap) {
      maxOverlap = overlap;
      // 沿「垂直于最大重叠的那个轴」推
      axis = candidateAxis === "x" ? "y" : "x";
    }
  }

  // 两轴都没形成「同一行 / 同一列」→ 不让位
  if (axis === null) return EMPTY_PLAN;

  /**
   * 层叠排除：沿让位轴方向上已经有重叠 ⇒ 落位点压在卡上，不是「插进空档」。
   *
   * ⚠️ 这里必须用 overlapAlong（让位轴本身的重叠），不是 overlapOn（对侧轴重叠）。
   * 例：落位矩形 (0,0,240,200)、邻居 (10,10,240,200) → x 重叠 230、y 重叠 190，
   * 两轴都插进去了，属于直接叠在卡上，交给层叠机制，不让位。
   * 而正常让位情形 (0,0) vs (248,0)：x 重叠 = 0（正好挨着没插进去），
   * y 重叠 = 200（同一行）→ 不触发层叠。
   */
  const stacking = rects.some(
    ({ rect }) => overlapAlong(draggingRect, rect, axis as ReflowAxis) > LANDING_GAP,
  );
  if (stacking) return EMPTY_PLAN;

  const size: NodeSize = { width: draggingRect.w, height: draggingRect.h };
  const step = stepOn(size, axis);

  /**
   * 候选挡路者（**仅用于挑选锚点**）：同一行/列（对侧轴重叠 ≥ 40）
   * 且沿轴离落位点很近（≤ weakDistance）。
   *
   * ⚠️ 注意候选池的职责边界：它只决定「谁是被我压到的第一张卡」。
   * 链的**生长**必须独立于这个距离阈值 —— 链上第二张、第三张卡天然
   * 离落位点越来越远，若沿用 weakDistance 筛选，链会被截断成单卡，
   * 随后红线③的「链外卡」检测会把本该在链上的卡误判成障碍，导致
   * 一条正常的链被整条否决（回归：reflow.test.ts「链整体推一格」）。
   */
  interface Candidate {
    node: Node;
    rect: Rect;
    gap: number;
    after: boolean;
  }
  const candidates: Candidate[] = [];
  for (const { node, rect } of rects) {
    if (overlapOn(draggingRect, rect, axis) < MIN_OVERLAP) continue;
    const gap = gapOn(draggingRect, rect, axis);
    if (gap > config.weakDistance) continue;
    candidates.push({ node, rect, gap, after: isAfter(draggingRect, rect, axis) });
  }

  if (candidates.length === 0) return EMPTY_PLAN;

  // 锚点 = 最近的那个候选（真正被压到的卡）
  candidates.sort((a, b) => a.gap - b.gap);
  const anchor = candidates[0];

  /**
   * 链的生长：从锚点出发，沿让位方向逐张找「紧贴着的下一张卡」。
   *
   * ⚠️ 这里必须遍历**全部节点**（rects），不能复用 candidates —— 见上方注释。
   * 每找到一张就把它加入链，并继续以它为基准往后找；
   * 相邻两张的间隙必须 ≤ bondTolerance(2px) 才算「紧贴成链」。
   */
  const chain: Candidate[] = [{ ...anchor }];
  const chainIds = new Set<string>([anchor.node.id]);
  const direction = anchor.after ? 1 : -1;
  const bondTol = config.bondTolerance;

  /** 已加入链的卡片矩形，逐张往后生长 */
  let cursor = anchor.rect;
  // 防御性上限：链长不超过节点总数（避免任何意外死循环）
  for (let guard = 0; guard < rects.length; guard += 1) {
    let next: Candidate | null = null;
    for (const { node, rect } of rects) {
      if (chainIds.has(node.id)) continue;
      // 必须同一行/列
      if (overlapOn(cursor, rect, axis) < MIN_OVERLAP) continue;
      // 必须在同一侧继续往外
      if (isAfter(cursor, rect, axis) !== anchor.after) continue;
      // 必须紧贴（间隙 ≤ 容差）
      if (gapOn(cursor, rect, axis) > Math.max(bondTol, 0)) continue;
      // 取最近的一张
      const gap = gapOn(cursor, rect, axis);
      if (!next || gap < next.gap) {
        next = { node, rect, gap, after: anchor.after };
      }
    }
    if (!next) break;
    chain.push(next);
    chainIds.add(next.node.id);
    cursor = next.rect;
  }

  /**
   * 红线③：**推动之后**链会撞上同行紧贴的链外卡 → 整条链放弃。
   *
   * 为什么不能在「推动前」判：链的生长规则是「同行 + 紧贴(≤2px) 就吸收」，
   * 因此推动前所有紧贴的卡都已经在链上了，用「当前是否紧贴」去检测链外卡
   * 永远为假（这是一个曾经写错的判据）。
   *
   * 正确判据是「预测碰撞」：把链整体沿推动方向平移 step 后，
   * 检查链尾是否与某张链外卡变成「同行 + 紧贴」。若是，说明推开这条链
   * 会撞乱别人的布局 —— 按红线③ 宁可不让位。
   */
  const tailRect = shiftRect(cursor, direction * step, axis);
  for (const { node, rect } of rects) {
    if (chainIds.has(node.id)) continue;
    // 平移后必须同行/列
    if (overlapOn(tailRect, rect, axis) < MIN_OVERLAP) continue;
    // 必须落在推动方向的正前方
    if (isAfter(tailRect, rect, axis) !== anchor.after) continue;
    // 平移后变成紧贴或重叠 → 撞上
    if (gapOn(tailRect, rect, axis) > Math.max(bondTol, 0)) continue;
    return {
      ghost: null,
      shifts: [],
      axis,
      blocked: true,
    };
  }

  const shifts: ReflowShift[] = chain.map((member) => {
    const moved = shiftRect(member.rect, direction * step, axis);
    return { id: member.node.id, x: moved.x, y: moved.y };
  });

  /**
   * ghost = 拖拽卡的新落位。
   *
   * 让位后，拖拽卡应当落在**锚点原位置**（把锚点顶走、自己占它的坑），
   * 而不是停在原来的 snapPos —— 否则会和被推开的卡重叠。
   */
  const ghostRect: Rect = {
    x: anchor.rect.x,
    y: anchor.rect.y,
    w: draggingRect.w,
    h: draggingRect.h,
  };

  return {
    ghost: { x: ghostRect.x, y: ghostRect.y, w: ghostRect.w, h: ghostRect.h },
    shifts,
    axis,
    blocked: false,
  };
}

/** 让位规划是否为空（无 ghost 即无动作） */
export function isEmptyPlan(plan: ReflowPlan): boolean {
  return plan.ghost === null && plan.shifts.length === 0;
}
