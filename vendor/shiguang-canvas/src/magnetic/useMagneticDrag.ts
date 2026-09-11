/**
 * 磁吸拖拽 Hook
 *
 * 包装 ReactFlow 的 onNodeDrag / onNodeDragStop，
 * 在拖拽过程中计算磁力并偏移节点位置，
 * 在松开时执行吸附动画。
 *
 * 使用方式：
 *   const { onNodeDrag, onNodeDragStop, magState } = useMagneticDrag({
 *     rfRef, enabled, nodes,
 *   });
 *   <ReactFlow onNodeDrag={onNodeDrag} onNodeDragStop={onNodeDragStop} ... />
 */

import { useCallback, useMemo, useRef, useState } from "react";
import type { Node, ReactFlowInstance } from "@xyflow/react";
import { useCanvasStore } from "../store";
import { computeMagnetic, getMagneticOffset, resolveNodeSize } from "./MagneticEngine";
import { SpatialIndex } from "./SpatialIndex";
import { DEFAULT_MAG_CONFIG, type MagneticDragState } from "./types";

interface UseMagneticDragOptions {
  /** 预留：后续版本用于坐标转换 */
  rfRef?: React.MutableRefObject<ReactFlowInstance | null>;
  enabled: boolean;
  nodes: Node[];
}

/** 初始状态：无磁吸 */
const IDLE_STATE: MagneticDragState = {
  level: "none",
  targetId: null,
  direction: null,
  snapX: 0,
  snapY: 0,
};

export function useMagneticDrag({ enabled, nodes }: UseMagneticDragOptions) {
  const [magState, setMagState] = useState<MagneticDragState>(IDLE_STATE);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const draggingIdRef = useRef<string | null>(null);

  // 空间索引：拖拽时只遍历附近候选节点，避免全量 O(n²)
  const spatialIndex = useMemo(() => new SpatialIndex(nodes), [nodes]);

  /** 拖拽中：计算磁力并偏移节点位置 */
  const onNodeDrag = useCallback(
    (_event: React.MouseEvent, draggingNode: Node) => {
      if (!enabled) {
        if (magState.level !== "none") setMagState(IDLE_STATE);
        return;
      }

      draggingIdRef.current = draggingNode.id;
      setDraggingId(draggingNode.id);

      // 用当前中心坐标查空间索引，取邻近候选
      const dragSize = resolveNodeSize(draggingNode);
      const candidates = spatialIndex.queryNear(
        draggingNode.position.x + dragSize.width / 2,
        draggingNode.position.y + dragSize.height / 2,
      );
      const result = computeMagnetic(draggingNode, nodes, DEFAULT_MAG_CONFIG, candidates);

      // 有磁吸时：偏移节点位置（直接改 store 中的 position）
      if (result.level !== "none" && result.targetId) {
        const offset = getMagneticOffset(
          draggingNode.position.x,
          draggingNode.position.y,
          result.snapX,
          result.snapY,
          result.level,
        );

        // 实时偏移：更新节点位置（React Flow 会跟随）
        const newNodes = useCanvasStore.getState().nodes.map((n) =>
          n.id === draggingNode.id
            ? { ...n, position: { x: n.position.x + offset.x, y: n.position.y + offset.y } }
            : n,
        );
        useCanvasStore.setState({ nodes: newNodes });

        setMagState({
          level: result.level,
          targetId: result.targetId,
          direction: result.direction,
          snapX: result.snapX,
          snapY: result.snapY,
        });
      } else {
        if (magState.level !== "none") setMagState(IDLE_STATE);
      }
    },
    [enabled, nodes, magState.level, spatialIndex],
  );

  /** 拖拽结束：强磁吸时执行吸附动画 */
  const onNodeDragStop = useCallback(
    (_event: React.MouseEvent, draggingNode: Node) => {
      if (!enabled) {
        draggingIdRef.current = null;
        return;
      }

      // 强磁吸：吸附到目标位置
      if (magState.level === "strong" && magState.targetId) {
        const startTime = performance.now();
        const startX = draggingNode.position.x;
        const startY = draggingNode.position.y;
        const targetX = magState.snapX;
        const targetY = magState.snapY;
        const duration = DEFAULT_MAG_CONFIG.snapAnimationMs;

        // spring 缓动：先过冲一点再回弹
        function animateStep(now: number) {
          const t = Math.min((now - startTime) / duration, 1);
          const eased = t < 0.5
            ? 4 * t * t * t
            : 1 - Math.pow(-2 * t + 2, 3) / 2;

          // 落座过冲：结束前轻微越过目标再回弹（幅度取配置 overshootPx）
          const overshoot =
            t < 0.7
              ? 0
              : Math.sin(((t - 0.7) * Math.PI) / 0.3) * -DEFAULT_MAG_CONFIG.overshootPx;

          const x = startX + (targetX - startX) * eased + overshoot;
          const y = startY + (targetY - startY) * eased + overshoot;

          const currentNodes = useCanvasStore.getState().nodes;
          const newNodes = currentNodes.map((n) =>
            n.id === draggingNode.id ? { ...n, position: { x, y } } : n,
          );
          useCanvasStore.setState({ nodes: newNodes });

          if (t < 1) {
            requestAnimationFrame(animateStep);
          }
        }
        requestAnimationFrame(animateStep);
      }

      draggingIdRef.current = null;
      setDraggingId(null);
      setMagState(IDLE_STATE);
    },
    [enabled, magState.level, magState.targetId, magState.snapX, magState.snapY],
  );

  return {
    onNodeDrag,
    onNodeDragStop,
    magState,
    draggingId,
  };
}
