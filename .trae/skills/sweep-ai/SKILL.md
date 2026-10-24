---
name: "sweep-ai"
description: "Sweep AI - JetBrains IDE 智能编程助手。提供 Tab 补全、代码生成、Bug 修复和 Agent 模式。当需要在 PyCharm/IntelliJ/WebStorm 等 JetBrains IDE 中使用 AI 辅助开发时调用。"
---

# Sweep AI - JetBrains IDE 智能编程助手

## 概述
Sweep 是 JetBrains Marketplace #1 AI 插件 (4.9 星, 40k+ 安装)，为 PyCharm/IntelliJ/WebStorm/GoLand 等 IDE 提供原生 AI 编程体验。使用自研 LLM 模型，零代码外泄，SOC 2 合规。

## 安装
JetBrains IDE → Plugins 市场 → 搜索 "Sweep AI" → Install → GitHub 登录

## 支持 IDE
IntelliJ IDEA, PyCharm, CLion, WebStorm, GoLand, Rider, PhpStorm, Android Studio, RustRover, RubyMine

## 核心功能

### 1. Agent 模式
- 在编辑器内用自然语言描述需求
- 自动生成符合项目规范的完整代码段
- 跨文件重构、Bug 修复、需求级功能实现

### 2. Next-Edit Autocomplete (Tab-Tab-Tab)
- 自定义 Tab 模型，毫秒级代码补全预测
- 上下文感知：索引整个项目理解代码结构
- 比传统补全更精准（感知定义、引用、导入）

### 3. 智能 Bug 修复
- 自动扫描文件/项目的潜在缺陷
- 一键修复补丁

### 4. AI Code Review
- 实时分析代码风格、性能瓶颈、安全风险
- PR 自动生成变更说明

### 5. 终端指令
- `@terminal` - 终端上下文
- `@problems` - 问题定位
- `@current changes` - 变更感知

## 安全特性
- 自研 LLM，不传输代码到第三方
- SOC 2 认证
- 自托管部署选项 (企业版)
- 支持 BYOK (Bring Your Own Key)

## AI短剧编辑器 开发中的使用
```
1. PyCharm + Sweep AI 打开项目
2. 选中代码 → Alt+Enter → "Generate with Sweep"
3. 描述: "给这个类添加 GPU 硬件加速检测方法"
4. Sweep 自动生成符合项目风格的代码
5. 审查 → Tab 确认 → 完成
```
