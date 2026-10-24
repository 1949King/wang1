/**
 * 咬合缝 — Bond Seam（无感化版）
 *
 * 2026-09-16 用户裁定：吸附视觉「无感化」，对齐 Windows 磁贴手感——
 * 静止吸附零视觉残留（不画缝/胶囊/文字），贴合就贴合，画面保持干净。
 *
 * 仅保留两类**瞬态**反馈（松手即消失，不构成持久干扰）：
 *   1. 拖拽拉扯中的阻力提示：细线（拉伸中 琥珀 #fbbf24 / 即将断开 红 #f87171），
 *      解释三段式阻力手感（为什么拖不动 / 绷住了）；拉扯越深线越长越细。
 *   2. 落座 / 断裂的一次性细闪光（无文字胶囊）：一瞬即逝的确认感。
 *
 * 位置使用流坐标（与 MagneticLines 一致）。
 */

import { memo } from "react";
import {
  BOND_COLORS,
  type Bond,
  type BondFlash,
  type BondState,
} from "./types";

interface SnapSeamProps {
  /** 当前画布上所有咬合关系 */
  bonds: Bond[];
  /** 拖拽中的咬合状态（拉扯阶段 / 进度） */
  bondState: BondState;
  /** 落座 / 断裂的一次性闪光 */
  flash: BondFlash | null;
}

/** 拉扯细线基础厚度（px）——无感化：从旧版 9px 粗色带降到 3px 细线 */
const SEAM_T = 3;
/** 拉伸时的最大加长量（两端各加 / px） */
const MAX_STRETCH = 13;
/** 闪光色带厚度（px）——一次性动画，比旧版 16px 收敛 */
const FLASH_T = 8;

interface SeamGeom {
  /** 色带矩形 */
  band: { x: number; y: number; w: number; h: number };
  /** 中心点 */
  cx: number;
  cy: number;
  /** 细线端点（拉伸方向的两侧端点） */
  ends: [{ x: number; y: number }, { x: number; y: number }];
}

function seamGeom(bond: Bond, grow: number, thickness: number): SeamGeom {
  const { seam, axis } = bond;
  if (axis === "vertical") {
    const cx = seam.x;
    const cy = seam.y + seam.h / 2;
    const y0 = seam.y - grow;
    const y1 = seam.y + seam.h + grow;
    return {
      cx,
      cy,
      band: { x: cx - thickness / 2, y: y0, w: thickness, h: y1 - y0 },
      ends: [
        { x: cx, y: y0 },
        { x: cx, y: y1 },
      ],
    };
  }
  const cx = seam.x + seam.w / 2;
  const cy = seam.y;
  const x0 = seam.x - grow;
  const x1 = seam.x + seam.w + grow;
  return {
    cx,
    cy,
    band: { x: x0, y: cy - thickness / 2, w: x1 - x0, h: thickness },
    ends: [
      { x: x0, y: cy },
      { x: x1, y: cy },
    ],
  };
}

function SnapSeamImpl({ bonds, bondState, flash }: SnapSeamProps) {
  const activeKey = bondState.bond?.key ?? null;

  // ── 无感化核心：静止咬合（idle）一律不渲染 ──
  // 只有「正在被拉扯」的咬合才给瞬态细线；平时画面零残留。
  const pulling = bonds.filter(
    (b) => b.key === activeKey && (bondState.phase === "stretching" || bondState.phase === "strained"),
  );

  if (pulling.length === 0 && !flash) return null;

  return (
    <svg
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        zIndex: 13,
        overflow: "visible",
      }}
    >
      {/* ── 拉扯中的瞬态细线（拉伸中琥珀 / 临界红）── */}
      {pulling.map((bond) => {
        const strained = bondState.phase === "strained";
        const color = strained ? BOND_COLORS.strained : BOND_COLORS.stretching;
        // 拉得越开：线越长（grow）越细（3 → 1.5），「绷住」的手感被看见
        const grow = bondState.strain * MAX_STRETCH;
        const thickness = Math.max(1.5, SEAM_T - bondState.strain * 1.5);
        const g = seamGeom(bond, grow, thickness);
        return (
          <g key={bond.key} opacity={0.85}>
            <rect
              x={g.band.x}
              y={g.band.y}
              width={g.band.w}
              height={g.band.h}
              rx={thickness / 2}
              fill={color}
            />
            {/* 两端小圆点：提示「这条缝正在被拉开」的范围 */}
            {g.ends.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={2} fill={color} />
            ))}
          </g>
        );
      })}

      {/* ── 落座 / 断裂一次性细闪光（无文字胶囊，动画播完即消失）── */}
      {flash ? (
        <g key={`flash_${flash.at}`}>
          {(() => {
            const color =
              flash.kind === "snap" ? BOND_COLORS.snapFlash : BOND_COLORS.breakFlash;
            const g = seamGeom(flash.bond, 4, FLASH_T);
            return (
              <>
                <rect
                  className="sg-seam-flash"
                  x={g.band.x}
                  y={g.band.y}
                  width={g.band.w}
                  height={g.band.h}
                  rx={FLASH_T / 2}
                  fill={color}
                />
                <rect
                  className="sg-seam-flash-ring"
                  x={g.band.x - 5}
                  y={g.band.y - 5}
                  width={g.band.w + 10}
                  height={g.band.h + 10}
                  rx={(FLASH_T + 10) / 2}
                  fill="none"
                  stroke={color}
                  strokeWidth={2}
                />
              </>
            );
          })()}
        </g>
      ) : null}
    </svg>
  );
}

export const SnapSeam = memo(SnapSeamImpl);
