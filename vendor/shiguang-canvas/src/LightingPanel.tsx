/**
 * LightingPanel.tsx — 电影级灯位选择器（2026-10-06）。
 *
 * 怎么用：选中一个画布节点 → 选主光位 / 轮廓光 → 「套用」⇒ 灯位会写成一段**受管提示词块**
 * 追加进该节点提示词（`〔光照：伦勃朗光（主光 45°/高度 45°/3200K）+ 后上方 45°轮廓〕`）。
 * **写进提示词是因为提示词真的会送到模型** —— 只存字段没人读就是装饰。
 * 「移除灯位」可整块摘掉（`stripLightingBlock`），反复换灯位也不会越写越长。
 *
 * 图例口径（写在界面上，避免歧义）：**俯视图**，镜头在下方（0°），角度**顺时针**增大。
 */
import { useMemo, useState } from "react";

import {
  applyLightingBlock,
  buildLightingBlock,
  KEY_LIGHTS,
  readLightingBlock,
  RIM_LIGHTS,
  stripLightingBlock,
  type LightingChoice,
} from "./lightingPresets";
import { useCanvasStore } from "./store";
import "./lighting.css";

const DEFAULT_CHOICE: LightingChoice = { keyAzimuth: 45, rimName: "后上 45° 轮廓" };

function polar(cx: number, cy: number, r: number, az: number) {
  const t = (az * Math.PI) / 180;
  // 俯视图：0° 在下方（镜头方向），顺时针增大 ⇒ 90° 在左、180° 在上、270° 在右
  return { x: cx - r * Math.sin(t), y: cy + r * Math.cos(t) };
}

export default function LightingPanel({ onClose }: { onClose: () => void }) {
  const selectedId = useCanvasStore((s) => s.selectedId);
  const sel = useCanvasStore((s) => s.nodes.find((n) => n.id === s.selectedId));
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const [choice, setChoice] = useState<LightingChoice>(DEFAULT_CHOICE);
  const [msg, setMsg] = useState("");

  const currentPrompt = String((sel?.data as Record<string, unknown> | undefined)?.prompt || "");
  const currentBlock = readLightingBlock(currentPrompt);
  const preview = useMemo(() => buildLightingBlock(choice), [choice]);

  const cx = 78;
  const cy = 68;
  const R = 46;
  const dot = polar(cx, cy, R, choice.keyAzimuth);

  const apply = () => {
    if (!selectedId) {
      setMsg("请先在画布上选中一个节点");
      return;
    }
    const next = applyLightingBlock(currentPrompt, choice);
    updateNodeData(selectedId, { prompt: next } as never);
    setMsg("已写入该节点提示词");
  };

  const remove = () => {
    if (!selectedId) {
      setMsg("请先选中节点");
      return;
    }
    if (!currentBlock) {
      setMsg("该节点没有我们写入的灯位块");
      return;
    }
    updateNodeData(selectedId, { prompt: stripLightingBlock(currentPrompt) } as never);
    setMsg("已移除灯位块");
  };

  return (
    <div className="lp-panel">
      <header className="lp-head">
        <span className="lp-title">电影级灯位</span>
        <span className="lp-sub">24 主光位 · 9 轮廓光</span>
        <span className="lp-spacer" />
        <button type="button" className="lp-x" onClick={onClose} title="关闭">
          ×
        </button>
      </header>

      <div className="lp-body">
        <div className="lp-diagram">
          <svg viewBox="0 0 156 136" width="156" height="136" role="img">
            <title>灯位俯视图</title>
            <circle cx={cx} cy={cy} r={R} fill="none" stroke="#3a4356" strokeWidth="0.5" />
            <circle cx={cx} cy={cy} r={2.5} fill="#edf3ff" />
            <text x={cx} y={cy + 14} fontSize="9" fill="#9aa4b8" textAnchor="middle">
              主体
            </text>
            {/* 镜头方向 */}
            <path d={`M${cx} ${cy + R + 12} L${cx} ${cy + R}`} stroke="#85b7eb" strokeWidth="0.5" />
            <text x={cx} y={cy + R + 22} fontSize="9" fill="#85b7eb" textAnchor="middle">
              镜头 0°
            </text>
            {/* 主光点 */}
            <circle cx={dot.x} cy={dot.y} r="4.5" fill="#f9c74f" stroke="#8a6a1f" strokeWidth="0.5" />
            <text x={dot.x} y={dot.y - 8} fontSize="9" fill="#f9c74f" textAnchor="middle">
              {choice.keyAzimuth}°
            </text>
            <text x={cx} y="12" fontSize="9" fill="#9aa4b8" textAnchor="middle">
              俯视：角度顺时针
            </text>
          </svg>
          <div className="lp-diagram-note">
            当前：<b>{KEY_LIGHTS.find((k) => k.azimuth === choice.keyAzimuth)?.name}</b>
            <br />
            {KEY_LIGHTS.find((k) => k.azimuth === choice.keyAzimuth)?.note}
          </div>
        </div>

        <div className="lp-controls">
          <div className="lp-row-title">主光位（0–345°，每 15° 一档）</div>
          <div className="lp-chips">
            {KEY_LIGHTS.map((k) => (
              <button
                type="button"
                key={k.azimuth}
                className={`lp-chip${choice.keyAzimuth === k.azimuth ? " on" : ""}`}
                title={`${k.name}｜高度 ${k.height}°｜${k.kelvin}K｜${k.note}`}
                onClick={() => setChoice((c) => ({ ...c, keyAzimuth: k.azimuth }))}
              >
                {k.azimuth}°
              </button>
            ))}
          </div>

          <div className="lp-row-title">轮廓光</div>
          <div className="lp-chips">
            {RIM_LIGHTS.map((r) => (
              <button
                type="button"
                key={r.name}
                className={`lp-chip wide${choice.rimName === r.name ? " on" : ""}`}
                title={`${r.from}｜${r.note}`}
                onClick={() => setChoice((c) => ({ ...c, rimName: r.name }))}
              >
                {r.name}
              </button>
            ))}
          </div>

          <div className="lp-preview" title="这段文字会被追加到节点提示词末尾">
            {preview}
          </div>

          <div className="lp-actions">
            <button type="button" className="lp-apply" onClick={apply}>
              套用到选中节点
            </button>
            <button type="button" className="lp-clear" onClick={remove}>
              移除灯位
            </button>
            <span className="lp-msg">{msg || (currentBlock ? `当前：${currentBlock}` : "")}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
