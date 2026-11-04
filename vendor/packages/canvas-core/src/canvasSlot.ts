/**
 * Agent 铺卡确定性槽位（V4.46.3 · 2026-10-21）
 *
 * 根因（用户截图实锤）：`store.addNode` 无坐标时用 `Math.random()` 在
 * 120~440 × 80~320 的小盒子里撒点（store.ts 属冻结区 canvas-magnetic-intent，
 * 不可改）；Agent 一次铺一批卡（工作流）时全挤在同一小盒子 ⇒ 互相叠压混乱。
 *
 * 本模块在**非冻结侧**给出确定性网格槽位：从左上往右逐槽扫，跳过被已有节点
 * 占据的槽，返回第一个空位。Agent 批量铺卡因此天然排成整齐网格；用户手动
 * 拖过的卡会占住自己的槽，不会被新卡压上。纯函数，vitest 可测。
 */

export type SlotPos = { x: number; y: number };

/** 槽位间距：卡默认宽 240~280 / 高 160~240，留出手感间隙。 */
export const SLOT_GAP_X = 300;
export const SLOT_GAP_Y = 230;
export const SLOT_COLS = 5;
export const SLOT_ORIGIN: SlotPos = { x: 80, y: 80 };

/** 第 i 个槽位的坐标（行主序网格）。 */
export function slotAt(i: number): SlotPos {
  return {
    x: SLOT_ORIGIN.x + (i % SLOT_COLS) * SLOT_GAP_X,
    y: SLOT_ORIGIN.y + Math.floor(i / SLOT_COLS) * SLOT_GAP_Y,
  };
}

/**
 * 找第一个「离所有已有节点足够远」的槽位。
 * 判据：与任一现有节点位置在 0.7× 槽距内视为占据该槽。
 * 扫满 500 槽仍全占 ⇒ 沿确定性对角线兜底（绝不回退随机）。
 */
export function nextFreeSlot(
  nodes: ReadonlyArray<{ position: { x: number; y: number } }>,
): SlotPos {
  const occupied = (p: SlotPos) =>
    nodes.some(
      (n) =>
        Math.abs(n.position.x - p.x) < SLOT_GAP_X * 0.7 &&
        Math.abs(n.position.y - p.y) < SLOT_GAP_Y * 0.7,
    );
  for (let i = 0; i < 500; i++) {
    const p = slotAt(i);
    if (!occupied(p)) return p;
  }
  const n = nodes.length;
  return { x: SLOT_ORIGIN.x + (n % 40) * 40, y: SLOT_ORIGIN.y + n * 20 };
}
