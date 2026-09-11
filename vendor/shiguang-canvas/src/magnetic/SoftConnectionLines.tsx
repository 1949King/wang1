/**
 * 软连接可视化层
 *
 * 渲染"潜在血缘"虚线，表示两个节点可能有先后/依赖/对照关系但尚未确认。
 * 每条虚线中点有"固化"按钮，点击后通知父组件转为正式 edge。
 */

import { memo } from "react";
import type { Node } from "@xyflow/react";
import {
  CARD_SIZE,
  SOFT_CONNECTION_SEMANTICS,
  type SoftConnection,
} from "./types";

interface SoftConnectionLinesProps {
  nodes: Node[];
  connections: SoftConnection[];
  onConfirm: (conn: SoftConnection) => void;
  onDismiss: (connId: string) => void;
}

function getNodeCenter(node: Node): { x: number; y: number } {
  return {
    x: node.position.x + CARD_SIZE.width / 2,
    y: node.position.y + CARD_SIZE.height / 2,
  };
}

function SoftConnectionLinesImpl({
  nodes,
  connections,
  onConfirm,
}: SoftConnectionLinesProps) {
  if (connections.length === 0) return null;

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  return (
    <svg
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        zIndex: 4,
      }}
    >
      {connections.map((conn) => {
        const src = nodeMap.get(conn.sourceId);
        const tgt = nodeMap.get(conn.targetId);
        if (!src || !tgt) return null;

        const a = getNodeCenter(src);
        const b = getNodeCenter(tgt);
        const midX = (a.x + b.x) / 2;
        const midY = (a.y + b.y) / 2 - 8;

        const sem = SOFT_CONNECTION_SEMANTICS[conn.direction];

        return (
          <g key={conn.id}>
            {/* 虚线 */}
            <path
              d={`M ${a.x} ${a.y} Q ${midX} ${midY} ${b.x} ${b.y}`}
              stroke={sem.color}
              strokeWidth={1.5}
              strokeDasharray="5 5"
              fill="none"
              opacity={0.55}
            />

            {/* 固化按钮（可点击） */}
            <g
              style={{ cursor: "pointer", pointerEvents: "all" }}
              onClick={(e) => {
                e.stopPropagation();
                onConfirm(conn);
              }}
            >
              <circle cx={midX} cy={midY} r={11} fill={sem.color} opacity={0.85} />
              <text
                x={midX}
                y={midY + 4}
                textAnchor="middle"
                fontSize={11}
                fontWeight={700}
                fill="#0f1115"
              >
                ⚡
              </text>
            </g>

            {/* 标签 */}
            <text
              x={midX}
              y={midY - 14}
              textAnchor="middle"
              fontSize={9}
              fill={sem.color}
              opacity={0.8}
            >
              {sem.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export const SoftConnectionLines = memo(SoftConnectionLinesImpl);