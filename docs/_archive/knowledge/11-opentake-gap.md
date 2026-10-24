# 11 — OpenTake / OTIO / 选模 / 画布对照（只学不换壳）

> 状态：文档 + Agent/选模/画布体验优化（**不改** `_clips` 真相源；不引入 Tauri/Wails/Dify/tldraw）。  
> 姊妹篇：[`12-otio-clip-fields.md`](12-otio-clip-fields.md) · [`13-agent-skill-memory.md`](13-agent-skill-memory.md) · [`09-tool-registry-design.md`](09-tool-registry-design.md)

## 原则

| 做 | 不做 |
|----|------|
| OpenTake：MCP 工具可枚举、时间线自省 | OpenTake/Tauri 换宿主 |
| ClipSkills：决策 / 知识 / 执行分层 | 把执行绑到外部 Agent IDE |
| OTIO：字段语义对照 | OTIO 替换 `.timeline` |
| Ollama+云端：激活态与 Agent 下拉一致 | 再接一套推理后端 |
| Dify：记忆与 Skill UX 写进提示词 | 部署 Dify 当剪辑主脑 |
| infinite-canvas 打磨 | 换 tldraw / Wails 打包 |

## OpenTake MCP ↔ Dispatcher / 对话白名单

| OpenTake 工具 | capability | 对话 action | 状态 |
|---|---|---|---|
| `get_timeline` | `editor.get_timeline_context` | （自动注入，无 action） | ✅ 已增强 gaps/tracks/in·out |
| `get_media` | — | — | ❌ 缺口 |
| `inspect_media` | — | — | ❌ 缺口 |
| `add_clips` | — | — | 🚫 故意未开放 |
| `import_media` | — | — | 🚫 故意未开放 |
| `split_clip` | `editor.split_clip` | `split_clip` | ✅ |
| `set_clip_properties` | — | `trim_clip` 仅 duration | ⚠️ 部分 |
| `set_keyframes` | — | — | ❌ 缺口 |
| `ripple_delete_ranges` | `editor.ripple_delete_range` | `ripple_delete_range` / `ripple_delete` | ✅ |
| `search_media` | — | — | ❌ 缺口 |
| generate_* | pipeline.* / AIGC 画布 | — | ⚠️ 旁路，非对话主路径 |

**单一来源**：`app/core/agent_action_registry.py`（白名单 + 提示词 + `ACTION_TO_CAPABILITY`）。

**ClipSkills 分层**：见 [`13-agent-skill-memory.md`](13-agent-skill-memory.md)；系统提示含 L0/L1/L2 约束。

## OTIO

详见 [`12-otio-clip-fields.md`](12-otio-clip-fields.md)。一句话：`path/in_point/out_point/start_time/duration/track` ≈ Clip+Track；无 Nested、无正式 Gap 对象。

## 选模体验

- 云端保存 Key → **自动激活**（避免停在 ollama）
- `ensure_active_provider_sensible()`：激活为 ollama 但本地不可用、且已配置 DeepSeek 等 → 自动切云端
- Agent 下拉标 ★ 激活项；`PROVIDER_ACTIVATED` 事件刷新下拉
- 画布 bridge prefs 带 `active_provider`，inject 面板展示

## 画布（infinite-canvas，不换 tldraw）

- 继续 `canvas_runtime`：dist 静态 :3001 优先
- inject 面板：关闭/FAB、同步模型、连接 Agent、展示当前激活 Provider
- 入轨仍走 `MATERIAL_TO_TIMELINE`

## 明确后置

tldraw · Wails · Dify 运行时 · OTIO 读写实现 · Agent 开放 `add_clips`/`set_keyframes`
