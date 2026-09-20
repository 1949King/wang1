# 01 — 术语表（Glossary）

编码与文档必须使用下列共享语言。新概念先写入本表，再改代码。

| 术语 | 含义 |
|------|------|
| **LEGO模块** | `app/modules/lego/` 下的功能 UI 模块，经 `ModuleRegistry` 分级开关 |
| **双内核** | `EditorScheduler`：轻量 PyAV vs 专业 FFmpeg/MLT |
| **时间线** | 剪辑主画布；UI=`TimelineWidget`，数据=`TimelineManager` + `EditorModule._clips` |
| **真相源** | 日常剪辑以 `EditorModule._clips` 为准（见 P0 对齐约束） |
| **素材库** | 素材管理模块 / assets 目录 |
| **短剧筛选** | Drama finder：插件壳 `drama_finder_plugin`（无爬虫功能）；运行时经**拓展中心**打开；`drama_send_to_editor` 回流签名保留 |
| **拓展中心** | 注册表 id=`extensions`（原 `plugins` 已迁移）；Skill 工坊 + MCP + 旧插件兼容 |
| **账号矩阵** | 多账号多平台发布运营 |
| **AI剪辑** | 自动切片、转场、字幕、策略剪辑；另有编辑器 Agent 面板 |
| **Agent 模式** | Plan（只规划）/ 协作 B（写需确认）/ 自主 C（白名单自动、付费不重试）；见 `agent_policy` |
| **薄指令执行器** | `edit_commands`：Split / Ripple Delete 写回 `_clips` + 撤销（B1） |
| **文本↔帧绑定** | `text_frame_map`：字幕时间码 → 半开帧区间（B0） |
| **去水词** | `filler_silence_detect` + 字幕面板「一键去水词」（B2） |
| **Ollama本地** | `http://localhost:11434` 本地 LLM |
| **ChatGPT2API** | 自托管 OpenAI 兼容网关（默认 `http://127.0.0.1:8000/v1`）；模型广场 Provider=`chatgpt2api`，优先用于 `gpt-image-2` 生图并同步画布 `shiguang-aigc` |
| **AIGC 模型** | 生图/生视频/语音类能力目录（`AIGC_MODELS`），与对话模型分开配置；在「模型管理 → AIGC」页浏览 |
| **OpenClaw** | 多平台发布自动化 |
| **SkillEngine** | Skill 编排执行引擎 |
| **EventBus** | 模块间唯一推荐通信通道（勿模块互调） |
| **DataBus** | 全局键值共享 |
| **MasterClock** | 全局时钟 |
| **PreviewManager** | OpenCV 帧预览；时间线播放时由 Editor 墙钟驱动 `get_frame_at` |
| **WaveformGenerator** | 音频轨峰值波形 |
| **联动音频片** | 导入视频时自动挂到 audio 轨的同路径片段；主音由视频 QMediaPlayer 播，BGM 同步须跳过 |
| **墙钟播放** | `QElapsedTimer` 驱动 playhead，忙则丢帧，避免 `+=0.033` 越播越拖 |
| **剪辑画布联动** | round-trip：入轨盖 `canvas_node_id`；剪辑回推 outbox 自动落 `source` 节点；`/host/timeline-snapshot` 给画布 Agent 读轨 |
| **3D 导演台** | 画布内 `vendor/shiguang-canvas` 的 Three.js 站位台；素模 **vinchau BodyKun/BodyChan**（CC0）；点选可见网格；拉肢 IK；正面=+Z。摆姿截图，不是口型数字人 |
| **群像模板** | 导演台一键生成 2–5 人（对峙/弧形/一字/围圆）；与「重排现有人模」不同 |
| **账号运营** | 仅拓展中心插件 `account_ops_plugin`（UI 复用 `account_ops_module.py`）；非导航模块 id |
| **CORE / ADVANCED / EXPERIMENTAL** | 模块分级：核心不可关 / 高级默认关 / 实验默认关（**例外**：`extensions` 实验级但默认开） |

## 模块 ID（注册表 · 2026-08 复核）

`home` · `editor` · `settings` · `help` · `copywriting` · `tasks` · `materials` · `models` · `characters` · **`extensions`** · `performance` · `ai_clip_flow`  
（`account` 已迁插件，非导航 id）

已移除：`drama`（改插件）、`plugins`（迁 `extensions`，旧 id 有迁移逻辑）。  
注意：`PluginsModule` 源文件可能仍在，但**不在注册表**，勿当活入口。
