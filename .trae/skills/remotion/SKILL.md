---
name: "remotion"
description: "Remotion - React 编程式视频生成框架。用 React 组件创建视频，支持代码驱动批量渲染。当需要用代码生成视频、创建动画视频模板、或批量生产视频内容时调用。"
---

# Remotion - React 编程式视频生成技能

## 概述
Remotion 让你用 React 组件来创建视频。像写网页一样写视频，支持代码驱动、批量生成、服务端渲染。15k+ GitHub Stars。

## 快速开始
```bash
npx create-video@latest my-video
cd my-video && npm start
```

## 核心概念：React 组件 = 视频
```tsx
import { Composition, AbsoluteFill, useCurrentFrame, interpolate } from "remotion";

const MyVideo = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 30], [0, 1]); // 淡入动画

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <h1 style={{ color: "white", fontSize: 80, opacity }}>
        这是我的视频
      </h1>
    </AbsoluteFill>
  );
};

export const RemotionRoot = () => (
  <Composition id="MyVideo" component={MyVideo}
    durationInFrames={150} fps={30} width={1920} height={1080} />
);
```

## 核心 API
| 组件/API | 用途 |
|----------|------|
| `<Composition>` | 注册视频合成 |
| `<Sequence>` | 时间线片段 (多段拼接) |
| `<Video>` / `<Audio>` | 导入视频/音频素材 |
| `<AbsoluteFill>` | 全屏容器 |
| `useCurrentFrame()` | 获取当前帧号 |
| `interpolate()` | 插值动画 |
| `spring()` | 弹簧物理动画 |
| `<Img>` / `<IFrame>` | 图片/嵌入网页 |

## 渲染命令
```bash
# 渲染单个视频
npx remotion render MyVideo out.mp4

# 批量渲染 (不同参数)
npx remotion render MyVideo out.mp4 --props='{"title":"视频1"}'
npx remotion still MyVideo frame.png --frame=30
```

## AI短剧编辑器 集成思路
```
React 模板组件 (JSON 驱动)
  ├── ShortDramaTemplate: 竖屏 9:16, 抖音素材
  ├── SlideshowTemplate: 图片+文字+BGM 卡点
  └── DynamicSubtitle: CSS 动画字幕 (比 FFmpeg drawtext 强10倍)

自动化流水线:
  AI 生成脚本 → React 组件参数 → Remotion 批量渲染 → 100 条视频
```

## 资源
- 官网: https://remotion.dev
- GitHub: remotion-dev/remotion
- Editor Starter (付费模板): remotion.dev/docs/editor-starter
