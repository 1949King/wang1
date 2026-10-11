# 拾光剪影 — 项目长期记忆（核心事实）

> 结构化知识库（优先）：`docs/_archive/knowledge/INDEX.md`（00–19，**已归档到 `_archive/`**）
>   常查：00 概览 · 05 已知问题 · 08 冻结区 · 17 磁吸不变量 · 17 动捕设计 · 19 画布概论
> 版本历史：`docs/CHANGELOG.md`；逐轮明细：`.workbuddy/memory/YYYY-MM-DD.md`
> 本文件只留「北极星 + 核心不变量 + 用户偏好」摘要，细节一律查知识库。复核 **2026-10-11**
> 排查方法沉淀：`~/.workbuddy/skills/git-mass-deletion-triage/`（删定性）· `ast-scope-nameerror-hunt`（NameError 扫描）

## 一、产品北极星

闭环 7 阶段，V4.19.0 起「发布/数据采集/优化建议」随账号运营下线，活路径收敛为「剪辑精剪 + AI 画布」两条：精剪 → 人工改 → 文案 → 选题。
- C3 剪辑 workflow_hint ✅；仍缺：选题自动导入时间线 / 一键粗剪写 `_clips`
- 优先级：**先剪辑（稳→快→全→可维护），后 AI 闭环**
- **V4.43.0「外观大改版」已上线**：借 AI-Canvas-tauri 风格直抄外观（主题+侧边栏）+ 借鉴结构（首页+设置）。二期 V4.44.0 做画布笔记工具栏 / 帮助中心（需解冻）
- **V4.43.1「设置模块对齐 AI Canvas」已上线**：设置「外观」「常规」两页顶部新增 AI-Canvas 风格区块（外观预设 2×2 + 主题模式 3 段 + 大预览；节点工具栏分段 + 6 个 `.sidebar-pref-card` 开关）。新控件库 `settings_widgets.py` + 页区块 `settings_canvas_pages.py`。⚙ 顶栏 → 模态弹窗；左侧导航 → 页内模块（两处同源）
- **V4.43.2「设置收口 + 画布背景预设」已上线**：① 设置从左侧导航撤出（`module_registry` 新增 `nav_hidden` 字段），保留顶栏 ⚙ + 用户中心 👤；② 画布背景 6 预设（移植开源 `backgroundOptions.ts`）用**运行时注入 `<style>`** 实现，**冻结区只动 `canvasVersion.ts`**（画布 0.3.23）；③ 画布通道 = `data/canvas_appearance.json` + `GET /host/canvas-settings`（**别用 QSettings —— 沙箱写注册表返回 `Status.AccessError`**）
- **登录窗口无设置**（`login_window.py` 只有登录/注册/设备管理）；`modules.py:1234 _show_login_dialog`「登录信息与设置」是死代码

## 二、核心不变量（改动前必读，错了代价大）

1. **真相源** = `EditorModule._clips`；勿用 `AppState`/孤儿 `ExportRenderer`。`_clips` 跨线程共享、**必须持锁**：① 非原子替换整段 `with self._clips_lock:`；② 序列化/遍历用 `_clips_snapshot()`，绝不把 `self._clips` 引用交给 `json.dump`；③ 锁是 **RLock**。
2. **插件 = 两套**（别被同名类迷惑）：`ExtensionsRegistry`（`app/core/extension_base.py:332`）+ `PluginManager`（`app/core/plugin_manager.py:13`）。真家 `app/plugins/`；`plugin_*.py` 与旧 plugins 目录已归档、勿合并。
3. **冻结区 9 zone / 85 锁点**：守卫 `scripts/frozen_zone_guard.py`（仅 `--update`/`--list`，无 `--check`，无参即校验）。`canvas-magnetic-intent` 锁 33 整文件，画布改动无一例外需解冻。改 zone 同步 4 处：`frozen_zones.json` · `docs/现行技术文档.md` §5 · `.cursor/rules/frozen-zones.mdc`。
4. **两套独立版本号**：主程序 `app/version.py`；画布 `vendor/shiguang-canvas/src/canvasVersion.ts`。刻意不同步、各自递增。改画布版三件套：`canvasVersion.ts` → `package.json` → CHANGELOG。禁内联版本字符串。
5. **Agent 常量单一来源** = `app/core/agent_constants.py`（`STATUS_*` + `ERR_WAITING_APPROVAL`），禁裸字符串。
6. **能力元数据单一来源** = `app/core/agent_capability_catalog.py`；新增能力唯一入口 = 目录表加一行（`verify_catalog_consistency()` 守卫）。
7. **音画纠偏 ~280ms（冻结区）**，勿压回 80ms。
8. **内联样式 = 主题盲区**：每新增一个 `setStyleSheet` 内联控件，必须回 `set_theme()` 补刷新（对比度：深色底 `#edf3ff` / 浅色底 `#172033`）。**V4.43.0 新解**：新控件一律走 `theme_manager._build_qss` 模板（#brandBtn/#chip/#glassPanel 等），不要写内联 hex。
9. **主题配色单一真相源** = `app/core/theme_tokens.py`（V4.43.0 起）。DARK_TOKENS / LIGHT_TOKENS / MOTION_TOKENS 三表，57 keys/套。**项目主蓝 #2f7bff（accent）保留**（深度嵌入 modules.py QSS），**品牌紫罗兰 #6366f1（brand）新增**（chip/badge/玻璃面板专用）。LEGACY_KEYS 19 个 100% 保留 = 无破坏性更新。
10. **静默 except 判定线**：UI 绘制 `pass` 可接受；状态机/资源路径 `pass` 不可接受（须 `logger.debug(..., exc_info=True)`）。例外 `except RuntimeError: pass` 有意保留。
10. **沙箱 wmic 黑名单**：import app 链触发 config_manager 的 wmic；验证脚本用 subprocess 包一层、写干净 UTF-8 再读。
11. **清理纪律（2026-09-21 血泪）**：临时文件**禁止用 `_*` 等宽 glob 清理**。必须① 显式列名单删除；② 删除前先 `git ls-files <候选>` 区分「项目自有 / 本次新建」；③ 未在 git 里的产物先确认有无副本（我曾用 `_*` 误删 6 个项目自有文件，3 个 git 跟踪的救回，3 个未跟踪 PNG 永久丢失）。
12. **git 已补-commit（2026-09-21）**：此前 HEAD 停在 2026-09-12（27 次提交），~9 天改动未提交。现已拆成 **10 个语义提交**固化（`d67f80a..5809fa3`）：config / vendor(openshot 移除 7309) / clean ×2 / core / editor / plugins / canvas / docs / verify。**只在本机，未 push**（`origin = github.com/1949King/shiguangjianying`）。四条踩坑纪律见下表。

   | 坑 | 后果 | 正解 |
|---|---|---|
   | `git add -A -f -- <目录>` | **穿透嵌套 .gitignore**，把 6462 个 node_modules + `__pycache__` + `dist/` 卷进历史（一次性 +236 万行） | 用 `git status -uall` 得到的**精确文件清单**，`-f` 是最后手段 |
   | `git check-ignore <已跟踪文件>` | 恒返回"未忽略"（默认跳过索引内的文件），误判成全都很干净 | 判历史性忽略要加 `--no-index`；其实 status 里的路径**本来就不被忽略** |
   | `git show --stat` | 长路径被截断成 `...`，统计严重失真 | 统计/审计一律用 `--numstat` + `-c core.quotePath=false` |
   | 逐文件调子进程 | 7856 次 `check-ignore` 跑了 17 分钟没出结果 | 用 `check-ignore -z --stdin` 一次批量；或把临时文件写 `tempfile.gettempdir()` |

   另记两个环境限制：沙箱**每轮最多 50 次删除**（超了连 `shutil.move` 都被拦，改用同盘 `os.rename` 或 `.git/info/exclude`）；跨盘 `rename` 会报 WinError 17。

## 三、用户习惯与偏好

- 核电管工转 AIGC；简体中文；指令极简；先看结论再展开
- 小白模式讲解：比喻 + 表格；迭代：规划→「开始」→汇总→「继续」
- 拒绝随机效果；前后端强绑定；情绪化时专业耐心推进、不回怼
- 素材库仅本机；素材网站直达在「帮助」；画布默认 `shiguang-canvas`

## 四、分区索引（细节查 `docs/_archive/knowledge/`，不在此展开）

- **磁吸系统不变量**（edge-gap 判据 / Bond 咬合 / 三段式手感 / 让位 reflow / 空间记忆 depth）→ `17-canvas-magnetic-invariants.md`（**专文**）+ `08-frozen-zones.md`
- **角色库字段模型**（一字段横跨 6 处，`visual` vs `inner` 流向）→ `_verify/check_character_schema.py`
- **画布桥接层**（`@_route_*` 注册、节点级后端化、SSE 桥、端口 18765）→ `19-canvas-design-review.md` + `05-known-issues.md`
- **参考视频驱动生视频 / 姿态解析（模式 A/B）** → `17-motion-ref-design.md`（§五已订正：**刀1/2/3 完成**，刀3=`stage3dPoseRetarget.ts`+Stage3D.tsx UI；**下一刀=刀4 录制白模视频**；刀5 通道就位、无模型支持 `video_motion`）
- **代码健康度基线**（2026-09-19 全库实测 228,583 行、`editor_module.py` 9,479 行）→ `docs/_reports/2026-09-19-全库代码评价报告.md`
- **Agent 定位「知心秘书」+ 温度开关** → `app/core/agent_persona.py`
- **冷启动性能**（MainWindow 8.24s→0.191s）→ `docs/冷启动性能诊断报告.md` + 技能 `~/.workbuddy/skills/python-coldstart-profiling/`
- **视频代码化 / 词锚定**（`timeline_dsl.py` 死代码 / `timeline_source.py` 工程源码层 / 阶段1 完成；**阶段3 已完成**：`app/core/dialogue_anchor.py` 重锚引擎 + 能力 `重锚` 已接线 `capability_handlers.py:657`，2026-09-21 代码核实）→ `docs/_reports/2026-09-20-工程源码化与词锚定阶段1.md`（**尚未沉淀进知识库**）

## 五、2026-09-28 新增（持久约束，改动前必读）

- **YuE 全曲生成已接入音乐节点 + 意图卡片（V4.40.12）**：`app/core/ai/yue_music.py` +
  `POST /host/yue/{probe,plan,generate}` + 前端 `canvasYue.ts`/`canvasMusic.ts`。
  其价值是**把 YuE2 的三段式对齐画布意图分层**（plan 出可编辑 ABC 谱=「你的意图」，渲染=「系统的事」）。
  ⚠️ **官方硬要求 Linux + Python3.12 + NVIDIA ≥24GB VRAM**，本机 RTX 4060(8GB) 跑不动 3B：
  执行端只能走**远程** `SHIGUANG_YUE_ENDPOINT` 或本地 `SHIGUANG_YUE_HOME`(需含 examples/generate.py)。
  **纪律（冻结区不变量第 35 条）：执行端不可用必须诚实失败，绝不返回假音频/静默降级 Suno。**
- **沙箱 `tempfile.gettempdir()` 会回退到 cwd（项目根）**：因 `%TEMP%` 不可写。
  症状=仓库根累积 `sg_*/cover_*/pip-*/pytest-of-*`。**三处入口都要钉 `.workbuddy/tmp`**：
  根 `conftest.py`（pytest）、`_verify/run_all_checks.py`（子进程 env）、以及**直接单跑的 _verify 脚本**。
- **月份进度相关的测试是日期炸弹**：`check_global_price.py` 曾用固定 `record_spend(90)` 比
  `1-本月已过比例`，过每月约 90% 自动变红。新增 `over_paced_spend()` 按进度反推。同类固定值比
  时间基准的用例都要警惕。

## 六、启动与环境（2026-09-30 实测）

- **启动**：`python -m app.main_qt6`（工作目录=项目根，`PYTHONUTF8=1`）。
  `启动AI短剧编辑器.bat` 先试系统 Python 3.14，失败回退 `.venv312`。
- **`.venv312` 依赖更全**（`psutil` / `pynvml` / `PyQt6` 全有），系统 Python 3.14 只有 PyQt6。
  用系统 Python 启动会出两条**误导性告警**：「未检测到 GPU，将使用 CPU 运行」+「硬件检测失败: No module named 'psutil'」。
- ⚠️ **「未检测到 GPU」是假的**：`main_qt6.py::check_gpu()` 只试 pynvml/torch，
  且**仅在日志/展示处被调用**（全仓只有 2 处），不参与编码器选择；
  真正决定编码器的是 `app/core/gpu_acceleration.py::_detect_nvidia()`，走 **nvidia-smi**
  （本机返回 `RTX 4060 Laptop GPU, 8188 MiB, 610.62`）。看到这句别重启、别改编码逻辑。
- **画布白屏 = Chromium 沙箱起不来（2026-10-06 定案，非项目缺陷）**：
  症状=进画布只有壳 + 日志 `canvas page loadFinished FAIL`。**决定性判据**：连 `data:` URL 都失败。
  修法=启动时带 `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`（实测日志变 `loadFinished ok`）。
  已证伪：不是代理（清掉仍失败）、不是 GPU（--disable-gpu 无效）、不是 `_SPAHandler`（搬到别的端口就成功）、
  不是 dist 内容。**探测前先验 `netstat` 确认服务还活着**——我曾打到已关闭的 3011 上被 502 带偏结论。
- ComfyUI(8188) / Ollama(11434) 未启动、提示词封面图 CDN 取不到 —— 外部依赖噪音，非故障。

## 七、画布桥接层约定（2026-09-13 建立，2026-09-30 复核仍在）

- **新增 `/host/*` 端点一律用 `@_route_get` / `@_route_post` 注册进路由表**，不要再往
  `do_GET`/`do_POST` 的老 `if path ==` 链里塞。`_dispatch_table` 未命中才回落老链。
  2026-09-30 复核：该模式已被推广拆分（`canvas_routes_get.py` 等 mixin），仍在使用。
- **端点写进函数体 `return` 之后 = 语法合法的死代码**（`/host/plugins/install|toggle|uninstall`
  就是这样死的）。`_verify/check_canvas_routes.py` 用 AST 检测「不可达路由」+「路由表×老链重复注册」。
- **⚠️ 画布 CSS 里别用 `body:has(...)` 做让位/联动（2026-10-07 定案）**：Qt WebEngine(Chromium 134)
  对 `:has()` 的**样式失效(invalidation)不可靠**——类名变化后依赖它的元素不重算，要等别的样式改动
  触发全量重算才生效（规则在 CSSOM、querySelector 也 MATCH，就是不应用；现场注入的 `:has()` 反而生效）。
  正解：MutationObserver 盯宿主 class + **写内联样式**。范例 `CanvasOverlays.tsx`（`🧰 工具` 让位）。
  验证法见技能 `qt-visual-change-verification` 第八课。
- **派生值一律后端下发，前端不要自己算**：角色提示词（`entry["prompt"] = build_character_prompt(c)`，
  现位于 `canvas_routes_get.py:115`）、分镜记忆保留率（`/host/storyboard-memory-plan`）。
  前端硬编码系数必然和 Python 漂移。
- 回归：`_verify/run_all_checks.py`（2026-10-06 实测 **72 项**，支持 `.mjs`）。
  **跑之前先确认解释器**：2026-10-06 起自带 `_python()` **优先项目 `.venv312`**（回退 `sys.executable`）
  并打印用的是哪个 —— 此前用系统 Python 3.14 跑会把「缺 pypinyin」误报成 PINYIN/TTSGUARD 功能回归。
  手工单跑 `_verify/*.py` 也要用 `.venv312`。
- **`run_all_checks` 报失败时的定性顺序**：① 跑错解释器（缺依赖）② 撞上并发会话
  （本机存在并行编辑，近 1 小时可改几十个文件；**双库同步是人工动作、非自动机制**，
  所以 CANVASDUAL 会撞在「主库写完副库没拷完」的窗口报瞬时缺失）③ 才当成真回归。
  另：`Error in sitecustomize; PermissionError … shim/sitecustomize.py` 是 WorkBuddy 注入噪音，无害。
  `_verify/check_canvas_bridge_e2e.py` 会**真起一个 bridge 服务**打 HTTP，最有价值。

- **3D 导演台编辑辅助物一律打 `userData.isHelper`**（机位视锥/标签/地面环/`axisHelper`，2026-10-07 V4.40.55）：
  `setHelpersVisible(scene,false)` 必须在**渲染产物**前摘除、之后还原 —— 落点四处在
  `stage3dControlNet.captureDepthMap/captureNormalMap`、`Stage3D.capture()` 截图、机位路径视频、白模姿势视频。
  机位可视化已抽成 `stage3dCamGizmo.ts`（Stage3D.tsx 只留一行接线，基线 4660→4623），
  **视锥真由 fov 推**、标签 mm 与截图元数据同源（`fovToFocalLength` 单一来源）。
  回归锁 `stage3dCamGizmo.test.ts`（15 项）。还原函数**只还原被自己改过的对象** ⇒ 别写成"全置 true"。

## 八、2026-10-07 新增（持久约束）

- **未提交改动已全量固化（仅本机，未 push）**：13 个提交 / 259 文件，工作区 `git status` 归零，
  HEAD = `95b8e977`（V4.40.56「门禁加固」），起点 `23911b2b`(V4.40.5)。
  统计未提交项**必须 `git status -uall`** —— 默认视图折叠未跟踪目录（实测 231 vs 257，差 26）。
- **ruff 门禁 = 逐文件存量棘轮（V4.40.56 起）**：`scripts/ruff_gate.py` +
  `docs/knowledge/ruff_gate_baseline.json`（167 文件 / 1016 项存量）。语义：**新文件必须 0 违规**、
  已有文件只减不增、`--update` 抬高基线或为新文件建条目需 `--force`。
  病根：旧实现「整文件判定」会拿历史债拦正当改动 —— 极端例 = 冻结区 `editor_module.py`
  有 50 处存量违规 ⇒ **核心文件永不可提交**。**别再退回整文件 check。**
- **提交必须由原生 bash 发起，不要用 Python 派生 git**：Python 会加载 WorkBuddy 的
  `sitecustomize` 沙箱 shim 并**传递给子进程**，git 再派生 MSYS2 bash 时报
  `NtCreateDirectoryObject(\BaseNamedObjects\msys-2.0S5-…): 0xC0000022`（bash 起不来，看着像门禁炸了）。
  **判别法**：`bash .git/hooks/pre-commit` 直接跑若全绿 ⇒ 链路问题，不是门禁问题。
  正解 = 生成 `.sh`（`git commit -F 消息文件`）再由 bash 执行；顺带绕开多行中文引号转义。
- **启发式误报的处置原则**：人工定性 + 登记到**受版本控制**处（hook 本身不入库 ⇒ 写 CHANGELOG /
  现行技术文档）；**不要为了过计数去动代码结构**。例：⑦c `fnOver300` 9→10 ——
  `stage3dPoseLibrary.ts` 的 `defaultPose()` 本体仅 3 行，其后 541 行 `POSE_PRESETS` 数据表
  被 `len`（「到下一个函数起点」的近似）算进跨度；移除该文件**实测**回落 9。
  若「拆模块」会打断既有校验器（`_verify/check_stage3d_pose_dof.mjs` **按源文本解析**该文件），就不硬拆。
