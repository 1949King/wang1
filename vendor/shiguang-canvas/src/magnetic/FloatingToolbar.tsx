/**
 * 浮动工具条 — 选中节点时显示在节点上方
 *
 * 快速操作：生成新版本、复制、入轨、删除
 *
 * 不侵入节点组件，通过 ReactFlow children 绝对定位渲染。
 */

import { memo } from "react";
import type { NodeChange } from "@xyflow/react";
import { useCanvasStore } from "../store";
import { analyzeSpatialPattern, autoLayoutSequence, autoLayoutParallel } from "./SpatialAnalyzer";

interface FloatingToolbarProps {
  nodeId: string;
  nodeX: number;
  nodeY: number;
  nodeWidth: number;
  onSendToEditor: () => void;
}

function FloatingToolbarImpl({ nodeId, nodeX, nodeY, nodeWidth, onSendToEditor }: FloatingToolbarProps) {
  const addNode = useCanvasStore((s) => s.addNode);
  const pushLayer = useCanvasStore((s) => s.pushLayer);
  const onNodesChange = useCanvasStore((s) => s.onNodesChange);

  /** 一键整理布局：根据空间模式自动重排所有节点 */
  const handleAutoLayout = () => {
    const state = useCanvasStore.getState();
    const all = state.nodes;
    if (all.length <= 1) return;
    const analysis = analyzeSpatialPattern(all);
    const layout =
      analysis.pattern === "parallel"
        ? autoLayoutParallel(all)
        : autoLayoutSequence(all);
    const map = new Map(layout.map((pt) => [pt.id, pt]));
    const changes: NodeChange[] = all.map((n) => {
      const target = map.get(n.id);
      if (!target || (target.x === n.position.x && target.y === n.position.y)) {
        return { id: n.id, type: "dimensions" as const };
      }
      return {
        id: n.id,
        type: "position" as const,
        position: { x: target.x, y: target.y },
        dragging: false,
      };
    });
    onNodesChange(changes);
  };

  // 生成：推入新版本
  const handleGenerate = () => {
    const state = useCanvasStore.getState();
    const node = state.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    pushLayer(nodeId, { ...node.data });
  };

  // 复制：新增同类型节点
  const handleDuplicate = () => {
    const state = useCanvasStore.getState();
    const node = state.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const kind = (node.data as { kind?: string }).kind;
    if (kind) {
      addNode(kind as any, { x: node.position.x + 30, y: node.position.y + 30 });
    }
  };

  // 删除
  const handleDelete = () => {
    const state = useCanvasStore.getState();
    const newNodes = state.nodes.filter((n) => n.id !== nodeId);
    const newEdges = state.edges.filter(
      (e) => e.source !== nodeId && e.target !== nodeId,
    );
    useCanvasStore.setState({
      nodes: newNodes,
      edges: newEdges,
      selectedId: null,
      dirtyVersion: state.dirtyVersion + 1,
    });
  };

  const btnStyle: React.CSSProperties = {
    width: 32,
    height: 32,
    border: "none",
    background: "transparent",
    color: "#9aa0b4",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: 14,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "all 0.15s",
  };

  return (
    <div
      style={{
        position: "absolute",
        top: nodeY - 42,
        left: nodeX + nodeWidth / 2 - 82,
        display: "flex",
        gap: 2,
        background: "#161922",
        border: "1px solid #2a2f42",
        borderRadius: 10,
        padding: 4,
        boxShadow: "0 4px 20px rgba(0,0,0,0.4)",
        zIndex: 50,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={handleGenerate}
        style={{
          ...btnStyle,
          background: "linear-gradient(135deg, #c084fc, #a855f7)",
          color: "#fff",
          fontWeight: 600,
        }}
        title="生成新版本"
      >
        ▶
      </button>
      <button type="button" onClick={handleDuplicate} style={btnStyle} title="复制">
        ⎘
      </button>
      <button type="button" onClick={onSendToEditor} style={btnStyle} title="发送到时间线">
        ⏬
      </button>
      <button type="button" onClick={handleDelete} style={btnStyle} title="删除">
        🗑
      </button>
      <span style={{ width: 1, background: "#2a2f42", margin: "4px 2px" }} />
      <button type="button" onClick={handleAutoLayout} style={btnStyle} title="一键整理布局">
        🗂
      </button>
    </div>
  );
}

export const FloatingToolbar = memo(FloatingToolbarImpl);
