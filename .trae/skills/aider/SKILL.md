---
name: "aider"
description: "Aider AI 终端配对编程助手。在终端中使用 LLM 直接编辑代码、自动 git commit。支持 Claude/GPT-4/DeepSeek 等模型。当需要在终端中让 AI 辅助编码、重构、或批量修改代码时调用。"
---

# Aider - AI 终端配对编程技能

## 概述
Aider 是 Paul Gauthier (前 Inktomi CTO/Groupon CTO) 创建的终端 AI 编程工具，44k+ GitHub Stars，680万+ pip 安装。与 Claude Code/Cursor/Copilot 不同，Aider 是终端优先、Git 原生、Bring-Your-Own-Key 的设计。

## 快速安装
```bash
pip install aider-chat
# 或
pipx install aider-chat
```

## 基础用法
```bash
cd your-project
aider                    # 开始会话

# 在会话中
/add src/main.py         # 添加要编辑的文件
"重构这个类，拆分成两个类"    # 自然语言指令
/undo                    # 撤销上次修改
/diff                    # 查看变更
/commit                  # 手动提交
/model claude-sonnet-4   # 切换模型
```

## 支持的模型
- Claude 3.5/4 (Sonnet, Opus, Haiku)
- GPT-4o, GPT-4.5/5
- DeepSeek R1, V3
- Gemini 2.5
- 本地模型 via Ollama: `aider --model ollama/qwen2.5:14b`

## 核心特性
- **自动 Git 提交**: 每次修改自动生成描述性提交信息
- **仓库地图**: 用 tree-sitter 构建代码图谱，给 LLM 上下文
- **多文件编辑**: 一次指令修改多个文件
- **Architect/Editor 模式**: DeepSeek R1 做架构设计 + Claude 做代码实现
- **71%+ 代码由 Aider 自己编写**: 吃自己狗粮的信任度

## AI短剧编辑器 项目中的应用
```bash
# 快速重构视频引擎
aider app/core/video_processing/ --model claude-sonnet-4
"将所有 FFmpeg subprocess 调用统一到 FFmpegTool 类"

# 批量添加日志
aider app/modules/lego/ --model deepseek
"给每个模块的 __init__ 方法添加 logger.info 启动日志"

# 自动生成测试
aider app/core/render_manager.py app/core/gpu_acceleration.py
"为这两个文件生成完整的 pytest 单元测试"
```

## 配置 (~/.aider.conf.yml)
```yaml
model: claude-sonnet-4
auto-commits: true
dark-mode: true
edit-format: diff
git: true
```
