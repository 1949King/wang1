# 拾光剪影 — 项目长期记忆（跨轮事实，细节查 `.workbuddy/memory/日志` + `~/.workbuddy/skills/`）

## 〇、定位（2026-10-28 用户纠正，最高优先级，勿再犯）
🔴 **它是「通用创意生产工具 / 创意工作台」，不是「短剧剪辑工具」** —— 短剧只是其中一个用法场景。
- 输入 = 想法 / 素材 / 参考；输出 = 图 · 视频 · 3D · 成片。**画布是工作台，不是流水线**。
- 对标物：Figma（协作）· Miro（无限画布）· Canva（模板化生产）· ComfyUI（节点编排）· Runway/Pika（生成）· 剪映（剪辑）· DX-OS（同类）。
- 禁止：① 用「短剧」框定产品方向；② 把「懂短剧连续性 / 剧集状态机」当成护城河。
- 真正的护城河 = **一个人把「无限画布 + 3D 导演台 + 多模型生成 + 剪辑」四条链路打通并全本地运行**（工程整合能力，不是领域知识）。
- 推论：凡是设计取舍冲突，按「通用创意生产」优先，而不是按「短剧生产链」优先。S0-S5 生产链是**一条**内置范式，不是唯一范式。

## 一、北极星与缺口
- 活路径 =「剪辑精剪 + AI 画布」。设计文档已是**生产链视角**（S0 选题→S1 剧本→S2 分镜美术→S3 生成→S4 剪辑→S5 成片 + G 治理横切，17 章），核心工具 = **阶段契约**（输入/输出/责任人/验收/失败语义，填不满=缺口）。
- 🔴 2026-10-19 重估：**抽卡闭环已落地**（draw_orchestrator 179 + gen_critic 320 + draw_book 321 + score_book 278 + draw_ledger 188）；**编剧生产端非空白**（script_writer 99 + editing_script_generator 396 + storyboard_memory 209，缺长篇体系；drama_understanding_engine 2160 是消费类）。**现行真缺口**（2026-10-23 全库实测复核，四条线并行深挖）：① S2 缺 D2 接线——`asset_master.py` 213 行纯模型已落（D1 ✅ 2026-10-20，master+variant+继承+stale）但生产代码零 import；② G 缺接线+零并发写保护——`aesthetic_gate.py` 176 行（E1 ✅）零生产调用方，全库无 revision/409/ETag/乐观锁（写入口靠 `glue/policies.py:122-146` TIMELINE_WRITE_ENTRYPOINTS 登记册+`check_timeline_write_surface.py` 棘轮收敛；`agent_policy.py:185-189 can_auto_retry` 无运行时调用方，「写不重试」靠机制缺失）；③ S1 长篇（`script_doc.py` 269 行纯模型，缺 UI/存储/分集生成）；④ S3 参数回灌（回流已到提示词层 `guard_pipeline.py:166-185` best_combo 增益/负面词，`draw_book.recommend()` 的 best_seed 无生产消费方）；⑤ S0 立意卡接线（`idea_card.py` 176 行纯模型）。
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
- 🔴 **Qt 6.11 WebEngine 必须给 QApplication 非空 argv**（2026-10-25 实证）：`QApplication([])` ⇒ Chromium `base::CommandLine` 初始化失败 ⇒ 渲染进程 fail-fast `0xC0000409`；`QApplication(["x"])` 正常。画布「永久黑屏 + 点刷新/启动都没用」先查这条（预检脚本、子进程小工具同样中招）。
- 🔴 **画布静态服务有 SPA 兜底，缺文件不返回 404**：`_SPAHandler.do_GET` 把不存在的 path 改写成 `/index.html` ⇒ **200 + HTML**；前端把它当 ESM import 就报 `Unexpected token '<'`。排查插件/资源缺失时别只看状态码，要看 body 是不是 HTML。
- 🔴 **`SkeletonUtils.clone` 后必须先 `updateMatrixWorld(true)` 再测包围盒**：clone 的 matrixWorld 是脏的，`Box3.setFromObject` 会量出 1/33 假尺寸（bodychan 0.0512m vs 真值 1.70m）⇒ 归一化算出 33× 补偿 ⇒ 1.7m 模型放大成 56.5m（「群像第三个角色一只脚占满屏幕」）。
- 🔴 **SkinnedMesh 包围盒必须 precise**：`setFromObject(obj, true)`，普通模式只读 geometry.boundingBox 测不出骨骼异常。
- 🔴 **尺寸自检必须进 `tick()` 渲染循环**（每秒一次）：GLB 异步加载完成时 actors 数组没变 ⇒ 挂 actors effect 里 = 死代码。
- 🔴 **PyQt6 别对 Qt 枚举 `int()`**：抛 TypeError 被 `except: pass` 吞 ⇒ console 镜像零输出（用 `str(level)`）。
- 🔴 **启动必须优先 `.venv312`，不要“有 PyQt6 就用系统 Python”**（2026-10-25 实证）：`C:\Python314` 有 PyQt6 但**无 torch**，本地 SD/Wan 全部 `available:false / 未安装 torch`；`.venv312` 才有 torch 2.6+cu124 + RTX 4060。`启动AI短剧编辑器.bat` 旧逻辑先探系统 Python，正是本地模型“下载了却用不了”的根因。
- **体积守卫余量见底**：`bridge.ts` 2043/2046 禁改；`Stage3D.tsx` 4604/4653；`riggedHumanoid.ts` 3189；`CanvasShell.tsx` 3281 ⇒ **新逻辑另开文件，拆模块不抬基线**。
- **两条单通道（禁造第二套）**：① 3D 产物入轨 = `stage3dArtifacts.ts::sendArtifactToTimeline()` → `POST /ingest_path`；② 角色库→导演台 = store `requestStage3dCast` → `stage3dCastSeq` → `useStage3dCast()`。
- **生成模型选择单一真相源 = `generationModels.ts` store**（2026-10-25）：云端/本地图像/本地视频/对话模型列表与 4 个 selected key 全在此；`App.tsx`、`GeneratePanel.tsx`、`AgentPanel.tsx` 共用。图像生成统一走 `localImage.ts::generateImageUnified`（`local` → `/host/local-image-generate`，其余 → 云端），禁止面板再自拉列表或另存 key。Agent「模型」页现为**唯一可见入口**：本地生图/生视频列表 + `ExecutionBiasChip embedded`（本地/云端算力滑块），固定左下胶囊已移除。
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
- 🔴 **A/B 性能对照必须"逐轮换序"，只做 A/B/A/B 是错的**（2026-10-28 实证）：内核永远排在每组第二位，吃掉上一个 10~15s 负载的降频，恒定偏慢 3~5%（SVD 上量到 1.032/1.042/1.051/1.056×，几乎与步数无关 ⇒ 一眼看出是位置效应不是实现差异）。换序后 0.979/1.014/1.002×。**凡是"新路径总是第二组"的基准都不可信。**
- **内核族的 `caps.verified` 是一份可被机器核对的承诺**：改成 `VERIFIED` 的前提是 `docs/knowledge/kernel_evidence.json` 里有该族 `passed=true`。守卫 ⑱ 第⑤条静态查、`test_kernel_svd.py::test_verified_requires_real_gate_evidence` 运行时查。改回 `UNVERIFIED` 会让内核明确拒绝并回退上游（不是静默降级）。
- **8GB 卡上 SVD 的显存现实**（2026-10-28 实测）：1024×576 × 14 帧顶到 **7.9/8.0GB**（VAE fp32 编码叠加常驻模型），UNet 单步从 4.5s 掉到 20s+；这是 **stock 路径本身**的特性，不是自研内核带来的。等价性验收可在 512×288 上做（判据与尺寸无关），但要在证据里如实记 `size`。
- 🔴 **远程仓库格局（2026-10-24 实测）**：origin = `git@github.com:1949King/wang1.git`（私有）；远程 main 原是单 commit 网页上传快照（575ed7bd，与本地历史不相关）；本地历史含 3 个 >100MB 文件（发布版 zip 743MB / 纵年华 mp4 723MB / avfilter dll 104MB）触发 GitHub 硬限 ⇒ 已 filter-repo 克隆手术剥除（2.88GB→316MB，236 提交完整）后强推成功（远程 main = be198520b）；**本地 main 仍是旧历史未对齐，下次推送前需再手术**；GitHub 副本不含 ffmpeg 二进制/发布包/示例视频。
- 🔴 **`frozen_zones.json` 改 files 禁 `sorted()`** ⇒ 取 HEAD 原顺序 + 尾部追加。
- 🔴 **`frozen_zone_guard.py --update` 必须是最后一次动冻结文件之后** ⇒ 正序：改完全部文件 → `--update` → `git add` → 跑门禁。
- ⚠️ `precommit_gates.sh` 口径不一致：ruff 按**已暂存**筛（未暂存 = 正常空跑），冻结区按**工作区全量**算。
- 🔴 **`git stash push -- <path>` 会把当时暂存区状态一并捎进 stash ⇒ pop 时与期间新提交的文件冲突**（2026-10-25 实证：stash 只含 extensions_module.py，pop 却在 README/version/CHANGELOG/PACK 四处 conflict，因 A/B 提交改过这四文件）。解法 = `git checkout HEAD -- <冲突文件>`（已提交版本即正确版本），勿手解冲突标记；stash 只作分钟级窗口工具，验证恢复后立即 drop。
- 行尾：Edit 保留 CRLF；画布 `src/*.ts(x)`、`现行技术文档.md`、`frozen_zones.json`、`memory/*` = LF；`version.py`、CHANGELOG、`.mdc` = CRLF。
- 提交必须原生 bash（`.sh` + `git commit -F`），**永不裸 commit**；版本号提交前最后一步写，被覆盖换号不抢回。ruff 门禁 = 存量棘轮，用 `C:/Python314/python.exe -m ruff`。回归优先 `.venv312`；失败定性：跑错解释器 → 并发会话 → 才当真回归。Node22 直调真实二进制（`22.22.2-6/node.exe`）。

## 六、画布桥接层与双库
- 新增 `/host/*` 端点必须用 `@_route_get`/`@_route_post` 注册进路由表（写在 return 之后 = 死代码，check_canvas_routes.py AST 检测）。
- 双库同步是人工动作：主库 `vendor/shiguang-canvas/src/` ↔ 副库 `vendor/AI-Canvas-tauri/src/libtv/`；验证 `check_canvas_dual_repo.py`（禁 `--update`）；版本三件套易漏同步副库。
- **副库 tsc 假绿陷阱**：`tsconfig.json` 是 project references（files: []）恒报 0 错 ⇒ 用 `tsc -p tsconfig.app.json --noEmit`。副库 vitest v4 不接受 `--reporter=basic`。
- 画布测试：不能引用包外相对路径（`?raw` 会解析到 vendor/app/）；vitest 是 node 环境无 jsdom ⇒ useEffect 逻辑零覆盖，须抽纯函数；`include` 只收 `*.test.ts`。
- Agent 触达前端唯一通道 = `make_agent_event()` + `broadcast_agent_event()`（SSE），前端 `subscribeAgentEvents` 消费。

## 七、Agent 编排原语：工作流蓝图（2026-10-31，画布 0.3.34，提交 d948138）
- 🔴 **画布 Agent 的编排原语 = 蓝图（blueprint）**，不是一条条 addNode：
  `app/core/canvas_blueprint.py`（后端：归一化+校验+标准流程补全+LLM 输出规范）
  ↔ 前端 `blueprintLayout.ts`（分层拓扑布局）+ `applyBlueprint.ts`（一次落图）
  ↔ `AgentPanel.tsx` 的 `case "applyBlueprint"`。action 已入 `agent_action_registry`。
- **蓝图 schema 里没有 x/y**（AiDiagram 语义放置模式）⇒ 坐标一律本地算；布局引擎零新依赖
  （本仓 dagre/elkjs/d3-force 零命中）。落图只走 store 已公开三件套
  `addNode/updateNodeData/onConnect` ⇒ **不造第二条链路**，`store.ts` 冻结区零改动。
- 🔴 **标准链必须过端口类型校验**：`shotlist` 只吃 `video`/`grid`，**不吃 `image`**
  ⇒ 「镜头→分镜表」类型上是断的。**终点不同 ⇒ 路径不同**（`CANONICAL_PATHS` 7 条）：
  「到分镜表」走宫格路径（不塞视频生成），「到成片」走全生产链。
- 🔴 **冻结区 `canvas-magnetic-intent` 含 `canvasVersion.ts` + `NodePalette.tsx`**
  ⇒ 改画布版本号（该区不变量明确许可的「三件套」）或调色板后**必须 `--update` 重新上锁**。
- 🔴 **沙箱 `safe-bin` 的 pnpm 垫片用 SQLite 记账，DB 打不开 ⇒ `[ERROR] unable to open
  database file`** ⇒ `check_canvas_dual_repo.py` 构建门禁**必红（环境层，非代码）**；
  用真 pnpm 直跑（`cmd //c "pnpm --filter … exec vite build --outDir dist.check"`，
  且**先 `mv` 走旧 dist.check**，否则 safe-delete 垫片拦删除）可验真构建。
- **主程序 `app/version.py` 与画布版本刻意不同步**；主版本线被并行线占用时**不抢号**。

## 八、Agent「模型不吐指令」的根因与兜底（2026-10-31）
- 🔴 **提示词必须和真实审批机制对齐**。协作模式段原写「改画布前先给计划，**等用户确认**」，
  但审批实际在**策略引擎 + 前端确认框**（`agent_policy.decide()` → `require_approval`
  → `AgentPanel.tsx` 的 `askConfirm`，前端消费后端下发的策略表）
  ⇒ 模型在文字里等确认 = **多余**，且直接导致「只吐计划不吐 JSON ⇒ 画布空的」。
  修法：协作段改成「确认由系统弹框，**不要在文字里停下来等用户点头**，说明与指令同批输出」。
- 🔴 **赌模型会听话 = 赌**。后端必须有兜底层：`canvas_blueprint.ensure_workflow_blueprint()`
  —— 模型已给蓝图就保留（模型提示词更好）；只给零散 `addNode` 就**丢掉零散动作**换整张链
  （零散动作正是「杂乱」的来源）；只给文字计划（`tools=[]`）就按标准路径**合成整张链**。
  触发条件保守：命中「完整流程」信号 **或** 需求里点了 ≥2 个不同环节；单步需求**绝不铺**；
  Plan 模式（只读）不合成。
- 🔴 **system 提示段序 = 注意力预算**：角色 → 模式 → **契约（蓝图段）** → 动作清单（附录）。
  18 个 action 的长清单必须排最后，否则「注意力稀释」；且契约里要有「信息不全也要先铺全」
  的硬规则，否则模型会反问要素材、只给计划。
- **真机验证方法**（别只做模拟输出）：用 `app.core.project_agent_host._build_canvas_fast_messages()`
  构造与真实链路同源的提示 → POST 本机 Ollama `/api/chat` → `parse_canvas_tools`
  → `normalize_canvas_tools` → `ensure_workflow_blueprint`。本机 `qwen3.5:4b` 可用。
- 🔴 **后端补的环节也要带真提示词**：模型只给 1 张卡时，补出来的 6 张才是用户看得见的部分
  ⇒ 「补齐环节」与「合成整张图」**共用同一套提示词骨架**（`canvas_blueprint._STAGE_PROMPT_TEMPLATES`
  / `_synth_node_prompt`，一个出口不分叉）；提示词要带得上需求里的时长 / 风格
  （风格词**只在需求里确实出现时**才引用，不猜）。
- 🔴 **别让「正常操作」混进 `problems`**：`problems` 只放真问题；「按标准流程补齐 N 个环节」
  塞进去会被 `describe_report` 重复算成「校验提示」⇒ 走 `inserted` 字段。
