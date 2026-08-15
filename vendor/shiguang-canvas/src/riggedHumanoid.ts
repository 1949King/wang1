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

/** 变更此值会强制 Stage3D 重建旧场景中的人模网格 */
export const RIG_MESH_STYLE = "bodykun-v4";

/** 女体用 BodyChan，其余体型用 BodyKun（儿童/胖瘦靠 heightScale） */
export function bodyFigureUrl(variant: HumanVariant = "male_std"): string {
  return variant === "female_std" ? "/models/bodychan.glb" : "/models/bodykun.glb";
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

/** 关节角（度）——导演摆姿，非完整 IK */
export type JointPose = {
  spineX: number;
  spineY: number;
  abdomenX: number;
  headX: number;
  headY: number;
  lShoulderX: number;
  lShoulderZ: number;
  lElbowX: number;
  lWristX: number;
  rShoulderX: number;
  rShoulderZ: number;
  rElbowX: number;
  rWristX: number;
  lHipX: number;
  lHipZ: number;
  lKneeX: number;
  lAnkleX: number;
  rHipX: number;
  rHipZ: number;
  rKneeX: number;
  rAnkleX: number;
};

export const JOINT_LABELS: { key: keyof JointPose; label: string; min: number; max: number }[] = [
  { key: "spineX", label: "胸俯仰", min: -40, max: 40 },
  { key: "spineY", label: "胸扭转", min: -50, max: 50 },
  { key: "abdomenX", label: "腹俯仰", min: -35, max: 35 },
  { key: "headX", label: "头俯仰", min: -45, max: 45 },
  { key: "headY", label: "头左右", min: -70, max: 70 },
  { key: "lShoulderX", label: "左臂前后", min: -170, max: 80 },
  { key: "lShoulderZ", label: "左臂侧举", min: -20, max: 170 },
  { key: "lElbowX", label: "左肘", min: 0, max: 145 },
  { key: "lWristX", label: "左腕", min: -60, max: 60 },
  { key: "rShoulderX", label: "右臂前后", min: -170, max: 80 },
  { key: "rShoulderZ", label: "右臂侧举", min: -170, max: 20 },
  { key: "rElbowX", label: "右肘", min: 0, max: 145 },
  { key: "rWristX", label: "右腕", min: -60, max: 60 },
  { key: "lHipX", label: "左腿前后", min: -100, max: 90 },
  { key: "lHipZ", label: "左腿侧展", min: -20, max: 80 },
  { key: "lKneeX", label: "左膝", min: 0, max: 140 },
  { key: "lAnkleX", label: "左踝", min: -40, max: 40 },
  { key: "rHipX", label: "右腿前后", min: -100, max: 90 },
  { key: "rHipZ", label: "右腿侧展", min: -80, max: 20 },
  { key: "rKneeX", label: "右膝", min: 0, max: 140 },
  { key: "rAnkleX", label: "右踝", min: -40, max: 40 },
];

export function defaultPose(): JointPose {
  return {
    spineX: 0,
    spineY: 0,
    abdomenX: 0,
    headX: 0,
    headY: 0,
    lShoulderX: 6,
    lShoulderZ: 14,
    lElbowX: 10,
    lWristX: 0,
    rShoulderX: 6,
    rShoulderZ: -14,
    rElbowX: 10,
    rWristX: 0,
    lHipX: 3,
    lHipZ: 4,
    lKneeX: 6,
    lAnkleX: 0,
    rHipX: 3,
    rHipZ: -4,
    rKneeX: 6,
    rAnkleX: 0,
  };
}

export type PosePresetId =
  | "idle"
  | "wave"
  | "think"
  | "point"
  | "hands_hips"
  | "cross_arms"
  | "sit"
  | "fight"
  | "bow"
  | "jump_kick"
  | "sword_up"
  | "aim"
  | "staff"
  | "phone"
  | "lean_wall"
  | "hands_pockets"
  | "stretch"
  | "yawn"
  | "cheer"
  | "sad"
  | "surprised"
  | "punch"
  | "block"
  | "throw"
  | "crouch"
  | "step_turn";

export const POSE_PRESETS: { id: PosePresetId; label: string; pose: Partial<JointPose> }[] = [
  { id: "idle", label: "站立", pose: defaultPose() },
  {
    id: "wave",
    label: "挥手",
    pose: {
      ...defaultPose(),
      rShoulderZ: -120,
      rShoulderX: -25,
      rElbowX: 35,
      headY: -12,
    },
  },
  {
    id: "think",
    label: "思考",
    pose: {
      ...defaultPose(),
      rShoulderX: -75,
      rElbowX: 105,
      rWristX: 20,
      headX: 10,
      headY: 16,
      spineX: 5,
    },
  },
  {
    id: "point",
    label: "指向",
    pose: {
      ...defaultPose(),
      rShoulderX: -85,
      rShoulderZ: -18,
      rElbowX: 8,
      headY: -10,
    },
  },
  {
    id: "hands_hips",
    label: "叉腰",
    pose: {
      ...defaultPose(),
      lShoulderZ: 58,
      lElbowX: 98,
      rShoulderZ: -58,
      rElbowX: 98,
    },
  },
  {
    id: "cross_arms",
    label: "抱臂",
    pose: {
      ...defaultPose(),
      lShoulderX: -58,
      lElbowX: 115,
      rShoulderX: -58,
      rElbowX: 115,
      spineX: 4,
    },
  },
  {
    id: "sit",
    label: "坐姿",
    pose: {
      ...defaultPose(),
      abdomenX: 10,
      spineX: 6,
      lHipX: 72,
      lKneeX: 90,
      rHipX: 72,
      rKneeX: 90,
      lShoulderX: -18,
      rShoulderX: -18,
    },
  },
  {
    id: "fight",
    label: "戒备",
    pose: {
      ...defaultPose(),
      spineX: -8,
      spineY: 12,
      lShoulderX: -100,
      lElbowX: 75,
      rShoulderX: -72,
      rElbowX: 58,
      lHipX: 28,
      rHipX: -18,
      headX: -4,
    },
  },
  {
    id: "bow",
    label: "鞠躬",
    pose: {
      ...defaultPose(),
      abdomenX: 28,
      spineX: 28,
      headX: 22,
      lShoulderX: 12,
      rShoulderX: 12,
    },
  },
  {
    id: "jump_kick",
    label: "飞踢",
    pose: {
      ...defaultPose(),
      spineX: -12,
      abdomenX: -8,
      lShoulderX: -40,
      lShoulderZ: 50,
      rShoulderX: -90,
      rElbowX: 40,
      lHipX: -20,
      lKneeX: 95,
      rHipX: 70,
      rKneeX: 20,
      headX: -8,
    },
  },
  {
    id: "sword_up",
    label: "举剑",
    pose: {
      ...defaultPose(),
      rShoulderX: -150,
      rShoulderZ: -35,
      rElbowX: 20,
      lShoulderX: -40,
      lElbowX: 50,
      spineY: -10,
      lHipX: 15,
      rHipX: -10,
    },
  },
  {
    id: "aim",
    label: "瞄准",
    pose: {
      ...defaultPose(),
      lShoulderX: -85,
      lElbowX: 15,
      rShoulderX: -85,
      rElbowX: 15,
      spineY: 18,
      lHipX: 35,
      rHipX: -25,
      headY: 10,
    },
  },
  {
    id: "staff",
    label: "持杖",
    pose: {
      ...defaultPose(),
      lShoulderX: -55,
      lElbowX: 70,
      rShoulderX: -70,
      rElbowX: 55,
      spineY: -8,
      lHipX: 12,
      rHipX: -8,
    },
  },
  // —— 日常类 ——
  {
    id: "phone",
    label: "看手机",
    pose: {
      ...defaultPose(),
      rShoulderX: -48,
      rShoulderZ: -12,
      rElbowX: 115,
      lShoulderX: -12,
      headX: 16,
      spineX: 8,
    },
  },
  {
    id: "lean_wall",
    label: "靠墙",
    pose: {
      ...defaultPose(),
      spineX: -18,
      abdomenX: -8,
      rShoulderX: -6,
      rShoulderZ: -22,
      rElbowX: 65,
      lShoulderX: 8,
      lHipX: 6,
      rHipX: -4,
    },
  },
  {
    id: "hands_pockets",
    label: "手插兜",
    pose: {
      ...defaultPose(),
      lShoulderX: 4,
      lShoulderZ: 22,
      lElbowX: 45,
      rShoulderX: 4,
      rShoulderZ: -22,
      rElbowX: 45,
      abdomenX: 6,
    },
  },
  {
    id: "stretch",
    label: "伸懒腰",
    pose: {
      ...defaultPose(),
      lShoulderX: -155,
      lShoulderZ: 42,
      lElbowX: 10,
      rShoulderX: -155,
      rShoulderZ: -42,
      rElbowX: 10,
      spineX: -14,
      headX: -12,
    },
  },
  {
    id: "yawn",
    label: "打哈欠",
    pose: {
      ...defaultPose(),
      lShoulderX: -120,
      lElbowX: 55,
      rShoulderX: -120,
      rElbowX: 55,
      headX: 28,
      headY: -18,
      spineX: 10,
    },
  },
  // —— 情绪类 ——
  {
    id: "cheer",
    label: "欢呼",
    pose: {
      ...defaultPose(),
      lShoulderX: -160,
      lShoulderZ: 60,
      lElbowX: 25,
      rShoulderX: -160,
      rShoulderZ: -60,
      rElbowX: 25,
      spineX: -6,
      headX: -6,
      lHipX: 10,
      rHipX: -10,
    },
  },
  {
    id: "sad",
    label: "垂头",
    pose: {
      ...defaultPose(),
      spineX: 18,
      abdomenX: 12,
      headX: 42,
      headY: -20,
      lShoulderX: 12,
      lShoulderZ: 10,
      rShoulderX: 12,
      rShoulderZ: -10,
    },
  },
  {
    id: "surprised",
    label: "惊讶",
    pose: {
      ...defaultPose(),
      headX: -14,
      headY: 6,
      lShoulderX: -38,
      lShoulderZ: 28,
      lElbowX: 58,
      rShoulderX: -38,
      rShoulderZ: -28,
      rElbowX: 58,
      spineX: -4,
    },
  },
  // —— 动作类 ——
  {
    id: "punch",
    label: "出拳",
    pose: {
      ...defaultPose(),
      spineY: 22,
      spineX: -6,
      rShoulderX: -10,
      rShoulderZ: -8,
      rElbowX: 6,
      lShoulderX: -95,
      lElbowX: 72,
      lHipX: 22,
      rHipX: -16,
      headY: 14,
    },
  },
  {
    id: "block",
    label: "格挡",
    pose: {
      ...defaultPose(),
      lShoulderX: -85,
      lShoulderZ: 32,
      lElbowX: 95,
      rShoulderX: -85,
      rShoulderZ: -32,
      rElbowX: 95,
      spineY: 8,
      lHipX: 18,
      rHipX: -12,
      headX: -6,
    },
  },
  {
    id: "throw",
    label: "投掷",
    pose: {
      ...defaultPose(),
      rShoulderX: -165,
      rShoulderZ: -40,
      rElbowX: 30,
      lShoulderX: 20,
      lShoulderZ: 12,
      rWristX: 18,
      spineY: -18,
      spineX: -8,
      lHipX: 22,
      rHipX: -14,
      headY: -10,
    },
  },
  // —— 姿态类 ——
  {
    id: "crouch",
    label: "蹲姿",
    pose: {
      ...defaultPose(),
      lHipX: 52,
      lKneeX: 95,
      rHipX: 52,
      rKneeX: 95,
      abdomenX: 12,
      spineX: 8,
      lShoulderX: -10,
      rShoulderX: -10,
      headX: 8,
    },
  },
  {
    id: "step_turn",
    label: "转身回头",
    pose: {
      ...defaultPose(),
      spineY: -32,
      headY: 42,
      spineX: 6,
      lShoulderX: -22,
      lShoulderZ: 18,
      rShoulderX: -22,
      rShoulderZ: -18,
      lHipX: 14,
      rHipX: -10,
    },
  },
];

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

/** 下蹲起身：髋膝大幅弯曲 → 逐步伸展（2s 完整蹲起周期） */
export const MOTION_SQUAT_RISE: MotionPreset = {
  id: "squat_rise",
  label: "下蹲起身",
  duration: 2000,
  easeFn: easeInOutCubic,
  keyframes: [
    { t: 0,    pose: { lHipX: -8, lKneeX: 4,  rHipX: -8, rKneeX: 4,  abdomenX: -2, spineX: 2 } },
    { t: 400,  pose: { lHipX: 15, lKneeX: 45, rHipX: 15, rKneeX: 45, abdomenX: 8,  spineX: -3 } },
    { t: 800,  pose: { lHipX: 45, lKneeX: 95, rHipX: 45, rKneeX: 95, abdomenX: 20, spineX: -12 } },
    { t: 1200, pose: { lHipX: 45, lKneeX: 95, rHipX: 45, rKneeX: 95, abdomenX: 20, spineX: -12 } },
    { t: 1600, pose: { lHipX: 15, lKneeX: 45, rHipX: 15, rKneeX: 45, abdomenX: 8,  spineX: -3 } },
    { t: 2000, pose: { lHipX: -8, lKneeX: 4,  rHipX: -8, rKneeX: 4,  abdomenX: -2, spineX: 2 } },
  ],
  rootOffset: [
    { t: 0,    pos: [0, 0, 0] },
    { t: 400,  pos: [0, -0.12, 0] },
    { t: 800,  pos: [0, -0.28, 0] },
    { t: 1200, pos: [0, -0.28, 0] },
    { t: 1600, pos: [0, -0.12, 0] },
    { t: 2000, pos: [0, 0, 0] },
  ],
};

/** 侧身倚靠：全身倾向一侧 + 重心转移 + 肩放松下垂（循环摆动 ≈ 5s） */
export const MOTION_LEAN_SIDE: MotionPreset = {
  id: "lean_side",
  label: "侧身倚靠",
  duration: 5000,
  easeFn: easeInOutSine,
  keyframes: [
    { t: 0,    pose: { lHipZ: 0,  rHipZ: 0,  spineY: 0,  spineX: 0,  lShoulderZ: 0, rShoulderZ: 0 } },
    { t: 1250, pose: { lHipZ: 8,  rHipZ: -12,spineY: -6, spineX: 2,  lShoulderZ: 10, rShoulderZ: -8 } },
    { t: 2500, pose: { lHipZ: 0,  rHipZ: 0,  spineY: 0,  spineX: 0,  lShoulderZ: 0, rShoulderZ: 0 } },
    { t: 3750, pose: { lHipZ: -12, rHipZ: 8,  spineY: 6,  spineX: 2,  lShoulderZ: -8, rShoulderZ: 10 } },
    { t: 5000, pose: { lHipZ: 0,  rHipZ: 0,  spineY: 0,  spineX: 0,  lShoulderZ: 0, rShoulderZ: 0 } },
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
      pose[k] = (pose[k] ?? 0) + sampled[k] - (defaultPose()[k] ?? 0);
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
  const neckJoint = jointBall(0.045);
  neckJoint.position.y = P.shoulderPadY + 0.3;
  spine.add(neckJoint);
  const head = new THREE.Group();
  head.position.y = P.shoulderPadY + 0.34;
  spine.add(head);
  const neck = taperedCylinderPart(0.048, 0.042, 0.06, body);
  neck.position.y = 0.03;
  head.add(neck);
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

  // 异步加载 BodyKun/BodyChan：灰白素体 + 黑网格 + 关节球，保留现有 JointPose
  attachGLBToHumanoid(root, bodyFigureUrl(variant));

  return root;
}

export function applyPose(root: THREE.Object3D, pose: JointPose) {
  // 保存最新姿势，供异步加载的 GLB 骨架使用
  root.userData._lastPose = pose;

  // 统一姿势管线：default + 链式联动 + 防穿模 → 应用到所有骨架通道
  const resolvedPose = resolveClampPose(resolveChainPose(mergePose(defaultPose(), pose)));

  // —— capsule 骨架（原有 21 关节）——
  const bones = root.userData.bones as BoneMap | undefined;
  if (bones) {
    const p = resolvedPose;
    const neg = (v: number) => -v;

    bones.abdomen.rotation.set(deg(neg(p.abdomenX)), 0, 0);
    bones.spine.rotation.set(deg(neg(p.spineX)), deg(p.spineY), 0);
    bones.head.rotation.set(deg(neg(p.headX)), deg(p.headY), 0);

    bones.lShoulder.rotation.set(deg(neg(p.lShoulderX)), 0, deg(p.lShoulderZ));
    bones.lElbow.rotation.set(deg(neg(p.lElbowX)), 0, 0);
    bones.lWrist.rotation.set(deg(neg(p.lWristX)), 0, 0);
    bones.rShoulder.rotation.set(deg(neg(p.rShoulderX)), 0, deg(p.rShoulderZ));
    bones.rElbow.rotation.set(deg(neg(p.rElbowX)), 0, 0);
    bones.rWrist.rotation.set(deg(neg(p.rWristX)), 0, 0);

    bones.lHip.rotation.set(deg(neg(p.lHipX)), 0, deg(p.lHipZ));
    bones.lKnee.rotation.set(deg(neg(p.lKneeX)), 0, 0);
    bones.lAnkle.rotation.set(deg(neg(p.lAnkleX)), 0, 0);
    bones.rHip.rotation.set(deg(neg(p.rHipX)), 0, deg(p.rHipZ));
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
  // 渐进抬升：用户把 shoulderZ 从 0 滑到 20° 时，实际值从 20° 连续降到原值，
  // 避免滑条拖到 0° 时上臂突然"弹开"的视觉跳变
  const pushShoulderOutSmooth = (shX: number, shZ: number, sign: 1 | -1): number => {
    if (shX < -15 || shX > 15) return shZ;
    const absZ = Math.abs(shZ);
    if (absZ >= 20) return shZ;
    // 渐进 ramp：absZ=0 → 输出 20°；absZ=10 → max(10, 15) = 15°；absZ=20 → 不推
    const floor = 20 - absZ * 0.5;
    const outAbs = Math.max(absZ, floor);
    return sign * outAbs;
  };
  p.lShoulderZ = pushShoulderOutSmooth(p.lShoulderX, p.lShoulderZ, 1);
  p.rShoulderZ = pushShoulderOutSmooth(p.rShoulderX, p.rShoulderZ, -1);

  return p;
}

/* ─────────────────────────────────────────────────────────────────────
 * 链式联动约束 / Kinematic Chain
 *
 * 让"主动关节"驱动"被动关节"产生自然的联动偏移。
 * 目标：用户只调肩，肘自动微弯；只调髋，膝自动微屈。
 * 消除"这边乱动那边乱动"的独立关节观感。
 *
 * 规则：
 *   1. 肩大幅上举/侧举 → 肘自动微弯 5~15°（举手时不会笔直像僵尸）
 *   2. 髋大幅前屈 → 膝自动微屈 8~20°（走路抬腿时自然屈膝）
 *   3. 胸扭转 → 头微幅跟随（系数 0.3，保留独立控制能力）
 *   4. 腹俯仰 → 胸微幅反向补偿（保持上半身整体姿态协调）
 *
 * 注意：所有联动都是**叠加小偏移量**，不覆盖用户显式设置的值。
 * 显式设置的关节值仍为主导，chain 只是"锦上添花"的自然化微调。
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

  // —— 规则 3：胸扭转 → 头跟随（系数 0.3）——
  // 如果胸扭得很多但头没动，头自动跟进一点
  const spineToHead = p.spineY * 0.3 * s;
  // 头已有独立值时只补差值（最多 10°）
  const headFollowDelta = Math.max(-10, Math.min(10, spineToHead));
  p.headY += headFollowDelta;
  p.headY = Math.max(-70, Math.min(70, p.headY));

  // —— 规则 4：腹俯仰 → 胸反向补偿 ——
  // 腹大幅前弯时，胸微幅反向，保持整体不塌
  if (p.abdomenX > 15) {
    const comp = (p.abdomenX - 15) * 0.25 * s;
    p.spineX += comp;
    p.spineX = Math.max(-40, Math.min(40, p.spineX));
  }

  // —— 规则 5：走路对侧联动（lHip ↔ rShoulder 反相）——
  // 如果一只髋前屈，对侧肩自动前摆一点，模拟走路时的自然摆臂
  const walkCompensate = (hipX: number, oppositeShoulderX: number): number => {
    const swing = Math.max(0, Math.abs(hipX) - 25) * 0.15 * s;
    return oppositeShoulderX + swing;
  };
  p.lShoulderX = walkCompensate(p.rHipX, p.lShoulderX);
  p.rShoulderX = walkCompensate(p.lHipX, p.rShoulderX);

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
  const headLimit = 22;
  if (Math.abs(p.headX) > headLimit) {
    const extra = (p.headX - Math.sign(p.headX) * headLimit) * 0.22 * s;
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

/**
 * 在关键帧序列里按时间戳取插值姿势。
 * 默认用 easeInOutCubic 缓动，让姿势切换呈自然曲线而非匀速。
 * 输出自动过 resolveChainPose + resolveClampPose，保证链式联动 + 防穿模。
 */
export function sampleKeyframes(
  keyframes: { t: number; pose: JointPose }[],
  timeMs: number,
  easeFn: (t: number) => number = easeInOutCubic,
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
      const t = (timeMs - a.t) / (b.t - a.t);
      const raw = lerpPose(a.pose, b.pose, t, easeFn);
      return resolveChainPose(resolveClampPose(raw));
    }
  }
  return resolveChainPose(resolveClampPose(last.pose));
}

export function applyPreset(id: PosePresetId): JointPose {
  const hit = POSE_PRESETS.find((p) => p.id === id);
  return mergePose(defaultPose(), hit?.pose || {});
}

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
  return (name || "").replace(/^(mixamorig|mixamo):?[\s_-]?/i, "").toLowerCase();
}

function findGLBBoneExact(scene: THREE.Object3D, keyword: string): THREE.Object3D | null {
  const key = keyword.toLowerCase();
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
  const key = keyword.toLowerCase();
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
  B.hips = pickGLBBone(scene, ["Hips", "DEF-spine", "hips", "torso"]);
  B.abdomen = pickGLBBone(scene, ["Spine", "DEF-spine.001", "spine.001"]);
  B.spine = pickGLBBone(scene, ["Spine1", "DEF-spine.002", "spine.002"]);
  B.spine2 = pickGLBBone(scene, ["Spine2", "DEF-spine.003", "spine.003", "chest"]);
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
  if (/hip|pelvis/.test(n)) return "abdomen";
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
    assign("abdomen", gl.abdomen || gl.hips);
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

function worldPos(obj: THREE.Object3D, out = new THREE.Vector3()) {
  return obj.getWorldPosition(out);
}

function clampJoint(key: keyof JointPose, value: number): number {
  const meta = JOINT_LABELS.find((j) => j.key === key);
  if (!meta) return value;
  return Math.max(meta.min, Math.min(meta.max, value));
}

/**
 * 2 骨 IK：目标点 → 肩/髋朝向 + 肘/膝弯曲，写成 JointPose 补丁。
 * 拉手/脚会带动整条肢体；头/胸则看向目标。
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
      headX: clampJoint("headX", rad2deg(Math.atan2(-dir.y, Math.hypot(dir.x, dir.z)))),
    };
  }

  if (chain === "torso") {
    const origin = bones.abdomen ? worldPos(bones.abdomen) : worldPos(root).add(new THREE.Vector3(0, 1.0, 0));
    const dir = target.clone().sub(origin).applyQuaternion(qInv);
    if (dir.lengthSq() < 1e-6) return {};
    dir.normalize();
    const x = clampJoint("spineX", rad2deg(Math.atan2(-dir.y, dir.z)) * 0.45);
    const y = clampJoint("spineY", rad2deg(Math.atan2(dir.x, dir.z)) * 0.45);
    return { spineX: x, spineY: y, abdomenX: clampJoint("abdomenX", x * 0.6) };
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
) {
  if (!bone) return;
  const rest = identity[key];
  if (rest) bone.quaternion.copy(rest);
  else bone.quaternion.identity();
  if (xDeg === 0 && yDeg === 0 && zDeg === 0) return;
  bone.quaternion.multiply(
    new THREE.Quaternion().setFromEuler(new THREE.Euler(deg(xDeg), deg(yDeg), deg(zDeg), "XYZ")),
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
  const p = resolveClampPose(mergePose(defaultPose(), pose));
  const neg = (v: number) => -v;

  applyBoneDelta(bones.abdomen, identity, "abdomen", neg(p.abdomenX), 0, 0);
  applyBoneDelta(bones.spine2 || bones.spine, identity, bones.spine2 ? "spine2" : "spine", neg(p.spineX), p.spineY, 0);
  applyBoneDelta(bones.head, identity, "head", neg(p.headX), p.headY, 0);

  applyBoneDelta(bones.lShoulder, identity, "lShoulder", 0, 0, p.lShoulderZ * 0.35);
  applyBoneDelta(bones.lArm, identity, "lArm", neg(p.lShoulderX), 0, p.lShoulderZ);
  // BodyKun 前臂/小腿 rest 未镜像，+X 才是屈肘/屈膝（朝腹侧）；肩/髋仍用 neg X = 抬起
  applyBoneDelta(bones.lForeArm, identity, "lForeArm", p.lElbowX, 0, 0);
  applyBoneDelta(bones.lWrist, identity, "lWrist", p.lWristX, 0, 0);

  applyBoneDelta(bones.rShoulder, identity, "rShoulder", 0, 0, p.rShoulderZ * 0.35);
  applyBoneDelta(bones.rArm, identity, "rArm", neg(p.rShoulderX), 0, p.rShoulderZ);
  applyBoneDelta(bones.rForeArm, identity, "rForeArm", p.rElbowX, 0, 0);
  applyBoneDelta(bones.rWrist, identity, "rWrist", p.rWristX, 0, 0);

  applyBoneDelta(bones.lHip, identity, "lHip", neg(p.lHipX), 0, p.lHipZ);
  applyBoneDelta(bones.lKnee, identity, "lKnee", p.lKneeX, 0, 0);
  applyBoneDelta(bones.lAnkle, identity, "lAnkle", p.lAnkleX, 0, 0);

  applyBoneDelta(bones.rHip, identity, "rHip", neg(p.rHipX), 0, p.rHipZ);
  applyBoneDelta(bones.rKnee, identity, "rKnee", p.rKneeX, 0, 0);
  applyBoneDelta(bones.rAnkle, identity, "rAnkle", p.rAnkleX, 0, 0);
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

  applyBoneDelta(bones.abdomen, identity, "abdomen", neg(p.abdomenX), 0, 0);
  applyBoneDelta(bones.spine2 || bones.spine, identity, bones.spine2 ? "spine2" : "spine", neg(p.spineX), p.spineY, 0);
  applyBoneDelta(bones.head, identity, "head", neg(p.headX), p.headY, 0);

  applyBoneDelta(bones.lShoulder, identity, "lShoulder", 0, 0, p.lShoulderZ * 0.35);
  applyBoneDelta(bones.lArm, identity, "lArm", neg(p.lShoulderX), 0, p.lShoulderZ);
  applyBoneDelta(bones.lForeArm, identity, "lForeArm", p.lElbowX, 0, 0);
  applyBoneDelta(bones.lWrist, identity, "lWrist", p.lWristX, 0, 0);

  applyBoneDelta(bones.rShoulder, identity, "rShoulder", 0, 0, p.rShoulderZ * 0.35);
  applyBoneDelta(bones.rArm, identity, "rArm", neg(p.rShoulderX), 0, p.rShoulderZ);
  applyBoneDelta(bones.rForeArm, identity, "rForeArm", p.rElbowX, 0, 0);
  applyBoneDelta(bones.rWrist, identity, "rWrist", p.rWristX, 0, 0);

  applyBoneDelta(bones.lHip, identity, "lHip", neg(p.lHipX), 0, p.lHipZ);
  applyBoneDelta(bones.lKnee, identity, "lKnee", p.lKneeX, 0, 0);
  applyBoneDelta(bones.lAnkle, identity, "lAnkle", p.lAnkleX, 0, 0);

  applyBoneDelta(bones.rHip, identity, "rHip", neg(p.rHipX), 0, p.rHipZ);
  applyBoneDelta(bones.rKnee, identity, "rKnee", p.rKneeX, 0, 0);
  applyBoneDelta(bones.rAnkle, identity, "rAnkle", p.rAnkleX, 0, 0);
}

let _sharedGLTFLoader: GLTFLoader | null = null;
function getGLTFLoader(): GLTFLoader {
  if (!_sharedGLTFLoader) _sharedGLTFLoader = new GLTFLoader();
  return _sharedGLTFLoader;
}

let _bodyGridTex: THREE.CanvasTexture | null = null;

/** BodyKun 风格：灰白底 + 环绕等高线（经纬网格），不要 mesh 线框。 */
function getBodyGridTexture(): THREE.CanvasTexture {
  if (_bodyGridTex) return _bodyGridTex;
  const s = 1024;
  const canvas = document.createElement("canvas");
  canvas.width = s;
  canvas.height = s;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#c9c9c4";
  ctx.fillRect(0, 0, s, s);
  const meridians = 8;
  const parallels = 12;
  for (let i = 0; i <= meridians; i++) {
    ctx.beginPath();
    ctx.strokeStyle = "#161618";
    ctx.lineWidth = i === 0 || i === meridians / 2 || i === meridians ? 3.4 : 1.5;
    const x = (i / meridians) * s + 0.5;
    ctx.moveTo(x, 0);
    ctx.lineTo(x, s);
    ctx.stroke();
  }
  for (let i = 0; i <= parallels; i++) {
    ctx.beginPath();
    ctx.strokeStyle = "#161618";
    ctx.lineWidth = i === 0 || i === parallels / 2 || i === parallels ? 3.4 : 1.5;
    const y = (i / parallels) * s + 0.5;
    ctx.moveTo(0, y);
    ctx.lineTo(s, y);
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.anisotropy = 8;
  tex.needsUpdate = true;
  _bodyGridTex = tex;
  return tex;
}

function rewriteGeometryUVs(geometry: THREE.BufferGeometry, spherical: boolean) {
  geometry.computeBoundingBox();
  const bb = geometry.boundingBox;
  if (!bb) return;
  const size = new THREE.Vector3();
  bb.getSize(size);
  const pos = geometry.attributes.position;
  const n = pos.count;
  const uv = new Float32Array(n * 2);
  let axis: 0 | 1 | 2 = 1;
  if (size.x >= size.y && size.x >= size.z) axis = 0;
  else if (size.z >= size.y && size.z >= size.x) axis = 2;
  const minA = axis === 0 ? bb.min.x : axis === 1 ? bb.min.y : bb.min.z;
  const maxA = axis === 0 ? bb.max.x : axis === 1 ? bb.max.y : bb.max.z;
  const span = Math.max(1e-6, maxA - minA);
  const cx0 = (bb.min.x + bb.max.x) * 0.5;
  const cy0 = (bb.min.y + bb.max.y) * 0.5;
  const cz0 = (bb.min.z + bb.max.z) * 0.5;
  for (let i = 0; i < n; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    const z = pos.getZ(i);
    if (spherical) {
      const dx = x - cx0;
      const dy = y - cy0;
      const dz = z - cz0;
      const r = Math.hypot(dx, dy, dz) || 1;
      uv[i * 2] = Math.atan2(dx, dz) / (Math.PI * 2) + 0.5;
      uv[i * 2 + 1] = Math.acos(Math.max(-1, Math.min(1, dy / r))) / Math.PI;
    } else {
      let along: number;
      let cx: number;
      let cy: number;
      if (axis === 1) {
        along = y;
        cx = x;
        cy = z;
      } else if (axis === 0) {
        along = x;
        cx = y;
        cy = z;
      } else {
        along = z;
        cx = x;
        cy = y;
      }
      uv[i * 2] = Math.atan2(cx, cy) / (Math.PI * 2) + 0.5;
      uv[i * 2 + 1] = (along - minA) / span;
    }
  }
  geometry.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
}

/** 把 GLB 外观统一成参考图：哑光灰白 + 环绕等高线 + 深灰关节球。 */
function applyBodyKunLook(scene: THREE.Object3D) {
  const grid = getBodyGridTexture();
  const bodyMat = new THREE.MeshStandardMaterial({
    color: "#c8c8c3",
    map: grid,
    roughness: 0.74,
    metalness: 0.03,
  });
  const jointMat = new THREE.MeshStandardMaterial({
    color: "#5e5e5a",
    roughness: 0.38,
    metalness: 0.18,
  });
  const size = new THREE.Vector3();
  scene.traverse((obj) => {
    const m = obj as THREE.Mesh;
    if (!m.isMesh || !m.geometry) return;
    m.geometry = m.geometry.clone();
    m.geometry.computeBoundingBox();
    const bb = m.geometry.boundingBox;
    if (!bb) return;
    bb.getSize(size);
    const max = Math.max(size.x, size.y, size.z);
    const min = Math.min(size.x, size.y, size.z);
    const spherical = max > 1e-6 && min / max > 0.68;
    const isJoint = spherical && max < 0.12;
    if (!isJoint) rewriteGeometryUVs(m.geometry, spherical);
    m.material = isJoint ? jointMat : bodyMat;
    m.castShadow = true;
    m.receiveShadow = true;
  });
}

/** 缓存原始 GLTF scene（URL → 未处理的原始 Object3D），每次使用时 clone 独立副本 */
const _glbSceneCache = new Map<string, Promise<THREE.Object3D>>();

function loadRawGLBScene(url: string): Promise<THREE.Object3D> {
  const cached = _glbSceneCache.get(url);
  if (cached) return cached;
  const task = new Promise<THREE.Object3D>((resolve, reject) => {
    getGLTFLoader().load(url, (gltf) => resolve(gltf.scene), undefined, reject);
  });
  _glbSceneCache.set(url, task);
  return task;
}

export type LoadGLBOptions = {
  wireframeOverlay?: boolean;
  overrideColor?: string;
  scale?: number;
};

export function loadGLBRiggedHumanoid(
  url: string,
  options?: LoadGLBOptions,
): Promise<THREE.Group> {
  return loadRawGLBScene(url).then((rawScene) => {
    // 每次 clone 独立副本，避免多 actor 共享同一场景对象
    // SkeletonUtils.clone 会重绑 SkinnedMesh.skeleton，普通 clone 会导致旋转骨骼 mesh 不动
    const scene = cloneSkinned(rawScene);
    scene.name = "glb_scene_" + (url.split("/").pop()?.replace(/\.glb$/i, "") ?? "");
    scene.traverse((obj) => {
      const m = obj as THREE.Mesh;
      if (!m.isMesh || !m.material) return;
      m.material = Array.isArray(m.material) ? m.material.map((x) => x.clone()) : m.material.clone();
      m.castShadow = true;
      m.receiveShadow = true;
    });

    const boneMap = buildGLBBoneMap(scene);
    const identity = recordGLBTPose(boneMap);
    scene.traverse((obj) => {
      const m = obj as THREE.Mesh;
      if (!m.isMesh) return;
      m.castShadow = true;
      m.receiveShadow = true;
    });

    const root = new THREE.Group();
    root.add(scene);

    const hipsBone = boneMap.hips;
    if (hipsBone) {
      const wp = new THREE.Vector3();
      hipsBone.getWorldPosition(wp);
      scene.position.y = 0.92 - wp.y;
    }

    scene.scale.setScalar(options?.scale ?? 1.0);

    root.userData.glBones = boneMap;
    root.userData.glBonesIdentity = identity;
    root.userData.sourceUrl = url;

    const foundCount = Object.values(boneMap).filter(Boolean).length;
    let skinned = 0;
    let skelBones = 0;
    scene.traverse((obj) => {
      const mesh = obj as THREE.SkinnedMesh;
      if (!mesh.isSkinnedMesh || !mesh.skeleton) return;
      skinned += 1;
      skelBones += mesh.skeleton.bones.length;
    });
    console.log("[RiggedHumanoid] GLB cloned:", { url, foundBones: foundCount, skinned, skelBones });

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

  loadGLBRiggedHumanoid(url, options)
    .then((glbRoot) => {
      const glbScene = glbRoot.children[0];
      if (!glbScene) {
        root.userData._glb_attaching = false;
        return;
      }
      let tries = 0;
      const finish = () => {
        if (root.userData._disposed) return;
        if (!root.parent && tries++ < 60) {
          requestAnimationFrame(finish);
          return;
        }
        if (!root.parent) {
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
        bindHumanoidPickData(root);
        applyPose(root, root.userData._lastPose || defaultPose());
        console.log("[RiggedHumanoid] GLB attached:", url, {
          foundBones: Object.values(root.userData.glBones as object[]).filter(Boolean).length,
        });
      };
      finish();
    })
    .catch((err) => {
      console.warn("[RiggedHumanoid] GLB attach failed, keeping capsule:", err?.message || err);
      root.userData._glb_attaching = false;
    });
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