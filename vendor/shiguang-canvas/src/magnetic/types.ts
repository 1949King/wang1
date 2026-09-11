/**
 * 磁吸画布类型定义
 *
 * 磁吸系统在 CanvasShell 层注入，不侵入节点组件。
 * 拖拽节点时计算磁力，靠近目标节点产生吸附效果。
 */

/** 磁吸等级 */
export type MagneticLevel = "none" | "weak" | "medium" | "strong";

/** 空间方向语义 */
export type SpatialDirection =
  | "left"    // 输入 / 参考
  | "right"   // 输出 / 后续
  | "top"     // 并行 / 对照
  | "bottom"  // 分支 / 备注
  | "stack";  // 层叠 / 版本

/** 磁吸配置 */
export interface MagneticConfig {
  /** 弱磁吸距离（px），超出此距离无磁力（对齐 spec：80px） */
  weakDistance: number;
  /** 中磁吸距离（px）（对齐 spec：50px） */
  mediumDistance: number;
  /** 强磁吸距离（px），进入即吸附（对齐 spec：25px，落座） */
  strongDistance: number;
  /** 吸引力曲线指数（越大越急促） */
  attractionCurve: number;
  /** 吸附动画 / 回弹时长（ms）（对齐 spec：200ms） */
  snapAnimationMs: number;
  /** 过冲距离（px），吸附落座时越过目标再回弹（对齐 spec：5px） */
  overshootPx: number;
  /** 拉伸阈值（px），分离瞬间的弹性拉伸距离（对齐 spec：30px） */
  stretchThreshold: number;
  /** 断裂阈值（px），超过即解除磁吸关系（对齐 spec：50px） */
  breakThreshold: number;
}

/** 磁吸计算结果 */
export interface MagneticResult {
  level: MagneticLevel;
  targetId: string | null;
  direction: SpatialDirection | null;
  /** 建议吸附位置 */
  snapX: number;
  snapY: number;
  /** 与目标的距离 */
  distance: number;
}

/**
 * 方向语义标签
 *
 * 六向语义（对齐 spec 4.3）映射关系：
 * - left / right / top / bottom 四向为空间方位，方向决定语义
 * - 前（导演卡）与 后（历史版本）均通过「拖到卡片上」的层叠动作触发，
 *   物理上都是重叠 → 统一收敛为 stack（层叠/版本）这一方向，
 *   故实现层用 stack 承载 spec 中的「前 / 后」两个语义维度。
 */
export const DIRECTION_SEMANTICS: Record<SpatialDirection, { label: string; color: string }> = {
  left: { label: "输入 · 参考", color: "#22d3ee" },
  right: { label: "输出 · 接续", color: "#4ade80" },
  top: { label: "并行 · 对照", color: "#fbbf24" },
  bottom: { label: "分支 · 备选", color: "#f87171" },
  stack: { label: "前·导演卡 / 后·历史版本", color: "#c084fc" },
};

/** 默认磁吸配置（距离阈值对齐 spec：80/50/25；回弹 200ms；过冲 5px） */
export const DEFAULT_MAG_CONFIG: MagneticConfig = {
  weakDistance: 80,
  mediumDistance: 50,
  strongDistance: 25,
  attractionCurve: 2.0,
  snapAnimationMs: 200,
  overshootPx: 5,
  stretchThreshold: 30,
  breakThreshold: 50,
};

/** 卡片宽高（用于吸附位置计算；对齐 spec：240×200） */
export const CARD_SIZE = { width: 240, height: 200 };

/** 磁吸拖拽状态（在 useMagneticDrag 和 MagneticLines 间传递） */
export interface MagneticDragState {
  level: MagneticLevel;
  targetId: string | null;
  direction: SpatialDirection | null;
  snapX: number;
  snapY: number;
}

// ════════════════════════════════════════════════════════════════════════
//  软连接 — Soft Connection
// ════════════════════════════════════════════════════════════════════════

/** 软连接方向语义标签（复用磁吸方向，但用更口语的表达） */
export const SOFT_CONNECTION_SEMANTICS: Record<SpatialDirection, { label: string; color: string }> = {
  left: { label: "参考此节点", color: "#22d3ee" },
  right: { label: "此节点输出", color: "#4ade80" },
  top: { label: "平行对照", color: "#fbbf24" },
  bottom: { label: "分支备选", color: "#f87171" },
  stack: { label: "版本关系", color: "#c084fc" },
};

/** 软连接记录 — 一条待确认的血缘虚线 */
export interface SoftConnection {
  id: string;
  sourceId: string;
  targetId: string;
  direction: SpatialDirection;
  /** 生成时间戳 */
  createdAt: number;
}

// ════════════════════════════════════════════════════════════════════════
//  层叠系统 — Card Stack
// ════════════════════════════════════════════════════════════════════════

/** 卡片生成状态 */
export type CardStatus =
  | "idle"           // 待执行
  | "generating"     // 生成中
  | "success"        // 成功
  | "failed"         // 失败
  | "pending_review" // 待 AI 审阅
  | "review_passed"  // 审阅通过
  | "review_issues"; // 审阅有问题

/** 卡片层 — 一个版本 */
export interface CardLayer {
  id: string;
  version: number;
  status: CardStatus;
  /** 该层的参数快照（用于对比和混血） */
  params: Record<string, unknown>;
  /** 生成结果 URL（图片/视频等） */
  resultUrl?: string;
  /** AI 质检评分（0~1） */
  qualityScore?: number;
  /** AI 质检发现的问题 */
  issues?: string[];
  createdAt: number;
  isActive: boolean;
}

/** 层叠栈 — 挂在 node.data.stack 上 */
export interface CardStackData {
  layers: CardLayer[];
  activeLayerId: string;
}

/** 默认空层叠 */
export const EMPTY_STACK: CardStackData = {
  layers: [],
  activeLayerId: "",
};

/** 层叠操作类型 */
export type StackAction =
  | { type: "push"; params: Record<string, unknown>; resultUrl?: string }
  | { type: "remove"; layerId: string }
  | { type: "activate"; layerId: string }
  | { type: "swap"; indexA: number; indexB: number }
  | { type: "hybrid"; layerIdA: string; layerIdB: string; weightA: number }
  | { type: "set_status"; layerId: string; status: CardStatus; issues?: string[]; qualityScore?: number };

