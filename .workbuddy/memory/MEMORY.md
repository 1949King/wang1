# 拾光剪影 — 项目长期记忆
> 深水区 `topics/`（neural-models · packaging · gguf-quant · agent-blueprint · canvas-bridge · team-collab）；日志 `memory/YYYY-MM-DD.md`；工作法 `~/.workbuddy/skills/`。机制：本文件是项目记忆唯一真相源，在 git 里（`.workbuddy` 被 gitignore ⇒ 新文件须 `git add -f`）；跨项目档案在账号级 MEMORY.md（不在本仓库）；**云端 profile 服务端自动学习，本地改不了**，别许诺「已同步云端」。入口表见 `AGENTS.md`。

## 〇、规模与定位
- 生产代码 **≈29.3 万行**：`app/` 下 core+modules+plugins 222,006 行/503 文件；画布 `canvas-core/src` 61,588 行/206 文件；测试 45,049 行。
- 画布包 2026-11-04 由 `libtv` 改名 **`canvas-core`**，旧路径全失效。
- 🔴 **定位（2026-10-28 用户纠正）**：**通用创意生产工具/创意工作台，不是「短剧剪辑工具」**。输入想法/素材 → 输出 图·视频·3D·成片；画布是工作台不是流水线。对标 Figma/Miro/Canva/ComfyUI/Runway/剪映；禁拿「短剧」「懂短剧连续性」当定位与护城河；S0-S5 只是内置范式之一。

## 一、核心不变量
1. 时间线真相源 `EditorModule._clips`；跨线程整段替换带 `_clips_lock`；序列化用 `_clips_snapshot()`，禁把 `_clips` 交 `json.dump`。
2. 插件两套：`ExtensionsRegistry`(extension_base.py:332) + `PluginManager`(plugin_manager.py:13)；真家 `app/plugins/`；注册表 id 是 `extensions`（非 `plugins`）。
3. 冻结区 9 zone（锁数动态，以守卫输出为准；2026-11-20 重锁 121，T5 +5 前端文件）：改 zone 同步 4 处 —— `docs/knowledge/frozen_zones.json`（**字符串手术**，禁 json.dump / `sorted()`，HEAD 原顺序尾部追加）· `现行技术文档.md §5` · `.cursor/rules/frozen-zones.mdc` · 重锁；新文件须登记。`app/core/neural/` 不在冻结区。
4. 两套独立版本号：`app/version.py`（主）与 `canvasVersion.ts`→`package.json`→CHANGELOG（画布）；禁内联版本字符串。
5. `agent_capability_catalog.py` 加行即注册，`verify_catalog_consistency()` 双向守卫；`CapabilityResult` 字段是 `success` 不是 `ok`。
6. 音画纠偏 ~280ms（冻结区），勿压回 80ms。
7. 主题真相源 `theme_tokens.py`（三表 57 keys）；内联 `setStyleSheet` = 主题盲区，须回 `set_theme()`；`setObjectName` 后 grep `#x` 确认 QSS 有规则。
8. 静默 except：UI 绘制 pass 可；状态机/资源路径须 `logger.debug(..., exc_info=True)`。沙箱 wmic 黑名单：import app 链触发，验证脚本 subprocess 包一层。

## 二、用户偏好
简体中文；指令极简；**先结论后展开**；小白模式（比喻+表格）；拒绝随机效果；要证据（文件+行号）；被纠正直接认错重查不辩解。🔴「迭代设计文档」≠把数字改对，要设计增量。🔴 他问「够不够用」时先按现有流程逐段找缺口，别答「该加什么新功能」。🔴 **下判断前先分清字段是「手工写死」还是「动态推导」**。

## 三、持久约束（血泪）
### Qt / 启动 / 界面
- 🔴 **2026-11-16 起唯一 Qt 绑定为 PySide6 6.10.2**（Essentials / Addons / shiboken6 同版），不保留 PyQt6 双绑定兼容层；`pyqtSignal/pyqtSlot/pyqtProperty` 对应 `Signal/Slot/Property`。PySide6 的 `QMetaObject.invokeMethod` 目标必须注册 `@Slot`；不支持直接 `Q_ARG(np.ndarray/object)`。WebEngine 仍须早于 `QApplication` 导入、非空 argv、`--no-sandbox` 先置；失败继续回退系统浏览器。绑定切换不代表已消除 torch / sentencepiece / OTIO 原生冲突，既有子进程与打包隔离继续保留。
- 🔴 **启动必须优先 `.venv312`**（`C:\Python314` 有 PyQt6 无 torch ⇒ 本地模型全 `available:false`）。正式入口 `.venv312\Scripts\python.exe -m app.main_qt6`（根目录 bat / `docs/接手速查卡.md` 口径）；起进程用 python `subprocess` + `CREATE_NEW_CONSOLE|CREATE_NEW_PROCESS_GROUP`，**禁用 DETACHED_PROCESS + stdout 重定向**（应用 ~60s 后因 window-CLOSE 自杀）。判存活认内存大的子进程，cmdline 含 `app.main_qt6`。🔴 **WorkBuddy Bash 会话里 Popen 起的子进程会在命令结束时被沙箱清掉**（实测 PID 起来后复查零进程、零日志）⇒ 必须用「前台保活」：应用作为 `run_in_background` 任务的主进程跑，stdout**重定向到文件**（不是管道，避 window-CLOSE 自杀）。验活三件套：ctypes `EnumWindows` 查窗口标题 / psutil 查 747MB 级真进程 / 日志尾部「应用启动成功」。启动后桥与静态服三端口全 closed 是**正常按需启动**，不是失败判据。
- 🔴 **Qt6.11 WebEngine 必须给 QApplication 非空 argv**（`QApplication([])` ⇒ 渲染进程 `0xC0000409`）；白屏另查 `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`，CSS 别用 `body:has(...)`。**PyQt6 别对 Qt 枚举 `int()`**（TypeError 被 `except: pass` 吞 ⇒ console 零输出，用 `str(level)`）。
- 🔴 **QtWebEngine 里禁用 `QMenu.exec()` / 长期存活 `popup()` 做右键菜单**（嵌套事件循环 ⇒ `0xc0000005`；popup 不消失 ⇒ 黑块堆叠 + AppHang）。现 Qt 菜单默认关（`SHIGUANG_QT_CTX_MENU=1` 才开），右键统一走前端 React 菜单。
- 🔴 **QtWebEngine 原生 `<select>` 弹层是白块**（OS 级弹层不走网页合成器；2026-11-21 实测）⇒ 下拉统一用前端渲染 `SgSelect.tsx`（options/value/onChange 与原生同构，`AgentPanel.tsx`:1173 / `StudioPages.tsx`:445 已换）；画布仍有其他原生 select 残留，复现白块按同法替换。与上条 QMenu.exec 禁令同源：原生弹层在 WebEngine 里不可靠。
- 🔴 **清空 Qt 布局先 `hide()` 再 `setParent(None)`**（可见控件脱离父级变顶层窗口，一次搜索实测 +583 个小窗）。
- 🔴 **Qt 页面验收两条腿**：`QT_QPA_PLATFORM=offscreen` 验结构、真实窗口 `QTimer.singleShot` 后 `grab()` 验像素。**QLabel 默认 PlainText ⇒ `**x**` 原样画到界面**；QGroupBox 标题深底偏暗需显式给色。
- 🔴 **不要整文件 read→write**（单次读取有上限会静默截断，App.tsx 1860→1175 行）；大文件用 edit / 行号 splice，改完核行数 + `git diff --stat`。
- 🔴 **WebEngine localStorage 不持久且 `setItem` 不报错** ⇒ 跨重启状态必须写服务端（`data/compliance_acceptance.json` + `/host/compliance/*`）。
- 帮助页正文真源 `docs/help/<id>.md`：加话题 = `topics` 加一行 + `_xxx()` 三行 + 落 md；`_render_markdown` 只认 `#/##/###`、`- `、`> `、`|表格|`、`---`。
- 模块懒加载：`_on_module_selected` → `_perform_module_load` → `widget_class()` → `set_module_widget` → `_activate_module`；`on_activated()` 是死钩子。`switch_to_module()` 对 `nav_hidden` 静默无效 ⇒ 走 `_perform_module_load`。

### 画布 / 前后端桥
- 🔴 **画布静态服务有 SPA 兜底**：缺文件改写 `/index.html` ⇒ 200 + HTML，前端 ESM import 报 `Unexpected token '<'`。排查看 body 不看状态码。
- 🔴 **Qt ↔ 画布唤起用「探测全局函数」不用 `dispatchEvent`**（后者页面未加载也返成功）：画布挂 `window.__sgTeamOpen`，PyQt 侧 `runJavaScript` 拿 'ok'/'pending' 轮询。
- 🔴 **浮动面板一律 `createPortal(..., document.body)`**：`backdrop-filter`（及 filter/transform）祖先会成为 `position:fixed` 后代的包含块（团队面板挂 `.ic-nav` 后 420px 只剩 46px 窄缝）。
- 🔴 **入口位置由能力归属层级决定，不由体积守卫有没有空位决定**：工作区级能力挂常驻 `AppNav`（团队入口曾塞画布第二顶栏被 `showWorkspace` 挡住，另 8 个界面全看不见）。
- 🔴 **Vitest node 环境用 `renderToStaticMarkup()` 测 Zustand 组件时，store 默认读 `getInitialState()` 而非刚 `setState()` 的当前态** ⇒ 空面板会同时制造可生成项假失败、不可生成项假阳性；只 mock React `useSyncExternalStore` 的服务端读取为当前 `getSnapshot()`，真实 store / 节点工厂 / 组件不动，并断言非生成面板确实渲染。回归样例：`src/novice/generateEntry.test.ts`。
- 🔴 **`SkeletonUtils.clone` 后先 `updateMatrixWorld(true)` 再测包围盒**（脏矩阵量出 1/33 假尺寸）；SkinnedMesh 用 `setFromObject(obj, true)`；尺寸自检必须进 `tick()` 渲染循环（挂 actors effect = 死代码）；画布里 `tick` 是高频函数名，新函数别用。
- **两条单通道（禁造第二套）**：3D 产物入轨 = `stage3dArtifacts.ts::sendArtifactToTimeline()` → `POST /ingest_path`；角色库→导演台 = store `requestStage3dCast` → `stage3dCastSeq` → `useStage3dCast()`。生成模型选择唯一真源 `generationModels.ts`；图像生成走 `localImage.ts::generateImageUnified`，Agent「模型」页是唯一可见入口。
- **体积守卫**（`_verify/check_file_size.py`，阈值 2000+容差 30，基线 12 文件）：顶格 `CanvasShell.tsx`、`riggedHumanoid.ts`；`Stage3D.tsx`/`settings_module.py`/`editor_module.py` 余 1~2 行 ⇒ **新逻辑必须另开文件**。以脚本数字为准；`bridge.ts` 已不在基线。
- **`tsc` 棘轮**：`cd vendor/packages/canvas-core && node node_modules/typescript/bin/tsc --noEmit --pretty false`，基线 **37**。测试里 `.catch(e => e as Error & {code})` 会 +9 TS2339 ⇒ 写 `rejection(p)` helper。
- 🔴 **vitest include 仅 `*.test.ts`**（不含 `.test.tsx`）⇒ 组件测试须用 `React.createElement`（无 JSX），写成 `.test.tsx` 会静默不被跑。回归样例：`src/PanoramaViewer3D.test.ts`。
- 🔴 **画布整文件锁的冻结文件（`nodes.tsx`/`mediaExtraNodes.tsx`）常被并行会话重构** ⇒ 编辑前必重读真实内容 + `git status`，禁凭旧会话记忆接线（2026-11-20 实测 VideoNode export / EditableText 签名已变）。
- 🔴 **顶格零加行 ⇒ 路由另开 mixin 先例**（2026-11-20 T5）：往 `canvas_routes_post.py` 加路由顶破 2000 体积守卫 ⇒ 按 dub/roughcut 先例新建 `canvas_routes_scene3d.py` mixin + `canvas_server.py`（明写非冻结）import/继承接线。今后加路由先查目标文件行数，顶格就另开 mixin，不硬加。
- 🔴 **Agent 策略链必须 fail closed**：`CapabilityDispatcher` 的会话预算、`agent_policy.decide()`、审批判断任一环节自身异常，都必须返回失败且不得调用 handler；禁止只记日志后继续执行写能力。回归：`app/tests/test_agent_policy.py::test_dispatcher_policy_exception_fails_closed`。
- **孤儿端点差集法四扫描面**：画布 src 非注释行 / `canvas_server.py` JS 字面量 / `app/**/*.py` URL 拼接 / Rust `src-tauri/src/lib.rs`。
- 🔴 **套接字错误码先查 `app/core/team_discovery.py`**（全库唯一碰 UDP/sendto/recvfrom，`lan_ip` 自带兜底）；错误码必须翻人话（`friendly_socket_error` / `teamClient.netError`）；`hostCall` 的 `authHeaders()` 放 `try` 外面。

### 模型 / 生成
- 🔴 **本地模型细节全在 `topics/neural-models.md`**。秒记：① `verification=VERIFIED` 是**手工写死**，`_probe_local_video` 只管权重在不在盘、**不参与** verification；② `kernel_evidence.json` 是内核 vs stock 等价性，wan 缺画质数据不能登记；③ **Ollama 只服务文本模型，拉不了扩散模型**；④ `is_downloaded` 是 **Engine 静态方法**、无模块级同名函数，`_probe_local_video` 禁止 `_guess_model_kind(族名)`（恒 True），防回归须 AST 断言；⑤ 入口 `scripts/check_models.py`（`--all` 看 9 族全景、`--missing` 看缺什么）；⑥ 五族下载源在 `local_family_catalog.py`：**整仓体积 ≠ 下载量**、hunyuan 非 diffusers 不能拉、minimax_h3 无开放权重、落盘目录名须命中 `MODEL_KEYWORD_MAP`。
- 🔴 **「吃不吃图」真源 = `video_gen.available_models()` 的 `modes`，挂模型 id 不挂族名**：`wan21-t2v-1.3b` 只有 t2v，同族 `wan22-ti2v-5b` 是 t2v+i2v ⇒ 按族名推必错。判定只许在 `canvas_routes_local_video._model_modes()` 一处。auto 通道 `localModel` 三处调用方都不传 ⇒ 固定跳 SVD。
- 🔴 **SVD 图生视频输出尺寸必须随输入比例走**（硬编码 1024×576 ⇒ 人脸横向胖 1.78×），已加 `video_gen.fit_output_size`；**只有方形慢**（1024×576 9.5s/帧、576×1024 6.5s/帧、768×768 27.7s/帧，原因未定论）；**特写人脸第 10 帧畸变**，首帧完好。
- 🔴 **「让用户去社区自己挑」≠「程序自动抓」**（2026-11-15 用户纠正）：界面每行给**可点入口**（`neural/model_sources.py` → 行内 `sources`），下载交给人；链接只写核实过 200 的，查不到返空列表，**别编搜索页充数**。⚠️ `available_models()` 体积字段叫 **`download_gb`**（写 `size_gb` ⇒ 整列静默变空、不抛异常）。
- **内核族 `caps.verified` 是机器可核对承诺**：改 `VERIFIED` 须 `docs/knowledge/kernel_evidence.json` 该族 `passed=true`；与 `model_family` 的「族能跑通」是两个 verified，别混。
- YuE 全曲跑不动 ⇒ 执行端不可用必须诚实失败，绝不假音频。**人话 vs 假指标**：自检 `cpu=/gpu=` 曾写成 `(x @ x.T).sum()` 被当性能证据；凡「像指标」的输出要么有量纲真测量，要么同 seed 双端比 `max|Δ|`；「没测出来」≠「测出来了」，后端空串前端原样保留、禁填默认值；非法数值落 0 不猜；带 quality/tier/mode/level 的字段先核前端语义。

- **外部选型参考 `docs/_reports/2026-11-19-无界工作台工作流与模型参考清单.md`**（无界工作台 v0.24.3，2026-11-19 整理，只参考不接入）：H3 系列权重在 ModelScope 有 Comfy-Org/MiniMax-H3 重打包（**MiniMax H3 Community License，条款未读**；旧记「minimax_h3 无开放权重」指官方渠道，社区重打包≠官方开放）；YuE2 CC-BY-NC-4.0、4x-UltraSharp/AnimeSharp NC-SA ⇒ 商用排除；GPL 节点（ComfyUI/KJNodes/Goohaitools/hyperflow/Idol）只走 HTTP 不随包；TE_MAN/TE-Speed/SelfLift 授权链不完整不随包；优先池 Apache/BSD/MIT（Qwen3.5 GGUF、SeedVR2、RealESRGAN、Idol 权重、Florence-2 PromptGen）。

- 🔴 **RIFE v4.9 神经补帧已接线但权重须自取**（`neural/rife_engine.py`+`rife_net.py`+`video_interpolate_job.py`，MIT 署名 vendor）：`rife49.pth` 放 `thirdparty/models/`（或 env `SHIGUANG_RIFE_PATH/DIR`），**绝不自动下载**；缺失⇒`ok:false`+guidance 诚实提示，运行时异常⇒降级光流 `degraded=True`。许可证据+资源地址见 `docs/现行技术文档.md §40.30`，实现见 §40.31。
- 🔴 **四项优化权重全自取 + guidance 单一真源**（2026-11-20 T1–T5，§40.32）：realesrgan/lama/SD15-inpaint/Lightning-LoRA/depth-small 均 env+`thirdparty/models` 自取，绝不自动下载（`tool_weights.py` 登记）。**H3 条件放行用户已确认**：UI 常驻署名 "MiniMax H3"（`gateway_scene3d.H3_ATTRIBUTION`），地域中国大陆/营收≤2000万美元用户自担，输出禁训他模；副本 `license/third_party/MINIMAX-H3-Community-License.txt` 尾部 ~1KB 截断（**再分发前从权威 HF URL 补全**），NOTICE 第 3 条传导 5 条件；网关默认关。

### 打包 / 门禁 / 提交 / 沙箱
- 🔴 **打包细节 `topics/packaging.md`**：① 目录扫描型加载的 `app/plugins`、`app/skills`、`app/core/video_processing` **必须进 `build_release.SYNC_APP_SUBPKGS`**（进 PYZ 等于没进，缺了**静默返回 0**）；② 整目录拷包必须排 `.git`（只读 pack ⇒ `PermissionError [WinError 5]`）；③ `opentimelineio`/`mediapipe` 在冻结进程加载即崩；④ **NSIS 装不下**（makensis 32 位 ~1.8GB 上限，6.35GB ⇒ 无 Setup.exe）；`.nsi` 无 BOM ⇒ 中文乱码且退出码 0。
- 🔴 **CRT 必须随包**（2026-11-19 干净机弹「找不到 MSVCP140.dll」实测）：PyInstaller 不收系统 VC++ redist 的 CRT，构建机有 redist ⇒ 自检全过但干净机启动即弹窗。`build_release.ensure_vc_runtime()` 把 msvcp140/_1/_2、vcruntime140/_1、concrt140 从 System32 补到 **exe 根 + `_internal` 双份**（app-local，loader 优先搜 exe 目录），接线在补包后、自检前；契约测试钉死（`test_installer_contract.py` 21/21）。2026-11-20 重建版起目标机无需另装 redist。
- 🔴 **Inno 缺 `[Languages]` = 英文向导**（编译不报错、装完才发现；2026-11-21 实测）：`installer.iss`:48-53 必须显式 `Name: "chinesesimplified"; MessagesFile: "{#ROOT_DIR}\scripts\ChineseSimplified.isl"`；isl 为官方 6.5.0+ 翻译（LanguageID=$0804）**随仓库携带**（出包机 Inno Languages 目录实测无中文），契约 `test_inno_wizard_language_is_chinese` 钉死（26/26）。只配一种语言 ⇒ 不弹语言选择框，卸载器跟随中文。🔴 同 AppId 冒烟安装会覆盖本机真实安装的卸载注册表 ⇒ 测前 reg export 快照、测后 reg import 恢复（本轮快照 C:\SGSetup\reg_snapshot_lang.reg）。
- 🔴 **Inno 安装器/卸载器启动方式**（2026-11-22 实测）：GUI 子系统 ⇒ PS `&` 不等待（后续验证跑在安装前）；python `subprocess.run` 破坏二阶段 /SL5 句柄握手 ⇒ exit1 无日志；**必须 `Start-Process -Wait -PassThru`** 取 ExitCode。🔴 **主窗口无框自绘标题栏** ⇒ EnumWindows/GetWindowText 取不到「拾光剪影」标题；GUI 验活 = 进程存活 + **截屏**（CopyFromScreen）双判。🔴 **Lite `[Files]` 禁带 createallsubdirs**（为被排除 runtime\* 建空目录 ⇒ ensure_runtime_path 只判 isdir 假报 AI 可用；全量行保留）。🔴 **冻结引导器忽略 PYTHONIOENCODING**：GBK emoji print 崩在 MainWindow 前 = 双击静默退出根因；根 main_qt6.py:10-19 代码 reconfigure(utf-8, errors=replace)；冻结入口 = 根 main_qt6.py（非 app/main_qt6.py）。
- **Trae 沙箱写权限口径（2026-11-22，与下条 WorkBuddy Bash 口径不同，别混）**：python 子进程写文件仅限工作区（TEMP / C:\SGSetup 均 PermissionError，`dangerouslyDisableSandbox` 不改变该限制）；PS cmdlet 与 Start-Process 起的安装器/应用可写 C 盘 ⇒ 冒烟 stdout 用 `Start-Process -RedirectStandardOutput` 到 TEMP。
- 🔴 **稳定性门禁豁免逐行 + 必写理由**（`# stability-gate: allow-print（理由）` / `allow-swallow（理由）`）；合规只有 CLI stdout、结构性正常分支两类；**能真改就别豁免**，禁 `--update` 把违规写进基线。`run_all_checks.py` **不含**稳定性门禁 ⇒ 另跑 `scripts/stability_gate.py`。
- 🔴 **静态门禁全绿 ≠ 运行时没崩** ⇒ 自绘控件交付标准 = 真机启动 + paintEvent 真跑；**哈希 ≠ 不变量**（新不变量须 AST 断言 + 反例验证）；**门禁项本身也可能是摆设**。
- 🔴 **`--selftest` 的 stdout 是文本报告（非 JSON）**（2026-11-21 冒烟实测）：直接 `ConvertFrom-Json` 报「无效 JSON 基元」；结构化报告另写 `%TEMP%\shiguang_selftest.json`（`passed/total/warned/hard_failed/ok`），取判定读它。GUI 存活测试末尾 `taskkill /F /IM` 在 `/T` 已杀净后返 exit128（无匹配进程）属预期，非失败。
- 🔴 **禁 `git add -A`** ⇒ 精确 pathspec；`.cursor/` 需 `git add -f`；提交用原生 bash（`.sh` + `git commit -F`），永不裸 commit；版本号提交前最后一步写；`git status --porcelain --cached` 非法 ⇒ `git diff --cached --name-only`；提交后核 `git show --name-only HEAD`。🔴 **提交门禁不许绕过**（2026-11-13 误用 `--no-verify` 被体积守卫抓出两处超标）；体积守卫扫工作树，并行会话未提交改动也算。
- 🔴 **A/B 对照必须逐轮换序**（A/B/A/B 让内核恒定第二、吃降频，偏慢 3~5%）。`frozen_zones.json --update` 必须是最后一次动冻结文件之后；`precommit_gates.sh` 口径不一（ruff 按已暂存、冻结区按工作区全量）。`git stash push -- <path>` 会捎进暂存区 ⇒ pop 冲突，解法 `git checkout HEAD -- <冲突文件>`。
- **行尾**：画布 `src/*.ts(x)`、`docs/*.md`、`frozen_zones.json`、`memory/*` = LF；`app/` 多数 `.py`、`version.py`、`.mdc` = CRLF ⇒ 写入前判 `'\r\n' in raw`。ruff 用 `C:/Python314/python.exe -m ruff`；回归优先 `.venv312`；Node22 直调 `22.22.2-6/node.exe`；本机 locale=utf-8 ⇒ `open()` 必带 encoding。
- **远程** origin=`git@github.com:1949King/wang1.git`（私有）；filter-repo 剥 3 个 >100MB 后强推，**本地 main 仍是旧历史**；2026-11-12 实测 GitHub 不可达（SSH 22 refused / 代理 `127.0.0.1:7897` 无监听）⇒ 别把「推不上去」误判成凭据问题，处方 `memory/2026-11-12.md`。
- **沙箱**：模拟鼠标点击打不进去（`mouse_event` 无效），GUI 只能让用户点；截图用 PIL `PrintWindow(hwnd, mem, 2)`；起进程只能用 python `subprocess`（`Start-Process`/`cmd start`/`.NET Process.Start` 全被拦）；tempfile 回退 cwd ⇒ 三入口钉 `.workbuddy/tmp`；🔴 该 tempdir 含中文（`d:\拾光剪影\.workbuddy\tmp`）⇒ `cv2.imread/imwrite` 静默失败，须 `np.fromfile+cv2.imdecode` / `cv2.imencode+tofile`；**Bash 偶发 `SandboxError(0xFFFFF826)`** ⇒ 换 `PowerShell` + `dangerouslyDisableSandbox: true`。
- 🔴 **三个「不报错就坏掉」高频形态**（`docs/现行技术文档.md §40.21`）：① **闭包读+写同一变量必须 `nonlocal`**（否则 `UnboundLocalError` 被 `except` 吞 ⇒ 任务 100% 失败、界面 100% 说成功）；② **dict 重复键静默覆盖**（F601 只看值不同那部分）；③ **未入库但被 import 的文件** ⇒ 只有本机跑得动，`git ls-files` 才是判据。⚠️ 修完先查**调用方是否为零**；改文本别用 ast 的 `col_offset`（UTF-16 偏移遇 emoji 写坏文件）；**测试触到 `render_manager` 必须 stub**（真实现 import `cpp_engine` 让 pytest access violation 硬崩）。
- 🔴 **`editor_agent_panel_mixin.py` 规模棘轮已顶格**（基线 2270 / 容差 30）⇒ Agent 面板新逻辑一律放 `editor_agent_runtime_mixin.py`（运行时/编排）或 `editor_agent_dock_mixin.py`（线程与设置辅助）；`editor_module.py`（9.7k 行）同样禁止加行。2026-11-18 多轮闭环即按此落位。
- 🔴 **`AgentLoop` 此前是「已建未接」**（`app/` 内零调用点，2026-11-18 核验）⇒ 桌面面板已于当日接入（`EditorAgentLoopWorker` + `_AgentLoopToolBridge` 主线程往返）；判断 Agent 能力「有没有」不能只看 core 有没有模块，要看 UI 是否真调用。


## 四、团队协作现状（2026-11-12 复核，画布 0.3.52）
> 细节全在 `topics/team-collab.md`。**路线别改**：Figma 之外不做实时共编；视频项目强耦合 ⇒ CRDT 是负资产，「锁 + 冲突检测 + 服务端 diff」正确。
- 🔴 **三个致命空洞已全补（旧记忆作废）**：`role` 三级 + `_need()` 守卫（`POST /team/join` 曾可伪造 owner，编辑权只来自配对码）；批注落 `comment` 表不产生 rev；presence 靠 `member.last_seen` + 90 秒窗口 + 12 秒心跳。
- **仍存隐患**：版本全量快照膨胀、`claim` TTL 600 无续约、`diff` 只比结构不比素材。

## 五、收尾纪律（用户要求）
每完成一个任务立刻更新：① `docs/现行技术文档.md`（问题→根因→修复→验证，§40.x）；② `memory/YYYY-MM-DD.md`；③ 有长期价值的坑写进本文件。标准：下个会话只读文档即可复现结论、不用问人。

## 六、主题只有一套机制（2026-11-27 加，血泪：4.47.0 设置页「浅底浅字」）

- 🔴 **主题只由 `ThemeManager.apply_theme` 驱动**：它应用全局 QSS + repolish 后，回调各顶层窗口的 `refresh_module_themes(theme)` → 各模块 `set_theme(theme)`。任何切换入口（标题栏按钮 / 设置页下拉框 / 按时间切换 / 画布设置页）一律只调 `apply_theme`，**不要**自己 `setProperty("theme", …)`、不要绕过它改内联样式。
- 🔴 **`set_theme` = 纯视图刷新**：只负责把自己（含子控件）的内联样式画成指定主题。禁止在里面发主题事件、写持久化、决定主题状态。带内联样式的新控件 ⇒ 在自己类里重写 `set_theme`。
- **懒加载模块的坑**：模块创建于全局主题之后，新控件没有 `theme` 属性 ⇒ 在 `set_theme` 里调 `ThemeManager._apply_theme_property(self, theme)` 补（别裸 setProperty：只写属性不 repolish 等于没换）。
- **回调顺序**：`ThemeManager` 先落定 `_current_theme/_theme_preference` 再回调，否则回调方读到旧偏好。
- **内联颜色映射必须逐声明、可逆**（`SettingsModule._map_declarations`）：整段子串替换会污染（`#333333` 既是文字色又是边框键），切回深色回不去。
- **旧记忆修正**：原先写「内联 setStyleSheet = 主题盲区，须回 set_theme()」——现在 `set_theme` 会由 ThemeManager 统一回调，不必再手动逐个调用；但**没重写 `set_theme` 的带内联样式控件仍是盲区**（未审计）。
- 回归测试：`tests/unit/test_theme_single_mechanism.py`（对比度 ≥4.5 + 深浅往返样式一致）。详见 `docs/现行技术文档.md` §40.36。
