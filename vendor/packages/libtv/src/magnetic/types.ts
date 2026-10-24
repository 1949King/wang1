/**
 * 磁吸画布类型定义
 *
 * 磁吸系统在 CanvasShell 层注入，不侵入节点组件。
 * 拖拽节点时计算磁力，靠近目标节点产生吸附效果。
 */

/** 磁吸等级（2026-09-17 用户裁定：新增 instant——拖拽中边距 < instantDistance 直接 snap，不走渐进） */
export type MagneticLevel = "none" | "weak" | "medium" | "strong" | "instant";

/** 空间方向（纯物理方位，无语义；2026-09-18 方案 A 剥离业务语义） */
export type SpatialDirection =
  | "left"    // 左
  | "right"   // 右
  | "top"     // 上
  | "bottom"  // 下
  | "stack";  // 层叠

/** 磁吸配置 */
export interface MagneticConfig {
  /** 弱磁吸距离（px），超出此距离无磁力（对齐 spec：80px） */
  weakDistance: number;
  /** 中磁吸距离（px）（对齐 spec：50px） */
  mediumDistance: number;
  /** 强磁吸距离（px），进入即吸附（对齐 spec：25px，落座） */
  strongDistance: number;
  /** 瞬时磁吸距离（px），进入即拖拽中直接 snap，不走渐进吸引（2026-09-17 用户裁定，对齐 Win11 磁贴手感）；默认 10 */
  instantDistance: number;
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
  /** 咬合判定容差（px）：两卡边距 ≤ 此值即视为「已吸附」，用于渲染咬合缝 */
  bondTolerance: number;
  /** 断裂前的给出比例：拉力超出拉伸段后，卡片只让出超出量的这个比例（制造「绷住」的阻力感） */
  bondGiveRatio: number;
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
 * 方向语义已剥离（2026-09-18 方案 A）
 *
 * 早期迭代曾把空间方向（left/right/top/bottom/stack）硬套上「输入/输出/对照/分支」
 * 等业务语义（DIRECTION_SEMANTICS），但用户从未要求过这类「对照关系」——
 * 属于过度设计。磁吸回到纯空间关系：方向只表示物理方位，吸附反馈统一为蓝色占位缝。
 */

/** 默认磁吸配置（距离阈值：2026-09-17 用户裁定放大 weak 80→120、strong 25→60；新增 instant=10；medium 50 不动；吸引力曲线/过冲/回弹/拉伸/断裂全部不变） */
export const DEFAULT_MAG_CONFIG: MagneticConfig = {
  weakDistance: 120,
  mediumDistance: 50,
  strongDistance: 60,
  instantDistance: 10,
  attractionCurve: 2.0,
  snapAnimationMs: 200,
  overshootPx: 5,
  stretchThreshold: 30,
  breakThreshold: 50,
  bondTolerance: 2,
  bondGiveRatio: 0.28,
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
//  咬合 — Bond（吸附成功之后的持久贴合关系）
// ════════════════════════════════════════════════════════════════════════
//  说明：咬合不是「拖拽中的临时磁吸」，而是两张卡真正贴合后的结果状态。
//  它由几何关系推导（边距 ≤ bondTolerance 且投影重叠），因此刷新后依然成立，
//  无需落盘。画面上的表现就是「咬合缝」——那条明显的接缝色带。

/** 两卡之间的咬合关系 */
export interface Bond {
  /** 无向键：两个 id 排序后拼接，保证同一对只出现一次 */
  key: string;
  aId: string;
  bId: string;
  /** b 相对 a 的方向（右/左/下/上） */
  side: SpatialDirection;
  /** 贴合缝走向：vertical = 左右贴合（缝是竖的）；horizontal = 上下贴合（缝是横的） */
  axis: "vertical" | "horizontal";
  /**
   * 咬合缝的中心线（流坐标）：
   * vertical 时 w = 0，用 (x, y, h) 描述竖线；horizontal 时 h = 0，用 (x, y, w) 描述横线。
   * 渲染层自行决定缝的厚度（以中心线为准左右/上下各铺一半）。
   */
  seam: { x: number; y: number; w: number; h: number };
}

/** 咬合在拖拽分离过程中的阶段 */
export type BondPhase = "idle" | "stretching" | "strained";

/** 咬合拖拽状态 */
export interface BondState {
  /** 当前正在被拉扯的咬合（拖拽中且尚未断裂） */
  bond: Bond | null;
  phase: BondPhase;
  /** 0~1 拉扯进度：0 = 完全贴合，1 = 到达断裂阈值 */
  strain: number;
  /** 是否正在施加位移压制（卡片被「粘住」） */
  resisted: boolean;
}

/** 咬合的一次性事件（用于落座 / 断裂闪光） */
export interface BondFlash {
  kind: "snap" | "break";
  bond: Bond;
  /** 事件时间戳（performance.now()） */
  at: number;
}

export const IDLE_BOND_STATE: BondState = {
  bond: null,
  phase: "idle",
  strain: 0,
  resisted: false,
};

/** 咬合缝的配色：稳定 / 拉伸 / 临界 / 落座闪光 / 断裂闪光 */
export const BOND_COLORS = {
  stretching: "#fbbf24",
  strained: "#f87171",
  snapFlash: "#4ade80",
  breakFlash: "#f87171",
  /** 缝上的白色高光，保证在深色卡面上也足够醒目 */
  highlight: "#ffffff",
} as const;

// ════════════════════════════════════════════════════════════════════════
//  软连接 — Soft Connection
// ════════════════════════════════════════════════════════════════════════

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

