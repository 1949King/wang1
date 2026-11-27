/**
 * 全景真 3D 环视纯函数回归（2026-11-20 · 本地三项优化项三）。
 *
 * 拖拽灵敏度与符号必须与旧 2D PanoramaViewport 逐字一致
 * （mediaExtraNodes.tsx：yaw -= dx*0.4、pitch += dy*0.3、pitch 钳制 ±80），
 * 保证升级 three.js 后节点头部「°」读数与手感不变。vitest node 环境，纯函数可测。
 */
import { describe, expect, it } from "vitest";

import {
  PITCH_LIMIT,
  YAW_DEG_PER_PX,
  PITCH_DEG_PER_PX,
  FOV_MIN,
  FOV_MAX,
  FOV_DEFAULT,
  clampPitch,
  normalizeYaw,
  dragToYawPitch,
  wheelFov,
  degToRad,
  radToDeg,
} from "./panoramaMath";

describe("clampPitch（与旧 2D ±80 一致）", () => {
  it("限幅到 ±80", () => {
    expect(clampPitch(0)).toBe(0);
    expect(clampPitch(90)).toBe(PITCH_LIMIT);
    expect(clampPitch(-90)).toBe(-PITCH_LIMIT);
    expect(clampPitch(80)).toBe(80);
    expect(clampPitch(-80)).toBe(-80);
    expect(clampPitch(1234)).toBe(80);
  });
});

describe("normalizeYaw（归一到 [0,360)）", () => {
  it("处理负角与多圈", () => {
    expect(normalizeYaw(0)).toBe(0);
    expect(normalizeYaw(360)).toBe(0);
    expect(normalizeYaw(-90)).toBe(270);
    expect(normalizeYaw(450)).toBe(90);
    expect(normalizeYaw(720)).toBe(0);
  });
});

describe("dragToYawPitch（符号与旧 2D 一致）", () => {
  it("右拖（dx>0）⇒ yaw 减；下拖（dy>0）⇒ pitch 增", () => {
    const r = dragToYawPitch(0, 0, 10, 10);
    expect(r.yaw).toBeCloseTo(-10 * YAW_DEG_PER_PX, 6);
    expect(r.pitch).toBeCloseTo(10 * PITCH_DEG_PER_PX, 6);
    expect(YAW_DEG_PER_PX).toBe(0.4);
    expect(PITCH_DEG_PER_PX).toBe(0.3);
  });

  it("左拖 ⇒ yaw 增；上拖 ⇒ pitch 减", () => {
    const r = dragToYawPitch(100, 10, -10, -10);
    expect(r.yaw).toBeCloseTo(104, 6);
    expect(r.pitch).toBeCloseTo(7, 6);
  });

  it("pitch 越界即钳制（不累积超出 ±80）", () => {
    expect(dragToYawPitch(0, 79, 0, 10).pitch).toBe(80);
    expect(dragToYawPitch(0, -79, 0, -10).pitch).toBe(-80);
  });
});

describe("wheelFov（35..90 边界 + 方向）", () => {
  it("默认 75，下滚（deltaY>0）拉远 fov 增、上滚拉近 fov 减", () => {
    expect(FOV_DEFAULT).toBe(75);
    expect(wheelFov(75, 100)).toBeGreaterThan(75);
    expect(wheelFov(75, -100)).toBeLessThan(75);
  });

  it("钳制到 [35,90]", () => {
    expect(wheelFov(75, 100000)).toBe(FOV_MAX);
    expect(wheelFov(75, -100000)).toBe(FOV_MIN);
    expect(wheelFov(90, 100)).toBe(FOV_MAX);
    expect(wheelFov(35, -100)).toBe(FOV_MIN);
    expect(FOV_MIN).toBe(35);
    expect(FOV_MAX).toBe(90);
  });
});

describe("deg↔rad", () => {
  it("180° = π，往返一致", () => {
    expect(degToRad(180)).toBeCloseTo(Math.PI, 9);
    expect(radToDeg(Math.PI)).toBeCloseTo(180, 9);
    expect(radToDeg(degToRad(37.5))).toBeCloseTo(37.5, 9);
  });
});
