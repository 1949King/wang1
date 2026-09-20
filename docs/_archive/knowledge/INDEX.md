# 拾光剪影 — 项目知识库

> 人和 Agent 共用的单一事实来源(Single Source of Truth).  
> 更新约定:改架构/活路径/已知问题后,先改本库,再改代码.  
> 全量索引由 `python scripts/sync_knowledge.py` 刷新.

## 快速入口

| 文档 | 用途 |
|------|------|
| [00-overview.md](00-overview.md) | 产品北极星、四条专注轨、优先级 |
| [01-glossary.md](01-glossary.md) | 领域术语表 |
| [02-architecture.md](02-architecture.md) | 分层架构、启动链路、双内核 |
| [03-editor-pipeline.md](03-editor-pipeline.md) | 导入→时间线→预览→播放→导出 |
| [04-module-map.md](04-module-map.md) | 模块注册表与功能去向 |
| [05-known-issues.md](05-known-issues.md) | 已知问题与已修复项 |
| [06-roadmap.md](06-roadmap.md) | P0 剪映对齐与地基分层 |
| [07-coding-rules.md](07-coding-rules.md) | 编码约定与最小入侵原则 |
| [08-frozen-zones.md](08-frozen-zones.md) | **已修好功能冻结区**(禁改清单) |
| [09-tool-registry-design.md](09-tool-registry-design.md) | Agent 能力表面收敛设计提案(4 套→1 套,分阶段) |
| [10-editor-module-split-plan.md](10-editor-module-split-plan.md) | `editor_module.py` 量化分析 + 拆分方案(13,321 行现状与分期提取计划) |
| [11-opentake-gap.md](11-opentake-gap.md) | OpenTake/OTIO/选模/画布对照:只学不换壳 |
| [12-otio-clip-fields.md](12-otio-clip-fields.md) | OTIO 概念 ↔ `_clips` 字段对照(不换真相源) |
| [14-canvas-strategy.md](14-canvas-strategy.md) | 自研导演台画布 vs infinite-canvas / LibTV 策略 |
| [15-long-term-iteration.md](15-long-term-iteration.md) | **长期迭代计划**(N 剪辑 / P 画布 / A Agent / D 数字人) |
| [16-aigc-canvas-gap.md](16-aigc-canvas-gap.md) | 主流 AIGC 画布借鉴清单 ↔ 落地状态 |
| [17-canvas-magnetic-invariants.md](17-canvas-magnetic-invariants.md) | **画布磁吸系统设计不变量**(边缘隙判据 / Bond / 阻力三段式 / React Flow v12 机制) |
| [18-codebase-health-2026-09.md](18-codebase-health-2026-09.md) | **代码库体检与优先级快照**(实测数据 / 吞异常 / Agent 能力门槛 / 三层优先级) |
| [19-canvas-design-review.md](19-canvas-design-review.md) | **AI 画布设计概论 · 21 种节点功能全景 · 双库分叉实测 · P0-P3 优化建议** |
| [comfyui-local-inference-plan.md](../comfyui-local-inference-plan.md) | ComfyUI 兼容与内置方案:workflow 粘贴即用 + 内置透明引擎 + AI 伙伴减负(方案未实施) |
| [sources/MANIFEST.md](sources/MANIFEST.md) | 全库 Markdown 源清单(自动生成) |
| [catalog.json](catalog.json) | 机器可读目录(自动生成) |

## 根上下文

- 项目根 [`CONTEXT.md`](../../CONTEXT.md) — 精简术语 + 指向本库  
- Agent 规则 [`.cursor/rules/project-knowledge.mdc`](../../.cursor/rules/project-knowledge.mdc)  
- 长期记忆 [`.workbuddy/memory/MEMORY.md`](../../.workbuddy/memory/MEMORY.md)

## 同步命令

```bash
# 在项目根执行:扫描全部 md → 刷新 MANIFEST + catalog.json
python scripts/sync_knowledge.py
```

## 活路径(编码时优先跟这些文件)

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

**剪辑抽出 / AI 体力活(副路径)**

```
app/modules/lego/clip_transform.py
app/modules/lego/editor_export.py
app/modules/lego/editor_burn.py
app/modules/lego/editor_subtitle_panel.py
app/modules/lego/editor_color_panel.py
app/modules/lego/editor_props_panel.py
app/modules/lego/editor_audio_panel.py
app/modules/lego/editor_ai_panel.py
app/modules/lego/ai_agent_panel.py
app/modules/lego/editor_preview_ux.py
app/modules/lego/editor_ux_commands.py
app/core/proxy_media.py
app/core/text_frame_map.py
app/core/edit_commands.py
app/core/filler_silence_detect.py
app/core/transition_plugin_registry.py
```

**拓展 / 闭环(按需)**

```
app/modules/lego/extensions_module.py
app/modules/lego/account_ops_module.py
app/modules/lego/drama_send_to_editor.py
app/modules/lego/character_management_module.py
app/core/canvas_bridge.py
app/core/editor_canvas_link.py
app/core/canvas_runtime.py
app/core/canvas_agent_runtime.py
app/core/project_agent_host.py
app/core/agent_policy.py
app/core/agent_session.py
app/core/agent_task_store.py
app/core/agent_runtime.py
app/plugins/drama_finder_plugin/
app/plugins/account_ops_plugin/
vendor/shiguang-canvas/   # 默认画布引擎;3D 导演台;数字人节点
vendor/infinite-canvas/   # scripts/setup_infinite_canvas.ps1
```

**明确不做**:重写时间线架构、GPU 流式预览大改、完整转场库、剪映商店包兼容、Desktop 栈迁入(见 `docs/P0_CAPCUT_ALIGN.md`).

自研拓展:`.cube` LUT 导入 · `transition_plugin_registry`(`ITransitionPlugin`).

知识库最近全量对照代码复核:**2026-08-19**(AI 剪辑差异化 + 剪辑↔画布 round-trip)。
