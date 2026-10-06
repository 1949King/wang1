// 场景五：技术栈 —— UI / 视频处理 / 画布 / AI / 语言 分层展示
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, enter, sansFont, serifFont } from "../theme";

// 技术栈分层数据（来自现行技术文档 §2）
const LAYERS = [
  { layer: "UI", tech: "PyQt6 · Fusion + 深色 QSS", color: COLORS.cyan },
  { layer: "视频处理", tech: "FFmpeg / OpenCV / PyAV / MLT 双内核", color: COLORS.gold },
  { layer: "画布", tech: "React + Zustand + Three.js + @xyflow/react", color: COLORS.violet },
  { layer: "AI", tech: "Ollama 本地 + 多云 Provider · Agent / Skill / MCP", color: COLORS.amber },
  { layer: "语言", tech: "Python 3.x · TypeScript", color: COLORS.blue },
];

export const TechStack: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headIn = enter(frame, 0, Math.round(0.7 * fps));

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(1100px 700px at 70% 40%, #0f1a2c 0%, ${COLORS.bg} 70%)`,
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
          技术栈
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
          分层清晰 · 双内核 · 本地优先
        </div>
      </div>

      {/* 分层行：逐行从左侧滑入，左侧色条标识层级 */}
      <div style={{ display: "flex", flexDirection: "column", gap: 20, marginTop: 30, width: 860 }}>
        {LAYERS.map((item, i) => {
          const rowIn = enter(frame, Math.round((0.5 + i * 0.22) * fps), Math.round(0.7 * fps));
          return (
            <div
              key={item.layer}
              style={{
                opacity: rowIn,
                transform: `translateX(${(1 - rowIn) * -50}px)`,
                display: "flex",
                alignItems: "center",
                gap: 24,
                padding: "20px 30px",
                borderRadius: 16,
                border: "1px solid rgba(255,255,255,0.08)",
                background: "rgba(255,255,255,0.03)",
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 44,
                  borderRadius: 3,
                  background: item.color,
                  flexShrink: 0,
                }}
              />
              <div style={{ width: 130, fontSize: 28, fontWeight: 700, color: item.color, letterSpacing: 2 }}>
                {item.layer}
              </div>
              <div style={{ fontSize: 26, color: COLORS.text, letterSpacing: 1 }}>{item.tech}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
