/**
 * 让位落位预览 — SlotGhost
 *
 * 拖拽卡准备落进一个被占用的空位时，在被推开的那张卡的**原位置**上
 * 画一个虚线空位框，告诉用户「松手后你会占住这里」。
 *
 * 与 MagneticLines（贴合占位缝）的分工：
 *   - MagneticLines 画「贴合**接缝**」——一条线，表示两卡将并排贴住；
 *   - SlotGhost 画「让位**坑位**」——一个整卡外框，表示这张卡要让开。
 *   两者可以同时出现（吸到某卡右缘 + 那张卡所在行需要让位）。
 *
 * ⚠️ 纯展示组件：
 *   - 不做任何磁吸 / 位移计算（规划由 reflow.planReflow 纯函数负责）
 *   - 不持有状态、不派发事件（pointerEvents: none）
 *   - 拖拽中只做**预览**，绝不驱动真实位移（让位落位在松手时统一执行）
 *
 * 坐标处理：用 ReactFlow 的 ViewportPortal 把内容放进「视口坐标系」，
 * 这样直接写流坐标即可，无需自己算 transform（也不依赖 useViewport，
 * 避免在 CanvasShell 的 JSX 作用域里踩 provider 边界）。
 */

import { memo } from "react";
import { ViewportPortal } from "@xyflow/react";
import type { ReflowPlan } from "./reflow";

export interface SlotGhostProps {
  /** 由 planReflow 算出的让位规划；ghost 为 null 时不渲染 */
  plan: ReflowPlan;
}

/** 与 MagneticLines 同一套蓝（#378ADD）：让位与吸附同属「即将落座」的视觉族 */
const GHOST_COLOR = "#378ADD";
/** 坑位填充色（极淡，只做存在感提示，不遮挡底下的卡） */
const GHOST_FILL = "rgba(55, 138, 221, 0.06)";
/** 虚线节奏 */
const DASH = "8 6";

function SlotGhostImpl({ plan }: SlotGhostProps) {
  const ghost = plan.ghost;
  if (!ghost) return null;

  return (
    <ViewportPortal>
      <div
        style={{
          position: "absolute",
          left: ghost.x,
          top: ghost.y,
          width: ghost.w,
          height: ghost.h,
          border: `2px dashed ${GHOST_COLOR}`,
          borderRadius: 16,
          background: GHOST_FILL,
          pointerEvents: "none",
          opacity: 0.9,
          zIndex: 6,
        }}
        aria-hidden
      />
    </ViewportPortal>
  );
}

export const SlotGhost = memo(SlotGhostImpl);
export default SlotGhost;
