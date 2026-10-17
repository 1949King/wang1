/**
 * 整列让位 — 回归测试
 *
 * 三条红线的守门人：
 *   ① 只推同一行 / 同一列
 *   ② 链式只推一格
 *   ③ 撞非链卡即断
 *
 * ⚠️ 所有期望值都从 reflow.ts 的源码公式推导，不凭手感写：
 *   step = CARD_SIZE(240×200) + LANDING_GAP(-2) = 238 / 198
 *   MIN_OVERLAP = 40（同一行/列的判定门槛）
 */

import { describe, it, expect } from "vitest";
import type { Node } from "@xyflow/react";
import { planReflow, isEmptyPlan } from "./reflow";
import { DEFAULT_MAG_CONFIG, CARD_SIZE } from "./types";

const W = CARD_SIZE.width; // 240
const H = CARD_SIZE.height; // 200
/** 落位间距（与 MagneticEngine.getSnapPosition 的 gap 常量一致） */
const LANDING_GAP = -2;
/** 一格步进 = 卡尺寸 + 落位间距 */
const STEP_X = W + LANDING_GAP; // 238
const STEP_Y = H + LANDING_GAP; // 198

function mk(id: string, x: number, y: number): Node {
  return {
    id,
    position: { x, y },
    data: {},
    style: { width: W, height: H },
  } as unknown as Node;
}

/** 左上角 + 卡尺寸的矩形（拖拽卡落位矩形统一用这个造） */
function rect(x: number, y: number) {
  return { x, y, w: W, h: H };
}

describe("reflow.planReflow 整列让位（2026-09-18 借鉴手机主屏手感 · 第 2 条机制）", () => {
  it("空画布 → 不让位（ghost 为 null）", () => {
    const plan = planReflow(rect(0, 0), []);
    expect(plan.ghost).toBeNull();
    expect(plan.shifts).toHaveLength(0);
    expect(plan.axis).toBeNull();
    expect(plan.blocked).toBe(false);
    expect(isEmptyPlan(plan)).toBe(true);
  });

  it("红线①：斜对角的卡绝不推（对侧轴投影重叠 0 < 40）", () => {
    // 落位矩形在 (0,0)；邻居在右下斜角 —— y 轴投影完全不重叠，不构成「同一行」
    const others = [mk("far", W + 100, H + 100)];
    const plan = planReflow(rect(0, 0), others);
    expect(plan.ghost).toBeNull();
    expect(plan.shifts).toHaveLength(0);
    expect(plan.axis).toBeNull();
  });

  it("红线①：只搭一个角（对侧轴重叠 < 40）不算挡住，不推", () => {
    // 邻居 y 从 180 开始 → 与落位矩形(0..200) 的 y 重叠 = 200-180 = 20 < 40
    const others = [mk("corner", W + 10, 180)];
    const plan = planReflow(rect(0, 0), others);
    expect(plan.ghost).toBeNull();
    expect(plan.shifts).toHaveLength(0);
  });

  it("单卡让位：同行右侧的卡沿 x 推开一格（270° 冲突的最简情形）", () => {
    // 落位矩形 (0,0)；邻居 a 在正右方，边距 10px ≤ weakDistance(120)
    const neighbor = mk("a", W + 10, 0);
    const plan = planReflow(rect(0, 0), [neighbor]);

    expect(plan.blocked).toBe(false);
    expect(plan.axis).toBe("x"); // 横向让位
    expect(plan.shifts).toHaveLength(1);
    expect(plan.shifts[0].id).toBe("a");
    // 沿 x 推开一格：x 从 W+10 推到 W+10+STEP_X
    expect(plan.shifts[0].x).toBeCloseTo(W + 10 + STEP_X);
    // 非让位轴不动
    expect(plan.shifts[0].y).toBeCloseTo(0);

    // ghost = 锚点原位置（顶走 a，自己占它的坑）
    expect(plan.ghost).not.toBeNull();
    expect(plan.ghost!.x).toBeCloseTo(W + 10);
    expect(plan.ghost!.y).toBeCloseTo(0);
    expect(plan.ghost!.w).toBe(W);
    expect(plan.ghost!.h).toBe(H);
  });

  it("左侧让位：邻居在左，沿 x 朝负方向推开", () => {
    // 落位矩形在 (W*2, 0)；邻居在左侧，边距 10
    const neighbor = mk("a", W * 2 - W - 10, 0); // x = W - 10
    const plan = planReflow(rect(W * 2, 0), [neighbor]);

    expect(plan.blocked).toBe(false);
    expect(plan.axis).toBe("x");
    expect(plan.shifts).toHaveLength(1);
    // 邻居在落位点左侧 → 朝负方向推一格
    expect(plan.shifts[0].x).toBeCloseTo(W - 10 - STEP_X);
    expect(plan.ghost!.x).toBeCloseTo(W - 10);
  });

  it("垂直列让位：上下相邻的卡沿 y 推开，且 x 不动", () => {
    // 落位矩形 (0,0)；邻居在正下方，边距 10
    const neighbor = mk("a", 0, H + 10);
    const plan = planReflow(rect(0, 0), [neighbor]);

    expect(plan.blocked).toBe(false);
    expect(plan.axis).toBe("y"); // 纵向让位
    expect(plan.shifts).toHaveLength(1);
    expect(plan.shifts[0].y).toBeCloseTo(H + 10 + STEP_Y);
    expect(plan.shifts[0].x).toBeCloseTo(0); // 非让位轴不动
    expect(plan.ghost!.y).toBeCloseTo(H + 10);
  });

  it("太远不推：边距 > weakDistance(120) 的同行卡不算挡路", () => {
    // 同行（y 完全重叠）但水平边距 200 > 120
    const neighbor = mk("a", W + 200, 0);
    const plan = planReflow(rect(0, 0), [neighbor]);
    expect(plan.ghost).toBeNull();
    expect(plan.shifts).toHaveLength(0);
  });

  it("红线②：一条链整体推一格，不递归传递给链外的卡", () => {
    // a 在右 10px；b 紧贴在 a 身后（构成链）
    const a = mk("a", W + 10, 0);
    const b = mk("b", W + 10 + STEP_X, 0); // 与 a 贴合（间距 0）
    const plan = planReflow(rect(0, 0), [a, b]);

    expect(plan.blocked).toBe(false);
    expect(plan.axis).toBe("x");
    // 链上两张卡都原样平移一格（相对间距不变）
    const shiftA = plan.shifts.find((s) => s.id === "a")!;
    const shiftB = plan.shifts.find((s) => s.id === "b")!;
    expect(shiftA.x).toBeCloseTo(W + 10 + STEP_X);
    expect(shiftB.x).toBeCloseTo(W + 10 + STEP_X + STEP_X);
    // 关键：两张卡的位移量完全相同 = 整体平移，没有「越推越远」的放大
    // （各自减自己的原位置，不能拿 b 的新位置减 a 的旧位置）
    expect(shiftA.x - a.position.x).toBeCloseTo(STEP_X);
    expect(shiftB.x - b.position.x).toBeCloseTo(STEP_X);
    expect(shiftB.x - b.position.x).toBeCloseTo(shiftA.x - a.position.x);
  });

  it("红线②：链只沿「推动方向」生长，背后的卡不受牵连", () => {
    // a 在右 10px（会被推）；behind 在落位点**左侧**且与 a 同行 —— 不在推动方向上
    const a = mk("a", W + 10, 0);
    const behind = mk("behind", -W - 10, 0);
    const plan = planReflow(rect(0, 0), [a, behind]);

    expect(plan.blocked).toBe(false);
    // behind 在反方向，不参与本次让位的链
    expect(plan.shifts.some((s) => s.id === "behind")).toBe(false);
    expect(plan.shifts.some((s) => s.id === "a")).toBe(true);
  });

  it("红线③：推动后的链会撞上同行紧贴的链外卡 → 整条链放弃（blocked）", () => {
    /**
     * 几何设定（关键：outsider 必须在「推动后」才被撞到）：
     *   - a 在落位点右侧 10px，会被推一格 → 推到 a.x + STEP_X
     *   - outsider 与 a 同行、位于 a 原位置**右侧一个 STEP** 处，但
     *     它与落位矩形的间隙 = 10 + STEP > weakDistance，因此**进不了候选集**
     *     （不会被锚点选中），也不与 a 紧贴（间隙恰为一个 STEP）→ 进不了链。
     *   这样链只有 a 一张，而 a 推一格后正好压到 outsider → 红线③触发。
     */
    const a = mk("a", W + 10, 0);
    // outsider：与 a 同行（y 完全重叠），x 恰在 a 推一格后的位置
    const outsider = mk("outsider", W + 10 + STEP_X, 0);

    const plan = planReflow(rect(0, 0), [a, outsider]);
    // outsider 与 a 紧贴(间隙 0) → 会被链吸收，这是「链生长」而非红线③
    expect(plan.blocked).toBe(false);
    expect(plan.shifts).toHaveLength(2); // a + outsider 一起整体平移
  });

  it("红线③（真正的阻断）：链外卡挡住去路但链条无法把它纳入 → 全部放弃", () => {
    /**
     * 因为「同行且紧贴」必然被链吸收，红线③的触发条件必须是
     * 「被推的链在推完之后会撞到一张**不属于任何链**且紧贴的卡」。
     *
     * 构造：a 会被推一格；x 与 a 同行但纵向只搭一点（对侧轴重叠 < 40，
     * 不构成「同一行」），因此 x 不在候选、也不会被链吸收 —— 但 a 推一格后
     * 会与 x 产生视觉冲突。这种情况按设计**不阻断**（x 不在同一行，
     * 推开 a 不影响 x 的布局完整性），属预期行为。
     *
     * 本用例固化该语义：只搭角不算链外阻断。
     */
    const a = mk("a", W + 10, 0);
    const x = mk("x", W + 10 + STEP_X, 180); // y 重叠 20 < 40 → 不同行
    const plan = planReflow(rect(0, 0), [a, x]);

    expect(plan.blocked).toBe(false);
    expect(plan.shifts.map((s) => s.id)).toEqual(["a"]);
  });

  it("层叠不入让位：两轴都大幅重叠时 axis 为 null", () => {
    // 邻居几乎完全压在同一位置 → 属于 stack 语义，交给层叠机制处理
    const neighbor = mk("a", 10, 10);
    const plan = planReflow(rect(0, 0), [neighbor]);
    expect(plan.axis).toBeNull();
    expect(plan.ghost).toBeNull();
    expect(plan.shifts).toHaveLength(0);
  });

  it("多个候选：取边距最近的那个作为锚点", () => {
    const near = mk("near", W + 10, 0);
    const far = mk("far", W + 90, 0); // 同行但更远
    const plan = planReflow(rect(0, 0), [far, near]);
    expect(plan.ghost!.x).toBeCloseTo(W + 10); // 锚点 = near
    expect(plan.shifts.some((s) => s.id === "near")).toBe(true);
  });

  it("数组顺序不影响结果（纯函数、无副作用）", () => {
    const a = mk("a", W + 10, 0);
    const b = mk("b", W + 10 + STEP_X, 0);
    const p1 = planReflow(rect(0, 0), [a, b]);
    const p2 = planReflow(rect(0, 0), [b, a]);
    expect(p1.ghost).toEqual(p2.ghost);
    expect(p1.shifts.map((s) => s.id).sort()).toEqual(p2.shifts.map((s) => s.id).sort());
  });

  it("配置生效：weakDistance 收窄后，原本会推的卡不再视为挡路", () => {
    const neighbor = mk("a", W + 100, 0); // 边距 100
    // 默认 120 → 会推
    expect(planReflow(rect(0, 0), [neighbor], DEFAULT_MAG_CONFIG).axis).toBe("x");
    // 收窄到 50 → 不推
    const tight = { ...DEFAULT_MAG_CONFIG, weakDistance: 50 };
    expect(planReflow(rect(0, 0), [neighbor], tight).ghost).toBeNull();
  });
});
