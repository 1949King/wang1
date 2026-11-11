# Agent 编排原语与「模型不吐指令」根因（2026-10-31）— 从 MEMORY.md 拆出

## 工作流蓝图（画布 0.3.34）

- 🔴 **编排原语 = 蓝图（blueprint）**：`canvas_blueprint.py` ↔ `blueprintLayout.ts` + `applyBlueprint.ts` ↔ `AgentPanel.tsx case "applyBlueprint"`。
- **蓝图 schema 无 x/y** ⇒ 坐标本地算；落图只走 store 三件套 `addNode/updateNodeData/onConnect` ⇒ `store.ts` 零改动。
- 🔴 **标准链必须过端口类型校验**：`shotlist` 只吃 `video`/`grid`，**不吃 `image`**。**终点不同 ⇒ 路径不同**（`CANONICAL_PATHS` 7 条）。
- 🔴 **冻结区 `canvas-magnetic-intent` 含 `canvasVersion.ts` + `NodePalette.tsx`** ⇒ 改版本号或调色板后**必须 `--update` 重锁**。
- 主程序版本与画布版本刻意不同步；主版本线被并行线占用时**不抢号**。

## 「模型只吐计划不吐 JSON」根因

- 🔴 **提示词必须和真实审批机制对齐**：审批在策略引擎 + 前端确认框（`agent_policy.decide()` → `require_approval` → `askConfirm`）⇒ 模型在文字里等确认 = 多余，直接导致不出 JSON。协作段写「确认由系统弹框，别停下来等点头」。
- 🔴 **赌模型会听话 = 赌**。后端必须有兜底 `ensure_workflow_blueprint()`：已给蓝图保留；零散 addNode 换整张链；只给文字按标准路径合成。单步需求**绝不铺**；Plan 模式不合成。
- 🔴 **system 段序 = 注意力预算**：角色 → 模式 → **契约** → 动作清单（附录）。
- 真机验证：`_build_canvas_fast_messages()` → POST 本机 Ollama `/api/chat` → `parse_canvas_tools` → `normalize_canvas_tools` → `ensure_workflow_blueprint`（`qwen3.5:4b` 可用）。
- 🔴 后端补的环节也要带真提示词：「补齐环节」与「合成整张图」共用 `_STAGE_PROMPT_TEMPLATES`，一个出口不分叉。**别让「正常操作」混进 `problems`**（走 `inserted` 字段）。
