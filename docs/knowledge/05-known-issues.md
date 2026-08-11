# 05 — 已知问题与近期修复

## 已修复（2026-08-12 · AI 画布「预热卡住 / 切换引擎无反应」）

**现象**：进入「AI 画布」状态长期停在「正在预热…」，中间 WebView 一片白；顶栏切换「拾光导演台 / infinite-canvas」两个引擎也像没反应。日志里其实已经出现 `canvas static server on …3011/3001`，说明本机静态服务已起来。

**根因**：`character_management_module.py` 在后台线程（`CanvasWarmup` / 引擎切换 / 手动启动 / Agent）里用 `QTimer.singleShot(0, lambda…)` 试图回主线程更新 UI、调用 `_load_canvas`。QTimer 必须在归属线程调度，从纯 `threading.Thread` 里 `singleShot` 经常**永不触发**——于是服务已监听、状态不更新、WebView 从不 `load(url)`。叠加：画布就绪后还会自动 `warmup` `canvas-agent`（npx，常 30–60s+），即便 UI 回调偶尔成功也会感觉「预热永远不完」。

**修复**：后台改 `pyqtSignal` 跨线程投递；取消进模块自动拉起 Agent（需用时点「连接 Agent」）；WebView `loadFinished` 反馈；切换引擎确认默认「是」并先清空页面提示。

涉及：`app/modules/lego/character_management_module.py`。需重启 Qt6 进程后生效。

## 已完善（2026-08-12 · 删除 App 页 · UI 仅画布/3D）

顶栏只保留「画布 | 3D 导演台」；AppBoard 已删，分镜在节点检视器编辑。

## 已完善（2026-08-12 · UI 简洁化 + 3D 导演台）

| 项 | 说明 |
|----|------|
| UI | 顶栏模式切换（画布/App/3D）；侧栏折叠面板；去掉按钮墙 |
| 3D | `Stage3D.tsx`：人体素模/道具、VRS 工具、导演/机位视角、FOV、截图→镜头节点 |
| 局限 | 非 LibTV 关节级姿态；无 720° 全景上传；素模级站位构图 |

涉及：`vendor/shiguang-canvas`（`CanvasShell` / `Stage3D` / `three`）

## 已完善（2026-08-12 · 对齐主流画布：@素材 / 变体 / 全量入轨）

| 项 | 说明 |
|----|------|
| 对照表 | [`16-aigc-canvas-gap.md`](16-aigc-canvas-gap.md) |
| @素材/@标题 | 提示词展开；有图则作 img2img 参考 |
| 上游汇聚 | 连线剧本/提示词写入生成提示 |
| 变体 | 选中镜头 → 表情/服装/背景×3 |
| 全部入轨 | 按序 ingest；`duration_sec` → 静图短视频时长 |

## 已完善（2026-08-12 · P2：三视图 / 参考重绘 / 分镜导出）

| 项 | 说明 |
|----|------|
| 三视图 | 导演台「角色三视图」铺正/侧/背镜头节点 |
| 参考重绘 | 有图或首帧时 img2img；完整蒙版局部后置 |
| 导出 | 分镜 JSON + CSV 下载 |

## 已完善（2026-08-12 · 长期计划 P1：@角色 / 批量 / img2img）

| 项 | 说明 |
|----|------|
| 计划 | [`15-long-term-iteration.md`](15-long-term-iteration.md) |
| @角色 | bridge prefs 带 `character_prompt`；画布展开 + 自动注入 |
| 批量 | 导演台「批量生成全部镜头」可中断 |
| img2img | `reference_image` → 优先图生图，失败降级文生图并在状态条说明 |

涉及：`canvas_bridge.py` · `character_management_module.py` · `vendor/shiguang-canvas`

## 已完善（2026-08-12 · 导演台迭代：首尾帧 / 拉片 / App 模式 / 模板）

| 项 | 说明 |
|----|------|
| 首尾帧 | 镜头·视频节点可上传首/尾帧；生成提示词附带一致性约束 |
| 拉片 | `POST /host/storyboard-breakdown`（AIEngine + 启发式）→ `applyStoryboard` 铺节点 |
| App 模式 | 画布/App 切换；表单编辑分镜 |
| 模板 | localStorage 工作流模板 |
| 局限 | 首尾帧尚未 img2img；拉片依赖已激活对话模型 |

涉及：`canvas_bridge.py` · `vendor/shiguang-canvas` · [`14-canvas-strategy.md`](14-canvas-strategy.md)

## 已完善（2026-08-12 · 导演台「生成选中节点」接通 AIGC）

| 项 | 说明 |
|----|------|
| API | `POST /host/generate-image`：OpenAI-compatible `/images/generations`（硅基流动 FLUX 等） |
| UI | 生图模型下拉（`/host/image-models`）；失败占位兜底 |
| 鉴权 | 画布 URL 带 bridge token；inject 写入 `__SHIGUANG_BRIDGE_TOKEN` |

涉及：`canvas_bridge.py` · `vendor/shiguang-canvas` · `character_management_module.py`

## 已完善（2026-08-12 · 自研拾光导演台画布 MVP，默认替代 infinite-canvas）

| 项 | 说明 |
|----|------|
| 前端 | `vendor/shiguang-canvas`：React Flow 节点无限画布（剧本/镜头/提示词/图/视频、九宫格、连线、本地工程） |
| 宿主 | `canvas_runtime` 默认引擎 `shiguang`（:3010/:3011）；`SHIGUANG_CANVAS_ENGINE=infinite` 回退 |
| 桥 | 复用 `canvas_bridge`：同步模型池、发送到剪辑、prefs |
| 文档 | [`14-canvas-strategy.md`](14-canvas-strategy.md) |
| 局限 | MVP 生图为占位图；角色一致性/真实 AIGC/局部重绘后续迭代 |

## 已完善（2026-08-12 · 帮助中心增加 LibTV / TapNow 外链备选）

| 项 | 说明 |
|----|------|
| 话题 | 新增「🌐 外部画布备选」：浏览器直达 LibTV / TapNow；诚实标明非内置、不自动入轨 |
| AI画布页 | 同页增加外链小节，搜索「LibTV」「TapNow」可命中 |

涉及：`app/modules/lego/help_module.py`

## 已完善（2026-08-12 · OpenTake 对照：Agent 工具面体验，不换壳）

| 项 | 说明 |
|----|------|
| 差距文档 | [`11`](11-opentake-gap.md) / [`12`](12-otio-clip-fields.md) / [`13`](13-agent-skill-memory.md) |
| 白名单+ClipSkills | `agent_action_registry`；L0/L1/L2 提示；MCP 缺口表 |
| 时间线自省 | gaps/tracks/in·out；SkillEngine.`list_all` |
| 选模 | `ensure_active_provider_sensible`；`PROVIDER_ACTIVATED`；云端保存自动激活 |
| 多集记忆 | `MemoryStore.project_context`；Agent 面板剧名/集数/平台 |
| 画布 | inject 展示激活模型；prefs 同步（仍 infinite-canvas） |

涉及：`agent_action_registry` · `memory_store` · `model_config` · `editor_module` · `canvas_bridge` · `character_management_module` · `model_management`

## 已完善（2026-08-11 · 帮助中心缺 AI画布 / AIGC 模型内容）

**现象**：`help_module.py` 硬编码 17 个帮助话题，均是较早期就存在的模块；后续新增的 `characters`（"AI 画布"，镶嵌 infinite-canvas，`default_enabled=True` 的常驻模块）和 `model_management.py` 里新增的「🎨 AIGC」标签页（生图/生视频/语音模型目录）上线时都没有回头更新帮助内容，帮助中心里搜"画布"/"AIGC"完全搜不到东西。

**修复**：
- 新增帮助话题「🎨 AI画布」（`_ai_canvas()`），覆盖：前置依赖（PyQt6-WebEngine + `setup_infinite_canvas.ps1`）、dist 秒开/Vite 首次慢的正常现象、角色库、右下角「发送到剪辑/同步模型/连接 Agent」面板、线性插帧非 RIFE 的诚实说明。
- 「🤖 模型广场」话题（`_models()`）补一节「🎨 AIGC 标签页」，说明它和模型广场（对话模型）是两码事、怎么先在模型广场填 Key 再回 AIGC 页选生图/生视频型号、配好后在 AI 画布生效。
- 话题总数从文档字符串里过期的"16"更正为实际"18"。

**验证**：`.venv312` 下实例化 `HelpModule` 直接渲染 `_ai_canvas()`/`_models()` 无异常；`_on_help_search("AI画布")`/`_on_help_search("AIGC")` 均命中新内容（现有搜索机制按 `self._help_topics` 动态提取渲染文本，新增话题自动被搜索覆盖，无需额外接线）。

涉及：`app/modules/lego/help_module.py`。

## 已修复（2026-08-11 · AIEngine.__init__ 被 get_instance() 腰斩，_clients_loaded 从未设置）

**现象**：文案生成等所有走 `ai_engine.chat_with_fallback()`/`chat()` 的功能点击即弹「LLM 不可用：ai_engine: 'AIEngineEnhanced' object has no attribute '_clients_loaded'」。

**根因**：`app/core/ai_engine.py` 的历史某次编辑把新增的 `get_instance()` classmethod **误粘贴在 `AIEngine.__init__` 方法体中间**（`self._initialized = True` 之后、`self._cloud_api = None` 之前）。由于 `get_instance` 与其后 `return cls._instance` 之后的那些语句缩进层级相同，Python 并不报语法错误，而是把 `self._cloud_api = None` 起到 `logger.info(...)` 结束的一大段代码全部解析成 `get_instance()` 里 `return` 之后的**不可达死代码**——效果是 `AIEngine.__init__` 实际只执行了 `self._initialized = True` 就结束，`_cloud_api`/`_ollama_client`/`_clients_loaded`/`_stats`/`_cache`/`_circuit_open`/`_default_providers`/`_pricing` 全部从未被设置。`_ensure_clients()` 里原来是裸 `if self._clients_loaded:` 直接属性访问，一旦被调用立刻 `AttributeError` 崩溃到 UI。

**修复**（本次核实后提交，此前已在工作区修好但未提交）：
- `get_instance()` 移回 `__init__` 方法体**之后**，不再腰斩 `__init__`。
- `__init__`/`_ensure_clients` 里的直接属性访问改为 `getattr(self, "_xxx", default)`，即使今后再出现类似结构性错误也不会崩溃，只会静默走默认值。
- `_ensure_clients()` 新增"旧单例若曾错误初始化，补齐缺失属性"防御块，兼容进程内已存在的、由旧代码错误构造的单例对象。

**验证**：`.venv312` 下实测 `ai_engine._ensure_clients()` 与 `ai_engine.chat_with_fallback(...)` 完整跑通，`_clients_loaded` 正确存在且为 `True`，真实拿到一次云端 provider 回复；`py_compile` 通过。

**用户侧**：若重启前仍复现此报错，是因为正在运行的进程内存里还是旧对象（Python 不会自动重载已导入模块），**重启程序**即可加载已修复的代码。

## 已完善（2026-08-11 · DeepSeek 已配置但 Agent/文案无响应）

| 项 | 说明 |
|----|------|
| 根因 | `app/data/active_provider.json` 仍为 `ollama`：只保存 Key 未激活；文案读激活项；Agent 下拉默认 Ollama 在前，本地不可用时把 `错误: …` 当正常结果，解析失败像「没响应」 |
| 修复 | 保存云端配置后自动激活；文案优先 `chat(active)`；Agent 下拉按激活/已配置排序并标 ★；引擎错误串走 `error_ready`；本机激活已切到 `deepseek`（chat 实测通） |
| 用法 | 模型管理 → DeepSeek 保存（自动激活）→ Agent 下拉选 ★ DeepSeek → 再试 |

涉及：`model_management.py` · `copywriting_module.py` · `editor_module.py` · `model_config.load/save_active_provider`

## 已完善（2026-08-11 · 技术债务清理第一批：死代码路径）

对 2026-08-11 项目整体评估中列出的技术债务，本轮先做风险最低的一项：删除已确认零外部引用的死代码。

| 文件/目录 | 引用核查方式 | 结论 |
|---|---|---|
| `app/modules/render/`（8 文件） | 全仓库 grep `from app.modules.render` / `import app.modules.render` | 仅 `app/core/performance_benchmark.py` 一处内部引用（该文件本身也是死代码） |
| `app/modules/lego/render/`（6 文件） | 全仓库 grep `lego.render` | 仅被上条 `render_performance_optimizer.py` 交叉引用，无外部业务方 |
| `app/core/performance_benchmark.py` | 全仓库 grep `performance_benchmark` / `PerformanceBenchmark` | 零外部引用（无任何模块调用 `get_performance_benchmark`） |
| `app/core/app_state.py`（`AppState`） | 全仓库 grep `app_state` / `AppState`（不区分大小写） | 零外部引用，与文档记录一致 |
| `app/modules/lego/ai_clip_flow.py.fixbak` | 文件名后缀即非源码 | 遗留备份文件，直接删除 |

删除后验收：`compileall app/core app/modules` 通过；`.venv312` 实际环境下 `import editor_module` / `main_window` / `preview_manager` 全部成功；`python scripts/frozen_zone_guard.py` 确认无 drift（53 locks intact，这些路径均不在冻结区清单内）。

涉及：见 [`02-architecture.md`](02-architecture.md)「渲染栈注意」章节。

## 已完善（2026-08-11 · A4 第二刀：scrub = 时间线合成）

| 项 | 说明 |
|----|------|
| scrub 预览 | `_render_scrub_preview_at` 改为调用 `_render_timeline_frame`（转场/叠轨/画幅与播放一致） |
| 拖动静音 | 实例级 stub `_arm_media_audio` / `_sync_bgm_audio`，不改冻结符号体；松手再 `_sync_scrub_audio_position` |
| scrub open | 切源 `for_scrub=playing\|\|scrubbing`，避免拖 scrub 跑完整帧数探针 |
| 叠层降载 | scrub 中跳过字幕/贴纸/变换手柄；松手高质量路径再刷 |

涉及：`editor_module.py`（未改 `FROZEN:playback-av:main-audio` 内容）

## 已完善（2026-08-11 · A4 体验第一刀）

| 项 | 说明 |
|----|------|
| 胶片条 vs 代理 | 长片（≥12s）先等代理约 2.8s / 就绪后立刻采；短片不等；减少与代理转码抢同一文件 |
| 导入预览 | 不再起 ffmpeg 抽帧；优先复用 PreviewManager 首帧，否则文件名占位 |
| 时长探测 | ffprobe 已有可信时长则跳过再开 OpenCV |
| 点选片段 | `_refresh_preview_to_current_clip(jump_playhead=False)`，改属性不再拽播放头到片头 |
| 预览进度条 | 接线 `sliderMoved/Released`；0~1000 映射时间线总长；与时间码同步 |

涉及：`timeline_widget.py` · `editor_module.py` · `00-overview` 评分写回 **8.0**

## 已完善（2026-08-11 第五轮：Agent 子系统评价后的诚实性/健壮性修复批）

对 Agent 子系统（`agent_brain.py`/`capability_dispatcher.py`/`agent_pipeline_router.py`/`agent_pipeline_orchestrator.py`/`memory_store.py`/`llm_editor.py`/`agent_feedback_bridge.py`/`skill_engine.py`/`mcp_client.py`/`ai_video_generation_pipeline.py`/`editing_script_generator.py`）做了一次全面架构评价（为后续"升级为主控 Agent"打基础），结论：目前是**固定流水线 + 装饰性学习层**（`AgentBrain` 的联想/协同只用于聊天框展示一句话，明确不改变实际路由参数），不是自主规划的智能体；顺带发现并修复以下几处具体问题：

| 文件 | 问题 | 修复 |
|---|---|---|
| `core/llm_editor.py` | `_execute_one` 的 `add_keyframe`：`clip_index` 解析不到片段（`cid` 为空）时 `tm.add_keyframe` 被跳过，但 `return` 语句在 `if` 块外无条件 `success=True`，用户看到"关键帧已添加"但时间线毫无变化；`undo` 只是把最近一批指令从本地历史栈弹出，`TimelineManager` 并无任何真正的反向操作/快照回滚接口，之前的"已撤销"文案会让人误以为时间线已回退 | `add_keyframe` 在 `cid` 为空时改为 `success=False` 并给出"未找到第N个片段"提示；`undo` 消息改为"已从操作历史中移除最近一条记录（时间线上的实际改动未回滚，TimelineManager 暂不支持真正撤销）"。注：该 `execute()`/`_execute_one()` 路径经核实并不在当前对话式 Agent 的活路径上（活路径是 `ai_agent_panel.py` 的 `_apply_agent_command`，`add_keyframe`/`undo` 都不在其白名单 `_AGENT_ALLOWED_ACTIONS` 内，会被诚实拒绝），此处修复主要是消除潜在误用风险 |
| `modules/lego/skill_engine.py` | `SkillStep.timeout` 字段定义了但 `execute()` 从未读取，某一步 handler 卡死（网络请求/子进程 hang 住）会让整个 Skill 无限期挂起；`get_latest_skills()` 请求 `api.example.com`/`clawhud.example.com`（RFC 2606 保留的文档示例域名，必定连不通），把"必然失败的请求→回退本地列表"包装成正常流程，失败分支还塞了一个不存在的 `clawhud_link` | 新增 `_run_handler_with_timeout`：用后台线程 + `join(timeout)` 做软超时，超时后该步骤标记失败、流程继续（Python 无法强杀线程，未返回的线程会在后台自然结束，不会造成主线程假死）；`get_latest_skills()` 改为直接如实返回本地已注册 Skill，不再假装发起远程请求 |
| `core/agent_feedback_bridge.py` + `editor_module.py` | `AgentFeedbackBridge.get_pending_feedback()` 被 `editor_module.py` 读取用于拼进 Agent system prompt，但配套的 `mark_feedback_consumed()` 从未被任何调用方触发——同一条反馈会在之后每一次对话里被反复注入，且更新的反馈实际上永远排不到 `limit=3` 之外的旧反馈前面 | 在 `editor_module.py` 拼完 `[近期发布反馈]` 提示词后，调用 `agent_feedback_bridge.mark_feedback_consumed()` 把本次已展示的反馈标记为已消费 |
| `core/ai_video_generation_pipeline.py` | `GenerationInspector`（`_inspect`）在 LLM 不可用/调用异常/返回无法解析为 JSON 时"默认放行"（`passed=True`），这是为了不卡死流水线的合理设计，但下游 `GeneratedClip.inspection_passed=True` 和"真正跑过穿模/畸形检测并通过"完全混在一起，报告/UI 无法区分 | `_inspect` 新增返回值 `skipped`，`GeneratedClip`/`agent_pipeline_orchestrator._run_generation_line` 新增 `inspection_skipped` 字段透传，如实标注"未核验、直接放行"与"真正核验通过"的区别（供后续 UI 展示） |

**Agent 升级为「主控 Agent」的 5 大架构缺口**（评价结论，未在本轮修复，留作后续规划）：
1. 缺一个真正的 LLM 规划器（统一大脑）——现在是规则分流 + 固定 6 阶段，无目标分解/动态 DAG/重新规划
2. 缺可执行的纠错/重试策略层——`AgentPipelineOrchestrator` 全程线性无重试，反馈只进记忆/权重不触发重生成
3. 能力表面分裂成 4 套并行体系（`CapabilityDispatcher`/`SkillEngine`/`ExtensionsRegistry`/对话白名单），需收敛成一套 Tool Registry
4. 工具调用缺结构化约束——普遍是"返回 JSON"+ 正则提取，无 function calling / JSON Schema 校验
5. 感知/评估层大量启发式与占位（AI 生成无真实云端后端、初检可默认放行、五维打分基线估算），主控若据此决策，决策本身不可靠

验收：`python -m py_compile` 全部改动文件通过；`llm_editor`/`skill_engine`/`ai_video_generation_pipeline`/`agent_pipeline_orchestrator`/`agent_feedback_bridge` 直接 import 验证通过；`app.modules.lego.editor_module` 按生产环境实际懒加载路径单独 import 验证通过；`python scripts/frozen_zone_guard.py` 复查确认本轮未新增冻结符号 drift（仍报告的 5 处历史 drift 与本轮改动位置不重叠，同上一轮）。

涉及文件：`core/llm_editor.py` · `modules/lego/skill_engine.py` · `core/agent_feedback_bridge.py` · `modules/lego/editor_module.py` · `core/ai_video_generation_pipeline.py` · `core/agent_pipeline_orchestrator.py`

## 已完善（2026-08-11 · AI 画布镶嵌替换角色管理）

| 项 | 说明 |
|----|------|
| 模块 | `characters` 导航改为「AI 画布」，默认启用；主界面镶嵌 infinite-canvas |
| 运行时 | `app/core/canvas_runtime.py`：优先已有端口 → **`dist/` 静态秒开 :3001** → 否则 Vite :3000；进入模块自动预热 |
| 桥接 | `app/core/canvas_bridge.py` :18765 — `/ingest`、`/inject.js`、「发送到剪辑」、`/host/*` 模型同步、`/editor_outbox` 剪辑→画布 |
| Agent | `app/core/canvas_agent_runtime.py`：进入画布自动预热 + 注入；工具栏「连接 Agent」→ :17371 |
| 模型池 | `GET /host/ai-config-patch` → `shiguang-*`；专用 **`shiguang-aigc`**；**模型管理**广场卡片合并 AIGC 下拉 +「🎨 AIGC」目录页 |
| 双向 | 画布→剪辑：`MATERIAL_TO_TIMELINE`；剪辑→画布：AI 页「发送选中片段到画布」→ `TIMELINE_TO_CANVAS` / outbox |
| 慢启动 | 白屏「正在启动…」多为冷启动 Vite；跑 `scripts/setup_infinite_canvas.ps1`（含 `npm run build`）后应秒开 |
| 角色库 | `CharacterStore` 保留；侧栏编辑 + `generated_assets` 挂载；工具栏偏好同步到 bridge prefs |
| 入轨 | `MATERIAL_TO_TIMELINE`；静图经 ffmpeg 转 3s still.mp4 |
| 插帧 | 可选 `enable_interpolation` → `PreviewManager.set_interpolation_enabled`（线性补帧，非 RIFE） |
| 安装 | `scripts/setup_infinite_canvas.ps1`；WebEngine 需 `PyQt6-WebEngine==6.10.0`（对齐 PyQt6 6.10） |
| 端口 | 画布 `:3001`/`:3000` · 桥 `:18765` · Agent `:17371` |

涉及：`character_management_module.py` · `canvas_bridge.py` · `canvas_runtime.py` · `canvas_agent_runtime.py` · `module_registry.py` · `editor_module.py` · `editor_ai_panel.py`

## 已完善（2026-08-11 第四轮：AI 剪辑功能 + 剪辑体验专项）

针对「剪辑体验和 AI 剪辑功能」的专项审计（`ai_agent_panel.py`/`editor_ai_panel.py`/`llm_clipper.py`/`five_dimension_scorer.py`/`director_skill.py`/`deformity_repair_skill.py`/`capability_handlers.py`/`editor_module.py` 中 AI 相关方法），发现约 6 处高危（含 2 处点击必崩）+ 9 处中危，全部修复；另发现并修复一处上一轮遗留的**启动级回归**（见下）。

| 文件 | 问题 | 修复 |
|---|---|---|
| **`core/cache_system.py`（紧急回归）** | 上一轮改动让全局单例改成 `HybridCache(disk_max_mb=...)` 构造，但 `HybridCache.__new__` 把 `*args/**kwargs` 原样转发给 `object.__new__`，Python 不允许——直接 `TypeError` 崩溃在 `app/core/__init__.py` 的 import 阶段，相当于全应用无法启动 | `__new__` 改为只调用 `super().__new__(cls)`，不转发业务参数（`object.__new__` 本就不需要） |
| `ai_agent_panel.py` + `editor_module.py` | 两文件共 11 处调用 `show_clear_messagebox`（空时间线/文件不存在提示）但从未 import，点「LLM智能裁剪」「FunClip」「AutoClip」「Fusion」「LoRA」等按钮在素材为空时必 `NameError` 崩溃 | 补齐调用；因 `editor_module` 是被 `main_window` 懒加载**直接** `import .editor_module`（不经过 `modules.py`），若直接在模块顶层 `from .modules import show_clear_messagebox` 会与 `modules.py` 末尾 `from .editor_module import EditorModule` 形成循环导入——改为函数内局部 import（`editor_export_panel.py` 已有同款先例） |
| `capability_handlers.py` | `preview_validate`：`registered==0`（无片段登记）仍 `success=True`；`auto_preview_pass=True` 时对每个片段无条件 `mark_preview_passed`，完全没用上 `PreviewValidationLoop.ai_auto_inspect` 现成的路径/时长规则校验；`apply_filter`/`add_transition` 完全忽略 `agent_apply_filter`/`agent_apply_transition` 的返回值，底层异常也报 `True` | `registered==0` 改为 `success=False`；`auto_preview_pass` 改为真正调用 `ai_auto_inspect` 逐条跑规则校验，只有通过的才标记通过；`apply_filter`/`add_transition` 改为读取真实返回值的 `success` 字段 |
| `capability_handlers.py` + `editor_module.py` | `execute_editing` 精剪成功后返回 `output={"output_path": ...}`，但 UI 侧读的是 `final_video_path`——key 对不上，即使精剪真的成功也只显示"已执行精剪"这种不带路径的模糊文案 | handler 同时写入 `final_video_path`/`output_path` 两个 key |
| `deformity_repair_skill.py` | 骨骼关键点识别（`mock_17_points`/`confidence:0.85`）、插帧骨骼校验（恒 `True`）、分级修复（`status:"applied"`）均为占位/未执行，却和真实巡检结果混在一起产出"完成"报告 | 骨骼数据标注 `source:"placeholder"`；修复状态 `"applied"`→`"planned"` 并加 `note` 说明未真正执行；最终报告新增 `uses_placeholder_detection` 字段 + 摘要文案如实注明"骨架版，未接入真实视觉检测引擎" |
| `editor_module.py` | FunClip/AutoClip/Fusion/LoRA 四个 AI 处理按钮成片生成后只弹"完成"提示，从不加入时间线，用户要手动去输出目录找文件再导入——体验割裂；FunClip 输出因 `-an` 参数无音轨但提示语未说明；四处均裸调 `"ffmpeg"` 而非 `self._get_ffmpeg()`，系统未装 FFmpeg 时更容易失败 | 成功后统一调用 `_add_clip_to_timeline()` 直接上轨；FunClip 完成提示补充"⚠️ 该成片仅保留视频画面，不含原始音轨"；四处改用 `self._get_ffmpeg()`；新增 `_record_ai_tool_history()` 写入此前从未被填充过的"处理历史"列表 |
| `editor_ai_panel.py` | AI 工具按钮文案「LoRA / 创意编辑·风格迁移」「音频AI / 降噪增强·人声分离」，实际实现分别是 FFmpeg 调色滤镜组合、loudnorm+压缩，并未接入 LoRA 或声源分离模型 | 按钮文案改为「风格化 / 调色滤镜（非LoRA/AI迁移）」「音频增强 / 响度/压缩（非人声分离）」 |
| `director_skill.py` | 分镜表/剪辑指令生成时，LLM 有返回但解析失败（未抛异常）这条路径不会标记 `fallback`，只有异常分支才标记——实际上同样是模板占位却被当真实生成展示；最终报告完全不体现任何步骤是否用了占位；`edit_instructions` 只进报告文本，从不写入编辑器时间线，也没有任何提示告知用户 | 解析失败路径统一标记 `fallback=True` 并写入 `context` 变量；`_compose_final` 汇总 `script_is_template`/`storyboard_is_template`/`edit_instructions_is_template`，任一为真时摘要追加"⚠️ 以下内容为本地模板占位"；剪辑指令行追加"仅供参考，未自动应用到剪辑时间线，需手动剪辑" |
| `five_dimension_scorer.py` + `editor_module.py` | `extract_features_from_clip` 缺 `quality_scores` 时用固定 70 分基线填充每一维（设计上为了不误判 D 级），但 UI「五维打分结果」列表把基线分和真实分混在一起展示，用户无法区分 | `ClipFeatures`/`ScoreResult` 新增 `estimated_dims` 字段记录哪些维度是基线估值；UI 每条打分结果追加"（N/5维为估算基线）"标签 |
| `ai_agent_panel.py` | 对话指令 `add_track`：用 `hasattr(self,'_timeline_widget')` 判断，属性不存在时静默跳过真实调用，但仍无条件返回 `success=True`「已添加轨道」，时间线其实毫无变化 | 改为 `getattr` 判空 + 真正调用后检查返回值，时间线未就绪或添加失败都如实返回 `success=False` |
| `editor_ai_panel.py` | 读取 `active_provider.json` 状态时 `dirname` 多绕了一层，解析到仓库根 `data/`（不存在），真实文件在 `app/data/`（与 `copywriting_module.py`/`model_config.py` 里的算法本应一致）——AI引擎状态栏因此常年显示"未加载"，即使已激活 provider | 修正路径层级，与其余三处一致 |

验收：`python -m py_compile` 全部 9 个改动文件通过；`app.modules.lego.editor_module` / `ai_agent_panel` 等模块按生产环境实际懒加载路径（直接 `import .editor_module`，不经过 `modules.py`）单独 import 验证通过，排除循环导入回归；`python scripts/frozen_zone_guard.py` 复查确认本轮未新增冻结符号 drift（仍报告的 5 处 drift 是更早之前就存在的历史状态：`editor_module.py:_start_timeline_playback`/`eventFilter`、`preview_manager.py:get_frame_at`、`video_processor.py:bake_clip_transform`/`_build_transform_segments`，与本轮改动位置不重叠，尚待用户确认是否需要补跑 `--update` 重新收敛基线）。

涉及文件：`core/cache_system.py` · `ai_agent_panel.py` · `editor_module.py` · `core/capability_handlers.py` · `deformity_repair_skill.py` · `editor_ai_panel.py` · `director_skill.py` · `core/five_dimension_scorer.py`

## 已完善（2026-08-11 第三轮：账号运营/工作流/剪辑Skill 假成功修复批）

对此前两轮未覆盖的 13 个模块（copywriting/workflow_manager/viral_optimization_engine/data_analyzer/account_analyzer/account_skills/video_editing_skill/plugins_module/plugin_store/license_manager/theme_manager/model_card/agent_workflow）做的第三轮审计与修复，发现约 12 处高危（假成功/崩溃风险）+ 10 处中低危。除 license_manager 的授权/收款相关项按用户选择只做诚实标注（不重做鉴权架构）外，其余高中危项本轮全部真实修复。

| 文件 | 问题 | 修复 |
|---|---|---|
| `video_editing_skill.py` | `SmartClipSkill._clip_video`/`CoverGeneratorSkill._generate_cover` 只把输出路径塞进变量就 `success=True`，从未调用任何视频/图像处理，输出文件根本不存在；`_analyze_video` 写死 `duration=60.0`，`_identify_clips` 写死固定片段坐标，短视频会越界；`AutoSubtitleSkill` 在 whisper 不可用时伪造一条占位字幕仍 `success=True` | `_clip_video` 改为真正用 ffmpeg 逐段裁剪+concat；`_generate_cover` 改为真正用 ffmpeg 截取真实帧保存为 jpg；`_analyze_video`/`_extract_keyframes` 改用 ffprobe 读真实时长按比例选点；片段/内容分析仍是启发式占位选择，但完成文案如实注明"非真实AI识别"；whisper 不可用时改为如实 `success=False` 而不是伪造字幕文件 |
| `workflow_manager.py` | `WorkflowThread.run()` 四步跑完不管各步是否失败一律报"全流程完成"；`_try_ai_copywriting` 用 `from ..core.ai_engine import AIEngine`，相对导入层级错误，AI文案永远 `ImportError` 静默退化成模板；`_step_publish_prepare` 不检查 `publish_to_multiple_platforms` 的各平台真实结果就标 `success=True`；`_on_video_clipped` 对 `event.data` 非 dict 会崩 | `run()` 收集四步真实结果，按 `failed_steps` 给出诚实的完成/部分完成摘要；导入改为绝对路径 `from app.core.ai_engine import AIEngine`；发布步骤按每平台真实布尔结果统计成功/失败，全部失败才标 `success=False`；`event.data` 增加 `isinstance(dict)` 判断 |
| `account_skills.py` | `PublishContentSkill._do_publish`/`MatrixPublishSkill._batch_publish` 在无 `PlatformIntegrator` 时都直接标记 `success=True`/`status="exported"`，但没有做任何真实转码/导出/发布；`_load_matrix` 未提供配置时静默套用 3 个虚构账号（`acc_001` 等）；`_summarize_results` 统计 `status=="submitted"` 但实际状态从未写过这个值，成功数恒为 0 | 无 Integrator 时如实标记未发布/未导出（`success=False`/`status="skipped"`）；`_load_matrix` 无真实账号配置时改为报错而非套用虚构账号；汇总统计改为读取实际状态值 `published`/`failed`/`error`/`skipped` |
| `plugin_store.py` | `install_item()` 在商品没有 `download_url` 时，只建空目录+写一个 `metadata.json` 占位文件就标记 `is_installed=True`、返回"安装成功"，目录里没有任何真实插件代码 | 无下载链接时如实返回安装失败（官方内置商品走 `init_official_items` 直接解析真实路径，不受影响） |
| `data_analyzer.py` | `_on_workflow_completed`/`_on_publish_result` 对 `event.data` 非 dict 会 `AttributeError` 崩溃；`_get_recent_records` 对时间戳做无条件 `[:-1]` 切片，空字符串直接让 `datetime.fromisoformat` 抛 `ValueError` | 两处事件回调增加 `isinstance(dict)` 判断；时间戳解析改为逐条 try/except 隔离失败记录，不整体崩溃 |
| `plugins_module.py` | 自动安装两条路径都失败后，仍用 `QMessageBox.information` + "正在安装..."的措辞，像是还在进行中；插件引擎未就绪时提示"文件路径已记录"，但代码从未做任何持久化 | 改为 `QMessageBox.warning` + 如实说明"未能自动安装/无法导入，请手动操作" |
| `copywriting_module.py` + `main_window.py` | 「推送到剪辑模块」只要 `emit()` 不抛异常就无条件弹"推送成功"；真实根因定位在 `main_window._on_module_activated`：编辑器模块懒加载走 `QTimer.singleShot(50,...)` 异步创建，若编辑器此前未打开过，`COPY_GENERATED` 事件在监听器注册前就已发出，payload 直接丢失且无任何提示 | 根因修复：`_on_module_activated` 不再立即 emit，改为把 payload 存入 `_pending_module_actions[target]["data"]`，由 `_flush_pending_module_action`（保证在目标模块真正加载完成、监听器已注册后才被调用）统一交付，两条路径（已加载/懒加载）都不再丢数据 |
| `agent_workflow.py` | `ReviewAgent.review()` 喂给预测引擎的 7 个特征里有 5 个（对话密度/情绪方差/冲突强度/高潮位置/画质/音质/字幕质量）是写死常量，却和真实数据混在一起产出一个"评分"当作内容分析结果展示；迭代精修产出新版本后，未重新调用 `review()` 打分，却直接宣称"评分从 X 提升" | `ReviewResult` 新增 `uses_placeholder_features` 字段，审核完成提示追加"部分特征为占位估值，仅供参考"；精修完成文案改为如实说明"未重新评分，效果建议人工复核"，不再编造提升结论 |
| `viral_optimization_engine.py` / `editor_module.py` | `VIRAL_GENES_LIBRARY` 里的 `success_rate` 是行业经验估值，UI 上以"成功率: X%"展示，容易被当成真实播放数据统计 | 库定义处加注释说明来源；`_predict_viral` 弹窗结果追加"以上预测和成功率均为启发式估算，非真实平台数据统计"提示 |
| `license_manager.py` | 激活码校验只查格式（`PER｜PRO｜ENT` 前缀 + 本机硬件ID前4位），没有任何服务器端验证，理论上凑对格式即可激活任意权限；购买链接是 Stripe `test_` 测试环境链接，点击无法完成真实付款 | 按用户选择：不重做鉴权/收款架构（需要真实后端），仅在 UI 上加诚实标注——激活成功提示、授权信息展示均标注"本地试用模式，未接入服务器验证"；购买页加"当前为测试环境购买链接，暂不支持真实付款"提示 |

验收：`python -m py_compile` 全部 12 个改动文件通过；`python scripts/frozen_zone_guard.py` 复查确认本轮未触碰任何冻结符号（仍报告的 5 处 drift 是更早之前就存在的历史状态，与本轮无关）。

涉及文件：`video_editing_skill.py` · `workflow_manager.py` · `account_skills.py` · `plugin_store.py` · `data_analyzer.py` · `plugins_module.py` · `copywriting_module.py` · `main_window.py` · `core.py` · `agent_workflow.py` · `viral_optimization_engine.py` · `editor_module.py` · `license_manager.py`

## 已完善（2026-08-11 全模块审计：中低危收尾批）

上一轮「崩溃优先修复批」文末列出的 5 项中低危遗留项，本轮全部处理完毕。

| 项 | 说明 | 修复 |
|---|---|---|
| 设置页多个开关不 save/load | `_create_general_tab` 建了「开机自动启动」「记住窗口大小和位置」「缓存大小」三个控件，`_save_settings`/`_load_settings` 从未涉及；另外 `auto_login`/`auto_save`/`auto_save_interval`/`max_threads`/`gpu_accel` 虽然会保存，但 `_load_settings` 从未把它们读回 UI，每次重启设置页都显示写死的默认值 | `_load_settings` 补齐全部 8 个控件的读取；`_save_settings` 补齐三项新增的持久化；「记住窗口大小和位置」新增真实效果：`main_window.py` 增加 `_restore_window_geometry`/`_save_window_geometry`，通过 `QApplication.aboutToQuit` 信号钩子保存（未碰 `closeEvent`，见下方冻结区说明）；「缓存大小」新增真实效果：`cache_system.py` 构造全局 `hybrid_cache` 单例前读取该配置作为 `disk_max_mb`；「开机自动启动」新增真实效果：`settings_module._set_windows_autostart()` 写入/删除 Windows 注册表 `HKCU\...\Run` 键 |
| 帮助模块视频教程列表内容偏夸张/虚构 | `help_module._video_tutorials()` 列出一批带具体时长（"5分钟""8分钟"...）的教程条目，暗示是官方已发布的分镜头视频，实际点击只会跳到 B站/YouTube 主页而非对应视频；`_beginner()`/`_openclaw_guide()` 里也有个别搜索结果链接被贴上虚构的具体时长 | 重写 `_video_tutorials()` 为「建议学习路径 + 关键词搜索链接」的诚实模式（和 `_beginner()` 一致的做法），明确标注"本软件没有官方视频教程，以下为第三方内容搜索入口"；顺手清理另外两处贴在搜索链接上的虚构时长标签 |
| 拓展中心占位 Skill 会尝试执行导致失败提示 | `_refresh_skill_list()` 在 `skill_registry` 未注册任何真实技能时会展示 5 条硬编码占位技能，展示文本和真实技能完全一样（`⚡ 名称`），用户选中、点「运行技能」才会弹"是占位项，暂未实现"——体验上是"点了才发现是假的" | 占位项文本改为 `⚡ 名称（占位，未接入）`，详情区提前说明"暂未接入真实技能引擎"，让用户点击前就能分辨 |
| 账号运营发布时长下拉写了但读取时机不明确 | `_create_publish_card()` 里的 `dur`（30秒/60秒/90秒/3分钟）下拉框创建后从未被任何调用方读取——`_quick_publish` 的 lambda 根本没有传入这个控件，选什么都不生效 | `_quick_publish`/`_execute_publish` 新增 `duration_label` 参数，真正读取 `dur.currentText()` 并写入发布回执（`_append_publish_log`），仅作为标签记录、不改变实际导出时长，避免过度承诺 |
| `plugin_loader.py::discover_plugins()` 不登记 `_plugin_infos` | `discover_plugins()` 把扫描结果放进局部变量 `discovered` 直接返回，从不写回 `self._plugin_infos`；只有走 `PluginHotReloader` 才会手动回填。若调用方单独调 `discover_plugins()` 后裸调 `load_plugin(plugin_id)`，`load_plugin` 在 427 行 `self._plugin_infos.get(plugin_id)` 必得 `None`，抛 `PluginLoadError` | `discover_plugins()` 扫描完成后同步把结果写入 `self._plugin_infos`，使其可以独立配合 `load_plugin()` 使用，不再依赖热加载器路径 |

**冻结区说明**：`main_window.py:closeEvent` 属于 `exit-media` 冻结区（[`docs/knowledge/frozen_zones.json`](frozen_zones.json)），未获解冻不能改。窗口几何保存本可以直接加一行在 `closeEvent` 里，但这里刻意改用 `QApplication.aboutToQuit` 信号在 `MainWindow.__init__` 里连接，效果等价（真正退出前触发一次）但完全不触碰冻结符号。中途一度误加进 `closeEvent` 又立即撤回，最终方案已通过 `frozen_zone_guard.py` 复查确认无新增 drift。

验收：`python -m py_compile` 全部 7 个改动文件通过；`python scripts/frozen_zone_guard.py` 复查确认本轮未触碰任何冻结符号（仍报告的 5 处 drift 是更早之前就存在的历史状态，与本轮无关）。

涉及文件：`settings_module.py` · `main_window.py` · `core/cache_system.py` · `help_module.py` · `extensions_module.py` · `account_ops_module.py` · `core/plugin_loader.py`

## 已完善（2026-08-10 全模块审计：崩溃优先修复批）

对 5 个并行子代理审计出的 13 个模块问题（首页/设置/帮助/多任务/素材库/模型管理/角色管理/性能监控/账号运营/拓展中心/AI剪辑流水线/插件系统/AI特效插件）做的第一轮修复，按用户要求「先只修高危：崩溃优先，其次假成功」，未处理的中低危项见文末列表。

### 崩溃类（点击必炸）

| 文件 | 问题 | 修复 |
|---|---|---|
| `settings_module.py` | `_test_smtp_connection` 用 `self._smtp_test_btn`，但按钮从未赋值给该属性，点「测试连接」必 `AttributeError` | 补 `self._smtp_test_btn = test_btn` |
| `help_module.py` | 多处 `webbrowser.open(url)`，文件顶部没有 `import webbrowser`，点外链按钮必 `NameError` | 补 import |
| `ai_effects_plugin/effects/beauty_filter.py` | `load_model()` 用 `os.path.exists`，模块顶层没 `import os` | 补 import |
| `ai_effects_plugin/ui/ai_effects_widget.py` | `_apply_beauty_preset` 用 `from .effects.beauty_filter import ...`，本文件在 `ui/` 子包下会解析成不存在的 `ui.effects`，点美颜预设必 `ImportError` | 改为 `from ..effects.beauty_filter import ...`；顺带把此前创建了控件但从未 `.connect()` 的「应用预设」按钮接上（非美颜标签页时如实提示"暂无预设"而非假装生效） |
| `ai_clip_flow.py` | `_step_funclip/_step_videofusion/_step_lora_edit` 内用了 `output_base`，但方法签名根本没接这个参数（只在外层 `_run_pipeline` 是局部变量），必 `NameError`；`_finalize_clip_flow` 同理用了未传入的 `base_name`；且 4 个 `_step_*` 均无 `return current_output`，导致 `current_output = self._step_xxx(...)` 每次都拿到 `None`，后续步骤全部操作不存在的文件——上述 `NameError` 又被外层 `except Exception` 吞掉，UI 只显示"⚠️ 部分完成"掩盖了真实的连环崩溃 | 统一给 4 个 `_step_*` 补 `output_base` 形参、调用处补传参，方法末尾补 `return current_output`；`_finalize_clip_flow` 补 `base_name` 形参 |
| `extensions_module.py` | `_on_skill_selected` 对真实 `Skill` 实例调用 `.get('name')`，`Skill` 是普通类没有 `.get()`，选中真实技能必 `AttributeError`（`_run_selected_skill` 此前已修过同类问题，`_on_skill_selected` 漏改） | 和 `_run_selected_skill` 一样区分 `Skill` 实例 / 占位 `dict` |

### 假成功 / 误导性文案类

| 文件 | 问题 | 修复 |
|---|---|---|
| `ai_clip_flow.py` | AutoClip 只做分析和高光识别，从不真正剪切原片；旁白/音效/版权检测/BGM替换/肤色矫正等勾选项只写入 settings、从未被任何处理器消费，但完成摘要仍显示"是/否"暗示已生效 | 高光步骤摘要新增如实说明"仅供参考，不会自动剪切"；未实现的勾选项统一改橙色高亮 + tooltip 标注"暂未实现"，完成摘要不再假装生效 |
| `plugin_manager.py` | `install_plugin()` 注释写"暂时返回成功"，无任何安装逻辑恒 `return True`，`plugins_module` 回退路径会弹"安装成功"但插件根本没装 | 如实 `return False`，让调用方走既有的"请手动放入 plugins/ 目录"提示 |
| `ai_effects_plugin/effects/super_resolution.py` | `load_model()` 只存占位字符串就打印"SR模型就绪（演示模式）"，实际放大用的是 OpenCV 经典插值（bicubic/lanczos），不是神经网络超分 | 消息改为如实标注"未接入神经网络模型，使用 OpenCV 经典插值" |
| `ai_effects_plugin/main.py` + `ui/ai_effects_widget.py` | `apply_effect()` 失败时吞异常、原样返回输入帧，`EffectProcessorThread` 拿到"结果"就走完成路径弹"✅ 特效应用完成"，用户不知道其实什么都没处理 | `main.py` 记录 `_last_error`；UI 线程消费后按此判断，若有错误则走 `error_occurred` 而非假成功 |
| `modules/plugins/plugin_system.py` | `plugin_video_clip`/`plugin_video_merge` 的 `subprocess.run` 不检查 `returncode`，ffmpeg 报错也 `return True` | 补 `returncode`/输出文件存在性检查，失败时打印 stderr 尾部 |
| `tasks_module.py` | `_new_from_template` 直接 append 一条没有 `queue_id`/`batch_task_id` 的记录，不进真实队列，永远停在"等待中"；`batch_task_manager._execute_task` 只要 processor 不抛异常就标 `COMPLETED`，但剪辑/AI生成/导出/转码等处理器在缺视频时会如实返回 `{"status":"pending"/"error",...}` 而不抛异常，导致这类"未处理"任务也显示"已完成 100%" | `_new_from_template` 复用 `_add_task_to_queue` 走真实入队路径；`_execute_task` 识别 `status in ("pending","error")` 的返回值，转为失败而非成功 |
| 首页 `modules.py` | 编辑器实际保存工程后缀是 `.timeline`（`editor_module._save_project`），首页统计/最近项目却扫 `.json`/`.proj`，项目数恒 0；"生成文案"读的是 `from core.batch_task_manager import batch_task_manager`——路径和全局单例都不存在，必 `ImportError` 被吞掉；"最近项目"双击只 emit 了 `MODULE_ACTIVATED` 切页签，`project` 字段从未被消费，工程从未真正打开 | 扫描后缀加入 `.timeline`；"生成文案"如实标"—"（未接入，不再用文不对题的任务队列数冒充）；新增 `action="open_project"` 事件路径，`main_window._flush_pending_module_action` 据此调用 `EditorModule.import_project()` 真正加载；`_save_project`/`_open_project` 默认目录改为 `data/projects/`，让今后的保存能被首页统计到 |
| `model_management.py` | `_run_speed_test` 调用 `ai_engine.chat(...)`（返回生成器）后直接测耗时、不迭代生成器——真实网络请求根本没发出，`elapsed` 测的是"创建生成器"的耗时（≈0），`resp` 也不是文本而是生成器对象 | 用 `"".join(chunks)` 真正消费生成器，按 `"错误: "` 前缀识别失败 |
| `character_management_module.py` | `CharacterStore.add()` 保存失败时虽正确回滚内存，但仍 `return new_id`（真值），`_on_save` 只判断 `if new_id:` 就弹"保存成功"，磁盘写入失败也不会被发现；搜索框是局部变量，`_refresh_list` 靠遍历 `self.layout()`（根布局）找 `QLineEdit`，但输入框实际嵌套在四层布局之下，`itemAt(i).widget()` 对 `addLayout` 的项恒返回 `None`，搜索永远不生效 | 保存失败时 `add()` 改为 `return ""`；搜索框存为 `self._search_edit` 属性直接读取 |
| `performance_module.py` + `modules.py` + `tasks_module.py` | `BatchTaskManager` 没有跨模块单例，`performance_module.py` 却调用 `BatchTaskManager.get_instance()`（此前不存在该方法），`hasattr` 检查恒 False，任务队列卡片永远显示"就绪" | 给 `BatchTaskManager` 加真正的 `get_instance()` 单例；`tasks_module.py` 改用该单例创建 `_batch_mgr`，三处模块从此读同一份真实数据 |
| `account_ops_module.py` | "导出报表"按钮创建后从未 `.connect()`，点击无响应；"全平台数据采集"实际只是把本地 `publish_log.json` 条数汇总进 `analytics.json`，不联网拉取任何平台数据，却弹"全平台数据采集完成！"；首次启动时抖音/快手/视频号被预置了虚构的"@主账号 12.5万粉"等账号，让人误以为已绑定真实账号 | 接线「导出报表」→ 真实导出账号+统计数据为 JSON；采集按钮改名"汇总本地发布日志"+完成文案标注"不联网拉取"；默认账号改为空列表 |
| `materials_module.py` | 标签筛选按钮只切到外层"📁 本地素材"大标签页（本来就常驻显示），从不切换内层按类型分的子标签页，点"音频""图片"等任何标签界面都无变化；`import_asset()` 失败返回 `None`（不抛异常），文件夹批量导入/多选导入此前不检查返回值，全部计入"导入成功" | 存下内层 `QTabWidget` 引用+类型到索引的映射，标签按钮真正切换子页；两处导入统一检查 `import_asset()` 返回值，失败单独计数并提示 |
| `settings_module.py`（SMTP） | "测试连接"只做 TCP socket 连通性检查就弹"测试成功"，用户名密码错误、SSL/TLS 配置错误等真正会导致发信失败的场景测不出来 | 改为真正走 `smtplib` 登录握手（不发送邮件），按 `SMTPAuthenticationError`/`SMTPException` 细分报错 |

### 未处理（中低危，本轮不动，供下一轮参考）

- 设置页多个开关（自动启动/记住窗口位置/缓存大小等）不 save/load
- 帮助模块视频教程列表内容偏夸张/虚构，未标注来源
- 拓展中心占位 Skill 会尝试执行导致失败提示（非崩溃，已有提示兜底）
- 账号运营发布时长下拉写了但读取时机不明确
- `ai_clip_flow.py` 明星脸替换/BGM 版权替换等特效仍是未来功能占位（本轮已在这几项上补了"暂未实现"标注，未新增真实处理逻辑）
- `plugin_loader.py::discover_plugins()` 不登记 `_plugin_infos`，裸用 `PluginLoader.load_plugin(id)` 会失败（热加载器路径不受影响）

涉及文件：`ai_clip_flow.py` · `extensions_module.py` · `settings_module.py` · `help_module.py` · `ai_effects_plugin/{effects/beauty_filter.py,effects/super_resolution.py,main.py,ui/ai_effects_widget.py}` · `core/plugin_manager.py` · `modules/plugins/plugin_system.py` · `tasks_module.py` · `batch_task_manager.py` · `modules.py` · `main_window.py` · `editor_module.py`（`_save_project`/`_open_project` 默认目录） · `model_management.py` · `character_management_module.py` · `performance_module.py` · `account_ops_module.py` · `materials_module.py`

验收：`python -m py_compile` 全部 20 个改动文件通过；`python scripts/frozen_zone_guard.py` 复查确认本轮未触碰任何冻结符号（仍报告的 5 处 drift 是本轮之前就存在的历史状态，见下一节末尾记录）。

## 已完善（2026-08-10 Agent 左右脑：修真突触持久化 / 激活死代码）

| 项 | 说明 |
|----|------|
| 突触持久化从未生效（真 bug，非小事） | `AgentBrain._persist_synapses()` 调用 `memory_store.record(..., metadata={...})`，但 `MemoryStore.record()` 签名根本没有 `metadata` 形参——每次调用必抛 `TypeError`，被外层 `except Exception: logger.debug(...)` 静默吞掉。等于"学习"从第一天起就没有真正写盘过 |
| 读取端类型也对不上 | `content=f"{pre}->{post}"` 存字符串，但 `MemoryEntry.content` 是 `Dict[str,Any]`；`load_synapses()` 用 `getattr(e,"metadata",{})` 取权重，而 `MemoryEntry` 根本没有 `metadata` 属性，永远拿到 `{}` |
| 无人调用 `load_synapses()` | 即使持久化修好，没有任何调用点在启动时执行它，重启后突触权重照样清零，"长期记忆"名不副实 |
| `activate()` 从无调用方 | 定义了扩散激活但没人触发，`get_brain_status()['active_neurons']` 永远空列表，UI「⚡ 激活」永远显示 0 |
| `correlate()` / 左右脑协同思考完全是死代码 | 定义了但没有任何业务路径调用，不影响任何实际决策，纯装饰 |
| 修复 | ① `_persist_synapses`/`load_synapses` 改为把 weight/fire_count/last_reinforced 放进 `content` 字典（不再用不存在的 `metadata` 形参）；② `AgentBrain.__init__` 末尾调 `self.load_synapses()`；③ `CapabilityDispatcher.invoke()` 每次调用后 `agent_brain.activate(capability_id, ...)`；④ Agent 面板启动全链路前，非空创意简报会跑一次 `agent_brain.correlate(brief)` 并在聊天区展示联想到的左右脑能力，让「左右脑协同」真正可观测 |
| 验收 | 独立进程二次验证：`reinforce_path` 写盘 → 新进程 `load_synapses()` 能读回同一条突触；`app/tests/test_agent_brain_learn.py`（25）+ `test_editor_ripple_capability.py`（5）全绿 |

涉及：`app/core/agent_brain.py` · `app/core/capability_dispatcher.py` · `app/modules/lego/editor_module.py`（`_on_run_full_pipeline`）
未改：`agent_pipeline_orchestrator.py` / `capability_handlers.py` / `agent_feedback_bridge.py`（已有的 `reinforce_path`/`learn_from_feedback`/`sync_from_dispatcher` 调用点保留不动）

**顺带发现（未处理，仅记录）**：`python scripts/frozen_zone_guard.py` 报告 `editor_module.py:_start_timeline_playback/eventFilter`、`preview_manager.py:get_frame_at`、`video_processor.py:bake_clip_transform/_build_transform_segments` 已偏离基线哈希——经核对是本轮改动之前就已存在的未重锁状态（这些符号本轮完全未触碰），建议确认是否为此前已授权的解冻改动，若是则 `--update` 重新上锁。

## 已完善（2026-08-10 剪辑模块性能一轮）

| 项 | 说明 |
|----|------|
| 预览同档不清缓存 | `set_preview_quality` 同档 early-return，减少 scrub 空刷 |
| 胶片条走代理 | `ClipWidget._resolve_clip_media_path` 优先 `proxy_path`；代理就绪后重采 |
| 胶片条缩放缓存 | paint 缓存 scaled 格子；拖动用 FastTransformation |
| Worker 生命周期 | 删片先 `sleep_media_workers`；`destroyed` 清理；interrupt+wait |
| 拖完唤醒 | `set_clip_interaction_active(False)` → `_wake_visible_clip_media` |
| Scrub 路径 | 比对/GL 缓存键用代理解析路径，少误开源 |
| 导出防代理 | `editor_export` 跳过/回退疑似 proxies 路径 |
| Worker 全局并发上限 | `_MediaWorkerGate`（默认 3 并发）挡 Filmstrip/Waveform 线程风暴；片段休眠/删除撤销排队项 |
| 标尺网格按脏区绘制 | `TrackViewport._paint_grid_background` 用 `event.rect()` 裁剪循环范围，不再从 0 循环到 `_total_duration`；长时间线/高缩放下滚动、框选更跟手 |
| 播放中误触发墙钟 rebase | `_on_timeline_playhead_moved` 原先无条件先调 `_rebasing_playback_clock` 再判断 `_timeline_playing`；播放中每约 100ms UI 回抛 playhead 都会重置墙钟锚点，造成微抖。改为播放中直接 return，不再 rebase（未改冻结的 `_rebasing_playback_clock` 本体） |
| Agent 提示词/白名单不一致 | 系统提示词曾宣传 `add_clip`/`move_clip`，但 `_AGENT_ALLOWED_ACTIONS` 白名单和 `_apply_agent_command` 都未实现这两个 action，模型一提就被拒。已从提示词删掉这两个，并把已支持但漏提的 `apply_filter`/`suggest_cleanup` 补进提示词，和白名单对齐 |
| Agent 面板标签指错 | `_agent_tab_index` 原来在加完「导出」标签之后才用 `tabs.count()-1` 赋值，实际指向导出页而非 Agent 页；改为加 Agent 标签当下就记索引 |

涉及：`app/modules/lego/editor_module.py`（`_build_edit_agent_messages` 提示词、`_agent_tab_index`）  
验收补充：`_verify/test_editor_perf_opts.py::TestAgentPromptWhitelistAligned`、`TestPlayheadMovedNoRebaseDuringPlayback`

涉及：`preview_manager.py` · `timeline_widget.py` · `editor_module.py` · `editor_export.py`  
验收：`_verify/test_editor_perf_opts.py`（8 项）  
未改冻结 `get_frame_at`（完整 quality 分桶需解冻 `playback-av`）。

## 已完善（2026-08-08 P1b 误触 / 视口懒加载 / 负载标尺）

| 项 | 说明 |
|----|------|
| 误触保护 | 拖片/片缘位移不足 5px 视为点击，不挪片、不 trim |
| 视口懒加载 | 视口外不采胶片条/波形；滚动 120ms 后唤醒可见片 |
| 负载红线 | 标尺底边红线标特效/转场/LUT/KF/变速区（轻量提示，非达芬奇缓存） |
| I/O 高亮 | 序列入出点在标尺区间半透明 + 竖线（接已有 I/O 快捷键） |

涉及：`timeline_widget.py` · `editor_timeline_tools.py` · `editor_module.py`  
验收：`_verify/test_timeline_lod_threshold.py`

## 已完善（2026-08-08 P1 Esc / 防抖保存 / 波纹开关）

| 项 | 说明 |
|----|------|
| Esc 取消拖拽 | 拖片/trim 中 Esc 还原按下时 start/in/out/轨；批量拖整组还原 |
| autosave 防抖 | `_touch_project_dirty` → 停手 3s 写盘；120s 定时仅 dirty 时写 |
| 波纹删开关 | 时间线「🌊 波纹删」；关=普通删除留白；Delete 跟开关 |

涉及：`timeline_widget.py` · `editor_module.py` · `editor_ux_commands.py`  
验收：`_verify/test_p1_esc_autosave_ripple.py`

## 已完善（2026-08-08 P0 预览/代理/工具栏手感）

| 项 | 说明 |
|----|------|
| 分级预览 UI | 预览窗 1/4·1/2·100%；默认 1/2；拖 scrub/播放强制 1/4，静止回用户档；Ctrl+1/2/3 |
| 代理媒体接线 | 导入后后台生成 H.264 代理（长边≤960，保持比例）；预览走 `proxy_path`，导出仍用 `path`；按钮开关 |
| 缓存盘 | `config.json` → `editor.proxy_cache_dir` 或环境变量 `SHIGUANG_PROXY_CACHE`；设置清理含 `cache/proxies`；闲置 14 天清理 |
| 统一指令 | `editor_ux_commands.dispatch`：工具栏与快捷键共用 cut/delete/play/收拢等 |
| 折叠轨休眠 | 折叠停缩略图/波形 worker；展开再懒加载 |
| 拖片降载 | `_clip_interaction_active` 期间不调度波形/胶片条 |

涉及：`editor_preview_ux.py` · `editor_ux_commands.py` · `proxy_media.py` · `editor_module.py` · `timeline_widget.py`  
验收：`_verify/test_editor_preview_ux.py`

限制：未做达芬奇式预渲染红蓝线 / DAG 时间轴；代理非 ProRes。

## 已完善（2026-08-08 多选 / 吸附红线）

| 项 | 说明 |
|----|------|
| 吸附视觉红线 | 拖移/trim 命中吸附时全轨竖直线（青）；松手约 180ms 淡出 |
| 多选 | Ctrl 点选切换；Shift 同轨范围选；主选仍走 `clip_selected` |
| 框选 | 轨空白处拖橡胶筋；Shift/Ctrl 追加 |
| 批量移动 | 拖选区中任一成员则整组同步 Δstart；一条 compound undo |
| 批量删除 | Delete 删全部选中（ripple + 联动音频）；多选一条 `batch_delete` |

涉及：`timeline_widget.py` · `editor_timeline_tools.py` · `editor_module.py`

**热修（审查 P0）**：清选/空选 `emit(None)` 同步 Editor，Delete 不回退陈旧 `_current_clip`；批量/单片移动 undo 含联动音画；吸附线 X 跟 `clip_container`；框选 `grabMouse`；Ctrl 取消后不拖走；右键删除走多选路径。

## 已完善（2026-08-08 多选 / 吸附手感加固）

| 项 | 说明 |
|----|------|
| Shift 范围选 | 同轨按锚点↔目标时间外包络，选中**重叠或夹在其间**的片（不再仅 `start_time` 闭区间） |
| 跨轨落点 | 仍仅同类型可落；指针下轨青绿/不兼容淡红反馈；单片拖也强制同类型 |
| 吸附参照 | 批量跨轨时按指针下**兼容轨**片缘吸附；红线画在实际合缝边（片头贴合或片尾贴合） |
| 框选预览 | 橡胶筋拖动中即时高亮将命中片；取消/刀片切换还原真实选区 |

涉及：`timeline_widget.py` · `editor_timeline_tools.py`  
验收：`_verify/test_timeline_select_snap.py`

已知限制：跨轨仍禁止异类型（视频↔音频）；混合多选拖到一轨时仅同类型成员落轨，时间仍整组平移。

## 已完善（2026-08-08 时间线精细编辑）

| 项 | 说明 |
|----|------|
| 缩放上限 | 500% → **3000%**（约 20px/帧@30fps）；Ctrl+滚轮 / Ctrl± |
| 吸附 | 固定 0.25s → **按 8px 换算秒**（放大更细）；**Alt 临时关闭** |
| 最短片宽 | 40px（默认缩放下≈2s）→ **6px**，可 trim 短片 |
| 标尺 | 拖 scrub；放大后出现帧/ms 刻度 |
| 快捷键 | ←/→ 播放头逐帧；Shift+←/→ 选中片平移一帧 |

涉及：`timeline_widget.py` · `editor_module.py`

## 已完善（2026-08-08 剪辑手感二轮）

| 项 | 说明 |
|----|------|
| 播放头对齐 | 用 `px_per_sec()`，缩放后不再错位 |
| Trim 跟手 | 全局坐标基准，修局部 delta 漂移 |
| 实时吸附 | 拖移/拉片缘过程中吸附，松手再帧量化 |
| 锚点缩放 | Ctrl+滚轮以指针下时间为锚，画面不跳飞 |
| 跟镜 | scrub 时播放头靠近边缘自动横滚 |
| 音画锁 | trim/移动后联动音视频 timing 同步 |

涉及：`timeline_widget.py` · `editor_module.py`

## 已修复（2026-07-25 AI 加载/提示）

| 项 | 说明 |
|----|------|
| AI 特效插件加载 | `PluginManager` 兼容 `plugin_info`；记录 `_load_errors`；特效子模块懒加载；插件中心状态条 +「打开面板」失败明文 |
| LLMClipper | `last_error`；空字幕/空 JSON/无模型不再静默切前 15 秒；编辑器 AI 页提示词 + LLM 按钮 + 主线程弹窗 |
| Ollama 诊断 | `format_diagnose_report` / `diagnose_user_message`；模型卡状态带 error；编辑器 AI 页「重新诊断/详情」 |

## 已修复（2026-07-25 AI 诚实降预期）

| 项 | 说明 |
|----|------|
| 文案静默模板 | 选云端模型失败时弹窗确认，不再假装 AI 成功；「本地模板（非 AI）」 |
| TTS 适配器 | `VoiceGenerator` 别名 + `generate_audio` |
| 插帧命名 | UI/日志改为「线性补帧」 |
| Whisper 提示 | `unavailable_reason()` + setup_deps 路径 |
| 模块说明 | copywriting / ai_clip_flow / models 描述标明依赖与半通 |

## 已修复（2026-07-25 续）

### 预览比例被拉成 16:9

| 根因 | 修复 |
|------|------|
| `preview_quality=medium/low` 硬编码目标 960×540 / 640×360 | `_get_target_size()` 按长边降采样，保持片源宽高比 |
| 空隙黑场写死 `QImage(1280,720)` | 改用当前片源宽高 |
| QLabel 可能拉伸 | `setScaledContents(False)` |

涉及：`preview_manager.py` · `editor_module.py`  
验收：`test_preview_aspect.py`

### 恢复工程后音频轨无波形

| 根因 | 修复 |
|------|------|
| 旧 `autosave/latest.timeline` 只存视频片、无联动音频 | `import_project` → `_ensure_linked_audio_clips()` 自动补 audio 轨 |
| 相对路径导致 `exists` 失败 | ClipWidget `_resolve_clip_media_path()` |

涉及：`editor_module.py` · `timeline_widget.py`  
验收：`test_linked_audio_restore.py`

## 已修复（2026-07-25）

### 音频轨无波形

| 根因 | 修复 |
|------|------|
| 绘制写死 `track==1` | `_is_audio_clip()` 按轨 type / type / 扩展名 |
| 生成失败 → 全 0 peaks ≈ 看不见 | `WaveformGenerator` 失败返回 `None`；UI 虚线中线 |
| BGM `_add_to_clips` 未上时间线 | 真正 `add_clip` 到 audio 轨 |
| paintEvent 反复起线程 + 随机假波形 | 防重入；去掉随机占位 |

涉及：`timeline_widget.py` · `waveform_generator.py` · `editor_module.py`  
验收脚本：`test_waveform_fix.py`

### 播放卡顿 / 音画不同步

| 根因 | 修复 |
|------|------|
| playhead `+=0.033` 软件时钟 | `QElapsedTimer` 墙钟 + 忙则丢帧 |
| 每帧 `CAP_PROP_POS_FRAMES` seek | 顺序 grab/read，落后≤24 帧 grab 追赶 |
| 音画双时钟，350ms 才纠偏 | 阈值 80ms；跳过联动音频双开 |
| Smooth 缩放 + 高分辨率预览 | 播放中 medium + FastTransformation |

涉及：`editor_module.py` · `preview_manager.py`

## 已完善（2026-08-08 导入后播放卡顿）

| 根因 | 修复 |
|------|------|
| 导入路径多次 `open_video`（校验帧数/关开 capture） | `_ensure_preview_source_open` 同文件复用；`_load_video` 先加片再完整 open 一次；时长探测不再为取时长额外 open |
| 首帧 `_on_preview_frame` + `_render_timeline_frame` 双刷 | `_force_show_first_video_frame` 只刷一次 |
| 播放每帧二次 letterbox | sequence 画幅帧标 `_preview_frame_preletterboxed`，播放中跳过二次 fit |
| 播放中切源仍跑帧数探针 | `_render_timeline_frame` / 转场取帧 `for_scrub=True` |
| 每次 ▶ 重跑 heal（ffprobe） | `_heal_linked_av_duration_mismatch` 按片段签名幂等 |

涉及：`editor_module.py`（未改冻结 `playback-av` 符号体）  
验收：导入视频 → 立刻 ▶，起播无明显卡顿；同文件反复 ▶ 不反复探针。

### 导入/时间线（较早）

- `_ensure_preview_manager()` 后再 `open_video`
- ClipWidget `elidedText` 替代错误的 `setEllipsize`
- 详见 `debug-video-import-timeline.md`

## 已完善（2026-07-25 手感/接线）

| 项 | 说明 |
|----|------|
| 修复 `move_clip` | 此前误粘在 `add_keyframe_at_playhead` 后成为死代码 |
| 吸附默认开 | 按钮与 `_snap_enabled` 同步；trim 片头/片尾也可吸附 |
| 波纹删除 | 删视频连带删联动音频；一次撤销恢复整组 |
| 变速 | 「应用变速」写片段 speed（可撤销）；复杂预设走导出 |
| LUT | 调色页应用/即时预览写入 `effects.color_params.lut` |
| 关键帧入口 | 时间线工具条「◆ 关键帧」 |

## 已完善（2026-07-25 第 2 期所见即所得 · 第一刀）

| 项 | 说明 |
|----|------|
| 字幕进工程 | `subtitle_styles` 存取对齐 `SubtitleManager`；导入刷新列表；字幕编辑标 dirty |
| 字幕-only autosave | 无片段但有字幕也会写入 `autosave/latest.timeline` |
| 音量打通预览 | 音频页「片段/总控」滑条；轨音量 × 片段 × 总控；导出烘焙含轨音量 |
| 转场 UI | 类型/时长/曲线控件真正存引用并写入片段 `transition` |
| 字幕烧录样式 | ASS 导出（字体/色/描边/底/位置）；预览按 x,y 中心锚点；失败回退 SRT |
| 多轨导出 | 主轨按 start_time 黑场空隙；上层视频画中画叠轨；独立音频 adelay+amix；跳过联动内嵌音 |
| 关键帧深工具 | 属性选 opacity/volume/scale；删关键帧；缓动走 `keyframe_animation`；可撤销；EffectManager getter 修复 |
| 滤镜预览体验 | 滑杆 60ms 节流；同帧只改 GL uniform；拖 scrub 降分辨率；播放跳过锐化/模糊/暗角；LUT 半分辨率快路径 |
| 多轨导出 UX | 叠轨/混音进度 toast；失败明文提示；PiP 读专业页 X/Y/大小 |

## 已完善（2026-07-25 右侧工具栏接线）

| 项 | 说明 |
|----|------|
| 调色页 | 基础/HSL 滑杆存 `_color_sliders`；拖动即时预览；应用/重置写入片段 `effects.color_params`（可撤销） |
| 属性页 | 不透明度 / 缩放 / 位移 / 旋转 live 写片段；选中时同步滑杆 |
| 导出页 | 平台/分辨率/帧率/码率等真实 `QComboBox` 引用；硬件加速可见；项目信息刷新；`_export_video` 安全读取控件 |

## 已修复（2026-07-25 导出链路）

| 根因 | 修复 |
|------|------|
| `ProfessionalVideoEngine` 打印 `✓` 在 GBK 控制台抛错 → 「FFmpeg CLI 不可用」 | 安全打印 / ASCII 标记 |
| 专业渲染 `-hwaccel_output_format cuda` + CPU `scale` → Function not implemented | 仅 `-hwaccel cuda`，帧回系统内存再滤镜 |
| UI「硬件加速」未进最终转码 | `apply_export_settings` 优先 NVENC/QSV/AMF，失败软编 |
| `H.265` 未映射 / 缺编码器直接失败 | 映射 `libx265`；失败回退 `libx264` |
| `ffprobe`/`-encoders` 用系统默认编码导致 probe 空 | `encoding=utf-8, errors=ignore` |
| 导出源片取 `_clips[0]` 可能是音频 | 优先取视频轨路径 |

涉及：`professional_video_engine.py` · `video_processor.py` · `render_manager.py` · `editor_module.py`

## 已修复（2026-07-25 贴纸）

| 根因 | 修复 |
|------|------|
| 仅离线 FFmpeg 烘焙，预览无叠加 | 点击即上画布；`_overlay_stickers_on_qimage` 进预览/GL |
| 后台线程 `QMessageBox` 易卡死 | 去掉线程弹窗；滑杆 live 写回选中贴纸 |
| 导出不含贴纸 | `_burn_stickers_if_any` 在字幕烧录后执行 |
| 工程不存贴纸 | `export_project` / `import_project` 读写 `stickers` |

## 已修复（2026-07-25 字幕识别）

| 根因 | 修复 |
|------|------|
| `from core.subtitle_generator` 导入失败 → 假字幕「字幕片段 N」 | 改走 `app.core.ai.whisper_asr`；禁用占位假文案 |
| Whisper 未安装 | 需 `pip install faster-whisper`；未安装时明确提示 |
| TypoCorrector 乱换「的/得/在/再」 | 默认纠错表清空；`correct_typos=False` |
| 未按片段 in/out 截取音频 | 提取当前片音轨并按 `start_time` 对齐时间轴 |
| HuggingFace 超时下不了模型 | `whisper_asr` 默认 `HF_ENDPOINT=https://hf-mirror.com` |

## 环境补齐（2026-07-25）

一键脚本：`scripts/setup_deps.ps1`  
已装：CUDA `torch 2.6.0+cu124`（RTX 4060）、`faster-whisper`、`transformers`、`easyocr`、`librosa`；Whisper **tiny/base** 已缓存。  
注意：勿用默认 PyPI 装 CPU 版 torch 覆盖 CUDA wheel。

## 已完善（2026-07-28 A2 滤镜/scrub 预览降载）

| 项 | 说明 |
|----|------|
| 播放二次解码 | `playhead_moved` 在播放中 early-return，避免 `_render_timeline_frame` 后再走一遍 scrub 预览 |
| scrub 合并 | 50ms 定时器合并 playhead 事件，松手 220ms 后恢复高质量 + 一次性音频 seek |
| scrub fast | `_lighten_effects_for_playback` 在 `_preview_scrubbing` 时也设 `_preview_fast` |
| CPU 滤镜 | `PreviewManager._apply_effects_sync`：fast 跳过命名滤镜与 hue/gamma/exposure |
| 质量恢复 bug | `_begin_preview_scrub` 修正读 `preview_quality`（非 `_preview_quality`） |
| 可观测 | scrub 结束日志 `scrub 预览合并 N 次请求（降载）` |

涉及：`editor_module.py` · `preview_manager.py`  
验收：`_verify/test_scrub_filter_smoke.py`

## 已完善（2026-07-28 轨 C1 发布真回执）

| 项 | 说明 |
|----|------|
| 快速发布死按钮 | `account_ops_module._create_publish_card` 中 `pub_btn` 接线 `_quick_publish` |
| 矩阵/快速假成功 | `_execute_publish` 统一回执：`failed` / `local_queue` / `local_export` / `upload_attempted`；禁止弹「已提交到平台」 |
| publish_log | 写入 `status` + `receipt_kind` + `message`（及 `export_path`）；不再默认 `published` |
| PlatformIntegrator | 有 Playwright 上传器时标 `upload_attempted` 并提示后台核对；否则标本地导出路径 |

涉及：`account_ops_module.py`  
验收：账号运营 → 快速发布/矩阵发布，无视频或标题应失败可见；无 API 时文案含「本地队列/需手动上传」。

## 已完善（2026-07-28 轨 C2 爆款优化进 UI）

| 项 | 说明 |
|----|------|
| 入口 | 账号运营各平台面板 →「🔥 爆款优化建议」（在 AI 运营建议下方） |
| 引擎接线 | `get_account_analyzer().analyze_data()` → `_build_video_features_from_analysis` → `ViralOptimizationEngine.predict_performance` + `generate_optimization_suggestions` |
| 无数据 | 状态条提示 `app/运营数据` 为空；「样例分析」明确标注非真实数据 |
| 引擎失败 | 显示「爆款优化引擎加载失败」，不弹假成功 |
| C1 保留 | 快速/矩阵发布真回执未回退 |

涉及：`account_ops_module.py`  
手测：启用账号运营 → 任平台 →「从运营数据生成」（无数据应警告）→「样例分析」应出预测与建议。

## 已完善（2026-07-28 轨 C3 闭环跳转）

| 项 | 说明 |
|----|------|
| 入口 | 账号运营各平台 →「🔥 爆款优化建议」生成后 →「🎭 去短剧筛选选题」/「✂️ 去剪辑（下一轮粗剪）」 |
| 跳转机制 | `EventType.MODULE_ACTIVATED` + `target`/`action`/`workflow_hint`；`MainWindow._flush_pending_module_action` 交付子页 |
| 粗剪提示 | `target=editor` + `workflow_hint` → 剪辑状态栏 + 非模态信息框展示优化项摘要 ✅ |
| 短剧筛选 | 原设计 `target=plugins` + `action=drama_finder` |
| C2 保留 | 爆款引擎/analyzer 接线未回退 |

涉及：`account_ops_module.py` · `main_window.py` · `editor_module.py`（`_on_workflow_hint_received`）

### 开放缺陷（2026-08-04 复核）— C3 短剧支路断裂

| 根因 | 说明 |
|------|------|
| 注册表迁移 | `plugins` 已迁为 **`extensions`**；`is_enabled("plugins")` 恒为假 |
| 跳转未改 | ~~`account_ops` 仍发 `target=plugins`~~ → **已修（M1 / 2026-08-07）** |
| 宿主漂移 | 短剧常驻标签在未注册的 `plugins_module`；运行时走拓展中心 `_open_drama_finder` |

**M1 已修（2026-08-07）**：`account_ops` → `target=extensions` + `action=drama_finder`；`main_window` 归一化旧 `plugins` 并调用 `_open_drama_finder`；首页快捷「拓展中心」。自动导入选题仍待 **M6**。

## 已完善（2026-08-07 M2 漫剧竖屏导出 · 第一刀）

| 项 | 说明 |
|----|------|
| 默认画幅 | 导出缺省 `1080x1920` / `9:16`（原静默 16:9） |
| 预设接线 | 平台（抖音等）与「漫剧竖屏快切」等输出模式真正改分辨率/比例/码率 |
| 一键按钮 | 导出页「一键漫剧竖屏 1080×1920」 |
| 不拉伸 | `apply_export_settings` 使用 `scale=…:decrease` + `pad` 黑边 |
| 预览徽标 | 预览条显示竖屏/横屏画幅提示 |
| 冒烟 | `_verify/test_export_portrait_pad_smoke.py` |

仍开：无（A3 播放跟曲线已在解冻 `playback-av` 后接线）。

## 已完善（2026-08-08 轨B · 工程画幅 SSOT）

| 项 | 说明 |
|----|------|
| SSOT | `app/core/sequence_format.py`：`SequenceFormat` + `parse_*` / `normalize_size` / `fit_rect` |
| 工程字段 | `EditorModule._sequence_format`；`export_project` / `import_project` / autosave 写 `sequence` |
| 默认 | 漫剧竖屏 `9:16` · `1080×1920` · `fit_mode=contain` |
| 预览 | `_present_preview_frame`：按工程画幅 letterbox（contain 黑边 / cover 裁切），不硬拉 |
| 导出 | 读 SSOT 分辨率 + `scale_fit`；控件↔SSOT 双向同步；一键竖屏/横屏 |
| 测例 | `app/tests/test_sequence_format.py` |
| **热修** | `SEQUENCE_FORMAT_PRESETS` 写在类定义前导致 `NameError`（无法 import）→ 已移到类后 |

明确不做：智能 16:9→9:16 重构；时间线多选/吸附（轨A）。

## 已完善（2026-08-08 轨B续 · 预览/导出 WYSIWYG）

| 项 | 说明 |
|----|------|
| GL | `_show_frame_gl` 先 `_fit_qimage_to_sequence` 再叠字幕/上传，滤镜预览不再绕过画幅 |
| 多轨 | 底图 `_place_bgr_on_sequence_canvas`；叠层 `normalize_clip_transform` 用 sequence 宽高 |
| 尺寸 SSOT | `_preview_frame_size` / 空黑帧读 `_sequence_format`，不再跟源片分辨率 |
| 几何 | `_apply_sequence_format_to_preview` 同步 `_gl_widget` geometry |
| 旧工程 | 无 `sequence`/`resolution`/`aspect` 时 `_infer_sequence_from_clips`（首个视频片） |

## 已完善（2026-08-08 · 刀片工具 / 联动切 / 多选属性 / 跨轨 / 合缝）

| 项 | 说明 |
|----|------|
| 刀片工具态 | ✂ 可切换；C 切换；Esc 退出；悬停红切开线；点击按指针时间切开 |
| Ctrl+K | 仍在播放头切开 |
| 联动音画 | `_cut_at_timeline_time` 扩展同 path/同 start 联动片，compound undo |
| 多选属性 | 不透明度/音量/调色/滤镜写 `get_selected_clips()`；音量/调色/滤镜 compound |
| 多选跨轨 | 批量拖移时同类型轨落到指针下轨道；undo 记按下时 track |
| 合缝 | `edit_commands.close_track_gaps`；Shift+Del / 右键「合缝」；可撤销 |

**P0 四项验收（刀片+联动 → 多选属性 → 跨轨拖移 → Close Gap）：已完成。**

涉及：`timeline_widget.py` · `editor_timeline_tools.py` · `editor_module.py` · `edit_commands.py`

## 已完善（2026-08-08 · 非 xfade 转场：映射 / bake / 诚实降级）

| 项 | 说明 |
|----|------|
| 映射扩展 | zoom→`zoomin`；glitch→`pixelize`；flip/spin 失败回退 `squeezeh`/`radial`；dissolve 仍走 ffmpeg `dissolve` |
| 保真度 API | `export_fidelity_for_transition` / `export_degradation_note` / `collect_transition_export_notes` / `is_bakeable_transition` |
| 插件 bake | flip / spin：重叠窗 OpenCV 插件混合 + ffmpeg 头尾 concat + acrossfade；失败回退 xfade |
| UI 提示 | 应用转场 `_notify_edit` 附 note；导出前汇总「导出将近似/烘焙…」 |
| 明确不做 | 完整转场库重写；剪映商店包；glitch 真 bake（成本高，诚实 pixelize） |

涉及：`transition_plugin_registry.py` · `video_processor.py` · `editor_module.py` · `editor_export_panel.py`  
验收：`test_lut_transition_smoke.py`（含 fidelity / xfade 映射）

已知限制：zoom/glitch 仍为 xfade 近似；bake 依赖 cv2+ffmpeg，重叠窗按帧数线性变慢。

## 已完善（2026-08-08 · 体验五连：联动 / 转场导出 / scrub / 关键帧 / 拆面板）

| 项 | 说明 |
|----|------|
| 联动音画 | `move_clip` / `_resize_clip` 走 `_sync_linked_av_timing`；`close_track_gaps` 单轨合缝跟 Δstart；undo 不改伙伴轨号 |
| 转场预览≈导出 | `xfade_name_for_transition(plugin_id)` → `build_xfade_filtergraph`；fade/slide/wipe 对齐；非精确见上节 bake/降级 |
| 长片 scrub | scrub open 跳过帧数探针；GL 尊 `lut_fast`；LUT 滑杆 120ms + scrub busy-drop |
| 关键帧连续 | bake 门禁含 opacity/volume KF；分段采样加密；叠轨 `_op_kfs`→geq alpha |
| 拆面板 | `editor_color_panel.py` · `editor_props_panel.py` · `editor_audio_panel.py` · `editor_ai_panel.py`（字幕面板同款薄包装；AI 业务仍在 `ai_agent_panel` Mixin） |

涉及：`edit_commands.py` · `transition_plugin_registry.py` · `video_processor.py` · `preview_manager.py` · `gl_filter_widget.py` · `editor_export.py` · `editor_module.py`  
验收：`test_edit_commands.py`（合缝联动）· `test_lut_transition_smoke.py`

## 已完善（2026-08-08 · .cube LUT UI + 自研转场插件）

| 项 | 说明 |
|----|------|
| 导入 .cube/.3dl | 调色页「导入.cube」→ `lut_loader.register_file`；下拉 `userData`=路径；`get_preset` 可解析路径 |
| 应用 LUT | 多选 `_property_target_clips` + compound；预览/导出共用 `color_params.lut` |
| 转场下拉 | `transition_plugin_registry` 扫描 `app/plugins/transition_*.py`（ITransitionPlugin / `apply`） |
| 预览双帧 | 片尾转场窗 `_try_render_plugin_transition` 调插件混合；失败回退 dissolve 透明度近似 |
| 明确不做 | 剪映素材商店包 / OFX / AE 预设兼容 |

涉及：`lut_loader.py` · `transition_plugin_registry.py` · `editor_module.py` · `gl_filter_widget.py`  
验收：`test_lut_transition_smoke.py`

**热修（刀片/合缝硬ening · 2026-08-08）**：

| 项 | 说明 |
|----|------|
| 双选音画重复切 | `_cut_at_timeline_time` 去掉「补切」内层循环；联动片仅由 `_expand_cut_targets_with_linked_av` 去重调度，每 id 只切一次 |
| Esc 抢键 | Esc 改为时间线 `WidgetShortcut` + 仅刀片开启时 enable；模态框 Esc 不再被抢 |
| 合缝 deepcopy | `_sync_timeline_widget_state` 镜像 `tw._clips` 并按 id 重绑 `_current_clip`，合缝/撤销后选区与 widget 一致 |
| 框选冲突 | 进出刀片时 `_clear_marquee_state`；razor 态下 `_marquee_release` 早退 |

验收：`app/tests/test_edit_commands.py`（`TestCloseTrackGaps` · `TestExpandCutTargetsLinkedAv`）

## 已完善（2026-08-08 · 剪映式时间线胶片条缩略图）

| 项 | 说明 |
|----|------|
| 现象 | 蓝紫占位条 / 同一帧循环刷屏；缩放不加密；trim 后仍显示片头；相对路径不出图 |
| 根因 | 采样忽略 `in_point`；绘制 `i % N`；仅创建时按窄 width 采一次；缩略图未走 `_resolve_clip_media_path`；每格一次 ffmpeg 冷启动 |
| 修复 | `ClipWidget`：`t_i = in+(i+0.5)/N*(out-in)`；`thumb_key` + 120ms debounce；resize/zoom/`position_clip_widget`/trim 重采；等距映射禁 modulo；OpenCV 单开批量抽帧，失败回退 `ffmpeg_service.extract_frames_batch`；N≤48 |
| 验收 | 竖/横屏连续胶片；放大变密；左/右 trim 内容随 in/out；`assets\videos\...` 可出图；音频轨仍只波形 |

涉及：`timeline_widget.py` · `ffmpeg_service.py`

## 已完善（2026-08-08 热修 · 首帧 No Signal 假画面）

| 项 | 说明 |
|----|------|
| 现象 | 有素材时预览仍显示灰底 `No Signal`，不是视频真首帧 |
| 根因 | `_read_frame` 在 capture 未就绪时返回占位图，被当成成功帧；恢复工程后首帧刷洗不稳 |
| 修复 | 占位不再冒充读帧；`get_first_frame` 双路径 seek；`_force_show_first_video_frame` 在导入/恢复/加片后强制出画；路径解析绝对化；主选优先视频片 |

## 已完善（2026-08-08 热修 · 播放后半只剩声音 / 首帧 ????）

| 项 | 说明 |
|----|------|
| 现象 | scrub 有画；播放约前 8s 有画，之后只剩声音；首帧灰底带问号 |
| 根因 | ① 视频轨时长被压短（~7s）而同文件音频轨仍是全长 → `video_hits` 空后黑场，音频轨继续出声；scrub 回退 `_current_clip` 仍能解画。② 占位图曾用中文「无视频信号」，OpenCV Hershey 画成 `????` |
| 修复 | 导入/恢复时 `_resolve_media_duration` + `_heal_linked_av_duration_mismatch`；播放无视频命中时用同文件音频窗解画；占位改 ASCII；`_cap_next_idx` 仅成功读帧才推进；导入强制刷首帧 |

仍注意：刀片后只移视频不移音频会造成音画窗不对齐；联动 trim 应走 `_sync_linked_av_timing`。

## 已完善（2026-08-08 热修 · GL 失败挡预览）

| 项 | 说明 |
|----|------|
| 现象 | 导入后预览区 `????` / 黑屏，时间线缩略图正常 |
| 根因 | `_ensure_gl_preview` 初始化异常后仍把坏掉的 `GLFilterWidget` 留在 `QStackedLayout` 当前页，CPU `QLabel` 被挡住 |
| 修复 | 失败时 `removeWidget` + 切回 `_preview_label`；`setPixmap` 时清空占位文字 |

## 已完善（2026-08-08 手感续 · fit / ZoomFit / 刀片）

| 项 | 说明 |
|----|------|
| fit_mode UI | 导出「适配」下拉：等比黑边 / 裁切铺满；写入 `_sequence_format`；预览徽标可点击切换 |
| Zoom to Fit | 修正 `BASE_PPS=20` 公式；按片段内容时长 + 可视宽度；工具栏 ⧉ + Ctrl+0 |
| 刀片 | 工具栏 ✂；`C`（输入框不抢键）+ `Ctrl+K`；支持多选/命中播放头批量切 |

已续：完整刀片工具态（见上节）；JKL 见「穿梭手感」节。

## 已完善（2026-08-07 解冻 playback-av · 播放跟 speed_ramp）

| 项 | 说明 |
|----|------|
| 授权 | 用户「解冻」（承接 A3：播放主时钟跟曲线） |
| 画面 | `_render_timeline_frame` 取帧用 `source_time_for_clip_at_timeline` |
| 主音 | `FROZEN:playback-av:main-audio`：`source_t` + `instant_speed_for_clip_at_timeline` → `setPlaybackRate`；墙钟 / 280ms 纠偏不变 |
| 重锁 | `python scripts/frozen_zone_guard.py --update` |
| 不变式 | 仍禁止 `+= 固定步长`；仍不 `setVideoOutput` |

## 已完善（2026-08-07 A3 速度曲线分段烘焙 + scrub 映射）

| 项 | 说明 |
|----|------|
| 导出 | `build_speed_ramp_filter_complex` 多段 trim/setpts/atempo/concat；补 `output_path`；失败回退平均倍率 |
| 数学 | 修复 `get_source_time`（按输出时间积分源位置） |
| 预览 | scrub / `_refresh_preview_with_effects` 经 `source_time_for_clip_at_timeline` 读 `speed_ramp` |
| 播放 | 见上「解冻 playback-av」 |
| 测例 | `app/tests/test_speed_ramping.py` |

## 已完善（2026-08-07 M2 长对白 scrub 降载）

| 项 | 说明 |
|----|------|
| busy-drop | `_scrub_render_busy`：上一帧未解完则丢弃中间请求，只渲染最新 pending |
| 跨 clip | `open_video(..., preload=False, for_scrub=True)`：不预载 30 帧、不拉预读线程 |
| 叠层 | 拖 scrub 时 `_show_frame_gl` 跳过字幕/贴纸；松手 HQ 再补 |
| 合并窗 | scrub coalesce 50→80ms |
| 未动 | 冻结 `get_frame_at` / 播放主时钟 |
| 冒烟 | `_verify/test_scrub_filter_smoke.py` |

## 已完善（2026-08-06 Agent A+C：白名单 + 诚实降级）

| 项 | 说明 |
|----|------|
| A 白名单 | `ai_agent_panel`：仅允许安全指令 + `remove_clip`/`ripple_delete`；未知 action 拒绝并列出允许集 |
| A 危险确认 | 删除/波纹删执行前确认；取消则跳过 |
| A→B1 | `ripple_delete` 带时间区间时走 `edit_commands` + 可撤销 |
| C 汇总 | 「成功/跳过/失败」计数，避免笼统「已执行」 |
| C 模型失败 | 标明「仅本地规则回退，非模型成功」 |
| C 全链路 | `PipelineSession.degraded`：无成片仅脚本时 UI 标降级而非庆祝成片 |

涉及：`ai_agent_panel.py` · `editor_module.py` · `agent_pipeline_orchestrator.py`（未动 Dispatcher/Brain/冻结区）

## 已完善（2026-08-07 M6 选题发送到剪辑）

| 项 | 说明 |
|----|------|
| 入口 | 拓展中心短剧弹窗底部「📤 发送到剪辑」（外挂，**未改**冻结区 `drama_ui.py`） |
| 路径 | `drama_send_to_editor` → `MODULE_ACTIVATED(editor)` + `MATERIAL_TO_TIMELINE` → `_add_clip_to_timeline` |
| 诚实失败 | 元数据无 `local_path` 等 → 提示后可选手选本机视频；取消则不写 `_clips` |
| 明确不做 | 不下载成片、不自动精剪、不走 `DRAMA_SELECTED` 全链路 |
| 测例 | `app/tests/test_drama_send_to_editor.py` |

## 已完善（2026-08-07 M5 确认后执行竖切）

| 项 | 说明 |
|----|------|
| UI | `CleanupChecklistDialog`：建议列表可勾选（全选/全不选/仅填充词）；「执行选中」才写 `_clips` |
| 入口 | 字幕面板「一键去水词」→ 勾选确认（不再汇总 Yes/No 全删） |
| Agent | `editor.suggest_cleanup` / 对话 `suggest_cleanup`；`open_ui=False` 仅返回建议 JSON |
| 约束 | **不**默认 `pipeline.run_full`；未勾选则不改时间线 |
| 测例 | `TestCleanupPlanSubset` + `test_suggest_cleanup_handler_data_only` |

## 已完善（2026-08-07 M4 Agent 公开 API + 波纹删 capability）

| 项 | 说明 |
|----|------|
| 公开包装 | `EditorModule.agent_ripple_delete_range` → `_apply_ripple_delete_range`（B1 + widget/内核同步） |
| Capability | `editor.ripple_delete_range`（内置 24 个）；Brain 神经元同步 |
| 对话对齐 | `ripple_delete` / `ripple_delete_range` → 公开包装；split/filter/transition 亦走 `agent_*` |
| 测例 | `app/tests/test_editor_ripple_capability.py` |

仍薄：导入/导出/字幕 CRUD 等未暴露（故意）。

## 仍开放 / 待做

- GPU 滤镜：命名滤镜可实时；LUT 可走 **GPU 2D 图集**（失败自动回退 CPU）
- 导出 nvenc 正常，预览加速 ≠ 成片加速（预期）
- 速度斜坡曲线仍走「导出成片」；固定倍率已写入片段 `speed` ✅
- 叠轨带 transform 关键帧：优先 **连续 overlay 表达式**；失败回退分段静态
- `editor_module.py` 仍大（实测 **13,321 行**，见 [`10-editor-module-split-plan.md`](10-editor-module-split-plan.md)）；已抽 [`clip_transform`](app/modules/lego/clip_transform.py) · [`editor_export`](app/modules/lego/editor_export.py) · [`editor_burn`](app/modules/lego/editor_burn.py) · [`editor_subtitle_panel`](app/modules/lego/editor_subtitle_panel.py) + B0–B2 core
- 7 阶段闭环：**C1/C2 ✅**；**C3 半通**（见上）；自动导入选题 / 一键粗剪仍缺
- `extensions` 实验级却默认开（与「首屏只 CORE」不完全一致）
- 冻结区见 [`08-frozen-zones.md`](08-frozen-zones.md)

## 已完善（2026-07-25 所见即所得·导出烘焙）

| 项 | 说明 |
|----|------|
| 缩放/不透明度 | `bake_clip_transform` 写入主轨成片（半透明叠黑底） |
| 不透明度关键帧 | geq 动画 alpha |
| 音量关键帧 | `volume=expr:eval=frame` |
| scale 关键帧 | 分段静态 bake + concat（阶跃近似，非连续 zoompan） |
| 叠轨 | 可读属性页 scale/position；PiP 滑条仍优先 |
| exposure | 映射进 `eq` brightness |

## 已完善（2026-07-25 剪辑体验短冲刺）

| 项 | 说明 |
|----|------|
| 归一化变换 | `normalize_clip_transform` / `apply_normalized_transform`；属性页与 PiP 滑条读写同一套 `pip_*` + `transform` |
| 预览叠层 | `_render_timeline_frame` 按 x/y/scale 偏移粘贴（多轨跳过单层 GL） |
| 导出叠轨 | `overlay_timeline_videos` 与预览同坐标；scale 上限 2.0；去掉 1920×1080 硬编码映射 |
| scale 关键帧导出 | 去掉中点近似，走分段烘焙 |
| UX | 导出分阶段文案；autosave 恢复带修改时间；AI 字幕失败摘要更明确 |

## 已完善（2026-07-25 变换深工具）

| 项 | 说明 |
|----|------|
| 旋转/锚点 | 属性页接线；预览 `composite_overlay_bgr`；导出 bake `rotate=` + 叠轨 rotate |
| position/rotation 关键帧 | 添加关键帧 UI + `_interpolate_clip_keyframes`；预览吃 `_tf_x/y/rot` |
| 画布拖拽 | `_preview_label` eventFilter 拖动改归一化 x/y |
| GPU LUT | `GLFilterWidget.supports_lut` + 2D 图集纹理；失败回退 CPU |
| 拆分 | 新增 [`clip_transform.py`](app/modules/lego/clip_transform.py)；`video_processor` 再导出 |

## 仍开放 / 待做

- `editor_module` 继续拆 UI/AI 面板（可维护性；导出/字幕已抽）
- 7 阶段闭环：修 C3 `plugins→extensions`；自动导入选题 / 一键粗剪仍缺

## 已完善（2026-07-25 叠轨 KF 连续化）

| 项 | 说明 |
|----|------|
| 导出 | `overlay_timeline_videos` 吃 `_x/_y/_sc/_rot_kfs`，scale+overlay `eval=frame` |
| 预拆段 | 默认不再拆段；失败才 `_force_segment_overlay` |
| 冒烟 | `_verify/test_overlay_kf_smoke.py` |

## 非剪辑模块审计（2026-07-25）

来源：全库盘点。  
原则：**先诚实降预期 / 修阶段 4，再谈闭环**；不优先堆未接线引擎。

| 问题 | 严重度 | 说明 |
|------|--------|------|
| 账号「矩阵发布」假成功 | — | **已修（2026-07-28 C1）**：不再写 `status=published` 假回执；须选视频+标题；弹窗区分 `local_queue` / `local_export` / `upload_attempted` / `failed` |
| 账号「快速发布」死按钮 | — | **已修（2026-07-28 C1）**：`pub_btn.clicked.connect` → `_quick_publish`；补视频浏览与诚实说明 |
| 在线素材假目录 | 高 | `online_materials._generate_materials` 随机造卡；下载 MOCK |
| 短剧筛选入口 | — | **已收口（同日）**：删注册表 drama 模块；仅插件；爬虫打包进 `drama_finder_plugin/crawler/` |
| 短剧筛选无打开入口 | — | **已修（同日）**：详情页「打开界面」→ `plugin.run()` 弹 `DramaFinderWidget` |
| 打开插件 `'Plugin' has no _widget` | — | **已修**：PluginManager 只实例化不 `initialize`；`getattr(_initialized, True)` 误跳过；短剧插件补 `__init__`/`_initialized`，打开前 `_ensure_plugin_initialized` |
| 短剧筛选无可视化预览 | — | **已修**：`drama_ui.py` 封面卡片墙+右侧详情预览；插件中心常驻「🎭 短剧筛选」标签 |
| 插件商店虚构上架 | — | **已修**：`OFFICIAL_ITEMS`/`items.json` 仅保留 `app/plugins` 真实 17 项；剔除智能剪辑/字幕生成/批量导出Pro 等假条目；残缺转场补 description |
| AI特效面板 AttributeError | — | **已修**：`btn_glamour.setToolTip` 笔误 |
| 模块切换卡顿/抢跳 | — | **已修**：禁用后台 `_on_module_selected` 预加载（曾误激活剪辑等重模块） |
| 播放声音卡顿 | 中 | **缓解**：主音/BGM 纠偏阈值 80ms→280ms，减少每帧硬 seek |
| 关程序后仍出声 | — | **已修（同日）**：`EditorModule.cleanup` + `MainWindow._stop_all_media_on_exit` 关窗前 stop/静音/清 source（Windows WMF 幽灵音） |
| 首页快捷跳未启用模块 | 中 | `MODULE_ACTIVATED` 时导航无按钮 → 静默无反应（短剧快捷已改为插件中心） |
| 文案无模型静默模板 | — | **已修（同日）**：云端失败弹窗征得同意再模板；模型项改名「本地模板（非 AI）」；批量/AB 带回退 reason |
| extensions 实验却默认开 | 低 | 原 plugins 已迁 id=`extensions`；仍 default_enabled=True，与「首屏只 CORE」不完全一致 |
| viral / account_analyzer | 中 | **C2 已接线**：账号运营「爆款优化建议」；仍不吃平台真播放 API |
| C3 短剧跳转 | 高 | **2026-08 开放**：仍 `target=plugins`，registry 无此 id（见上文「C3 短剧支路断裂」） |
| TTS 类名不一致 | — | **已修**：`VoiceGenerator` 别名 + `generate_audio`；AIEngine TTS 适配器可初始化 |
| `AIEngine.__init__` 误放进 `get_instance` return 后 | Agent 报 `_clients_loaded` 缺失、模型调用全失败 | **已修**：初始化体移回 `__init__`；`_ensure_clients` 容错补属性 |
| 「AI 插帧」名不副实 | — | **已修**：文案改为线性补帧；默认仍关闭 |

相对可信：settings · help · performance（监控）· copywriting（配好 Provider；失败不再静默假 AI）· materials **本地**导入 · 短剧筛选（插件中心启用后）。

## 短剧筛选爬虫可用性（2026-07-25）

引擎位置：`app/plugins/drama_finder_plugin/crawler/`  
适配层仍在：`modules/lego/*_playwright_api.py` · `stealth_browser.py` · `tiktokhub_douyin_api.py`

| 层 | 完整度 | 本机可用性 |
|----|--------|------------|
| 数据结构 / 评分 / 推荐 / 偏好持久化 | 高 | ✅ |
| 平台壳 15 个 | 列表齐全 | 多数 `api_class=None`（未接入） |
| Douyin/Kuaishou/Bilibili **内置 API 类** | 有代码 | ❌ 实为 `_generate_data` 随机假数据 |
| Playwright 抖音/B站 | 代码在 lego | ❌ 当前 venv **未装 playwright** → 不注入 |
| TikHub | 代码在 | ❌ 未配 `TIKHUB_API_TOKEN` |
| DramaWebScraper HTTP 源 | 有骨架 | ❌ `api.example.com` 且 `enabled=False` |
| `app/data/drama_data.json` 静态缓存 | 有文件 | ✅ 迁插件后路径曾指错 `plugins/data`，**已修回 app/data** |
| 内置标题池兜底 | 有 | ✅ UI 永不空，但非真实榜单 |

**结论**：代码链路完整；**默认优先静态缓存**（`app/data/drama_data.json`），不再被内置随机假 API 抢先。真榜单仍需 Playwright/TikHub。  
完善（2026-07-25）：跳过 fake API → Web/静态 → 随机兜底；UI 标注来源；验收 `test_drama_crawler_static.py`。

## 已完善（2026-07-25 连续变换 bake）

| 项 | 说明 |
|----|------|
| 主轨 KF | `bake_clip_transform` 优先 `_bake_clip_transform_continuous`（scale eval=frame + rotate + overlay eval=frame） |
| 回退 | 表达式失败时仍走分段静态 + concat |
| 位置 | 不用含 `t` 的 pad（不稳定），改 overlay 归一化坐标 |

## 已完善（2026-07-25 画布缩放把手）

| 项 | 说明 |
|----|------|
| 边角缩放 | 命中片段包围盒四角/边框 → 拖拽改 scale |
| Ctrl+滚轮 | 预览区缩放当前选中片段 |
| 变换框 | 暂停时绘制蓝框+四角把手；Alt 仍为旋转 |
| 坐标 | 鼠标映射扣除信箱黑边，与 KeepAspectRatio 预览对齐 |

## 已完善（2026-07-25 position 关键帧 + 旋转把手）

| 项 | 说明 |
|----|------|
| transform 分段 | `_build_transform_segments` 同时吃 scale/x/y/rotation 关键帧（叠轨/回退仍用） |
| 主轨导出 | 连续表达式 bake（见上）；失败回退分段 |
| 叠轨导出 | 有 transform 关键帧时拆成多段静态 overlay（避免透明通道丢失） |
| 画布旋转 | Alt+拖 或 四角附近拖 → 旋转；中心区拖 → 平移 |

## 已完善（2026-07-28 B0 文本↔帧绑定）

| 项 | 说明 |
|----|------|
| 映射层 | `app/core/text_frame_map.py`：Whisper/字幕条目 → timeline & source 的 in/out 秒 + 半开帧区间 |
| 边界策略 | 默认 `SAFE_WORD`：起点 `floor(t*fps)`、终点 `ceil(t*fps)`（`[frame_in, frame_out)`），极短段至少 1 帧 |
| 接线点 | `SubtitleManager.compute_frame_bindings(clip, fps)`；编辑器 AI 字幕写入处注释指向 B1 |
| 验收 | `pytest app/tests/test_text_frame_map.py -m unit` |

## 已完善（2026-07-28 B1 薄指令执行器）

| 项 | 说明 |
|----|------|
| 执行层 | `app/core/edit_commands.py`：`split_clip_at_timeline` / `ripple_delete_timeline_range` / `ripple_delete_from_binding` |
| 撤销 | 返回 `compound` steps，与 `EditorModule._apply_action` 对接；Ctrl+Z 可回滚整段 split+delete |
| UI 入口 | 字幕面板「🗑 删除」：B0 帧绑定 → 主视频轨波纹删除 → 再删字幕条目 |
| 限制（已热修 2026-08-08） | `ripple_delete_timeline_range` 在切分/删除时扩展同 path + start 对齐的联动内嵌音，compound undo；字幕去水词不再留下「只剩音频」 |
| 验收 | `pytest app/tests/test_edit_commands.py -m unit` |

## 已完善（2026-08-08 · JKL 穿梭手感）

| 项 | 说明 |
|----|------|
| 文件 | 仅 `playback_shuttle.py`（未改冻结墙钟） |
| 修复 | 闲置时 `_playback_rate` 曾返回 0 → Space 播不动；现回退到倍速下拉基速 |
| 手感 | J/L 点按 1→2→4→8；按住保持；松手约 300ms 减速停；K 立即停 |
| 焦点 | App 级 filter；输入框内忽略；不抢 Space / C |
| 验收 | `_verify/test_playback_shuttle_smoke.py` |

## 已完善（2026-07-28 B2 去水词/长静音）

| 项 | 说明 |
|----|------|
| 检测层 | `app/core/filler_silence_detect.py`：纯填充词（呃/嗯/啊等）+ 句间长静音（默认 ≥0.4s，可配置） |
| 映射 | 经 B0 `bind_entries_to_clip` → timeline `[t_in,t_out)`；批量删除从右向左复用 B1 |
| UI 入口 | 字幕面板「✂ 一键去水词」；需先有 AI/导入字幕；短剧密集对白仅删纯填充词且二次确认 |
| 限制 | 句级 ASR，混合句内填充词默认不删；仅主视频轨 |
| M3 同步 | 去水词完成后默认询问「是否重对齐字幕」→ `realign_subtitles_after_cleanup`（右→左移位，相交切口丢弃） |
| 验收 | `pytest app/tests/test_filler_silence_detect.py -m unit` |

## 已完善（2026-08-07 M3 去水词后字幕重对齐）

| 项 | 说明 |
|----|------|
| 纯数据 | `filler_silence_detect.realign_subtitles_after_cleanup` + `replace_subtitle_manager_entries` |
| UI | 去水词成功后二次确认；选「是」刷新字幕列表 |
| 测例 | `test_filler_silence_detect.py::TestRealignSubtitlesAfterCleanup` |

## 已完善（2026-08-07 A3 曲线变速接线）

| 项 | 说明 |
|----|------|
| UI | `_apply_speed_ramp` → `SpeedRamp.preset_preset` / `apply_speed_ramp_ffmpeg` / `reverse_clip_ffmpeg` |
| 线程 | FFmpeg 在后台；`QTimer.singleShot` 回主线程弹窗与写 `_clips` |
| 播放 | 解冻后画面/主音跟 `speed_ramp`（墙钟不变） |

## 已完善（2026-07-28 A1 拆 editor_module · 字幕面板）

| 项 | 说明 |
|----|------|
| 新模块 | `app/modules/lego/editor_subtitle_panel.py`：文字侧栏字幕 UI + CRUD + AI 生成 + 去水词 |
| 接线 | `EditorModule._make_text_tab` 委托 `build_subtitle_panel_section`；原 `_refresh_subtitle_list` 等方法保留薄包装 |
| 冻结区 | 未改 playback/exit-media/canvas-transform 等锁定符号；`frozen_zone_guard.py` 通过 |
| 验收 | 模块可 import；`test_edit_commands` / `test_filler_silence_detect` 无回归 |

## 调试备忘

- 临时 debug HTTP（`127.0.0.1:7777`）若仍残留，修完后应移除
- 崩溃日志：`app/_crash_report.log`
