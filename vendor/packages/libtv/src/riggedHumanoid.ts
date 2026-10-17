/**
 * 内置关节素模系统：
 * 提供男/女/瘦/胖/儿童五种体型预设（CapsuleGeometry 圆滑体素），
 * 15 关节层级 + 21 旋转角可自由摆姿，搭配 POSE_PRESETS 快速落位。
 * 骨骼层级不变，JointPose / BONE_ROTATION_MAP 直接复用。
 */
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";

/** ── 缓动函数（必须在 POSE_PRESETS / MOTION_PRESETS 之前声明，避免 TDZ） ── */
export const easeLinear = (t: number) => t;
export const easeInOutCubic = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
export const easeInOutSine = (t: number): number =>
  -(Math.cos(Math.PI * t) - 1) / 2;
export const easeOutBack = (t: number): number => {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
};

/* 以下缓动函数对齐后端 app/core/keyframe_animation.py 的 EasingType 枚举，
 * 便于后端点单动作把带 easing/bezier 的关键帧推到画布时语义一致。 */
/** ease_in：二次加速 */
export const easeIn = (t: number): number => t * t;
/** ease_out：二次减速 */
export const easeOut = (t: number): number => t * (2 - t);
/** ease_in_out：smoothstep 缓入缓出 */
export const easeInOut = (t: number): number => t * t * (3 - 2 * t);
/** cubic_ease_in：三次加速 */
export const easeCubicIn = (t: number): number => t * t * t;
/** cubic_ease_out：三次减速 */
export const easeCubicOut = (t: number): number => 1 - Math.pow(1 - t, 3);
/** back：easeInBack（超出再回弹） */
export const easeInBack = (t: number): number => {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return c3 * t * t * t - c1 * t * t;
};
/** bounce：easeOutBounce */
export const easeOutBounce = (t: number): number => {
  const n1 = 7.5625;
  const d1 = 2.75;
  if (t < 1 / d1) return n1 * t * t;
  if (t < 2 / d1) return n1 * (t - 1.5 / d1) ** 2 + 0.75;
  if (t < 2.5 / d1) return n1 * (t - 2.25 / d1) ** 2 + 0.9375;
  return n1 * (t - 2.625 / d1) ** 2 + 0.984375;
};
/** elastic：easeOutElastic */
export const easeOutElastic = (t: number): number => {
  if (t === 0 || t === 1) return t;
  const c4 = (2 * Math.PI) / 3;
  return Math.pow(2, -10 * t) * Math.sin((t * 10 - 0.75) * c4) + 1;
};

/* ── 缓动命名 + 映射（对齐后端 app/core/keyframe_animation.py 的 EasingType） ──
 * 后端 EasingType：linear / ease_in / ease_out / ease_in_out / bounce /
 * elastic / back / cubic_ease_in / cubic_ease_out / cubic_ease_in_out。 */
export type EasingName =
  | "linear"
  | "ease_in"
  | "ease_out"
  | "ease_in_out"
  | "bounce"
  | "elastic"
  | "back"
  | "cubic_ease_in"
  | "cubic_ease_out"
  | "cubic_ease_in_out";

/** EasingName → 缓动函数（语义与后端 _apply_easing 一致） */
export const EASING_FNS: Record<EasingName, (t: number) => number> = {
  linear: easeLinear,
  ease_in: easeIn,
  ease_out: easeOut,
  ease_in_out: easeInOut,
  bounce: easeOutBounce,
  elastic: easeOutElastic,
  back: easeInBack,
  cubic_ease_in: easeCubicIn,
  cubic_ease_out: easeCubicOut,
  cubic_ease_in_out: easeInOutCubic,
};

/** 缓动中文标签，供 UI 下拉展示 */
export const EASING_LABELS: Record<EasingName, string> = {
  linear: "线性",
  ease_in: "缓入",
  ease_out: "缓出",
  ease_in_out: "缓入缓出",
  bounce: "弹跳",
  elastic: "弹性",
  back: "回弹",
  cubic_ease_in: "三次缓入",
  cubic_ease_out: "三次缓出",
  cubic_ease_in_out: "三次缓入缓出",
};

/** 缓动枚举顺序（供 UI 下拉按固定顺序渲染） */
export const EASING_NAMES: EasingName[] = [
  "linear",
  "ease_in",
  "ease_out",
  "ease_in_out",
  "bounce",
  "elastic",
  "back",
  "cubic_ease_in",
  "cubic_ease_out",
  "cubic_ease_in_out",
];

/** 变更此值会强制 Stage3D 重建旧场景中的人模网格，并让 GLB URL 换查询串以绕过 WebView 长缓存 */
export const RIG_MESH_STYLE = "bodykun-v6-20260907";

/** 女体用 BodyChan，其余体型用 BodyKun（儿童/胖瘦靠 heightScale） */
export function bodyFigureUrl(variant: HumanVariant = "male_std"): string {
  const file = variant === "female_std" ? "bodychan.glb" : "bodykun.glb";
  return `/models/${file}?v=${RIG_MESH_STYLE}`;
}

/** 体型预设 ID */
export type HumanVariant =
  | "male_std"
  | "female_std"
  | "male_thin"
  | "male_heavy"
  | "child";

/** 发型预设 ID（挂在头骨后方/头顶的装饰 Mesh，不参与关节） */
export type HairStyle = "none" | "short" | "long" | "round";

/** 体型几何参数（单位：米，比例参考真实人体） */
export type HumanPreset = {
  id: HumanVariant;
  label: string;
  /** root 整体均匀缩放（反映身高差异：男标=1.0，儿童≈0.74） */
  heightScale: number;
  /** 站立脚底≈0 时骨盆组根 y */
  hipsY: number;
  /** 肩宽垫块总宽 */
  shoulderPadW: number;
  /** 胸节主体（含 shoulderPad 之上）y 高度起点偏移 */
  chestY: number;
  /** 胸宽（front chest 盒宽度） */
  chestW: number;
  /** 骨盆宽 */
  pelvisW: number;
  /** 腹节盒宽 */
  abdomenW: number;
  /** 头骨尺寸 */
  skullW: number;
  /** 上臂截面（胶囊半径×2） */
  armR: number;
  /** 前臂截面 */
  foreR: number;
  /** 大腿截面 */
  thighR: number;
  /** 小腿截面 */
  shinR: number;
  /** 肩位相对 spine 根的 z（正=向前） */
  shoulderOffsetZ: number;
  /** 肩位相对 spine 根的 x（正=右） */
  shoulderOffsetX: number;
  /** 肩位 y 高度（相对于 spine 根的局部 y） */
  shoulderOffsetY: number;
  /** 肩宽垫块中心 y（相对于 spine 根） */
  shoulderPadY: number;
  /** 骨盆根左右髋关节局部 x */
  hipOffsetX: number;
};

/** 五种体型预设（身高从儿童 1.25m 到男标准 1.72m） */
export const HUMAN_PRESETS: Record<HumanVariant, HumanPreset> = {
  male_std: {
    id: "male_std",
    label: "男·标准",
    heightScale: 1.0,
    hipsY: 0.92,
    shoulderPadW: 0.46,
    chestY: 0.38,
    chestW: 0.38,
    pelvisW: 0.30,
    abdomenW: 0.26,
    skullW: 0.22,
    armR: 0.055,
    foreR: 0.05,
    thighR: 0.065,
    shinR: 0.06,
    shoulderOffsetZ: 0,
    shoulderOffsetX: 0.26,
    shoulderOffsetY: 0,
    shoulderPadY: 0.1,
    hipOffsetX: 0.1,
  },
  female_std: {
    id: "female_std",
    label: "女·标准",
    heightScale: 0.94,
    hipsY: 0.86,
    shoulderPadW: 0.40,
    chestY: 0.36,
    chestW: 0.34,
    pelvisW: 0.32,
    abdomenW: 0.24,
    skullW: 0.21,
    armR: 0.05,
    foreR: 0.045,
    thighR: 0.06,
    shinR: 0.055,
    shoulderOffsetZ: 0.01,
    shoulderOffsetX: 0.22,
    shoulderOffsetY: -0.02,
    shoulderPadY: 0.08,
    hipOffsetX: 0.11,
  },
  male_thin: {
    id: "male_thin",
    label: "男·瘦",
    heightScale: 1.03,
    hipsY: 0.94,
    shoulderPadW: 0.40,
    chestY: 0.38,
    chestW: 0.34,
    pelvisW: 0.28,
    abdomenW: 0.22,
    skullW: 0.21,
    armR: 0.045,
    foreR: 0.04,
    thighR: 0.055,
    shinR: 0.05,
    shoulderOffsetZ: 0,
    shoulderOffsetX: 0.24,
    shoulderOffsetY: 0.01,
    shoulderPadY: 0.1,
    hipOffsetX: 0.09,
  },
  male_heavy: {
    id: "male_heavy",
    label: "男·胖",
    heightScale: 0.96,
    hipsY: 0.90,
    shoulderPadW: 0.54,
    chestY: 0.36,
    chestW: 0.48,
    pelvisW: 0.38,
    abdomenW: 0.38,
    skullW: 0.23,
    armR: 0.07,
    foreR: 0.065,
    thighR: 0.085,
    shinR: 0.08,
    shoulderOffsetZ: 0.015,
    shoulderOffsetX: 0.30,
    shoulderOffsetY: -0.01,
    shoulderPadY: 0.09,
    hipOffsetX: 0.12,
  },
  child: {
    id: "child",
    label: "儿童",
    heightScale: 0.74,
    hipsY: 0.68,
    shoulderPadW: 0.32,
    chestY: 0.28,
    chestW: 0.26,
    pelvisW: 0.22,
    abdomenW: 0.20,
    skullW: 0.18,
    armR: 0.045,
    foreR: 0.04,
    thighR: 0.05,
    shinR: 0.045,
    shoulderOffsetZ: 0,
    shoulderOffsetX: 0.17,
    shoulderOffsetY: 0.02,
    shoulderPadY: 0.08,
    hipOffsetX: 0.075,
  },
};

const JOINT = "#111111";

/* ─────────────────────────────────────────────────────────────────────
 * ★ 2026-10-05 姿势数据已抽到 `stage3dPoseLibrary.ts`
 *   （单文件规模棘轮 + 职责分离）。这里 import 内部使用 + re-export 对外，
 *   **既有导入方零改动**。
 * ───────────────────────────────────────────────────────────────────── */
import type { JointPose, PosePresetId } from "./stage3dPoseLibrary";
import { defaultPose, JOINT_LABELS, POSE_PRESETS } from "./stage3dPoseLibrary";

export type { JointPose, PosePresetId };
export { JOINT_LABELS, POSE_PRESETS, defaultPose };

/* ─────────────────────────────────────────────────────────────────────
 * 基础动作轨迹库 / Motion Presets
 *
 * 与 POSE_PRESETS（静态姿势）不同，MotionPreset 是**循环动画轨迹**：
 * 每个预设由一组关键帧 + 缓动曲线描述完整的运动周期。
 * 用户只需选 "走姿" / "呼吸" / "摆臂" 等，系统自动按曲线插值。
 *
 * 所有轨迹 pose 值均为**相对 defaultPose 的增量**（偏移量）。
 * 这样与现有姿势系统完全兼容：final = resolveClampPose(resolveChainPose(default + motionOffset))
 * ───────────────────────────────────────────────────────────────────── */

export type MotionPreset = {
  /** 唯一 ID */
  id: string;
  /** 中文标签 */
  label: string;
  /** 完整循环周期（ms） */
  duration: number;
  /** 关键帧数组，必须有 t=0 和 t=duration 形成闭合循环 */
  keyframes: { t: number; pose: Partial<JointPose> }[];
  /** 此轨迹使用的缓动函数（默认 easeInOutSine，柔和连续） */
  easeFn?: (t: number) => number;
  /** 播放速度倍率（默认 1.0）— 0.5 = 慢动作，2.0 = 快动作 */
  speed?: number;
  /** root 位置偏移关键帧（可选）：[x, y, z] 米偏移量，随关键帧循环采样 */
  rootOffset?: { t: number; pos: [number, number, number] }[];
};

/** sampleMotion 返回值同时带 root 位置偏移（有 rootOffset 时生效） */
export type MotionSample = { pose: JointPose; rootOffset: [number, number, number] };

/** 内部工具：按 motion 的 speed 倍率调整时间 */
function motionCycleTime(motion: MotionPreset, timeMs: number): number {
  const speed = motion.speed ?? 1.0;
  const adjustedMs = timeMs * speed;
  return ((adjustedMs % motion.duration) + motion.duration) % motion.duration;
}

/** 内部工具：从 rootOffset 关键帧序列中插值 */
function sampleRootOffset(
  motion: MotionPreset,
  cycleT: number,
): [number, number, number] {
  if (!motion.rootOffset || motion.rootOffset.length === 0) return [0, 0, 0];
  const kfs = motion.rootOffset;
  if (cycleT <= kfs[0].t) return [...kfs[0].pos] as [number, number, number];
  for (let i = 0; i < kfs.length - 1; i++) {
    const a = kfs[i], b = kfs[i + 1];
    if (cycleT >= a.t && cycleT <= b.t) {
      const segT = (cycleT - a.t) / (b.t - a.t);
      return [
        a.pos[0] + (b.pos[0] - a.pos[0]) * segT,
        a.pos[1] + (b.pos[1] - a.pos[1]) * segT,
        a.pos[2] + (b.pos[2] - a.pos[2]) * segT,
      ];
    }
  }
  return [...kfs[kfs.length - 1].pos] as [number, number, number];
}

/**
 * Motion → JointPose 采样器：
 * 给定 MotionPreset + 当前时间（ms），返回该时刻的完整姿态增量。
 * 内部自动做周期循环（用模运算）和 ease 曲线插值。
 */
export function sampleMotion(
  motion: MotionPreset,
  timeMs: number,
): JointPose {
  const cycleT = motionCycleTime(motion, timeMs);
  const easedLerp = (a: JointPose, b: JointPose, t: number): JointPose =>
    lerpPose(a, b, t, motion.easeFn ?? easeInOutSine);

  const kfs = motion.keyframes;
  if (cycleT <= kfs[0].t) {
    return mergePose(defaultPose(), kfs[0].pose);
  }
  for (let i = 0; i < kfs.length - 1; i++) {
    const a = kfs[i];
    const b = kfs[i + 1];
    if (cycleT >= a.t && cycleT <= b.t) {
      const segT = (cycleT - a.t) / (b.t - a.t);
      const fullA = mergePose(defaultPose(), a.pose);
      const fullB = mergePose(defaultPose(), b.pose);
      return easedLerp(fullA, fullB, segT);
    }
  }
  return mergePose(defaultPose(), kfs[kfs.length - 1].pose);
}

/** Motion → MotionSample 采样器（同时返回 rootOffset） */
export function sampleMotionFull(
  motion: MotionPreset,
  timeMs: number,
): MotionSample {
  const cycleT = motionCycleTime(motion, timeMs);
  const pose = sampleMotion(motion, timeMs);
  const rootOffset = sampleRootOffset(motion, cycleT);
  return { pose, rootOffset };
}

/* ──────────── 4 组基础动作轨迹 ──────────── */

/** 走姿循环：髋前后摆 + 膝联动 + 肩反相摆臂 + 呼吸微幅 + 重心颠动 */
export const MOTION_WALK_GAIT: MotionPreset = {
  id: "walk_gait",
  label: "走姿循环",
  duration: 1200,
  easeFn: easeInOutSine,
  keyframes: [
    { t: 0,    pose: { lHipX: 20, lKneeX: 18, rHipX: -20, rKneeX: 4,  lShoulderX: -12, rShoulderX: 12, spineY: 4, abdomenX: -2 } },
    { t: 300,  pose: { lHipX: -8, lKneeX: 6,  rHipX: 10,  rKneeX: 22, lShoulderX: 8,   rShoulderX: -8,  spineY: -3, abdomenX: 2 } },
    { t: 600,  pose: { lHipX: -20,lKneeX: 4,  rHipX: 20,  rKneeX: 18, lShoulderX: 12,  rShoulderX: -12, spineY: -4, abdomenX: 3 } },
    { t: 900,  pose: { lHipX: 10, lKneeX: 22, rHipX: -8,  rKneeX: 6,  lShoulderX: -8,  rShoulderX: 8,   spineY: 3,  abdomenX: -3 } },
    { t: 1200, pose: { lHipX: 20, lKneeX: 18, rHipX: -20, rKneeX: 4,  lShoulderX: -12, rShoulderX: 12, spineY: 4, abdomenX: -2 } },
  ],
  /** 走路时的原地重心颠动（Y 轴 ±3cm） */
  rootOffset: [
    { t: 0,    pos: [0, 0, 0] },
    { t: 300,  pos: [0, -0.025, 0] },
    { t: 600,  pos: [0, 0.015, 0] },
    { t: 900,  pos: [0, -0.025, 0] },
    { t: 1200, pos: [0, 0, 0] },
  ],
};

/** 呼吸微循环：腹起伏 + 胸微幅跟随 + 头部微动 */
export const MOTION_BREATHING: MotionPreset = {
  id: "breathing",
  label: "呼吸微循",
  duration: 4000, // 4s ≈ 0.25 Hz 安静呼吸
  easeFn: easeInOutSine,
  keyframes: [
    {
      t: 0,
      pose: { abdomenX: -4, spineX: -2, headX: -1 },
    },
    {
      t: 1000,
      pose: { abdomenX: 2, spineX: 1, headX: 0 },
    },
    {
      t: 2000,
      pose: { abdomenX: 5, spineX: 3, headX: 1 },
    },
    {
      t: 3000,
      pose: { abdomenX: 1, spineX: 0, headX: 0 },
    },
    {
      t: 4000,
      pose: { abdomenX: -4, spineX: -2, headX: -1 },
    },
  ],
};

/** 手臂自然摆动：肩 X 正弦 + 肘微弯 + 髋反相补偿 */
export const MOTION_ARM_SWING: MotionPreset = {
  id: "arm_swing",
  label: "手臂摆动",
  duration: 2000, // 2s ≈ 0.5 Hz
  easeFn: easeInOutSine,
  keyframes: [
    {
      t: 0,
      pose: {
        lShoulderX: 12, lElbowX: 14,
        rShoulderX: -12, rElbowX: 14,
        lHipX: -4, rHipX: 4,
        spineY: -3,
      },
    },
    {
      t: 500,
      pose: {
        lShoulderX: -8, lElbowX: 18,
        rShoulderX: 8, rElbowX: 12,
        lHipX: 3, rHipX: -3,
        spineY: 2,
      },
    },
    {
      t: 1000,
      pose: {
        lShoulderX: -12, lElbowX: 20,
        rShoulderX: 12, rElbowX: 10,
        lHipX: 4, rHipX: -4,
        spineY: 3,
      },
    },
    {
      t: 1500,
      pose: {
        lShoulderX: 8, lElbowX: 12,
        rShoulderX: -8, rElbowX: 18,
        lHipX: -3, rHipX: 3,
        spineY: -2,
      },
    },
    {
      t: 2000,
      pose: {
        lShoulderX: 12, lElbowX: 14,
        rShoulderX: -12, rElbowX: 14,
        lHipX: -4, rHipX: 4,
        spineY: -3,
      },
    },
  ],
};

/** 头部环顾：headY 正弦 + headX 微幅点头 + 胸微跟随 */
export const MOTION_HEAD_LOOK: MotionPreset = {
  id: "head_look",
  label: "头部环顾",
  duration: 5000,
  easeFn: easeInOutSine,
  keyframes: [
    {
      t: 0,
      pose: { headY: 0, headX: 0, spineY: 0 },
    },
    {
      t: 1250,
      pose: { headY: 28, headX: 4, spineY: 8 },
    },
    {
      t: 2500,
      pose: { headY: 0, headX: -2, spineY: 0 },
    },
    {
      t: 3750,
      pose: { headY: -28, headX: 2, spineY: -8 },
    },
    {
      t: 5000,
      pose: { headY: 0, headX: 0, spineY: 0 },
    },
  ],
};

/** 站立微晃（idle sway）：spineY 正弦 + spineX 微幅 + 重心转移 */
export const MOTION_IDLE_SWAY: MotionPreset = {
  id: "idle_sway",
  label: "站立微晃",
  duration: 6000,
  easeFn: easeInOutSine,
  keyframes: [
    {
      t: 0,
      pose: { spineY: -4, spineX: 1, lHipX: -2, rHipX: 2 },
    },
    {
      t: 1500,
      pose: { spineY: 2, spineX: -1, lHipX: 1, rHipX: -1 },
    },
    {
      t: 3000,
      pose: { spineY: 4, spineX: 2, lHipX: 2, rHipX: -2 },
    },
    {
      t: 4500,
      pose: { spineY: -2, spineX: 0, lHipX: -1, rHipX: 1 },
    },
    {
      t: 6000,
      pose: { spineY: -4, spineX: 1, lHipX: -2, rHipX: 2 },
    },
  ],
};

/** 挥手打招呼：右臂高举左右摆 + 头微跟随 + 躯干微前倾（单次循环 ≈ 2.4s） */
export const MOTION_WAVE_HELLO: MotionPreset = {
  id: "wave_hello",
  label: "挥手打招呼",
  duration: 2400,
  easeFn: easeOutBack,
  keyframes: [
    { t: 0,    pose: { rShoulderX: -60, rShoulderZ: -10, rElbowX: 40, headY: -10, spineX: 3 } },
    { t: 600,  pose: { rShoulderX: -60, rShoulderZ: -10, rElbowX: 40, headY: 20,  spineX: 3 } },
    { t: 1200, pose: { rShoulderX: -60, rShoulderZ: -10, rElbowX: 40, headY: -10, spineX: 3 } },
    { t: 1800, pose: { rShoulderX: -60, rShoulderZ: -10, rElbowX: 40, headY: 20,  spineX: 3 } },
    { t: 2400, pose: { rShoulderX: -60, rShoulderZ: -10, rElbowX: 40, headY: -10, spineX: 3 } },
  ],
};

/** 下蹲起身：髋后坐 → 膝屈 → 躯干前倾配平 → 蹬伸起身（符合深蹲力学，不后仰） */
export const MOTION_SQUAT_RISE: MotionPreset = {
  id: "squat_rise",
  label: "下蹲起身",
  duration: 2400,
  easeFn: easeInOutCubic,
  keyframes: [
    // 站立微屈（预备）
    {
      t: 0,
      pose: {
        lHipX: 4,
        rHipX: 4,
        lKneeX: 6,
        rKneeX: 6,
        lAnkleX: 2,
        rAnkleX: 2,
        abdomenX: 2,
        spineX: 2,
        headX: 0,
        lShoulderX: -8,
        rShoulderX: -8,
        lElbowX: 12,
        rElbowX: 12,
      },
    },
    // 下坐：髋膝同步，躯干略前倾，手臂前伸配平
    {
      t: 500,
      pose: {
        lHipX: 38,
        rHipX: 38,
        lKneeX: 62,
        rKneeX: 62,
        lAnkleX: 14,
        rAnkleX: 14,
        abdomenX: 14,
        spineX: 10,
        headX: 4,
        lShoulderX: -28,
        rShoulderX: -28,
        lShoulderZ: 12,
        rShoulderZ: -12,
        lElbowX: 38,
        rElbowX: 38,
      },
    },
    // 深蹲底部：大腿近水平，胸仍前倾（禁止后仰），重心压脚跟
    {
      t: 1000,
      pose: {
        lHipX: 78,
        rHipX: 78,
        lKneeX: 118,
        rKneeX: 118,
        lAnkleX: 26,
        rAnkleX: 26,
        abdomenX: 20,
        spineX: 14,
        headX: 6,
        lShoulderX: -36,
        rShoulderX: -36,
        lShoulderZ: 16,
        rShoulderZ: -16,
        lElbowX: 48,
        rElbowX: 48,
      },
    },
    // 稍作停留再起
    {
      t: 1300,
      pose: {
        lHipX: 78,
        rHipX: 78,
        lKneeX: 118,
        rKneeX: 118,
        lAnkleX: 26,
        rAnkleX: 26,
        abdomenX: 20,
        spineX: 14,
        headX: 6,
        lShoulderX: -36,
        rShoulderX: -36,
        lShoulderZ: 16,
        rShoulderZ: -16,
        lElbowX: 48,
        rElbowX: 48,
      },
    },
    // 蹬伸过半：髋先伸、膝跟进
    {
      t: 1800,
      pose: {
        lHipX: 32,
        rHipX: 32,
        lKneeX: 52,
        rKneeX: 52,
        lAnkleX: 12,
        rAnkleX: 12,
        abdomenX: 10,
        spineX: 8,
        headX: 2,
        lShoulderX: -22,
        rShoulderX: -22,
        lShoulderZ: 10,
        rShoulderZ: -10,
        lElbowX: 30,
        rElbowX: 30,
      },
    },
    // 回站
    {
      t: 2400,
      pose: {
        lHipX: 4,
        rHipX: 4,
        lKneeX: 6,
        rKneeX: 6,
        lAnkleX: 2,
        rAnkleX: 2,
        abdomenX: 2,
        spineX: 2,
        headX: 0,
        lShoulderX: -8,
        rShoulderX: -8,
        lElbowX: 12,
        rElbowX: 12,
      },
    },
  ],
  rootOffset: [
    { t: 0, pos: [0, 0, 0] },
    { t: 500, pos: [0, -0.16, 0.04] },
    { t: 1000, pos: [0, -0.42, 0.06] },
    { t: 1300, pos: [0, -0.42, 0.06] },
    { t: 1800, pos: [0, -0.14, 0.03] },
    { t: 2400, pos: [0, 0, 0] },
  ],
};

/** 深侧倚：重心压到一侧腿，躯干侧倾靠「墙」，对侧腿放松，慢呼吸微动（不再左右来回晃） */
export const MOTION_LEAN_SIDE: MotionPreset = {
  id: "lean_side",
  label: "深侧倚靠",
  duration: 5600,
  easeFn: easeInOutSine,
  keyframes: [
    // 直立
    {
      t: 0,
      pose: {
        abdomenZ: 0,
        spineZ: 0,
        spineY: 0,
        spineX: 0,
        lHipX: 0,
        rHipX: 0,
        lHipZ: 0,
        rHipZ: 0,
        lKneeX: 4,
        rKneeX: 4,
        lShoulderZ: 0,
        rShoulderZ: 0,
        lShoulderX: 0,
        rShoulderX: 0,
        lElbowX: 8,
        rElbowX: 8,
        headY: 0,
        headX: 0,
      },
    },
    // 开始把重心挪到右腿，躯干向右靠
    {
      t: 900,
      pose: {
        abdomenZ: 10,
        spineZ: 12,
        spineY: -4,
        spineX: -6,
        rHipX: 6,
        rHipZ: -10,
        lHipX: 18,
        lHipZ: 8,
        rKneeX: 8,
        lKneeX: 28,
        rShoulderX: -18,
        rShoulderZ: -28,
        rElbowX: 52,
        lShoulderX: 6,
        lShoulderZ: 8,
        lElbowX: 22,
        headY: 8,
        headX: 2,
      },
    },
    // 深倚到位：右侧承重 + 右臂撑墙，左腿虚点地
    {
      t: 1800,
      pose: {
        abdomenZ: 16,
        spineZ: 18,
        spineY: -6,
        spineX: -10,
        rHipX: 8,
        rHipZ: -14,
        lHipX: 28,
        lHipZ: 12,
        rKneeX: 10,
        lKneeX: 42,
        rAnkleX: 4,
        lAnkleX: 12,
        rShoulderX: -28,
        rShoulderZ: -36,
        rElbowX: 72,
        lShoulderX: 10,
        lShoulderZ: 12,
        lElbowX: 30,
        headY: 10,
        headX: 4,
      },
    },
    // 维持深倚，轻微呼吸起伏
    {
      t: 3200,
      pose: {
        abdomenZ: 15,
        spineZ: 17,
        spineY: -5,
        spineX: -9,
        rHipX: 7,
        rHipZ: -13,
        lHipX: 26,
        lHipZ: 11,
        rKneeX: 9,
        lKneeX: 40,
        rAnkleX: 4,
        lAnkleX: 11,
        rShoulderX: -26,
        rShoulderZ: -34,
        rElbowX: 68,
        lShoulderX: 8,
        lShoulderZ: 10,
        lElbowX: 28,
        headY: 9,
        headX: 3,
      },
    },
    // 慢慢回正
    {
      t: 4600,
      pose: {
        abdomenZ: 6,
        spineZ: 7,
        spineY: -2,
        spineX: -4,
        rHipX: 4,
        rHipZ: -5,
        lHipX: 10,
        lHipZ: 4,
        rKneeX: 6,
        lKneeX: 14,
        rShoulderX: -10,
        rShoulderZ: -14,
        rElbowX: 28,
        lShoulderX: 4,
        lShoulderZ: 4,
        lElbowX: 14,
        headY: 3,
        headX: 1,
      },
    },
    {
      t: 5600,
      pose: {
        abdomenZ: 0,
        spineZ: 0,
        spineY: 0,
        spineX: 0,
        lHipX: 0,
        rHipX: 0,
        lHipZ: 0,
        rHipZ: 0,
        lKneeX: 4,
        rKneeX: 4,
        lShoulderZ: 0,
        rShoulderZ: 0,
        lShoulderX: 0,
        rShoulderX: 0,
        lElbowX: 8,
        rElbowX: 8,
        headY: 0,
        headX: 0,
      },
    },
  ],
  rootOffset: [
    { t: 0, pos: [0, 0, 0] },
    { t: 900, pos: [0.06, -0.02, 0] },
    { t: 1800, pos: [0.12, -0.05, -0.02] },
    { t: 3200, pos: [0.11, -0.04, -0.02] },
    { t: 4600, pos: [0.04, -0.01, 0] },
    { t: 5600, pos: [0, 0, 0] },
  ],
};

export const MOTION_PRESETS: MotionPreset[] = [
  MOTION_WALK_GAIT,
  MOTION_BREATHING,
  MOTION_ARM_SWING,
  MOTION_HEAD_LOOK,
  MOTION_IDLE_SWAY,
  MOTION_WAVE_HELLO,
  MOTION_SQUAT_RISE,
  MOTION_LEAN_SIDE,
];

/** 组合多个 MotionPreset：时间戳取第一个的绝对时间，循环独立，rootOffset 叠加 */
export function sampleCompositeMotion(
  motions: MotionPreset[],
  timeMs: number,
): MotionSample {
  if (motions.length === 0) return { pose: defaultPose(), rootOffset: [0, 0, 0] };
  let pose: Partial<JointPose> = {};
  let rootOffset: [number, number, number] = [0, 0, 0];
  for (const m of motions) {
    const cycleT = motionCycleTime(m, timeMs);
    const sampled = sampleMotion(m, timeMs);
    for (const k of Object.keys(sampled) as (keyof JointPose)[]) {
      // DEFAULT_POSE 全为 0，sampled 已是相对偏移，直接累加即可，省去每 motion 一次 defaultPose() 分配
      pose[k] = (pose[k] ?? 0) + sampled[k];
    }
    const ro = sampleRootOffset(m, cycleT);
    rootOffset[0] += ro[0];
    rootOffset[1] += ro[1];
    rootOffset[2] += ro[2];
  }
  const full = mergePose(defaultPose(), pose);
  return { pose: resolveClampPose(resolveChainPose(full)), rootOffset };
}

function deg(n: number) {
  return (n * Math.PI) / 180;
}

function bodyMat(color: string, tint?: string, flat = true) {
  const mat = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.55,
    metalness: 0.08,
    flatShading: flat,
  });
  return { mat, tint };
}

function jointMat() {
  return new THREE.MeshStandardMaterial({
    color: JOINT,
    roughness: 0.45,
    metalness: 0.25,
    flatShading: true,
  });
}

/** 胶囊体素（用 CapsuleGeometry 代替 BoxGeometry 做四肢/躯干主体，更圆滑） */
function capsulePart(
  radius: number,
  length: number,
  color: string,
  tint?: string,
  flat = false,
): THREE.Mesh {
  const { mat } = bodyMat(color, tint, flat);
  const geo = new THREE.CapsuleGeometry(radius, length, 6, 14);
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  if (tint) m.userData.tint = tint;
  return m;
}

/** 渐变胶囊：上粗下细（大腿→小腿）或上细下粗，cap 自动收头
 *  用 Group 装 3 个原生 geometry mesh，避免手动 merge 坑 */
function taperedCapsulePart(
  topR: number,
  botR: number,
  length: number,
  color: string,
  tint?: string,
): THREE.Group {
  const { mat } = bodyMat(color, tint, false);
  const capH = Math.min(topR, botR) * 1.0;
  const cyH = Math.max(0.001, length - capH * 2);
  const g = new THREE.Group();
  const cy = new THREE.Mesh(
    new THREE.CylinderGeometry(topR, botR, cyH, 16, 1, false),
    mat,
  );
  cy.position.y = capH + cyH / 2;
  cy.castShadow = true;
  cy.receiveShadow = true;
  cy.userData.tint = tint;
  g.add(cy);
  const topCap = new THREE.Mesh(
    new THREE.SphereGeometry(topR, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2),
    mat,
  );
  topCap.position.y = capH + cyH;
  topCap.castShadow = true;
  topCap.receiveShadow = true;
  topCap.userData.tint = tint;
  g.add(topCap);
  const botCap = new THREE.Mesh(
    new THREE.SphereGeometry(botR, 16, 10, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2),
    mat,
  );
  botCap.castShadow = true;
  botCap.receiveShadow = true;
  botCap.userData.tint = tint;
  g.add(botCap);
  return g;
}

/** 渐变圆柱体（无球帽），适合脖子 / 腰围过渡 */
function taperedCylinderPart(
  topR: number,
  botR: number,
  height: number,
  color: string,
  tint?: string,
): THREE.Mesh {
  const { mat } = bodyMat(color, tint, false);
  const geo = new THREE.CylinderGeometry(topR, botR, height, 18, 1, false);
  geo.translate(0, height / 2, 0);
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  if (tint) m.userData.tint = tint;
  return m;
}

/** 椭球头骨：脸稍扁、后脑稍凸，比 Box 头自然得多 */
function ellipsoidHeadPart(
  w: number,
  color: string,
): THREE.Mesh {
  const { mat } = bodyMat(color, "clothes", false);
  const geo = new THREE.SphereGeometry(w * 0.52, 28, 20);
  geo.scale(1.0, 1.08, 0.93);
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  m.userData.tint = "clothes";
  return m;
}

/** 躯干：多截面 BufferGeometry 渐变，骨盆→腰→胸→肩窝→颈底 */
function torsoTaperPart(
  P: HumanPreset,
  color: string,
): THREE.Mesh {
  const { mat } = bodyMat(color, "clothes", false);
  const sections: { y: number; w: number; d: number }[] = [
    { y: 0.0, w: P.pelvisW * 0.90, d: P.pelvisW * 0.55 },
    { y: 0.06, w: P.pelvisW, d: P.pelvisW * 0.65 },
    { y: 0.16, w: P.abdomenW * 1.02, d: P.abdomenW * 0.72 },
    { y: 0.24, w: P.abdomenW, d: P.abdomenW * 0.74 },
    { y: 0.34, w: P.chestW * 0.92, d: P.chestW * 0.80 },
    { y: 0.44, w: P.chestW, d: P.chestW * 0.82 },
    { y: 0.54, w: P.chestW * 0.94, d: P.chestW * 0.76 },
    { y: 0.62, w: P.shoulderPadW * 0.55, d: P.chestW * 0.50 },
    { y: 0.70, w: P.chestW * 0.28, d: P.chestW * 0.22 },
  ];
  const geo = buildTaperedBodyGeo(sections, 24);
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  m.userData.tint = "clothes";
  return m;
}

/** 腹部：单截面渐变圆柱，腰最细处 */
function abdomenTaperPart(
  topW: number,
  botW: number,
  height: number,
  color: string,
): THREE.Mesh {
  const { mat } = bodyMat(color, "clothes", false);
  const geo = buildTaperedBodyGeo(
    [
      { y: 0, w: botW, d: botW * 0.70 },
      { y: height * 0.35, w: Math.min(topW, botW) * 0.96, d: Math.min(topW, botW) * 0.72 },
      { y: height, w: topW, d: topW * 0.70 },
    ],
    20,
  );
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  m.userData.tint = "clothes";
  return m;
}

/** 骨盆：扁平渐变胶囊（上宽下窄） */
function pelvisTaperPart(
  w: number,
  d: number,
  height: number,
  color: string,
): THREE.Mesh {
  const { mat } = bodyMat(color, "clothes", false);
  const geo = buildTaperedBodyGeo(
    [
      { y: 0, w: w * 0.88, d: d * 0.9 },
      { y: height * 0.5, w: w, d: d },
      { y: height, w: w * 0.72, d: d * 0.78 },
    ],
    22,
  );
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  m.userData.tint = "clothes";
  return m;
}

/** 合并多个几何体（安全版：自动对齐顶点索引偏移，用 Uint16 兼容 WebGL1） */
function mergeGeometriesSafe(geoms: THREE.BufferGeometry[]): THREE.BufferGeometry {
  let totalPos = 0, totalIdx = 0;
  for (const g of geoms) {
    totalPos += g.attributes.position.count;
    totalIdx += g.index ? g.index.count : 0;
  }
  const positions = new Float32Array(totalPos * 3);
  const normals = new Float32Array(totalPos * 3);
  const TypedIdx = totalIdx > 65535 ? Uint32Array : Uint16Array;
  const indices = new TypedIdx(totalIdx);
  let posOff = 0, idxOff = 0, vertOff = 0;
  for (const g of geoms) {
    g.computeVertexNormals();
    const pos = g.attributes.position.array as Float32Array;
    const nrm = g.attributes.normal.array as Float32Array;
    positions.set(pos, posOff);
    normals.set(nrm, posOff);
    if (g.index) {
      const idx = g.index.array;
      for (let i = 0; i < idx.length; i++) indices[idxOff + i] = (idx as Uint32Array | Uint16Array)[i] + vertOff;
      idxOff += idx.length;
    }
    vertOff += g.attributes.position.count;
    posOff += pos.length;
  }
  const merged = new THREE.BufferGeometry();
  merged.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  merged.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  merged.setIndex(indices);
  merged.computeBoundingSphere();
  merged.computeBoundingBox();
  return merged;
}

/** 多椭圆截面 → 平滑 BufferGeometry（躯干/骨盆通用，环形闭合用 %） */
function buildTaperedBodyGeo(
  sections: { y: number; w: number; d: number }[],
  radialSeg = 22,
): THREE.BufferGeometry {
  const n = sections.length;
  const vertices: number[] = [];
  const indexList: number[] = [];
  for (let i = 0; i < n; i++) {
    const { y, w, d } = sections[i];
    for (let j = 0; j < radialSeg; j++) {
      const t = (j / radialSeg) * Math.PI * 2;
      vertices.push(Math.cos(t) * w * 0.5, y, Math.sin(t) * d * 0.5);
    }
  }
  for (let i = 0; i < n - 1; i++) {
    for (let j = 0; j < radialSeg; j++) {
      const nextJ = (j + 1) % radialSeg;
      const a = i * radialSeg + j;
      const b = i * radialSeg + nextJ;
      const c = (i + 1) * radialSeg + nextJ;
      const d = (i + 1) * radialSeg + j;
      indexList.push(a, d, b);
      indexList.push(b, d, c);
    }
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  geom.setIndex(indexList);
  geom.computeVertexNormals();
  geom.computeBoundingSphere();
  geom.computeBoundingBox();
  return geom;
}

function boxPart(
  w: number,
  h: number,
  d: number,
  color: string,
  tint?: string,
  bevel = 0.02,
  flat = true,
): THREE.Mesh {
  const { mat } = bodyMat(color, tint, flat);
  const geo = new THREE.BoxGeometry(w, h, d, 1, 1, 1);
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  if (tint) m.userData.tint = tint;
  m.userData.bevel = bevel;
  return m;
}

function jointBall(radius: number): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.SphereGeometry(radius, 12, 10), jointMat());
  m.castShadow = true;
  return m;
}

function jointHinge(radius: number, axis: "x" | "z" = "x"): THREE.Mesh {
  const m = new THREE.Mesh(
    new THREE.CylinderGeometry(radius, radius, radius * 1.6, 12),
    jointMat(),
  );
  if (axis === "x") m.rotation.z = Math.PI / 2;
  else m.rotation.x = Math.PI / 2;
  m.castShadow = true;
  return m;
}

type BoneMap = {
  abdomen: THREE.Object3D;
  spine: THREE.Object3D;
  head: THREE.Object3D;
  lShoulder: THREE.Object3D;
  lElbow: THREE.Object3D;
  lWrist: THREE.Object3D;
  rShoulder: THREE.Object3D;
  rElbow: THREE.Object3D;
  rWrist: THREE.Object3D;
  lHip: THREE.Object3D;
  lKnee: THREE.Object3D;
  lAnkle: THREE.Object3D;
  rHip: THREE.Object3D;
  rKnee: THREE.Object3D;
  rAnkle: THREE.Object3D;
};

/** 发型 Mesh（挂在 head 组上，不参与关节旋转） */
function makeHair(style: HairStyle, skullW: number, hairColor = "#1e293b"): THREE.Group | null {
  if (style === "none") return null;
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({
    color: hairColor,
    roughness: 0.7,
    metalness: 0.05,
    flatShading: false,
  });
  const half = skullW / 2;
  if (style === "short") {
    // 短头发：头顶 + 两侧覆盖（SphereGeometry + BoxGeometry 组合）
    const cap = new THREE.Mesh(new THREE.SphereGeometry(half * 1.05, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.65), mat);
    cap.position.set(0, half * 0.2, 0);
    cap.userData.hair = true;
    g.add(cap);
    // 侧方修剪（削薄感）
    const sideL = new THREE.Mesh(new THREE.BoxGeometry(half * 0.2, half * 0.9, half * 0.9), mat);
    sideL.position.set(-half * 0.85, half * 0.05, 0);
    g.add(sideL);
    const sideR = sideL.clone();
    sideR.position.x = half * 0.85;
    g.add(sideR);
  } else if (style === "long") {
    // 长头发：头顶帽 + 后披长发（BoxGeometry 挂到背后）
    const cap = new THREE.Mesh(new THREE.SphereGeometry(half * 1.05, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.6), mat);
    cap.position.set(0, half * 0.25, 0);
    g.add(cap);
    // 后披长发（从头顶到骨盆的长发块）
    const back = new THREE.Mesh(new THREE.BoxGeometry(half * 1.7, half * 2.0, half * 0.7), mat);
    back.position.set(0, -half * 0.5, -half * 0.5);
    g.add(back);
    // 刘海（前额）
    const bang = new THREE.Mesh(new THREE.BoxGeometry(half * 1.5, half * 0.3, half * 0.3), mat);
    bang.position.set(0, half * 0.45, half * 0.85);
    g.add(bang);
  } else if (style === "round") {
    // 儿童圆头：整体头包 + 头顶小揪
    const wrap = new THREE.Mesh(new THREE.SphereGeometry(half * 1.1, 14, 10), mat);
    wrap.position.set(0, half * 0.1, 0);
    g.add(wrap);
    const tuft = new THREE.Mesh(new THREE.CylinderGeometry(half * 0.15, half * 0.12, half * 0.5, 8), mat);
    tuft.position.set(0, half * 0.95, 0);
    g.add(tuft);
  }
  return g;
}

function makeHand(color: string): THREE.Group {
  const g = new THREE.Group();
  const { mat } = bodyMat(color, "clothes", false);
  const palmGeo = new THREE.SphereGeometry(0.05, 14, 10);
  palmGeo.scale(1.0, 0.85, 1.15);
  const palm = new THREE.Mesh(palmGeo, mat);
  palm.position.y = -0.04;
  palm.castShadow = true;
  palm.userData.tint = "clothes";
  g.add(palm);
  const gripGeo = new THREE.SphereGeometry(0.042, 14, 10);
  gripGeo.scale(1.1, 0.9, 1.2);
  const grip = new THREE.Mesh(gripGeo, mat);
  grip.position.set(0, -0.11, 0.02);
  grip.castShadow = true;
  grip.userData.tint = "clothes";
  g.add(grip);
  return g;
}

function makeFoot(color: string): THREE.Group {
  const g = new THREE.Group();
  const { mat } = bodyMat(color, "clothes", false);
  const soleGeo = new THREE.SphereGeometry(0.055, 14, 10);
  soleGeo.scale(1.08, 0.55, 1.8);
  const sole = new THREE.Mesh(soleGeo, mat);
  sole.position.set(0, -0.035, 0.05);
  sole.castShadow = true;
  sole.receiveShadow = true;
  sole.userData.tint = "clothes";
  g.add(sole);
  return g;
}

/** 创建 Dummy13 风格可动素模 */
/**
 * 创建可动素模：15 关节层级 + 21 旋转角，支持 HumanVariant 体型预设。
 * 骨骼层级、BoneMap、boneKey 与 applyPose 完全不变，与 Stage3D 的关节控制无缝对接。
 */
export function makeRiggedHumanoid(
  color: string,
  pose?: JointPose,
  variant: HumanVariant = "male_std",
  hairStyle: HairStyle = "none",
): THREE.Group {
  // eslint-disable-next-line no-console
  console.log("[RiggedHumanoid] makeRiggedHumanoid", { variant, meshStyle: RIG_MESH_STYLE });
  const root = new THREE.Group();
  root.userData.meshStyle = RIG_MESH_STYLE;

  const body = color || "#60a5fa";
  const P = HUMAN_PRESETS[variant];
  // 整体身高/比例缩放——让儿童明显更矮、瘦人略高、胖人略矮
  root.scale.setScalar(P.heightScale);

  // —— 骨盆根 ——
  const hips = new THREE.Group();
  hips.position.y = P.hipsY;
  root.add(hips);
  const pelvis = capsulePart(P.pelvisW * 0.5, 0.08, body, "clothes", false);
  pelvis.rotation.x = Math.PI / 2;
  pelvis.scale.set(1.0, 1.0, 0.625);
  hips.add(pelvis);
  hips.add(jointBall(0.055));

  // —— 腹节 ——
  const abdomen = new THREE.Group();
  abdomen.position.y = 0.1;
  hips.add(abdomen);
  const abdomenMesh = taperedCylinderPart(P.abdomenW * 0.5, P.pelvisW * 0.41, 0.2, body);
  abdomen.add(abdomenMesh);
  const abJoint = jointBall(0.05);
  abJoint.position.y = 0.2;
  abdomen.add(abJoint);

  // —— 胸节：多层胶囊叠加更平滑 ——
  const spine = new THREE.Group();
  spine.position.y = 0.22;
  abdomen.add(spine);
  const chestR = P.chestW / 2;
  const torsoTop = taperedCylinderPart(P.shoulderPadW * 0.45, chestR * 0.94, 0.48, body);
  torsoTop.name = "torsoTop";
  torsoTop.position.y = 0.0;
  spine.add(torsoTop);
  const shoulderPad = capsulePart(P.shoulderPadW / 2, 0.06, body, "clothes", false);
  shoulderPad.name = "shoulderPad";
  shoulderPad.position.y = P.shoulderPadY + 0.1;
  shoulderPad.scale.set(1.0, 0.55, 0.72);
  spine.add(shoulderPad);
  const chestBadge = boxPart(0.12, 0.08, 0.025, "#f8fafc", "front");
  chestBadge.position.set(0, P.shoulderPadY + 0.12, chestR + 0.015);
  spine.add(chestBadge);

  // —— 颈 + 头 ——
  // 颈关节（旋转支点，挂在 spine 下；颈部视觉网格也挂 spine，避免转头时脖子跟着转）
  const neckJoint = jointBall(0.045);
  neckJoint.position.y = P.shoulderPadY + 0.3;
  spine.add(neckJoint);
  const neck = taperedCylinderPart(0.048, 0.042, 0.06, body);
  neck.position.y = P.shoulderPadY + 0.37;
  spine.add(neck);
  const head = new THREE.Group();
  head.position.y = P.shoulderPadY + 0.34;
  spine.add(head);
  const skullHalf = P.skullW / 2;
  const skull = ellipsoidHeadPart(P.skullW, body);
  skull.position.y = skullHalf * 1.15;
  head.add(skull);
  // 五官（正面约定：局部 +Z）—— 位置适配椭球头
  const faceMat = new THREE.MeshStandardMaterial({ color: "#0f172a", roughness: 0.35 });
  const eyeR = Math.max(0.02, P.skullW * 0.12);
  const eyeY = skullHalf * 1.15 + eyeR * 0.35;
  const eyeZ = skullHalf * 0.92 + 0.01;
  const lEye = new THREE.Mesh(new THREE.SphereGeometry(eyeR, 8, 8), faceMat);
  lEye.position.set(-skullHalf * 0.38, eyeY, eyeZ);
  lEye.userData.tint = "face";
  const rEye = lEye.clone();
  rEye.position.x = skullHalf * 0.38;
  rEye.userData.tint = "face";
  head.add(lEye, rEye);
  const nose = new THREE.Mesh(new THREE.ConeGeometry(eyeR * 0.55, eyeR * 1.3, 10), faceMat);
  nose.rotation.x = -Math.PI / 2;
  nose.position.set(0, eyeY - eyeR * 0.65, eyeZ + eyeR * 0.9);
  nose.userData.tint = "face";
  head.add(nose);
  // 发型
  const hair = makeHair(hairStyle, P.skullW);
  if (hair) {
    hair.position.y = skullHalf * 1.0;
    head.add(hair);
  }

  // —— 左臂 ——
  const lShoulder = new THREE.Group();
  lShoulder.position.set(-P.shoulderOffsetX, P.shoulderOffsetY + P.shoulderPadY, P.shoulderOffsetZ);
  spine.add(lShoulder);
  lShoulder.add(jointBall(0.055));
  const lUpper = taperedCapsulePart(P.armR, P.foreR * 1.05, 0.26, body);
  lUpper.position.y = -0.16;
  lShoulder.add(lUpper);
  const lElbow = new THREE.Group();
  lElbow.position.y = -0.3;
  lShoulder.add(lElbow);
  lElbow.add(jointHinge(0.045));
  const lFore = taperedCapsulePart(P.foreR, P.foreR * 0.82, 0.24, body);
  lFore.position.y = -0.14;
  lElbow.add(lFore);
  const lWrist = new THREE.Group();
  lWrist.position.y = -0.28;
  lElbow.add(lWrist);
  lWrist.add(jointBall(0.035));
  const lHand = makeHand(body);
  lHand.position.y = -0.02;
  lWrist.add(lHand);

  // —— 右臂 ——
  const rShoulder = new THREE.Group();
  rShoulder.position.set(P.shoulderOffsetX, P.shoulderOffsetY + P.shoulderPadY, P.shoulderOffsetZ);
  spine.add(rShoulder);
  rShoulder.add(jointBall(0.055));
  const rUpper = taperedCapsulePart(P.armR, P.foreR * 1.05, 0.26, body);
  rUpper.position.y = -0.16;
  rShoulder.add(rUpper);
  const rElbow = new THREE.Group();
  rElbow.position.y = -0.3;
  rShoulder.add(rElbow);
  rElbow.add(jointHinge(0.045));
  const rFore = taperedCapsulePart(P.foreR, P.foreR * 0.82, 0.24, body);
  rFore.position.y = -0.14;
  rElbow.add(rFore);
  const rWrist = new THREE.Group();
  rWrist.position.y = -0.28;
  rElbow.add(rWrist);
  rWrist.add(jointBall(0.035));
  const rHand = makeHand(body);
  rHand.position.y = -0.02;
  rWrist.add(rHand);

  // —— 左腿 ——
  const lHip = new THREE.Group();
  lHip.position.set(-P.hipOffsetX, -0.06, 0);
  hips.add(lHip);
  lHip.add(jointBall(0.055));
  const lThigh = taperedCapsulePart(P.thighR, P.shinR * 1.08, 0.32, body);
  lThigh.position.y = -0.18;
  lHip.add(lThigh);
  const lKnee = new THREE.Group();
  lKnee.position.y = -0.34;
  lHip.add(lKnee);
  lKnee.add(jointHinge(0.05));
  const lShin = taperedCapsulePart(P.shinR, P.shinR * 0.82, 0.3, body);
  lShin.position.y = -0.17;
  lKnee.add(lShin);
  const lAnkle = new THREE.Group();
  lAnkle.position.y = -0.34;
  lKnee.add(lAnkle);
  lAnkle.add(jointBall(0.04));
  const lFoot = makeFoot(body);
  lAnkle.add(lFoot);

  // —— 右腿 ——
  const rHip = new THREE.Group();
  rHip.position.set(P.hipOffsetX, -0.06, 0);
  hips.add(rHip);
  rHip.add(jointBall(0.055));
  const rThigh = taperedCapsulePart(P.thighR, P.shinR * 1.08, 0.32, body);
  rThigh.position.y = -0.18;
  rHip.add(rThigh);
  const rKnee = new THREE.Group();
  rKnee.position.y = -0.34;
  rHip.add(rKnee);
  rKnee.add(jointHinge(0.05));
  const rShin = taperedCapsulePart(P.shinR, P.shinR * 0.82, 0.3, body);
  rShin.position.y = -0.17;
  rKnee.add(rShin);
  const rAnkle = new THREE.Group();
  rAnkle.position.y = -0.34;
  rKnee.add(rAnkle);
  rAnkle.add(jointBall(0.04));
  const rFoot = makeFoot(body);
  rAnkle.add(rFoot);

  const bones: BoneMap = {
    abdomen,
    spine,
    head,
    lShoulder,
    lElbow,
    lWrist,
    rShoulder,
    rElbow,
    rWrist,
    lHip,
    lKnee,
    lAnkle,
    rHip,
    rKnee,
    rAnkle,
  };
  for (const [key, bone] of Object.entries(bones)) {
    bone.userData.boneKey = key;
    bone.traverse((ch) => {
      ch.userData.boneKey = key;
    });
  }
  root.userData.bones = bones;
  root.userData.frontAxis = "+z";
  root.userData.variant = variant;
  root.userData.hairStyle = hairStyle;
  const frontArrow = new THREE.Mesh(
    new THREE.ConeGeometry(0.07, 0.18, 4),
    new THREE.MeshStandardMaterial({
      color: "#fbbf24",
      emissive: "#b45309",
      emissiveIntensity: 0.35,
      roughness: 0.5,
    }),
  );
  frontArrow.rotation.x = Math.PI / 2;
  frontArrow.position.set(0, 0.05, 0.32);
  frontArrow.userData.tint = "front";
  frontArrow.userData.frontMarker = true;
  root.add(frontArrow);
  applyPose(root, pose || defaultPose());
  bindHumanoidPickData(root);
  // DEBUG: 检查所有 mesh geometry
  const broken: string[] = [];
  const nan: string[] = [];
  const pathOf = (obj: THREE.Object3D): string => {
    const parts: string[] = [];
    let p: THREE.Object3D | null = obj;
    while (p && p !== root) {
      parts.unshift(`${p.type}${p.name ? ":" + p.name : ""}`);
      p = p.parent;
    }
    return parts.join(" > ");
  };
  root.traverse((ch) => {
    if ((ch as THREE.Mesh).isMesh) {
      const m = ch as THREE.Mesh;
      const g = m.geometry;
      const pos = g.attributes.position;
      const idx = g.index;
      const path = pathOf(m);
      if (!pos || !pos.array || !(pos.array.byteLength > 0)) {
        broken.push(`${path}: position attribute broken`);
      } else {
        const arr = pos.array as Float32Array;
        for (let i = 0; i < arr.length; i++) {
          if (!isFinite(arr[i])) { nan.push(`${path}: pos[${i}]=${arr[i]}`); break; }
        }
      }
      if (idx && (!idx.array || !(idx.array.byteLength > 0))) {
        broken.push(`${path}: index attribute broken`);
      } else if (idx) {
        const arr = idx.array as Uint16Array | Uint32Array;
        for (let i = 0; i < arr.length; i++) {
          if (!isFinite(arr[i])) { nan.push(`${path}: idx[${i}]=${arr[i]}`); break; }
        }
      }
    }
  });
  if (broken.length) console.warn("[RiggedHumanoid] BROKEN:", broken.join("\n"));
  if (nan.length) console.warn("[RiggedHumanoid] NaN:", nan.join("\n"));
  console.log("[RiggedHumanoid] total meshes:", (function () { let c = 0; root.traverse(o => { if ((o as THREE.Mesh).isMesh) c++; }); return c; })());

  // 保存当前姿势，供 GLB 加载完成后重新应用
  root.userData._lastPose = pose || defaultPose();

  // 删除胶囊素模：创建后立即隐藏所有胶囊网格，不再作为可见模型或失败回退；
  // bones（Group 节点）保留，供关节拾取 / 姿势驱动使用。frontMarker 方向箭头除外。
  root.traverse((ch) => {
    const m = ch as THREE.Mesh;
    if (m.isMesh && !m.userData.frontMarker) m.visible = false;
  });

  // 异步加载 BodyKun/BodyChan：灰白素体 + 黑网格 + 关节球，保留现有 JointPose
  attachGLBToHumanoid(root, bodyFigureUrl(variant));

  return root;
}

export function applyPose(
  root: THREE.Object3D,
  pose: JointPose,
  opts?: { /** 默认 false：预设/拖肢按作者角度直出；动作采样已自带 chain 时勿再套 */ chain?: boolean },
) {
  // 保存最新姿势，供异步加载的 GLB 骨架使用
  root.userData._lastPose = pose;

  const merged = mergePose(defaultPose(), pose);
  // resolveChainPose 是累加型、非幂等：对已写好的预设再套一次会把坐姿/抱臂等拧坏
  const resolved =
    opts?.chain === true
      ? resolveClampPose(resolveChainPose(merged))
      : resolveClampPose(merged);
  applyPoseResolved(root, resolved);
}

/**
 * 直接应用已过 chain + clamp 的姿态（供采样器/关键帧等已解析路径调用）。
 * 避免对同一姿态重复执行链式联动与防穿模——resolveChainPose 的规则是累加增量、
 * 非幂等，二次执行会把肩→肘、髋→膝、胸→头等联动放大，导致动作比预设更夸张。
 */
export function applyPoseResolved(root: THREE.Object3D, resolvedPose: JointPose) {
  // —— capsule 骨架（原有 21 关节）——
  const bones = root.userData.bones as BoneMap | undefined;
  if (bones) {
    const p = resolvedPose;
    const neg = (v: number) => -v;

    // ★ 2026-10-05 修躯干/头 X 轴符号：实测（bodykun.glb，脚趾朝 +Z 判为前方）
    //   `neg(spineX)` 使 +30° 让头顶朝 **-Z（后）** 移动 ⇒ 与 UI 标签「前倾」相反，
    //   导致「鞠躬」预设（躯干正值）实际表现为**后仰**。去掉 neg 后 +X = 前倾，标签语义成立。
    bones.abdomen.rotation.set(deg(p.abdomenX), deg(p.abdomenY), deg(p.abdomenZ));
    bones.spine.rotation.set(deg(p.spineX), deg(p.spineY), deg(p.spineZ));
    bones.head.rotation.set(deg(p.headX), deg(p.headY), deg(p.headZ));

    // ★ 2026-10-05 补内旋（Y 轴）：此前 Y 硬编码为 0，导致肩/髋被砍成 2 自由度，
    //   肘弯曲平面锁死 ⇒「叉腰/抱臂/握手/背手」做不出、手臂像板子。
    //   Y 正 = 内旋（与 JOINT_LABELS 的「左臂内旋/左腿内旋」一致；右侧镜像取负为对称）。
    bones.lShoulder.rotation.set(deg(neg(p.lShoulderX)), deg(p.lShoulderY), deg(p.lShoulderZ));
    bones.lElbow.rotation.set(deg(neg(p.lElbowX)), deg(p.lElbowY), 0);
    bones.lWrist.rotation.set(deg(neg(p.lWristX)), 0, 0);
    bones.rShoulder.rotation.set(deg(neg(p.rShoulderX)), deg(p.rShoulderY), deg(p.rShoulderZ));
    bones.rElbow.rotation.set(deg(neg(p.rElbowX)), deg(p.rElbowY), 0);
    bones.rWrist.rotation.set(deg(neg(p.rWristX)), 0, 0);

    bones.lHip.rotation.set(deg(neg(p.lHipX)), deg(p.lHipY), deg(p.lHipZ));
    bones.lKnee.rotation.set(deg(neg(p.lKneeX)), 0, 0);
    bones.lAnkle.rotation.set(deg(neg(p.lAnkleX)), 0, 0);
    bones.rHip.rotation.set(deg(neg(p.rHipX)), deg(p.rHipY), deg(p.rHipZ));
    bones.rKnee.rotation.set(deg(neg(p.rKneeX)), 0, 0);
    bones.rAnkle.rotation.set(deg(neg(p.rAnkleX)), 0, 0);
  }

  // —— GLB 骨架（retarget 叠加，保留 GLB 自带 T-Pose identity）——
  const glBones = root.userData.glBones as GLBBoneMap | undefined;
  const glIdentity = root.userData.glBonesIdentity as Record<string, THREE.Quaternion> | undefined;
  if (glBones && glIdentity) {
    // 用已过 chain + clamp 的 resolvedPose，避免 GLB 内部重复处理
    applyPoseToGLBResolved(glBones, resolvedPose, glIdentity);
  }
  root.updateMatrixWorld(true);
  root.traverse((obj) => {
    const mesh = obj as THREE.SkinnedMesh;
    if (mesh.isSkinnedMesh && mesh.skeleton) mesh.skeleton.update();
  });
}

/**
 * 轻量穿模修正器：根据肩/肘角度关系自适应钳制，避免手臂穿过躯干/头部。
 * 纯数学 clamp，不依赖 Three.js raycasting，性能零损耗。
 * 仅处理"自然下垂态下被动穿模"场景，不主动干预有意为之的姿势。
 *
 * 只覆盖 2 类高频被动穿模：
 *   1. 手臂贴身自然下垂（shoulderX ≈ 0）+ 弯肘过大 → 前臂穿腹部
 *   2. 上臂贴身内摆（shoulderX 小幅 +Z 侧摆不足） → 上臂穿躯干
 *
 * 以下场景**绝不干预**（留给姿势预设本身）：
 *   - cross_arms（故意弯肘抱臂）
 *   - think（故意弯肘到头部）
 *   - phone（故意弯肘看手机）
 *   - wave/cheer/stretch（故意举手）
 */
export function resolveClampPose(pose: JointPose): JointPose {
  const p: JointPose = { ...pose };

  // —— 规则 1：前臂穿躯干（仅自然下垂态）——
  // 触发条件：shoulderX 在 -25~25°（手臂几乎垂直自然下垂方向）
  //         + shoulderZ 贴身（|Z| < 20°）
  //         + elbowX 过大
  // 贴身度越高，弯曲上限越低；完全张开时上限正常 145°
  const clampElbowNatural = (shX: number, shZ: number, elX: number): number => {
    // 仅自然下垂区间才防穿模：手已抬起（shX < -25 或 shX > 25）的不干预
    if (shX < -25 || shX > 25) return elX;
    const absZ = Math.abs(shZ);
    if (absZ >= 30) return elX; // 肩已张开不贴身，无穿模风险
    // 贴身度 0=完全贴身, 1=完全张开
    const openness = Math.max(0, Math.min(1, absZ / 30));
    // 完全贴身时上限 100°（足够弯起手），完全张开时正常 145°
    const maxElbow = 100 + openness * 45;
    return Math.min(elX, maxElbow);
  };
  p.lElbowX = clampElbowNatural(p.lShoulderX, p.lShoulderZ, p.lElbowX);
  p.rElbowX = clampElbowNatural(p.rShoulderX, p.rShoulderZ, p.rElbowX);

  // —— 规则 2：上臂穿躯干（仅轻微内摆 + 贴身）——
  // 触发条件：shoulderX 在 -15~15°（小幅内摆，还没抬起）
  //         + shoulderZ 极贴身
  // 渐进抬升：用户把 shoulderZ 从 0 滑到 20° 时，实际值从 5° 连续降到原值，
  // 避免滑条拖到 0° 时上臂突然"弹开"的视觉跳变；下限 5° 足够防穿模，
  // 又允许手臂自然下垂贴身（不八字张开）
  const pushShoulderOutSmooth = (shX: number, shZ: number, sign: 1 | -1): number => {
    if (shX < -15 || shX > 15) return shZ;
    const absZ = Math.abs(shZ);
    if (absZ >= 20) return shZ;
    // 渐进 ramp：absZ=0 → 输出 5°；absZ=10 → max(10, 2.5) = 10°；absZ=20 → 不推
    const floor = 5 - absZ * 0.25;
    const outAbs = Math.max(absZ, floor);
    return sign * outAbs;
  };
  p.lShoulderZ = pushShoulderOutSmooth(p.lShoulderX, p.lShoulderZ, 1);
  p.rShoulderZ = pushShoulderOutSmooth(p.rShoulderX, p.rShoulderZ, -1);

  return p;
}

/* ─────────────────────────────────────────────────────────────────────
 * 链式联动约束 / Kinematic Chain（仅同一肢体链内）
 *
 * 只保留"同一条肢体内部"的联动，让主动关节带动相邻关节：
 *   肩 → 肘、髋 → 膝、肘 → 腕、膝 → 踝。
 *
 * 已移除跨部位联动（胸→头、腹→胸、腿→对侧臂、头→胸、重心补偿），
 * 避免手动摆姿势时拖动躯干/头导致其他部位跟着动，保证关节独立可控。
 *
 * 注意：所有联动都是**叠加小偏移量**，不覆盖用户显式设置的值。
 * ───────────────────────────────────────────────────────────────────── */
export function resolveChainPose(pose: JointPose, strength = 1.0): JointPose {
  const p: JointPose = { ...pose };
  const s = Math.max(0, Math.min(1.5, strength));

  // —— 规则 1：肩 → 肘 联动 ——
  // 肩膀侧举/上举幅度越大，肘自然微弯越多（0~15°）
  // 仅当肩处于"举起"区间时才联动（不是自然下垂）
  const armChain = (shX: number, shZ: number, elX: number): number => {
    const shUp = Math.max(0, -shX); // shX < -20 视为举手
    const shSide = Math.max(0, Math.abs(shZ) - 20); // 侧举超过 20° 的部分
    const raiseAmount = Math.min(1, shUp / 60 + shSide / 140);
    const chainAmount = raiseAmount * 15 * s;
    return Math.min(145, elX + chainAmount);
  };
  p.lElbowX = armChain(p.lShoulderX, p.lShoulderZ, p.lElbowX);
  p.rElbowX = armChain(p.rShoulderX, p.rShoulderZ, p.rElbowX);

  // —— 规则 2：髋 → 膝 联动 ——
  // 髋大幅前屈（如走路抬脚、坐）时，膝自动微屈
  const legChain = (hipX: number, kneeX: number): number => {
    // hipX > 30° 视为抬腿/坐
    const liftAmount = Math.max(0, (hipX - 15) / 55);
    const chainAmount = liftAmount * 18 * s;
    return Math.min(140, kneeX + chainAmount);
  };
  p.lKneeX = legChain(p.lHipX, p.lKneeX);
  p.rKneeX = legChain(p.rHipX, p.rKneeX);

  // —— 规则 6：肘 → 腕 联动 ——
  // 肘大幅弯曲时，手腕自然微调跟随（防手硬直）
  const elbowToWrist = (elX: number, wrX: number): number => {
    const flex = Math.max(0, elX - 50);
    return wrX + flex * 0.15 * s;
  };
  p.lWristX = elbowToWrist(p.lElbowX, p.lWristX);
  p.rWristX = elbowToWrist(p.rElbowX, p.rWristX);

  // —— 规则 7：膝 → 踝 联动 ——
  // 膝弯曲时，脚踝自动补脚面弯曲（防脚面锁死）
  const kneeToAnkle = (knX: number, anX: number): number => {
    const flex = Math.max(0, knX - 25);
    return anX + flex * 0.2 * s;
  };
  p.lAnkleX = kneeToAnkle(p.lKneeX, p.lAnkleX);
  p.rAnkleX = kneeToAnkle(p.rKneeX, p.rAnkleX);

  // —— 规则 8：重心偏移补偿 ——
  // 单腿抬起时，躯干反向倾斜保持平衡（模拟走路/跳跃的重心转移）
  const lLift = Math.max(0, p.lHipX - 20);
  const rLift = Math.max(0, p.rHipX - 20);
  const netLift = lLift - rLift;
  if (Math.abs(netLift) > 5) {
    const offset = Math.max(-12, Math.min(12, netLift * 0.18 * s));
    p.spineX -= offset;
  }

  // —— 规则 9：头大幅俯仰 → 胸微幅补偿 ——
  // 点头太深时胸微微跟进，仰头太深时胸微微后弯
  // 注意：阈值提高、系数降低，避免"拖头带动躯干"的突兀感
  const headLimit = 30;
  if (Math.abs(p.headX) > headLimit) {
    const extra = (p.headX - Math.sign(p.headX) * headLimit) * 0.12 * s;
    p.spineX += extra;
  }

  // 最后用 JOINT_LABELS 的 min/max 做一次硬钳制，防止 chain 超界
  for (const { key, min, max } of JOINT_LABELS) {
    p[key] = Math.max(min, Math.min(max, p[key]));
  }

  return p;
}

export function mergePose(base: JointPose, patch: Partial<JointPose>): JointPose {
  return { ...base, ...patch };
}

/* ─────────────────────────────────────────────────────────────────────
 * 缓动函数已移至文件顶部（第 12-18 行），避免 TDZ 并让 MOTION_PRESETS
 * 能先于 easeInOutSine / easeOutBack 等引用到它们。
 * ───────────────────────────────────────────────────────────────────── */

/** 对每个关节值分别 ease 再插值 */
export function lerpPose(
  a: JointPose,
  b: JointPose,
  t: number,
  easeFn: (t: number) => number = easeInOutCubic,
): JointPose {
  const k = easeFn(Math.max(0, Math.min(1, t)));
  const r: JointPose = {} as JointPose;
  for (const key of Object.keys(a) as (keyof JointPose)[]) {
    r[key] = a[key] + (b[key] - a[key]) * k;
  }
  return r;
}

/** 姿势关键帧：在 { t, pose } 基础上扩展 easing / interpolation / bezier 控制点，
 *  对齐后端 app/core/keyframe_animation.py 的 Keyframe 结构。 */
export type PoseKeyframe = {
  t: number;
  pose: JointPose;
  /** 本帧 → 下一帧 段的缓动（默认 ease_in_out，柔和连续） */
  easing?: EasingName;
  /** 插值方式：linear（默认）/ bezier / step */
  interpolation?: "linear" | "bezier" | "step";
  /** 贝塞尔控制点 [x, y]；对齐后端 _apply_bezier：仅取 y，x 语义占位 */
  bezierC1?: [number, number];
  bezierC2?: [number, number];
};

/** 由 EasingName 解析缓动函数（未知名回退线性） */
export function resolveEasingFn(easing?: EasingName): (t: number) => number {
  return (easing && EASING_FNS[easing]) || easeLinear;
}

/** 单值三次贝塞尔插值（对齐后端 _apply_bezier：控制点仅取 y 分量） */
function bezierValue(
  t: number,
  v0: number,
  v1: number,
  c0: [number, number],
  c1: [number, number],
): number {
  const t2 = t * t;
  const t3 = t2 * t;
  const mt = 1 - t;
  const mt2 = mt * mt;
  const mt3 = mt2 * mt;
  return mt3 * v0 + 3 * mt2 * t * c0[1] + 3 * mt * t2 * c1[1] + t3 * v1;
}

/**
 * 在关键帧序列里按时间戳取插值姿势。
 * 每个关键帧可携带 easing（段缓动）/ interpolation（bezier/step）/ bezier 控制点，
 * 未指定 easing 时回退 defaultEaseFn；输出自动过 resolveChainPose + resolveClampPose。
 */
export function sampleKeyframes(
  keyframes: PoseKeyframe[],
  timeMs: number,
  defaultEaseFn: (t: number) => number = easeInOutCubic,
): JointPose {
  if (!keyframes.length) return defaultPose();
  if (keyframes.length === 1) return resolveChainPose(resolveClampPose(keyframes[0].pose));
  const sorted = [...keyframes].sort((a, b) => a.t - b.t);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  if (timeMs <= first.t) return resolveChainPose(resolveClampPose(first.pose));
  if (timeMs >= last.t) return resolveChainPose(resolveClampPose(last.pose));
  for (let i = 0; i < sorted.length - 1; i++) {
    const a = sorted[i];
    const b = sorted[i + 1];
    if (timeMs >= a.t && timeMs <= b.t) {
      const rawT = (timeMs - a.t) / (b.t - a.t);
      const easeFn = a.easing ? resolveEasingFn(a.easing) : defaultEaseFn;
      let raw: JointPose;
      if (a.interpolation === "step") {
        raw = a.pose;
      } else if (a.interpolation === "bezier" && a.bezierC1 && a.bezierC2) {
        const k = easeFn(Math.max(0, Math.min(1, rawT)));
        raw = {} as JointPose;
        for (const key of Object.keys(a.pose) as (keyof JointPose)[]) {
          raw[key] = bezierValue(k, a.pose[key], b.pose[key], a.bezierC1, a.bezierC2);
        }
      } else {
        raw = lerpPose(a.pose, b.pose, rawT, easeFn);
      }
      return resolveChainPose(resolveClampPose(raw));
    }
  }
  return resolveChainPose(resolveClampPose(last.pose));
}

export function applyPreset(id: PosePresetId): JointPose {
  const hit = POSE_PRESETS.find((p) => p.id === id);
  return mergePose(defaultPose(), hit?.pose || {});
}

/** 坐/蹲/跪等需要降髋，否则腿弯了人还站着高，看起来像漂浮或腿折进肚子 */
export const POSE_ROOT_OFFSET_Y: Partial<Record<PosePresetId, number>> = {
  sit: -0.42,
  crouch: -0.45,
  kneel: -0.28,
  jump_kick: 0.12,
};

/** 群像站位：在世界 XZ 平面排布 */
export type FormationId = "line" | "arc" | "circle" | "face" | "triangle";

export type GroupTemplateId = "duo-face" | "trio-arc" | "quad-line" | "five-circle";

/** 一键生成多人（不是只重排现有 1 人） */
export const GROUP_TEMPLATES: {
  id: GroupTemplateId;
  label: string;
  count: number;
  formation: FormationId;
}[] = [
  { id: "duo-face", label: "双人对峙", count: 2, formation: "face" },
  { id: "trio-arc", label: "三人弧形", count: 3, formation: "arc" },
  { id: "quad-line", label: "四人一字", count: 4, formation: "line" },
  { id: "five-circle", label: "五人围圆", count: 5, formation: "circle" },
];

/** 使局部 +Z（正面）指向目标点的 Y 旋转（弧度） */
export function yawToward(
  from: [number, number, number],
  to: [number, number, number],
): number {
  return Math.atan2(to[0] - from[0], to[2] - from[2]);
}

export function formationPositions(
  count: number,
  formation: FormationId,
  spacing = 1.15,
): [number, number, number][] {
  const n = Math.max(1, count);
  const out: [number, number, number][] = [];
  if (formation === "line") {
    const start = -((n - 1) * spacing) / 2;
    for (let i = 0; i < n; i++) out.push([start + i * spacing, 0, 0]);
    return out;
  }
  if (formation === "arc") {
    const radius = Math.max(1.2, (n * spacing) / Math.PI);
    const sweep = Math.min(Math.PI * 0.9, (n - 1) * 0.35 + 0.4);
    const start = -sweep / 2;
    for (let i = 0; i < n; i++) {
      const a = n === 1 ? 0 : start + (sweep * i) / Math.max(1, n - 1);
      out.push([Math.sin(a) * radius, 0, -Math.cos(a) * radius + radius * 0.35]);
    }
    return out;
  }
  if (formation === "circle") {
    const radius = Math.max(1.1, (n * spacing) / (2 * Math.PI) + 0.6);
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      out.push([Math.cos(a) * radius, 0, Math.sin(a) * radius]);
    }
    return out;
  }
  if (formation === "face") {
    const half = Math.ceil(n / 2);
    for (let i = 0; i < n; i++) {
      const row = i < half ? 0 : 1;
      const idx = i < half ? i : i - half;
      const rowN = row === 0 ? half : n - half;
      const start = -((rowN - 1) * spacing) / 2;
      out.push([start + idx * spacing, 0, row === 0 ? -0.9 : 0.9]);
    }
    return out;
  }
  let left = n;
  let row = 0;
  let placed = 0;
  while (placed < n) {
    const rowCount = Math.min(left, row + 1);
    const start = -((rowCount - 1) * spacing) / 2;
    for (let i = 0; i < rowCount; i++) {
      out.push([start + i * spacing, 0, row * spacing * 0.85]);
      placed++;
    }
    left -= rowCount;
    row++;
  }
  return out;
}

export function facingYForFormation(
  pos: [number, number, number],
  formation: FormationId,
): number {
  if (formation === "face") {
    return pos[2] < 0 ? 0 : Math.PI;
  }
  if (formation === "circle" || formation === "arc") {
    return Math.atan2(pos[0], pos[2]) + Math.PI;
  }
  return 0;
}


/* ───────────────────────────────────────────────────────────────────────
 * GLB Retarget 层
 *
 * 方案 A 真正含义：
 *   1. 加载 GLB → 拿到 SkinnedMesh + mixamorig:* 骨架
 *   2. 用 GLB 自带骨架做骨骼动画（顶点权重绑定在它们身上）
 *   3. 建立 JointPose 字段 → GLB 骨骼的 retarget 映射表
 *   4. applyPoseToGLB 把旋转叠加到 GLB 骨架上（保留 T-Pose identity）
 *
 * 这样：现有姿势库、穿模修正、体型缩放全部复用，
 *      只是 mesh 从 capsule 变成写实 GLB。
 * ─────────────────────────────────────────────────────────────────────── */

type GLBBoneMap = Partial<Record<
  | "hips" | "abdomen" | "spine" | "spine2"
  | "head" | "neck"
  | "lShoulder" | "lArm" | "lForeArm" | "lWrist"
  | "rShoulder" | "rArm" | "rForeArm" | "rWrist"
  | "lHip" | "lKnee" | "lAnkle"
  | "rHip" | "rKnee" | "rAnkle",
  THREE.Object3D
>>;

function collectSkinBones(scene: THREE.Object3D): THREE.Object3D[] {
  const out: THREE.Object3D[] = [];
  const seen = new Set<THREE.Object3D>();
  scene.traverse((obj) => {
    const mesh = obj as THREE.SkinnedMesh;
    if (!mesh.isSkinnedMesh || !mesh.skeleton) return;
    for (const bone of mesh.skeleton.bones) {
      if (bone && !seen.has(bone)) {
        seen.add(bone);
        out.push(bone);
      }
    }
  });
  return out;
}

function boneNameTail(name: string): string {
  // 去掉 mixamorig 前缀 + 小数点 + 统一小写，兼容 Mixamo（LeftArm / DEF-thigh.L）
  // 与 BodyChan/BodyKun（DEF-spine001 / DEF-thighL，无点）两种命名
  return (name || "")
    .replace(/^(mixamorig|mixamo):?[\s_-]?/i, "")
    .replace(/\./g, "")
    .toLowerCase();
}

function findGLBBoneExact(scene: THREE.Object3D, keyword: string): THREE.Object3D | null {
  const key = boneNameTail(keyword);
  for (const bone of collectSkinBones(scene)) {
    if (boneNameTail(bone.name) === key) return bone;
  }
  let hit: THREE.Object3D | null = null;
  scene.traverse((obj) => {
    if (hit) return;
    if ((obj as THREE.Mesh).isMesh) return;
    if (boneNameTail(obj.name) === key) hit = obj;
  });
  return hit;
}

function pickGLBBone(scene: THREE.Object3D, aliases: string[]): THREE.Object3D | null {
  for (const a of aliases) {
    const hit = findGLBBoneExact(scene, a);
    if (hit) return hit;
  }
  return findGLBBone(scene, aliases[0]);
}

function findGLBBone(scene: THREE.Object3D, keyword: string): THREE.Object3D | null {
  const key = boneNameTail(keyword);
  let exact: THREE.Object3D | null = null;
  let fuzzy: THREE.Object3D | null = null;
  scene.traverse((obj) => {
    if (exact && fuzzy) return;
    if ((obj as THREE.Mesh).isMesh) return;
    const tail = boneNameTail(obj.name);
    if (!exact && tail === key) exact = obj;
    else if (!fuzzy && tail !== key && (tail.endsWith(key) || tail.includes(key))) fuzzy = obj;
  });
  return exact || fuzzy;
}

function buildGLBBoneMap(scene: THREE.Object3D): GLBBoneMap {
  const B: GLBBoneMap = {};
  B.hips = pickGLBBone(scene, ["Hips", "hips", "pelvis", "root"]);
  B.abdomen = pickGLBBone(scene, ["Spine", "DEF-spine.001", "spine.001", "abdomen", "waist"]);
  B.spine = pickGLBBone(scene, ["Spine1", "DEF-spine.002", "spine.002"]);
  B.spine2 = pickGLBBone(scene, ["Spine2", "DEF-spine.003", "spine.003", "chest"]);
  // 若腹部骨缺失或误绑到 hips，退到胸椎链，避免腰 IK 拧髋
  if (!B.abdomen || B.abdomen === B.hips) {
    B.abdomen = B.spine || B.spine2 || B.abdomen;
  }
  B.neck = pickGLBBone(scene, ["Neck", "DEF-spine.004", "DEF-neck", "neck"]);
  B.head = pickGLBBone(scene, ["Head", "DEF-spine.006", "DEF-head", "head"]);
  B.lShoulder = pickGLBBone(scene, ["LeftShoulder", "DEF-shoulder.L", "shoulder.L"]);
  B.lArm = pickGLBBone(scene, ["LeftArm", "DEF-upper_arm.L", "upper_arm.L"]);
  B.lForeArm = pickGLBBone(scene, ["LeftForeArm", "DEF-forearm.L", "forearm.L"]);
  B.lWrist = pickGLBBone(scene, ["LeftHand", "DEF-hand.L", "hand.L"]);
  B.rShoulder = pickGLBBone(scene, ["RightShoulder", "DEF-shoulder.R", "shoulder.R"]);
  B.rArm = pickGLBBone(scene, ["RightArm", "DEF-upper_arm.R", "upper_arm.R"]);
  B.rForeArm = pickGLBBone(scene, ["RightForeArm", "DEF-forearm.R", "forearm.R"]);
  B.rWrist = pickGLBBone(scene, ["RightHand", "DEF-hand.R", "hand.R"]);
  B.lHip = pickGLBBone(scene, ["LeftUpLeg", "DEF-thigh.L", "thigh.L"]);
  B.lKnee = pickGLBBone(scene, ["LeftLeg", "DEF-shin.L", "shin.L"]);
  B.lAnkle = pickGLBBone(scene, ["LeftFoot", "DEF-foot.L", "foot.L"]);
  B.rHip = pickGLBBone(scene, ["RightUpLeg", "DEF-thigh.R", "thigh.R"]);
  B.rKnee = pickGLBBone(scene, ["RightLeg", "DEF-shin.R", "shin.R"]);
  B.rAnkle = pickGLBBone(scene, ["RightFoot", "DEF-foot.R", "foot.R"]);
  return B;
}

export const BONE_CHAINS: Record<string, string[]> = {
  lArm: ["lShoulder", "lElbow", "lWrist"],
  rArm: ["rShoulder", "rElbow", "rWrist"],
  lLeg: ["lHip", "lKnee", "lAnkle"],
  rLeg: ["rHip", "rKnee", "rAnkle"],
  head: ["head"],
  torso: ["abdomen", "spine"],
};

export function chainIdForBone(key: string): string | null {
  for (const [id, bones] of Object.entries(BONE_CHAINS)) {
    if (bones.includes(key)) return id;
  }
  return null;
}

export function inferBoneRegion(name: string): string | null {
  const n = (name || "").toLowerCase();
  if (!n || /^wgt/.test(n)) return null;
  if (/head|skull/.test(n)) return "head";
  if (/neck/.test(n)) return "head";
  if (/torso|chest|bust|trunk/.test(n)) return "spine";
  if (/tummy|abdomen|waist|core/.test(n)) return "abdomen";
  // 骨盆网格按腰部点选，但姿态骨禁止绑到 Hips（见 bindHumanoidPickData）
  if (/pelvis|waist/.test(n)) return "abdomen";
  if (/hip/.test(n) && !/whip/.test(n)) return "hip";
  if (/upperarm|upper_arm|deltoid/.test(n)) return "shoulder";
  if (/forearm|lowerarm|lower_arm/.test(n)) return "elbow";
  if (/hand|wrist|finger|index|pinky|ring|thumb|palm|mid_/.test(n)) return "wrist";
  if (/thigh|upleg|upperleg/.test(n)) return "hip";
  if (/shin|lowerleg|calf/.test(n)) return "knee";
  if (/foot|feet|ankle|toe/.test(n)) return "ankle";
  return null;
}

export function chainBonesFor(boneKey: string): string[] {
  const id = chainIdForBone(boneKey);
  return id ? BONE_CHAINS[id] : boneKey ? [boneKey] : [];
}

export function endEffectorBoneKey(boneKey: string): string {
  const chain = chainIdForBone(boneKey);
  if (chain === "lArm") return "lWrist";
  if (chain === "rArm") return "rWrist";
  if (chain === "lLeg") return "lAnkle";
  if (chain === "rLeg") return "rAnkle";
  if (chain === "head") return "head";
  if (chain === "torso") return "spine";
  return boneKey;
}

export function pickClosestPoseBone(root: THREE.Object3D, worldPoint: THREE.Vector3): string | null {
  const bones = getPoseBones(root);
  let best: string | null = null;
  let bestD = Infinity;
  const p = new THREE.Vector3();
  for (const [key, bone] of Object.entries(bones)) {
    if (!bone) continue;
    bone.getWorldPosition(p);
    const d = p.distanceToSquared(worldPoint);
    if (d < bestD) {
      bestD = d;
      best = key;
    }
  }
  return best;
}

/** 从命中网格解析关节键：部位名 + 左右，或最近骨。 */
export function resolveHitBoneKey(
  root: THREE.Object3D,
  hitObject: THREE.Object3D,
  worldPoint: THREE.Vector3,
): string | null {
  let obj: THREE.Object3D | null = hitObject;
  let region: string | null = null;
  let boneKey: string | null = null;
  while (obj) {
    if (typeof obj.userData.boneRegion === "string" && !region) region = obj.userData.boneRegion;
    if (typeof obj.userData.boneKey === "string" && !boneKey) boneKey = obj.userData.boneKey;
    if (obj === root) break;
    obj = obj.parent;
  }
  if (region) return resolvePickBoneKey(root, region, worldPoint);
  if (boneKey) return boneKey;
  return pickClosestPoseBone(root, worldPoint);
}

const POSE_BONE_AXES: Record<string, { x?: keyof JointPose; y?: keyof JointPose; z?: keyof JointPose }> = {
  abdomen: { x: "abdomenX" },
  spine: { x: "spineX", y: "spineY" },
  head: { x: "headX", y: "headY" },
  lShoulder: { x: "lShoulderX", z: "lShoulderZ" },
  lElbow: { x: "lElbowX" },
  lWrist: { x: "lWristX" },
  rShoulder: { x: "rShoulderX", z: "rShoulderZ" },
  rElbow: { x: "rElbowX" },
  rWrist: { x: "rWristX" },
  lHip: { x: "lHipX", z: "lHipZ" },
  lKnee: { x: "lKneeX" },
  lAnkle: { x: "lAnkleX" },
  rHip: { x: "rHipX", z: "rHipZ" },
  rKnee: { x: "rKneeX" },
  rAnkle: { x: "rAnkleX" },
};

/** 把骨骼当前欧拉角读回 JointPose（对齐 applyPose 的 X 取反 + GLB T-Pose identity）。 */
export function readPosePatchFromBone(
  root: THREE.Object3D,
  bone: THREE.Object3D,
  boneKey: string,
): Partial<JointPose> {
  const map = POSE_BONE_AXES[boneKey];
  if (!map) return {};
  const identMap = (root.userData.glBonesIdentity || {}) as Record<string, THREE.Quaternion | THREE.Euler>;
  const gl = root.userData.glBones as GLBBoneMap | undefined;
  const restQ = new THREE.Quaternion();
  if (gl) {
    for (const [k, b] of Object.entries(gl)) {
      if (b === bone) {
        const rest = identMap[k];
        if (rest instanceof THREE.Quaternion) restQ.copy(rest);
        else if (rest) restQ.setFromEuler(rest as THREE.Euler);
        break;
      }
    }
  }
  const local = bone.quaternion.clone().premultiply(restQ.clone().invert());
  const euler = new THREE.Euler().setFromQuaternion(local, "XYZ");
  const toDeg = (r: number) => (r * 180) / Math.PI;
  const patch: Partial<JointPose> = {};
  // GLB 屈肘/屈膝在 applyPoseToGLB 里不再取反，读回保持同号
  const glbFlex =
    Boolean(gl) &&
    (boneKey.endsWith("Elbow") ||
      boneKey.endsWith("Wrist") ||
      boneKey.endsWith("Knee") ||
      boneKey.endsWith("Ankle"));
  if (map.x) patch[map.x] = (glbFlex ? 1 : -1) * toDeg(euler.x);
  if (map.y) patch[map.y] = toDeg(euler.y);
  if (map.z) patch[map.z] = toDeg(euler.z);
  return patch;
}

/**
 * Mixamo / BodyKun：解剖左在 +X；胶囊素模：解剖左在 -X。
 * 用左右肩（或手腕）世界坐标判断，避免点选/IK 操纵对面那条臂。
 */
export function isMixamoLateral(root: THREE.Object3D): boolean {
  const bones = getPoseBones(root);
  const l = bones.lShoulder || bones.lWrist || bones.lHip;
  const r = bones.rShoulder || bones.rWrist || bones.rHip;
  if (!l || !r) return Boolean(root.userData.glBones);
  const lp = new THREE.Vector3();
  const rp = new THREE.Vector3();
  l.getWorldPosition(lp);
  r.getWorldPosition(rp);
  return lp.x > rp.x + 0.02;
}

function regionToBoneKey(region: string, left: boolean): string {
  const L = left;
  switch (region) {
    case "shoulder": return L ? "lShoulder" : "rShoulder";
    case "elbow": return L ? "lElbow" : "rElbow";
    case "wrist": return L ? "lWrist" : "rWrist";
    case "hip": return L ? "lHip" : "rHip";
    case "knee": return L ? "lKnee" : "rKnee";
    case "ankle": return L ? "lAnkle" : "rAnkle";
    default: return region;
  }
}

export function resolvePickBoneKey(
  root: THREE.Object3D,
  region: string,
  worldPoint: THREE.Vector3,
): string {
  if (region === "head" || region === "spine" || region === "abdomen") return region;
  const bones = getPoseBones(root);
  const leftKey = regionToBoneKey(region, true);
  const rightKey = regionToBoneKey(region, false);
  const lb = bones[leftKey];
  const rb = bones[rightKey];
  if (lb && rb) {
    const dl = worldPos(lb).distanceToSquared(worldPoint);
    const dr = worldPos(rb).distanceToSquared(worldPoint);
    return dl <= dr ? leftKey : rightKey;
  }
  const local = worldPoint.clone().applyMatrix4(root.matrixWorld.clone().invert());
  const left = isMixamoLateral(root) ? local.x > 0 : local.x < 0;
  return regionToBoneKey(region, left);
}

export function getPoseBones(root: THREE.Object3D): Record<string, THREE.Object3D> {
  return (root.userData.poseBones as Record<string, THREE.Object3D>)
    || (root.userData.bones as Record<string, THREE.Object3D>)
    || {};
}

/** 把可见网格 / GLB 骨打上 boneKey，供点选与旋转环使用。 */
export function bindHumanoidPickData(root: THREE.Object3D) {
  const cap = root.userData.bones as BoneMap | undefined;
  const gl = root.userData.glBones as GLBBoneMap | undefined;
  const poseBones: Record<string, THREE.Object3D> = {};
  const assign = (key: string, obj?: THREE.Object3D | null) => {
    if (!obj) return;
    obj.userData.boneKey = key;
    poseBones[key] = obj;
  };
  if (cap) {
    for (const [k, b] of Object.entries(cap)) assign(k, b);
  }
  if (gl) {
    // 禁止把 hips 当成 abdomen：TransformControls/点选挂到骨盆会整身离地，地面像被拖变形
    assign("abdomen", gl.abdomen || gl.spine || gl.spine2);
    assign("spine", gl.spine2 || gl.spine);
    assign("head", gl.head || gl.neck);
    assign("lShoulder", gl.lShoulder || gl.lArm);
    assign("lElbow", gl.lForeArm || gl.lArm);
    assign("lWrist", gl.lWrist);
    assign("rShoulder", gl.rShoulder || gl.rArm);
    assign("rElbow", gl.rForeArm || gl.rArm);
    assign("rWrist", gl.rWrist);
    assign("lHip", gl.lHip);
    assign("lKnee", gl.lKnee);
    assign("lAnkle", gl.lAnkle);
    assign("rHip", gl.rHip);
    assign("rKnee", gl.rKnee);
    assign("rAnkle", gl.rAnkle);
  }
  root.userData.poseBones = poseBones;

  root.traverse((obj) => {
    if (!(obj as THREE.Mesh).isMesh) return;
    if (obj.userData.frontMarker) return;
    const region = inferBoneRegion(obj.name)
      || inferBoneRegion(obj.parent?.name || "")
      || (typeof obj.userData.boneKey === "string" ? boneKeyToRegion(obj.userData.boneKey) : null);
    if (region) obj.userData.boneRegion = region;
  });
}

export function boneKeyToRegion(key: string): string | null {
  if (key === "head") return "head";
  if (key === "spine") return "spine";
  if (key === "abdomen") return "abdomen";
  if (key.endsWith("Shoulder")) return "shoulder";
  if (key.endsWith("Elbow")) return "elbow";
  if (key.endsWith("Wrist")) return "wrist";
  if (key.endsWith("Hip")) return "hip";
  if (key.endsWith("Knee")) return "knee";
  if (key.endsWith("Ankle")) return "ankle";
  return null;
}

/** 手/脚/头/胸/腰（及同链肩肘髋膝）需：框选整模 → 双击解锁 → 再拖 */
export function needsJointUnlock(boneKey: string): boolean {
  const r = boneKeyToRegion(boneKey);
  return (
    r === "wrist" ||
    r === "ankle" ||
    r === "head" ||
    r === "spine" ||
    r === "abdomen" ||
    r === "shoulder" ||
    r === "elbow" ||
    r === "hip" ||
    r === "knee"
  );
}

export function sameUnlockChain(a: string, b: string): boolean {
  const ca = chainIdForBone(a);
  const cb = chainIdForBone(b);
  return Boolean(ca && ca === cb);
}

/** 胸/腰/头只用 IK，挂 TransformControls 易把骨盆连带拧飞 */
export function isIkOnlyUnlockBone(boneKey: string): boolean {
  const r = boneKeyToRegion(boneKey);
  return r === "spine" || r === "abdomen" || r === "head";
}

/** 拖拽模式：末端整肢 IK；中间/近端单关节 FK；头胸腰看向 */
export type LimbDragMode = "chainIk" | "segmentFk" | "look";

export function limbDragMode(boneKey: string): LimbDragMode {
  const r = boneKeyToRegion(boneKey);
  if (r === "head" || r === "spine" || r === "abdomen") return "look";
  if (r === "wrist" || r === "ankle") return "chainIk";
  if (r === "shoulder" || r === "elbow" || r === "hip" || r === "knee") return "segmentFk";
  return "chainIk";
}

/** 高亮范围：FK 只亮当前节；IK 亮整条肢 */
export function highlightBonesFor(boneKey: string): string[] {
  if (limbDragMode(boneKey) === "segmentFk") return [boneKey];
  return chainBonesFor(boneKey);
}

function worldPos(obj: THREE.Object3D, out = new THREE.Vector3()) {
  return obj.getWorldPosition(out);
}

/** 关节角 min/max 查找表（由 JOINT_LABELS 派生），避免 IK 每帧线性 find */
const JOINT_LIMITS: Record<keyof JointPose, { min: number; max: number }> = JOINT_LABELS.reduce(
  (acc, j) => {
    acc[j.key] = { min: j.min, max: j.max };
    return acc;
  },
  {} as Record<keyof JointPose, { min: number; max: number }>,
);

function clampJoint(key: keyof JointPose, value: number): number {
  const meta = JOINT_LIMITS[key];
  if (!meta) return value;
  return Math.max(meta.min, Math.min(meta.max, value));
}

/**
 * 2 骨 IK：目标点 → 肩/髋朝向 + 肘/膝弯曲，写成 JointPose 补丁。
 * 仅用于腕/踝等末端（整肢）；中间节请用 solveSegmentFk。
 */
export function solveChainIk(
  root: THREE.Object3D,
  boneKey: string,
  target: THREE.Vector3,
  pose: JointPose,
): Partial<JointPose> {
  const chain = chainIdForBone(boneKey);
  if (!chain) return {};
  const bones = getPoseBones(root);
  const qInv = root.getWorldQuaternion(new THREE.Quaternion()).invert();
  const rad2deg = (r: number) => (r * 180) / Math.PI;

  if (chain === "head") {
    const origin = bones.head ? worldPos(bones.head) : worldPos(root).add(new THREE.Vector3(0, 1.5, 0));
    const dir = target.clone().sub(origin).applyQuaternion(qInv);
    if (dir.lengthSq() < 1e-6) return {};
    dir.normalize();
    return {
      headY: clampJoint("headY", rad2deg(Math.atan2(dir.x, dir.z))),
      // headX 在 applyPose 中会取反（neg），此处用 +dir.y 才能让头朝目标方向俯仰（修正旧版上下反向）
      headX: clampJoint("headX", rad2deg(Math.atan2(dir.y, Math.hypot(dir.x, dir.z)))),
    };
  }

  if (chain === "torso") {
    // 胸/腰只转胸椎与轻度腹弯，不碰髋骨；增益收小，避免脚离地/地面「变形」错觉
    const origin = bones.spine
      ? worldPos(bones.spine)
      : bones.abdomen
        ? worldPos(bones.abdomen)
        : worldPos(root).add(new THREE.Vector3(0, 1.15, 0));
    const dir = target.clone().sub(origin).applyQuaternion(qInv);
    if (dir.lengthSq() < 1e-6) return {};
    dir.normalize();
    const x = clampJoint("spineX", rad2deg(Math.atan2(-dir.y, dir.z)) * 0.28);
    const y = clampJoint("spineY", rad2deg(Math.atan2(dir.x, dir.z)) * 0.28);
    const abdomenX = clampJoint("abdomenX", Math.max(-18, Math.min(18, x * 0.4)));
    return { spineX: x, spineY: y, abdomenX };
  }

  const isArm = chain === "lArm" || chain === "rArm";
  const left = chain === "lArm" || chain === "lLeg";
  const originKey = isArm ? (left ? "lShoulder" : "rShoulder") : (left ? "lHip" : "rHip");
  const midKey = isArm ? (left ? "lElbow" : "rElbow") : (left ? "lKnee" : "rKnee");
  const endKey = isArm ? (left ? "lWrist" : "rWrist") : (left ? "lAnkle" : "rAnkle");
  const origin = bones[originKey];
  const mid = bones[midKey];
  const end = bones[endKey];
  if (!origin) return {};

  const o = worldPos(origin);
  const upper = mid ? o.distanceTo(worldPos(mid)) : (isArm ? 0.28 : 0.34);
  const lower = mid && end ? worldPos(mid).distanceTo(worldPos(end)) : (isArm ? 0.26 : 0.32);
  const reach = Math.max(0.08, upper + lower);
  const minReach = Math.abs(upper - lower) + 0.02;

  const dirWorld = target.clone().sub(o);
  const dist = Math.max(minReach, Math.min(reach * 0.98, dirWorld.length()));
  const dir = dirWorld.clone().applyQuaternion(qInv);
  if (dir.lengthSq() < 1e-8) return {};
  dir.normalize();

  const rawPitch = rad2deg(Math.atan2(dir.z, -dir.y));
  // 臂：负 shoulderX = 前伸；腿：正 hipX = 前踢。同一 atan2 对臂要取反。
  const pitch = isArm ? -rawPitch : rawPitch;
  // 胶囊解剖左在 -X，Mixamo/BodyKun 解剖左在 +X；侧摆符号必须跟实际肩位走
  const roll = rad2deg(
    Math.atan2(isMixamoLateral(root) ? dir.x : -dir.x, Math.max(1e-4, Math.hypot(dir.y, dir.z))),
  );
  const cosE = (upper * upper + lower * lower - dist * dist) / (2 * upper * lower);
  const interior = Math.acos(Math.max(-1, Math.min(1, cosE)));
  const bend = 180 - (interior * 180) / Math.PI;

  if (isArm) {
    if (left) {
      return {
        lShoulderX: clampJoint("lShoulderX", pitch),
        lShoulderZ: clampJoint("lShoulderZ", roll),
        lElbowX: clampJoint("lElbowX", bend),
      };
    }
    return {
      rShoulderX: clampJoint("rShoulderX", pitch),
      rShoulderZ: clampJoint("rShoulderZ", roll),
      rElbowX: clampJoint("rElbowX", bend),
    };
  }
  if (left) {
    return {
      lHipX: clampJoint("lHipX", pitch),
      lHipZ: clampJoint("lHipZ", roll),
      lKneeX: clampJoint("lKneeX", bend),
    };
  }
  return {
    rHipX: clampJoint("rHipX", pitch),
    rHipZ: clampJoint("rHipZ", roll),
    rKneeX: clampJoint("rKneeX", bend),
  };
}

/**
 * 单关节 FK：只改点中的那一节（大腿/小腿/上臂/前臂），不整肢重解。
 * 肩/髋：朝向目标；肘/膝：铰链弯曲使远端指向目标。
 */
export function solveSegmentFk(
  root: THREE.Object3D,
  boneKey: string,
  target: THREE.Vector3,
  _pose: JointPose,
): Partial<JointPose> {
  const region = boneKeyToRegion(boneKey);
  if (!region) return {};
  const bones = getPoseBones(root);
  const qInv = root.getWorldQuaternion(new THREE.Quaternion()).invert();
  const rad2deg = (r: number) => (r * 180) / Math.PI;
  const left = boneKey.startsWith("l");
  const mixamo = isMixamoLateral(root);

  if (region === "shoulder" || region === "hip") {
    const bone = bones[boneKey];
    if (!bone) return {};
    const o = worldPos(bone);
    const dir = target.clone().sub(o).applyQuaternion(qInv);
    if (dir.lengthSq() < 1e-8) return {};
    dir.normalize();
    const rawPitch = rad2deg(Math.atan2(dir.z, -dir.y));
    const pitch = region === "shoulder" ? -rawPitch : rawPitch;
    const roll = rad2deg(
      Math.atan2(mixamo ? dir.x : -dir.x, Math.max(1e-4, Math.hypot(dir.y, dir.z))),
    );
    if (region === "shoulder") {
      if (left) {
        return {
          lShoulderX: clampJoint("lShoulderX", pitch),
          lShoulderZ: clampJoint("lShoulderZ", roll),
        };
      }
      return {
        rShoulderX: clampJoint("rShoulderX", pitch),
        rShoulderZ: clampJoint("rShoulderZ", roll),
      };
    }
    if (left) {
      return {
        lHipX: clampJoint("lHipX", pitch),
        lHipZ: clampJoint("lHipZ", roll),
      };
    }
    return {
      rHipX: clampJoint("rHipX", pitch),
      rHipZ: clampJoint("rHipZ", roll),
    };
  }

  if (region === "elbow" || region === "knee") {
    const proxKey =
      region === "elbow"
        ? left
          ? "lShoulder"
          : "rShoulder"
        : left
          ? "lHip"
          : "rHip";
    const mid = bones[boneKey];
    const prox = bones[proxKey];
    if (!mid) return {};
    const b = worldPos(mid);
    const a = prox ? worldPos(prox) : b.clone().add(new THREE.Vector3(0, 0.3, 0));
    const ba = a.clone().sub(b).normalize();
    const bc = target.clone().sub(b);
    if (bc.lengthSq() < 1e-8) return {};
    bc.normalize();
    const cos = Math.max(-1, Math.min(1, ba.dot(bc)));
    // 伸直 ≈ 180° → bend 0；完全折叠 → bend 大
    const bend = clampJoint(
      region === "elbow" ? (left ? "lElbowX" : "rElbowX") : left ? "lKneeX" : "rKneeX",
      rad2deg(Math.PI - Math.acos(cos)),
    );
    if (region === "elbow") {
      return left ? { lElbowX: bend } : { rElbowX: bend };
    }
    return left ? { lKneeX: bend } : { rKneeX: bend };
  }

  return {};
}

function recordGLBTPose(bones: GLBBoneMap): Record<string, THREE.Quaternion> {
  const identity: Record<string, THREE.Quaternion> = {};
  for (const [key, bone] of Object.entries(bones)) {
    if (bone) identity[key] = bone.quaternion.clone();
  }
  return identity;
}

function applyBoneDelta(
  bone: THREE.Object3D | undefined,
  identity: Record<string, THREE.Quaternion>,
  key: string,
  xDeg: number,
  yDeg: number,
  zDeg: number,
  /** ★ 旋转顺序（2026-10-05）：肢体用 "YXZ"（先扭转再摆动），
   *  因为侧举 Z→±90° 时 "XYZ" 会让 X/Y 轴退化重合（万向节锁）导致肩部突然翻转；
   *  躯干/头保持 "XYZ"。Y=0 时两种顺序结果完全相同 ⇒ 旧预设零回归。 */
  order: "XYZ" | "YXZ" = "XYZ",
) {
  if (!bone) return;
  const rest = identity[key];
  if (rest) bone.quaternion.copy(rest);
  else bone.quaternion.identity();
  if (xDeg === 0 && yDeg === 0 && zDeg === 0) return;
  bone.quaternion.multiply(
    new THREE.Quaternion().setFromEuler(
      new THREE.Euler(deg(xDeg), deg(yDeg), deg(zDeg), order),
    ),
  );
}

/**
 * 把 JointPose 旋转叠加到 GLB 骨架上（retarget）。
 *
 * Mixamo：Shoulder=锁骨，Arm=上臂，ForeArm=前臂。
 * 前后/侧举主要打在 Arm/UpLeg，锁骨只跟一点侧摆。
 *
 * 注意：BodyKun rest 左右臂已镜像，JointPose 右臂侧摆也是镜像语义（rShoulderZ 外展为负）。
 * 两边符号必须与左侧同一套（neg X、Z 原样），不能再翻一次，否则对称姿势会坏。
 */
export function applyPoseToGLB(
  bones: GLBBoneMap,
  pose: JointPose,
  identity: Record<string, THREE.Quaternion>,
): void {
  // 统一入口：预设已是终态，不再二次 chain（避免坐姿/抱臂被拧坏）
  const resolved = resolveClampPose(mergePose(defaultPose(), pose));
  applyPoseToGLBResolved(bones, resolved, identity);
}

/**
 * 已处理（chain + clamp 已过）的 pose → GLB 骨架直接应用。
 * 用于 applyPose 的统一管线入口，避免在 GLB 内部重复 chain/clamp。
 * 也可独立调用——直接传入 defaultPose() + 用户修改值的合并结果。
 */
export function applyPoseToGLBResolved(
  bones: GLBBoneMap,
  pose: JointPose,
  identity: Record<string, THREE.Quaternion>,
): void {
  const p = pose;
  const neg = (v: number) => -v;

  // 腰部绝不能打到 Hips，否则脚离地、地面像被拽变形
  const abdomenBone =
    bones.abdomen && bones.abdomen !== bones.hips
      ? bones.abdomen
      : bones.spine && bones.spine !== bones.hips
        ? bones.spine
        : bones.spine2;
  // ★ 2026-10-05 躯干/头 X 轴符号修正：去 neg ⇒ 正 = 前倾（与 UI 标签一致）。
  //   实测依据（bodykun.glb + 脚趾朝 +Z 判前方）：原实现 +30° 让头顶朝 -Z（后）移动，
  //   于是「鞠躬」预设（躯干全正值）实际是**后仰**——这是「姿势不像人」的直接来源之一。
  applyBoneDelta(abdomenBone, identity, "abdomen", p.abdomenX, p.abdomenY, p.abdomenZ);
  applyBoneDelta(bones.spine2 || bones.spine, identity, bones.spine2 ? "spine2" : "spine", p.spineX, p.spineY, p.spineZ);
  // neck 承担头部旋转的一半，让脖子蒙皮平滑过渡，避免头转脖子不跟导致"颈子凸出断裂"
  applyBoneDelta(bones.neck, identity, "neck", p.headX * 0.5, p.headY * 0.5, p.headZ * 0.5);
  applyBoneDelta(bones.head, identity, "head", p.headX * 0.5, p.headY * 0.5, p.headZ * 0.5);

  // ★ 2026-10-05 补内旋（Y 轴）+ 肢体改 "YXZ" 顺序（消万向节锁）：
  //   此前 lArm/lHip 的 Y 恒 0 ⇒ 肘弯曲平面锁死；现接 lShoulderY / lHipY / lElbowY。
  //   侧举 Z 接近 ±90° 时 "XYZ" 会退化为二轴，改 "YXZ" 后无翻转。
  applyBoneDelta(bones.lShoulder, identity, "lShoulder", 0, 0, p.lShoulderZ * 0.35);
  applyBoneDelta(bones.lArm, identity, "lArm",
                 neg(p.lShoulderX), p.lShoulderY, p.lShoulderZ, "YXZ");
  applyBoneDelta(bones.lForeArm, identity, "lForeArm", p.lElbowX, p.lElbowY, 0, "YXZ");
  applyBoneDelta(bones.lWrist, identity, "lWrist", p.lWristX, 0, 0, "YXZ");

  applyBoneDelta(bones.rShoulder, identity, "rShoulder", 0, 0, p.rShoulderZ * 0.35);
  applyBoneDelta(bones.rArm, identity, "rArm",
                 neg(p.rShoulderX), p.rShoulderY, p.rShoulderZ, "YXZ");
  applyBoneDelta(bones.rForeArm, identity, "rForeArm", p.rElbowX, p.rElbowY, 0, "YXZ");
  applyBoneDelta(bones.rWrist, identity, "rWrist", p.rWristX, 0, 0, "YXZ");

  applyBoneDelta(bones.lHip, identity, "lHip", neg(p.lHipX), p.lHipY, p.lHipZ, "YXZ");
  applyBoneDelta(bones.lKnee, identity, "lKnee", p.lKneeX, 0, 0, "YXZ");
  applyBoneDelta(bones.lAnkle, identity, "lAnkle", p.lAnkleX, 0, 0, "YXZ");

  applyBoneDelta(bones.rHip, identity, "rHip", neg(p.rHipX), p.rHipY, p.rHipZ, "YXZ");
  applyBoneDelta(bones.rKnee, identity, "rKnee", p.rKneeX, 0, 0, "YXZ");
  applyBoneDelta(bones.rAnkle, identity, "rAnkle", p.rAnkleX, 0, 0, "YXZ");
}

let _sharedGLTFLoader: GLTFLoader | null = null;
function getGLTFLoader(): GLTFLoader {
  if (!_sharedGLTFLoader) _sharedGLTFLoader = new GLTFLoader();
  return _sharedGLTFLoader;
}

/**
 * 保留 vinchau BodyKun/BodyChan 原材质与分段网格。
 * 旧版会重写 UV 并贴生成等高线，把真实绘制人偶刷成早期程序化素模。
 */
function prepareBodyFigureMeshes(scene: THREE.Object3D) {
  scene.traverse((obj) => {
    const m = obj as THREE.Mesh;
    if (!m.isMesh) return;
    m.userData.sharedTemplate = true;
    m.castShadow = true;
    m.receiveShadow = true;
  });
}

/** 缓存原始 GLTF scene（URL → 未处理的原始 Object3D） */
const _glbSceneCache = new Map<string, Promise<THREE.Object3D>>();
/** 缓存已归一化缩放的模板；多 actor 只 clone */
const _glbProcessedCache = new Map<string, Promise<THREE.Object3D>>();

function loadRawGLBScene(url: string): Promise<THREE.Object3D> {
  const cached = _glbSceneCache.get(url);
  if (cached) return cached;
  const task = new Promise<THREE.Object3D>((resolve, reject) => {
    getGLTFLoader().load(url, (gltf) => resolve(gltf.scene), undefined, reject);
  }).catch((err) => {
    _glbSceneCache.delete(url);
    throw err;
  });
  _glbSceneCache.set(url, task);
  return task;
}

function loadProcessedGLBTemplate(url: string): Promise<THREE.Object3D> {
  const hit = _glbProcessedCache.get(url);
  if (hit) return hit;
  const task = loadRawGLBScene(url)
    .then((rawScene) => {
      const scene = cloneSkinned(rawScene);
      scene.name = "glb_tpl_" + (url.split("/").pop()?.replace(/\.glb$/i, "") ?? "");
      scene.traverse((obj) => {
        const m = obj as THREE.Mesh;
        if (!m.isMesh || !m.material) return;
        m.material = Array.isArray(m.material)
          ? m.material.map((x) => x.clone())
          : m.material.clone();
        m.castShadow = true;
        m.receiveShadow = true;
      });
      prepareBodyFigureMeshes(scene);

      // 归一化基准 = GLB 素体实测原生身高（bodykun/bodychan 均为 1.7000m，
      // 测量脚本 .workbuddy/tmp/glb_total_height.py）。
      // 2026-10-13 用户授权解冻修复：旧值 1.815 比原生身高高 6.8%，
      // 导致所有体型统一被放大（用户反馈「全部偏大」）；回落到原生 1.70。
      // 注意：ACTOR_PRESETS / VARIANT_SCALE 是相对倍率，随基准等比生效，无需联动改。
      const TARGET_HEIGHT = 1.70;
      const fitBox = new THREE.Box3().setFromObject(scene);
      const fitSize = new THREE.Vector3();
      fitBox.getSize(fitSize);
      if (fitSize.y > 1e-6) {
        scene.scale.setScalar(TARGET_HEIGHT / fitSize.y);
      }
      scene.updateMatrixWorld(true);
      fitBox.setFromObject(scene);
      scene.position.y -= fitBox.min.y;
      scene.updateMatrixWorld(true);
      return scene;
    })
    .catch((err) => {
      _glbProcessedCache.delete(url);
      throw err;
    });
  _glbProcessedCache.set(url, task);
  return task;
}

export type LoadGLBOptions = {
  wireframeOverlay?: boolean;
  overrideColor?: string;
  scale?: number;
};

/** 空闲时预热 BodyKun/BodyChan，缩短首次进 3D 的等待 */
export function preloadBodyFigures(variants: Array<"male_std" | "female_std"> = ["male_std", "female_std"]): void {
  for (const v of variants) {
    void loadProcessedGLBTemplate(bodyFigureUrl(v)).catch(() => {
      /* 预热失败不影响功能 */
    });
  }
}

export function loadGLBRiggedHumanoid(
  url: string,
  options?: LoadGLBOptions,
): Promise<THREE.Group> {
  return loadProcessedGLBTemplate(url).then((template) => {
    const scene = cloneSkinned(template);
    scene.name = "glb_scene_" + (url.split("/").pop()?.replace(/\.glb$/i, "") ?? "");
    const extraScale = options?.scale ?? 1.0;
    if (extraScale !== 1.0) {
      scene.scale.multiplyScalar(extraScale);
      scene.updateMatrixWorld(true);
      const fitBox = new THREE.Box3().setFromObject(scene);
      scene.position.y -= fitBox.min.y;
    }

    const boneMap = buildGLBBoneMap(scene);
    const identity = recordGLBTPose(boneMap);

    const root = new THREE.Group();
    root.add(scene);
    root.userData.glBones = boneMap;
    root.userData.glBonesIdentity = identity;
    root.userData.sourceUrl = url;

    return root;
  });
}

/**
 * 将 GLB 模型异步附加到已有的胶囊骨架人模上：
 *  - 先隐藏胶囊骨架的可见 Mesh（保留 bones 引用用于调试）
 *  - 将 GLB scene 附加到原 root，复制 glBones / glBonesIdentity
 *  - 最后重新 applyPose 让 GLB 骨架获得当前姿势
 * 这样 Stage3D 侧的同步调用 makeRiggedHumanoid 不受影响，
 * 但用户会在 GLB 加载完成后看到更精细的外观替换。
 */
export function attachGLBToHumanoid(
  root: THREE.Group,
  url: string,
  options?: LoadGLBOptions,
): void {
  if (root.userData.glbLoaded || root.userData._glb_attaching) return;
  root.userData._glb_attaching = true;

  const tryAttach = (attempt: number) => {
    loadGLBRiggedHumanoid(url, options)
      .then((glbRoot) => {
      const glbScene = glbRoot.children[0];
      if (!glbScene) {
        root.userData._glb_attaching = false;
        return;
      }
      if (root.userData._disposed) {
        root.userData._glb_attaching = false;
        return;
      }
      root.children.forEach((ch) => {
        if (ch !== glbScene) ch.visible = false;
      });
      root.add(glbScene);
      root.userData.glBones = glbRoot.userData.glBones;
      root.userData.glBonesIdentity = glbRoot.userData.glBonesIdentity;
      root.userData.glbLoaded = true;
      root.userData._glb_attaching = false;
      bindHumanoidPickData(root);
      applyPose(root, root.userData._lastPose || defaultPose());
      console.log("[RiggedHumanoid] GLB attached:", url, {
        foundBones: Object.values(root.userData.glBones as object[]).filter(Boolean).length,
      });
    })
      .catch((err) => {
      if (root.userData._disposed) {
        root.userData._glb_attaching = false;
        return;
      }
      if (attempt < 1) {
        setTimeout(() => tryAttach(attempt + 1), 450);
        return;
      }
      // 已移除胶囊素模 fallback：GLB 加载失败时不再回退显示几何拼装素模，
      // 只隐藏胶囊骨架网格（bones 仍保留，供拾取/姿势驱动使用）。
      root.traverse((ch) => {
        const m = ch as THREE.Mesh;
        if (m.isMesh) m.visible = false;
      });
      console.warn("[RiggedHumanoid] GLB attach failed, capsule fallback removed:", err?.message || err);
      root.userData._glb_attaching = false;
    });
  };
  tryAttach(0);
}

/* END GLUE */

// ─── BVH 骨骼动画导出 ────────────────────────────────────────────

type BVHJointDef = {
  name: string;
  offset: [number, number, number];
  channels: string[]; // e.g. ["Xposition","Yposition","Zposition","Zrotation","Xrotation","Yrotation"]
};

const BVH_OFFSETS: Record<string, [number, number, number]> = {
  Hips: [0, 1.0, 0],
  Spine: [0, 0.35, 0],
  Chest: [0, 0.25, 0],
  Neck: [0, 0.18, 0],
  Head: [0, 0.15, 0],
  LeftShoulder: [-0.18, 0.12, 0],
  LeftElbow: [-0.28, 0, 0],
  LeftWrist: [-0.26, 0, 0],
  RightShoulder: [0.18, 0.12, 0],
  RightElbow: [0.28, 0, 0],
  RightWrist: [0.26, 0, 0],
  LeftHip: [-0.1, 0, 0],
  LeftKnee: [0, -0.34, 0],
  LeftAnkle: [0, -0.32, 0],
  RightHip: [0.1, 0, 0],
  RightKnee: [0, -0.34, 0],
  RightAnkle: [0, -0.32, 0],
};

/** 把 JointPose 单帧数据展开为每个 BVH 关节的旋转角数组（ZYX 顺序，匹配 BVH 标准） */
function poseToBVHChannels(p: JointPose): Record<string, [number, number, number]> {
  const neg = (v: number) => -v;
  return {
    Hips: [0, p.spineY * 0.3, 0],
    Spine: [0, neg(p.spineY) * 0.7, neg(p.spineX)],
    Chest: [0, neg(p.spineY) * 0.3, neg(p.spineX) * 0.5],
    Neck: [0, p.headY * 0.3, 0],
    Head: [0, p.headY * 0.7, neg(p.headX)],
    LeftShoulder: [neg(p.lShoulderZ), 0, neg(p.lShoulderX)],
    LeftElbow: [0, 0, neg(p.lElbowX)],
    LeftWrist: [0, 0, neg(p.lWristX)],
    RightShoulder: [p.rShoulderZ, 0, neg(p.rShoulderX)],
    RightElbow: [0, 0, neg(p.rElbowX)],
    RightWrist: [0, 0, neg(p.rWristX)],
    LeftHip: [neg(p.lHipZ), 0, neg(p.lHipX)],
    LeftKnee: [0, 0, neg(p.lKneeX)],
    LeftAnkle: [0, 0, neg(p.lAnkleX)],
    RightHip: [p.rHipZ, 0, neg(p.rHipX)],
    RightKnee: [0, 0, neg(p.rKneeX)],
    RightAnkle: [0, 0, neg(p.rAnkleX)],
  };
}

/**
 * 导出标准 BVH 文本（Blender/Mixamo/Cascadeur 可直接导入）。
 * @param frames 逐帧 JointPose（通常是 MotionPreset 或关键帧采样）
 * @param rootPositions Hips 世界位移序列，null 则全部 (0,0,0)
 * @param fps 采样帧率
 */
export function exportBVH(
  frames: JointPose[],
  rootPositions: [number, number, number][] | null,
  fps = 30,
): string {
  if (frames.length === 0) return "";
  const nFrames = frames.length;

  // ── HIERARCHY ──
  const hi = [
    "HIERARCHY",
    "ROOT Hips",
    "{",
    `    OFFSET ${BVH_OFFSETS.Hips.join(" ")}`,
    "    CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation",
    "    JOINT Spine",
    "    {",
    `        OFFSET ${BVH_OFFSETS.Spine.join(" ")}`,
    "        CHANNELS 3 Zrotation Xrotation Yrotation",
    "        JOINT Chest",
    "        {",
    `            OFFSET ${BVH_OFFSETS.Chest.join(" ")}`,
    "            CHANNELS 3 Zrotation Xrotation Yrotation",
    "            JOINT Neck",
    "            {",
    `                OFFSET ${BVH_OFFSETS.Neck.join(" ")}`,
    "                CHANNELS 3 Zrotation Xrotation Yrotation",
    "                JOINT Head",
    "                {",
    `                    OFFSET ${BVH_OFFSETS.Head.join(" ")}`,
    "                    CHANNELS 3 Zrotation Xrotation Yrotation",
    "                    End Site",
    "                    { OFFSET 0 0.22 0 }",
    "                }",
    "            }",
    "        }",
    "    }",
    "    JOINT LeftShoulder",
    "    {",
    `        OFFSET ${BVH_OFFSETS.LeftShoulder.join(" ")}`,
    "        CHANNELS 3 Zrotation Xrotation Yrotation",
    "        JOINT LeftElbow",
    "        {",
    `            OFFSET ${BVH_OFFSETS.LeftElbow.join(" ")}`,
    "            CHANNELS 3 Zrotation Xrotation Yrotation",
    "            JOINT LeftWrist",
    "            {",
    `                OFFSET ${BVH_OFFSETS.LeftWrist.join(" ")}`,
    "                CHANNELS 3 Zrotation Xrotation Yrotation",
    "                End Site",
    "                { OFFSET -0.15 0 0 }",
    "            }",
    "        }",
    "    }",
    "    JOINT RightShoulder",
    "    {",
    `        OFFSET ${BVH_OFFSETS.RightShoulder.join(" ")}`,
    "        CHANNELS 3 Zrotation Xrotation Yrotation",
    "        JOINT RightElbow",
    "        {",
    `            OFFSET ${BVH_OFFSETS.RightElbow.join(" ")}`,
    "            CHANNELS 3 Zrotation Xrotation Yrotation",
    "            JOINT RightWrist",
    "            {",
    `                OFFSET ${BVH_OFFSETS.RightWrist.join(" ")}`,
    "                CHANNELS 3 Zrotation Xrotation Yrotation",
    "                End Site",
    "                { OFFSET 0.15 0 0 }",
    "            }",
    "        }",
    "    }",
    "    JOINT LeftHip",
    "    {",
    `        OFFSET ${BVH_OFFSETS.LeftHip.join(" ")}`,
    "        CHANNELS 3 Zrotation Xrotation Yrotation",
    "        JOINT LeftKnee",
    "        {",
    `            OFFSET ${BVH_OFFSETS.LeftKnee.join(" ")}`,
    "            CHANNELS 3 Zrotation Xrotation Yrotation",
    "            JOINT LeftAnkle",
    "            {",
    `                OFFSET ${BVH_OFFSETS.LeftAnkle.join(" ")}`,
    "                CHANNELS 3 Zrotation Xrotation Yrotation",
    "                End Site",
    "                { OFFSET 0 -0.06 -0.12 }",
    "            }",
    "        }",
    "    }",
    "    JOINT RightHip",
    "    {",
    `        OFFSET ${BVH_OFFSETS.RightHip.join(" ")}`,
    "        CHANNELS 3 Zrotation Xrotation Yrotation",
    "        JOINT RightKnee",
    "        {",
    `            OFFSET ${BVH_OFFSETS.RightKnee.join(" ")}`,
    "            CHANNELS 3 Zrotation Xrotation Yrotation",
    "            JOINT RightAnkle",
    "            {",
    `                OFFSET ${BVH_OFFSETS.RightAnkle.join(" ")}`,
    "                CHANNELS 3 Zrotation Xrotation Yrotation",
    "                End Site",
    "                { OFFSET 0 -0.06 -0.12 }",
    "            }",
    "        }",
    "    }",
    "}",
  ];

  // ── MOTION ──
  const motion: string[] = [
    "MOTION",
    `Frames: ${nFrames}`,
    `Frame Time: ${(1 / fps).toFixed(6)}`,
  ];

  for (let fi = 0; fi < nFrames; fi++) {
    const p = frames[fi];
    const ch = poseToBVHChannels(p);
    const pos = rootPositions?.[fi] ?? [0, 0, 0];
    motion.push(
      [
        `${pos[0].toFixed(4)} ${pos[1].toFixed(4)} ${pos[2].toFixed(4)}`,
        `${ch.Hips[0].toFixed(4)} ${ch.Hips[1].toFixed(4)} ${ch.Hips[2].toFixed(4)}`,
        `${ch.Spine[0].toFixed(4)} ${ch.Spine[1].toFixed(4)} ${ch.Spine[2].toFixed(4)}`,
        `${ch.Chest[0].toFixed(4)} ${ch.Chest[1].toFixed(4)} ${ch.Chest[2].toFixed(4)}`,
        `${ch.Neck[0].toFixed(4)} ${ch.Neck[1].toFixed(4)} ${ch.Neck[2].toFixed(4)}`,
        `${ch.Head[0].toFixed(4)} ${ch.Head[1].toFixed(4)} ${ch.Head[2].toFixed(4)}`,
        `${ch.LeftShoulder[0].toFixed(4)} ${ch.LeftShoulder[1].toFixed(4)} ${ch.LeftShoulder[2].toFixed(4)}`,
        `${ch.LeftElbow[0].toFixed(4)} ${ch.LeftElbow[1].toFixed(4)} ${ch.LeftElbow[2].toFixed(4)}`,
        `${ch.LeftWrist[0].toFixed(4)} ${ch.LeftWrist[1].toFixed(4)} ${ch.LeftWrist[2].toFixed(4)}`,
        `${ch.RightShoulder[0].toFixed(4)} ${ch.RightShoulder[1].toFixed(4)} ${ch.RightShoulder[2].toFixed(4)}`,
        `${ch.RightElbow[0].toFixed(4)} ${ch.RightElbow[1].toFixed(4)} ${ch.RightElbow[2].toFixed(4)}`,
        `${ch.RightWrist[0].toFixed(4)} ${ch.RightWrist[1].toFixed(4)} ${ch.RightWrist[2].toFixed(4)}`,
        `${ch.LeftHip[0].toFixed(4)} ${ch.LeftHip[1].toFixed(4)} ${ch.LeftHip[2].toFixed(4)}`,
        `${ch.LeftKnee[0].toFixed(4)} ${ch.LeftKnee[1].toFixed(4)} ${ch.LeftKnee[2].toFixed(4)}`,
        `${ch.LeftAnkle[0].toFixed(4)} ${ch.LeftAnkle[1].toFixed(4)} ${ch.LeftAnkle[2].toFixed(4)}`,
        `${ch.RightHip[0].toFixed(4)} ${ch.RightHip[1].toFixed(4)} ${ch.RightHip[2].toFixed(4)}`,
        `${ch.RightKnee[0].toFixed(4)} ${ch.RightKnee[1].toFixed(4)} ${ch.RightKnee[2].toFixed(4)}`,
        `${ch.RightAnkle[0].toFixed(4)} ${ch.RightAnkle[1].toFixed(4)} ${ch.RightAnkle[2].toFixed(4)}`,
      ].join(" "),
    );
  }

  return [...hi, ...motion].join("\n");
}

/** 把 MotionPreset 展开为指定时长的帧序列（可直接喂给 exportBVH） */
export function sampleMotionFrames(
  motion: MotionPreset | MotionPreset[],
  durationMs: number,
  fps = 30,
): { pose: JointPose[]; rootPositions: [number, number, number][] } {
  const stepMs = 1000 / fps;
  const count = Math.max(2, Math.ceil(durationMs / stepMs));
  const list = Array.isArray(motion) ? motion : [motion];
  const poses: JointPose[] = [];
  const roots: [number, number, number][] = [];
  for (let i = 0; i < count; i++) {
    const t = i * stepMs;
    const s = sampleCompositeMotion(list, t);
    poses.push(s.pose);
    roots.push(s.rootOffset);
  }
  return { pose: poses, rootPositions: roots };
}