/**
 * canvasSlot 确定性槽位单测（V4.46.3 · 修「Agent 铺卡混乱」）。
 */
import { describe, expect, it } from "vitest";
import { nextFreeSlot, slotAt, SLOT_COLS, SLOT_GAP_X, SLOT_GAP_Y, SLOT_ORIGIN } from "./canvasSlot";

describe("slotAt 网格", () => {
  it("行主序：第 0 槽在原点，第 COLS 槽换行", () => {
    expect(slotAt(0)).toEqual(SLOT_ORIGIN);
    expect(slotAt(1).x).toBe(SLOT_ORIGIN.x + SLOT_GAP_X);
    expect(slotAt(SLOT_COLS)).toEqual({ x: SLOT_ORIGIN.x, y: SLOT_ORIGIN.y + SLOT_GAP_Y });
  });

  it("确定性：同输入恒同输出（无随机）", () => {
    for (let i = 0; i < 30; i++) {
      expect(slotAt(i)).toEqual(slotAt(i));
    }
  });
});

describe("nextFreeSlot 找空位", () => {
  it("空画布 → 第一槽", () => {
    expect(nextFreeSlot([])).toEqual(slotAt(0));
  });

  it("已有节点占位 → 下一槽，不叠压", () => {
    const p0 = nextFreeSlot([]);
    const p1 = nextFreeSlot([{ position: p0 }]);
    expect(p1).not.toEqual(p0);
    // 相邻槽间距足够大，不会互相压卡
    expect(Math.abs(p1.x - p0.x) + Math.abs(p1.y - p0.y)).toBeGreaterThan(150);
  });

  it("批量铺 12 张卡互不重叠（用户场景：工作流一批卡）", () => {
    const placed: Array<{ position: { x: number; y: number } }> = [];
    for (let i = 0; i < 12; i++) {
      placed.push({ position: nextFreeSlot(placed) });
    }
    for (let a = 0; a < placed.length; a++) {
      for (let b = a + 1; b < placed.length; b++) {
        const dx = Math.abs(placed[a].position.x - placed[b].position.x);
        const dy = Math.abs(placed[a].position.y - placed[b].position.y);
        // 任意两卡至少一个轴分开 ≥0.7 槽距（默认卡宽 240~340 不重叠）
        expect(dx >= SLOT_GAP_X * 0.7 || dy >= SLOT_GAP_Y * 0.7).toBe(true);
      }
    }
  });

  it("用户手动拖过的卡占住槽 ⇒ 新卡绕开（近似位置也算占据）", () => {
    const dragged = { position: { x: SLOT_ORIGIN.x + 12, y: SLOT_ORIGIN.y + 8 } };
    const p = nextFreeSlot([dragged]);
    expect(p).toEqual(slotAt(1));
  });

  it("满 500 槽极端场景仍确定性兜底（绝不回退随机）", () => {
    const crowded = Array.from({ length: 600 }, (_, i) => ({
      position: { x: (i % 40) * 40 + SLOT_ORIGIN.x, y: Math.floor(i / 40) * 20 + SLOT_ORIGIN.y },
    }));
    const a = nextFreeSlot(crowded);
    const b = nextFreeSlot(crowded);
    expect(a).toEqual(b);
  });
});
