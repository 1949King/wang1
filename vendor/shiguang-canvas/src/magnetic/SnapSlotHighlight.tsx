/**
 * 六向槽位高亮 — 拖拽卡片靠近目标时，高亮目标卡片的对应槽位
 *
 * 对齐 spec 4.3：
 * - left  → 目标左侧「输入槽」（输入/参考）
 * - right → 目标右侧「输出槽」（输出/接续）
 * - top   → 目标上方「并行区」
 * - bottom→ 目标下方「分支区」
 * - stack → 层叠通道（拖到卡片上），由层叠徽章承载，不在此高亮
 *
 * 通过 ReactFlow children 绝对定位渲染，不侵入节点组件。
 * 位置使用流坐标（与 MagneticLines / StackBadge 一致）。
 */

import { memo } from "react";
import type { CSSProperties } from "react";
import { useReactFlow } from "@xyflow/react";
import { DIRECTION_SEMANTICS, type SpatialDirection, type MagneticLevel } from "./types";

interface SnapSlotHighlightProps {
  targetId: string;
  direction: SpatialDirection;
  level: MagneticLevel;
}

/** 槽位条厚度（px） */
const SLOT_THICKNESS = 5;

function SnapSlotHighlightImpl({ targetId, direction, level }: SnapSlotHighlightProps) {
  const { getNode } = useReactFlow();
  const target = getNode(targetId);
  if (!target || direction === "stack") return null;

  const semantic = DIRECTION_SEMANTICS[direction];
  const w = target.width || 240;
  const h = target.height || 200;
  const x = target.position.x;
  const y = target.position.y;
  const strong = level === "strong";

  // 槽位条：贴目标卡片对应边缘的发光条
  let strip: CSSProperties = {
    position: "absolute",
    background: semantic.color,
    boxShadow: strong ? `0 0 16px ${semantic.color}` : "none",
    borderRadius: 4,
    opacity: strong ? 1 : 0.72,
    pointerEvents: "none",
    zIndex: 15,
  };
  // 语义标签：浮在槽位外侧（translate 仅做锚点校正）
  let label: CSSProperties = {
    position: "absolute",
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "3px 9px",
    borderRadius: 12,
    background: "rgba(12,16,22,0.92)",
    border: `1px solid ${semantic.color}66`,
    color: semantic.color,
    fontSize: 10,
    fontWeight: 600,
    whiteSpace: "nowrap",
    pointerEvents: "none",
    zIndex: 16,
  };

  switch (direction) {
    case "left":
      strip = { ...strip, left: x - SLOT_THICKNESS, top: y, width: SLOT_THICKNESS, height: h };
      label = { ...label, left: x - 10, top: y + h / 2, transform: "translate(-100%, -50%)" };
      break;
    case "right":
      strip = { ...strip, left: x + w, top: y, width: SLOT_THICKNESS, height: h };
      label = { ...label, left: x + w + 10, top: y + h / 2, transform: "translate(0, -50%)" };
      break;
    case "top":
      strip = { ...strip, left: x, top: y - SLOT_THICKNESS, width: w, height: SLOT_THICKNESS };
      label = { ...label, left: x + w / 2, top: y - 10, transform: "translate(-50%, -100%)" };
      break;
    case "bottom":
      strip = { ...strip, left: x, top: y + h, width: w, height: SLOT_THICKNESS };
      label = { ...label, left: x + w / 2, top: y + h + 10, transform: "translate(-50%, 0)" };
      break;
  }

  return (
    <>
      <div style={strip} />
      <div style={label}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: semantic.color, flexShrink: 0 }} />
        {semantic.label}
      </div>
    </>
  );
}

export const SnapSlotHighlight = memo(SnapSlotHighlightImpl);