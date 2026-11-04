/**
 * 卡片状态徽标 — 显示在节点左上角
 *
 * 状态：idle / generating / success / failed / pending_review / review_passed / review_issues
 *
 * 不侵入节点组件，通过 ReactFlow children 绝对定位渲染。
 */

import { memo } from "react";
import type { CardStatus } from "./types";

interface StatusBadgeProps {
  status: CardStatus;
  qualityScore?: number;
}

const STATUS_CONFIG: Record<CardStatus, { label: string; color: string; bg: string; dot: string }> = {
  idle: {
    label: "待生成",
    color: "#94a3b8",
    bg: "rgba(148,163,184,0.12)",
    dot: "#94a3b8",
  },
  generating: {
    label: "生成中",
    color: "#c084fc",
    bg: "rgba(192,132,252,0.15)",
    dot: "#c084fc",
  },
  success: {
    label: "已完成",
    color: "#34d399",
    bg: "rgba(52,211,153,0.12)",
    dot: "#34d399",
  },
  failed: {
    label: "失败",
    color: "#f87171",
    bg: "rgba(248,113,113,0.12)",
    dot: "#f87171",
  },
  pending_review: {
    label: "AI 审阅中",
    color: "#fbbf24",
    bg: "rgba(251,191,36,0.12)",
    dot: "#fbbf24",
  },
  review_passed: {
    label: "审阅通过",
    color: "#34d399",
    bg: "rgba(52,211,153,0.12)",
    dot: "#34d399",
  },
  review_issues: {
    label: "有问题",
    color: "#fb923c",
    bg: "rgba(251,146,60,0.12)",
    dot: "#fb923c",
  },
};

function StatusBadgeImpl({ status, qualityScore }: StatusBadgeProps) {
  const cfg = STATUS_CONFIG[status];
  const isGenerating = status === "generating" || status === "pending_review";

  return (
    <div
      style={{
        position: "absolute",
        top: 8,
        left: 8,
        display: "flex",
        alignItems: "center",
        gap: 5,
        padding: "3px 8px",
        background: cfg.bg,
        border: `1px solid ${cfg.color}33`,
        borderRadius: 20,
        fontSize: 10,
        fontWeight: 600,
        color: cfg.color,
        pointerEvents: "none",
        zIndex: 5,
        backdropFilter: "blur(8px)",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: cfg.dot,
          boxShadow: isGenerating ? `0 0 8px ${cfg.dot}` : "none",
          animation: isGenerating ? "status-pulse 1.5s ease-in-out infinite" : "none",
        }}
      />
      {cfg.label}
      {qualityScore !== undefined && qualityScore > 0 && (
        <span style={{ marginLeft: 2, opacity: 0.8 }}>
          · {Math.round(qualityScore * 100)}分
        </span>
      )}
      <style>{`
        @keyframes status-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.6; transform: scale(1.3); }
        }
      `}</style>
    </div>
  );
}

export const StatusBadge = memo(StatusBadgeImpl);
