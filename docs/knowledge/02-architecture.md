# 02 — 架构

> 复核：2026-08-04

## 分层

```
Application (main_qt6.Application)
  └── MainWindow + ModuleRegistry（懒加载 LEGO 模块）
        └── EditorModule / Home / Settings / Extensions / …
              ↕ EventBus
        └── app/core（Timeline / Preview / FFmpeg / Scheduler / AI / Plugins / Agent）
```

## 启动序列

1. UTF-8 / crash hook  
2. 环境检查（PyQt6 必需，FFmpeg/GPU 建议）  
3. 路径 / EventBus / MasterClock / DataBus / SkillEngine / Auth  
4. 基础设施（security / permission / APM / alert / i18n）best-effort  
5. Blocks + Skills（含 `video_editing_skill.register_skills` 等）  
6. Qt Fusion + 深色 QSS  
7. MainWindow → 默认 home  
8. `qt_app.exec()`

## 双内核（`editor_scheduler.py`）

| 操作 | 倾向内核 |
|------|----------|
| preview / probe | LIGHTWEIGHT（PyAV） |
| clip / export / multi_track / ai_clip | PROFESSIONAL（FFmpeg/MLT） |

## 剪辑副路径（抽出模块）

```
EditorModule（宿主 ~10.8k）
  ├── clip_transform / editor_export / editor_burn     # 变换·导出·烧录
  ├── editor_subtitle_panel                            # 字幕 UI + AI + 去水词
  │     └── text_frame_map → edit_commands / filler_silence_detect
  └── Agent 面板 → capability_dispatcher → agent_pipeline_orchestrator
```

多轨导出改动优先读 `editor_export.py`，勿再堆进宿主上帝类。

## 渲染栈注意

存在多份 `RenderManager` / FFmpeg 查找逻辑：

- **活导出**: `app/core/render_manager.py`（经 scheduler）+ `editor_export` 拼片/叠轨
- `ExportRenderer`（`modules/render` 与 `lego/render`）：**2026-08 复核仍无业务引用**，勿当真相源
- `AppState`：**仍无外部引用**，勿当真相源（真相源 = `EditorModule._clips`）

## 插件 / 拓展三层

1. `core/plugin_manager` + `plugin_loader`  
2. `app/plugins/`（effect_/transition_/ai_effects/drama_finder）  
3. LEGO：**拓展中心** `extensions_module`（registry id=`extensions`）+ Blocks + SkillEngine + MCP  

旧 `plugins_module` 含短剧常驻标签实现，但**未注册**；运行时短剧以拓展中心弹窗 / 插件 `run()` 为主。冻结区 `drama-finder-ui` 仍锁 `plugins_module` 符号 + `drama_ui.py`。

## 关键约束

- 模块间优先 EventBus，避免硬依赖  
- UI 渲染，core 处理数据，MainWindow 调度  
- 对话框必须有 parent  
- **最小入侵、最大兼容**；不擅自重写时间线架构  
- 改播放/停声/画布变换/商店目录前先解冻（见 `08-frozen-zones.md`）
