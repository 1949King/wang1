/**
 * 捏脸模板库（「永劫无间式」捏脸的第一层：先选模板，再微调）。
 *
 * 设计约束
 * ========
 * 1. 模板 = **完整的一套 Partial<FaceParams> 覆盖**，应用时从 DEFAULT 起算，
 *    保证「选模板 → 整张脸立刻变成该风格」，而不是在用户当前脸上打补丁；
 * 2. 全部字段走 faceParams 的枚举/色板白名单，不引入任何新 id（FaceCard 的
 *    normalizeFaceParams 会再兜一层）；
 * 3. 纯数据 + 纯函数：可单测、可导入导出，不碰 store / 不碰 3D。
 *
 * 与「预设」的区别
 * ================
 * - 模板：官方提供、不可变、用于**起步**（本文件）；
 * - 预设：用户自存、可删、存 localStorage（facePresets.ts）。
 */
import {
  ACCESSORY_META,
  BROW_LABELS,
  DEFAULT_FACE_PARAMS,
  EYE_LABELS,
  LIP_LABELS,
  SKIN_LABELS,
  normalizeFaceParams,
  type FaceParams,
} from "./faceParams";

export interface FaceTemplate {
  id: string;
  name: string;
  /** 一句话气质（卡片副标题，不参与生成） */
  tagline: string;
  /** 卡片强调色（由气质决定，不是随机） */
  accent: string;
  /** 只写需要覆盖的字段；其余继承 DEFAULT_FACE_PARAMS */
  params: Partial<FaceParams>;
}

/** 8 套官方模板（名字/气质对齐短剧常见人设，覆盖冷/暖/元气/古典/英气/神秘） */
export const OFFICIAL_FACE_TEMPLATES: FaceTemplate[] = [
  {
    id: "cold-elegant",
    name: "清冷知性",
    tagline: "眼镜 · 猫眼 · 冷白皮",
    accent: "#7f9ce8",
    params: {
      browStyle: "thin", eyeStyle: "cat", lipStyle: "sharp", hairAccessory: "glasses",
      eyeColor: "blue", skinTone: "#fdece4",
      headWidth: -0.08, jawWidth: -0.06, cheekbone: 0.05,
      eyeshadow: "#c9d6f5", eyeshadowAlpha: 0.2, lipColor: "#d94f8a", lipAlpha: 0.26,
    },
  },
  {
    id: "gentle-sister",
    name: "温柔大姐姐",
    tagline: "柳眉 · 杏眼 · 微醺腮红",
    accent: "#e8a0a8",
    params: {
      browStyle: "round", eyeStyle: "almond", lipStyle: "plump", hairAccessory: "hairpin",
      eyeColor: "brown", skinTone: "#f8d9c9",
      headHeight: 0.04, cheekbone: 0.04,
      emotion: "smile", blush: "#f7c6d9", blushAlpha: 0.34, lipColor: "#d94f8a", lipAlpha: 0.24,
    },
  },
  {
    id: "genki-girl",
    name: "元气少女",
    tagline: "挑眉 · 大眼 · 发带",
    accent: "#f7c061",
    params: {
      browStyle: "arch", eyeStyle: "big", lipStyle: "cupid", hairAccessory: "ribbon",
      eyeColor: "amber", skinTone: "#fdece4",
      emotion: "smile", blush: "#f7c6d9", blushAlpha: 0.44,
      accessoryColor: "#eab308", accessoryColor2: "#f5e6d3",
    },
  },
  {
    id: "classic-beauty",
    name: "古典美人",
    tagline: "花钿 · 小口 · 东方",
    accent: "#c9a227",
    params: {
      browStyle: "round", eyeStyle: "almond", lipStyle: "small", hairAccessory: "flower",
      eyeColor: "black", skinTone: "#f8d9c9",
      eyeshadow: "#f08bb4", eyeshadowAlpha: 0.22, lipColor: "#a8326b", lipAlpha: 0.26,
    },
  },
  {
    id: "swordswoman",
    name: "冷面剑客",
    tagline: "剑眉 · 细长眼 · 小麦皮",
    accent: "#8c5230",
    params: {
      browStyle: "angry", eyeStyle: "narrow", lipStyle: "thin", hairAccessory: "none",
      eyeColor: "gold", skinTone: "#e0a882",
      headWidth: -0.08, jawWidth: -0.1,
      emotion: "determined",
    },
  },
  {
    id: "girl-next-door",
    name: "邻家少女",
    tagline: "平眉 · 圆眼 · 耳饰",
    accent: "#e8c4a0",
    params: {
      browStyle: "flat", eyeStyle: "round", lipStyle: "neutral", hairAccessory: "earring",
      eyeColor: "hazel", skinTone: "#fdece4",
      blush: "#f08bb4", blushAlpha: 0.28,
    },
  },
  {
    id: "fox-spirit",
    name: "神秘狐仙",
    tagline: "异色瞳 · 猫眼 · 头纱",
    accent: "#7c3aed",
    params: {
      browStyle: "arch", eyeStyle: "cat", lipStyle: "pouty", hairAccessory: "veil",
      eyeColor: "violet", eyeColorRight: "gold", skinTone: "#fdece4",
      eyeshadow: "#7c3aed", eyeshadowAlpha: 0.22, lipColor: "#a8326b", lipAlpha: 0.3,
    },
  },
  {
    id: "warrior",
    name: "英气女将",
    tagline: "粗眉 · 上挑眼 · 冠冕",
    accent: "#b91c1c",
    params: {
      browStyle: "thick", eyeStyle: "upturned", lipStyle: "wide", hairAccessory: "tiara",
      eyeColor: "brown", skinTone: "#c88a63",
      headWidth: 0.05, jawWidth: 0.04,
      emotion: "determined", lipColor: "#b02a2a", lipAlpha: 0.2,
    },
  },
];

/** 应用模板：从 DEFAULT 起算 + 覆盖 + 统一 normalize（唯一入口）。 */
export function applyFaceTemplate(template: FaceTemplate): FaceParams {
  return normalizeFaceParams({ ...DEFAULT_FACE_PARAMS, ...template.params });
}

/** 当前参数的可读摘要（模板卡与卡片底部共用；纯展示，不参与生成）。 */
export interface FaceTrait {
  key: "brow" | "eye" | "lip" | "accessory" | "skin";
  label: string;
}

export function describeFace(params: FaceParams): FaceTrait[] {
  return [
    { key: "brow", label: BROW_LABELS[params.browStyle] ?? params.browStyle },
    { key: "eye", label: EYE_LABELS[params.eyeStyle] ?? params.eyeStyle },
    { key: "lip", label: LIP_LABELS[params.lipStyle] ?? params.lipStyle },
    { key: "accessory", label: ACCESSORY_META[params.hairAccessory]?.label ?? "无" },
    { key: "skin", label: SKIN_LABELS[params.skinTone] ?? "自定义肤色" },
  ];
}

/** 按 id 取模板（供 AI 生成时传 base_id 校验）。 */
export function findFaceTemplate(id: string | null | undefined): FaceTemplate | undefined {
  if (!id) return undefined;
  return OFFICIAL_FACE_TEMPLATES.find((t) => t.id === id);
}
