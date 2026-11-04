/**
 * 层叠徽章 + 控制面板
 *
 * 显示在选中节点右上角，展示当前层叠数量。
 * 点击展开层叠列表，可切换版本、删除、混血。
 *
 * 不侵入节点组件，通过 ReactFlow children 绝对定位渲染。
 */

import { memo, useState } from "react";
import { useReactFlow } from "@xyflow/react";
import { useCanvasStore } from "../store";
import type { CardStackData, CardLayer } from "./types";

interface StackBadgeProps {
  nodeId: string;
  stack: CardStackData;
}

function StackBadgeImpl({ nodeId, stack }: StackBadgeProps) {
  const [expanded, setExpanded] = useState(false);
  const { getNode } = useReactFlow();
  const activateLayer = useCanvasStore((s) => s.activateLayer);
  const removeLayer = useCanvasStore((s) => s.removeLayer);
  const hybridLayers = useCanvasStore((s) => s.hybridLayers);

  const node = getNode(nodeId);
  if (!node) return null;

  const count = stack.layers.length;
  if (count <= 1) return null; // 只有 1 层不显示

  const activeIndex = stack.layers.findIndex((l) => l.id === stack.activeLayerId);

  // 状态颜色
  const statusColor = (status: CardLayer["status"]) => {
    switch (status) {
      case "success":
      case "review_passed":
        return "#4ade80";
      case "generating":
      case "pending_review":
        return "#22d3ee";
      case "failed":
        return "#f87171";
      case "review_issues":
        return "#fbbf24";
      default:
        return "#6b7280";
    }
  };

  return (
    <div
      style={{
        position: "absolute",
        top: node.position.y - 12,
        left: node.position.x + (node.width || 280) - 12,
        zIndex: 20,
      }}
    >
      {/* 徽章 */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: "linear-gradient(135deg, #c084fc, #a855f7)",
          color: "#fff",
          border: "none",
          fontSize: 12,
          fontWeight: 700,
          cursor: "pointer",
          boxShadow: "0 2px 12px rgba(192,132,252,0.4)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
        title={`${count} 个版本，点击展开`}
      >
        {count}
      </button>

      {/* 展开面板 */}
      {expanded ? (
        <div
          style={{
            position: "absolute",
            top: 34,
            right: 0,
            width: 220,
            background: "#1c2030",
            border: "1px solid #2a2f42",
            borderRadius: 10,
            padding: 10,
            boxShadow: "0 8px 30px rgba(0,0,0,0.4)",
            zIndex: 30,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "#e6e8ef",
              marginBottom: 8,
              paddingBottom: 6,
              borderBottom: "1px solid #2a2f42",
            }}
          >
            版本层叠 ({count})
          </div>

          <div style={{ maxHeight: 200, overflowY: "auto" }}>
            {[...stack.layers].reverse().map((layer, idx) => {
              const isActive = layer.id === stack.activeLayerId;
              return (
                <div
                  key={layer.id}
                  onClick={() => {
                    activateLayer(nodeId, layer.id);
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 8px",
                    borderRadius: 6,
                    cursor: "pointer",
                    background: isActive ? "rgba(192,132,252,0.15)" : "transparent",
                    border: isActive ? "1px solid rgba(192,132,252,0.3)" : "1px solid transparent",
                    marginBottom: 2,
                    fontSize: 12,
                  }}
                >
                  <div
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: statusColor(layer.status),
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      flex: 1,
                      color: isActive ? "#fff" : "#9aa0b4",
                      fontWeight: isActive ? 600 : 400,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    v{layer.version} · {new Date(layer.createdAt).toLocaleTimeString()}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeLayer(nodeId, layer.id);
                    }}
                    style={{
                      background: "none",
                      border: "none",
                      color: "#6b7280",
                      cursor: "pointer",
                      fontSize: 12,
                      padding: "2px 4px",
                    }}
                    title="删除此版本"
                  >
                    ✕
                  </button>
                </div>
              );
            })}
          </div>

          {/* 混血 */}
          {stack.layers.length >= 2 ? (
            <div
              style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: "1px solid #2a2f42",
              }}
            >
              <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>
                混血当前 & 上一版本
              </div>
              <button
                type="button"
                onClick={() => {
                  const currentIdx = activeIndex;
                  const prevIdx = Math.max(0, currentIdx - 1);
                  if (currentIdx !== prevIdx) {
                    hybridLayers(
                      nodeId,
                      stack.layers[currentIdx].id,
                      stack.layers[prevIdx].id,
                      0.5,
                    );
                  }
                }}
                style={{
                  width: "100%",
                  padding: "6px 10px",
                  background: "linear-gradient(135deg, #c084fc, #22d3ee)",
                  color: "#0f1115",
                  border: "none",
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                ⚡ 混血生成新版本
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export const StackBadge = memo(StackBadgeImpl);
