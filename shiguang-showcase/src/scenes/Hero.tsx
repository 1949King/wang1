// 场景一：Hero 品牌开场 —— 标题、副标语、产品定位徽章
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, EASE_IN_OUT, enter, clampInterpolate, sansFont, serifFont } from "../theme";

export const Hero: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  // 背景扫光：一条缓慢横移的金色光带，营造「拾光」氛围
  const sweepX = clampInterpolate(frame, [0, 4 * fps], [-width * 0.4, width * 0.6], EASE_IN_OUT);

  // 各元素入场进度（错拍出现，节奏更自然）
  const badgeIn = enter(frame, Math.round(0.2 * fps), Math.round(0.8 * fps));
  const titleIn = enter(frame, Math.round(0.5 * fps), Math.round(1 * fps));
  const subIn = enter(frame, Math.round(1.2 * fps), Math.round(0.9 * fps));
  const captionIn = enter(frame, Math.round(1.8 * fps), Math.round(0.8 * fps));

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(1200px 800px at 50% 30%, #101a30 0%, ${COLORS.bg} 65%)`,
        fontFamily: sansFont,
        justifyContent: "center",
        alignItems: "center",
        overflow: "hidden",
      }}
    >
      {/* 扫光层 */}
      <div
        style={{
          position: "absolute",
          top: "-30%",
          left: sweepX,
          width: width * 0.5,
          height: height * 1.6,
          transform: "rotate(18deg)",
          background:
            "linear-gradient(90deg, transparent, rgba(245,196,81,0.10), transparent)",
          filter: "blur(6px)",
        }}
      />

      {/* 定位徽章 */}
      <div
        style={{
          opacity: badgeIn,
          transform: `translateY(${(1 - badgeIn) * 24}px)`,
          padding: "10px 28px",
          borderRadius: 999,
          border: `1px solid ${COLORS.panelBorder}`,
          background: COLORS.panel,
          color: COLORS.gold,
          fontSize: 26,
          letterSpacing: 4,
          marginBottom: 42,
        }}
      >
        PyQt6 桌面端 · 短剧精剪 + AI 导演台画布
      </div>

      {/* 主标题 */}
      <div
        style={{
          opacity: titleIn,
          transform: `translateY(${(1 - titleIn) * 40}px) scale(${0.96 + titleIn * 0.04})`,
          fontFamily: serifFont,
          fontWeight: 900,
          fontSize: 190,
          lineHeight: 1.05,
          letterSpacing: 12,
          background: `linear-gradient(120deg, ${COLORS.text} 20%, ${COLORS.gold} 55%, ${COLORS.amber} 80%)`,
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
        }}
      >
        拾光剪影
      </div>

      {/* 副标语 */}
      <div
        style={{
          opacity: subIn,
          transform: `translateY(${(1 - subIn) * 28}px)`,
          marginTop: 36,
          fontSize: 44,
          fontWeight: 300,
          color: COLORS.text,
          letterSpacing: 6,
        }}
      >
        把每一帧时光，剪成想要的样子
      </div>

      {/* 英文注脚 */}
      <div
        style={{
          opacity: captionIn,
          marginTop: 26,
          fontSize: 20,
          letterSpacing: 10,
          color: COLORS.textDim,
        }}
      >
        SHIGUANG JIANYING · CAPTURE LIGHT, CUT STORIES
      </div>
    </AbsoluteFill>
  );
};
