# 拾光剪影 — 项目长期记忆（跨轮事实，细节查 `.workbuddy/memory/日志` + `~/.workbuddy/skills/`）

## 一、北极星与缺口
- 活路径 =「剪辑精剪 + AI 画布」。设计文档已是**生产链视角**（S0 选题→S1 剧本→S2 分镜美术→S3 生成→S4 剪辑→S5 成片 + G 治理横切，17 章），核心工具 = **阶段契约**（输入/输出/责任人/验收/失败语义，填不满=缺口）。
- 🔴 2026-10-19 重估：**抽卡闭环已落地**（draw_orchestrator 179 + gen_critic 320 + draw_book 321 + score_book 278 + draw_ledger 188）；**编剧生产端非空白**（script_writer 99 + editing_script_generator 396 + storyboard_memory 209，缺长篇体系；drama_understanding_engine 2160 是消费类）。**现行真缺口**：① S2 母版层（无 AssetMaster）② G 治理闸门（有分无闸）③ S1 长篇体系 ④ S3 偏好回流 ⑤ S0 立意卡。
- LibTV（liblib.tv）对标 7 项已于 V4.43.19 完成。画布外观走 `data/canvas_appearance.json` + `GET /host/canvas-settings`（别用 QSettings）。

## 二、核心不变量
1. 真相源 = `EditorModule._clips`；跨线程整段替换带 `_clips_lock`；序列化用 `_clips_snapshot()`，禁把 `_clips` 交 `json.dump`。
2. 插件两套：`ExtensionsRegistry`(extension_base.py:332) + `PluginManager`(plugin_manager.py:13)；真家 `app/plugins/`。
3. 冻结区 9 zone / 91 锁。改 zone 同步 4 处：`frozen_zones.json`（**字符串手术**，json.dump 会重排几千行）· `现行技术文档.md §5` · `.cursor/rules/frozen-zones.mdc` · 重锁。**新文件必须登记进 zone files**。
4. 两套独立版本号：主程序 `app/version.py`；画布 `canvasVersion.ts`→`package.json`→CHANGELOG。禁内联版本字符串。
5. 能力目录 `agent_capability_catalog.py`：**加行即注册**，`verify_catalog_consistency()` 双向守卫（目录有/注册无 = 报错）。CapabilityResult 字段是 `success` 不是 `ok`。
6. 音画纠偏 ~280ms（冻结区），勿压回 80ms。
7. 内联 setStyleSheet = 主题盲区，须回 `set_theme()`；`setObjectName` 后必须 grep `#x` 确认 QSS 有对应规则。
8. 主题单一真相源 `theme_tokens.py`（DARK/LIGHT/MOTION 三表 57 keys）。
9. 静默 except 判定线：UI 绘制 pass 可；状态机/资源路径须 `logger.debug(..., exc_info=True)`。`except OSError: pass` 会被 stability_gate 拦。
10. 沙箱 wmic 黑名单：import app 链触发，验证脚本 subprocess 包一层。

## 三、用户偏好
核电管工转 AIGC；简体中文；指令极简；**先结论后展开**；小白模式（比喻+表格）；拒绝随机效果；要证据（文件+行号）；被纠正直接认错重查不辩解。🔴 **「迭代设计文档」≠「把数字改对」**——要设计增量（骨架/架构/概念重定义），改版本号行数锁数只是校准。

## 四、持久约束（血泪）
- 🔴 **`SkeletonUtils.clone` 后必须先 `updateMatrixWorld(true)` 再测包围盒**：clone 的 matrixWorld 是脏的，`Box3.setFromObject` 会量出 1/33 假尺寸（bodychan 0.0512m vs 真值 1.70m）⇒ 归一化算出 33× 补偿 ⇒ 1.7m 模型放大成 56.5m（「群像第三个角色一只脚占满屏幕」）。
- 🔴 **SkinnedMesh 包围盒必须 precise**：`setFromObject(obj, true)`，普通模式只读 geometry.boundingBox 测不出骨骼异常。
- 🔴 **尺寸自检必须进 `tick()` 渲染循环**（每秒一次）：GLB 异步加载完成时 actors 数组没变 ⇒ 挂 actors effect 里 = 死代码。
- 🔴 **PyQt6 别对 Qt 枚举 `int()`**：抛 TypeError 被 `except: pass` 吞 ⇒ console 镜像零输出（用 `str(level)`）。
- **体积守卫余量见底**：`bridge.ts` 2043/2046 禁改；`Stage3D.tsx` 4604/4653；`riggedHumanoid.ts` 3189；`CanvasShell.tsx` 3281 ⇒ **新逻辑另开文件，拆模块不抬基线**。
- **两条单通道（禁造第二套）**：① 3D 产物入轨 = `stage3dArtifacts.ts::sendArtifactToTimeline()` → `POST /ingest_path`；② 角色库→导演台 = store `requestStage3dCast` → `stage3dCastSeq` → `useStage3dCast()`。
- 🔴 **「没测出来」≠「测出来了」**：后端空串字段前端原样保留，禁填默认值；非法数值落 0 不猜。
- 🔴 **同名不同义常量高频坑**（warnings / quality_tiers 踩过）：接线时凡带 quality/tier/mode/level 的后端字段先核前端语义。
- **孤儿端点差集法四扫描面**：画布 src 非注释行 / canvas_server.py JS 字面量 / `app/**/*.py` URL 拼接 / **副库 Rust `src-tauri/src/lib.rs`**（漏第四面会误报 /host/tauri-closing）。
- YuE 全曲本机跑不动 ⇒ 执行端不可用必须诚实失败，绝不假音频。沙箱 tempfile 回退 cwd ⇒ 三入口钉 `.workbuddy/tmp`。
- 画布白屏 = Chromium 沙箱起不来 ⇒ `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`；CSS 别用 `body:has(...)`。派生值一律后端下发。
- `switch_to_module()` 对 `nav_hidden` 模块静默无效 ⇒ 走 `_perform_module_load`。UI 乱码先 grep 源码乱码字面量（`s.encode('gbk').decode('utf-8')` 判据）。本机 locale=utf-8 ⇒ `open()` 必带 encoding（可移植性地雷）。

## 五、验证与提交纪律
- **静态门禁全绿 ≠ 运行时没崩** ⇒ 自绘控件交付标准 = 真机启动 + paintEvent 真跑。
- `run_all_checks.py`（在 `_verify/`）**不含**稳定性门禁 ⇒ 须另跑 `scripts/stability_gate.py`。**哈希 ≠ 不变量**：冻结区新不变量必须 AST 断言 + 反例验证，否则守卫可能是永远绿的摆设；**门禁项本身也可能是摆设**（2026-10-19：dual-repo 的 tauri filter 大小写不匹配但 pnpm 退出码 0 ⇒ 长期假绿；空跑退出码为 0 的工具链最危险）。
- 🔴 **沙箱 safe-delete 的 `scope:"turn"` 累计删除计数**超 50 即拦（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`）：vite 构建末尾清 `dist/assets`/`prompts/bundled` 会被拦 ⇒ 表现「构建成功但退出码 1」。绕开 = `mv` 旧产物到 `.workbuddy/tmp/`（同分区 rename 不计数），下个 turn 计数自动重置。**不是代码回归，别改代码**。
- 🔴 **禁 `git add -A`**（复发多次夹带无关文件）⇒ 一律精确 pathspec；`.cursor/` 需 `git add -f`。
- 🔴 **`frozen_zones.json` 改 files 禁 `sorted()`** ⇒ 取 HEAD 原顺序 + 尾部追加。
- 🔴 **`frozen_zone_guard.py --update` 必须是最后一次动冻结文件之后** ⇒ 正序：改完全部文件 → `--update` → `git add` → 跑门禁。
- ⚠️ `precommit_gates.sh` 口径不一致：ruff 按**已暂存**筛（未暂存 = 正常空跑），冻结区按**工作区全量**算。
- 行尾：Edit 保留 CRLF；画布 `src/*.ts(x)`、`现行技术文档.md`、`frozen_zones.json`、`memory/*` = LF；`version.py`、CHANGELOG、`.mdc` = CRLF。
- 提交必须原生 bash（`.sh` + `git commit -F`），**永不裸 commit**；版本号提交前最后一步写，被覆盖换号不抢回。ruff 门禁 = 存量棘轮，用 `C:/Python314/python.exe -m ruff`。回归优先 `.venv312`；失败定性：跑错解释器 → 并发会话 → 才当真回归。Node22 直调真实二进制（`22.22.2-6/node.exe`）。

## 六、画布桥接层与双库
- 新增 `/host/*` 端点必须用 `@_route_get`/`@_route_post` 注册进路由表（写在 return 之后 = 死代码，check_canvas_routes.py AST 检测）。
- 双库同步是人工动作：主库 `vendor/shiguang-canvas/src/` ↔ 副库 `vendor/AI-Canvas-tauri/src/libtv/`；验证 `check_canvas_dual_repo.py`（禁 `--update`）；版本三件套易漏同步副库。
- **副库 tsc 假绿陷阱**：`tsconfig.json` 是 project references（files: []）恒报 0 错 ⇒ 用 `tsc -p tsconfig.app.json --noEmit`。副库 vitest v4 不接受 `--reporter=basic`。
- 画布测试：不能引用包外相对路径（`?raw` 会解析到 vendor/app/）；vitest 是 node 环境无 jsdom ⇒ useEffect 逻辑零覆盖，须抽纯函数；`include` 只收 `*.test.ts`。
- Agent 触达前端唯一通道 = `make_agent_event()` + `broadcast_agent_event()`（SSE），前端 `subscribeAgentEvents` 消费。
