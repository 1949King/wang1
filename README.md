# 拾光剪影

> **剪辑 + AI 生成的近乎全能工作台** — PyQt6 桌面应用，一句话：**从素材/分镜到成片的本地一体化创作台**（「想法→成片」是方向：S0 选题 / S1 长篇剧本 / S2 母版层待补）。
> 当前版本 **V4.47.0**（主程序，`app/version.py`）· 画布 **0.3.33**（`vendor/packages/canvas-core`，独立版本线）

---

## 项目简介

拾光剪影是 Windows 桌面端的「剪辑 + AI 生成」近乎全能工作台，把「剪辑时间线」和「AI 导演台画布（生成线）」装进同一个壳，目标是一条片子从素材到成片的绝大多数工序都在这张台子上完成：

- **剪辑线**：时间线编辑、预览播放、多格式导出；双内核渲染（FFmpeg / PyAV / MLT），转场语义分层（`exact` 逐像素对齐 vs `bake` 预览-导出对齐）；AI 体力活（拉片、去水词、卡点切镜、建议入轨）。
- **AI 生成线**（导演台画布）：React 节点式导演台 — 生图 / 生视频 / 3D 舞台（Three.js）/ 磁吸画布 / 数字人节点，通过本地服务（端口 18765，HTTP + SSE）与主程序双向通信；配方沉淀 + Agent 一键铺卡。
- **内置 Agent**：白名单 + 「确认后执行」的智能体遥控器（拉片、去水词、批量操作），支持 Ollama 本地模型与多云 Provider（DeepSeek / OpenAI 等 15 类），MCP 客户端已接入（Blender 通道已通）。

**产品北极星**：成片回路可重复——「导演台（含数字人）→ 分镜图 → 入轨精剪 → 导出」，全链路可重复、可撤销、诚实失败；剪辑与 AI 生成互为兜底。短剧/漫剧竖切是当下最成熟的参考场景，**但不是产品边界**。不默认一键成片（「全能」指工序覆盖，不指自动化程度），智能体只做确认后执行。

## 功能特性

| 模块 | 能力 |
|---|---|
| 剪辑 | 多轨时间线、片段变换（冻结区保护）、18+ 转场插件、音频处理、字幕、调色、导出 |
| 画布 | 节点式工作流、生图（ComfyUI）/ 生视频、3D 导演舞台、提示词库、抽卡（draw）+ 代理评分（gen_critic）选优 |
| Agent | 能力目录（capability_catalog 唯一入口）、工作流编排、剪辑↔画布 round-trip、技能系统 |
| 数字人 | TTS + 形象节点（口型成片待模型） |
| 工程 | 自动保存与恢复、会话恢复、项目管理（`data/projects/*.timeline`） |

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面壳 | Python 3.12 + PyQt6（Fusion + 深/浅双主题，`theme_tokens.py` 单一配色真相源） |
| 视频处理 | FFmpeg · OpenCV · PyAV · MLT（双内核） |
| 画布前端 | TypeScript · React 19 · Zustand · Three.js · @xyflow/react · Vite |
| 通信 | 本地 HTTP + SSE（`canvas_server.py`，端口 18765）+ 粘合层契约（`app/core/glue/`） |
| AI | Ollama（本地）+ 多云 Provider；Whisper ASR；ComfyUI 生图；YuE 全曲生成（需远程执行端） |

## 安装（终端用户）

两种形态，内容一样，外壳不同。**完整说明见 [`docs/安装与部署.md`](docs/安装与部署.md)**。

| 形态 | 怎么用 |
|---|---|
| **安装包** `拾光剪影-Setup-<版本>.exe` | 双击 → 6 页向导（许可 / 组件 / 目录 / 完成）→ 从开始菜单或桌面启动。有卸载入口 |
| **绿色版** `拾光剪影-<版本>-portable.zip` | 解压到**固定目录** → 双击 `拾光剪影.exe`。免管理员，无卸载器，删目录即可 |

要点：

- **装完不含任何 AI 模型权重**。本地生图/生视频要自己从 ModelScope 等社区取（程序内模型面板每行有入口），`python scripts/check_models.py --missing` 可看缺什么。
- 安装包可选装「本地 AI 内核」（约 6 GB 量级）；不装就只能用云端模型 + 纯剪辑。
- 卸载会**问你要不要保留用户数据**（作品、素材库、项目文件）。选「否」保留。

### 自己出包

```bash
winget install NSIS.NSIS                                              # 一次性：装 NSIS
.venv312\Scripts\python.exe scripts\build_release.py --installer      # PyInstaller → 内核 → 自检 → Setup.exe
.venv312\Scripts\python.exe scripts\build_release.py --installer --skip-pyinstaller --skip-selftest --fast-compress
```

> ⚠️ **当前 `--installer` 会失败，是体积问题不是脚本问题。** `_internal` 有 1.96 GB，
> 超过 makensis（32 位）实测约 1.8 GB 的地址空间上限，报
> `Internal compiler error #12345: error mmapping file ...`。
> 安装脚本本身已完成并测过（6 页向导 / UTF-8 BOM / 卸载保护用户数据 / 15 个契约测试）。
> 现在能用的是绿色版 zip。出路见 [`docs/安装与部署.md` §2.7](docs/安装与部署.md)。

## 快速开始（开发）

```bash
# 1) 环境：Windows + Python 3.12（.venv312）+ Node 22

# 2) 启动主程序
启动AI短剧编辑器.bat          # 或 .venv312/Scripts/python app/main_qt6.py

# 3) 画布前端开发（改动 vendor/shiguang-canvas 后）
cd vendor/shiguang-canvas
node node_modules/vite/bin/vite.js build

# 4) 提交前全量体检
bash scripts/check_all.sh
```

## 架构概览

```
Qt 桌面壳 (app/main_qt6.py + app/modules/lego/)     ← 全部 UI 模块，真相源 EditorModule._clips
        │
业务内核 (app/core/)                                 ← Agent / 画布桥 / AI 引擎 / 主题配置
        │  HTTP + SSE (端口 18765)
画布前端 (vendor/shiguang-canvas/src)                 ← React 唯一源码 × 双宿主（WebEngine 嵌入 / Tauri 独立）
        │
插件与技能 (app/plugins/ · app/skills/)               ← 18 转场插件 + 特效 + MCP 集成
        │
质量体系 (scripts/ + _verify/ + app/tests/)           ← 11 道门禁 + 全量回归
```

规模（2026-10-11 实测）：Python ≈ 185K 行（app/ 481 文件）+ 画布 TS 48.5K 行 + 测试/验证 37K 行。

## 目录结构

```
app/                    主程序 Python
  main_qt6.py           入口
  modules/lego/         全部 UI 模块（剪辑 editor_module.py 为主文件）
  core/                 业务内核（agent_* · canvas_* · ai/ · glue/ · theme_tokens）
  plugins/              转场/特效插件（注册表 id = extensions）
  tests/                pytest 单元测试
vendor/shiguang-canvas/ 画布前端唯一源码（独立版本线 0.3.x）
vendor/AI-Canvas-tauri/ 副库（第三方克隆，src/libtv 为画布副本；⚠️ 绝不 push）
docs/                   文档（现行技术文档.md 为唯一事实源）
scripts/                门禁脚本（frozen_zone_guard · ruff_gate · stability_gate …）
_verify/                回归脚本（run_all_checks.py …）
data/                   工程与运行数据（projects/*.timeline）
```

## 开发工作流（必读）

1. **唯一事实源**：架构 / 活路径 / 纪律只看 [`docs/现行技术文档.md`](docs/现行技术文档.md)；变更历史看 [`docs/CHANGELOG.md`](docs/CHANGELOG.md)。
2. **冻结区**：9 zone / 85 锁点受 `frozen_zone_guard.py` 保护，未获「解冻 \<zone-id\>」授权禁止改动；流程 = 解冻 → 备份 → 改 → 回归 → `--update` 重锁。
3. **提交门禁**：11 道卡点（ruff 逐文件棘轮 / 冻结区 / 稳定性 / 契约 / 架构 / 双库 / tsc / 规模 / 信号类型 / 出域），入口 `scripts/precommit_gates.sh`。
4. **核心不变量**：时间线真相源 = `EditorModule._clips`（跨线程持锁）；两套版本号独立维护；能力新增唯一入口 = `agent_capability_catalog.py`；音画纠偏 ~280ms 勿动。
5. **验收纪律**：静态门禁全绿 ≠ 运行时没崩——自绘控件必须真机启动验收；提交必须原生 bash 发起，并发会话时路径限定 `git commit -- <精确清单>`。

## 文档索引

| 文档 | 用途 |
|---|---|
| [`docs/现行技术文档.md`](docs/现行技术文档.md) | **唯一开发事实源** |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | 逐版变更与踩坑复盘 |
| [`docs/PROJECT_CONTEXT_PACK.md`](docs/PROJECT_CONTEXT_PACK.md) | 项目上下文包（新会话/新人一键加载） |
| [`docs/智能项目地图.html`](docs/智能项目地图.html) | 交互式项目地图（架构/规模/冻结区/门禁可视化） |
| [`docs/接手速查卡.md`](docs/接手速查卡.md) | 日常操作 / 红线 / 假警报速查 |
| [`docs/knowledge/INDEX.md`](docs/knowledge/INDEX.md) | 结构化知识库（00–19） |

---

*本 README 为对外/新人入口。开发细节、纪律与已知问题以 `docs/现行技术文档.md` 为准，两者冲突时以后者为准。*
