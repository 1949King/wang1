# 拾光剪影 — 项目长期记忆
> 细节深水区已拆到 `.workbuddy/memory/topics/`：`gguf-quant.md` · `agent-blueprint.md` · `canvas-bridge.md`（含视频黑框/缺口现状）。日志查 `.workbuddy/memory/YYYY-MM-DD.md`，工作法查 `~/.workbuddy/skills/`。
>
> **记忆同步机制（2026-11-12 核实，别猜）**：① 本文件是**项目记忆的唯一真相源**，且**已在 git 里** ⇒ 提交并推到远程后云端确有一份；② 跨项目个人档案（职业/转型/表达纪律）在 `C:\Users\Administrator\.workbuddy\user-<id>-personal\MEMORY.md`，属账号级目录、不在本仓库；③ **云端 profile 由服务端从对话自动学习，本地改不了**（`memory/` 是只读缓存，手写会被下次会话覆盖）——想让它"进云端"只能靠：a) 把内容写进上面两个文件；b) 在本会话里说出来让它成为对话事实；c) 推 git。别许诺"我同步到云端了"。

## 〇、规模（2026-11-12 实测，写数字一律用这个口径）
- `app/**/*.py`：**512 个文件 / 222,485 行**（排除 `tests/` `_retired/` `temp/` `__pycache__` `app/models`）
- `vendor/packages/canvas-core/src/**/*.ts(x)`：**262 个文件 / 70,179 行**（含 `magnetic/` `novice/` `mascot/` 等子目录）
- 合计约 **29.3 万行**。⚠️ 旧口径「Python 20.9 万 + 画布 4.1 万」已过时（画布 4.1 万是**只数根目录文件**的旧算法）。
- 画布包 2026-11-04（提交 `fbfca1ae`）由 `vendor/packages/libtv` 改名为 **`canvas-core`**（`workspace:*` 引用名同步改）。⚠️ 文档与旧记忆里凡是 `vendor/packages/libtv` 的路径都已失效。


## 〇、定位（2026-10-28 用户纠正，最高优先级）
🔴 **通用创意生产工具 / 创意工作台，不是「短剧剪辑工具」** —— 短剧只是其中一个用法场景。
- 输入 = 想法/素材/参考；输出 = 图·视频·3D·成片。**画布是工作台，不是流水线**。
- 对标 Figma·Miro·Canva·ComfyUI·Runway/Pika·剪映·DX-OS。**禁**用「短剧」框定方向，禁把「懂短剧连续性」当护城河。
- 真护城河 = 一个人把「无限画布 + 3D 导演台 + 多模型生成 + 剪辑」四条链路打通并全本地运行。S0-S5 生产链是**一条**内置范式，不是唯一范式。

## 一、核心不变量
1. 真相源 `EditorModule._clips`；跨线程整段替换带 `_clips_lock`；序列化用 `_clips_snapshot()`，禁把 `_clips` 交 `json.dump`。
2. 插件两套：`ExtensionsRegistry`(extension_base.py:332) + `PluginManager`(plugin_manager.py:13)；真家 `app/plugins/`。
3. 冻结区 9 zone / 106 锁，改 zone 同步 4 处：`docs/knowledge/frozen_zones.json`（**字符串手术**，json.dump 会重排几千行）· `现行技术文档.md §5` · `.cursor/rules/frozen-zones.mdc` · 重锁。新文件必须登记进 zone files。`app/core/neural/` **不在任何冻结区**。
4. 两套独立版本号：`app/version.py`（主）与 `canvasVersion.ts`→`package.json`→CHANGELOG（画布）。禁内联版本字符串。
5. `agent_capability_catalog.py` **加行即注册**，`verify_catalog_consistency()` 双向守卫。CapabilityResult 字段是 `success` 不是 `ok`。
6. 音画纠偏 ~280ms（冻结区），勿压回 80ms。
7. 主题真相源 `theme_tokens.py`（三表 57 keys）。内联 setStyleSheet = 主题盲区，须回 `set_theme()`；`setObjectName` 后必须 grep `#x` 确认 QSS 有规则。
8. 静默 except：UI 绘制 pass 可；状态机/资源路径须 `logger.debug(..., exc_info=True)`。
9. 沙箱 wmic 黑名单：import app 链触发，验证脚本 subprocess 包一层。

## 二、用户偏好
简体中文；指令极简；**先结论后展开**；小白模式（比喻+表格）；拒绝随机效果；要证据（文件+行号）；被纠正直接认错重查不辩解。🔴 **「迭代设计文档」≠「把数字改对」**——要设计增量。🔴 **他问「够不够用」时别答「该加什么新功能」**：先按现有流程逐段找缺口，再谈新模块（2026-11-04 被纠正过）。

## 三、持久约束（血泪）
- 🔴 **Qt 6.11 WebEngine 必须给 QApplication 非空 argv**（`QApplication([])` ⇒ 渲染进程 `0xC0000409`）；画布白屏另查 `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`，CSS 别用 `body:has(...)`。
- 🔴 **画布静态服务有 SPA 兜底**：缺文件改写 `/index.html` ⇒ **200 + HTML**，前端当 ESM import 报 `Unexpected token '<'`。排查看 body 不看状态码。
- 🔴 **`SkeletonUtils.clone` 后必须先 `updateMatrixWorld(true)` 再测包围盒**（脏矩阵量出 1/33 假尺寸）；SkinnedMesh 须 `setFromObject(obj, true)`；尺寸自检必须进 `tick()` 渲染循环（挂 actors effect = 死代码）。
- 🔴 **PyQt6 别对 Qt 枚举 `int()`**（TypeError 被 `except: pass` 吞 ⇒ console 镜像零输出，用 `str(level)`）。
- 🔴 **启动必须优先 `.venv312`**：`C:\Python314` 有 PyQt6 但**无 torch** ⇒ 本地模型全 `available:false`。
- **体积守卫实况（2026-11-12 实测，`_verify/check_file_size.py` 阈值 2000 + 容差 30，基线 12 个文件）**：
  🔴 **顶格，一行都不能加**：`CanvasShell.tsx` 3281/3281、`riggedHumanoid.ts` 3189/3189；
  🔴 **只剩 1~2 行**：`Stage3D.tsx` 4652/4653、`settings_module.py` 2852/2853、`editor_module.py` 9745/9747；
  ⚠️ `styles.css` 4004/4010（余 6）、`extensions_module.py` 2218/2228（余 10）、`canvas_aigc.py` 2919/2935（余 16）、`store.ts` 2526/2544（余 18）。
  ⇒ **新逻辑必须另开文件**（先例 `teamPanel.css` / `settings_team_tab.py` / `stage3dPoseLibrary.ts`）。
  ⚠️ **`bridge.ts` 已不在基线里**（1897 行，收敛到 2000 以下）——旧记忆里「bridge.ts 2043/2046 禁改」是过时信息，别再拿它挡改动。
  自查口径：`git show HEAD:<file> | wc -l` 得 HEAD 行数，但**守卫本身用 Python 逐行读**，两者可能差 1（末尾换行）；以 `check_file_size.py` 的数字为准。
- **两条单通道（禁造第二套）**：① 3D 产物入轨 = `stage3dArtifacts.ts::sendArtifactToTimeline()` → `POST /ingest_path`；② 角色库→导演台 = store `requestStage3dCast` → `stage3dCastSeq` → `useStage3dCast()`。
- **生成模型选择单一真相源 = `generationModels.ts`**；图像生成统一走 `localImage.ts::generateImageUnified`。Agent「模型」页是唯一可见入口。
- 🔴 **「目录扫描型加载」的 app 子包必须进 `build_release.SYNC_APP_SUBPKGS`**，进 PYZ 等于没进：`app/plugins`（PluginManager 用 `os.listdir`+`spec_from_file_location`）、`app/skills`（`SKILLS_ROOT=Path(__file__).parent` + `os.walk` 找 SKILL.md）、`app/core/video_processing`（进 Analysis 会 0xC0000005）。三者缺了都**静默返回 0、不报错**。自检里各有对应项（插件 27 / 外部 skill 11 / PyAV 引擎）。
- 🔴 **自检的数字要能证伪**：`cpu=/gpu=` 曾写成 `(x @ x.T).sum()`（随机矩阵乘求和，还会出负数），被当成性能证据误读过。凡「看起来像指标」的输出，要么是有量纲的真测量，要么改成双端比对（同 seed CPU vs GPU 比 `max|Δ|`）。
- 🔴 **「没测出来」≠「测出来了」**：后端空串字段前端原样保留，禁填默认值；非法数值落 0 不猜。
- 🔴 **同名不同义常量高频坑**（warnings / quality_tiers 踩过）：带 quality/tier/mode/level 的后端字段先核前端语义。
- 🔴 **打包验收三件套**：① spec 的 `hiddenimports` 必须**自动枚举 `app/` 全量**（产品模块靠动态加载，静态分析看不见；手写清单实测漏 107 个模块、27 个插件）；② AI 栈在 `runtime/` 对 Analysis 不可见 ⇒ stdlib（timeit/modulefinder/struct）与三方包（markupsafe/safetensors/httpx2）会缺，只能靠 selftest 一项项抓；③ **残件包补进 `_internal`**，别放 runtime/ —— numpy/scipy/PIL 的 `__init__` 在 PYZ 里、`__path__` 指向 `_internal/<pkg>`，放 runtime/ 会被完全遮住。工具：`scripts/build_release.py`(一键) + `.workbuddy/tmp/check_module_coverage.py`(引用闭包，含 `disk_modules()`)。
- 🔴 **`opentimelineio` / `mediapipe` 在冻结进程里加载即崩**（前者段错误，后者 1114），文件是齐的、普通解释器正常。产品已有降级：OTIO 走 `--otio-worker` 独立子进程（`main_qt6.py` 在 import PyQt6 前分流）、姿态解析声明发布版不支持。自检里归 `OPTIONAL_CHECKS` 记 WARN，不算硬失败。
- 🔴 **整目录拷进发布包时必须排 `.git`**：`app/skills/external/` 下三个 skill 是 git clone 来的，第一版连带 `.git` 拷了 ⇒ ① 包里有别人仓库的完整历史与来源地址；② **git 的 pack 文件默认只读**，`shutil.copy2` 会保留属性，下次 PyInstaller `_rmtree(dist)` 直接 `PermissionError: [WinError 5]` 打断打包（实测撞到）。`_sync_app_subpkg` 的 `skip_dirs` 已含 `.git/.github/.idea/.vscode`。
- 🔴 **`app/core/runtime_pack.py` 是 `runtime/` 装载方案的核心**（把 exe 同级 `runtime/` 插到 `sys.path[0]`，绕开 PyInstaller 拿 torch 必崩的 0xC0000005）。它曾长期 untracked 而 `build_release.py` 已引用它 = 库里引用库外模块。2026-11-05 已入库（提交 `2aab20f3` / `.git` 修复 `b9195613`）。
- 🔴 **稳定性门禁的豁免是逐行 + 必须写理由**：`# stability-gate: allow-print（理由）` / `allow-swallow（理由）`，不写理由等于后门。合规用法只有两类：① CLI 报告器的 stdout（logger 会写进日志文件用户看不见）；② 结构性正常分支（无父控制台 / `add_dll_directory` 拒绝 / 体积统计跳过）。**能真改就别豁免**——`_t_plugins` 那处「错误明细读取失败」原本 `except: pass`，改成把异常写进 errs 才是对的。
- **孤儿端点差集法四扫描面**：画布 src 非注释行 / canvas_server.py JS 字面量 / `app/**/*.py` URL 拼接 / **副库 Rust `src-tauri/src/lib.rs`**。
- 🔴 **入口位置由「能力归属层级」决定，不由「体积守卫有没有空位」决定**：团队入口曾为省 12 行塞进画布第二条顶栏（`WorkspaceCanvasMenus`）⇒ 被 `showWorkspace = viewMode === "canvas"` 挡住，另外 8 个界面全看不见。工作区级能力 ⇒ 挂常驻 `AppNav`。
- 🔴 **判断体积守卫会不会红，用 `git show HEAD:<file> | wc -l` 算 HEAD 行数**，别用工作区行数（工作区已含自己的改动）。
- 🔴 **累计删除 >50 触发沙箱 safe-delete 拦截**（vite 清 `dist/assets` ⇒「构建成功但退出码 1」，**不是代码回归**）。绕开 = `mv` 到 `.workbuddy/tmp/`。
- 🔴 **`backdrop-filter`（及 filter/transform）的祖先会成为 `position:fixed` 后代的包含块**：团队面板挂进有 `backdrop-filter` 的 `.ic-nav` 后 420px 被推出屏幕只剩 46px 窄缝（用户原话「就这么小一个窗口」）。**浮动面板一律 `createPortal(..., document.body)`**。
- 🔴 **PyQt ↔ 画布唤起用「探测全局函数」不用 `dispatchEvent`**：后者在页面未加载时也返成功 ⇒ 点了没反应还不报错。画布侧挂 `window.__sgTeamOpen`，PyQt 侧 `runJavaScript` 拿 'ok'/'pending' 轮询。
- 🔴 **帮助页正文的真源是 `docs/help/<id>.md`**（`HelpModule._load_markdown_topic(id)` 读它）：加话题 = `topics` 加一行 + `_xxx()` 三行 + 落 md，**改说明不用改代码**。`_render_markdown` 只认 `#/##/###`、`- `、`> `、`|表格|`、`---`。
- 🔴 **Qt 页面验收两条腿**：`QT_QPA_PLATFORM=offscreen` 验结构（无字体 ⇒ 豆腐块，只看布局），真实窗口 `QTimer.singleShot` 后 `grab()` 验像素。**QLabel 默认 PlainText ⇒ `**x**` 会原样画到界面上**；QGroupBox 标题继承调色板、深底上偏暗需显式给色。
- 🔴 **套接字错误码先查 `app/core/team_discovery.py`**：全库只有它碰 UDP/`sendto`/`recvfrom`（`lan_ip` 自带兜底）。错误码必须翻人话（`friendly_socket_error` 后端 / `teamClient.netError` 前端）；`hostCall` 的 `authHeaders()` 要放 `try` 外面，否则本地装配错误被误报成「连不上桥」。
- `switch_to_module()` 对 `nav_hidden` 模块静默无效 ⇒ 走 `_perform_module_load`。本机 locale=utf-8 ⇒ `open()` 必带 encoding。YuE 全曲跑不动 ⇒ 执行端不可用必须诚实失败，绝不假音频。沙箱 tempfile 回退 cwd ⇒ 三入口钉 `.workbuddy/tmp`。
- 沙箱里**模拟鼠标点击打不进去**（`mouse_event` 无效），GUI 交互只能让用户点；但窗口枚举 + PIL `PrintWindow(hwnd, mem, 2)` 截屏可用。ps 里 `Start-Process` / `cmd start` / `.NET Process.Start` 全被拦，只能用 python `subprocess` 拉起。
- **`tsc` 棘轮**：`cd vendor/packages/canvas-core && node node_modules/typescript/bin/tsc --noEmit --pretty false`，基线 **37**（2026-11-12 复核仍是 37）。测试里 `.catch(e => e as Error & {code})` 会把成功返回类型并进联合（+9 个 TS2339）⇒ 写 `rejection(p)` helper。
- 🔴 **SVD 图生视频的输出尺寸必须随输入比例走**（2026-11-09 首次真机验收）：硬编码 1024×576 ⇒ 方图/竖图被**直接拉伸**（实测：第1帧 vs 拉伸后输入 cos **0.972**，vs 居中裁剪只有 **0.852** ⇒ 是拉伸不是裁剪），人脸横向胖 1.78×。已加 `video_gen.fit_output_size`（官方两档优先 + 中间保面积 + 恒 8 倍数）。⚠️ **只有方形慢**：1024×576 = 9.5s/帧、576×1024 = **6.5s/帧**、768×768 = **27.7s/帧**（三步卡 70s/it，原因未定论）。**特写人脸第 10 帧会畸变**（眼周横纹/鼻梁过曝），首帧完好。

## 四、验证与提交纪律
- **静态门禁全绿 ≠ 运行时没崩** ⇒ 自绘控件交付标准 = 真机启动 + paintEvent 真跑。
- `run_all_checks.py` **不含**稳定性门禁 ⇒ 另跑 `scripts/stability_gate.py`。**哈希 ≠ 不变量**：新不变量必须 AST 断言 + 反例验证；**门禁项本身也可能是摆设**。
- 🔴 **禁 `git add -A`** ⇒ 精确 pathspec；`.cursor/` 需 `git add -f`。提交用原生 bash（`.sh` + `git commit -F`），**永不裸 commit**；版本号提交前最后一步写。`git status --porcelain --cached` 是非法参数 ⇒ 用 `git diff --cached --name-only`。
- 🔴 **A/B 对照必须"逐轮换序"**：A/B/A/B 会让内核恒定排第二位、吃掉上一负载降频，恒定偏慢 3~5%。**"新路径总是第二组"的基准都不可信。**
- 🔴 `frozen_zones.json` 改 files 禁 `sorted()` ⇒ HEAD 原顺序 + 尾部追加。`frozen_zone_guard.py --update` 必须是**最后一次**动冻结文件之后。⚠️ `precommit_gates.sh` 口径不一致：ruff 按已暂存筛，冻结区按工作区全量算。
- 🔴 **`git stash push -- <path>` 会捎进暂存区状态 ⇒ pop 冲突**。解法 = `git checkout HEAD -- <冲突文件>`，勿手解标记。
- 行尾：画布 `src/*.ts(x)`、`现行技术文档.md`、`frozen_zones.json`、`memory/*`、`docs/CHANGELOG.md`（现为 LF） = LF；`version.py`、`.mdc` = CRLF。写入前先 `'\r\n' in raw` 判行尾。`grep` 搜 emoji（astral 字符）0 命中 ⇒ 用 python 读文本断言。ruff 用 `C:/Python314/python.exe -m ruff`；回归优先 `.venv312`；Node22 直调 `22.22.2-6/node.exe`。
- 🔴 **远程仓库**：origin = `git@github.com:1949King/wang1.git`（私有）。已 filter-repo 剥除 3 个 >100MB 文件（2.88GB→316MB，236 提交）强推；**本地 main 仍是旧历史（315 提交），下次推送前需再手术**。
  ⚠️ **2026-11-12 实测：GitHub 完全不可达** —— SSH 22 端口 `Connection refused`；HTTPS 443 走 `127.0.0.1` 代理但代理没起（`Failed to connect ... over proxy`）。⇒ 想推之前先确认代理/网络，别把「推不上去」误判成凭据或仓库问题。
- **内核族 `caps.verified` 是机器可核对的承诺**：改 `VERIFIED` 须 `docs/knowledge/kernel_evidence.json` 有该族 `passed=true`。
- **`Bash` 工具偶发 `SandboxError(0xFFFFF826)` / `bash.exe: Permission denied`** ⇒ 换 `PowerShell` + `dangerouslyDisableSandbox: true`。

## 五、团队协作现状（2026-11-12 复核，画布 **0.3.52**）
- 档位对标结论：专业视频工具（DaVinci bin/timeline 锁、Premiere 序列交接+Frame.io、CapCut 单编辑权转移）**都不做实时共编**；只有 Figma 做。视频项目大二进制+时间轴强耦合 ⇒ **CRDT 是负资产**。我们的「锁 + 冲突检测 + 服务端 diff」路线正确。
- 骨架：`push(base_rev)` 冲突检测不自动合并、`claim` 项目锁 TTL 600、服务端 `diff(from,to)` 只回摘要、前端 `teamDiff`/`formatTeamDiff`、锁可见 🔒 认领者。⚠️ 具体行号会随迭代漂移，查代码别信旧行号。
- 🔴 **2026-11-04 记的「三个致命空洞」已全部补掉**（旧记忆作废，别再当现状复述）：
  - **(a) `role` 是装饰品** → 0.3.52 立三档 `owner`/`editor`/`viewer` + `_need(need)` 守卫（五个写端点要编辑权，403 文案直说「你是查看者」）。同时**堵掉一个真洞**：`POST /team/join` 以前把请求体 `role` 原样写库 ⇒ 局域网里任何人 POST `{"role":"owner"}` 就是主人；现在忽略请求体角色（首成员 owner、其余 viewer），**编辑权只能来自配对码**，`pairing` 表加了 `role` 列；`POST /team/members/{id}/role` 属 owner 专属且改不了 owner 自己；认不出的角色一律按 viewer。
  - **(b) 无批注/审阅** → 0.3.52 `comment` 表，**`node_id` 挂画布节点而不是坐标**（挂坐标一排版就漂），空串=针对整份画布；**提批注不产生新 rev**（否则意见会把「谁改了什么」淹掉）；**viewer 能提批注但不能改解决状态**（这是该功能存在的理由）。
  - **(c) 无 presence** → 0.3.50 `member.last_seen`（`auth()` 刷新、20 秒节流；老库补列取 0 不取 now）+ `teamPresence.ts`（窗口 90 秒）+ 12 秒心跳（失败亮红字「和团队服务器断开了」）。🔴 **宁可说在线也不谎报离线**。
- **0.3.51 收窄配对**：二维码**砍掉**（它编的就是邀请链接，只多养 cv2 + `team_qr.py` + 4 个测试），只留 **6 位码 + 邀请链接**；`/pair?code=` 落地页保留。前端原本只有发出端、同事收到链接**软件里没地方粘** ⇒ 新增 `teamInvite.ts`（`parseInvite()` 认三种粘贴形态：纯码 / 带码链接 / 光地址；**不联网不猜**，认不出就说原因）。链接已带地址时走 `joinByLink()` 直接换令牌、**不发 UDP 广播**——跨网段（不同 AP / 禁广播）时这是唯一能通的路径。
- 0.3.46~0.3.50 已落（细节查 `docs/CHANGELOG.md`）：主人自举成员+owner.json chmod 600；拉取前另存本地工程（`teamBackup.ts`，名字带「覆盖前 月-日 时:分」）+ 拉完自动 claim 不抢锁；历史版本面板 + `Hub.rollback`（**历史只增不删**，回滚=又提交一版旧内容，`base_rev` 不符 ⇒ Conflict）；素材段类型 chip + 搜索（`assetFilter.ts`，两种空结果分开说）。
- **仍存的隐患**：版本全量快照会无声膨胀；`claim` TTL 600 无续约/无释放时机（幽灵锁）；`diff` 只比结构不比素材。
- 🔴 **画布里 `tick` 是高频函数名**，新函数别用它（质量棘轮 `dupNames` 只数重名个数，重名一个就红）。
- 方案文档：`docs/_reports/2026-11-04-团队协作对标与新版方案.md`。
