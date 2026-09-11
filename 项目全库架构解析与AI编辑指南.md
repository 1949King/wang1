# 拾光剪影 — 全库架构解析与直接编辑指南

> 本文档面向 **DeepSeek / Cursor** 等 AI 编辑器，提供项目全貌、分层架构、关键文件索引、铁律红线、以及可直接落地的修改入口。目标：AI 读完即可安全上手改代码，不出格、不踩冻结区、不破坏活路径。
>
> 生成时间：2026-09-08 · 基于真实代码通读（非命名推测）。规模口径为 AST/逐行实测。

---

## 0. 一页看懂这个项目

**拾光剪影** = 基于 **OpenShot(MLT) 二次开发** 的 **PyQt6 桌面端短剧精剪 + AI 导演台**。

一句话产品定位：**竖切可重复的「导演台（含数字人）→ 分镜 → 入轨精剪」**，智能体只做"确认后的遥控器"，不默认一键成片。

| 维度 | 结论 |
|---|---|
| 技术栈 | PyQt6 + FFmpeg + PyAV + OpenShot/MLT + Three.js(画布) + React/Zustand/Vite(前端画布) + Ollama + DeepSeek/OpenAI 等 16 个 provider |
| 规模 | Python 约 **15.7 万行**(app 438 文件) + 前端 shiguang-canvas 约 3.3 万行 + AI-Canvas-tauri 约 16.7 万行 + OpenShot 本体约 73 万行 |
| 真相源 | `EditorModule._clips`（时间线）、`SubtitleManager.subtitles`、`_active_stickers` |
| 活路径 | 剪辑模块 + AI 画布 + Agent + 数字人（发布/筛选已卸为接口壳） |
| 政府文档 | 知识库 `docs/knowledge/INDEX.md` 是人和 AI 共用的 Single Source of Truth |
| 监管机制 | 冻结区 `frozen_zones.json`（7 个 zone），未解冻禁改 |

---

## 1. 必须先遵守的红线（不遵守 = 白干 + 恢复）

> 这些来自 `.trae/rules/*.md` + `AGENTS.md` + 知识库，是项目的**元规则**。AI 编辑前必须内化。

### 1.1 三条开发前前置

1. **未读结构不编码**：先读 `docs/knowledge/INDEX.md`、`CONTEXT.md`、`08-frozen-zones.md`。
2. **未懂业务不新增**：先理解启动流程、窗口跳转、EventBus、权限状态、信号槽绑定。
3. **最小改动优先**：只碰需求相关文件；不顺手重构、不清理无关代码、不新增无用文件。

### 1.2 八条编码铁律

1. 命名：类大驼峰 `PascalCase` · 方法/函数下划线 `snake_case` · 私有 `_` 前缀 · 常量 `UPPER_SNAKE`。禁 `aaa/temp/test`。
2. 导入分组：标准库 → 第三方 → 本地；优先 `from app.xxx import`。
3. 分层钙读：**UI 只渲染，core 算数据，MainWindow 调度**。UI 层不写复杂业务。
4. 日志：用 `logger`，禁新增裸 `print()`；禁 `except: pass`（至少 `logger.warning`）。
5. 异常：空值/格式校验、防重复点击、错误提示全覆盖，不许闪退卡死。
6. 状态归集：登录/权限/版本统一走 auth/permission 模块，禁 UI 乱放全局状态。
7. 弹窗必须有 parent：`QDialog(self)`/`QMessageBox(self)`，禁野窗口。
8. 测试：改 Python 至少 `py_compile`；改渲染/导出验证 C++/FFmpeg fallback。

### 1.3 冻结区（最高优先级，未「解冻 <zone-id>」禁止改）

机器校验：`python scripts/frozen_zone_guard.py`；改完后重写基线 `python scripts/frozen_zone_guard.py --update`。

| zone-id | 内容 | 涉及典型文件 |
|---|---|---|
| `playback-av` | 时间线播放 · 音画同步 | `editor_module`、`preview_manager` |
| `exit-media` | 关程序停声 | `main_window` |
| `clip-transform` | 归一化变换模型 | `clip_transform` |
| `transform-bake` | 变换关键帧导出 bake | 导出链路 |
| `canvas-transform` | 预览画布变换交互 | 预览合成 |
| `plugin-host-ui` | 插件宿主常驻 UI 入口 | `plugins_module`（短剧功能已卸，宿主开合仍锁） |
| `plugin-store-catalog` | 插件商店真实目录 | `app/plugins` 真实项 |

**重要**：`_render_timeline_frame`（预览合成核心，~250 行）紧邻 `playback-av`，**未解冻禁改**。

---

## 2. 分层架构总览（脑内地图）

```
ENTRY   app/main_qt6.py  →  MainWindow + ModuleRegistry（懒加载 LEGO 模块）
UI      app/modules/lego/   EditorModule + Home/Settings/Extensions...   [EditorModule 是上帝类，已拆 7 个 Mixin]
CORE    app/core/           Timeline · Preview · FFmpeg · Scheduler · AI · Agent · Plugins · Render
CANVAS  vendor/shiguang-canvas/   （Python bridge.c → 默认画布引擎）
        vendor/AI-Canvas-tauri/    （Tauri 桌面智能体画布，磁吸 + 3D 导演台）
DATA    data/auth.db · *.timeline · autosave/ · cache/ · memory_store JSONL
EXT     Ollama(本地) · DeepSeek/OpenAI 等云端 · app/plugins · skills/ + external
```

**启动序列**：
```
UTF-8/crash hook → 环境检查 → 路径/EventBus/MasterClock/DataBus/SkillEngine/Auth
→ 基础设施(security/permission/APM/alert/i18n) best-effort → Blocks + Skills → Qt Fusion+深色QSS
→ MainWindow(默认 home) → qt_app.exec()
```

---

## 3. 分层细节与关键文件索引（可直接跳转编辑）

### 3.1 入口与运行时（很小，多为转发）

| 文件 | 行数 | 职责 | 备注 |
|---|---|---|---|
| `app/main_qt6.py` | 840 | 应用入口/启动序列 | |
| `app/modules/lego/main_window.py` | 1199 | 主窗口调度 | 弹窗父窗口、模块切换 |
| `app/modules/lego/module_registry.py` | — | LEGO 模块注册表 | 懒加载，禁硬依赖 |
| `app/config.json` | — | 运行配置 | |

### 3.2 编辑器核心 `editor_module.py` + Mixin

> **现状**：宿主实测约 **8492 行**（从历史峰值 13,321 分七波抽除后）。类方法总数约 300+。是活路径核心、贴近冻结区。

Mixin 拆分清单（累计抽出方法，改这些文件 = 安全）：

| Mixin 文件 | 方法数 | 行数 | 说明 |
|---|---|---|---|
| `ai_agent_panel.py` | 6 | 242 | 对话式 Agent 指令 |
| `editor_export_panel.py` | 8 | ~350 | 导出 |
| `editor_agent_panel_mixin.py` | 17 | 1667 | Agent 面板 |
| `editor_effects_mixin.py` | 12 | 928 | 特效/滤镜/调色/转场 |
| `editor_ui_builder_mixin.py` | 10 | 1255 | UI 构建 |
| `editor_ai_process_mixin.py` | 7 | 516 | AI 处理 |
| `editor_ai_tools_mixin.py` | 22 | 388 | AI 工具按钮 |
| `editor_agent_runtime_mixin.py` | 42 | ~736 | Agent 运行时 |

另有**已抽出模块**（编辑走这些，勿堆回宿主）：
`clip_transform.py` · `editor_export.py` · `editor_burn.py` · `editor_subtitle_panel.py` · `text_frame_map.py` · `edit_commands.py` · `filler_silence_detect.py`

> ⚠️ MRO 顺序（不要打乱）：`EditorModule → BaseModule → QWidget → AiAgentPanelMixin → EditorExportPanelMixin → EditorAgentPanelMixin → EditorEffectsMixin → EditorUiBuilderMixin → EditorAiProcessMixin → EditorAiToolsMixin → EditorAgentRuntimeMixin → object`

**🔴 禁止近期拆分/改动**（高风险核心，须解冻或架构级决策）：
- 预览/渲染组（51 方法/~1966 行）：`_render_timeline_frame`（250 行全文件最大）等
- 时间线编辑组（79 方法/~2249 行）：单选/多选/框选/吸附/跨轨
- 事件回调/核心机制组（129 方法/~3102 行）：`__init__`(192)/`_apply_action`(113 撤销统一入口)/`_sync_kernel_timeline`(59)/`_sync_timeline_widget_state`(70)
- Agent 指令执行/学习闭环（~20 方法）：`_agent_dispatch`/`_agent_brain_learn`/`agent_split_clip`/`agent_ripple_delete_range`/`_on_edit_agent_result`

**剪辑相关硬约束**：
- 真相源 `EditorModule._clips`，禁建第二套时间线状态
- 轨索引用 `find_track_index_by_type`，禁魔法数字 `track == 1`
- 播放用墙钟 + 顺序解码，勿恢复 `+=0.033` 主时钟
- 联动音频片（视频的音频轨孪生）在 BGM 同步时须过滤，避免与主播双开

### 3.3 核心业务层 `app/core/`（改业务逻辑的主战场）

#### 时间线 / 预览 / 渲染 / 调度
| 文件 | 行数 | 职责 |
|---|---|---|
| `editor_scheduler.py` | 949 | **双内核调度**：`EditorKernel`+`KernelSelection`；preview/probe → LIGHTWEIGHT(PyAV)；clip/export/multi_track → PROFESSIONAL(FFmpeg/MLT) |
| `render_manager.py` | 895 | **三级 fallback**：C++ 引擎(cpp_engine) → FFmpeg CLI → CPU 软渲染；含 `HardwareDetector` |
| `timeline_manager.py` | 840 | 时间线数据真相源之一 |
| `preview_manager.py` | — | 预览管理（墙钟播放核心） |
| `preview_generator.py` | — | 预览生成 |
| `waveform_generator.py` | — | 音频波形预分析 |
| `timeline_dsl.py` | 705 | 时间线 DSL |
| `multitrack_editor.py` | 771 | 多轨 |
| `multithread_rendering.py` | 553 | 渲染多线程 |
| `keyframe_animation.py` | 614 | 关键帧动画 |
| `speed_ramping.py` | 437 | 变速（仍弱，待优化） |
| `lossless_trim.py` | 185 | 无损裁剪 |
| `edit_commands.py` | 437 | 编辑命令（公开接口层） |
| `text_frame_map.py` | — | 字幕帧绑定（B0） |
| `filler_silence_detect.py` | 451 | 静音检测（B2） |

#### 视频处理子目录 `app/core/video_processing/`
| 文件 | 行数 | 职责 |
|---|---|---|
| `pyav_engine.py` | 330 | PyAV 轻内核（预览/草稿） |
| `mlt_engine.py` | 408 | MLT 专业内核 |
| `mlt_engine_cpp.py` | 1665 | MLT C++ 引擎 |
| `cpp_engine/` | ~433+311 | C++ 引擎 init + 性能优化 |
| `mlt_api_detect.py` | 167 | MLT API 检测 |

> 改渲染/导出必须走 `RenderManager`（C++ → FFmpeg → CPU fallback）；GPU 检测走现有 `HardwareDetector`；FFmpeg 走 `ffmpeg_utils.py`，禁在 UI 直接拼复杂 FFmpeg。

#### AI / Agent（差异化卖点核心）
| 文件 | 行数 | 职责 |
|---|---|---|
| `agent_brain.py` | 453 | **左右脑神经网络**：23 神经元 + `BrainHemisphere`(LEFT/RIGHT/CORPUS_CALLOSUM) + Hebbian 学习；`reinforce_path`/`learn_from_feedback` 持久化到 `MemoryStore("brain_synapse")` |
| `capability_dispatcher.py` | 354 | 统一能力调度 `CapabilityDispatcher`；每次 invoke 激活 AgentBrain + 记 trace + 广播 |
| `capability_handlers.py` | 830 | 注册 **25 capability**（editor 7 / model 3 / extension 3 / workflow 2 / account 3 / pipeline 6 / canvas 3） |
| `agent_pipeline_orchestrator.py` | 571 | **六级流程**：route → [generation/editing] → preview_validation → scoring → script_generation → execute_editing → `_emit_done`+`reinforce_path` |
| `agent_pipeline_router.py` | 220 | 业务分流 GENERATION/EDITING（仅看素材有无） |
| `ai_engine.py` | 1296 | AI 统一入口：16 provider + Ollama + LRU缓存 + 熔断(60s) + 预算 + 指数退避 |
| `ai/` 子目录 | — | `llm_clipper`(576)· `video_generation_client`(284)· `audio_emotion_analyzer`(285)· `content_classifier`(510)· `viral_detector`(675)· `whisper_asr`(211)· `prompt_templates`(327)· `comfy_client`(354)· `comfy_provider`(411)· `pose_extract_service`(301)· `workflow_importer`(258) |
| `five_dimension_scorer.py` | 282 | **五维打分**（画面25/高光叙事25/文案20/BGM15/镜头时长15）；D 级(<60)剔除 |
| `llm_editor.py` | 835 | 自然语言 → 编辑指令 |
| `subtitle_generator.py` | 506 | 字幕生成 |
| `lip_sync.py` | 687 | 嘴型同步（Viseme 12 嘴型） |
| `neural/` | — | 风格迁移/背景替换/超分/修复 |

#### 画布与 Agent 桥接
| 文件 | 职责 |
|---|---|
| `canvas_bridge.py` / `canvas_runtime.py` | Python ↔ 前端画布 bridge |
| `canvas_aigc.py` | 画布 AIGC 调用（诚实失败） |
| `canvas_agent_runtime.py` | 画布 Agent 运行时 |
| `editor_canvas_link.py` | 剪辑↔画布 round-trip |
| `project_agent_host.py` | 项目级 Agent 主机 |
| `agent_policy.py` / `agent_session.py` / `agent_task_store.py` / `agent_runtime.py` / `agent_action_registry.py` | Agent 基础设施 |

#### 插件 / 拓展三层
1. `core/plugin_manager` + `plugin_loader`
2. `app/plugins/`（effect_/transition_/ai_effects/drama_finder/account_ops）
3. LEGO：**拓展中心** `extensions_module`（registry id=`extensions`）+ Blocks + SkillEngine + MCP

### 3.4 UI 层 `app/modules/lego/`（改界面/交互）
`editor_module.py` · `timeline_widget.py` · `timeline_subwidgets.py` · `timeline_ui.py` · `settings_module.py`(含「🧰一键环境诊断」入口) · `extensions_module.py` · `login_window.py` · `auth.py` · `theme_manager.py` · `features_search.py` · `copywriting_module.py` · `tasks_module.py` · `help_module.py` · `shortcut_manager.py` 等。

---

## 4. 前端画布（两个库，主从关系）⚠️ 特别注意

> **惯例**：`vendor/shiguang-canvas/` = 默认画布引擎（主路径）；`vendor/AI-Canvas-tauri/` 的 `src/libtv/` 含 shiguang-canvas 的**共享代码副本**（硬链接/同步关系）。改共享逻辑须**双库同步**。

### 4.1 shiguang-canvas（默认画布）
- 技术栈：React 19 + Three.js 0.185 + @xyflow/react 12.6 + Zustand 5 + Vite 6.2
- 规模：78 源文件 / 33,314 行

| 文件 | 行数 | 职责 |
|---|---|---|
| `App.tsx` | — | 应用入口 |
| `CanvasShell.tsx` | — | 画布外壳（ReactFlow + 磁吸集成） |
| `Stage3D.tsx` | 4208 | 3D 导演台（纯 Three.js，Dummy13 关节素模） |
| `store.ts` | 2104 | 核心 Zustand Store（**单体**） |
| `nodes.tsx` | — | 节点定义（20 种内置） |
| `bridge.ts` | — | 与 Python 后端通信 |
| `magnetic/MagneticEngine.ts` | — | 磁吸计算核心 |
| `magnetic/SpatialIndex.ts` | — | 空间索引 Grid Hash（O(n²)→候选桶） |
| `magnetic/CardStack.ts` | — | 层叠/多版本 |
| `magnetic/SoftConnection.ts` | — | 软连接系统 |
| `magnetic/useMagneticDrag.ts` | — | 拖拽 Hook |
| `stores/` | — | `node-factory`/`project-storage`/`schema-migrations`/`templates`/`history-store`/`persist-media` |

### 4.2 AI-Canvas-tauri（智能体画布 + Tauri 桌面）
- 技术栈：React + Three.js + @xyflow/react + **20 个 Slice Store** + Tauri 2 + Tailwind + GSAP + Konva
- 规模：575 源文件 / **167,129 行**
- `src/libtv/` 是共享库（与 shiguang-canvas 同源同步）
- `src/store/` 多 Slice Store（20 文件）：`useAppStore.ts` 聚合 19 slice

**修改提醒**：
- 两库 mobile `magnetic/*.ts`、`Stage3D.tsx`、`store.ts`、`stores/*` 都要求强一致。改前 `git diff` 对比，改后**双向同步 + hash 校验**（此前已用硬链接/同步脚本保证 100% 一致，勿破坏）。
- AI-Canvas-tauri 有 **Rolldown-vite Windows 盘符 is_absolute bug**：勿用 vite alias 指向共享文件，硬链接是验证过的 workaround。
- `SpatialAnalyzer.ts` 曾是无连线孤儿代码（若仍在，要么接「🗂一键整理布局」要么删）。

---

## 5. 关键数据契约 / 单一事实来源

- 知识库 `docs/knowledge/`（INDEX + 00–17）+ `catalog.json` + `sources/MANIFEST.md`，改架构后**先改知识库再改代码**，然后 `python scripts/sync_knowledge.py`。
- 冻结区 `frozen_zones.json` + `frozen_zones.hashes.json`（哈希基线，机器校验）。
- 双库数据契约文件以硬链接保证单源。

---

## 6. 已知问题与风险（改代码前必读）

> 详细列表在 `docs/knowledge/05-known-issues.md`（量大，按需 grep）。

**P0（高风险，1-2 周）**：
- `AgentPipelineOrchestrator._emit_done` 的 `reinforce_path` 基于**预设路径**而非真实执行路径——若在第 3 步就挂，仍会强化整条链，学习信号不准确。若改，需追踪真实执行路径。

**P1（中风险，2-4 周）**：
- `agent_pipeline_router.py` 只看"有无素材"分流，忽略创意简报/目标平台/时长，混合再创作易误判。
- `AccountAnalysisSkill` 是纯本地，未调 `ViralOptimizationEngine`（能力不对等）。
- `capability_handlers` L282 `account.publish` 默认 `skill_id="account_publish"` 不存在（实际是 `matrix_publish`/`publish_content`）。
- Agent 覆盖仍薄：仅暴露 split/filter/transition/timeline_context/ripple_delete_range/suggest_cleanup 6 个；导入/导出/字幕 CRUD/贴纸/关键帧/调色未暴露（按 70/20/10 按需加）。

**P2（技术债）**：
- import 风格不统一（~41 处）
- Skill 框架部分绕开 SkillEngine 直接做业务
- severity 阈值硬编码（5000/20000 播放量）
- `agent_pipeline_router` 的 `_NEURON_TAXONOMY` 与 capability 需一一对应，注册后记得 `sync_from_dispatcher`
- **store.ts 主从漂移风险**：一度两库 store.ts 行数不同；需明确主从并同步

**已知"假成功"接口（勿改，是产品定位）**：`PublishContentSkill`/`PluginStore`/`account.*` 发布/筛选为接口壳，诚实失败是刻意的，不是 bug。

---

## 7. 评审视角：架构亮点 / 隐患 / 建议（百万UP + DeepSeek CEO 视角）

### 7.1 值得称道的设计 ✅
1. **Agent 左右脑 + Hebbian 学习是真闭环**（不是噱头）：`reinforce_path`/`learn_from_feedback` 有 4 条真实业务入口，持久化到 MemoryStore，启动加载——极少见把「神经网络学习」落进桌面剪辑软件并跑通。
2. **三级渲染 fallback 非常务实**：C++ → FFmpeg → CPU，兼容一切环境；双内核（PyAV 轻 / MLT 重）按操作分流，是量产级取舍。
3. **冻结区 + 哈希基线监管**：把"已验证能力锁死"做成机器可校验，有效防 AI 瞎改回退功能——这是一线大厂才有的纪律。
4. **最小入侵策略 + 大量 Mixin 拆分**：把 13k 上帝类拆成 8 个 Mixin，不推翻重构，保住稳定性。
5. **诚实失败的产品哲学**：发布/筛选壳不造假成功，避免虚胖。
6. **editor_module 从 13,321 行压到 8,492 行**，且全程保住 <10k 硬约束——持续重构的真实战绩。

### 7.2 风险与隐患 ⚠️
1. **单文件规模天花板依旧**：`ai_engine.py`(1296)、`mlt_engine_cpp.py`(1665)、`Stage3D.tsx`(4208)、`store.ts`(2104/2078)、`editor_module.py`(8492) 仍是巨型单体，可维护性负担重。
2. **双库代码重复**：两套画布库共享逻辑靠"同步"而非"单一依赖"，drift 风险长期存在。
3. **学习信号不够精确**：`reinforce_path` 基于预设路径，需要落地真实路径追踪才值得信赖。
4. **Agent 能力覆盖偏薄**：相比产品野心，editor capability 只有 6 个，闭环纵深不足。
5. **路由分流死板**：只看素材有无，缺少上下文融合判断。
6. **UI 层仍会夹带业务逻辑风险**：Mixin 拆分虽好，但新增代码须继续坚持"纯 UI"，否则前功尽弃。

### 7.3 给 AI 编辑者的三句建议
1. **改 AI/Agent 先看 `agent_brain` + `capability_dispatcher` 的注册链路**，新能力记得双注册（capability + `sync_from_dispatcher`）。
2. **改画布先 diff 双库 differences**，改完双向同步并跑 hash。
3. **改编辑器永远从「最小点」入手**：优先复用已有 Mixin/公开接口（如 `edit_commands.py`、`agent_*` 包装），不要直接闭包访问 `self._clips` 或写冻结区符号。

---

## 8. 标准验证命令（每次改动后跑）

```powershell
# Python 语法
python -m py_compile <改的文件>                    # 单文件
python -m compileall app/core app/modules          # 全量

# 冻结区校验（改到冻结符号前必须跑，跑通才可改）
python scripts/frozen_zone_guard.py
# 修改冻结区后解冻改完，重写基线：
python scripts/frozen_zone_guard.py --update

# 知识库同步（改了 docs/knowledge 后）
python scripts/sync_knowledge.py

# 前端构建（改画布后）
# shiguang-canvas:
cd vendor/shiguang-canvas && npm run build
# AI-Canvas-tauri（跑前先对比双库 diff）
cd vendor/AI-Canvas-tauri && npm run build && npm run typecheck
```

---

## 9. 入口速查（下一步该看哪）

| 想干嘛 | 看这个 |
|---|---|
| 改剪辑/时间线 | `editor_module.py` + `timeline_widget.py` + `editor_scheduler.py` |
| 改预览/播放 | `preview_manager.py`（墙钟）+ `_render_timeline_frame`（⚠️冻结邻域） |
| 改导出 | `editor_export.py` + `render_manager.py` |
| 改字幕 | `editor_subtitle_panel.py` + `subtitle_manager.py` + `editor_burn.py` |
| 改 AI 生成 | `ai_engine.py` + `ai_video_generation_pipeline.py` + `agent_pipeline_orchestrator.py` |
| 改 Agent 能力 | `capability_dispatcher.py` + `capability_handlers.py` + `agent_brain.py` |
| 改画布 | `bridge.py` + `CanvasShell.tsx` + `magnetic/` + `Stage3D.tsx`（双库同步） |
| 改数字人 | `Stage3D.tsx` + `riggedHumanoid.ts` + `lip_sync.py` + `digitalHuman` 节点 |
| 改登录/权限 | `auth.py` + `permission_management.py` |
| 改环境诊断 | `settings_module.py`（「🧰一键环境诊断」） |

---

*本文档为一次性全库解析产物，正式修订以后续 `docs/knowledge/*.md` 为准。*