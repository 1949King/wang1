// 场景三：双活路径 —— 剪辑模块 + AI 画布（产品仅有的两条主线）
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, enter, sansFont, serifFont } from "../theme";

// 两条活路径的卡片数据
const PATHS = [
  {
    tag: "PATH 01",
    title: "剪辑模块",
    color: COLORS.cyan,
    points: ["时间线编辑 · 手感优先", "实时预览 / 播放", "多内核导出（C++ / FFmpeg）"],
  },
  {
    tag: "PATH 02",
    title: "AI 导演台画布",
    color: COLORS.gold,
    points: ["导演台节点 · 生图 / 生视频", "智能体确认后执行", "画布数字人（TTS + 形象）"],
  },
];

export const DualPaths: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headIn = enter(frame, 0, Math.round(0.7 * fps));

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(1100px 700px at 50% 80%, #101c2e 0%, ${COLORS.bg} 70%)`,
        fontFamily: sansFont,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div style={{ position: "absolute", top: 90, textAlign: "center", width: "100%" }}>
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
          两条活路径
        </div>
        <div
          style={{
            opacity: enter(frame, Math.round(0.3 * fps), Math.round(0.7 * fps)),
            marginTop: 18,
            fontSize: 24,
            color: COLORS.textDim,
            letterSpacing: 3,
          }}
        >
          专注，是产品的护城河
        </div>
      </div>

      <div style={{ display: "flex", gap: 60 }}>
        {PATHS.map((path, i) => {
          // 左右卡片分别从两侧滑入，形成对称节奏
          const cardIn = enter(frame, Math.round((0.5 + i * 0.35) * fps), Math.round(0.8 * fps));
          const fromX = i === 0 ? -60 : 60;
          return (
            <div
              key={path.title}
              style={{
                opacity: cardIn,
                transform: `translateX(${(1 - cardIn) * fromX}px)`,
                width: 440,
                padding: "44px 40px",
                borderRadius: 24,
                border: `1px solid ${path.color}40`,
                background: `linear-gradient(165deg, ${path.color}12, rgba(255,255,255,0.02))`,
              }}
            >
              <div style={{ fontSize: 20, color: path.color, letterSpacing: 5 }}>{path.tag}</div>
              <div
                style={{
                  fontFamily: serifFont,
                  fontSize: 44,
                  fontWeight: 900,
                  color: COLORS.text,
                  marginTop: 14,
                  letterSpacing: 2,
                  whiteSpace: "nowrap",
                }}
              >
                {path.title}
              </div>
              <div style={{ marginTop: 28, display: "flex", flexDirection: "column", gap: 16 }}>
                {path.points.map((point, j) => {
                  // 要点逐条浮现
                  const pointIn = enter(
                    frame,
                    Math.round((1 + i * 0.35 + j * 0.22) * fps),
                    Math.round(0.5 * fps),
                  );
                  return (
                    <div
                      key={point}
                      style={{
                        opacity: pointIn,
                        transform: `translateY(${(1 - pointIn) * 12}px)`,
                        display: "flex",
                        alignItems: "center",
                        gap: 14,
                        fontSize: 24,
                        color: COLORS.text,
                      }}
                    >
                      <span
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: 999,
                          background: path.color,
                          flexShrink: 0,
                        }}
                      />
                      {point}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
