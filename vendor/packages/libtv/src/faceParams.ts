/**
 * 捏脸参数单一真相源（faceParams）
 *
 * 定位：独立捏脸卡片（FaceCard.tsx）与 3D 导演台共享的**唯一数据结构**。
 *  - 卡片负责「调参数」；本模块负责「定义参数 + 校验 + 确定性兜底」。
 *  - 导演台侧「长在身上」目前**尚未接线**（2026-10-13 审查实测：riggedHumanoid /
 *    Stage3D / store 对本模块零引用）；faceHeadParts 已备好几何层，
 *    挂载是后续刀（需解冻 zone7）。
 *  - 两端只通过本结构交汇，UI 互不依赖 ⇒ 卡片可单独打开，导演台缺省也能跑。
 *
 * 铁律（与项目其余部分一致）：
 *  1. **零随机** —— 随机只出现在用户点「随机」时，且走 mulberry32(id 哈希) 确定性种子；
 *     同一 characterId 多次生成结果恒等。禁止 Math.random()。
 *  2. **派生值不下发前端** —— 本模块只做「参数的规范化与兜底」，不做美术口径换算。
 *  3. **缺省即合法** —— normalizeFaceParams(undefined) 必须返回完整合法对象，
 *     保证旧工程（无 faceParams 字段）零改动加载。
 */

/** 表情预设 ID（程序化五官驱动，非 morph target） */
export type FaceEmotionId =
  | "neutral"
  | "smile"
  | "grin"
  | "sad"
  | "angry"
  | "surprised"
  | "shy"
  | "smirk"
  // A 类扩展（2026-10-13）：更多表演基元
  | "confused"
  | "determined"
  | "sleepy"
  | "excited";

/** 眉形预设 ID */
export type BrowStyleId =
  | "flat" | "arch" | "angry" | "sad" | "thin" | "thick"
  // A 类扩展
  | "round" | "short";

/** 眼型预设 ID */
export type EyeStyleId =
  | "round" | "almond" | "narrow" | "upturned" | "droopy" | "big"
  // A 类扩展
  | "cat" | "sleepy";

/** 瞳色预设（含异色瞳） */
export type EyeColorId =
  | "black" | "brown" | "amber" | "hazel"
  | "blue" | "green" | "violet" | "red" | "gold";

/** 唇形预设 ID */
export type LipStyleId =
  | "thin" | "plump" | "wide" | "small" | "cupid" | "neutral"
  // A 类扩展
  | "pouty" | "sharp";

/** 发饰预设 ID（挂在 head 骨骼的几何附件，非贴图） */
export type HairAccessoryId =
  | "none"
  | "hairpin"      // 单簪
  | "hairpin_dual" // 双簪
  | "ribbon"       // 发带（蝴蝶结）
  | "ribbon_tail"  // 长飘带
  | "tiara"        // 冠冕
  | "flower"       // 花钿
  | "earring"      // 耳饰
  | "forehead_mark"// 额饰（花钿/印记）
  | "veil"         // 头纱
  | "horns"        // 角（幻想系）
  // A 类扩展：轻量几何
  | "glasses"
  | "flower_crown";

/** 妆容色板（16 色，男女通用低饱和到高饱和） */
export const MAKEUP_PALETTE: string[] = [
  "#f5e6dc", "#e8c4a0", "#d9a273", "#b97b4e", "#8c5230", "#5c3520", "#2b1a12", "#111111",
  "#f7c6d9", "#f08bb4", "#d94f8a", "#a8326b",
  "#c9d6f5", "#7f9ce8", "#5b6dc4", "#3a3f8c",
];

/** 肤色色板（8 档，从冷白到深棕） */
export const SKIN_PALETTE: string[] = [
  "#fdece4", "#f8d9c9", "#f0c3a8", "#e0a882",
  "#c88a63", "#a86a45", "#7d4c2e", "#54321d",
];

/** 发色色板（16 色，含幻想色） */
export const HAIR_PALETTE: string[] = [
  "#111111", "#1e293b", "#3f3f46", "#6b4423", "#a16207", "#d4a373", "#f5e6d3", "#e5e7eb",
  "#b91c1c", "#ea580c", "#eab308", "#16a34a", "#0d9488", "#2563eb", "#7c3aed", "#db2777",
];

/** 瞳色色板映射（id → hex，供 UI 色块与 3D 双端同源） */
export const EYE_COLOR_HEX: Record<EyeColorId, string> = {
  black: "#111111",
  brown: "#5c3520",
  amber: "#c2762a",
  hazel: "#8a7a45",
  blue: "#2f6fd0",
  green: "#2f8f5b",
  violet: "#7c4fd0",
  red: "#b02a2a",
  gold: "#c9a227",
};

/** 全员默认妆容基线（素颜 = 极淡，不是「无色」） */
export type FaceParams = {
  /** 结构化版本号；未来字段增删时用于迁移，勿删字段只加字段 */
  v: 1;

  // —— 表情 ——
  emotion: FaceEmotionId;
  /** 表情强度 0~1（0 = 完全中性；卡片滑杆可微调单点） */
  emotionIntensity: number;
  /** 局部强度覆盖（0~1，未提供则用 emotionIntensity 兜底） */
  browLift: number;   // 眉毛上扬/下压（负=下压）
  eyeOpen: number;    // 眼睛开合（0.5=半闭，1.5=睁大）
  mouthOpen: number;  // 嘴张开
  mouthCurve: number; // 嘴角弧度（-1=下撇，0=平，+1=上扬）

  // —— 五官样式 ——
  browStyle: BrowStyleId;
  /** 眉色（null = 默认深棕；通常与发色联动） */
  browColor: string | null;
  eyeStyle: EyeStyleId;
  eyeColor: EyeColorId;
  /** 异色瞳：右眼颜色（null = 与左眼一致） */
  eyeColorRight: EyeColorId | null;
  lipStyle: LipStyleId;

  // —— 头型（Ruth2 式 shape sliders；±1，0=默认，作用于顶点位移场） ——
  /** 脸宽：整脸横向缩放 */
  headWidth: number;
  /** 脸长：整脸纵向缩放 */
  headHeight: number;
  /** 下颌宽：下半脸横向缩放（越往下权重越大） */
  jawWidth: number;
  /** 颧骨：面中一带横向+前向隆起 */
  cheekbone: number;
  /** 下巴：下极纵向拉伸 + 前突 */
  chin: number;

  // —— 发饰 ——
  hairAccessory: HairAccessoryId;
  /** 发饰主色（发簪/发带/冠冕金属或缎带色） */
  accessoryColor: string;
  /** 发饰副色（飘带渐变/花蕊） */
  accessoryColor2: string;

  // —— 妆容 ——
  /** 肤色（作用在 GLB 素体材质上） */
  skinTone: string;
  /** 腮红颜色（null = 不上腮红） */
  blush: string | null;
  /** 腮红不透明度 0~1 */
  blushAlpha: number;
  /** 眼影颜色（null = 不上眼影） */
  eyeshadow: string | null;
  /** 眼影不透明度 0~1 */
  eyeshadowAlpha: number;
  /** 唇色（null = 不上唇彩，用自然唇） */
  lipColor: string | null;
  /** 唇彩色不透明度 0~1 */
  lipAlpha: number;
  /** 眼线（null = 无） */
  eyeliner: string | null;
  /** 面部纹饰/花纹颜色（null = 无） */
  faceMark: string | null;
};

/** 表情预设 → 五官参数映射（确定性，无随机） */
export const EMOTION_PRESETS: Record<FaceEmotionId, {
  label: string;
  browLift: number;
  eyeOpen: number;
  mouthOpen: number;
  mouthCurve: number;
}> = {
  neutral:   { label: "平静",  browLift:  0.0, eyeOpen: 1.0, mouthOpen: 0.0,  mouthCurve:  0.0 },
  smile:     { label: "微笑",  browLift:  0.1, eyeOpen: 0.9, mouthOpen: 0.05, mouthCurve:  0.6 },
  grin:      { label: "大笑",  browLift:  0.25, eyeOpen: 0.7, mouthOpen: 0.8, mouthCurve:  0.9 },
  sad:       { label: "悲伤",  browLift: -0.3, eyeOpen: 0.85, mouthOpen: 0.0, mouthCurve: -0.6 },
  angry:     { label: "愤怒",  browLift: -0.55, eyeOpen: 0.95, mouthOpen: 0.15, mouthCurve: -0.5 },
  surprised: { label: "惊讶",  browLift:  0.7, eyeOpen: 1.5, mouthOpen: 0.9, mouthCurve:  0.1 },
  shy:       { label: "害羞",  browLift:  0.15, eyeOpen: 0.55, mouthOpen: 0.1, mouthCurve:  0.35 },
  smirk:     { label: "坏笑",  browLift:  0.2, eyeOpen: 0.95, mouthOpen: 0.1, mouthCurve:  0.5 },
  // A 类扩展（2026-10-13）
  confused:    { label: "困惑",  browLift:  0.35, eyeOpen: 0.85, mouthOpen: 0.05, mouthCurve: -0.2 },
  determined:  { label: "坚定",  browLift: -0.25, eyeOpen: 0.90, mouthOpen: 0.00, mouthCurve: -0.1 },
  sleepy:      { label: "困倦",  browLift:  0.00, eyeOpen: 0.45, mouthOpen: 0.00, mouthCurve:  0.0 },
  excited:     { label: "兴奋",  browLift:  0.50, eyeOpen: 1.30, mouthOpen: 0.40, mouthCurve:  0.7 },
};

/** 发饰预设 → 展示名 + 是否双色（供 UI；几何由 faceHeadParts 负责） */
export const ACCESSORY_META: Record<HairAccessoryId, { label: string; dual: boolean }> = {
  none:           { label: "无",       dual: false },
  hairpin:        { label: "单簪",     dual: false },
  hairpin_dual:   { label: "双簪",     dual: false },
  ribbon:         { label: "发带",     dual: true },
  ribbon_tail:    { label: "长飘带",   dual: true },
  tiara:          { label: "冠冕",     dual: false },
  flower:         { label: "花钿",     dual: true },
  earring:        { label: "耳饰",     dual: false },
  forehead_mark:  { label: "额饰",     dual: false },
  veil:           { label: "头纱",     dual: true },
  horns:          { label: "角",       dual: false },
  // A 类扩展
  glasses:        { label: "眼镜",     dual: false },
  flower_crown:   { label: "花冠",     dual: true },
};

/** 眉/眼/唇/肤色的展示名（UI 下拉与模板摘要的唯一来源；改这里即全站生效） */
export const BROW_LABELS: Record<BrowStyleId, string> = {
  flat: "平眉", arch: "挑眉", angry: "剑眉", sad: "八字眉", thin: "细眉", thick: "粗眉",
  round: "柳眉", short: "短眉",
};
export const EYE_LABELS: Record<EyeStyleId, string> = {
  round: "圆眼", almond: "杏眼", narrow: "细长", upturned: "上挑", droopy: "下垂", big: "大眼",
  cat: "猫眼", sleepy: "睡眼",
};
export const LIP_LABELS: Record<LipStyleId, string> = {
  thin: "薄唇", plump: "饱满", wide: "宽唇", small: "小口", cupid: "丘比特", neutral: "自然",
  pouty: "嘟唇", sharp: "利落",
};
/** 肤色 hex → 展示名（与 SKIN_PALETTE 同源 8 档；未登记色值回落「自定义」） */
export const SKIN_LABELS: Record<string, string> = {
  "#fdece4": "冷白", "#f8d9c9": "白皙", "#f0c3a8": "自然", "#e0a882": "小麦",
  "#c88a63": "蜜色", "#a86a45": "古铜", "#7d4c2e": "深棕", "#54321d": "黝黑",
};

/** 默认（素颜中性）参数 —— 唯一兜底基线 */
export const DEFAULT_FACE_PARAMS: FaceParams = {
  v: 1,
  emotion: "neutral",
  emotionIntensity: 1.0,
  browLift: 0.0,
  eyeOpen: 1.0,
  mouthOpen: 0.0,
  mouthCurve: 0.0,
  browStyle: "flat",
  browColor: null,
  eyeStyle: "almond",
  eyeColor: "black",
  eyeColorRight: null,
  lipStyle: "neutral",
  headWidth: 0,
  headHeight: 0,
  jawWidth: 0,
  cheekbone: 0,
  chin: 0,
  hairAccessory: "none",
  accessoryColor: "#c9a227",
  accessoryColor2: "#f5e6d3",
  skinTone: "#f0c3a8",
  blush: null,
  blushAlpha: 0.35,
  eyeshadow: null,
  eyeshadowAlpha: 0.4,
  lipColor: null,
  lipAlpha: 0.7,
  eyeliner: null,
  faceMark: null,
};

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

function clamp01(v: unknown, fallback: number): number {
  const n = typeof v === "number" && isFinite(v) ? v : fallback;
  return Math.max(0, Math.min(1, n));
}

/** browLift / mouthCurve 允许 -1~1 */
function clampSigned(v: unknown, fallback: number): number {
  const n = typeof v === "number" && isFinite(v) ? v : fallback;
  return Math.max(-1, Math.min(1, n));
}

/** eyeOpen 允许 0~2（1 = 正常，<1 眯，>1 睁大） */
function clampEye(v: unknown, fallback: number): number {
  const n = typeof v === "number" && isFinite(v) ? v : fallback;
  return Math.max(0, Math.min(2, n));
}

function pickEnum<T extends string>(v: unknown, allowed: Record<string, unknown> | readonly string[], fallback: T): T {
  const keys = Array.isArray(allowed) ? (allowed as readonly string[]) : Object.keys(allowed as Record<string, unknown>);
  return (typeof v === "string" && keys.includes(v)) ? (v as T) : fallback;
}

function pickHex(v: unknown, fallback: string | null): string | null {
  if (v === null || v === undefined) return fallback;
  return (typeof v === "string" && HEX_RE.test(v)) ? v.toLowerCase() : fallback;
}

/**
 * 规范化 faceParams：任何输入（undefined / 缺字段 / 脏值 / 旧版本）都返回**完整合法**对象。
 * 这是跨版本、跨端（卡片写入 / 导演台读取 / 角色库反序列化）的唯一入口，
 * 禁止消费方直接读原始对象（否则一个脏字段就能让 3D 崩塌）。
 */
export function normalizeFaceParams(raw: unknown): FaceParams {
  const src = (raw && typeof raw === "object") ? raw as Record<string, unknown> : {};
  const d = DEFAULT_FACE_PARAMS;
  const emotion = pickEnum<FaceEmotionId>(src.emotion, EMOTION_PRESETS, d.emotion);
  // P2 修复（2026-10-13 审查）：非法右眼瞳色兜底为 null（与左眼一致），不是 d.eyeColor（黑）。
  // 旧写法会让旧数据/未来废弃枚举静默变成「右眼黑瞳的假异色瞳」。
  // pickEnum 的 T 约束为 string，null 兜底用哨兵值桥接。
  const NO_RIGHT = "__no_right__" as EyeColorId;
  const rightPick = pickEnum<EyeColorId>(src.eyeColorRight, EYE_COLOR_HEX, NO_RIGHT);

  // 表情：显式滑杆优先；字段缺失时回落到该表情预设值（保证「选表情即生效」）
  const pres = EMOTION_PRESETS[emotion];
  return {
    v: 1,
    emotion,
    emotionIntensity: clamp01(src.emotionIntensity, d.emotionIntensity),
    browLift: clampSigned(src.browLift, pres.browLift),
    eyeOpen: clampEye(src.eyeOpen, pres.eyeOpen),
    mouthOpen: clamp01(src.mouthOpen, pres.mouthOpen),
    mouthCurve: clampSigned(src.mouthCurve, pres.mouthCurve),
    browStyle: pickEnum<BrowStyleId>(src.browStyle, ["flat", "arch", "angry", "sad", "thin", "thick", "round", "short"], d.browStyle),
    browColor: pickHex(src.browColor, d.browColor),
    eyeStyle: pickEnum<EyeStyleId>(src.eyeStyle, ["round", "almond", "narrow", "upturned", "droopy", "big", "cat", "sleepy"], d.eyeStyle),
    eyeColor: pickEnum<EyeColorId>(src.eyeColor, EYE_COLOR_HEX, d.eyeColor),
    eyeColorRight: rightPick === NO_RIGHT ? null : rightPick,
    lipStyle: pickEnum<LipStyleId>(src.lipStyle, ["thin", "plump", "wide", "small", "cupid", "neutral", "pouty", "sharp"], d.lipStyle),
    // 头型滑杆：±1 夹紧，缺省 0（=无形变，旧工程零改动加载）
    headWidth: clampSigned(src.headWidth, d.headWidth),
    headHeight: clampSigned(src.headHeight, d.headHeight),
    jawWidth: clampSigned(src.jawWidth, d.jawWidth),
    cheekbone: clampSigned(src.cheekbone, d.cheekbone),
    chin: clampSigned(src.chin, d.chin),
    hairAccessory: pickEnum<HairAccessoryId>(src.hairAccessory, ACCESSORY_META, d.hairAccessory),
    accessoryColor: pickHex(src.accessoryColor, d.accessoryColor) as string,
    accessoryColor2: pickHex(src.accessoryColor2, d.accessoryColor2) as string,
    skinTone: pickHex(src.skinTone, d.skinTone) as string,
    blush: pickHex(src.blush, d.blush),
    blushAlpha: clamp01(src.blushAlpha, d.blushAlpha),
    eyeshadow: pickHex(src.eyeshadow, d.eyeshadow),
    eyeshadowAlpha: clamp01(src.eyeshadowAlpha, d.eyeshadowAlpha),
    lipColor: pickHex(src.lipColor, d.lipColor),
    lipAlpha: clamp01(src.lipAlpha, d.lipAlpha),
    eyeliner: pickHex(src.eyeliner, d.eyeliner),
    faceMark: pickHex(src.faceMark, d.faceMark),
  };
}

/**
 * 表情强度混合：把四个五官滑杆相对「平静」的偏移量按 emotionIntensity 缩放。
 * 0 = 完全回到平静，1 = 完全保留当前值（含用户单点微调）。
 * emotionIntensity 的**唯一消费点**（faceHeadParts.makeFacialFeatures 入口调用），
 * 否则该滑杆是死参数。
 */
export function blendEmotion(p: FaceParams): FaceParams {
  const k = p.emotionIntensity;
  if (k === 1) return p;
  const n = EMOTION_PRESETS.neutral;
  const mix = (v: number, base: number) => base + (v - base) * k;
  return {
    ...p,
    browLift: mix(p.browLift, n.browLift),
    eyeOpen: mix(p.eyeOpen, n.eyeOpen),
    mouthOpen: mix(p.mouthOpen, n.mouthOpen),
    mouthCurve: mix(p.mouthCurve, n.mouthCurve),
  };
}

/** 参数是否等于默认（供 UI 显示「已修改」标记，避免无意义写库） */
export function isDefaultFaceParams(p: FaceParams): boolean {
  const d = DEFAULT_FACE_PARAMS;
  return (Object.keys(d) as (keyof FaceParams)[]).every((k) => p[k] === d[k]);
}

/**
 * 确定性伪随机（mulberry32）—— 供「随机捏脸」使用。
 * 铁律：绝不使用 Math.random()。同 seed 结果恒等，便于复现与回归测试。
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 字符串 → 32 位种子（FNV-1a；与项目 id 哈希配色同族算法） */
export function hashSeed(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

/**
 * 随机捏脸（确定性）。
 * @param seedKey 种子来源（角色 id 或用户点「随机」时的自增计数）
 * @param locked  被锁定的字段名集合（锁定的字段保持原值 —— 对应「锁定单点重 roll」）
 * @param base    基线（通常是当前卡片上的值）
 */
export function randomFaceParams(
  seedKey: string,
  locked: ReadonlySet<keyof FaceParams> = new Set(),
  base: FaceParams = DEFAULT_FACE_PARAMS,
): FaceParams {
  const rnd = mulberry32(hashSeed(seedKey));
  const pick = <T,>(arr: readonly T[]): T => arr[Math.floor(rnd() * arr.length)];
  const emotions = Object.keys(EMOTION_PRESETS) as FaceEmotionId[];
  const brows = ["flat", "arch", "angry", "sad", "thin", "thick", "round", "short"] as BrowStyleId[];
  const eyes = ["round", "almond", "narrow", "upturned", "droopy", "big", "cat", "sleepy"] as EyeStyleId[];
  const lips = ["thin", "plump", "wide", "small", "cupid", "neutral", "pouty", "sharp"] as LipStyleId[];
  const accs = Object.keys(ACCESSORY_META) as HairAccessoryId[];
  const eyeColors = Object.keys(EYE_COLOR_HEX) as EyeColorId[];

  const next: FaceParams = {
    ...base,
    emotion: pick(emotions),
    emotionIntensity: 0.7 + rnd() * 0.3,
    browStyle: pick(brows),
    // P3 优化（2026-10-13）：随机时连眉色一起 roll（之前一直复用 base，眉色卡死）。
    // 锁定字段会在后续循环还原，不影响「锁定」功能。
    browColor: pick(HAIR_PALETTE),
    eyeStyle: pick(eyes),
    eyeColor: pick(eyeColors),
    eyeColorRight: rnd() < 0.12 ? pick(eyeColors) : null,
    lipStyle: pick(lips),
    // 头型：温和区间（±0.6），避免随机直接捏出撕裂几何
    headWidth: (rnd() - 0.5) * 1.2,
    headHeight: (rnd() - 0.5) * 1.0,
    jawWidth: (rnd() - 0.5) * 1.2,
    cheekbone: (rnd() - 0.5) * 1.0,
    chin: (rnd() - 0.5) * 1.0,
    hairAccessory: pick(accs),
    accessoryColor: pick(MAKEUP_PALETTE),
    accessoryColor2: pick(MAKEUP_PALETTE),
    skinTone: pick(SKIN_PALETTE),
    blush: rnd() < 0.5 ? pick(MAKEUP_PALETTE) : null,
    blushAlpha: 0.2 + rnd() * 0.5,
    eyeshadow: rnd() < 0.5 ? pick(MAKEUP_PALETTE) : null,
    eyeshadowAlpha: 0.25 + rnd() * 0.5,
    lipColor: rnd() < 0.6 ? pick(MAKEUP_PALETTE) : null,
    lipAlpha: 0.5 + rnd() * 0.4,
    eyeliner: rnd() < 0.35 ? "#111111" : null,
    faceMark: rnd() < 0.2 ? pick(MAKEUP_PALETTE) : null,
  };
  // 表情预设联动的四个滑杆跟随新表情（除非用户显式锁定）
  const pres = EMOTION_PRESETS[next.emotion];
  if (!locked.has("browLift")) next.browLift = pres.browLift;
  if (!locked.has("eyeOpen")) next.eyeOpen = pres.eyeOpen;
  if (!locked.has("mouthOpen")) next.mouthOpen = pres.mouthOpen;
  if (!locked.has("mouthCurve")) next.mouthCurve = pres.mouthCurve;

  // 锁定字段还原
  for (const k of locked) {
    (next as Record<string, unknown>)[k] = base[k];
  }
  return normalizeFaceParams(next);
}

/** 序列化（存角色库字段用；不丢字段、保持稳定 key 顺序便于 diff） */
export function serializeFaceParams(p: FaceParams): string {
  return JSON.stringify(normalizeFaceParams(p));
}

/** 反序列化（容错；坏 JSON 返回默认值，绝不抛给 UI 层） */
export function deserializeFaceParams(text: unknown): FaceParams {
  if (typeof text !== "string" || !text.trim()) return { ...DEFAULT_FACE_PARAMS };
  try {
    return normalizeFaceParams(JSON.parse(text));
  } catch {
    return { ...DEFAULT_FACE_PARAMS };
  }
}
