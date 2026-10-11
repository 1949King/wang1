# 拾光剪影 — 项目长期记忆（北极星 + 不变量 + 偏好）

> 知识库 `docs/_archive/knowledge/INDEX.md`（00–19）：00 概览 · 05 已知问题 · 08 冻结区 · 17 磁吸/动捕 · 19 画布概论。版本史 `docs/CHANGELOG.md`；逐轮明细 `.workbuddy/memory/YYYY-MM-DD.md`。本文件只留跨轮事实，**细节查技能**。复核 2026-10-12。
> 技能（`~/.workbuddy/skills/`）：`frozen-zone-release` · `shiguang-guard-diagnostics` · `agent-capability-wiring` · `monolith-strangler-migration` · `serialization-field-symmetry` · `benchmark-before-optimize` · `shared-state-locking-proof` · `mjs-mirror-test` · `qt-visual-change-verification` · `python-coldstart-profiling` · `git-mass-deletion-triage` · `ast-scope-nameerror-hunt`

## 一、产品北极星
- 闭环 7 阶段；V4.19.0 起「发布/采集/优化建议」下线，活路径 = 「剪辑精剪 + AI 画布」：精剪→人工改→文案→选题。优先级：先剪辑（稳→快→全→可维护），后 AI 闭环。仍缺：选题自动导入时间线 / 一键粗剪写 `_clips`。
- 外观线 V4.43.0~V4.43.4 完成（直抄 AI-Canvas-tauri → 设置对齐 → `module_registry` 加 `nav_hidden` + 背景 6 预设 → 外观页 2×2 卡墙）。**「该露几个」以用户视觉稿为准，不以开源有几个为准。**
- 画布外观通道 = `data/canvas_appearance.json` + `GET /host/canvas-settings`（**别用 QSettings**：沙箱写注册表返回 `Status.AccessError`）。登录窗口无设置；`modules.py:1234 _show_login_dialog` 是死代码。
- 能力补齐顺序：**④抽卡 → ①编剧 → ②导演·节奏 → ③美术·母版**；四大缺口 = 编剧生产端全空 / 抽卡选优闭环缺失 / 资产母版层弱 / 审美治理层散落无管辖。
- 对标 **`www.liblib.tv`**（LibTV，Next.js 无限画布 + 人类 UI / Agent OpenAPI `im.liblib.tv` 双入口）→ `docs/_reports/2026-10-12-LibTV网页功能逆向报告.html`。

## 二、核心不变量（改动前必读）
1. **真相源** = `EditorModule._clips`（勿用 `AppState`/孤儿 `ExportRenderer`）。跨线程共享**必须持锁 RLock**：整段替换 `with self._clips_lock:`；序列化/遍历用 `_clips_snapshot()`，绝不把 `self._clips` 交给 `json.dump`。
2. **插件两套**：`ExtensionsRegistry`(`app/core/extension_base.py:332`) + `PluginManager`(`app/core/plugin_manager.py:13`)；真家 `app/plugins/`。
3. **冻结区 9 zone / 90 锁点**（2026-10-12；zone7 `stage3d-core` 7→**12** 文件）。守卫 `scripts/frozen_zone_guard.py`（**仅** `--update`/`--list`，无参即校验；基线 `frozen_zones.hashes.json`）。改 zone 必同步 4 处：`frozen_zones.json` · `现行技术文档.md §5` · `.cursor/rules/frozen-zones.mdc` · `--update` 重锁。**新文件必须登记进 zone 的 `files`**。`frozen_zones.json` 用**字符串手术**改（`json.dump` 会把超长 reason 重排成几千行 diff）。**哈希 ≠ 不变量**（§六）。
4. **两套独立版本号**：主程序 `app/version.py`、画布 `src/canvasVersion.ts`，**刻意不同步**。改画布版三件套 `canvasVersion.ts` → `package.json` → CHANGELOG。禁内联版本字符串。
5. **单一来源**：Agent 常量 `app/core/agent_constants.py`；能力元数据 `app/core/agent_capability_catalog.py`（新增能力唯一入口 = 目录表加一行，`verify_catalog_consistency()` 守卫）。
6. **音画纠偏 ~280ms（冻结区）**，勿压回 80ms。
7. **内联样式 = 主题盲区**：新 `setStyleSheet` 控件必须回 `set_theme()` 补刷新（深底 `#edf3ff` / 浅底 `#172033`）；新控件走 `theme_manager._build_qss` 模板。
8. **主题配色单一真相源** = `app/core/theme_tokens.py`：DARK/LIGHT/MOTION 三表 57 keys/套。主蓝 `#2f7bff`(accent) 保留、品牌紫罗兰 `#6366f1`(brand) 新增，LEGACY_KEYS 19 个全保留。
9. **静默 except 判定线**：UI 绘制 `pass` 可接受；状态机/资源路径 `pass` 不可接受（须 `logger.debug(..., exc_info=True)`）。例外 `except RuntimeError: pass` 有意保留。新写 `except OSError: pass` 会被 `stability_gate` 拦 ⇒ **别 `--update` 洗掉**。
10. **沙箱 wmic 黑名单**：import app 链触发 config_manager 的 wmic；验证脚本用 subprocess 包一层、写干净 UTF-8 再读。

## 三、用户偏好
核电管工转 AIGC；简体中文；指令极简（「继续/开始/要/一起开始」）；**先看结论再展开**；小白模式（比喻+表格）；节奏 规划→「开始」→汇总→「继续」；**拒绝随机效果**；前后端强绑定；情绪化时专业耐心推进、不回怼。素材库仅本机；素材网站直达在「帮助」。

## 四、分区索引
- 磁吸不变量 → `17-canvas-magnetic-invariants.md` + `08-frozen-zones.md`；角色库字段 → `_verify/check_character_schema.py`（⑥~⑧）
- 画布桥接层（`@_route_*` / SSE / 端口 18765）→ `19-canvas-design-review.md` + `05-known-issues.md`；参考视频驱动生视频 → `17-motion-ref-design.md`（刀1/2/3 完成，下一刀 = 刀4）
- Agent 人格「知心秘书」+ 温度开关 → `app/core/agent_persona.py`；冷启动（8.24s→0.191s）→ `docs/冷启动性能诊断报告.md`；代码基线 228,583 行 → `docs/_reports/2026-09-19-全库代码评价报告.md`

## 五、持久约束（跨轮，改动前必读）
- **体积守卫余量见底，改前先算行数预算**（2026-10-12 实测）：`bridge.ts` **2043/2046（仅 3 行 = 禁改）**；`store.ts` 2502/2513；`Stage3D.tsx` 4604/4653；`riggedHumanoid.ts` 3159/3189；`CanvasShell.tsx` 3113/3229。⇒ **新逻辑一律另开文件，冻结文件只留「1 行 import + 薄入口」；拆模块，不要抬基线**（守卫输出的「修复指引：拆模块」就是标准答案）。
- **两个静默失效坑（2026-10-12 查实）**：① `HUMAN_PRESETS[].heightScale` **在导演台失效** —— `riggedHumanoid.ts:1334` 设了 `root.scale=heightScale`，但 `Stage3D.tsx:1489` 紧接着 `obj.scale.setScalar(a.scale)` 覆盖同一对象 ⇒ 真正决定大小的是 `actor.scale`；体型缩放要用与 `ACTOR_PRESETS` 一致的 `VARIANT_SCALE`（儿童 0.58），照 heightScale（0.74）写会造出「同一体型两种身高」。② 角色库动态表单**只认 `text/string`** ⇒ 新加 `enum` 字段「标题看得见、值填不了」；须在 `_ENUM_SOURCES` 登记，且 `_enum_combos` 在 建控件/load/clear/set_enabled/_collect_data **五处**同步。两坑已由 `check_character_schema.py` ⑦⑧ 锁住（**反例验证 5/5 报红**）。
- **两条单通道（都禁止造第二套）**：① **3D 产物入轨** = `stage3dArtifacts.ts::sendArtifactToTimeline()`，复用后端既有 `POST /ingest_path`（`canvas_routes_post.py:274`，收**本机路径**、原生支持 `send_to_editor`）；只有 data URL 的产物（如 ControlNet）先经 `POST /host/upload-asset` 落盘拿 `path`。禁写 `/host/stage3d-to-timeline` 或别处自己 fetch。② **角色库 → 3D 导演台** = store 的 `requestStage3dCast` → `stage3dCastSeq` 递增 → `stage3dCast.tsx::useStage3dCast()` 消费一次（照抄 `stage3dApplySeq`；两者分属不同组件树，store 是唯一可测会合点）。**全链路零随机**：体型取 `human_variant`（缺省按性别/年龄段确定性兜底）、发型随体型、配色由 id 哈希。
- **一整类「后端齐全、前端无调用者」的孤儿端点缺口**（2026-10-12 两处独立发现：`/ingest_path`；LibTV 对标里片段重拍/深度捕捉/拉片/超分/抠像/文本生剧本/导演落时间线 7 条）⇒ **接线性价比远高于造新**；查缺口先全库 grep 端点名确认有无调用方。
- **YuE 全曲生成**：`app/core/ai/yue_music.py` + `POST /host/yue/*`。官方要 Linux+Py3.12+NVIDIA≥24GB，本机 RTX4060(8GB) 跑不动 ⇒ 只能远程 `SHIGUANG_YUE_ENDPOINT` 或本地 `SHIGUANG_YUE_HOME`。**执行端不可用必须诚实失败，绝不返回假音频/静默降级 Suno。**
- **沙箱 `tempfile.gettempdir()` 回退到 cwd（%TEMP% 不可写）** ⇒ 仓库根累积 `sg_*/cover_*/pip-*/pytest-of-*`。三入口钉 `.workbuddy/tmp`：根 `conftest.py`、`_verify/run_all_checks.py`、直接单跑的 `_verify` 脚本。
- **`.venv312` 依赖更全**；系统 Python 3.14 启动出误导告警；「未检测到 GPU」是假的（`_detect_nvidia()` 走 nvidia-smi，RTX4060 8188MiB）。别重启、别改编码逻辑。
- **画布白屏 = Chromium 沙箱起不来**（判据：连 `data:` URL 都失败）⇒ `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`；先 `netstat` 确认服务活着。**画布 CSS 别用 `body:has(...)` 做让位/联动**（Qt WebEngine 对 `:has()` invalidation 不可靠）⇒ MutationObserver + 内联样式（范例 `CanvasOverlays.tsx`）。
- **派生值一律后端下发**（角色提示词 `canvas_routes_get.py:115`、分镜记忆保留率），前端别自己算。
- **3D 导演台辅助物打 `userData.isHelper`**，渲染前 `setHelpersVisible(false)`、后还原（四处：captureDepthMap/NormalMap、`Stage3D.capture()`、机位路径视频、白模姿势视频）；**只还原自己改过的对象**。
- **固定值比时间基准的用例都是日期炸弹**：`check_global_price.py:155` 硬编码 `record_spend(90.0)`（L0 已改 `over_paced_spend()`、L1 漏改），月初必红 —— **既有问题，只报不擅改**。
- **`switch_to_module()` 不能用于任何 `nav_hidden` 模块**（内部经 `_nav_bar.select_module()` 的 `if module_id in self._buttons:` ⇒ 对隐藏模块**静默无效、日志无异常**，V4.43.9「设置打不开」根因）⇒ 必须走 `_perform_module_load` / `_activate_module`。**「没反应且日志无异常」先查前置守卫。**

## 六、验证与提交纪律（血泪，改动前必读）
- **静态门禁全绿 ≠ 运行时没崩**：V4.43.4 十二道门禁全过、offscreen 多次全绿，真机 10 秒刷屏崩 —— `settings_widgets.py:950 QColor("#fff",80)`（PyQt6 `QColor` 无 `(name,alpha)` 重载）。⇒ **自绘控件（QPainter/QColor/QPen）交付标准 = 真机启动（不带 offscreen）+ 打开界面让 `paintEvent` 真跑**。细节见 `qt-visual-change-verification`。
- **门禁 12 道**（V4.43.14 起，② 后新增 ③b `_verify/check_exit_media_invariant.py`）。**`run_all_checks.py` 里没有 ④ 稳定性** ⇒ 改完须连 `scripts/stability_gate.py` **两道都跑**。
- **哈希 ≠ 不变量（2026-10-11）**：`frozen_zone_guard.py` 只比哈希 ⇒ 报得出「代码被改」，报不出「不变量被破」（实测会话保存被插到 `closeEvent` 第一句而静默失效；只看到「有漂移」就 `--update`，基线洗白后再也查不出）。⇒ **冻结区新增/修改的不变量必须落成 AST 断言 + 做「反例验证」（喂违规版本、确认必报红）；不做反例验证的守卫可能是永远绿的摆设。**
- **改文件后必核行尾**：Edit 保留 CRLF，但新写文件默认 LF、把 LF 文本插进 CRLF 文件会造裸 LF。判据 `裸LF = LF − CRLF 必须 = 0` 再 `--update`。约定：画布 `src/*.ts(x)`、`现行技术文档.md`、`frozen_zones.json`、`.workbuddy/memory/*` = LF；`app/version.py`、`CHANGELOG.md`、`.cursor/rules/*.mdc` = CRLF。重写 CRLF 文件 = Write 临时文件 → Python 换行 → 写回；**`version.py` 用整体 Write**（「只匹配头部」的 Edit 会留残片致语法错）。
- **用户说「启动程序」= 要看窗口**：只看启动链路加 `timeout 40`（可 offscreen），要真看界面**不加 offscreen/timeout** + `run_in_background=true`。
- **提交必须原生 bash 发起，别用 Python 派生 git**（sitecustomize shim 传给子进程 ⇒ git 派生 MSYS2 bash 报 `0xC0000022`）⇒ 生成 `.sh`（`git commit -F 消息文件`）由 bash 执行。
- **与并发会话共存**：① **永不裸 `git commit`**（暂存区共享）⇒ 永远 `git commit -F 消息文件 -- <精确清单>`。② **共享文件会被整文件覆盖**（2026-10-12：`version.py` 的 4.43.15 被对方 4.43.16 整体覆盖）⇒ **版本号放到提交前最后一步写**，被覆盖时**换号而非抢回**。③ 门禁被**对方在途代码**踩红时 `--no-verify` 是最后手段，理由须**双份登记**（CHANGELOG + 提交消息）并标注归属与「零交集」判定。
- **ruff 门禁 = 逐文件存量棘轮**：`scripts/ruff_gate.py` + `docs/knowledge/ruff_gate_baseline.json`。新文件 0 违规、已有文件只减不增。**别再退回整文件 check。**
- **回归**：`_verify/run_all_checks.py`（支持 `.mjs`），优先 `.venv312`。失败定性顺序 ① 跑错解释器 ② 撞并发会话 ③ 才当真回归。`check_canvas_bridge_e2e.py` 真起服务打 HTTP 最有价值。
- **Node22 + Windows：`node_modules/.bin/<tool>` shim 挂** ⇒ 直调真实二进制 `node node_modules/typescript/bin/tsc --noEmit` / `vitest/vitest.mjs run` / `vite/bin/vite.js build`。沙箱 Python = `/c/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`。
- **误报 / 清理 / git 统计**：启发式误报人工定性 + 写进 CHANGELOG（hook 不入库），别为过计数动代码结构。临时文件禁 `_*` 宽 glob，显式列名单 + `git ls-files` 区分自有/新建；沙箱每轮最多 50 次删除；跨盘 rename 报 WinError 17。git 统计用 `--numstat` + `-c core.quotePath=false`；未提交项用 `git status -uall`。仅本机未 push（`origin = github.com/1949King/shiguangjianying`）。
- **`.gitignore` 目录里「已被跟踪」文件的删除仍会被 `git add -A` 暂存**：改名后 `git status --short` 显示 `D `（**D 在第一位 = 已暂存**），无需再 add；`git add -u <dir>` 反而报 `pathspec did not match`。
- **UI 乱码先 grep 源码里的乱码字面量**（别先怀疑字体/i18n/编码）：命中即**源码字符串坏了**（`settings_module.py:314` = 「设置分类」的 UTF-8 字节被按 GBK 解码；判据 `s.encode('gbk').decode('utf-8')` 成功且含中文），未命中才查字体/i18n。离屏验证注意：offscreen 下 `QFontDatabase.families()` 返回**空列表**，须 `addApplicationFont('C:\\Windows\\Fonts\\msyh.ttc')` 否则汉字全变方块（验证手段的限制，与乱码无关）。

## 七、画布桥接层与双库约定
- 新增 `/host/*` 端点一律 `@_route_get`/`@_route_post` 注册进路由表，别塞进老 `if path ==` 链；写在 `return` 之后 = 死代码（`check_canvas_routes.py` AST 检测不可达路由 + 重复注册）。
- **双库同步是人工动作**：主库 `vendor/shiguang-canvas/src/`、副库 `vendor/AI-Canvas-tauri/src/libtv/`（**gitignored ⇒ 改前必备份**，**不是硬链接**）。验证 `_verify/check_canvas_dual_repo.py`（`_walk()` 只收 `.ts/.tsx`；`BASELINE_*` 硬编码在脚本里，**禁用 `--update` 消警告**）。改完主库不拷副库 ⇒ 立刻「新分叉」。
- ⚠️ **副库 tsc 的假绿陷阱（2026-10-12 实测）**：`AI-Canvas-tauri/tsconfig.json` 是 **project references**（`files: []` + `references`）⇒ 在那儿跑 `tsc --noEmit` **一个文件都不编译、恒报 0 错误**。正解 = `tsc -p tsconfig.app.json --noEmit`（当前 **38** = `libtv/riggedHumanoid.ts` 21 + `libtv/Stage3D.tsx` 16 + 1）。**「报 0 错误」先确认它真的编译了东西。** 副库 vitest 是 **v4**（主库 v2），**不接受** `--reporter=basic`。
- ⚠️ **画布测试文件不能引用本包外的相对路径**：`?raw` 同步到副库后 `../../../app/...` 会解析到 `vendor/app/`。本包**没装 `@types/node`** ⇒ 也别用 `node:fs`；读源码用 Vite **`?raw`**（类型来自 `src/vite-env.d.ts` 的 `vite/client`，零配置且能读 `.py`）。**跨语言断言放 Python 门禁。**
- vitest 是 `environment: "node"`（**无 jsdom / RTL / react-test-renderer**）⇒ `useEffect` 里的逻辑**零覆盖**，必须把编排抽成纯函数（如 `applyPendingCast(deps, pending)`）再喂假 deps。`vitest.config.ts` 的 `include` **只收 `*.test.ts`**。
- **QSS 陷阱**：`setObjectName("x")` 了但 QSS 里没写 `#x` ⇒ 控件静默退回 Qt 默认样式（一天撞 3 次：顶栏 `headerBarIconBtn`、角色工具栏内联硬编码色、通知中心 17 个 objectName 全无样式）。**加完 `setObjectName` 必须 grep 一次 `#x`**。内联 `setStyleSheet` 优先级高于全局 QSS ⇒ 浅色主题下必然出错。
