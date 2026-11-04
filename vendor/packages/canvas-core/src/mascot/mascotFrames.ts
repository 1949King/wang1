/**
 * 桌宠表情帧清单（单一真源）+ 状态 → 帧的选择与回落。
 *
 * 为什么需要这一层
 * ================
 * 表情帧是**可选扩展素材**：新帧（思考/睡眼/委屈/期待/得意）在美术产出前，
 * 代码必须能正常运行，且**不得假装有**——缺素材时诚实回落到 neutral，
 * 并在 `data-frame` 上如实标出「实际渲染的帧」。这样：
 *   1. 美术交付后只改本表 ready=true，组件零改动自动点亮；
 *   2. `_verify/check_mascot_assets.py` 做双向校验（声明与磁盘一致 + 同画布 + 质心对齐），
 *      防止「声明 ready 但文件缺失」的运行时 404，也防止「文件在但没登记」的死资源。
 *
 * 纪律
 * ====
 * - 文件名固定 `pet_<id>.png`，全部 316×480 同画布、透明底；
 * - 质心与 neutral 的偏差 ≤ 2px（叠放不位移，否则眨眼/换表情时整个人会「跳一下」）；
 * - `proud`（得意）**只用于品牌展示/表情包，不接状态机**——不为接而接。
 */
import type { PetStatus } from "./mascotMotion";

/** 帧 id：前三个是已上线的必备帧，其余是待生成的可选帧。 */
export type FrameId =
  | "neutral"
  | "blink"
  | "cheer"
  | "thinking"
  | "sleepy"
  | "sad"
  | "surprised"
  | "proud";

export interface FrameSpec {
  /** public/mascot/ 下的文件名。 */
  file: string;
  /** 素材是否已入库。false = 待生成，运行时回落到 neutral。 */
  ready: boolean;
  /** 设计要点（给美术/AI 生图的对照，不进运行时）。 */
  note?: string;
}

export const PET_FRAMES: Record<FrameId, FrameSpec> = {
  neutral: { file: "pet_neutral.png", ready: true, note: "自然平和（主帧）" },
  blink: { file: "pet_blink.png", ready: true, note: "眨眼" },
  cheer: { file: "pet_cheer.png", ready: true, note: "大笑挥手（成功）" },
  thinking: { file: "pet_thinking.png", ready: false, note: "思考：眉微皱、视线偏上" },
  sleepy: { file: "pet_sleepy.png", ready: false, note: "睡眼：眼半闭、嘴角放松" },
  sad: { file: "pet_sad.png", ready: false, note: "委屈：耳垂下、眉尾下垂" },
  surprised: { file: "pet_surprised.png", ready: false, note: "期待：睁大眼、瞳孔放大" },
  proud: { file: "pet_proud.png", ready: false, note: "得意：只用于品牌/表情包，不接状态机" },
};

/** 帧素材的运行时 URL（public/mascot/ 下；BASE_URL 兜底为 "/"）。 */
export function frameUrl(id: FrameId): string {
  const base = import.meta.env?.BASE_URL ?? "/";
  return base + "mascot/" + PET_FRAMES[id].file;
}

/**
 * 状态 → 首选帧（sleepy 表现层优先）。
 *
 * 注意：这里返回的是**首选**，不代表素材一定存在 —— 渲染层必须再过一道
 * `resolvedFrame()`，否则缺素材时会出现空图/404。
 */
export function pickFrame(status: PetStatus, sleepy: boolean): FrameId {
  if (sleepy) return "sleepy";
  switch (status) {
    case "thinking":
      return "thinking";
    case "awaiting":
      return "surprised";
    case "error":
      return "sad";
    case "success":
      return "cheer";
    default:
      return "neutral";
  }
}

/** 把首选帧收敛到「当前真实拥有的帧」——缺素材时诚实回落 neutral。 */
export function resolvedFrame(id: FrameId): FrameId {
  return PET_FRAMES[id].ready ? id : "neutral";
}

/** 需要渲染的额外帧（除 neutral/blink 外的已就绪帧）——供组件按需挂 `<img>`。 */
export function readyExtraFrames(): FrameId[] {
  return (Object.keys(PET_FRAMES) as FrameId[]).filter(
    (id) => id !== "neutral" && id !== "blink" && PET_FRAMES[id].ready,
  );
}
