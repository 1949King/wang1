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
 * 节点矩形（流坐标）
 */
export function rectOf(node: Node): { x: number; y: number; w: number; h: number } {
  const size = resolveNodeSize(node);
  return { x: node.position.x, y: node.position.y, w: size.width, h: size.height };
}

/**
 * 两矩形的「边距」——即最少需要移动多少才能贴合
 *
 * 这是磁吸判定的正确度量：阈值 80/50/25px 描述的是「离贴合还差多远」，
 * 而不是两个中心点的距离。若用中心距，240×200 的卡片并排贴合时中心距已达 240px，
 * 永远超出 80px 阈值 → 并排吸附根本无法触发。
 *
 * 返回 gap = hypot(gapX, gapY)（gapX/gapY 为各轴分离量，重叠时为 0），
 * 以及各轴投影重叠长度 overlapX / overlapY（判定咬合时需要）。
 */
export function edgeGap(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
): { gap: number; gapX: number; gapY: number; overlapX: number; overlapY: number } {
  const gapX = Math.max(a.x - (b.x + b.w), b.x - (a.x + a.w), 0);
  const gapY = Math.max(a.y - (b.y + b.h), b.y - (a.y + a.h), 0);
  const overlapX = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const overlapY = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return { gap: Math.hypot(gapX, gapY), gapX, gapY, overlapX, overlapY };
}

/**
 * 计算拖拽节点与候选节点间的磁吸关系
 *
 * @param draggingNode 当前拖拽节点
 * @param allNodes 画布上所有节点（candidates 为空时的兜底）
 * @param config 磁吸配置
 * @param candidates 空间索引筛选出的候选节点（可选，性能优化）
 * @param ignoreIds 本次拖拽中已「断裂」的目标，需临时屏蔽，避免刚拉开又被吸回去
 * @returns 最强磁吸结果（level=none 表示无磁吸）
 */
export function computeMagnetic(
  draggingNode: Node,
  allNodes: Node[],
  config: MagneticConfig = DEFAULT_MAG_CONFIG,
  candidates?: Node[],
  ignoreIds?: Set<string>,
): MagneticResult {
  let best: MagneticResult = {
    level: "none",
    targetId: null,
    direction: null,
    snapX: draggingNode.position.x,
    snapY: draggingNode.position.y,
    distance: Infinity,
  };

  const dragRect = rectOf(draggingNode);
  const dragSize = { width: dragRect.w, height: dragRect.h };
  const dragCx = dragRect.x + dragRect.w / 2;
  const dragCy = dragRect.y + dragRect.h / 2;

  // 有候选集则只遍历候选（减少 O(n²) 全量扫描）
  const pool = candidates && candidates.length > 0 ? candidates : allNodes;

  for (const other of pool) {
    if (other.id === draggingNode.id) continue;
    if (ignoreIds && ignoreIds.has(other.id)) continue;

    const otherRect = rectOf(other);
    // 以「边距」衡量磁吸距离：0 = 已贴合
    const { gap } = edgeGap(dragRect, otherRect);

    if (gap > config.weakDistance) continue;

    // 判断磁吸等级（2026-09-17 新增 instant；2026-09-18 用户裁定所有等级拖拽中都直接吸附，
    // 等级仅用于目标优先级与 UI 反馈，不再区分吸附力度）
    let level: MagneticResult["level"] = "none";
    if (gap < config.instantDistance) level = "instant";
    else if (gap < config.strongDistance) level = "strong";
    else if (gap < config.mediumDistance) level = "medium";
    else level = "weak";

    // 只保留最强的磁吸（instant 最高档：漏掉它会导致 instant 被后遍历的 strong 覆盖）
    const levelRank = { none: 0, weak: 1, medium: 2, strong: 3, instant: 4 };
    if (levelRank[level] <= levelRank[best.level]) continue;

    const otherCx = otherRect.x + otherRect.w / 2;
    const otherCy = otherRect.y + otherRect.h / 2;
    const direction = getDirection(otherCx - dragCx, otherCy - dragCy, gap);
    // 用「拖拽节点尺寸」计算吸附落点，保证不同规格节点吸附不进内部
    // ⚠️ 方向取反（2026-09-17 修复「左右吸附跑到最右/上下不准」）：
    // direction 是「目标相对拖拽」的方位（用于六向语义标签，见 MagneticLines），
    // 而吸附落点要放在「目标相反一侧」——目标在拖拽右侧时，拖拽应贴到目标左侧，
    // 不能直接拿 direction 去 getSnapPosition（否则方向错 180°，吸附会甩到目标另一侧）。
    const snapPos = getSnapPosition(
      other.position,
      { width: otherRect.w, height: otherRect.h },
      dragSize,
      oppositeDirection(direction),
      // 单轴吸附（2026-09-18）：传入拖拽卡当前左上角，只动被吸附轴、另一轴保持原位
      { x: dragRect.x, y: dragRect.y },
    );

    best = {
      level,
      targetId: other.id,
      direction,
      snapX: snapPos.x,
      snapY: snapPos.y,
      distance: gap,
    };
  }

  return best;
}

/**
 * 判断空间方向
 * 根据两节点中心点的偏移量判断方向语义
 * @param gap 两卡边距：已贴合(≈0)且中心接近时视为层叠
 */
function getDirection(dx: number, dy: number, gap = 0): SpatialDirection {
  const absDx = Math.abs(dx);
  const absDy = Math.abs(dy);

  // 基本重叠 → 层叠（边距为 0 且两轴都没拉开）
  if (gap <= 1 && absDx < 60 && absDy < 40) {
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
 * 四向取反：left↔right、top↔bottom（stack 不变）。
 *
 * computeMagnetic 里 getDirection 返回「目标相对拖拽」的方位（供语义标签展示），
 * 但 getSnapPosition 期望的是「拖拽节点应放到目标的哪一侧」，两者正好相反——
 * 目标在拖拽右边 ⇒ 拖拽要贴到目标左边。故吸附落点必须先取反。
 */
function oppositeDirection(d: SpatialDirection): SpatialDirection {
  switch (d) {
    case "left":
      return "right";
    case "right":
      return "left";
    case "top":
      return "bottom";
    case "bottom":
      return "top";
    default:
      return d;
  }
}

/**
 * 计算吸附目标位置
 * 根据方向语义，在目标节点的对应方向放置拖拽节点
 * @param targetPos 目标节点左上角
 * @param targetSize 目标节点尺寸
 * @param dragSize 拖拽节点尺寸（防止吸附进内部）
 * @param direction 空间方向
 * @param dragPos 拖拽节点当前左上角（2026-09-18 单轴吸附用）
 */
function getSnapPosition(
  targetPos: { x: number; y: number },
  targetSize: NodeSize,
  dragSize: NodeSize,
  direction: SpatialDirection,
  dragPos?: { x: number; y: number },
): { x: number; y: number } {
  /**
   * 卡片间距（2026-09-16 用户裁定，对齐 Windows 磁贴「贴合无缝」观感）：
   * -2 = 两卡边框互相融合（卡片各有 1~3px 描边，贴合时相邻描边叠合成
   * 一条实色细线，而不是两条描边并排形成 2px 暗缝）；上下左右吸附统一生效。
   * 注意：落位重叠 ≤2px 仍在 Bond 判定容差内（edgeGap 重叠时 gap=0），
   * 不影响咬合 / 阻力三段式行为。
   */
  const gap = -2;

  /**
   * 单轴吸附（2026-09-18 用户裁定「借鉴手机主屏拖拽手感」）：
   *
   * 旧实现把非吸附轴的坐标硬取 targetPos，导致「吸左右轴时 y 被强行拽到目标 y」——
   * 几何实测：目标 T=(1000,1000)，拖拽卡在 T 右侧水平间隙 10px、垂直错开 180px 时，
   * 落点 y 被拉回 1000，等于瞬移一整个卡高（200px）。这正是「上下吸附不对」的真实来源。
   *
   * 新规则：**只动被吸附的那一轴，另一轴保持拖拽卡当前位置**（与 tldraw Snapping
   * 的「分轴独立判定、只调被吸附的那一轴」一致）。手机主屏手感同理：横向平移时
   * 图标不会纵向跳走。
   *
   * 无 dragPos（未传入）时回退旧行为，保证调用方兼容。
   */
  const keepX = dragPos ? dragPos.x : null;
  const keepY = dragPos ? dragPos.y : null;

  switch (direction) {
    case "left":
      return {
        x: targetPos.x - dragSize.width - gap,
        y: keepY !== null ? keepY : targetPos.y,
      };
    case "right":
      return {
        x: targetPos.x + targetSize.width + gap,
        y: keepY !== null ? keepY : targetPos.y,
      };
    case "top":
      return {
        x: keepX !== null ? keepX : targetPos.x,
        y: targetPos.y - dragSize.height - gap,
      };
    case "bottom":
      return {
        x: keepX !== null ? keepX : targetPos.x,
        y: targetPos.y + targetSize.height + gap,
      };
    case "stack":
      return { x: targetPos.x + 8, y: targetPos.y + 8 };
    default:
      return { x: targetPos.x, y: targetPos.y };
  }
}
