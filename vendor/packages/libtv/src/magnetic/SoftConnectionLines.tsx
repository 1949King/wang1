/**
 * 软连接可视化层
 *
 * 渲染"潜在血缘"虚线，表示两个节点可能有先后/依赖关系但尚未确认。
 * 每条虚线中点有"固化"按钮，点击后通知父组件转为正式 edge。
 *
 * 2026-09-18 方案 A：剥离方向业务语义——虚线统一中性青色，不再按方向
 * 渲染「参考/输出/对照/分支」等标签（软连接当前恒空，仅保留链路备用）。
 */

import { memo } from "react";
import type { Node } from "@xyflow/react";
import {
  CARD_SIZE,
  type SoftConnection,
} from "./types";

/** 软连接虚线统一色（中性青色，非方向语义色） */
const CONN_COLOR = "#22d3ee";

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

        return (
          <g key={conn.id}>
            {/* 虚线 */}
            <path
              d={`M ${a.x} ${a.y} Q ${midX} ${midY} ${b.x} ${b.y}`}
              stroke={CONN_COLOR}
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
              <circle cx={midX} cy={midY} r={11} fill={CONN_COLOR} opacity={0.85} />
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
          </g>
        );
      })}
    </svg>
  );
}

export const SoftConnectionLines = memo(SoftConnectionLinesImpl);