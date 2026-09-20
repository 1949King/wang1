/**
 * 磁力占位线可视化层
 *
 * 在 ReactFlow 画布上层叠加 SVG，拖拽节点靠近目标时：
 * - 在目标卡被贴合的那条边上绘制「蓝色占位缝」（直线）
 * - 占位缝 = 即将落座的接缝，替代旧的弯曲发光磁力线（2026-09-18「1+4 结合」裁定）
 * - 纯物理方位反馈，不携带任何方向业务语义（2026-09-18 方案 A 剥离）
 */

import { memo } from "react";
import type { Node } from "@xyflow/react";
import { CARD_SIZE, type MagneticDragState, type SpatialDirection } from "./types";

interface MagneticLinesProps {
  nodes: Node[];
  magState: MagneticDragState;
  draggingId: string | null;
}

/** 占位缝主色（对齐 demo：蓝色 #378ADD） */
const SEAM_COLOR = "#378ADD";
/** 占位缝外圈柔光色（对齐 demo：rgba(55,138,221,0.25)） */
const SEAM_GLOW_OPACITY = 0.25;
const SEAM_GLOW_WIDTH = 10;
const SEAM_CORE_WIDTH = 3;

/** 占位缝几何：目标卡被贴合边的全长直线（start/end 两点）；stack 返回 null 走整卡外框 */
function getSeam(target: { x: number; y: number }, direction: SpatialDirection) {
  const { width, height } = CARD_SIZE;
  switch (direction) {
    case "right": // 目标在右 → 贴其左缘（竖线）
      return { x1: target.x, y1: target.y, x2: target.x, y2: target.y + height };
    case "left": // 目标在左 → 贴其右缘（竖线）
      return { x1: target.x + width, y1: target.y, x2: target.x + width, y2: target.y + height };
    case "bottom": // 目标在下 → 贴其上缘（横线）
      return { x1: target.x, y1: target.y, x2: target.x + width, y2: target.y };
    case "top": // 目标在上 → 贴其下缘（横线）
      return { x1: target.x, y1: target.y + height, x2: target.x + width, y2: target.y + height };
    case "stack":
    default:
      return null;
  }
}

function MagneticLinesImpl({ nodes, magState, draggingId }: MagneticLinesProps) {
  if (magState.level === "none" || !magState.targetId || !draggingId) return null;

  const targetNode = nodes.find((n) => n.id === magState.targetId);
  if (!targetNode || !magState.direction) return null;

  const target = { x: targetNode.position.x, y: targetNode.position.y };
  const seam = getSeam(target, magState.direction);

  return (
    <svg
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        zIndex: 5,
      }}
    >
      <defs>
        <filter id="seam-blur" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
      </defs>

      {seam ? (
        <g>
          {/* 外圈柔光 */}
          <line
            x1={seam.x1}
            y1={seam.y1}
            x2={seam.x2}
            y2={seam.y2}
            stroke={SEAM_COLOR}
            strokeWidth={SEAM_GLOW_WIDTH}
            strokeLinecap="round"
            opacity={SEAM_GLOW_OPACITY}
            filter="url(#seam-blur)"
          />
          {/* 核心亮线 */}
          <line
            x1={seam.x1}
            y1={seam.y1}
            x2={seam.x2}
            y2={seam.y2}
            stroke={SEAM_COLOR}
            strokeWidth={SEAM_CORE_WIDTH}
            strokeLinecap="round"
          />
        </g>
      ) : (
        <g>
          {/* stack：目标整卡外框 */}
          <rect
            x={target.x}
            y={target.y}
            width={CARD_SIZE.width}
            height={CARD_SIZE.height}
            rx={16}
            fill="none"
            stroke={SEAM_COLOR}
            strokeWidth={SEAM_GLOW_WIDTH}
            opacity={SEAM_GLOW_OPACITY}
            filter="url(#seam-blur)"
          />
          <rect
            x={target.x}
            y={target.y}
            width={CARD_SIZE.width}
            height={CARD_SIZE.height}
            rx={16}
            fill="none"
            stroke={SEAM_COLOR}
            strokeWidth={SEAM_CORE_WIDTH}
          />
        </g>
      )}
    </svg>
  );
}

export const MagneticLines = memo(MagneticLinesImpl);
