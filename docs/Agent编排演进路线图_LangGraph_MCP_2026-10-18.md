# Agent 编排演进路线图：LangGraph / 多 Agent / MCP 工具化（远期项 e7 · 2026-10-18）

> 结论先行：**LangGraph 迁移 = 不做**（现状已达成蓝图阶段一，迁移违「不推翻
> 原有架构」红线且无近期收益）；**MCP 工具化 = 已落零风险第一步**（能力目录
> → MCP tools 清单导出，`mcp_tool_manifest.py`），后两步按需触发。

## 1. 现状对账（蓝图 §6.8.5/6.8.6 vs 代码）

| 蓝图设想 | 现状 | 位置 |
|---|---|---|
| 主控 = LangGraph | 🟢 **等价能力已在役**：`agent_loop.py` 多轮 think-act（观察→规划→行动→观察），LLM 工具调用解析 → `ACTION_TO_CAPABILITY` 映射 → `capability_dispatcher.invoke` 执行 → `require_approval` 闸门。蓝图原则「先单主控 Agent+多工具跑通」= **已达成** | `app/core/agent_loop.py`、`agent_action_registry.py` |
| 双 Agent（UniVA Plan-and-Act） | 🟢 雏形更进一档：**三 Agent 流水线** PlanAgent→ClipAgent→ReviewAgent（含 WorkflowState/ReviewResult），经 `editor_scheduler.get_agent_workflow()` 接入 `run_ai_clip` **活路径**（非孤儿原型） | `app/modules/lego/agent_workflow.py` |
| 工具协议 MCP Server | 🔴 零实现、零预留 → **本次落第一步**：`app/core/mcp_tool_manifest.py` 把能力目录（单一事实源 `CAPABILITY_ROWS`）导出成 MCP `tools/list` 形状（name/description/inputSchema + readOnlyHint/destructiveHint 注解按 effect 诚实映射）；产物 `data/mcp_tool_manifest.json`（gitignore，按需再生）；守卫 `MCPMANI` | 本文件 |
| 隐藏画布 = Agent 共享记忆/黑板 | 🟡 零件在位：循环窗口压缩（`check_agent_loop_context` 在册）、左右脑路由/学习回路（`agent_brain`）、分镜记忆（`storyboard_memory`）、抽卡账本。统一「黑板」= 远期，无近期触发 | 各 core 模块 |
| 策略分档（小白 reactive / 专业 deliberative） | 🟡 协作模式确认闸门统一（`needs_confirmation`），未随档位分策略；依赖小白模式用户量，维持观察 | `agent_policy` |

## 2. LangGraph 迁移裁决：❌ 不做（记录理由，防止反复评估）

1. **阶段原则已满足**：蓝图明写「先单主控+多工具跑通，再拆多 Agent」——
   现状单主控在役、三 Agent 流水线也有活路径，LangGraph 解决的问题
   （状态图编排、断点续跑、human-in-the-loop）**均已由自研实现覆盖**；
2. **红线冲突**：迁移 = 重写 agent_loop 编排层，违反 `.trae/rules`
   「不推翻原有逻辑」与 §2「可回退」；
3. **成本错配**：单人单机开发者，langgraph+langchain 依赖树庞大，
   版本漂移维护成本 > 收益；离线环境（素材不出域红线）还需验证依赖可离线安装。

**重评触发条件**（写死，避免口头反复）：出现「跨会话断点续跑」或「多 Agent
并行编排」的真实需求，且自研 `pipeline_jobs`/`AgentWorkflow` 扩展不动时。

## 3. MCP 工具化三步路径（第一步已落）

| 步 | 内容 | 状态 | 触发条件 |
|---|---|---|---|
| 1 | 工具清单导出：能力目录 → MCP tools 形状 JSON（注解含 effect/paid/readOnly/destructive） | ✅ **本次落地**（守卫 MCPMANI 锁形状与目录一致性） | — |
| 2 | 结构化参数 schema：为高频能力补 `inputSchema` 字段表（现泛型 object + 诚实声明） | ⏳ 按需 | 外部 MCP 客户端真要调用某能力时，补该能力的 schema（增量，不批量） |
| 3 | MCP server 接入：stdio server 包装 `capability_dispatcher.invoke`（复用 require_approval 闸门），依赖 `mcp` SDK | ⏳ 远期 | 外部生态接入需求出现（如用外部 Agent 操作编辑器）；届时 server 只读消费清单，**调用方零改动** |

**纪律**：第 3 步落地前，`/host` 端点 + 能力目录仍是唯一工具面；
清单是「投影」不是「新真相源」——真相源永远是 `agent_capability_catalog`，
守卫 `MCPMANI` ② 保证两者不漂移。

## 4. 本次交付物

- `app/core/mcp_tool_manifest.py`（纯 core 模块，零新依赖，导出绝不抛异常）
- `_verify/check_mcp_manifest.py`（守卫 `MCPMANI`：形状/完整性/注解诚实/往返）
- 本路线图（§6.9「远期观察」行 Agent/MCP 部分的裁决记录）
