# 拾光剪影 — 项目长期记忆（北极星 + 不变量 + 偏好）

> 知识库 `docs/_archive/knowledge/INDEX.md`（00–19）：00 概览 · 05 已知问题 · 08 冻结区 · 17 磁吸/动捕 · 19 画布概论。版本史 `docs/CHANGELOG.md`；逐轮明细 `.workbuddy/memory/YYYY-MM-DD.md`。本文件只留跨轮事实，**细节查技能**（`~/.workbuddy/skills/`：frozen-zone-release · shiguang-guard-diagnostics · agent-capability-wiring · monolith-strangler-migration · serialization-field-symmetry · benchmark-before-optimize · shared-state-locking-proof · mjs-mirror-test · qt-visual-change-verification · python-coldstart-profiling · git-mass-deletion-triage · ast-scope-nameerror-hunt）。复核 2026-10-12。

## 一、产品北极星
- 活路径 = 「剪辑精剪 + AI 画布」：精剪→人工改→文案→选题。能力补齐顺序：**④抽卡 → ①编剧 → ②导演·节奏 → ③美术·母版**；四大缺口 = 编剧生产端 / 抽卡选优闭环 / 资产母版层 / 审美治理层。
- 对标 **LibTV（`www.liblib.tv`）**：人类 UI + Agent OpenAPI 双入口 → `docs/_reports/2026-10-12-LibTV网页功能逆向报告.html`。LibTV 对标 7 项接线已于 V4.43.19（commit aeee5a35）完成：超分/抠像/深度/拉片/片段重拍/文本生剧本/导演落时间线。
- 画布外观通道 = `data/canvas_appearance.json` + `GET /host/canvas-settings`（**别用 QSettings**：沙箱写注册表 AccessError）。`modules.py:1234 _show_login_dialog` 是死代码。
- 真缺口 9 刀规划（2026-10-12 定稿，待拍板）：A 线资产母版层（A1 场景库起步）→ B 线剧本生产端 → C 线对外 Agent OpenAPI（做不做待拍板）。音色库已存在（voice_clone.py）。

## 二、核心不变量（改动前必读）
1. **真相源** = `EditorModule._clips`；跨线程整段替换 `with self._clips_lock:`；序列化/遍历用 `_clips_snapshot()`，绝不把 `self._clips` 交给 `json.dump`。
2. **插件两套**：`ExtensionsRegistry`(`app/core/extension_base.py:332`) + `PluginManager`(`app/core/plugin_manager.py:13`)；真家 `app/plugins/`。
3. **冻结区 9 zone / 91 锁点**。守卫 `scripts/frozen_zone_guard.py`（`--update`/`--list`，无参即校验）。改 zone 同步 4 处：`frozen_zones.json`（**字符串手术**，json.dump 会重排成几千行 diff）· `现行技术文档.md §5` · `.cursor/rules/frozen-zones.mdc` · `--update` 重锁。**新文件必须登记进 zone files**。**哈希 ≠ 不变量**（§六）。
4. **两套独立版本号**（刻意不同步）：主程序 `app/version.py`、画布三件套 `canvasVersion.ts` → `package.json` → CHANGELOG。禁内联版本字符串。
5. **单一来源**：Agent 常量 `agent_constants.py`；能力目录 `agent_capability_catalog.py`（加行即注册，`verify_catalog_consistency()` 双向守卫；CapabilityResult 字段是 `success` 不是 `ok`）。
6. **音画纠偏 ~280ms（冻结区）**，勿压回 80ms。
7. **内联样式 = 主题盲区**：新 `setStyleSheet` 控件必须回 `set_theme()` 补刷新；新控件走 `theme_manager._build_qss`。**QSS 陷阱**：`setObjectName("x")` 后必须 grep 一次 `#x`，否则静默退回默认样式；内联 setStyleSheet 优先级高于全局 QSS。
8. **主题配色单一真相源** = `theme_tokens.py`：DARK/LIGHT/MOTION 三表 57 keys/套；主蓝 `#2f7bff`(accent)、紫罗兰 `#6366f1`(brand)。
9. **静默 except 判定线**：UI 绘制 `pass` 可接受；状态机/资源路径 `pass` 须 `logger.debug(..., exc_info=True)`。`except OSError: pass` 会被 stability_gate 拦 ⇒ 别 `--update` 洗掉。
10. **沙箱 wmic 黑名单**：import app 链触发；验证脚本用 subprocess 包一层。

## 三、用户偏好
核电管工转 AIGC；简体中文；指令极简（「继续/开始」）；**先看结论再展开**；小白模式（比喻+表格）；规划→「开始」→汇总→「继续」；**拒绝随机效果**；要证据（文件+行号）；会主动纠正美化臆测，被纠正后直接认错重查不辩解。

## 四、持久约束（跨轮）
- **体积守卫余量见底**（2026-10-12）：`bridge.ts` 2043/2046（**禁改**）；`store.ts` 2502/2513；`Stage3D.tsx` 4604/4653；`riggedHumanoid.ts` 3159/3189；`CanvasShell.tsx` 3113/3229 ⇒ **新逻辑另开文件，拆模块不抬基线**。
- **静默失效坑**：① `HUMAN_PRESETS[].heightScale` 在导演台被 `Stage3D.tsx:1489` 的 `actor.scale` 覆盖 ⇒ 体型缩放用 `VARIANT_SCALE`；② 角色库动态表单只认 `text/string`，enum 字段须 `_ENUM_SOURCES` + `_enum_combos` 五处同步。均已由 `check_character_schema.py` ⑦⑧ 锁住（反例 5/5 报红）。
- **两条单通道（禁止造第二套）**：① 3D 产物入轨 = `stage3dArtifacts.ts::sendArtifactToTimeline()` → `POST /ingest_path`（data URL 先 `/host/upload-asset` 落盘）；② 角色库→导演台 = store `requestStage3dCast` → `stage3dCastSeq` 递增 → `useStage3dCast()` 消费。全链路零随机（id 哈希配色）。
- **孤儿端点缺口**：「后端齐全、前端无调用者」⇒ 接线性价比远高于造新。⚠️ **差集法本身必须先自检**（2026-10-15 三轮结论都不可信）：**四个扫描面**（画布 `src` 非注释非测试行 / `canvas_server.py` 的 JS 字面量 / `app/**/*.py` 的 URL 拼接 / **副库 Rust `src-tauri/src/lib.rs`**——第四面是 2026-10-15 第 4/5 条补上的，否则 `/host/tauri-closing` 被误报成孤儿）。基线：**85 端点 = 已接线 70 + 真孤儿 15** ⇒ 第 4/5 条消掉 2 组（3 端点）⇒ **剩 11**。已判定**不该接**的：`providers`（= `ai-config-patch` 别名，同一 handler）、`generate-video`/`video-generate`（被 `/host/generation/submit` 取代的历史端点）、`reference-breakdown` L1（L2 的子集）。
- 🔴 **「半成品缺口」是独立一类**（前端比后端多走一步、停在半路）：`referenceBreakdownL2` 桥函数 + 类型 + re-export 早就在，**零 UI 调用者**。找法 = grep 桥函数定义，看有没有 UI 层 import 它。
- 🔴 **「没测出来」≠「测出来了」**（2026-10-15 新增铁律）：后端给空串的字段（深度拉片 `景别`/`运镜`）前端**原样保留空串，绝不填默认值**；非法数值落 0 不猜；`keyframe` 是磁盘绝对路径 ⇒ **不塞 `frameUrl`**（WebView 加载不了 `D:\`）；要开云端视觉（素材出域）默认 false + 用户显式勾选。
- 🔴 **破坏性快照的三条限制**（`project-snapshot`）：① docstring 说「每次导出自动 push」但**实测 export 没调 push** ⇒ **只有 import 会长栈，空栈是真实状态**；② `list()` 白名单裁剪没有 clips；③ 🔴 **`restore` 不 push 且前端无 push 端点 ⇒ 回滚不可再回滚**，唯一兜底是先导出，二次确认必须写明。
- 🔴 **同名不同义的常量 = 本项目高频坑**（踩过 3 次：`bridge.ts` 的 `warnings` 字段不对称、`/host/enhance-intents` 的 `quality_tiers`=fast/standard/high vs 前端 `QUALITY_TIERS`=draft/standard/fine/cinema）。**接线时凡带 `quality/tier/mode/level` 的后端字段，先核前端同名常量是不是同一语义**，不确定就别暴露那个字段 + 写测试反锁。
- **端点接线三条硬纪律**：① 判定逻辑一律留后端，前端只展示（结论文案**逐字用后端 `summary`**，不自造）；② **不渲染「点了必然失败」的死按钮**（`heal` 缺遮罩入口、`style` 无风格选择器会静默套默认 cyberpunk ⇒ 白名单只留 `face/cutout/sharpen`，用 `excludedIntents()` 如实说明）；③ 后端同函数已 SSE 推的事件（如 `compliance.report`）**不新增第二条 HTTP 推送通道**。
- **YuE 全曲**：本机跑不动 ⇒ 只能远程 `SHIGUANG_YUE_ENDPOINT` / 本地 `SHIGUANG_YUE_HOME`；执行端不可用必须诚实失败，绝不假音频/静默降级。
- **沙箱 tempfile 回退 cwd** ⇒ 三入口钉 `.workbuddy/tmp`：根 `conftest.py`、`run_all_checks.py`、直接单跑的 `_verify` 脚本。
- `.venv312` 依赖更全；系统 Py3.14 出误导告警；「未检测到 GPU」是假的（nvidia-smi 探测）。
- **画布白屏 = Chromium 沙箱起不来**（连 `data:` URL 都失败）⇒ `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`。**CSS 别用 `body:has(...)`**（Qt WebEngine 不可靠）⇒ MutationObserver + 内联样式（范例 `CanvasOverlays.tsx`）。
- **派生值一律后端下发**（角色提示词 `canvas_routes_get.py:115`），前端别自己算。
- 3D 辅助物打 `userData.isHelper`，渲染前 `setHelpersVisible(false)` 后还原（四处）；**只还原自己改过的对象**。
- `check_global_price.py:155` 固定值日期炸弹 —— **既有问题，只报不擅改**。
- **`switch_to_module()` 对 `nav_hidden` 模块静默无效**（V4.43.9「设置打不开」根因）⇒ 走 `_perform_module_load` / `_activate_module`。「没反应且日志无异常」先查前置守卫。
- **UI 乱码先 grep 源码乱码字面量**（判据 `s.encode('gbk').decode('utf-8')` 成功且含中文），未命中才查字体/i18n。offscreen 下 `QFontDatabase.families()` 返回空，须 addApplicationFont 否则汉字变方块。
- **本机 locale=utf-8**：`open()` 无 encoding 本机不炸、GBK 机器必炸 ⇒ 可移植性地雷（审计 2026-10-12 发现 22 处，详见当日日志）。

## 五、验证与提交纪律（血泪）
- **静态门禁全绿 ≠ 运行时没崩**（V4.43.4 QColor 崩例）⇒ 自绘控件交付标准 = 真机启动 + paintEvent 真跑。
- **门禁 12 道**（② 后含 ③b exit_media_invariant）。`run_all_checks.py` **不含** ④ 稳定性 ⇒ 改完须连 `scripts/stability_gate.py` 两道都跑。
- **哈希 ≠ 不变量**：冻结区新不变量必须 AST 断言 + 反例验证，否则守卫可能是永远绿的摆设。
- **行尾纪律**：Edit 保留 CRLF；画布 `src/*.ts(x)`、`现行技术文档.md`、`frozen_zones.json`、`.workbuddy/memory/*` = LF；`version.py`、`CHANGELOG.md`、`.cursor/rules/*.mdc` = CRLF。重写 CRLF = Write 临时文件 → Python 换行 → 写回；`version.py` 用整体 Write。
- **提交**：必须原生 bash 发起（生成 `.sh` + `git commit -F 消息文件`，别用 Python 派生 git）；**永不裸 `git commit`**；版本号提交前最后一步写，被覆盖**换号不抢回**；`--no-verify` 是最后手段须双份登记（CHANGELOG + 提交消息）+ 归属与零交集判定。
- 🔴 **禁 `git add -A`**（2026-10-15 复发两次，D8C低那轮夹带 46+ 文件）：它本身就是绕过「暂存范围确认」的手法，不只是「忘了确认」。⇒ 一律**精确 pathspec**；`.cursor/` 被 gitignore 但已跟踪 ⇒ 需 `git add -f`。
- 🔴 **`frozen_zones.json` 改 files 列表禁止 `sorted()`**（2026-10-15 踩了两次）：一排序 35 项顺序全变，diff 从 8/5 纯增量变成 24/21。正解 = **取 HEAD 原顺序 + 尾部追加**（`subprocess` 读 `git show HEAD:` 再拼）。
- 🔴 **`frozen_zone_guard.py --update` 必须是最后一次动冻结文件之后**（2026-10-15 踩）：先重锁、后改 `canvasVersion.ts`（版本号也是 zone8 文件）⇒ 门禁 ③ 又报漂移，白跑一轮。正序：**改完全部文件 → 最后 `--update` → 再 `git add` → 再跑门禁**。
- ⚠️ **`precommit_gates.sh` 各道口径不一致**：① ruff 按**已暂存**的 `.py` 筛范围 ⇒ 未暂存时打印「无可检查的受控 .py」是**正常空跑**不是失败；但 ③ 冻结区按**工作区全量**算 ⇒ 未暂存也拦。别把空跑误判成失败（或反之）。
- **`check_canvas_dual_repo` 报「新分叉: X」时的正确处置**：先 `git show HEAD:<主库文件>` 与副库文件 `diff -q` ⇒ **一致**说明分叉确由本轮引起，直接同步；**不一致**是历史分叉，要人工核对。**别直接 `--update` 洗掉**。
- **Markdown 工具噪音**：Prettier 类编辑器会自动重排表格对齐 + 加尾随空格（`docs/画布可借鉴清单落地规划_2026-10-15.md` 被改）⇒ 提交前 `git status` 逐项核，非本轮改动一律 `git checkout --` 回退。
- **ruff 门禁 = 逐文件存量棘轮**（`scripts/ruff_gate.py`）；`.venv312` 无 ruff，用 `C:/Python314/python.exe -m ruff`。
- **回归**：`_verify/run_all_checks.py` 优先 `.venv312`；失败定性顺序 ① 跑错解释器 ② 撞并发会话 ③ 才当真回归。`check_canvas_bridge_e2e.py` 真起服务最有价值。
- **Node22**：`node_modules/.bin` shim 挂 ⇒ 直调真实二进制（tsc / vitest.mjs / vite.js）。node 路径 `.../22.22.2-6/node.exe`（勿写 -3，错路径 + 管道 = tsc 假绿）。
- 误报人工定性 + 写进 CHANGELOG；git 统计 `--numstat` + `-c core.quotePath=false`；`.gitignore` 目录里已跟踪文件删除仍会被 `git add -A` 暂存（`D ` 在第一位 = 已暂存）。

## 六、画布桥接层与双库
- 新增 `/host/*` 端点一律 `@_route_get`/`@_route_post` 注册进路由表（写在 `return` 之后 = 死代码，`check_canvas_routes.py` AST 检测）。
- **双库同步是人工动作**：主库 `vendor/shiguang-canvas/src/` ↔ 副库 `vendor/AI-Canvas-tauri/src/libtv/`（gitignored 改前必备份，非硬链接）；验证 `check_canvas_dual_repo.py`（禁 `--update`）。**版本三件套易漏同步副库**（V4.43.19 被抓过）。
- **副库 tsc 假绿陷阱**：`tsconfig.json` 是 project references（`files: []`）⇒ 恒报 0 错误；正解 `tsc -p tsconfig.app.json --noEmit`（基线 38）。副库 vitest 是 v4，不接受 `--reporter=basic`。
- **画布测试文件不能引用本包外相对路径**（`?raw` 同步后会解析到 vendor/app/）；无 `@types/node`；读源码用 Vite `?raw`；**跨语言断言放 Python 门禁**。vitest 是 node 环境无 jsdom ⇒ useEffect 逻辑零覆盖，须抽纯函数；`include` 只收 `*.test.ts`。
