---
name: "superpowers"
description: "Superpowers - 开源 HTML5 2D/3D 游戏引擎。TypeScript+Three.js，实时协作编辑，可导出到 Web/移动/桌面。当需要 3D 特效、实时动画协作或游戏化 UI 参考时调用。"
---

# Superpowers — HTML5 2D/3D 游戏引擎

## 概述
Superpowers 是 Sparklin Labs 开发的开源 HTML5 游戏引擎（ISC 许可），由 `obra/superpowers` 演变到 `superpowers/superpowers-core`（GitHub 已归档，最后一次更新 2021年1月）。

## 技术栈
- 语言：TypeScript
- 渲染：Three.js (WebGL)
- 运行环境：Electron + HTML5
- 实时协作：WebSocket 多用户同步编辑
- 编辑器：浏览器内运行 (`localhost:4237`)

## 安装与部署
```bash
git clone https://github.com/superpowers/superpowers-core superpowers/core
cd superpowers/core
npm run build
node server start
# 浏览器打开 http://localhost:4237
```

## 核心能力

| 功能 | 说明 |
|------|------|
| **2D + 3D 游戏** | 统一的编辑器，支持精灵(Sprites)和3D模型 |
| **实时协作** | 多人同时编辑同一项目，通过 URL+密码分享 |
| **跨平台导出** | Web / Windows / macOS / Linux / Android / iOS |
| **TypeScript IDE** | 语法高亮、自动补全、实时错误报告、跳转到定义 |
| **离线可用** | 项目存本地，无网络也能工作 |
| **免费素材包** | CC0 许可的精灵、3D模型、音效、字体、音乐 |
| **插件系统** | 编辑器内置工具也是插件，可替换/扩展 |
| **物理引擎** | Cannon.js / p2.js 集成 |
| **网络** | Socket.IO 内置 |

## 编辑器架构参考

```
Superpowers 的插件化编辑器架构：
├── Core (Electron 宿主)
├── Editor Plugins
│   ├── Scene Editor (场景编辑器)
│   ├── Script Editor (TypeScript 编辑器)
│   ├── Asset Browser (资源浏览器)
│   └── Game Preview (实时预览)
├── Runtime (Three.js + Cannon.js)
└── Export Pipeline (跨平台打包)
```

## 对本项目的参考价值

### 1. 实时协作编辑
```
Superpowers 的多用户协作模式：
  用户A 编辑时间线 → WebSocket → 用户B 实时看到

AI短剧编辑器 可参考:
  多人同时编辑短剧项目 → 类似于 Figma 协作模式
```

### 2. 插件架构
```
Superpowers: 编辑器工具即插件 → 可替换、可扩展
本项目: effect/transition/filter 插件系统
参考: 插件热加载 + 沙箱安全 + 即插即用
```

### 3. TypeScript 编辑器体验
```
Superpowers 的 TypeScript IDE 功能：
  语法高亮 + 自动补全 + 实时错误 + 跳转定义

参考 → 本项目未来的脚本/表达式编辑器
```

### 4. 跨平台导出
```
Superpowers: 同一项目 → Web/Mobile/Desktop
本项目: 同一时间线 → 抖音/快手/B站/小红书 多种格式输出
```

## 注意事项
- **已归档**: 2021年后未更新，不建议作为新项目依赖
- **替代品**: Godot Engine (更活跃的开源游戏引擎)
- 用于**架构参考和学习**，而非直接集成

## 替代推荐
| 引擎 | 语言 | 许可 | 说明 |
|------|------|:--:|------|
| Godot Engine | GDScript/C#/C++ | MIT | 最活跃的开源游戏引擎 |
| Cocos Creator | TypeScript | MIT | 2D 为主，微信小游戏首选 |
| PlayCanvas | JavaScript | MIT | Web-first 3D 引擎 |
