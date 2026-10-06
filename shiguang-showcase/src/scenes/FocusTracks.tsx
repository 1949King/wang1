// 场景四：四条专注轨 —— N 剪辑 / P 画布 / A Agent / D 数字人（含资源配比条）
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, enter, clampInterpolate, sansFont, serifFont } from "../theme";

// 四条专注轨数据（配比来自现行技术文档 §1.3）
const TRACKS = [
  { letter: "N", name: "剪辑", ratio: 30, color: COLORS.cyan, desc: "时间线手感 · 建议入轨 · 冻结区回归" },
  { letter: "P", name: "画布", ratio: 35, color: COLORS.gold, desc: "节点 / 落盘 / 诚实生成" },
  { letter: "A", name: "Agent", ratio: 25, color: COLORS.violet, desc: "白名单 · 确认后执行 · round-trip" },
  { letter: "D", name: "数字人", ratio: 10, color: COLORS.amber, desc: "TTS + 形象 · 画布 digitalHuman 节点" },
];

export const FocusTracks: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headIn = enter(frame, 0, Math.round(0.7 * fps));

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(1000px 700px at 30% 30%, #12182c 0%, ${COLORS.bg} 70%)`,
        fontFamily: sansFont,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div style={{ position: "absolute", top: 80, textAlign: "center", width: "100%" }}>
        <div
          style={{
            opacity: headIn,
            transform: `translateY(${(1 - headIn) * 24}px)`,
            fontFamily: serifFont,
            fontSize: 64,
            fontWeight: 900,
            color: COLORS.text,
            letterSpacing: 6,
          }}
        >
          四条专注轨
        </div>
        <div
          style={{
            opacity: enter(frame, Math.round(0.3 * fps), Math.round(0.7 * fps)),
            marginTop: 16,
            fontSize: 24,
            color: COLORS.textDim,
            letterSpacing: 3,
          }}
        >
          资源配比，写进产品基因
        </div>
      </div>

      <div style={{ display: "flex", gap: 36, marginTop: 40 }}>
        {TRACKS.map((track, i) => {
          const cardIn = enter(frame, Math.round((0.5 + i * 0.28) * fps), Math.round(0.7 * fps));
          // 配比条生长动画：把百分比映射为条宽
          const barIn = clampInterpolate(
            frame,
            [Math.round((0.9 + i * 0.28) * fps), Math.round((1.6 + i * 0.28) * fps)],
            [0, 1],
          );
          return (
            <div
              key={track.letter}
              style={{
                opacity: cardIn,
                transform: `translateY(${(1 - cardIn) * 32}px)`,
                width: 250,
                padding: "34px 28px",
                borderRadius: 20,
                border: `1px solid ${track.color}3a`,
                background: `linear-gradient(170deg, ${track.color}10, rgba(255,255,255,0.02))`,
              }}
            >
              <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                <span
                  style={{
                    fontFamily: serifFont,
                    fontSize: 64,
                    fontWeight: 900,
                    color: track.color,
                  }}
                >
                  {track.letter}
                </span>
                <span style={{ fontSize: 30, fontWeight: 700, color: COLORS.text, letterSpacing: 2 }}>
                  {track.name}
                </span>
              </div>

              {/* 配比数字 + 生长条 */}
              <div style={{ marginTop: 22 }}>
                <div style={{ fontSize: 40, fontWeight: 700, color: COLORS.text }}>
                  ~{track.ratio}
                  <span style={{ fontSize: 22, color: COLORS.textDim }}>%</span>
                </div>
                <div
                  style={{
                    marginTop: 12,
                    height: 8,
                    borderRadius: 999,
                    background: "rgba(255,255,255,0.08)",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${track.ratio * 2.4 * barIn}%`,
                      height: "100%",
                      borderRadius: 999,
                      background: `linear-gradient(90deg, ${track.color}, ${track.color}88)`,
                    }}
                  />
                </div>
              </div>

              <div style={{ marginTop: 20, fontSize: 18, lineHeight: 1.7, color: COLORS.textDim }}>
                {track.desc}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
