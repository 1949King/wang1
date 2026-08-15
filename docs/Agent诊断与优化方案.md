# Agent 诊断与优化方案

> 调研日期：2026-08-08
> 范围：`app/core/agent_*` + `app/modules/lego/agent_workflow.py` + `ai_agent_panel.py`
> 状态：诊断完成，方案待执行（按优先级排序）

## 一、Agent 体系全景（7 个模块 + 2 个接线点）

```
用户操作
   │
   ▼
EditorModule (app/modules/lego/editor_module.py)
   ├── AiAgentPanelMixin (app/modules/lego/ai_agent_panel.py)
   │     └── _agent_dispatch → CapabilityDispatcher (app/core/capability_dispatcher.py)
   │           └── cap_id: "workflow.start" / "model.chat_with_fallback" / ...
   │
   └── EditorScheduler (app/core/editor_scheduler.py)
         └── get_agent_workflow() → AgentWorkflow 单例
               └── run_ai_clip() / get_ai_clip_status() / cancel_ai_clip()
```

### 链路 A（老）：AgentWorkflow —— 三智能体协作剪辑

```
AgentWorkflow (app/modules/lego/agent_workflow.py)
  ├── PlanAgent.analyze()         → DramaUnderstandingEngine.analyze_video()
  │                                  → DramaStructure（含 dialogues/scenes/plot_points）
  │                                  → EditPlan.tasks[]
  ├── ClipAgent.execute_batch()   → ffmpeg 逐段切割输出 clips
  └── ReviewAgent.review()        → ViralOptimizationEngine.predict_performance()
                                     → ReviewResult（打分）
```

接线点：`EditorScheduler.run_ai_clip()`（[editor_scheduler.py L976-L1009](file:///D:/拾光剪影/app/core/editor_scheduler.py#L976-L1009)）

### 链路 B（新）：AgentPipelineOrchestrator —— 全链路闭环

```
AgentPipelineOrchestrator.execute() (app/core/agent_pipeline_orchestrator.py)
  ├── AgentPipelineRouter.route()         → 生成业务线 / 剪辑业务线
  ├── (GENERATION) AIVideoGenerationPipeline → 生成片段
  ├── (EDITING)   素材剪辑 → 片段列表
  ├── preview_validation_loop              → 预览校验（人工确认闸门）
  ├── FiveDimensionScorer                  → 五维打分
  ├── EditingScriptGenerator               → 剪辑创意脚本
  └── CapabilityDispatcher(pipeline.execute_editing) → 精剪成片
```

接线点：`AiAgentPanelMixin._agent_dispatch("workflow.start")` → CapabilityDispatcher → [capability_handlers.py L262-L273](file:///D:/拾光剪影/app/core/capability_handlers.py#L262-L273)

### 链路 C：WorkflowManager —— 短剧全流程（事件驱动）

```
WorkflowManager (app/modules/lego/workflow_manager.py)
  EventBus: DRAMA_SELECTED → start_workflow() → WorkflowThread
    ├── _step_fetch_drama()    → DramaCrawler 抓取短剧素材
    ├── _step_ai_clip()        → AI 智能剪辑
    ├── _step_copywriting()    → 文案生成
    └── _step_publish_prepare()→ 发布准备
```

接线点：`capability_handlers.start_workflow()` + EventBus `DRAMA_SELECTED`

### 支撑模块（横向）

| 模块 | 角色 | 状态 |
|------|------|------|
| `agent_brain.py` | 左右脑突触学习引擎，Hebbian 强化 | 单例，被 orchestrator 的 reinforce_path 调用 |
| `agent_feedback_bridge.py` | 发布反馈 → MemoryStore + brain.learn_from_feedback | 单例，被 data_analyzer / editor_module 订阅 |
| `canvas_agent_runtime.py` | 画布 Agent 运行时 | 单例，被 character_management_module 调用 |
| `agent_pipeline_router.py` | 业务分流（无素材→生成 / 有素材→剪辑） | 被 orchestrator 调用 |

## 二、问题清单（按严重度排序）

### P0-1：Review 打分是"假数据"（占位值）

[agent_workflow.py L530-L551](file:///D:/拾光剪影/app/modules/lego/agent_workflow.py#L530-L551) 里，`ReviewAgent.review()` 喂给 `ViralOptimizationEngine` 的 8 个特征中 **6 个是写死占位值**：

| 特征 | 当前值 | 应为 |
|------|--------|------|
| `dialogue_density` | 固定 0.6 | ASR 文本量 / 时长（真实） |
| `emotion_variance` | 固定 0.5 | DialogueSegment.emotion 方差（真实） |
| `conflict_intensity` | 固定 0.6 | 冲突词命中率（真实） |
| `climax_position` | 固定 0.7 | 高潮段位置比例（真实） |
| `visual_attractiveness` | 固定 70.0 | 帧统计 / 元数据（真实） |
| `audio_quality` | 固定 75.0 | 音频响度/信噪比（真实） |
| `subtitle_quality` | 固定 70.0 | 字幕覆盖率（真实） |
| `hook_quality` | `_estimate_hook_quality()` | ✅ 已真实 |

后果：`overall_score`、完播率预测、点赞/评论率全是占位值驱动的假结果，`uses_placeholder_features=True` 直接暴露。

**已有可复用能力（不用新写）**：
- [content_classifier.py L145-L239](file:///D:/拾光剪影/app/core/ai/content_classifier.py#L145-L239) `UniversalFeatureExtractor` → 8 维真实特征（含 dialogue_density/emotion_variance/conflict_intensity）
- `DramaStructure.dialogues` → 已在 `PlanAgent.analyze()` 拿到，但**没传进 `EditPlan`**，ReviewAgent 拿不到

### P0-2：FiveDimensionScorer 同样吃基线值

[five_dimension_scorer.py L182-L215](file:///D:/拾光剪影/app/core/five_dimension_scorer.py#L182-L215) `extract_features_from_clip`：`quality_scores` 缺失时全部维度回落到 **SMART_BASELINE=70**。链路 B 打分同样失真，`estimated_dims` 会全量标记。

### P1-3：三链路职责重叠

三条"启动→剪辑→(审核/发布)"链路并存：

| 链路 | 入口 | 职责 | 状态 |
|------|------|------|------|
| A. AgentWorkflow | `EditorScheduler.run_ai_clip()` | 单视频 Plan→Clip→Review 协作剪辑 | 老入口，UI 未直接调用 |
| B. AgentPipelineOrchestrator | `_agent_dispatch("workflow.start")` | 素材分流→业务线→打分→脚本→精剪 | 正式全链路 |
| C. WorkflowManager | `DRAMA_SELECTED` 事件 | 抓剧→AI剪辑→文案→发布 | 短剧产品流程 |

知识库 [09-tool-registry-design](file:///D:/拾光剪影/docs/knowledge/INDEX.md#L20) 已记录"4 套→1 套"收敛计划，但 Agent 层尚未执行。

### P1-4：Agent 无自动化测试

`app/tests/` 无任何 agent 链路测试。后续改动（打通真实特征、收敛链路）无回归保护。

## 三、执行计划（三步）

### 第一步：打通真实打分特征（P0-1 + P0-2）

1. `EditPlan` 增加 `analysis` 已有字段，`PlanAgent.analyze()` 把 `drama.dialogues`（精简为 start/end/text/emotion）存入 `edit_plan.analysis["dialogues"]`
2. `ReviewAgent.review()` 从 `plan.analysis` 取 dialogues，调 `UniversalFeatureExtractor.extract()` 得到真实 8 维特征，映射进 `VideoFeatures`（dialogue_density/emotion_variance/conflict_intensity 等）
3. 无 dialogues（fallback 计划）时保持原占位逻辑 + `uses_placeholder_features=True`；有真实数据时置 `False`
4. `FiveDimensionScorer.extract_features_from_clip` 增加真实特征注入（音频响度/时长合理性已可从 metadata 取）

**成功标准**：有 ASR 结果的视频，ReviewResult.uses_placeholder_features=False，打分随内容变化。

### 第二步：收敛链路边界（P1-3）

- 明确职责边界（本次只加边界注释，不改调用行为）：
  - 链路 B（Orchestrator）= **唯一正式全链路**（素材→打分→脚本→精剪）
  - 链路 A（AgentWorkflow）= 轻量单视频 AI 剪辑专用路径（`EditorScheduler.run_ai_clip` 保留老 UI 兼容）
  - 链路 C（WorkflowManager）= 短剧产品流程（抓剧→剪辑→文案→发布），不承担素材精剪
- `EditorScheduler.run_ai_clip()` 保留，内部加注释标注与 Orchestrator 的边界
- `capability_handlers.start_workflow()` 保持走 WorkflowManager（对外能力名不变）
- 冻结区外无破坏性改动

### 第三步：补 Agent 测试（P1-4）

- `tests/unit/test_agent_workflow_review.py`：ReviewAgent 有 dialogues → uses_placeholder_features=False；无 dialogues → True
- `tests/unit/test_pipeline_router.py`：无素材→GENERATION，有视频素材→EDITING

## 四、风险与边界

- **最小侵入**：不删既有占位逻辑，只在有真实数据时替换；无数据时保持降级
- **不碰冻结区**：`editor_scheduler` 音画纠偏 ~280ms、`EditorModule._clips` 真值源等不动
- **ASR 耗时**：`UniversalFeatureExtractor` 依赖的 dialogues 来自 PlanAgent 已完成的 ASR，无新增耗时
