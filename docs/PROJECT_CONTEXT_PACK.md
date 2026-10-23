# 拾光剪影 — 项目上下文包（Context Pack）

> **快照日期：2026-10-23**（主程序 V4.46.5 · 画布 0.3.33）
> **快照性质声明**：本文件是项目上下文快照，用于「一键加载项目上下文」
> （新 AI 会话 / 新协作者 / 新设备冷启动）。**代码与流程纪律的唯一事实源仍是
> [`docs/现行技术文档.md`](现行技术文档.md)**，两者冲突时以现行技术文档为准；
> 版本事实源 = `app/version.py`（主程序）与 `vendor/shiguang-canvas/src/canvasVersion.ts`（画布）。
>
> **再生成**：本包由智能体基于实测采集生成（读 version.py / wc -l / frozen_zones.json 等），
> 不建议手改；数据过期时请求重新生成即可。

---

## 1. 项目名片（一表读完）

| 项 | 值（2026-10-11 实测） |
|---|---|
| 名称 | **拾光剪影** — 剪辑 + AI 生成的近乎全能工作台（PyQt6 桌面应用） |
| 形态 | PyQt6 桌面壳 + WebEngine 内嵌 React 画布（本地单机应用） |
| 主程序版本 | **V4.46.5**（`app/version.py`，2026-10-23） |
| 画布版本 | **0.3.33**（`vendor/packages/libtv/src/canvasVersion.ts`，独立版本线，刻意不同步） |
| 生产代码规模 | Python ≈ **185,352 行**（app/ 481 个 .py，不含测试）+ 画布 TS/TSX **48,535 行** ≈ **23.4 万行** |
| 测试/验证 | `app/tests` 18,477 行 + `_verify` 18,714 行 + `scripts` 4,533 行 |
| Git | 1,598 个跟踪文件；最新提交 `3e10a445`；origin = `github.com/1949King/shiguangjianying`（仅本机，未 push） |
| 运行环境 | Windows + Python 3.12（`.venv312`）+ Node 22 + RTX 4060 8GB |
| 入口 | `app/main_qt6.py`（壳）· 画布服务 `app/core/canvas_server.py`（端口 **18765**，HTTP+SSE） |

## 2. 产品定位与北极星

- **是什么**：桌面端「剪辑 + AI 生成」的**近乎全能工作台**，重心偏向两条活路径——
  ① **剪辑线**（时间线编辑/预览/导出；AI 体力活：拉片/去水词/卡点切镜/建议入轨）；② **AI 生成线**（导演台画布节点、生图/生视频、智能体与数字人；配方沉淀 + Agent 一键铺卡）。
  两线在时间线上会师（产物入轨 / round-trip）。短剧/漫剧竖切是当下最成熟的参考场景，**但不是产品边界**。运营/发布、短剧筛选已彻底删除，不再是迭代主题。
- **北极星**：成片回路可重复——「导演台（含数字人）→ 分镜图 → 入轨精剪 → 导出」，全链路可重复、可撤销、诚实失败；剪辑与 AI 生成互为兜底。
  智能体只做「确认后执行」的遥控器，**不默认一键成片**（「近乎全能」指工序覆盖，不指自动化程度）。
- **四条专注轨（资源配比）**：N 剪辑 ~30% · P 画布 ~35% · A Agent ~25% · D 数字人 ~10%。
- **明确不做**：不重写时间线架构、不换壳（Wails/Tauri 宿主化、tldraw 替换主画布、Dify 当运行时）、
  不默认一键全链路成片、不做向量库/万能 EDL/完整转场库。

## 3. 技术栈

| 层 | 技术 |
|---|---|
| UI 壳 | PyQt6（Fusion + 深/浅双主题 QSS，`theme_tokens.py` 57 keys 单一真相源） |
| 视频处理 | FFmpeg / OpenCV / PyAV / MLT（**双内核**）；转场语义分层 exact（xfade-direct ≤4 LSB）vs bake（预览-导出对齐） |
| 画布前端 | TypeScript + React 19 + Zustand + Three.js + @xyflow/react（真源 `vendor/packages/libtv/src`，宿主壳 `vendor/shiguang-canvas`，Vite 构建） |
| 画布宿主 | 宿主 A：WebEngine 嵌入 Qt（默认 `engine=shiguang`）；宿主 B：独立 Tauri 进程（副库 `vendor/AI-Canvas-tauri/`，P0-1 后以 `@shiguang/libtv: workspace:*` 依赖包真源，`src/libtv/` 副本已删） |
| AI | Ollama（本地）+ 多云 Provider（DeepSeek/OpenAI 等 15 类）；ComfyUI 生图；编辑器内 Agent / Skill / MCP 客户端（stdio+SSE） |
| 音画 | 音画纠偏 ~280ms（冻结区不变量，勿压回） |

## 4. 架构分层与代码地图（行数实测 2026-10-11）

```
┌─ Qt 桌面壳  app/main_qt6.py + app/modules/lego/（98 个 .py）
│    └─ 剪辑模块主文件 editor_module.py（9,746 行，冻结区，真相源 = EditorModule._clips）
├─ 业务内核  app/core/（97,864 行）
│    ├─ Agent 系：agent_brain / agent_runtime / agent_capability_catalog（能力元数据唯一入口）
│    ├─ 画布桥：canvas_server(18765) / canvas_routes_get|post / canvas_bridge / glue 契约层
│    ├─ AI 系：app/core/ai/（draw_orchestrator 抽卡 / gen_critic 评分 / llm_clipper / yue_music …）
│    └─ 主题/配置：theme_tokens / config_manager（画布通道走 data/canvas_appearance.json，别用 QSettings）
├─ 画布前端  vendor/shiguang-canvas/src（48,535 行 TS/TSX；Stage3D.tsx 4,660 行为最大文件）
├─ 插件层   app/plugins/（7,209 行：18 个转场插件 + ai_effects_plugin + PLUGIN_STANDARD 两套注册表）
├─ 技能层   app/skills/（2,435 行）+ app/integrations/（523 行）
└─ 质量体系  scripts/（4,533 行，门禁）+ _verify/（18,714 行，回归）+ app/tests（18,477 行）
```

| 目录 | 行数 | 职责 |
|---|---|---|
| `app/core` | 97,864 | Agent/画布桥/AI 引擎/主题/配置内核 |
| `app/modules`（lego 98 文件） | 77,321 | 全部 UI 模块：剪辑、首页、设置、角色库、文案… |
| `app/plugins` | 7,209 | 转场/特效插件（id 注册表为 **`extensions`**） |
| `app/skills` + `app/integrations` | 2,958 | Agent 技能 + 外部集成 |
| `app/tests` | 18,477 | pytest 单元测试 |
| `vendor/shiguang-canvas/src` | 48,535 | 画布前端唯一源码（双宿主共用） |
| `scripts` + `_verify` | 23,247 | 11 道门禁 + 回归脚本 |

## 5. 核心不变量（改动前必读 10 条）

1. **真相源** = `EditorModule._clips`（勿用 `AppState` / 孤儿 `ExportRenderer`）；
   跨线程共享必须持 `RLock`：整段替换 `with self._clips_lock:`，遍历用 `_clips_snapshot()`，
   绝不把 `self._clips` 直接交给 `json.dump`。
2. **插件两套注册表**：`ExtensionsRegistry`（app/core/extension_base.py）+ `PluginManager`（app/core/plugin_manager.py），真家在 `app/plugins/`。
3. **冻结区 9 zone / 85 锁点**：守卫 `scripts/frozen_zone_guard.py`（无参即校验，`--update` 重锁基线）。
   改 zone 须同步 4 处：`frozen_zones.json` · `docs/现行技术文档.md §5` · `.cursor/rules/frozen-zones.mdc`。
4. **两套独立版本号**：主程序 `app/version.py`；画布 `canvasVersion.ts`。改画布版本三件套：
   `canvasVersion.ts` → `package.json` → `docs/CHANGELOG.md`。禁内联版本字符串。
5. **Agent 常量单一来源** = `app/core/agent_constants.py`；**能力元数据唯一入口** =
   `app/core/agent_capability_catalog.py`（目录表加一行 + `verify_catalog_consistency()` 守卫）。
6. **音画纠偏 ~280ms**（冻结区），勿压回 80ms。
7. **内联样式 = 主题盲区**：新控件一律走 `theme_manager._build_qss` 模板，勿写内联 hex；
   新增 `setObjectName("x")` 后必须 grep 确认 QSS 里存在 `#x`（同一天踩过 3 次）。
8. **主题配色单一真相源** = `app/core/theme_tokens.py`（DARK/LIGHT/MOTION 三表 57 keys/套）。
9. **静默 except 判定线**：UI 绘制 `pass` 可接受；状态机/资源路径不可接受（须 `logger.debug(..., exc_info=True)`）。
10. **`switch_to_module()` 对 `nav_hidden` 模块静默无效**——打开隐藏模块必须走 `_perform_module_load` / `_activate_module`。

## 6. 冻结区地图（9 zone）

| zone | 锁点 | 内容 |
|---|---|---|
| `playback-av` | 15 | 播放/音画对齐主链路 |
| `exit-media` | 4 | 退出媒体清理 |
| `clip-transform` | 整文件级 | 片段变换 |
| `transform-bake` | 6 | 变换烘焙 |
| `canvas-transform` | 7 | 画布侧变换 |
| `plugin-host-ui` | 3 | 插件宿主 UI |
| `plugin-store-catalog` | 2 | 插件商店目录 |
| `stage3d-core` | 整文件级 | 3D 舞台核心 |
| `canvas-magnetic-intent` | 33 整文件 | 磁吸画布（任何画布改动需解冻） |

流程纪律：**解冻 → 备份 → 改 → 回归 → `frozen_zone_guard.py --update` 重锁**。

## 7. 提交前门禁（11 道，`scripts/precommit_gates.sh` 入库版）

① ruff 逐文件存量棘轮（`ruff_gate.py`，只减不增）→ ② ruff format（仅警告）→
③ 冻结区守护 → ④ 稳定性门禁（裸 except / product-print / 未定义名）→
⑤ 粘合层契约等价性 → ⑥a 架构守护 `arch_guard.py --scan app` →
⑥b 双库一致性（`check_canvas_dual_repo.py`）→ ⑦ 前端 tsc 棘轮 / vitest / 质量棘轮 →
⑧ 单文件 2000 行守卫（存量冻结）→ ⑨ 路由 mixin 属性 → ⑩ pyqtSignal 参数类型 →
⑪ 素材不出域（`SHIGUANG_NO_EGRESS`）。

- 全量体检单入口：`bash scripts/check_all.sh`；回归：`_verify/run_all_checks.py`（优先 `.venv312`）。
- **静态全绿 ≠ 运行时没崩**：自绘控件（QPainter/QColor）交付标准 = 真机启动 + 打开该界面让 paintEvent 真跑。
- **提交必须原生 bash 发起**（`git commit -F 消息文件`），别用 Python 派生 git；
  并发会话共存时永不裸 `git commit`，必须路径限定 `-- <精确清单>`。
- 换版本号用整体 Write 改 `version.py`，改后必须 `frozen_zone_guard.py --update`。

## 8. 已知环境事实（别误诊）

- 沙箱 `tempfile.gettempdir()` 回退到 cwd ⇒ 临时文件统一钉 `.workbuddy/tmp`。
- `.venv312` 依赖最全；系统 Python 3.14 启动出误导告警；「未检测到 GPU」是假告警（探测走 nvidia-smi）。
- 画布白屏 = Chromium 沙箱起不来，修法 `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`。
- 画布 CSS 别用 `body:has(...)`（Qt WebEngine 对 `:has()` invalidation 不可靠），正解 MutationObserver + 内联样式。
- 副库 `vendor/AI-Canvas-tauri` origin 是第三方仓库，**绝对不要 push**；其 eslint 已豁免 `src/libtv/**`。
- numpy 钉死 1.26.4（numba 0.64 约束）；moviepy/opencv/librosa/mediapipe/anthropic 及前端 vite6/ts5/vitest2 均 MAJOR 禁升。
- 冷启动已优化（依赖探测 `find_spec`，27s → 0.02s）；PyQt6↔mediapipe 有 DLL 加载顺序冲突，姿态推理必须留在子进程。

## 9. 文档索引（权威顺序）

| 优先级 | 文档 | 用途 |
|---|---|---|
| ★★★ | `docs/现行技术文档.md` | **唯一开发事实源**（架构/活路径/门禁/规范） |
| ★★★ | `docs/CHANGELOG.md` | 逐版变更明细（含踩坑复盘） |
| ★★☆ | `docs/knowledge/INDEX.md` | 结构化知识库（00–19：00 概览 · 05 已知问题 · 08 冻结区 · 17 磁吸/动捕 · 19 画布概论） |
| ★★☆ | `docs/接手速查卡.md` | 日常操作 / 红线 / 假警报速查 |
| ★☆☆ | `docs/_archive/` | 历史归档（不作为现行依据） |
| ★☆☆ | `docs/零基础学习路径与恶补计划.md` · `docs/求职准备-技术面清单与角色定位.md` | 负责人个人向 |

## 10. 快速上手命令

```bash
# 启动主程序（真机窗口）
启动AI短剧编辑器.bat        # 或 python app/main_qt6.py（用 .venv312）

# 画布前端开发（改 vendor/shiguang-canvas 后）
cd vendor/shiguang-canvas && node node_modules/vite/bin/vite.js build

# 提交前全量体检
bash scripts/check_all.sh

# 单独跑门禁
python scripts/frozen_zone_guard.py          # 冻结区校验
python scripts/ruff_gate.py --report         # ruff 棘轮报告
node node_modules/typescript/bin/tsc --noEmit  # 前端类型检查（在画布目录）

# 回归（优先 .venv312）
python _verify/run_all_checks.py
```

---

*本包覆盖：定位 / 架构 / 规模 / 不变量 / 冻结区 / 门禁 / 环境坑 / 文档索引 / 命令。*
*数据来源：2026-10-11 实测（version.py、wc -l、frozen_zones.json、git log），非记忆复述。*
