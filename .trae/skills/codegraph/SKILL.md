---
name: "codegraph"
description: "CodeGraph - 代码知识图谱预索引工具。为 AI 编程 Agent 构建语义代码图谱，减少 token 消耗和工具调用。当需要让 AI 快速理解大型代码库、探索项目架构或分析代码影响范围时调用。"
---

# CodeGraph - 代码知识图谱技能

## 概述
CodeGraph 是 Colby McHenry 创建的开源代码知识图谱工具 (9.6k Stars, MIT 许可)。在本地用 tree-sitter 构建语义图谱存储于 SQLite，通过 MCP 服务暴露给 AI Agent。减少 92% 工具调用，提速 71%。

## 安装
```bash
npx @colbymchenry/codegraph        # 交互式安装 → 自动配置 AI Agent
cd your-project
codegraph init -i                   # 初始化项目并建立索引
```

## 四阶段流程
```
Extract (tree-sitter AST) → Store (SQLite+FTS5) → Resolve (交叉引用) → Auto-Sync (文件监听)
```

## MCP 工具集 (8 个)
| 工具 | 用途 |
|------|------|
| `codegraph_search` | 按名称搜索符号 |
| `codegraph_context` | 为任务构建代码上下文 |
| `codegraph_callers` | 谁调用了这个函数 |
| `codegraph_callees` | 这个函数调用了谁 |
| `codegraph_impact` | 修改某符号影响哪些代码 |
| `codegraph_node` | 获取符号详细信息 |
| `codegraph_files` | 索引文件结构 |
| `codegraph_status` | 索引健康状态 |

## 基准测试
| 代码库 | With CodeGraph | Without | 提升 |
|--------|:--:|:--:|:--:|
| VS Code (TS, 4002文件) | 3调用/17s | 52调用/97s | 94%↓ 82%↑ |
| Excalidraw (TS, 626文件) | 3调用/29s | 47调用/105s | 94%↓ 72%↑ |
| Tokio (Rust, 790文件) | — | — | 92%↓ 71%↑ |
| Alamofire (Swift) | 1调用/22s | 32调用/99s | 91%↓ 78%↑ |

## 支持语言 (19+)
TypeScript/JavaScript, Python, Go, Rust, Java, C#, PHP, Ruby, C/C++, Swift, Kotlin, Dart, Svelte, Liquid, Pascal/Delphi

## AI短剧编辑器 项目中的使用
```bash
cd AI短剧编辑器2
codegraph init -i
# 索引 app/ 下所有 Python/TypeScript 代码
# Claude Code 问: "渲染管线的数据流是怎样的？"
# → 1 次 codegraph_context 调用，无需扫描上百个文件
```

## 自动同步
- macOS: FSEvents
- Linux: inotify
- Windows: ReadDirectoryChangesW
- 2秒防抖增量同步 → 写代码时图谱自动更新
