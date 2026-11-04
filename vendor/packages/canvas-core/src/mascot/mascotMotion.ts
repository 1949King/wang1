/**
 * 桌宠动作曲线与调度取值（纯函数层）。
 *
 * 为什么单独一层
 * ==============
 * 对标参考开源画布（`vendor/AI-Canvas-tauri` 的 `shared/mascot/Mascot.tsx` + `mascotMotion.ts`）：
 * 它的做法是把**动作曲线**从 Three.js 渲染循环里剥出来 —— 渲染循环只按帧把结果写进场景对象，
 * 曲线本身不需要 WebGL 就能验证。我们照抄这个分层，理由有两条：
 *   1. 单测跑得快（毫秒级），不用起 WebGL 上下文；
 *   2. 手感参数（跳跃高度、挤压量、耳抖幅度）改动时，回归能第一时间报出「两端没回中立位」这类
 *      会留残余位移的经典错误。
 *
 * 移植口径
 * ========
 * `REACTION_DURATIONS` / `getReactionPose` / `getSquashWidth` / `pickNextGazeIndex` 与参考实现
 * **保持同名同语义**（含数值），这样它的 7 条回归用例可以原样迁移。狐狸专属的部分（耳朵、尾巴、
 * 眨眼、呼吸）另起函数，不改动上面四个的语义。
 */

/** 桌宠状态。`awaiting` 是我们自己的——对应 Agent 停在「等你确认」的状态位。 */
export type PetStatus = "idle" | "thinking" | "awaiting" | "success" | "error";

/** 状态转场时的一次性肢体反应。 */
export type MascotReactionKind = "hop" | "shake";

/** 各反应的时长（秒）。 */
export const REACTION_DURATIONS: Record<MascotReactionKind, number> = {
  hop: 0.62,
  shake: 0.5,
};

const HOP_HEIGHT = 0.16;
const HOP_SQUASH = 0.14;
/** 起跳前的下蹲与落地压扁各占的进度比例。 */
const HOP_CROUCH_END = 0.18;
const HOP_LAND_START = 0.82;
const SHAKE_ANGLE = 0.2;
const SHAKE_CYCLES = 2.5;
const SHAKE_DIP = 0.05;

export interface MascotReactionPose {
  /** 竖直位移，正值向上。 */
  lift: number;
  /** 叠加到头部偏航上的角度（弧度）。 */
  yaw: number;
  /** 纵向缩放系数，1 为原始高度；横向由调用方按等体积换算。 */
  squashY: number;
}

const NEUTRAL_POSE: MascotReactionPose = { lift: 0, yaw: 0, squashY: 1 };

/** 蹦跳的挤压拉伸：起跳前下蹲、空中拉长、落地再压一下。 */
function getHopSquash(progress: number): number {
  if (progress < HOP_CROUCH_END) {
    return 1 - HOP_SQUASH * Math.sin((progress / HOP_CROUCH_END) * Math.PI);
  }
  if (progress > HOP_LAND_START) {
    return 1 - HOP_SQUASH * Math.sin(((progress - HOP_LAND_START) / (1 - HOP_LAND_START)) * Math.PI);
  }
  const airProgress = (progress - HOP_CROUCH_END) / (HOP_LAND_START - HOP_CROUCH_END);
  return 1 + HOP_SQUASH * 0.6 * Math.sin(airProgress * Math.PI);
}

/**
 * 按反应进度取当前姿态。progress 会被夹到 [0,1]，两端都回到中立姿态，
 * 这样反应结束时不会在场景里留下残余位移或旋转。
 */
export function getReactionPose(kind: MascotReactionKind, progress: number): MascotReactionPose {
  const clamped = Math.min(Math.max(progress, 0), 1);
  if (clamped >= 1) return NEUTRAL_POSE;

  if (kind === "hop") {
    return {
      lift: Math.sin(Math.PI * clamped) * HOP_HEIGHT,
      yaw: 0,
      squashY: getHopSquash(clamped),
    };
  }
  // 摇头：左右摆动并随进度衰减，同时轻微下沉，读起来像“不行”。
  return {
    lift: -Math.sin(Math.PI * clamped) * SHAKE_DIP,
    yaw: Math.sin(clamped * Math.PI * 2 * SHAKE_CYCLES) * SHAKE_ANGLE * (1 - clamped),
    squashY: 1,
  };
}

/** 等体积换算：纵向压扁多少，横向就相应变宽。 */
export function getSquashWidth(squashY: number): number {
  return 1 / Math.sqrt(Math.max(squashY, 0.05));
}

/** 取下一个张望落点，保证与当前落点不同，避免连续两次看向同一处。 */
export function pickNextGazeIndex(
  currentIndex: number,
  pointCount: number,
  random: number,
): number {
  if (pointCount <= 1) return 0;
  const candidate = Math.min(Math.floor(random * pointCount), pointCount - 1);
  return candidate === currentIndex ? (candidate + 1) % pointCount : candidate;
}

/* ────────────────────────────── 狐狸专属 ────────────────────────────── */

/** 呼吸：永远是「纵向略微压扁」，绝不会变高（变高会被读成弹跳，抢掉真弹跳的信号）。 */
const BREATH_SQUASH = 0.014;
const BREATH_PERIOD = 3.6;

export function getBreath(timeSec: number): number {
  return 1 - BREATH_SQUASH * (0.5 - 0.5 * Math.cos((timeSec / BREATH_PERIOD) * Math.PI * 2));
}

/** 眨眼：单次时长为「闭合 + 张开」各半，两端都是 1（睁眼），中点为最闭。 */
export const BLINK_DURATION = 0.14;
export const BLINK_MIN_GAP = 2.2;
export const BLINK_MAX_GAP = 5.5;
const BLINK_CLOSE_RATIO = 0.94;

export function getBlinkScaleY(progress: number): number {
  const clamped = Math.min(Math.max(progress, 0), 1);
  return 1 - BLINK_CLOSE_RATIO * Math.sin(Math.PI * clamped);
}

/** 下一次眨眼的间隔（秒）；`random` 取 [0,1)。 */
export function nextBlinkGap(random: number): number {
  const r = Math.min(Math.max(random, 0), 1);
  return BLINK_MIN_GAP + r * (BLINK_MAX_GAP - BLINK_MIN_GAP);
}

/** 眨眼序列：有一定概率二连眨、或只眨一只眼（wink）。纯函数便于回归固定参数。 */
export interface BlinkPlan {
  /** 二连眨 */
  double: boolean;
  /** 单眼眨（左眼闭、右眼半闭） */
  wink: boolean;
}

export function planBlink(randomDouble: number, randomWink: number): BlinkPlan {
  return { double: randomDouble < 0.18, wink: randomWink < 0.12 };
}

/** 耳朵抖动：一次快速的「竖起 → 回落」，两端回 0。 */
export const EAR_FLICK_DURATION = 0.34;

export function getEarFlick(progress: number): number {
  const clamped = Math.min(Math.max(progress, 0), 1);
  if (clamped >= 1) return 0;
  // 先快速外翻再回位，用 |sin| 保证不出现负向「反向折耳」的怪动作。
  return Math.abs(Math.sin(clamped * Math.PI * 1.5)) * (1 - clamped) * 0.55;
}

/** 耳朵的情绪基态倾角：出错垂耳、思考微前倾、其它竖立。 */
const EAR_DROOP: Record<PetStatus, number> = {
  idle: 0,
  thinking: -0.06,
  awaiting: 0.14,
  success: 0.08,
  error: -0.34,
};

export function getEarDroop(status: PetStatus): number {
  return EAR_DROOP[status];
}

/** 尾巴摆动：能量越高摆得越快越大（思考/等待确认时能量高）。 */
export function getTailSwing(timeSec: number, energy: number): number {
  const e = Math.min(Math.max(energy, 0), 1);
  const freq = 1.5 + 2.6 * e;
  const amp = 0.12 + 0.38 * e;
  return Math.sin(timeSec * freq * Math.PI * 2) * amp;
}

/** 各状态的「能量」：驱动尾巴与视线游移频率。 */
const STATUS_ENERGY: Record<PetStatus, number> = {
  idle: 0.12,
  thinking: 0.75,
  awaiting: 0.95,
  success: 0.6,
  error: 0.3,
};

export function getStatusEnergy(status: PetStatus): number {
  return STATUS_ENERGY[status];
}

/** 状态 → 一次性反应（转场时播一次）。null = 不做肢体反应。 */
const REACTION_FOR_STATUS: Partial<Record<PetStatus, MascotReactionKind>> = {
  success: "hop",
  error: "shake",
  awaiting: "hop",
};

export function reactionForStatus(status: PetStatus): MascotReactionKind | null {
  return REACTION_FOR_STATUS[status] ?? null;
}

/** 眼形姿态：`scaleY` 纵向压缩、`rotationZ` 内外眼角倾角、`offsetY` 眼位高低（单位=头半径比例）。 */
export interface EyePose {
  scaleY: [number, number];
  rotationZ: [number, number];
  offsetY: [number, number];
  /** 瞳孔外扩量（惊讶/期待时放大眨眼瞳）——狐狸的特色，参考实现没有。 */
  pupilScale: number;
}

/**
 * 与参考实现同源的 EYE_POSES，另加 `awaiting`（期待：睁大眼 + 瞳孔放大）与 `pupilScale`。
 * 命名与语义都保留，方便和参考实现对照排查「为什么看起来不像同一个动作」。
 */
export const EYE_POSES: Record<PetStatus, EyePose> = {
  idle: {
    scaleY: [1, 1],
    rotationZ: [0, 0],
    offsetY: [0, 0],
    pupilScale: 1,
  },
  thinking: {
    scaleY: [0.72, 0.62],
    rotationZ: [-0.04, 0.04],
    offsetY: [0, 0.02],
    pupilScale: 0.92,
  },
  awaiting: {
    scaleY: [1.12, 1.12],
    rotationZ: [0.02, -0.02],
    offsetY: [0.012, 0.012],
    pupilScale: 1.22,
  },
  success: {
    scaleY: [0.34, 0.34],
    rotationZ: [-0.65, 0.65],
    offsetY: [0.025, 0.025],
    pupilScale: 1,
  },
  error: {
    scaleY: [0.58, 0.58],
    rotationZ: [0.48, -0.48],
    offsetY: [-0.025, -0.025],
    pupilScale: 0.8,
  },
};

/**
 * 眼神跟随鼠标的最大偏转（弧度）。狐狸是「杏眼 + 眼白」结构，比球体的贴片眼睛能多吃一点偏转，
 * 但过了 0.42 就会露眼白露得吓人，所以沿用参考实现的上限。
 */
export const EYE_MAX_ANGLE = 0.42;
/** 头部跟随鼠标的轻微转动（弧度）。 */
export const HEAD_MAX_ANGLE = 0.12;
/** 跟随平滑系数。 */
export const FOLLOW_LERP = 0.12;

/** 状态 → 边缘光颜色（十六进制）。idle 用品牌橙的柔化版。 */
export const STATUS_RIM_COLORS: Record<PetStatus, number> = {
  idle: 0xf7a061,
  thinking: 0x7ea6ff,
  awaiting: 0xf97316,
  success: 0x57c7a2,
  error: 0xd98282,
};

/** 状态 → 气泡文案（`null` 表示不显示气泡）。 */
export const STATUS_BUBBLES: Record<PetStatus, string | null> = {
  idle: null,
  thinking: "正在生成…",
  awaiting: "这步要我继续吗？",
  success: "好啦",
  error: "出错了",
};

/** 状态 → 无障碍标签（悬停 tooltip / 屏幕阅读器）。 */
export const STATUS_LABELS: Record<PetStatus, string> = {
  idle: "打开 Agent",
  thinking: "画布助手：正在生成",
  awaiting: "画布助手：等待你确认",
  success: "画布助手：已完成",
  error: "画布助手：任务失败",
};

/* ────────────────────────── 生命力层（2026-10-20） ──────────────────────────
 * 「有生命力」不等于一直动。这一层的三个动作都**低频、克制**：
 *   1. 待机小动作：每 4~9s 一次（歪头 / 轻摇 / 抖耳），让静止画面有呼吸感；
 *   2. 打瞌睡：idle 静置 75s 后呼吸放缓、下沉、冒「呼…」——被靠近或点击就醒；
 *   3. 好奇：指针进入 160px 半径时身体朝指针轻倾 ≤2°。
 * 三者都只产出**数值/种类**，渲染仍在 CSS（合成器友好、尊重 reduced-motion）。
 */

/** 静置多久后进入「打瞌睡」表现（毫秒）。 */
export const SLEEPY_AFTER_MS = 75_000;

/** 睡眠时的呼吸周期（秒）——比清醒的 3.6s 慢一档。 */
export const SLEEPY_BREATH_PERIOD = 5.2;

/** 睡眠气泡与无障碍标签。 */
export const SLEEPY_BUBBLE = "呼…";
export const SLEEPY_LABEL = "画布助手：打瞌睡";

/** 睡眠时的下沉像素（读作「睡着了往下沉一点」）。 */
export const SLEEPY_SINK_PX = 3;

/** 睡眠呼吸的纵向压扁量（比清醒的 1.4% 更深）。 */
const SLEEPY_BREATH_SQUASH = 0.02;

/** 睡眠呼吸的纵向缩放系数（≤1；永不高于原高，与清醒呼吸同一不变量）。 */
export function getSleepyBreath(timeSec: number): number {
  return 1 - SLEEPY_BREATH_SQUASH * (0.5 - 0.5 * Math.cos((timeSec / SLEEPY_BREATH_PERIOD) * Math.PI * 2));
}

/** 待机小动作的种类。 */
export type AmbientKind = "tilt" | "sway" | "perk";

/** 两次待机小动作之间的间隔区间（秒）。 */
export const AMBIENT_MIN_GAP = 4;
export const AMBIENT_MAX_GAP = 9;

/** 下一次待机小动作的间隔（秒）；random 取 [0,1)。 */
export function nextAmbientGap(random: number): number {
  const r = Math.min(Math.max(random, 0), 1);
  return AMBIENT_MIN_GAP + r * (AMBIENT_MAX_GAP - AMBIENT_MIN_GAP);
}

/**
 * 按随机数挑一个待机小动作。刻意让「歪头」占比最高（最像活物），抖耳最少
 * —— 抖耳频率高会像抽搐，只在约 1/5 的时候出现。
 */
export function pickAmbientKind(random: number): AmbientKind {
  const r = Math.min(Math.max(random, 0), 1);
  if (r < 0.45) return "tilt";
  if (r < 0.8) return "sway";
  return "perk";
}

/** 好奇触发半径（像素）：指针进入这个距离才响应。 */
export const CURIOUS_RADIUS_PX = 160;

/** 好奇的最大倾角（度）。超过 2° 会被读成「站不稳」。 */
export const CURIOUS_MAX_TILT_DEG = 2;

/**
 * 好奇倾角：指针在半径内时朝指针方向倾（左右），距离越近倾得越多；
 * 半径外恒为 0（不干扰正常使用）。
 */
export function getCuriousTilt(pointerDx: number, pointerDy: number): number {
  const distance = Math.sqrt(pointerDx * pointerDx + pointerDy * pointerDy);
  if (!Number.isFinite(distance) || distance >= CURIOUS_RADIUS_PX) return 0;
  const falloff = 1 - distance / CURIOUS_RADIUS_PX;
  const direction = Math.sign(pointerDx);
  return direction * CURIOUS_MAX_TILT_DEG * falloff;
}

