---
name: "editly"
description: "Editly - 声明式 JSON 驱动命令行视频编辑工具。基于 Node.js + FFmpeg，适合程序化视频合成。当需要 JSON 配置方式批量合成视频、创建幻灯片、或自动化视频编辑时调用。"
---

# Editly - 声明式视频编辑技能

## 概述
Editly 是 mifi 创建的开源声明式视频编辑工具 (MIT 许可, 4k+ Stars)。用 JSON/JSON5 配置文件描述视频编辑操作，基于 FFmpeg 流式处理，速度快、内存占用低。

## 安装
```bash
npm i -g editly
```

## 基本用法
```bash
# CLI 快速合成
editly title:'我的视频' clip1.mp4 clip2.mp4 title:'THE END' \
  --fast --audio-file-path music.mp3 --out output.mp4

# JSON5 配置文件
editly my-spec.json5 --fast --out output.mp4
```

## JSON5 配置示例
```json5
{
  outPath: "output.mp4",
  width: 1080,
  height: 1920,
  fps: 30,
  clips: [
    {
      duration: 4,
      layers: [
        { type: "video", path: "clip1.mp4", resizeMode: "cover" },
        { type: "title", text: "高能片段", position: "top", fontSize: 0.06 }
      ],
      transition: { name: "fade", duration: 0.5 }
    },
    {
      duration: 3,
      layers: [
        { type: "image", path: "photo.jpg", duration: 3 },
        { type: "subtitle", text: "精彩瞬间", position: "bottom" }
      ]
    }
  ],
  audioFilePath: "bgm.mp3"
}
```

## 核心功能
| 功能 | 说明 |
|------|------|
| 视频/图片/文字层 | 多层级叠加合成 |
| 转场效果 | fade, dissolve, slide, zoom, wipe 等 |
| 字幕叠加 | 支持 SRT/ASS 格式 |
| BGM + 音频混合 | 音频淡入淡出、音量控制 |
| Canvas/GL Shader | 自定义渲染 (Fabric.js / WebGL) |
| 输出格式 | MP4, GIF, WebM |
| 任意尺寸输出 | 9:16/16:9/1:1 自适应 letterbox |

## MCP 集成
已有 editly-mcp (MIT): 将 Editly 封装为 MCP Server，支持 Claude Desktop/Cursor 调用
```bash
npx @moeloubani/editly-mcp
# 工具: merge_clips, create_slideshow, add_title, trim_video, add_audio, create_video
```

## AI短剧编辑器 集成方案
- 作为轻量导出引擎的 JSON 后端
- 替代 modules.py 中的 `_basic_process` 用于简单合成场景
- 通过 editly-mcp 暴露为 MCP 工具供外部 AI 调用
