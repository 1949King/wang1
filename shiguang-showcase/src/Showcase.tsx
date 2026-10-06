// 主合成：拾光剪影官网展示片 —— 六场景编排 + fade 转场
import React from "react";
import { AbsoluteFill } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { COLORS } from "./theme";
import { Hero } from "./scenes/Hero";
import { NorthStar } from "./scenes/NorthStar";
import { DualPaths } from "./scenes/DualPaths";
import { FocusTracks } from "./scenes/FocusTracks";
import { TechStack } from "./scenes/TechStack";
import { Outro } from "./scenes/Outro";

// 各场景时长（帧，30fps）与转场时长集中管理，便于整体调节奏
const SCENE_FRAMES = {
  hero: 135,
  northStar: 135,
  dualPaths: 135,
  focusTracks: 135,
  techStack: 120,
  outro: 120,
};
const TRANSITION_FRAMES = 20;

// 总时长 = 各场景之和 - 转场重叠（5 个转场）
export const SHOWCASE_DURATION =
  Object.values(SCENE_FRAMES).reduce((a, b) => a + b, 0) - TRANSITION_FRAMES * 5;

export const Showcase: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.hero}>
          <Hero />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
        />
        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.northStar}>
          <NorthStar />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
        />
        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.dualPaths}>
          <DualPaths />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
        />
        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.focusTracks}>
          <FocusTracks />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
        />
        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.techStack}>
          <TechStack />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
        />
        <TransitionSeries.Sequence durationInFrames={SCENE_FRAMES.outro}>
          <Outro />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
