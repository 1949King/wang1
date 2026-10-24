/**
 * 桌宠动作曲线回归。用例 1~7 与参考开源画布（`vendor/AI-Canvas-tauri/tests/components/mascotMotion.test.ts`）
 * **逐条对应**，保证「移植」不是自我感觉良好；第 8 条起是狐狸专属动作。
 */
import { describe, expect, it } from "vitest";

import {
  AMBIENT_MAX_GAP,
  AMBIENT_MIN_GAP,
  CURIOUS_MAX_TILT_DEG,
  CURIOUS_RADIUS_PX,
  EYE_POSES,
  REACTION_DURATIONS,
  STATUS_BUBBLES,
  STATUS_RIM_COLORS,
  getBlinkScaleY,
  getBreath,
  getCuriousTilt,
  getSleepyBreath,
  nextAmbientGap,
  pickAmbientKind,
  getEarDroop,
  getEarFlick,
  getReactionPose,
  getSquashWidth,
  getStatusEnergy,
  getTailSwing,
  nextBlinkGap,
  pickNextGazeIndex,
  planBlink,
  reactionForStatus,
  type PetStatus,
} from "./mascotMotion";

const ALL_STATUSES: PetStatus[] = ["idle", "thinking", "awaiting", "success", "error"];

describe("mascotMotion（与参考实现同源）", () => {
  it("starts and ends every reaction at the neutral pose", () => {
    for (const kind of ["hop", "shake"] as const) {
      for (const progress of [0, 1, 1.5]) {
        const pose = getReactionPose(kind, progress);
        // 反应两端必须回到中立姿态，否则结束后场景里会留下残余位移或旋转
        expect(pose.lift).toBeCloseTo(0, 6);
        expect(pose.yaw).toBeCloseTo(0, 6);
        expect(pose.squashY).toBeCloseTo(1, 6);
      }
    }
  });

  it("lifts the body and stretches it mid-air during a hop", () => {
    const peak = getReactionPose("hop", 0.5);
    expect(peak.lift).toBeGreaterThan(0.1);
    expect(peak.squashY).toBeGreaterThan(1);
    expect(peak.yaw).toBe(0);

    // 起跳前下蹲、落地压扁：两端都比原始高度矮
    expect(getReactionPose("hop", 0.09).squashY).toBeLessThan(1);
    expect(getReactionPose("hop", 0.91).squashY).toBeLessThan(1);
  });

  it("swings the head both ways and decays over a shake", () => {
    const samples = Array.from({ length: 40 }, (_, index) => getReactionPose("shake", index / 40).yaw);
    expect(Math.max(...samples)).toBeGreaterThan(0.05);
    expect(Math.min(...samples)).toBeLessThan(-0.05);

    // 摆幅随进度衰减：后段的最大绝对值必须小于前段
    const earlyPeak = Math.max(...samples.slice(0, 10).map(Math.abs));
    const latePeak = Math.max(...samples.slice(30).map(Math.abs));
    expect(latePeak).toBeLessThan(earlyPeak);

    // 摇头不该把身体抬起来
    expect(getReactionPose("shake", 0.5).lift).toBeLessThan(0);
  });

  it("keeps the reaction durations positive and short enough to read as one beat", () => {
    expect(REACTION_DURATIONS.hop).toBeGreaterThan(0);
    expect(REACTION_DURATIONS.shake).toBeGreaterThan(0);
    expect(REACTION_DURATIONS.hop).toBeLessThan(1.2);
    expect(REACTION_DURATIONS.shake).toBeLessThan(1.2);
  });

  it("widens the body when it is squashed and narrows it when stretched", () => {
    expect(getSquashWidth(1)).toBeCloseTo(1, 6);
    expect(getSquashWidth(0.86)).toBeGreaterThan(1);
    expect(getSquashWidth(1.09)).toBeLessThan(1);
    // 极端值不能算出无穷或负数缩放
    expect(Number.isFinite(getSquashWidth(0))).toBe(true);
    expect(getSquashWidth(0)).toBeGreaterThan(0);
  });

  it("never picks the gaze point it is already looking at", () => {
    for (let current = 0; current < 5; current += 1) {
      for (const random of [0, 0.19, 0.4, 0.61, 0.83, 0.999]) {
        const next = pickNextGazeIndex(current, 5, random);
        expect(next).not.toBe(current);
        expect(next).toBeGreaterThanOrEqual(0);
        expect(next).toBeLessThan(5);
      }
    }
  });

  it("stays in range when random returns exactly 1 or there is a single point", () => {
    expect(pickNextGazeIndex(-1, 6, 1)).toBe(5);
    expect(pickNextGazeIndex(0, 1, 0.5)).toBe(0);
  });
});

describe("狐狸专属动作", () => {
  it("呼吸只压扁不拉长（拉长会被误读成弹跳）", () => {
    for (let i = 0; i <= 40; i += 1) {
      const v = getBreath((i / 40) * 8);
      expect(v).toBeLessThanOrEqual(1);
      expect(v).toBeGreaterThan(0.97);
    }
  });

  it("眨眼两端睁眼、中点闭合，且间隔落在配置区间内", () => {
    expect(getBlinkScaleY(0)).toBeCloseTo(1, 6);
    expect(getBlinkScaleY(1)).toBeCloseTo(1, 6);
    expect(getBlinkScaleY(0.5)).toBeLessThan(0.1);
    for (const r of [0, 0.25, 0.5, 0.75, 1]) {
      const gap = nextBlinkGap(r);
      expect(gap).toBeGreaterThanOrEqual(2.2);
      expect(gap).toBeLessThanOrEqual(5.5);
    }
    // 越界输入不能抛出或算出负间隔
    expect(nextBlinkGap(-3)).toBeGreaterThan(0);
    expect(nextBlinkGap(9)).toBeGreaterThan(0);
  });

  it("眨眼序列的触发概率是确定性的（同输入同输出）", () => {
    expect(planBlink(0.1, 0.9)).toEqual({ double: true, wink: false });
    expect(planBlink(0.9, 0.1)).toEqual({ double: false, wink: true });
    expect(planBlink(0.5, 0.5)).toEqual({ double: false, wink: false });
    // 边界 0.18 / 0.12 归「不触发」，防止阈值被随手改成 <= 产生抖动
    expect(planBlink(0.18, 0.12).double).toBe(false);
    expect(planBlink(0.18, 0.12).wink).toBe(false);
  });

  it("耳抖两端回零，且不会出现反向折耳（负值）", () => {
    for (const p of [0, 1, 2]) expect(getEarFlick(p)).toBeCloseTo(0, 6);
    for (let i = 0; i <= 40; i += 1) expect(getEarFlick(i / 40)).toBeGreaterThanOrEqual(0);
  });

  it("出错时耳垂下、等待确认时耳竖起", () => {
    expect(getEarDroop("error")).toBeLessThan(0);
    expect(getEarDroop("awaiting")).toBeGreaterThan(0);
    expect(getEarDroop("idle")).toBe(0);
  });

  it("尾巴在有限时间内有正负摆动，且能量越高摆幅越大", () => {
    const low = Array.from({ length: 60 }, (_, i) => getTailSwing(i / 60, 0.1));
    const high = Array.from({ length: 60 }, (_, i) => getTailSwing(i / 60, 0.95));
    const span = (xs: number[]) => Math.max(...xs) - Math.min(...xs);
    expect(span(low)).toBeGreaterThan(0);
    expect(span(high)).toBeGreaterThan(span(low));
    // 越界能量被夹住，不能出现爆炸摆幅
    expect(Math.abs(getTailSwing(1, 99))).toBeLessThanOrEqual(0.5);
  });

  it("每个状态都有完整的视觉配置（不外泄 undefined 到渲染层）", () => {
    for (const s of ALL_STATUSES) {
      expect(EYE_POSES[s]).toBeTruthy();
      expect(EYE_POSES[s].scaleY).toHaveLength(2);
      expect(EYE_POSES[s].pupilScale).toBeGreaterThan(0);
      expect(typeof STATUS_RIM_COLORS[s]).toBe("number");
      expect(s in STATUS_BUBBLES).toBe(true);
      expect(Number.isFinite(getStatusEnergy(s))).toBe(true);
      expect(getStatusEnergy(s)).toBeGreaterThanOrEqual(0);
      expect(getStatusEnergy(s)).toBeLessThanOrEqual(1);
    }
  });

  it("等待确认与成功各播一次肢体反应，待命不播", () => {
    expect(reactionForStatus("awaiting")).toBe("hop");
    expect(reactionForStatus("success")).toBe("hop");
    expect(reactionForStatus("error")).toBe("shake");
    expect(reactionForStatus("idle")).toBeNull();
    expect(reactionForStatus("thinking")).toBeNull();
  });
});

describe("生命力层（2026-10-20）：待机小动作 / 打瞌睡 / 好奇", () => {
  it("待机小动作间隔落在设计区间内，随机数越界被夹住", () => {
    for (const random of [0, 0.25, 0.5, 0.75, 1, -1, 2]) {
      const gap = nextAmbientGap(random);
      expect(gap).toBeGreaterThanOrEqual(AMBIENT_MIN_GAP);
      expect(gap).toBeLessThanOrEqual(AMBIENT_MAX_GAP);
    }
  });

  it("待机小动作种类确定性、三种都会出现，且歪头占比最高", () => {
    expect(pickAmbientKind(0)).toBe("tilt");
    expect(pickAmbientKind(0.44)).toBe("tilt");
    expect(pickAmbientKind(0.45)).toBe("sway");
    expect(pickAmbientKind(0.79)).toBe("sway");
    expect(pickAmbientKind(0.8)).toBe("perk");
    expect(pickAmbientKind(1)).toBe("perk");
    expect(new Set([0, 0.5, 0.9].map(pickAmbientKind)).size).toBe(3);
  });

  it("睡眠呼吸永远是压扁而非变高（同清醒呼吸的不变量），且比清醒更深", () => {
    for (let time = 0; time < 12; time += 0.15) {
      const scale = getSleepyBreath(time);
      expect(scale).toBeLessThanOrEqual(1);
      expect(scale).toBeGreaterThan(0.95);
    }
    const sleepyMin = Math.min(...Array.from({ length: 80 }, (_, i) => getSleepyBreath(i / 10)));
    const awakeMin = Math.min(...Array.from({ length: 80 }, (_, i) => getBreath(i / 10)));
    expect(sleepyMin).toBeLessThan(awakeMin);
  });

  it("好奇倾角有界、半径外为零、方向跟随指针左右、越近越倾", () => {
    expect(getCuriousTilt(0, 0)).toBe(0);
    expect(getCuriousTilt(CURIOUS_RADIUS_PX + 10, 0)).toBe(0);
    expect(getCuriousTilt(99999, 99999)).toBe(0);

    const left = getCuriousTilt(-40, 0);
    const right = getCuriousTilt(40, 0);
    expect(left).toBeLessThan(0);
    expect(right).toBeGreaterThan(0);
    expect(Math.abs(left)).toBeLessThanOrEqual(CURIOUS_MAX_TILT_DEG);
    expect(Math.abs(getCuriousTilt(-8, 0))).toBeGreaterThan(Math.abs(left));

    // 非有限输入不得把 NaN 漏进渲染层
    expect(getCuriousTilt(Number.NaN, 0)).toBe(0);
  });
});
