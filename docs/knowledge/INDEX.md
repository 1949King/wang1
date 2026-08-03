# 拾光剪影 — 项目知识库

> 人和 Agent 共用的单一事实来源（Single Source of Truth）。  
> 更新约定：改架构/活路径/已知问题后，先改本库，再改代码。  
> 全量索引由 `python scripts/sync_knowledge.py` 刷新。

## 快速入口

| 文档 | 用途 |
|------|------|
| [00-overview.md](00-overview.md) | 产品北极星、7 阶段闭环、优先级 |
| [01-glossary.md](01-glossary.md) | 领域术语表 |
| [02-architecture.md](02-architecture.md) | 分层架构、启动链路、双内核 |
| [03-editor-pipeline.md](03-editor-pipeline.md) | 导入→时间线→预览→播放→导出 |
| [04-module-map.md](04-module-map.md) | 模块注册表与功能去向 |
| [05-known-issues.md](05-known-issues.md) | 已知问题与已修复项 |
| [06-roadmap.md](06-roadmap.md) | P0 剪映对齐与地基分层 |
| [07-coding-rules.md](07-coding-rules.md) | 编码约定与最小入侵原则 |
| [08-frozen-zones.md](08-frozen-zones.md) | **已修好功能冻结区**（禁改清单） |
| [sources/MANIFEST.md](sources/MANIFEST.md) | 全库 Markdown 源清单（自动生成） |
| [catalog.json](catalog.json) | 机器可读目录（自动生成） |

## 根上下文

- 项目根 [`CONTEXT.md`](../../CONTEXT.md) — 精简术语 + 指向本库  
- Agent 规则 [`.cursor/rules/project-knowledge.mdc`](../../.cursor/rules/project-knowledge.mdc)  
- 长期记忆 [`.workbuddy/memory/MEMORY.md`](../../.workbuddy/memory/MEMORY.md)

## 同步命令

```bash
# 在项目根执行：扫描全部 md → 刷新 MANIFEST + catalog.json
python scripts/sync_knowledge.py
```

## 活路径（编码时优先跟这些文件）

**主路径**

```
app/main_qt6.py
app/modules/lego/main_window.py
app/modules/lego/module_registry.py
app/modules/lego/editor_module.py
app/modules/lego/timeline_widget.py
app/core/preview_manager.py
app/core/waveform_generator.py
app/core/editor_scheduler.py
app/core/timeline_manager.py
```

**剪辑抽出 / AI 体力活（副路径）**

```
app/modules/lego/clip_transform.py
app/modules/lego/editor_export.py
app/modules/lego/editor_burn.py
app/modules/lego/editor_subtitle_panel.py
app/core/text_frame_map.py
app/core/edit_commands.py
app/core/filler_silence_detect.py
```

**拓展 / 闭环（按需）**

```
app/modules/lego/extensions_module.py
app/modules/lego/account_ops_module.py
app/plugins/drama_finder_plugin/
```

**明确不做**：重写时间线架构、GPU 流式预览大改、完整转场库、Desktop 栈迁入（见 `docs/P0_CAPCUT_ALIGN.md`）。

知识库最近全量对照代码复核：**2026-08-04**。
