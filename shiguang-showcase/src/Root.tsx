// 合成注册入口：拾光剪影官网展示片（1920x1080 / 30fps）
import React from "react";
import { Composition } from "remotion";
import { Showcase, SHOWCASE_DURATION } from "./Showcase";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ShiguangShowcase"
        component={Showcase}
        durationInFrames={SHOWCASE_DURATION}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
