# 精剪能力与 Agent 闭环迭代计划

> 范围：P0（精剪接线） + P1（读能力） + P2（闭环增强） + 3D 导演台全部迭代 + Agent 长期精剪闭环。
> 原则：最小侵入、复用既有原语、不破坏现有链路、可回退。

---

## 0. 现状结论（已核实）

**引擎与 UI 原语几乎都已就绪，唯一缺的是"接线"与"对齐"。**

- 剪辑 UI 原语（EditorModule）已具备：`move_clip(3010)`、`set_clip_speed(2915)`、`add_keyframes_to_clip(2746)`（批量关键帧+合并）、`add_keyframe_channel_to_clip(2790)`、`get_keyframes_for_clip(2808)`。
- 对话 Agent 白名单 [agent_action_registry.py](file:///d:/拾光剪影/app/core/agent_action_registry.py) 仅 17 个动作，且提示词里明确"禁止 move_clip / set_keyframes"。
- 执行层 [capability_handlers.py](file:///d:/拾光剪影/app/core/capability_handlers.py) 的 `EditorCapabilityHandlers` 尚无 `set_keyframes`/`set_clip_properties`。
- 3D 导演台前端 `riggedHumanoid.ts` 已含关键帧+缓动采样（`MotionPreset`/`easeFn`/`sampleMotion`），`shotCamera.ts` 已含运镜模板（推拉摇移 dolly/crane 等），`stage3dControlNet.ts` 已输出 depth/normal/openpose。缺口在：poseTrack 无 bezier/easing 曲线、无 AI 自动分镜机位、无按分镜批量生成回填、两端动作清单分裂。
- 素材读能力（`get_media`/`inspect_media`）在 `OPENTAKE_GAP_ROWS` 中为 `missing`；底层已有 [ai_editing_assistant.py](file:///d:/拾光剪影/app/core/ai_editing_assistant.py)（场景/情绪/剪辑建议）与 [ai/audio_emotion_analyzer.py](file:///d:/拾光剪影/app/core/ai/audio_emotion_analyzer.py)（音频情绪）。

---

## 1. Workstream 1（P0）：精剪能力接线

**目标**：让 Agent 能通过白名单触发 移动/变速/关键帧。

### 1.1 动作白名单 [agent_action_registry.py](file:///d:/拾光剪影/app/core/agent_action_registry.py)

`_AGENT_ACTION_ROWS` 追加 4 行（沿用现有"别名"写法）：

```
("move_clip",      "safe", None,                        "移动片段到新时间点（本地）"),
("change_speed",   "safe", "editor.set_clip_properties", "变速/倒放（写 speed/reverse）"),
("add_keyframe",   "safe", "editor.set_keyframes",      "写入关键帧（单点或批量）"),
("set_keyframes",  "safe", "editor.set_keyframes",      "批量写入关键帧+插值+缓动"),
```

决策：`move_clip` 走**本地 action**（无 capability），沿用 `trim_clip`/`duplicate_clip` 的"本地、无 capability"既有模式；`change_speed`→`editor.set_clip_properties`，`add_keyframe`/`set_keyframes`→`editor.set_keyframes`。

同步修改：
- `OPENTAKE_GAP_ROWS`：`set_keyframes` 由 `missing`→`ok`，`set_clip_properties` 由 `partial`→`ok`。
- `build_clipskills_layers_block()` L98 删掉"不要输出 add_clip/move_clip/set_keyframes/import_media"。
- `build_agent_actions_help_block()` L109 删掉"禁止生成 add_clip / move_clip / set_keyframes…"，改为新动作的参数说明（见下）。

### 1.2 新增 capability handler [capability_handlers.py](file:///d:/拾光剪影/app/core/capability_handlers.py)

在 `EditorCapabilityHandlers` 内新增两个方法（签名 `(self, req) -> CapabilityResult`，与现有分裂/滤镜一致）：

- `set_clip_properties`：`clip_id` 解析后，`speed` 走 `editor.set_clip_speed(clip_id, speed)`；`reverse`/`volume`/`scale`/`opacity` 走片段 dict 直接 `clip[k] = v` 写入并 `_sync_kernel_timeline()`。
- `set_keyframes`：入参 `params.keyframes`（list[dict]），归一化字段名 `property→prop`、`time→time_offset`、保留 `value/easing/interpolation`，然后一次调用 `editor.add_keyframes_to_clip(clip_id, normalized)`。

在 `register_builtin_handlers()` 注册：

```
dispatcher.register("editor.set_clip_properties", CapabilityCategory.EDITOR, editor_handlers.set_clip_properties, "设置片段属性（变速/音量/缩放等）")
dispatcher.register("editor.set_keyframes",       CapabilityCategory.EDITOR, editor_handlers.set_keyframes,       "批量写入关键帧（含插值/缓动）")
```

> 实现时先完整读 `add_keyframes_to_clip`（L2746-2806）与 `_on_keyframe_clicked`/`_interpolate_clip_keyframes` 确认关键帧 dict 精确 schema（初步为 `{prop, time_offset, value}`），不臆测字段名。

### 1.3 本地调度 [ai_agent_panel.py](file:///d:/拾光剪影/app/modules/lego/ai_agent_panel.py)

在 `_apply_agent_command()` 末尾（`canvas_open` 分支之后、兜底 return 之前）追加 3 个分支：

- `move_clip`：`_resolve_agent_clip(params)` → `new_start_time`（必填，`float`）→ `self.move_clip(clip_id, new_start_time)`（该方法已含撤销/音画联动/内核同步）。`new_track` 暂不支持，若传入返回提示"跨轨移动暂未开放"。
- `change_speed`：解析 clip → `speed=float(params.speed)`、`reverse=bool(params.reverse)` → `self.set_clip_speed(clip_id, speed)`；`reverse` 写 `clip["reverse"]`。
- `add_keyframe` / `set_keyframes`：解析 clip → 归一化 keyframes → `self.add_keyframes_to_clip(clip_id, keyframes)`。

### 1.4 策略白名单 [agent_policy.py](file:///d:/拾光剪影/app/core/agent_policy.py)

`_EDITOR_ACTION_EFFECTS` 追加：

```
"move_clip":     (EFFECT_CANVAS_WRITE, False),
"change_speed":  (EFFECT_CANVAS_WRITE, False),
"add_keyframe":  (EFFECT_CANVAS_WRITE, False),
"set_keyframes": (EFFECT_CANVAS_WRITE, False),
```

---

## 2. Workstream 2（P1）：补齐"读"能力

**目标**：让 Agent 能读到素材语义/情绪/节奏，摆脱盲打。

### 2.1 新增 `editor.inspect_media` capability

[capability_handlers.py](file:///d:/拾光剪影/app/core/capability_handlers.py) 的 `EditorCapabilityHandlers` 新增 `inspect_media(req)`：
- 入参 `file_path` 或 `clip_id`。`clip_id` 时经 `editor.agent_get_timeline_context()` / 片 dict 解析真实路径。
- 调 [AIEditingAssistant](file:///d:/拾光剪影/app/core/ai_editing_assistant.py) 的 `SceneAnalyzer.analyze_scenes(path)` → 场景类型/情绪/分镜/置信度；调 [AudioEmotionAnalyzer](file:///d:/拾光剪影/app/core/ai/audio_emotion_analyzer.py) 的 `audio_emotion_for_dialogues(path)` → 音频情绪/节奏。
- 返回结构化 `{shots:[{scene_type, emotion, duration, confidence}], audio_emotion, suggestions}`。

> 风险/决策：这类推理较重，必须不在 UI 主线程。若 `CapabilityDispatcher.invoke` 已在后台线程执行则直接同步调用；否则套用 `project_agent_host._run_on_ui` 同理的线程切换，或返回 `EFFECT_READ` 由调用方异步排队。实现时先确认 dispatcher 执行线程模型。

### 2.2 注册 + 白名单 + 提示词

- `register_builtin_handlers`：`dispatcher.register("editor.inspect_media", CapabilityCategory.EDITOR, editor_handlers.inspect_media, "读取素材语义/情绪/节奏")`。
- `agent_action_registry`：追加 `("inspect_media", "safe", "editor.inspect_media", "读取素材元信息/情绪/节奏")`；`OPENTAKE_GAP_ROWS` 的 `get_media`/`inspect_media` 标记为 `ok`。
- `agent_policy`：`"inspect_media": (EFFECT_READ, False)`。
- 提示词：补充"需要判断镜头/情绪/节奏时先 inspect_media"。

---

## 3. Workstream 3（P2）：闭环增强 —— 精剪问题局部修复

**目标**：预览问题不再只能"整段重新生成"，切点突兀/节奏问题可触发精剪微调。

### 3.1 扩展 [preview_validation_loop.py](file:///d:/拾光剪影/app/core/preview_validation_loop.py)

- `PreviewIssue.issue_type` 已支持枚举扩展，新增 `cut`(切点突兀)、`pace`(节奏)、`transition`(衔接硬)（现有 gap/drift/desync/corrupt/other 保留）。
- 新增方法 `resolve_issue(clip, issue_type, strategy="fine_tune")`：`fine_tune` 分支把问题映射为本地编辑动作（见 3.2）；`regenerate` 分支回退到现有 `request_regenerate`。返回执行结果，不改动 `submit_preview_issue` 原语义。

### 3.2 新增 `pipeline.resolve_preview_issue` capability

[capability_handlers.py](file:///d:/拾光剪影/app/core/capability_handlers.py) `PipelineCapabilityHandlers` 新增 `resolve_preview_issue(req)`，`issue_type` → 动作映射：

- `cut`/`transition` → `editor.agent_apply_transition(clip, "fade", 0.5)`（衔接）
- `pace` → `editor.set_clip_speed(clip_id, 1.2)` 或 trim
- `desync` → trim/对齐
- 其它 → 回退 `preview_validation_loop.request_regenerate`

注册 `pipeline.resolve_preview_issue`；`agent_action_registry` 追加 `("resolve_preview_issue", "safe", "pipeline.resolve_preview_issue", "预览问题精剪修复")`；`agent_policy` 记为 `EFFECT_CANVAS_WRITE`。

---

## 4. Workstream 4：3D 导演台迭代（全部）

### 4.1 骨骼动画精细化（poseTrack 加曲线）

- 前端 [Stage3D.tsx](file:///d:/拾光剪影/vendor/shiguang-canvas/src/Stage3D.tsx) `ScenePersist.poseTracks` 关键帧项增加 `easing`、`bezierC1/C2`（对齐后端 `keyframe_animation.py` 的 `InterpolationType`/`EasingType` 枚举）。
- [riggedHumanoid.ts](file:///d:/拾光剪影/vendor/shiguang-canvas/src/riggedHumanoid.ts) `sampleMotion`（L783-860）采样时读取 per-keyframe `easing` 覆盖默认 `easeFn`，实现逐关节曲线插值。
- 后端：让 `editor.set_keyframes`（WS1）的结果可经 SSE `task.create` 推送到画布 pose track，打通"脑→手"。

### 4.2 相机路径规划（AI 分镜机位）

- 复用 [shotCamera.ts](file:///d:/拾光剪影/vendor/shiguang-canvas/src/shotCamera.ts) 已有运镜模板（push-in/pull-out/pan/tilt/dolly/crane）。
- 后端：`canvas_aigc.storyboard_breakdown` 输出分镜表 → 新增映射函数把每镜 `shot`(景别) 转为 `StageCamera`（position/lookAt/shotSize/fov）+ 运镜 `pathPoints`，经画布桥推送。实现 AI 自动摆机位而非手动。

### 4.3 AIGC 与时间打通（按分镜批量生成 + 回填时间轴）

- [canvas_aigc.py](file:///d:/拾光剪影/app/core/canvas_aigc.py) 新增 `generate_storyboard_batch(shots, ...)`：遍历分镜 → 逐镜调 `generate_image_openai_compatible`/`generate_video_via_host` → 结果落到 inbox → 通过 [canvas_bridge.py](file:///d:/拾光剪影/app/core/canvas_bridge.py) 现有 `emit_canvas_to_editor`/`ingest_local_file` 回填到编辑器时间线，形成"文案→分镜→生成→入轨"闭环。
- 保留单条生成旧路径与 fallback（生成失败不影响其它镜）。

### 4.4 Agent 跨域指令统一（单一 ACTION_REGISTRY）

- 现状：后端 `agent_action_registry._AGENT_ACTION_ROWS` 与前端 [AgentPanel.tsx](file:///d:/拾光剪影/vendor/shiguang-canvas/src/AgentPanel.tsx) `executeRemoteTask` switch（20+ case）两套清单。
- 方案（最小）：后端新增 `canvas.list_actions` capability/端点，输出统一动作清单（action → 描述 → 执行域）；`AgentPanel.tsx` 的 `executeRemoteTask` 分发表由该清单驱动的映射表承载，**保留各 store 具体变更逻辑不动**，只把"action→执行分支"的注册表抽成单一来源。
- 阶段化：先在后端出"只读"统一清单供前端消费，后续再逐步把前端 switch 改为查表。（前端改动需 `vendor/shiguang-canvas` 重新构建，见验证。）

---

## 5. Workstream 5：Agent 长期精剪闭环（对话式精修）

**目标**：一次对话完成"第3段衔接太硬，加 0.5s 缓动转场，BGM 12s 压到 30%"。

前置依赖：WS1(白名单/关键帧) + WS2(读能力) + WS4.1(缓动)。

### 5.1 音量包络关键帧

- 把 `volume`/`gain` 纳入关键帧通道（复用 `add_keyframes_to_clip`），并在音频混音/导出路径按时间采样音量包络。
- 落地前需定位音频混音入口（editor 预览 `_collect_preview_effects` 或 MLT 引擎），单独调研该路径后实现。**此子项暂列为"待定位后再编码"。**

### 5.2 多步组合指令执行

- `agent_brain` 支持单轮对话产出多条 action（`add_transition` + `set_keyframes(volume 包络)` + `change_speed`）顺序执行，复用 `_apply_agent_command` 循环 + 危险动作二次确认。
- 目标路径：`project_agent_host.project_agent_chat` 已具备分段产出/执行骨架，在其上扩多 action 提交即可，不推翻。

### 5.3 缓动入预览

- 把 `keyframe_animation.py` 的 easing/bezier 接入预览插值 `_interpolate_clip_keyframes`，使 Agent 写入的缓动关键帧在预览即时生效。

---

## 6. 关键决策汇总

1. `move_clip` 走本地 action，不新增 capability（对齐 `trim_clip`/`duplicate_clip`）。
2. `change_speed`→`editor.set_clip_properties`；`add_keyframe`/`set_keyframes`→`editor.set_keyframes`。
3. 关键帧 dict 目标 schema `{prop, time_offset, value, easing?, interpolation?}`（easing 存储但当前预览若不支持则透传，由 5.3 落地生效）。
4. 新 handler 复用 EditorModule 已公开原语，不新增 `agent_*` 包装（`move_clip`/`set_clip_speed`/`add_keyframes_to_clip` 已存在）。
5. 跨域指令统一采用"后端只读清单 + 前端查表"渐进式，不一次性重写前端 switch。
6. 前端 TS 改动后需重新构建 `vendor/shiguang-canvas`。

---

## 7. 验证步骤

- **Python 静态**：`python -m py_compile` 覆盖改动的 `agent_action_registry.py`、`capability_handlers.py`、`agent_policy.py`、`ai_agent_panel.py`、`preview_validation_loop.py`、`canvas_aigc.py`。
- **白名单一致性自检**：启动时 `register_builtin_handlers` 已有"action↔capability 告警"，确认无 `映射到未注册 capability` 告警。
- **动作枚举**：`agent_brain.sync_from_dispatcher` 后，`list_project_tools` / `list_capabilities` 能枚举到新 capability；`list_opentake_gaps()` 不再有 `missing`。
- **手动链路**（P0）：启动后对话"把第2段加速到1.5倍 / 给第1段加关键帧 / 把第3段移到10秒"，确认时间线真实变化、可撤销、无报错。
- **读能力**（P1）：对话"分析这个素材的情绪和镜头"，返回结构化结果且不卡 UI。
- **闭环**（P2）：制造切点问题，确认不走整段重生成而走上 `resolve_preview_issue` 精剪分支。
- **3D**（WS4）：`vendor/shiguang-canvas` 重新构建后，画布角色关键帧带缓动、AI 分镜自动摆机位、分镜批量生成回填时间轴、前端动作清单与后端一致。
- **冻结区**：改完跑 `python scripts/frozen_zone_guard.py`，确认未触碰冻结符号。

---

## 8. 交付说明模板（每阶段）

每阶段完成需说明：改了什么文件、验证了什么、残余风险（尤其 WS5 音频包络待定位、WS4 前端构建兼容性）。