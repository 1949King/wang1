/**
 * 磁力线可视化层
 *
 * 在 ReactFlow 画布上层叠加 SVG，拖拽节点靠近目标时：
 * - 绘制弯曲发光磁力线
 * - 线条粗细/颜色随磁吸等级变化
 * - 两端有发光圆点
 */

import { memo } from "react";
import type { Node } from "@xyflow/react";
import { DIRECTION_SEMANTICS, CARD_SIZE, type MagneticDragState, type SpatialDirection } from "./types";

interface MagneticLinesProps {
  nodes: Node[];
  magState: MagneticDragState;
  draggingId: string | null;
}

/** 获取节点中心坐标 */
function getNodeCenter(node: Node): { x: number; y: number } {
  return {
    x: node.position.x + CARD_SIZE.width / 2,
    y: node.position.y + CARD_SIZE.height / 2,
  };
}

function MagneticLinesImpl({ nodes, magState, draggingId }: MagneticLinesProps) {
  if (magState.level === "none" || !magState.targetId || !draggingId) return null;

  const sourceNode = nodes.find((n) => n.id === draggingId);
  const targetNode = nodes.find((n) => n.id === magState.targetId);
  if (!sourceNode || !targetNode) return null;

  const src = getNodeCenter(sourceNode);
  const tgt = getNodeCenter(targetNode);

  // 曲线控制点
  const midX = (src.x + tgt.x) / 2;
  const midY = (src.y + tgt.y) / 2 - 20;

  // 对齐绿线：strong（落座/对齐）用绿色辅助线，其余用青色
  const color = magState.level === "strong" ? "#4ade80" : "#22d3ee";
  const opacity = magState.level === "strong" ? 0.9 : magState.level === "medium" ? 0.6 : 0.3;
  const strokeWidth = magState.level === "strong" ? 3 : magState.level === "medium" ? 2 : 1;
  const dashArray = magState.level === "strong" ? "none" : "6 4";

  const dir: SpatialDirection | null = magState.direction;
  const sem = dir ? DIRECTION_SEMANTICS[dir] : null;
  const labelX = magState.snapX + CARD_SIZE.width / 2;
  const labelY = magState.snapY - 24;

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
        <filter id="mag-glow">
          <feGaussianBlur stdDeviation="2" result="coloredBlur" />
          <feMerge>
            <feMergeNode in="coloredBlur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* 磁力线 */}
      <path
        d={`M ${src.x} ${src.y} Q ${midX} ${midY} ${tgt.x} ${tgt.y}`}
        stroke={color}
        strokeWidth={strokeWidth}
        fill="none"
        opacity={opacity}
        filter="url(#mag-glow)"
        strokeDasharray={dashArray}
      />

      {/* 两端发光圆点 */}
      {[ [src.x, src.y], [tgt.x, tgt.y] ].map(([cx, cy], i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={magState.level === "strong" ? 6 : 4}
          fill={color}
          filter="url(#mag-glow)"
          opacity={opacity}
        />
      ))}

      {/* 方向语义标签 */}
      {sem ? (
        <g>
          <rect
            x={labelX - 50}
            y={labelY - 14}
            width={100}
            height={20}
            rx={4}
            fill={sem.color}
            opacity={opacity}
          />
          <text
            x={labelX}
            y={labelY}
            textAnchor="middle"
            fontSize={11}
            fontWeight={600}
            fill="#0f1115"
            opacity={opacity}
          >
            {sem.label}
          </text>
        </g>
      ) : null}
    </svg>
  );
}

export const MagneticLines = memo(MagneticLinesImpl);
