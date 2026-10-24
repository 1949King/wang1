---
name: "agentmemory"
description: "AgentMemory - AI Agent 持久化记忆系统。让 AI Agent 跨会话记住代码库知识、用户偏好和项目历史。当需要为 AI 编程助手添加长期记忆、知识图谱检索或跨会话上下文保持时调用。"
---

# AgentMemory - AI Agent 持久记忆系统

## 概述
agentmemory 是 rohitg00 创建的开源 AI 记忆层 (9.3k Stars, MIT 许可)，为 Claude Code/Cursor/Codex CLI 等编程 Agent 提供跨会话持久化记忆。基于 iii-engine，支持 BM25+向量+知识图谱混合检索。

## 安装
```bash
npx @agentmemory/agentmemory              # 启动记忆服务器 (:3111)
npx @agentmemory/agentmemory demo         # 演示预置会话
agentmemory connect claude-code           # 连接 Agent
```

## 支持的 Agent (10+)
Claude Code, Cursor, Codex CLI, Gemini CLI, Cline, Windsurf, Roo Code, OpenCode, Hermes, Aider, OpenClaw

## 核心能力

### 自动捕获
- 12 个 Claude Code hooks / 6 个 Codex CLI hooks
- 静默监听 Agent 操作，自动构建记忆图谱
- 无需手动记录，零侵入

### 混合检索
```
BM25 关键词匹配 + 向量语义搜索 + 知识图谱关系 = RRF 融合排序
```
- P@5: 0.578 (vs grep baseline 较低, 但 R@5: 95.2% on LongMemEval-S)
- p50 延迟: 14ms

### 智能压缩
- 自动去重相似记忆
- 生命周期管理 (衰减/强化)
- 置信度评分

### Token 经济学
```
无记忆: 19.5M tokens/年 (反复粘贴上下文)
有 AgentMemory: ~170K tokens/年 (自动注入精准记忆)
节省: 99%+ 重复上下文 → ~$10/年 (免费本地向量)
```

## MCP 工具集 (51 个)
| 类别 | 核心工具 |
|------|---------|
| 搜索 | `memory_smart_search`, `memory_hybrid_search`, `memory_semantic_search` |
| 存储 | `memory_save`, `memory_upsert`, `memory_save_batch` |
| 管理 | `memory_sessions`, `memory_lifecycle`, `memory_governance_delete` |
| 图谱 | `memory_graph_relationships`, `memory_entity_link` |
| 用户 | `memory_user_profile`, `memory_preferences_update` |

## AI短剧编辑器 中的应用
```
场景1: 用户偏好记忆
  用户: "上次我用暖色调+窄屏"
  AgentMemory: → 自动注入 "user prefers warm colors, 9:16 aspect ratio"
  AI: 直接推荐匹配预设

场景2: 项目上下文记忆
  用户: "给这个短剧加字幕"
  AgentMemory: → 自动注入 "project uses 黑体/24px/white with black border"
  不需要重新描述字幕样式

场景3: 跨编辑器记忆
  Claude Code 学到的代码结构 → Cursor 也能直接复用
  多 IDE/多 Agent 共享同一份记忆
```

## 配置 (.agentmemory.json)
```json
{
  "port": 3111,
  "storage": "sqlite",
  "auto_capture": true,
  "compression": "smart",
  "agent_id": "ai-drama-editor"
}
```
