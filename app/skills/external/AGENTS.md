# 外部 Skill 与 Agent 研究手册

> 本文件面向 AI Agent，汇总 `app/skills/external/` 下所有第三方剪辑师
> skill 与 agent 的入口、配置、调用方式。AI 在研究如何使用这些外部
> 资源时，应先读本文件，再按需深入具体 SKILL.md。

## 0. 总览

| 仓库 | 形态 | skill 数 | agent 配置 | 入口 |
|------|------|---------|-----------|------|
| `seedance2-skill` | 纯知识型 Markdown | 2 | 无 | SKILL.md（中英双版） |
| `video-use` | 知识型 + Python helpers | 2 | editor sub-agent brief（SKILL.md 内描述） | SKILL.md + `helpers/*.py` |
| `videocut-skills` | MCP 插件 + 子 skill 集合 | 7 | 每个子 skill 一个 `agents/openai.yaml` | `.mcp.json` + `dist/server.mjs` |

**注册到项目 SkillEngine 的 skill 总数**：11（由 `app/skills/external_loader.py`
自动发现并注册）。每个 skill 的 `skill_id` 形如 `<repo>__<name>`，
`skill_category` 形如 `外部/<repo>`。

## 1. 仓库：seedance2-skill

**用途**：即梦 Seedance 2.0 多模态 AI 视频生成模型的提示词撰写指南。
覆盖输入约束、`@` 引用语法、运镜语言、提示词结构模式，以及广告、
短剧、MV、科普教育等场景的现成模板。

**两个 skill**：
- `seedance2-skill__seedance-prompt-en`（英文版）
- `seedance2-skill__seedance-prompt-zh`（中文版，位于 `zh/SKILL.md`）

**典型研究路径**：
1. 调用 `skill_engine.execute_skill("seedance2-skill__seedance-prompt-zh")`
2. 读取返回的 `outputs.skill_md_content`，掌握 `@Image1`/`@Video1`/`@Audio1`
   引用语法、运镜术语、分时段提示词模板
3. 结合项目的 Seedance 视频生成能力（参考
   `byted-seedance-video-generate` 技能）产出可用提示词

## 2. 仓库：video-use

**用途**：基于 ffmpeg + ElevenLabs Scribe 的对话式视频剪辑助手。
LLM 从逐词转录驱动剪辑决策，支持转录、剪切、调色、生成动画叠加层、
烧录字幕。**适合长篇口播、教程、访谈、旅行 vlog**。

**两个 skill**：
- `video-use__video-use`（主 skill）
- `video-use__manim-video`（vendored 子 skill：用 Manim 生成数学/物理动画）

**关键 helpers**（`helpers/` 目录）：
| 文件 | 职责 |
|------|------|
| `transcribe.py <video>` | 单文件 ElevenLabs Scribe 转录，带缓存 |
| `transcribe_batch.py <videos_dir>` | 4-worker 并行转录，多 take 场景 |
| `pack_transcripts.py --edit-dir <dir>` | 把 `transcripts/*.json` 打包成 phrase-level 的 `takes_packed.md` |
| `timeline_view.py <video> <start> <end>` | 胶片条 + 波形 PNG，决策点可视化 |
| `render.py <edl.json> -o <out>` | 分段抽取 → concat → overlays（PTS-shifted）→ 字幕最后 |
| `grade.py <in> -o <out>` | ffmpeg 调色滤镜链，含预设 `warm_cinematic`/`neutral_punch`/`none` |

**editor sub-agent brief 模式**（位于 `video-use/SKILL.md` 第 ~123 行）：
当任务是多 take 选优时，video-use 推荐通过 `Agent` 工具 spawn 一个
专门的编辑子代理，brief 结构是 load-bearing 的：

```
你正在剪辑一支 <type> 视频。为每个 beat 挑最佳 take，按 beat 时间序装配。
INPUTS:
  - takes_packed.md（所有 take 的 phrase-level 时间标注转录）
  - 产品/叙事上下文: <2 句话>
  - 说话人: <姓名/角色/语速风格>
  - 期望结构: <选一个 archetype 或自创>
  - 需回避的口误: <预扫清单>
  - 目标时长: <秒>
RULES:
  - 起止时间必须落在转录词边界
  - 切边填充 30-200ms
  - 优先选 ≥400ms 的静音段
  - 不可避免的口误保留时在 "reason" 中标注
OUTPUT (JSON array, no prose):
  [{"source": "C0103", "start": 2.42, "end": 6.85, "beat": "HOOK",
    "quote": "...", "reason": "..."}, ...]
```

结构 archetype 选项（取/改/创）：
- Tech launch / demo: HOOK → PROBLEM → SOLUTION → BENEFIT → EXAMPLE → CTA
- Tutorial: INTRO → SETUP → STEPS → GOTCHAS → RECAP
- Interview: (QUESTION → ANSWER → FOLLOWUP) repeat
- Travel / event: ARRIVAL → HIGHLIGHTS → QUIET MOMENTS → DEPARTURE
- Documentary: THESIS → EVIDENCE → COUNTERPOINT → CONCLUSION
- Music / performance: INTRO → VERSE → CHORUS → BRIDGE → OUTRO

**Hard Rules**（不可妥协的产品正确性规则，完整列表见 SKILL.md）：
1. 字幕必须在 filter chain 最后应用（否则被 overlay 遮住）
2. 分段抽取 → 无损 `-c copy` concat，不要单 pass filtergraph
3. 每个段边界 30ms 音频淡入淡出（否则切点处爆音）
4. overlays 用 `setpts=PTS-STARTPTS+T/TB` 偏移到窗口起点
5. master SRT 用输出时间轴偏移
6. 永不切词内部，按词边界对齐
7. 每个切边填充 30-200ms
8. 词级 verbatim ASR，禁用 SRT/phrase mode
9. 转录按源文件缓存
10. 多动画用并行 sub-agents
11. 执行前必须用户确认策略
12. 所有会话输出写入 `<videos_dir>/edit/`

**研究建议**：本项目 `app/ai_video_editor_local.py` 已有 Whisper 转录、
ffmpeg 调用、剪辑流程，可与 video-use 的 phrase-level 打包、Hard Rules
对齐改造。

## 3. 仓库：videocut-skills

**用途**：`chengfeng-videocut` MCP 插件，专注于**中文口播视频**的
工业级剪辑流水线。包含 6 个业务子 skill + 1 个动画样式 skill，
通过 MCP server 暴露给 AI 调用。

### 3.1 MCP 入口

- **配置文件**：`videocut-skills/plugins/chengfeng-videocut/.mcp.json`
  ```json
  {
    "mcpServers": {
      "chengfeng-videocut": {
        "command": "node",
        "args": ["dist/server.mjs"],
        "cwd": "."
      }
    }
  }
  ```
- **server 实现**：`videocut-skills/plugins/chengfeng-videocut/dist/server.mjs`
- **运行时要求**：Node.js + 已执行 `bin/install.cjs` 安装依赖
- **项目集成**：通过 `app/core/mcp_client.py` 的 `McpClientManager.connect()`
  以 stdio 传输方式拉起 server，然后 `list_tools()` / `call_tool()`

### 3.2 七个子 skill

每个子 skill 都有 `SKILL.md` + `agents/openai.yaml` + 可选 `references/`。
`openai.yaml` 给出 `display_name` / `short_description` / `default_prompt`，
可作为 AI 研究/调用的入口。

| skill_id | 显示名 | 职责一句话 |
|----------|--------|-----------|
| `chengfeng-check-updates` | 检查更新 | 安全检查 Skills 是否有可信更新，不激活先报告状态 |
| `chengfeng-cut` | 剪口播 | 逐词转录 → 词典修字 → 五轮扫描找口误与重复 → 出删词账本，不切媒体 |
| `chengfeng-export` | 导出 | 把剪辑、推近、字幕和 HTML 画面层一次烧成成片 mp4 并抽帧验收 |
| `chengfeng-report-bug` | 上报 Bug | 整理脱敏问题，确认后创建 GitHub Issue |
| `chengfeng-subtitle` | 字幕 | 重新转写剪后视频，只修文字和断句，人工复核后发布 |
| `chengfeng-visual` | 画面 | 给剪好的口播配画面：录屏上盖 HTML 层，标注圈重点或整屏动画 |
| `ian-xiaohei-svg-motion` | 小黑 SVG 动效 | 把小黑正文配图改成可控的 HTML/SVG 漫画动效模板 |

### 3.3 流水线串联（chengfeng 推荐链路）

```
检查更新 → 剪口播 → 字幕 → 画面 → 导出
                      ↑
                   上报 Bug（异常时分支）
```

- `chengfeng-cut` 产出**已复核的删词账本（Cuts + EDL）**，不切媒体
- `chengfeng-subtitle` 基于**剪后视频**重新转写，修正专名与断句
- `chengfeng-visual` 在剪好的口播上盖 HTML 画面层
- `chengfeng-export` 一次性烧成成片，含抽帧验收

### 3.4 agent 配置（openai.yaml）

每个 `openai.yaml` 的字段含义：
- `interface.display_name`：UI 展示名（含「chengfeng ·」前缀）
- `interface.short_description`：一句话职责描述
- `interface.default_prompt`：用户调用时的默认提示词模板，
  含 `$chengfeng-videocut:<skill-name>` 引用语法
- `policy.allow_implicit_invocation`：是否允许隐式调用（true 表示
  AI 可在合适场景自动触发，无需用户显式指令）

`default_prompt` 是 AI 研究 chengfeng skill 调用方式的最佳入口——
它给出了该 skill 期望的输入描述与执行边界。

## 4. 项目集成与调用方式

### 4.1 通过 SkillEngine 调用（推荐，已就绪）

```python
from app.skills.external_loader import ensure_external_skills_registered
from app.modules.lego.skill_engine import skill_engine

# 幂等：首次实际扫描注册，后续调用直接返回
ensure_external_skills_registered()

# 调用外部 skill
result = skill_engine.execute_skill("videocut-skills__chengfeng-cut")
print(result["success"])           # True
print(result["outputs"]["skill_md_content"])   # SKILL.md 全文
print(result["outputs"]["helpers_dir"])        # helpers/ 目录路径
print(result["outputs"]["agent_yamls"])        # agents/openai.yaml 路径
```

返回的 `outputs` 字段（统一约定）：
| 字段 | 含义 |
|------|------|
| `skill_id` / `skill_name` | skill 标识 |
| `source_repo` | 来源仓库名（seedance2-skill / video-use / videocut-skills） |
| `skill_md_content` | SKILL.md 全文（AI 研究时优先读这个） |
| `skill_md_path` / `skill_dir` | 文件系统路径 |
| `helpers_dir` / `helper_files` | helpers/ 目录与文件清单（仅 video-use 有） |
| `scripts_dir` / `script_files` | scripts/ 目录与文件清单 |
| `references_dir` / `reference_files` | references/ 目录与文件清单 |
| `agents_dir` / `agent_yamls` | agents/ 目录与 yaml 配置路径（仅 videocut 有） |

### 4.2 通过 MCP 调用（videocut-skills 专用）

```python
from app.core.mcp_client import McpClientManager

manager = McpClientManager()
config = {
    "type": "stdio",
    "command": "node",
    "args": ["dist/server.mjs"],
    "cwd": "D:/拾光剪影/app/skills/external/videocut-skills/plugins/chengfeng-videocut",
    "name": "chengfeng-videocut"
}
if manager.connect(config):
    tools = manager.list_tools()
    for t in tools:
        print(t["name"], t["description"])
    # 调用具体工具
    result = manager.call_tool("chengfeng_cut", {"video": "/path/to/video.mp4"})
```

### 4.3 通过 UI 调用（拓展中心）

打开「拓展中心」→「Skill 工坊」标签，列表里会显示所有外部 skill
（分类前缀 `外部/`），选中后输入 JSON 参数（可空 `{}`），
点「运行技能」。执行结果会显示在右下输出框。

## 5. AI 研究流程建议

1. **先读 `AGENTS.md`（本文件）**：建立对外部资源全貌的认知。
2. **按需深入 SKILL.md**：通过
   `skill_engine.execute_skill("<repo>__<name>")["outputs"]["skill_md_content"]`
   获取具体 skill 的完整规范。
3. **对照 agent 配置**：videocut 系列读 `agent_yamls` 字段返回的
   `openai.yaml`，理解 default_prompt 给出的调用边界。
4. **检查 helpers/scripts**：video-use 的 helpers 是可直接执行的
   Python 脚本，研究时阅读源码理解实现细节。
5. **不要混淆形态**：
   - 知识型 skill（seedance2-skill）只提供指南，无副作用
   - 工具型 skill（video-use helpers）可执行 ffmpeg 命令
   - MCP 插件（videocut-skills）需先 `connect()` 再 `call_tool()`
6. **遵守外部 skill 的 Hard Rules**：特别是 video-use 的字幕必须
   最后应用、切边填充 30-200ms、词级 verbatim ASR 等不可妥协规则。

## 6. 文件清单（供 AI 快速定位）

```
app/skills/
├── __init__.py                      # 包入口，导出 SKILLS_ROOT 等
├── external_loader.py              # 外部 skill 加载器（发现+注册）
├── custom/
│   └── subtitle-gen/metadata.json   # 项目自带字幕生成 skill
└── external/
    ├── AGENTS.md                    # 本文件
    ├── seedance2-skill/             # 仓库 1：Seedance 提示词指南
    │   ├── SKILL.md                 # 英文版
    │   ├── zh/SKILL.md              # 中文版
    │   └── README-zh.md
    ├── video-use/                   # 仓库 2：对话式视频剪辑
    │   ├── SKILL.md                 # 主 skill（含 Hard Rules + editor brief）
    │   ├── install.md               # 安装指引
    │   ├── pyproject.toml           # Python 依赖
    │   ├── helpers/                  # 6 个可执行 Python 脚本
    │   │   ├── transcribe.py
    │   │   ├── transcribe_batch.py
    │   │   ├── pack_transcripts.py
    │   │   ├── timeline_view.py
    │   │   ├── render.py
    │   │   └── grade.py
    │   └── skills/manim-video/     # vendored Manim 子 skill
    └── videocut-skills/             # 仓库 3：chengfeng MCP 插件
        ├── .agents/plugins/marketplace.json
        ├── installer-manifest.json
        ├── package.json
        ├── bin/install.cjs          # 依赖安装脚本
        └── plugins/chengfeng-videocut/
            ├── .mcp.json            # MCP 配置入口
            ├── server.mjs           # MCP server 实现（src）
            ├── dist/server.mjs       # 构建产物
            ├── references/          # 业务契约文档
            │   ├── business-workflow-contract.md
            │   ├── runtime-and-product-contract.md
            │   └── ai-term-dictionary.md
            ├── scripts/             # 运维脚本（含 mcp-smoke-test）
            └── skills/              # 7 个子 skill
                ├── chengfeng-check-updates/{SKILL.md,agents/openai.yaml}
                ├── chengfeng-cut/{SKILL.md,agents/openai.yaml,references/}
                ├── chengfeng-export/{SKILL.md,agents/openai.yaml}
                ├── chengfeng-report-bug/{SKILL.md,agents/openai.yaml,scripts/}
                ├── chengfeng-subtitle/{SKILL.md,agents/openai.yaml,references/}
                ├── chengfeng-visual/{SKILL.md,agents/openai.yaml,references/,animation-styles/}
                └── chengfeng-visual/animation-styles/ian-xiaohei-svg-motion/{SKILL.md,agents/openai.yaml}
```

## 7. 反向链接

- 项目 Skill 基类与引擎：[`app/modules/lego/skill_engine.py`](../../modules/lego/skill_engine.py)
- 拓展中心 UI：[`app/modules/lego/extensions_module.py`](../../modules/lego/extensions_module.py)
- MCP 客户端：[`app/core/mcp_client.py`](../../core/mcp_client.py)
- 加载器实现：[`app/skills/external_loader.py`](../external_loader.py)
