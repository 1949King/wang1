// 场景六：品牌收尾 —— 主标语 + 行动号召
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, EASE_IN_OUT, clampInterpolate, enter, sansFont, serifFont } from "../theme";

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 收尾光晕：从中心向外扩散的金色呼吸光
  const glow = clampInterpolate(frame, [0, 2 * fps], [0.4, 1], EASE_IN_OUT);
  const titleIn = enter(frame, Math.round(0.3 * fps), Math.round(0.9 * fps));
  const sloganIn = enter(frame, Math.round(1 * fps), Math.round(0.8 * fps));
  const ctaIn = enter(frame, Math.round(1.7 * fps), Math.round(0.7 * fps));

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(${900 * glow}px ${600 * glow}px at 50% 45%, #1a2440 0%, ${COLORS.bg} 75%)`,
        fontFamily: sansFont,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          opacity: titleIn,
          transform: `scale(${0.94 + titleIn * 0.06})`,
          fontFamily: serifFont,
          fontWeight: 900,
          fontSize: 150,
          letterSpacing: 10,
          background: `linear-gradient(120deg, ${COLORS.gold} 10%, ${COLORS.text} 50%, ${COLORS.amber} 90%)`,
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
        }}
      >
        拾光剪影
      </div>

      <div
        style={{
          opacity: sloganIn,
          transform: `translateY(${(1 - sloganIn) * 20}px)`,
          marginTop: 34,
          fontSize: 40,
          fontWeight: 300,
          color: COLORS.text,
          letterSpacing: 8,
        }}
      >
        导演台起笔，时间线收尾
      </div>

      {/* 行动号召按钮 */}
      <div
        style={{
          opacity: ctaIn,
          transform: `translateY(${(1 - ctaIn) * 18}px)`,
          marginTop: 56,
          padding: "18px 56px",
          borderRadius: 999,
          background: `linear-gradient(120deg, ${COLORS.gold}, ${COLORS.amber})`,
          color: "#1a1206",
          fontSize: 28,
          fontWeight: 700,
          letterSpacing: 4,
        }}
      >
        立即下载 · 开始创作
      </div>

      <div
        style={{
          opacity: ctaIn,
          position: "absolute",
          bottom: 60,
          fontSize: 20,
          letterSpacing: 6,
          color: COLORS.textDim,
        }}
      >
        SHIGUANG JIANYING © 2026
      </div>
    </AbsoluteFill>
  );
};
