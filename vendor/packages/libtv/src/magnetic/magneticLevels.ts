/**
 * 磁吸等级元数据 —— 给 UI（StatusBadge / StatusPill / 实时提示）共用。
 *
 * 把「哪个等级配什么文案 / 颜色 / 图标」集中放一处，避免散落在多个
 * 组件里导致显示不一致。新增等级只动这里即可。
 *
 * ⚠️ 颜色集中选了一组在深色 / 浅色背景下都看得清的中性偏暖色（不强制
 * 设计主题，留给设计系统后续统一）。等级名严格对齐 MagneticEngine 的
 * `MagneticResult["level"]` —— "none" / "weak" / "medium" / "strong"。
 */
import type { MagneticResult } from "./types";

export type MagneticLevel = MagneticResult["level"];

export type LevelMeta = {
  /** 短标签（≤3 字，给徽标用） */
  short: string;
  /** 完整中文标签 */
  label: string;
  /** 解释（给小白用户看） */
  hint: string;
  /** 主色：用于文字 / 边框 */
  color: string;
  /** 背景色：用于徽标底色 */
  bg: string;
  /** 等级强度数值（仅 UI 展示元数据；2026-09-18 起不再驱动吸附行为，吸附统一为靠近即直接吸附） */
  strength: number;
  /** 排序权重（UI 排序、过滤用） */
  rank: number;
};

const NONE: LevelMeta = {
  short: "·",
  label: "无磁吸",
  hint: "未靠近任何目标节点",
  color: "#9ca3af",
  bg: "rgba(156,163,175,0.12)",
  strength: 0,
  rank: 0,
};
const WEAK: LevelMeta = {
  short: "弱",
  label: "弱磁吸",
  hint: "靠近目标，但偏移很慢（避免误吸）",
  color: "#3b82f6",
  bg: "rgba(59,130,246,0.18)",
  strength: 0.12,
  rank: 1,
};
const MEDIUM: LevelMeta = {
  short: "中",
  label: "中磁吸",
  hint: "典型吸附：拖拽会主动对齐到目标",
  color: "#f59e0b",
  bg: "rgba(245,158,11,0.20)",
  strength: 0.24,
  rank: 2,
};
const STRONG: LevelMeta = {
  short: "强",
  label: "强磁吸",
  hint: "紧贴即吸：非常靠近时快速锁定",
  color: "#10b981",
  bg: "rgba(16,185,129,0.22)",
  strength: 0.45,
  rank: 3,
};
const INSTANT: LevelMeta = {
  short: "瞬",
  label: "瞬时吸附",
  hint: "边对边立刻贴齐（Win11 磁贴手感）",
  color: "#8b5cf6",
  bg: "rgba(139,92,246,0.22)",
  strength: 1.0,
  rank: 4,
};

const TABLE: Record<MagneticLevel, LevelMeta> = {
  none: NONE,
  weak: WEAK,
  medium: MEDIUM,
  strong: STRONG,
  instant: INSTANT,
};

/** 拿一个等级的完整元数据。level 必传，没匹配时回退到 "none"。 */
export function getLevelMeta(level: MagneticLevel): LevelMeta {
  return TABLE[level] ?? NONE;
}

/** 列出所有等级（按 rank 升序，含 none 在末尾） */
export function listAllLevels(): LevelMeta[] {
  return [WEAK, MEDIUM, STRONG, INSTANT, NONE];
}

/** 把"距离 + 配置"翻译成等级 —— 纯函数，便于测试/调试。 */
export function levelByGap(
  gap: number,
  config: { weakDistance: number; mediumDistance: number; strongDistance: number; instantDistance: number },
): MagneticLevel {
  if (gap < 0) return "none";
  if (gap < config.instantDistance) return "instant";
  if (gap < config.strongDistance) return "strong";
  if (gap < config.mediumDistance) return "medium";
  if (gap < config.weakDistance) return "weak";
  return "none";
}
