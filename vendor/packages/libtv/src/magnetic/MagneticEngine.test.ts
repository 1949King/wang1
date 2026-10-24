import { describe, it, expect } from "vitest";
import type { Node } from "@xyflow/react";
import { computeMagnetic } from "./MagneticEngine";
import { DEFAULT_MAG_CONFIG, CARD_SIZE } from "./types";

describe("MagneticEngine.computeMagnetic 方向吸附（回归：方向反了 180° bug）", () => {
  const W = CARD_SIZE.width;
  const H = CARD_SIZE.height;
  const gap = -2; // 贴合落位（对齐 Win11 磁贴无缝观感）

  function mk(id: string, x: number, y: number): Node {
    return {
      id,
      position: { x, y },
      data: {},
      style: { width: W, height: H },
    } as unknown as Node;
  }

  it("目标在右 → 拖拽贴到目标左侧（不甩到最右）", () => {
    const drag = mk("a", 0, 0);
    const target = mk("b", W + 30, 0); // 目标在右，边距 30px
    const r = computeMagnetic(drag, [drag, target], DEFAULT_MAG_CONFIG);
    expect(r.targetId).toBe("b");
    expect(r.direction).toBe("right"); // 语义标签：目标在右 = 输出接续
    expect(r.snapX).toBeCloseTo(target.position.x - W - gap); // = 目标左边
    expect(r.snapX).toBeLessThan(target.position.x);
  });

  it("目标在左 → 拖拽贴到目标右侧", () => {
    const drag = mk("a", W + 30, 0);
    const target = mk("b", 0, 0); // 目标在左
    const r = computeMagnetic(drag, [drag, target], DEFAULT_MAG_CONFIG);
    expect(r.targetId).toBe("b");
    expect(r.direction).toBe("left");
    expect(r.snapX).toBeCloseTo(target.position.x + W + gap); // = 目标右边
    expect(r.snapX).toBeGreaterThan(target.position.x);
  });

  it("目标在下 → 拖拽贴到目标上方（不甩到最下）", () => {
    const drag = mk("a", 0, 0);
    const target = mk("b", 0, H + 30); // 目标在下，边距 30px
    const r = computeMagnetic(drag, [drag, target], DEFAULT_MAG_CONFIG);
    expect(r.targetId).toBe("b");
    expect(r.direction).toBe("bottom");
    expect(r.snapY).toBeCloseTo(target.position.y - H - gap); // = 目标上方
    expect(r.snapY).toBeLessThan(target.position.y);
  });

  it("目标在上 → 拖拽贴到目标下方", () => {
    const drag = mk("a", 0, H + 30);
    const target = mk("b", 0, 0); // 目标在上
    const r = computeMagnetic(drag, [drag, target], DEFAULT_MAG_CONFIG);
    expect(r.targetId).toBe("b");
    expect(r.direction).toBe("top");
    expect(r.snapY).toBeCloseTo(target.position.y + H + gap); // = 目标下方
    expect(r.snapY).toBeGreaterThan(target.position.y);
  });

  it("instant 档优先于 strong 档（levelRank 漏 instant 的回归）", () => {
    const drag = mk("a", 0, 0);
    const near = mk("near", W + 5, 0); // gap 5px → instant
    const far = mk("far", W + 30, 0); // gap 30px → strong
    // near 在数组前：旧 levelRank 缺 instant 时，后遍历的 strong 会错误覆盖 instant
    const r = computeMagnetic(drag, [drag, near, far], DEFAULT_MAG_CONFIG);
    expect(r.targetId).toBe("near");
    expect(r.level).toBe("instant");
  });
});

describe("单轴吸附（2026-09-18 借鉴手机主屏手感：吸一轴不拽走另一轴）", () => {
  const W = CARD_SIZE.width;
  const H = CARD_SIZE.height;

  function mk(id: string, x: number, y: number): Node {
    return {
      id,
      position: { x, y },
      data: {},
      style: { width: W, height: H },
    } as unknown as Node;
  }

  /**
   * 回归根因：旧 getSnapPosition 在 case "left"/"right" 里硬取 `y: targetPos.y`，
   * 导致「横向吸附时纵坐标被强行拽到目标 y」——几何实测垂直错开 180px 时，
   * 落点 y 被拉回，等于瞬移一整个卡高。这正是用户反馈「上下吸附不对」的真实来源。
   */
  it("吸左右轴时，y 必须保持拖拽卡当前位置（不被拽到目标 y）", () => {
    const dragY = 1180; // 与目标 y(1000) 垂直错开 180px
    const drag = mk("a", 0, dragY);
    const target = mk("b", W + 30, 1000); // 目标在右，垂直错开
    const r = computeMagnetic(drag, [drag, target], DEFAULT_MAG_CONFIG);
    expect(r.targetId).toBe("b");
    expect(r.direction).toBe("right");
    // x 被吸附到目标左侧：targetPos.x - W - gap（gap=-2 → 实际 +2）
    expect(r.snapX).toBeCloseTo(target.position.x - W + 2);
    // y 保持不变 —— 这是本次修复的核心断言
    expect(r.snapY).toBeCloseTo(dragY);
    expect(r.snapY).not.toBeCloseTo(target.position.y);
  });

  it("吸上下轴时，x 必须对齐目标 x（顶边对齐成列，2026-09-23 用户裁定）", () => {
    /**
     * ⚠️ 本用例同时暴露一个已知几何约束（见排查报告「根因 5」）：
     * computeMagnetic 用 hypot(gapX, gapY) 与 weakDistance(120) 比对，两轴被合并。
     * 因此「水平中心差 240 才让垂直方向主导」与「垂直边距需 < 120 才进磁吸范围」
     * 无法同时满足（240-200=40 边距可行，但需 target.y ≥ 340；此时边距 140 > 120）。
     * 故此处取斜向工况：垂直优势足以判 bottom，且总边距在范围内。
     *
     * 历史：2026-09-18 裁定「单轴吸附」时本处断言 x 保持不变（= dragX），
     * 但用户实测反馈「卡片最上端的吸附没有对齐」——上下贴住后左右边缘错开、
     * 不成列。2026-09-23 用户裁定修订：top/bottom 的 x 改为 targetPos.x
     * （left/right 的单轴语义保持不变，仍不拽 y）。
     */
    const dragX = 1240;
    const drag = mk("a", dragX, 0); // 中心 (1360, 100)
    const target = mk("b", 1000, 320); // 中心 (1120, 420)：dx=-240, dy=+320 → 垂直主导
    const r = computeMagnetic(drag, [drag, target], DEFAULT_MAG_CONFIG);
    expect(r.targetId).toBe("b");
    expect(r.direction).toBe("bottom");
    // y 被吸附到目标上方：targetPos.y - H - gap（gap=-2 → 实际 +2）
    expect(r.snapY).toBeCloseTo(target.position.y - H + 2);
    // x 对齐目标 —— 本次修订的核心断言
    expect(r.snapX).toBeCloseTo(target.position.x);
    expect(r.snapX).not.toBeCloseTo(dragX);
  });

  it("旧行为反例自证：同轴（y 相等）时新旧结果一致，不引入回归", () => {
    const drag = mk("a", 0, 500);
    const target = mk("b", W + 30, 500); // 完全同轴
    const r = computeMagnetic(drag, [drag, target], DEFAULT_MAG_CONFIG);
    expect(r.snapY).toBeCloseTo(500); // 保持 500，与旧实现 targetPos.y(500) 等价
  });
});
