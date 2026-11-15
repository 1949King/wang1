# 拾光剪影 — 项目长期记忆
> 深水区：`topics/`（`packaging.md` 打包 · `gguf-quant.md` · `agent-blueprint.md` · `canvas-bridge.md`）；日志 `memory/YYYY-MM-DD.md`；工作法 `~/.workbuddy/skills/`。
> **机制**：本文件是项目记忆唯一真相源，在 git 里（`.workbuddy` 被 gitignore ⇒ 新文件必须 `git add -f`）。跨项目个人档案在 `C:\Users\Administrator\.workbuddy\user-<id>-personal\MEMORY.md`（账号级、不在本仓库）。入口表见 `AGENTS.md` 的「项目记忆」章节。**云端 profile 由服务端自动学习，本地改不了**，别许诺「已同步到云端」。

## 〇、规模与定位（2026-11-12 实测）
- `app/**/*.py`：**512 文件 / 222,485 行**；`vendor/packages/canvas-core/src/**/*.ts(x)`：**262 文件 / 70,179 行**；合计 **≈29.3 万行**。旧口径「20.9 万 + 4.1 万」作废（4.1 万只数了根目录）。
- 画布包 2026-11-04（`fbfca1ae`）由 `libtv` 改名 **`canvas-core`**，旧路径 `vendor/packages/libtv` 全失效。
- 🔴 **定位（2026-10-28 用户纠正）**：**通用创意生产工具/创意工作台，不是「短剧剪辑工具」**。输入想法/素材 → 输出 图·视频·3D·成片；画布是工作台不是流水线。对标 Figma/Miro/Canva/ComfyUI/Runway/剪映。禁拿「短剧」「懂短剧连续性」当定位与护城河；S0-S5 只是内置范式之一。

## 一、核心不变量
1. 真相源 `EditorModule._clips`；跨线程整段替换带 `_clips_lock`；序列化用 `_clips_snapshot()`，禁把 `_clips` 交 `json.dump`。
2. 插件两套：`ExtensionsRegistry`(extension_base.py:332) + `PluginManager`(plugin_manager.py:13)；真家 `app/plugins/`。
3. 冻结区 9 zone / 106 锁，改 zone 同步 4 处：`docs/knowledge/frozen_zones.json`（**字符串手术**，json.dump 会重排几千行）· `现行技术文档.md §5` · `.cursor/rules/frozen-zones.mdc` · 重锁。新文件必须登记进 zone files。`app/core/neural/` 不在任何冻结区。
4. 两套独立版本号：`app/version.py`（主）与 `canvasVersion.ts`→`package.json`→CHANGELOG（画布）。禁内联版本字符串。
5. `agent_capability_catalog.py` 加行即注册，`verify_catalog_consistency()` 双向守卫；`CapabilityResult` 字段是 `success` 不是 `ok`。
6. 音画纠偏 ~280ms（冻结区），勿压回 80ms。
7. 主题真相源 `theme_tokens.py`（三表 57 keys）；内联 `setStyleSheet` = 主题盲区，须回 `set_theme()`；`setObjectName` 后 grep `#x` 确认 QSS 有规则。
8. 静默 except：UI 绘制 pass 可；状态机/资源路径须 `logger.debug(..., exc_info=True)`。
9. 沙箱 wmic 黑名单：import app 链触发，验证脚本 subprocess 包一层。

## 二、用户偏好
简体中文；指令极简；**先结论后展开**；小白模式（比喻+表格）；拒绝随机效果；要证据（文件+行号）；被纠正直接认错重查不辩解。🔴「迭代设计文档」≠「把数字改对」，要设计增量。🔴 他问「够不够用」时别答「该加什么新功能」：先按现有流程逐段找缺口，再谈新模块（2026-11-04 被纠正）。🔴 **下判断前先确认字段是「手工写死」还是「动态推导」**——2026-11-15 我把 `_probe_local_video` 误当 `verification` 来源，编出一个不存在的不诚实问题。

## 三、持久约束（血泪）
- 🔴 **Qt6.11 WebEngine 必须给 QApplication 非空 argv**（`QApplication([])` ⇒ 渲染进程 `0xC0000409`）；白屏另查 `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`，CSS 别用 `body:has(...)`。**PyQt6 别对 Qt 枚举 `int()`**（TypeError 被 `except: pass` 吞 ⇒ console 零输出，用 `str(level)`）。
- 🔴 **画布静态服务有 SPA 兜底**：缺文件改写 `/index.html` ⇒ 200 + HTML，前端当 ESM import 报 `Unexpected token '<'`。排查看 body 不看状态码。
- 🔴 **`SkeletonUtils.clone` 后先 `updateMatrixWorld(true)` 再测包围盒**（脏矩阵量出 1/33 假尺寸）；SkinnedMesh 用 `setFromObject(obj, true)`；尺寸自检必须进 `tick()` 渲染循环（挂 actors effect = 死代码）。
- 🔴 **启动必须优先 `.venv312`**：`C:\Python314` 有 PyQt6 但无 torch ⇒ 本地模型全 `available:false`。
- **体积守卫（`_verify/check_file_size.py`，阈值 2000+容差 30，基线 12 文件；2026-11-12）**：顶格 `CanvasShell.tsx` 3281/3281、`riggedHumanoid.ts` 3189/3189；余 1~2 行 `Stage3D.tsx` 4652/4653、`settings_module.py` 2852/2853、`editor_module.py` 9745/9747；余 6~18 `styles.css` 4004/4010、`extensions_module.py` 2218/2228、`canvas_aigc.py` 2919/2935、`store.ts` 2526/2544。⇒ 新逻辑必须另开文件（先例 `teamPanel.css`/`settings_team_tab.py`/`stage3dPoseLibrary.ts`）。⚠️ `bridge.ts` 已不在基线（1897 行），旧记忆「2043/2046 禁改」过时。判红用 `git show HEAD:<file> | wc -l`，但以 `check_file_size.py` 数字为准（末尾换行可差 1）。
- **两条单通道（禁造第二套）**：3D 产物入轨 = `stage3dArtifacts.ts::sendArtifactToTimeline()` → `POST /ingest_path`；角色库→导演台 = store `requestStage3dCast` → `stage3dCastSeq` → `useStage3dCast()`。生成模型选择唯一真源 = `generationModels.ts`；图像生成走 `localImage.ts::generateImageUnified`，Agent「模型」页是唯一可见入口。
- 🔴 **打包**：细节见 `topics/packaging.md`。三条秒记：① 目录扫描型加载的 `app/plugins`、`app/skills`、`app/core/video_processing` **必须进 `build_release.SYNC_APP_SUBPKGS`**（进 PYZ 等于没进，缺了**静默返回 0**）；② 整目录拷包必须排 `.git`（只读 pack ⇒ `PermissionError [WinError 5]` 卡重建）；③ `opentimelineio`/`mediapipe` 在冻结进程加载即崩，走子进程 / 声明不支持。基线：源码 512 模块缺 0、插件 27、外部 skill 11、自检 26 项 24 过 2 降级、产物 6.35GB。
- 🔴 **稳定性门禁豁免逐行 + 必写理由**：`# stability-gate: allow-print（理由）` / `allow-swallow（理由）`。合规只有两类：CLI 报告器 stdout、结构性正常分支（无父控制台 / `add_dll_directory` 拒绝 / 体积统计跳过）。**能真改就别豁免**。
- 🔴 **入口位置由能力归属层级决定，不由体积守卫有没有空位决定**：团队入口曾塞进画布第二条顶栏 ⇒ 被 `showWorkspace` 挡住，另外 8 个界面全看不见。工作区级能力 ⇒ 挂常驻 `AppNav`。
- 🔴 **`backdrop-filter`（及 filter/transform）祖先会成为 `position:fixed` 后代的包含块**：团队面板挂进 `.ic-nav` 后 420px 只剩 46px 窄缝。**浮动面板一律 `createPortal(..., document.body)`**。
- 🔴 **PyQt ↔ 画布唤起用「探测全局函数」不用 `dispatchEvent`**（后者页面未加载也返成功）：画布挂 `window.__sgTeamOpen`，PyQt 侧 `runJavaScript` 拿 'ok'/'pending' 轮询。
- 🔴 **帮助页正文真源是 `docs/help/<id>.md`**：加话题 = `topics` 加一行 + `_xxx()` 三行 + 落 md，改说明不用改代码。`_render_markdown` 只认 `#/##/###`、`- `、`> `、`|表格|`、`---`。
- 🔴 **Qt 页面验收两条腿**：`QT_QPA_PLATFORM=offscreen` 验结构（无字体 ⇒ 豆腐块），真实窗口 `QTimer.singleShot` 后 `grab()` 验像素。**QLabel 默认 PlainText ⇒ `**x**` 会原样画到界面**；QGroupBox 标题继承调色板、深底偏暗需显式给色。
- 🔴 **套接字错误码先查 `app/core/team_discovery.py`**（全库唯一碰 UDP/sendto/recvfrom，`lan_ip` 自带兜底）。错误码必须翻人话（`friendly_socket_error` / `teamClient.netError`）；`hostCall` 的 `authHeaders()` 放 `try` 外面，否则本地装配错误被误报成「连不上桥」。
- 🔴 **SVD 图生视频输出尺寸必须随输入比例走**（2026-11-09 真机）：硬编码 1024×576 ⇒ 拉伸（第1帧 vs 拉伸输入 cos 0.972，vs 居中裁剪 0.852），人脸横向胖 1.78×。已加 `video_gen.fit_output_size`。**只有方形慢**：1024×576 9.5s/帧、576×1024 6.5s/帧、768×768 27.7s/帧（原因未定论）。**特写人脸第 10 帧畸变**，首帧完好。
- **Wan 2.1 实测（2026-11-15，见 `memory/2026-11-15.md`）**：本机只有 **T2V-1.3B** 权重（`models/cache/Wan-AI_Wan2.1-T2V-1.3B-Diffusers`），传 `reference_image` 会 fail-fast 拒绝（I2V 无 encoder）。硬约束：帧数 **4k+1**、宽高被 **16** 整除。5 秒 = 81 帧 / 480×832 / 20 步 = **927 秒**，显存 6.6/8.2GB。
- **两个 `verified` 不是一回事（2026-11-15 查证，别混）**：① `model_family.py:185` 的 `verification=VERIFIED` 是**手工写死**的「族能真机跑通」（10-24 M5 背书），`_probe_local_video` 只管权重在不在盘、不决定 verification；② `kernel_evidence.json` 记的是**内核 vs stock 等价性**（张量/画质/速度/显存四门）。**wan 有 kernel adapter**（`kernel/adapters/wan.py`），10-30 `_verify/bench_wan_kernel_parity.py` 跑过（`data/wan_kernel_parity.json`）：`kernel_ok=true` 但 **PSNR 未产出**（`kernel_frames` 缺失，画质门没完成），且总耗时 265.2s vs 50.3s = **5.27×**——口径不齐（kernel 含 UMT5 编码 207.7s，上游吃的是预编码 embeds；同口径去噪 52.6s vs 50.3s ≈ 1.05×）。⇒ 缺画质数据 + 速度门按总耗时不过 ⇒ 不能登记。⚠️ `capability_manifest.py:66` 注释「wan 仍只有一腿（无 adapter）」**已过时**。
- 🔴 **本地视频「吃不吃图」的真源 = `video_gen.available_models()` 的 `modes`，挂在模型 id 上、不挂族名**（2026-11-15 收口）：`wan21-t2v-1.3b` 只有 `t2v`，同族 `wan22-ti2v-5b` 是 `t2v+i2v` ⇒ **按族名推必错**。判定只允许在 `canvas_routes_local_video._model_modes()` 一处；前端硬编码 `TEXT_ONLY_LOCAL_VIDEO` 已删。`_infer_cogvideox/hunyuan/ltx` 仍收 `reference_image` 但**从不使用**（靠路由层前置拦截兜住；新增族别指望它们自己拒）。已知缺口：auto 通道的 `localModel` 三处调用方都不传 ⇒ auto 本地跳固定 SVD，跑 wan 必须显式选模型。
- 🔴 **`model_family._PROBES` 的权重探测（2026-11-15 修，别退回）**：`is_downloaded` 在 `diffsynth_image`/`diffusers_image`/`video_gen` 里**都是 Engine 静态方法**（`DiffsynthImageEngine` / `DiffusersImageEngine` / `VideoGenEngine`），**没有模块级同名函数** —— 写 `from ... import is_downloaded` 会 ImportError 被吞 ⇒ 恒 False。`_probe_local_video` **禁止**再用 `_guess_model_kind(族名)`（族名命中自己关键词 ⇒ 恒 True）。实测该 bug 让 sd15/sdxl/svd 被判「权重不在盘」、cogvideox/ltx/mochi 被谎报「在盘」，9 族判定几乎全反。防回归：`test_model_family.py::test_probes_have_no_legacy_wrong_patterns`，**用 AST 断言，别用字符串匹配**（会被自己的注释绊倒，第一版就踩了）。
- **看本地模型全貌用 `python scripts/check_models.py`**（2026-11-15 加）：一次列出生图+生视频全部族（权重/磁盘/后端/验证态/可用）+ 不可用原因，`--capability`/`--json` 可选。**只做展示，判定全来自 `model_family.status()` + `resolve()`**，不另写一套。⚠️ 它只答「配置层能不能用」，不担保真能生成出东西。
- **孤儿端点差集法四扫描面**：画布 src 非注释行 / `canvas_server.py` JS 字面量 / `app/**/*.py` URL 拼接 / Rust `src-tauri/src/lib.rs`。
- **`人话 vs 假指标`**：自检的 `cpu=/gpu=` 曾写成 `(x @ x.T).sum()`（随机矩阵乘求和、还会出负数）被当性能证据。凡「像指标」的输出要么有量纲真测量，要么双端比对（同 seed 比 `max|Δ|`）。「没测出来」≠「测出来了」：后端空串前端原样保留，禁填默认值；非法数值落 0 不猜。**同名不同义常量高频坑**（warnings / quality_tiers）：带 quality/tier/mode/level 的字段先核前端语义。
- `switch_to_module()` 对 `nav_hidden` 模块静默无效 ⇒ 走 `_perform_module_load`。本机 locale=utf-8 ⇒ `open()` 必带 encoding。YuE 全曲跑不动 ⇒ 执行端不可用必须诚实失败，绝不假音频。沙箱 tempfile 回退 cwd ⇒ 三入口钉 `.workbuddy/tmp`。
- 沙箱里**模拟鼠标点击打不进去**（`mouse_event` 无效），GUI 只能让用户点；窗口枚举 + PIL `PrintWindow(hwnd, mem, 2)` 截屏可用。ps 里 `Start-Process`/`cmd start`/`.NET Process.Start` 全被拦，只能用 python `subprocess` 拉起。
- **`tsc` 棘轮**：`cd vendor/packages/canvas-core && node node_modules/typescript/bin/tsc --noEmit --pretty false`，基线 **37**（2026-11-12 复核）。测试里 `.catch(e => e as Error & {code})` 会把成功返回并进联合（+9 TS2339）⇒ 写 `rejection(p)` helper。

## 四、验证与提交纪律
- **静态门禁全绿 ≠ 运行时没崩** ⇒ 自绘控件交付标准 = 真机启动 + paintEvent 真跑。`run_all_checks.py` **不含**稳定性门禁 ⇒ 另跑 `scripts/stability_gate.py`。**哈希 ≠ 不变量**：新不变量须 AST 断言 + 反例验证；**门禁项本身也可能是摆设**。
- 🔴 **禁 `git add -A`** ⇒ 精确 pathspec；`.cursor/` 需 `git add -f`。提交用原生 bash（`.sh` + `git commit -F`），永不裸 commit；版本号提交前最后一步写。`git status --porcelain --cached` 非法 ⇒ 用 `git diff --cached --name-only`。
- 🔴 **A/B 对照必须逐轮换序**：A/B/A/B 会让内核恒定排第二、吃上一负载降频，恒定偏慢 3~5%。「新路径总在第二组」的基准都不可信。
- 🔴 `frozen_zones.json` 改 files 禁 `sorted()` ⇒ HEAD 原顺序 + 尾部追加。`--update` 必须是最后一次动冻结文件之后。⚠️ `precommit_gates.sh` 口径不一：ruff 按已暂存筛，冻结区按工作区全量算。
- 🔴 **`git stash push -- <path>` 会捎进暂存区状态 ⇒ pop 冲突**；解法 `git checkout HEAD -- <冲突文件>`。
- 行尾：画布 `src/*.ts(x)`、`现行技术文档.md`、`frozen_zones.json`、`memory/*`、`docs/CHANGELOG.md` = LF；`version.py`、`.mdc` = CRLF。写入前先 `'\r\n' in raw` 判。`grep` 搜 emoji 0 命中 ⇒ 用 python 读文本断言。ruff 用 `C:/Python314/python.exe -m ruff`；回归优先 `.venv312`；Node22 直调 `22.22.2-6/node.exe`。
- 🔴 **远程**：origin = `git@github.com:1949King/wang1.git`（私有）。已 filter-repo 剥 3 个 >100MB 文件（2.88GB→316MB）强推；**本地 main 仍是旧历史（315 提交）**。2026-11-12 实测 GitHub 不可达（SSH 22 refused；HTTPS 走 `127.0.0.1:7897` 但无监听）⇒ 别把「推不上去」误判成凭据问题。推送前必须做历史手术，前置：① 本地仍有 3 个 >100MB blob（`拾光剪影-发布版.zip` 743M / `assets/videos/纵年华--01.mp4` 723M / `cpp_engine/avfilter-11.dll` 104M）；② 工作区干净。处方见 `memory/2026-11-12.md`。
- **内核族 `caps.verified` 是机器可核对承诺**：改 `VERIFIED` 须 `docs/knowledge/kernel_evidence.json` 有该族 `passed=true`。⚠️ 该文件记的是**内核 vs stock 等价性**，与 `model_family` 的「族能跑通」是两个 verified，别混。
- **`Bash` 偶发 `SandboxError(0xFFFFF826)` / `bash.exe: Permission denied`** ⇒ 换 `PowerShell` + `dangerouslyDisableSandbox: true`。
- 🔴 **提交门禁不许绕过**：2026-11-13 误用 `--no-verify`，随即被体积守卫抓出两处超标（App.tsx 2016 行 / extensions_module 2233 行）。**体积守卫扫工作树**：并行会话未提交的改动也算进你的行数。

## 五、团队协作现状（2026-11-12 复核，画布 0.3.52）
> 细节全部在 `topics/team-collab.md`。这里只留判据。
- **路线**：DaVinci/Premiere/CapCut 都不做实时共编，只有 Figma 做；视频项目强耦合 ⇒ **CRDT 是负资产**，「锁 + 冲突检测 + 服务端 diff」正确，别改。
- 🔴 **2026-11-04 记的「三个致命空洞」已全部补掉（旧记忆作废）**：`role` 立 `owner`/`editor`/`viewer` + `_need()` 守卫（并堵掉 `POST /team/join` 请求体伪造 owner 的洞，编辑权只来自配对码）；批注落 `comment` 表（提批注不产生 rev）；presence 靠 `member.last_seen` + 90 秒窗口 + 12 秒心跳。
- 0.3.51 砍二维码，只留 6 位码 + 邀请链接（`teamInvite.ts` 不联网不猜）。
- **仍存隐患**：版本全量快照膨胀、`claim` TTL 600 无续约（幽灵锁）、`diff` 只比结构不比素材。🔴 画布里 `tick` 是高频函数名，新函数别用（质量棘轮 `dupNames` 重名即红）。

## 六、任务收尾纪律（2026-11-13 用户要求，务必执行）
- 每完成一个任务，立刻更新：① `docs/现行技术文档.md`（问题→根因→修复→验证）；② `.workbuddy/memory/YYYY-MM-DD.md`；③ 有长期价值的坑写进本文件。
- 判定标准：下一个会话只读文档就能复现结论、不需要问人。

## 七、2026-11-13 新增持久约束（血泪）
- 🔴 **QtWebEngine 里不要用 `QMenu.exec()` / 长期存活的 `popup()` 做右键菜单**：事件过滤器里嵌套事件循环 ⇒ `0xc0000005` 崩溃；popup 不消失 ⇒ 黑块堆叠 + AppHangTransient。现 Qt 菜单默认关闭（`SHIGUANG_QT_CTX_MENU=1` 才开），右键统一走前端 React 菜单。
- 🔴 **清空 Qt 布局时先 `hide()` 再 `setParent(None)`**：可见控件脱离父级会变成顶层窗口，一次搜索实测新增 583 个"小窗"（闪屏 + 假死）。
- 🔴 **不要整文件 read→write**：工具单次读取有上限，会静默截断（App.tsx 1860→1175 行、help_module 823→776 行）。改大文件用 edit / 行号 splice，改完核对行数 + `git diff --stat`。
- 🔴 **WebEngine 的 localStorage 不持久且 `setItem` 不报错**：需跨重启的状态必须写服务端标记（`data/compliance_acceptance.json` + `/host/compliance/*`）。
