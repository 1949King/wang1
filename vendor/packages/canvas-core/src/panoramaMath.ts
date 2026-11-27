/**
 * 全景真 3D 环视纯函数（2026-11-20 · 本地三项优化项三）。
 *
 * 拖拽灵敏度与符号刻意沿用旧 2D PanoramaViewport（mediaExtraNodes.tsx）：
 *   yaw -= dx * 0.4、pitch += dy * 0.3、pitch 钳制 ±80。
 * 升级 three.js 真等距柱状环视后，节点头部「°」读数与手感保持不变。
 * 纯函数零依赖，vitest node 环境可测（无 jsdom）。
 */

/** 俯仰限幅（度），与旧 2D 一致。 */
export const PITCH_LIMIT = 80;
/** 偏航灵敏度（度/像素），与旧 2D 一致。 */
export const YAW_DEG_PER_PX = 0.4;
/** 俯仰灵敏度（度/像素），与旧 2D 一致。 */
export const PITCH_DEG_PER_PX = 0.3;
/** 滚轮缩放视场角边界（度）。 */
export const FOV_MIN = 35;
export const FOV_MAX = 90;
export const FOV_DEFAULT = 75;
/** 滚轮每单位 deltaY 的 fov 增量（下滚拉远、上滚拉近）。 */
const FOV_WHEEL_STEP = 0.05;

/** 俯仰钳制到 ±PITCH_LIMIT。 */
export function clampPitch(pitch: number): number {
  return Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, pitch));
}

/** 偏航归一到 [0,360)。 */
export function normalizeYaw(yaw: number): number {
  return ((yaw % 360) + 360) % 360;
}

/**
 * 由拖拽起点与像素增量算目标 yaw/pitch。
 * 符号与旧 2D 逐字一致：右拖（dx>0）yaw 减、下拖（dy>0）pitch 增。
 */
export function dragToYawPitch(
  startYaw: number,
  startPitch: number,
  dx: number,
  dy: number,
): { yaw: number; pitch: number } {
  return {
    yaw: startYaw - dx * YAW_DEG_PER_PX,
    pitch: clampPitch(startPitch + dy * PITCH_DEG_PER_PX),
  };
}

/** 滚轮调整视场角，钳制到 [FOV_MIN,FOV_MAX]；deltaY>0 拉远（fov 增）。 */
export function wheelFov(fov: number, deltaY: number): number {
  return Math.max(FOV_MIN, Math.min(FOV_MAX, fov + deltaY * FOV_WHEEL_STEP));
}

/** 度 → 弧度。 */
export function degToRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

/** 弧度 → 度。 */
export function radToDeg(rad: number): number {
  return (rad * 180) / Math.PI;
}
