# 09 — Tool Registry 收敛设计（提案，未实施）

> 状态：**阶段 0 + 阶段 1 部分落地**；**2026-08-14** 增加 Policy Engine 叠层（`agent_policy.py`），不替代四套登记、不跳到阶段 2 动态白名单。完整动态白名单（阶段 2）未执行。对照见 [`11-opentake-gap.md`](11-opentake-gap.md) 与 [`13-agent-skill-memory.md`](13-agent-skill-memory.md)。
> **2026-09-13 校正**：④ 对话白名单已改为**表驱动单一来源**并配自动校验脚本，本文原「手写 frozenset」的描述已过时，已按现状更新；阶段 2 由「必修」降为「洁癖项」。
> 起因：2026-08-11 项目技术债务评估 P0 项——"能力表面分裂成 4 套并行体系"。

## 一、现状（基于代码实证，非推测）

Agent / UI 想要"调用一个能力"时，实际存在 **4 套并不完全同构的命名与登记体系**：

| 体系 | 命名空间示例 | 登记位置 | 对外枚举接口 | 返回形状 |
|---|---|---|---|---|
| ① `CapabilityDispatcher` | `editor.split_clip` / `account.publish`（点分 `category.verb`） | `capability_handlers.py::register_builtin_handlers` 硬编码调用 25 次 `dispatcher.register(...)` | `list_capabilities()` | `{capability_id, category, description, schema}` |
| ② `SkillEngine` | `publish_content` / `matrix_publish`（扁平 skill_id，类属性 `skill_id = "..."`） | 各 `Skill` 子类自带 `skill_id`，`skill_engine.register_skill(cls)` | `skill_engine.list_all()` | `Skill` 实例（`skill_id/skill_name/skill_description`） |
| ③ `ExtensionsRegistry` | `extension_id` + `tool_id`（插件/MCP 粒度） | `extension_base.get_extensions_registry()` | `ext.get_tools()` | `ExtensionInfo` + `Tool(id, name, description)` |
| ④ 对话白名单 | `add_track` / `ripple_delete` 等简化动词 | **`agent_action_registry.py`**（`ai_agent_panel` 再导入） | `get_allowed_actions()` | frozenset + `ACTION_TO_CAPABILITY`（**均由表驱动行派生**，见下方校正） |

**已验证的具体后果**（非假设）：

1. `capability_handlers.py::AccountCapabilityHandlers.publish()` 曾经默认 `skill_id="account_publish"`，但 ② 里从未存在这个 id（真实是 `publish_content`/`matrix_publish`）——任何未显式传 `skill_id` 的调用 100% 失败。**本轮已修复**（改默认值为 `publish_content` 并加注释说明批量场景需显式传参），但**修复方式仍是手改一处硬编码值，没有机制能在下一次新增 Skill 时自动防止同类问题**。
2. ④ 与 ① 是两套命名体系，历史上确实靠注释人工保持同步。
   **2026-09-13 校正**：`agent_action_registry.py` 现已改为**表驱动单一来源**
   （`_AGENT_ACTION_ROWS` 26 条 + `_CANVAS_ACTION_ROWS` 32 条；safe / dangerous / allowed /
   `ACTION_TO_CAPABILITY` 全部从同一张表派生），不再是「各写一份字符串集合」。
   剩余的「漏改」风险已从人工约定变成自动校验：`register_builtin_handlers()` 结束后的自检
   + 回归脚本 `_verify/check_agent_action_mapping.py`（实测 34 个能力 / 无 action 指向未注册能力）。
   ⇒ 因此阶段 2 的**紧迫性下降**：内容一致性问题已基本解决，剩下的是「清单生成方式」的洁癖。
3. `ext.list_tools`（①内部合并②③）与 `list_capabilities()`（① 自身）是**两个格式不同的"列出所有能力"接口**，Agent 系统提示词构建时要分别处理两种数据形状。

## 二、目标形态

**不新建第五套体系**，而是让 ① `CapabilityDispatcher` 真正成为唯一的对外契约层——这是四套里已经具备最完整语义（`category` + `description` + `schema` + 统一 `invoke()` + trace + EventBus 广播）的一套，②③ 保持不变但**只作为 handler 内部实现细节**，④ 从手写集合改为**从 ① 动态派生**。

```
Agent / UI / 外部入口
        │  只认一种词汇：capability_id（如 "account.publish"）
        ▼
CapabilityDispatcher.invoke(CapabilityRequest)
        │
        ├─ handler 内部按需调用 SkillEngine（skill_id 是实现细节，不外泄）
        ├─ handler 内部按需调用 ExtensionsRegistry（extension_id/tool_id 是实现细节）
        └─ 对话白名单 = capability_dispatcher.list_capabilities() 的一个子集视图
             （而不是独立维护的 frozenset）
```

## 三、分阶段迁移（每阶段独立可验收，不要求一次性重写）

### 阶段 0（已完成，本轮）

- 修复 `account.publish` 默认 `skill_id` 死值 bug。

### 阶段 1 — 注册期一致性校验（**部分完成 2026-08-12**）

已落地：

- `app/core/agent_action_registry.py`：对话 action / 危险级 / `ACTION_TO_CAPABILITY` 单一来源；
- `register_builtin_handlers()` 结束后对映射做 `logger.warning` 自检；
- `ai_agent_panel` 白名单改为从 registry 导入；Agent 系统提示用 `build_agent_actions_help_block()`。

仍待：散落在 handler 内的默认 `skill_id` 常量表 + debug 启动校验（原提案全文）。

### 阶段 2 — 对话白名单改为动态派生（中风险，需要行为对比测试）

**2026-09-13 现状校正**：`_AGENT_SAFE_ACTIONS`/`_AGENT_DANGEROUS_ACTIONS` 现已不是两个独立
`frozenset`，而是 `agent_action_registry.py` 里同一张表的两个投影视图（表驱动派生）。
目标（不变）：让这份表本身也从 ① 动态派生，彻底消灭「两张表」。

1. 在 `CapabilityDispatcher.register()` 增加可选参数 `conversational_alias: Optional[str]`（如 `editor.split_clip` 注册时带 `conversational_alias="split_clip"`）和 `danger_level: Literal["safe","dangerous"]="safe"`；
2. `ai_agent_panel.py` 不再手写 `frozenset`，改为 `{e["conversational_alias"]: e for e in capability_dispatcher.list_capabilities() if e.get("conversational_alias")}` 在运行时生成；危险指令集合同理按 `danger_level` 过滤；
3. **不改变**现有对话 action 的字符串本身（`add_track`/`ripple_delete` 等保持不变，只改"这份清单从哪来"），把回归面限制在"清单生成方式"而非"清单内容"。

**验收**：迁移前后 `_AGENT_ALLOWED_ACTIONS` 等价集合完全一致（写一个对比测试：旧硬编码集合 == 新动态生成集合），`test_editor_ripple_capability.py`/`test_p0a_public_interfaces.py` 无回归。

### 阶段 3 — 统一"列出能力"接口（中风险）

`ext.list_tools` 的返回形状改为复用 `list_capabilities()` 同款字典结构（`capability_id/category/description/schema`），`extension_id`/`tool_id`/`skill_id` 降级为 `schema` 里的一个内部字段而非顶层键。Agent 系统提示词构建处（`editor_module.py::_build_edit_agent_messages` 一类位置）改为只消费一种形状。

**验收**：Agent 面板"可用能力"展示不回归；`ext.list_tools` 旧调用方（如有）通过适配层兼容一个版本周期。

### 阶段 4 — 清理 ExtensionsRegistry / SkillEngine 里重复的"面向 Agent 暴露"逻辑（低优先）

三层 fallback（① Dispatcher → ② ExtensionsRegistry → ③ SkillEngine，见 `02-architecture.md` §七）本身可以保留——它是"执行时"的合理降级链，问题只在"注册/枚举时"的清单不统一。此阶段视前三阶段效果决定是否需要。

## 四、明确不做

- 不合并 `SkillEngine`（多步骤+进度回调+暂停/取消的执行模型）与 `ExtensionsRegistry`（插件生命周期管理）的**内部实现**，二者职责本就不同，只统一"对外暴露的登记表"。
- 不要求一次性把 25+ 个能力的 schema 全部补全为严格 JSON Schema（那是 `05-known-issues.md` 里"Agent 5 大架构缺口"第 4 条，属于更大的规划，见该文档）。
- 不在本设计范围内改变任何 UI 交互或危险操作二次确认逻辑。

## 五、与其他文档的关系

- 架构现状全景图见 [`02-architecture.md`](02-architecture.md) §五～七、§十四。
- "Agent 5 大架构缺口"（含"能力表面分裂成 4 套并行体系需收敛成一套 Tool Registry"原始表述）见 [`05-known-issues.md`](05-known-issues.md) 第五轮修复批。
- 本文档是该缺口的**具体落地方案**，阶段 1 完成后应回写 `05-known-issues.md` 勾掉对应条目。
