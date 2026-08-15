# 13 — Agent Skill / 多集记忆（Dify 对照，不部署 Dify）

> 学 Dify 的：**Skill 分层、提示词版本感、会话/项目记忆**。  
> **不**把剪辑主路径绑到 Dify 服务；执行仍走本机 `CapabilityDispatcher` → `_clips`。  
> 参考：Dify 工作流/知识库 UX · ClipSkills「决策知识 vs 执行适配」· [`09-tool-registry-design.md`](09-tool-registry-design.md)

## ClipSkills 式三层（写入 Agent 系统提示）

| 层 | 职责 | 本仓库落点 |
|----|------|------------|
| **L0 决策** | 要不要剪、剪哪里、先建议还是直接改 | Plan / 协作 B / 自主 C（`agent_policy`）；`suggest_cleanup`；B 删除二次确认，C 跳过 |
| **L1 知识** | 漫剧节奏、去水词、竖屏习惯（软件无关） | `memory_store` learned_rule / feedback；长期记忆块 |
| **L2 执行** | 落到具体 NLE API | 对话 action ↔ `ACTION_TO_CAPABILITY` ↔ Dispatcher / 本地 UI |

模型被要求：**先想 L0，再用 L2 的合法 action**；禁止发明未开放的 L2（如 `add_clip`）。

## 多集 / 项目记忆（轻量）

| Dify 概念 | 拾光剪影 |
|-----------|----------|
| 应用级变量 | `MemoryStore.set_project_context(drama, episode, notes)` |
| 会话记忆 | `get_agent_context()` 注入 system prompt |
| 知识库 | 暂不接向量库（D1 后置）；用 tags + keyword |
| 工作流节点 | `CapabilityDispatcher` + SkillEngine（不可视化编排） |

类别约定：

- `project_context`：当前剧名、集数、竖屏/平台备注（高 score，优先注入）
- `episode_note`：某一集的剪辑备忘（tags 含 `ep:N`）
- 既有：`feedback` / `learned_rule` / `execution_trace`

UI：剪辑 Agent 面板「剧名 / 集数」写入 `project_context`；发送指令时自动带进提示词。

## 会话模式与策略（2026-08-14）

对照外部画布助手方案，本仓库只实现与剪辑/导演台相关的边界：

- **Plan**：只规划 + 只读工具；不落时间线、不改画布
- **协作 B**（默认）：只读自动；时间线删除需确认；画布增删改/生成需确认
- **自主 C**：白名单工具自动执行；付费生成与写操作**不自动重试**
- 预算：12 模型轮次 / 24 工具调用 / 只读最多 3 次重试
- 压缩：只改发给模型的窗口；记忆禁止 Key 与绝对路径

代码：`app/core/agent_policy.py` · `agent_session.py` · `agent_context.py` · `agent_task_store.py` · `agent_runtime.py` · `vendor/shiguang-canvas/src/agentPolicy.ts`

任务：JSON 持久化；重启把 running/planning 标成 paused；B/C 可解析 `canvas_tools` 经 SSE 派发（前端确认）。剪辑/画布均支持串行排队、暂停/继续/重规划。

## 明确不做

- 私有化部署 Dify 作为剪辑运行时  
- 把 pipeline.run_full 做成默认主入口  
- 用远程知识库替代 `_clips` 真相源  
