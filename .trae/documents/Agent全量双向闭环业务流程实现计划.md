# Agent 全量双向闭环业务流程实现计划

## Context（背景）

用户给出了最终定稿的完整业务流程：Agent 读取导入栏 → 智能分流（AI生成/AI剪辑）→ 预览校验 → 五维打分 → 剪辑脚本 → 精修成片 → 运营回流 → 双向闭环。

**现有基础**：已建好 CapabilityDispatcher（统一调用层）+ MemoryStore（长期记忆）+ AgentFeedbackBridge（反馈桥）。

**缺口**：缺少业务分流器、五维打分、AI生成编排、预览校验闭环、剪辑脚本生成、总编排器。

**目标**：新建 7 个 core 文件 + 修改 6 个既有文件，实现完整双向闭环。

---

## 架构对齐

```
Agent → CapabilityDispatcher → AgentPipelineOrchestrator
  ├─ AgentPipelineRouter（业务分流）
  ├─ AIVideoGenerationPipeline（业务线1：生成→初检→入轨）
  ├─ AgentWorkflow（业务线2：复用既有 PlanAgent→ClipAgent→ReviewAgent）
  ├─ PreviewValidationLoop（预览校验闭环）
  ├─ FiveDimensionScorer（五维打分+D级剔除）
  ├─ EditingScriptGenerator（剪辑创意脚本）
  └─ 后置：workflow.start → account.publish → DataAnalyzer → AgentFeedbackBridge
```

---

## 新建文件（7 个，全部在 app/core/）

### 1. `app/core/agent_pipeline_router.py` — 业务分流器
- `RouteDecision` 枚举（AI_GENERATION / AI_EDITING / FALLBACK）
- `PipelineInput` dataclass（has_material / material_paths / creative_brief / editor_ref）
- `AgentPipelineRouter` 单例：`route()` 读取导入栏判断走哪条业务线

### 2. `app/core/five_dimension_scorer.py` — 五维打分系统
- `ScoreGrade` 枚举（S≥90 / A≥80 / B≥70 / C≥60 / D<60剔除）
- `ClipFeatures` dataclass（五维特征 0-100）
- `FiveDimensionScorer` 单例：
  - 权重：画面质量(25%) + 高光叙事(25%) + 文案匹配(20%) + BGM适配(15%) + 镜头时长(15%)
  - `score()` 单镜头打分 / `score_batch()` 批量+D级剔除

### 3. `app/core/ai_video_generation_pipeline.py` — AI视频生成业务编排
- `CreativeDecomposer`：大纲→剧本→关键词→提示词（复用 ai_engine.chat_with_fallback）
- `AICardGenerator`：AI抽卡生成多段画面（调用 VideoGenerationClient）
- `GenerationInspector`：后台初检（穿模/手部畸形/逻辑混乱），不合格→回溯重写提示词
- `AIVideoGenerationPipeline` 单例：`run()` 完整业务线1闭环

### 4. `app/core/ai/video_generation_client.py` — AI视频生成客户端
- `VideoGenerationClient` 单例：`generate()` 统一接口
- 内置 `_call_local_fallback()` 本地占位生成（保证无API密钥时流程可演示）

### 5. `app/core/preview_validation_loop.py` — 预览校验闭环
- `ValidationIssue` / `ValidationResult` dataclass
- `PreviewValidationLoop` 单例：`validate()` 预览→质检→反馈→重生成
- 检查项：镜头连续性/音画同步/视觉瑕疵

### 6. `app/core/editing_script_generator.py` — 剪辑创意脚本生成
- `EditingScript` dataclass（镜头顺序/转场/滤镜/BGM/节奏）
- `EditingScriptGenerator` 单例：`generate()` 根据高分镜头生成最优脚本 + `to_edit_commands()` 转换为可执行指令

### 7. `app/core/agent_pipeline_orchestrator.py` — 总编排器
- `AgentPipelineOrchestrator` 单例：`run_full_pipeline()` 串联全链路
- 分支A：AIVideoGenerationPipeline → 预览 → 打分 → 脚本 → 精修
- 分支B：AgentWorkflow → 打分 → 脚本 → 精修
- 后置：workflow.start → account.publish → DataAnalyzer → 反馈桥

---

## 修改文件（6 个，全部增量修改）

### 1. `app/core/capability_dispatcher.py`（+1行）
- `CapabilityCategory` 枚举新增 `PIPELINE = "pipeline"`

### 2. `app/core/capability_handlers.py`（+1类+8注册）
- 新增 `AgentPipelineCapabilityHandlers` 类（8个方法）
- `register_builtin_handlers()` 末尾注册 8 个新能力：
  - `agent.route_pipeline` / `agent.run_generation_pipeline` / `agent.run_editing_pipeline`
  - `agent.run_full_pipeline` / `agent.score_five_dimension` / `agent.validate_preview`
  - `agent.generate_editing_script` / `agent.feed_back_issue`

### 3. `app/modules/lego/core.py`（+5行 EventType）
- 追加：`PIPELINE_ROUTED` / `GENERATION_INSPECTION_FAILED` / `PREVIEW_VALIDATION_FAILED` / `SCORING_COMPLETED` / `EDITING_SCRIPT_GENERATED`

### 4. `app/core/agent_feedback_bridge.py`（+1方法+4订阅）
- 新增 `submit_quality_issue(issue_type, details)` 统一质检问题入口
- 订阅 4 个新 EventType 自动入记忆

### 5. `app/core/ai/prompt_templates.py`（+6套模板）
- `creative_outline` / `script_from_outline` / `keywords_from_script` / `prompt_from_keywords` / `generation_inspection` / `editing_script_from_scores`

### 6. `app/modules/lego/editor_module.py`（3处增量）
- `_apply_agent_command` 新增 7 个 action 分支（run_full_pipeline/run_generation/run_editing/score_clips/validate_preview/generate_editing_script/feed_back_issue）
- Agent 面板快捷指令追加 3 个按钮（🚀全链路/🎬AI生成/✂️AI剪辑）
- 订阅 4 个新 EventType 显示反馈提示

---

## 双向回流闭环

| 问题类型 | 触发点 | 回流方式 |
|---------|--------|---------|
| AI生成BUG | GenerationInspector | `submit_quality_issue("generation_bug", ...)` |
| 预览断层 | PreviewValidationLoop | `submit_quality_issue("preview_gap", ...)` |
| 精剪瑕疵 | EditingScriptGenerator | `submit_quality_issue("edit_flaw", ...)` |
| 打分偏差 | FiveDimensionScorer | `submit_quality_issue("scoring_deviation", ...)` |
| 运营数据 | DataAnalyzer（既有） | `submit_feedback({...})`（已接入） |

所有问题 → MemoryStore(category="feedback") → learn_from_feedback → AGENT_FEEDBACK_AVAILABLE → 下次 Agent 调用注入历史经验

---

## 实施顺序（13步）

1. 修改 `capability_dispatcher.py` + `core.py` + `prompt_templates.py`（纯增量基础）
2. 修改 `agent_feedback_bridge.py` 加 submit_quality_issue
3. 新建 `five_dimension_scorer.py`（独立可测）
4. 新建 `ai/video_generation_client.py`（独立）
5. 新建 `agent_pipeline_router.py`
6. 新建 `ai_video_generation_pipeline.py`
7. 新建 `preview_validation_loop.py`
8. 新建 `editing_script_generator.py`
9. 新建 `agent_pipeline_orchestrator.py`
10. 修改 `capability_handlers.py` 加 8 个能力注册
11. 修改 `editor_module.py` 加 action 分发 + 按钮
12. py_compile + frozen_zone_guard 验证
13. 启动测试

---

## 验证方案

1. **静态验证**：py_compile 13 个文件 + `frozen_zone_guard.py`
2. **启动验证**：`python main_qt6.py` 无报错，Agent 面板显示新按钮
3. **功能验证**：
   - 点击"🚀 Agent全链路" → 走完整闭环
   - 无素材时走AI生成业务线（本地占位生成）
   - 有素材时走AI剪辑业务线
   - Agent 面板显示打分结果 + 反馈提示
4. **回归验证**：既有剪辑功能 + Agent 快捷指令不变

---

## 风险控制

- **AI生成API不可用**：VideoGenerationClient 内置本地占位生成
- **LLM不可用**：CreativeDecomposer 降级到模板
- **UI阻塞**：orchestrator 通过 invoke_async 异步调用
- **冻结区**：editor_module.py 修改点远离 FROZEN 区，改后跑 frozen_zone_guard
- **向后兼容**：既有 15 个能力 + AgentWorkflow 完全保留
