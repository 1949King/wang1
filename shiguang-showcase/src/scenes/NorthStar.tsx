// 场景二：北极星工作流 —— 导演台 → 分镜图 → 入轨精剪（竖切可重复）
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, enter, clampInterpolate, sansFont, serifFont } from "../theme";

// 工作流节点数据
const STEPS = [
  { title: "导演台", desc: "节点式创作 · 数字人出镜", color: COLORS.gold },
  { title: "分镜图", desc: "AI 生图 · 逐镜打磨", color: COLORS.cyan },
  { title: "入轨精剪", desc: "时间线手感 · 建议入轨", color: COLORS.violet },
];

export const NorthStar: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headIn = enter(frame, 0, Math.round(0.7 * fps));
  const nodeW = 300;
  const gap = 110;

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(1000px 700px at 50% 20%, #0e1830 0%, ${COLORS.bg} 70%)`,
        fontFamily: sansFont,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      {/* 章节标题 */}
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
          北极星 · 竖切可重复
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
          智能体只做「确认后执行」的遥控器，不默认一键成片
        </div>
      </div>

      {/* 工作流节点 + 连接箭头 */}
      <div style={{ display: "flex", alignItems: "center" }}>
        {STEPS.map((step, i) => {
          const nodeIn = enter(frame, Math.round((0.6 + i * 0.45) * fps), Math.round(0.7 * fps));
          const arrowIn = clampInterpolate(
            frame,
            [Math.round((0.9 + i * 0.45) * fps), Math.round((1.3 + i * 0.45) * fps)],
            [0, 1],
          );
          return (
            <React.Fragment key={step.title}>
              <div
                style={{
                  opacity: nodeIn,
                  transform: `translateY(${(1 - nodeIn) * 36}px)`,
                  width: nodeW,
                  padding: "34px 26px",
                  borderRadius: 20,
                  border: `1px solid ${step.color}44`,
                  background: `linear-gradient(160deg, ${step.color}14, rgba(255,255,255,0.02))`,
                  textAlign: "center",
                }}
              >
                <div
                  style={{
                    fontSize: 20,
                    color: step.color,
                    letterSpacing: 4,
                    marginBottom: 10,
                  }}
                >
                  STEP {i + 1}
                </div>
                <div
                  style={{
                    fontFamily: serifFont,
                    fontSize: 46,
                    fontWeight: 900,
                    color: COLORS.text,
                    letterSpacing: 4,
                  }}
                >
                  {step.title}
                </div>
                <div style={{ marginTop: 14, fontSize: 20, color: COLORS.textDim, lineHeight: 1.6 }}>
                  {step.desc}
                </div>
              </div>
              {i < STEPS.length - 1 && (
                <div style={{ width: gap, display: "flex", justifyContent: "center" }}>
                  {/* 箭头：进度条式生长，呼应「流转」语义 */}
                  <div
                    style={{
                      width: gap * 0.62 * arrowIn,
                      height: 3,
                      borderRadius: 2,
                      background: `linear-gradient(90deg, ${STEPS[i].color}, ${STEPS[i + 1].color})`,
                      position: "relative",
                    }}
                  >
                    <div
                      style={{
                        position: "absolute",
                        right: -10,
                        top: -7,
                        opacity: arrowIn,
                        color: STEPS[i + 1].color,
                        fontSize: 24,
                      }}
                    >
                      ▶
                    </div>
                  </div>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
