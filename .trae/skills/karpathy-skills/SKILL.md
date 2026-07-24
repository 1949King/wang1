---
name: "karpathy-skills"
description: "Andrej Karpathy 的 AI 编程四诫：Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution。150k+ Stars 的单文件 CLAUDE.md。当需要规范 AI Agent 代码行为、防止过度设计、或学习 LLM 技能设计最佳实践时调用。"
---

# Andrej Karpathy Skills — AI 编程四诫

## 概述
一个 **CLAUDE.md** 文件，165k+ GitHub Stars，MIT 许可。
创建者 Forrest Chang (multica-ai)，灵感来自 Andrej Karpathy 的 viral tweet。

**不是框架，不是库，就是一个行为规范文件** — 却成为 GitHub 增长最快的 AI Workflow 仓库。

## 来源
Karpathy 在 2026年1月26日 发了一条 tweet，总结了 LLM 编程的三大通病：
> "模型替你假设需求，不检查就执行。不管理困惑，不寻求澄清，不展示 tradeoff。"
> "它们喜欢过度复杂化代码，膨胀抽象层。100行能搞定写成1000行。"
> "它们会改动不理解的相关代码和注释，即使跟任务无关。"

Forrest Chang 将这三点转化为四条可执行的规则。

## 四条规则

### 1. Think Before Coding (先思考，再编码)
**针对**: AI 默默假设需求，不澄清就执行

- 明确陈述所有假设 → 不确定就问，不要猜
- 展示 2-3 种方案及其 tradeoff
- 发现更优方案时主动提出
- 遇到模糊不清 → 停下来，命名困惑，请求澄清

### 2. Simplicity First (简洁优先)
**针对**: AI 过度设计

- 不添加未被要求的功能
- 不为单次使用的代码创建抽象层
- 不添加未请求的"灵活性"或"可配置性"
- 不为不可能场景写错误处理
- **检验标准**: 资深工程师会说"这也太复杂了"吗？

### 3. Surgical Changes (精准修改)
**针对**: AI "顺手优化"无关代码

- 不"改进"相邻代码/注释/格式
- 不重构没问题的代码
- 匹配现有风格，即使你会写得不同
- 发现死代码 → 仅提示，不直接删除
- **检验标准**: 每一行改动都能追溯到用户请求

### 4. Goal-Driven Execution (目标驱动执行)
**针对**: AI 写完就说"应该能工作了"，没有验证

| 不要 | 要 |
|------|----|
| "添加验证" | "先写测试, 再让测试通过" |
| "修复bug" | "先写能复现的测试, 再修复" |
| "重构X" | "确保测试前后都能通过" |

**成功标准模板**:
```
1. [步骤] → 验证: [检查项]
2. [步骤] → 验证: [检查项]
3. [步骤] → 验证: [检查项]
```

## 安装方式

**方式A: Claude Code Plugin (推荐)**
```bash
# 在 Claude Code 内执行
/plugin marketplace add forrestchang/andrej-karpathy-skills
/plugin install andrej-karpathy-skills@karpathy-skills
```

**方式B: 直接放进项目 CLAUDE.md**
```bash
curl -o CLAUDE.md https://raw.githubusercontent.com/forrestchang/andrej-karpathy-skills/main/CLAUDE.md
```

**方式C: Cursor 规则文件**
```bash
# 项目 .cursor/rules/karpathy-guidelines.mdc
```

## 生态：Multica 平台
Forrest Chang 还创建了 [Multica](https://github.com/multica-ai/multica)：开源平台，用于运行和管理带可复用技能的 AI 编程 Agent。

## 适配 Agent
Claude Code, Cursor, Copilot, Codex CLI, Windsurf, Claude Desktop

## 对本项目的启示
- 技能系统设计：参考 `CLAUDE.md` 的规则式约束模式
- AI Agent 行为规范：应用到 AI短剧编辑器 的 AI 剪辑 Agent
- Skill 元设计：最有效的技能不一定有代码，可能是规则
