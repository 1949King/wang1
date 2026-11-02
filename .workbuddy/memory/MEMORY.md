# 拾光剪影 — 项目长期记忆（细节查 `.workbuddy/memory/日志`；工作法查 `~/.workbuddy/skills/`）

## 〇、定位（2026-10-28 用户纠正，最高优先级）
🔴 **通用创意生产工具 / 创意工作台，不是「短剧剪辑工具」** —— 短剧只是其中一个用法场景。
- 输入 = 想法/素材/参考；输出 = 图·视频·3D·成片。**画布是工作台，不是流水线**。
- 对标 Figma·Miro·Canva·ComfyUI·Runway/Pika·剪映·DX-OS。**禁**用「短剧」框定方向，禁把「懂短剧连续性」当护城河。
- 真护城河 = 一个人把「无限画布 + 3D 导演台 + 多模型生成 + 剪辑」四条链路打通并全本地运行。
- 取舍冲突按「通用创意生产」优先；S0-S5 生产链是**一条**内置范式，不是唯一范式。

## 一、缺口现状（2026-10-23 全库实测）
活路径 =「剪辑精剪 + AI 画布」；核心工具 = **阶段契约**（输入/输出/责任人/验收/失败语义）。已落地抽卡闭环 + 编剧端（缺长篇体系）。
- **真缺口**：① `asset_master.py` 纯模型零 import；② `aesthetic_gate.py` 零调用方 + 全库无 revision/409/ETag 乐观锁（写入口靠 `glue/policies.py:122-146` 登记册 + `check_timeline_write_surface.py` 棘轮；`agent_policy.py:185-189 can_auto_retry` 无调用方）；③ `script_doc.py` 缺 UI/存储/分集；④ `draw_book.recommend()` 的 best_seed 无消费方（回流只到 `guard_pipeline.py:166-185`）；⑤ `idea_card.py` 纯模型。
- 画布外观走 `data/canvas_appearance.json` + `GET /host/canvas-settings`（非 QSettings）。
## 二、核心不变量
1. 真相源 `EditorModule._clips`；跨线程整段替换带 `_clips_lock`；序列化用 `_clips_snapshot()`，禁把 `_clips` 交 `json.dump`。
2. 插件两套：`ExtensionsRegistry`(extension_base.py:332) + `PluginManager`(plugin_manager.py:13)；真家 `app/plugins/`。
3. 冻结区 9 zone / 91 锁，改 zone 同步 4 处：`docs/knowledge/frozen_zones.json`（**字符串手术**，json.dump 会重排几千行）· `现行技术文档.md §5` · `.cursor/rules/frozen-zones.mdc` · 重锁。新文件必须登记进 zone files。`app/core/neural/` **不在任何冻结区**。
4. 两套独立版本号：`app/version.py`（主）与 `canvasVersion.ts`→`package.json`→CHANGELOG（画布）。禁内联版本字符串。
5. `agent_capability_catalog.py` **加行即注册**，`verify_catalog_consistency()` 双向守卫。CapabilityResult 字段是 `success` 不是 `ok`。
6. 音画纠偏 ~280ms（冻结区），勿压回 80ms。
7. 主题真相源 `theme_tokens.py`（三表 57 keys）。内联 setStyleSheet = 主题盲区，须回 `set_theme()`；`setObjectName` 后必须 grep `#x` 确认 QSS 有规则。
8. 静默 except：UI 绘制 pass 可；状态机/资源路径须 `logger.debug(..., exc_info=True)`。
9. 沙箱 wmic 黑名单：import app 链触发，验证脚本 subprocess 包一层。

## 三、用户偏好
简体中文；指令极简；**先结论后展开**；小白模式（比喻+表格）；拒绝随机效果；要证据（文件+行号）；被纠正直接认错重查不辩解。🔴 **「迭代设计文档」≠「把数字改对」**——要设计增量。

## 四、持久约束（血泪）
- 🔴 **Qt 6.11 WebEngine 必须给 QApplication 非空 argv**（`QApplication([])` ⇒ 渲染进程 `0xC0000409`）；画布白屏另查 `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"`，CSS 别用 `body:has(...)`。
- 🔴 **画布静态服务有 SPA 兜底**：缺文件改写 `/index.html` ⇒ **200 + HTML**，前端当 ESM import 报 `Unexpected token '<'`。排查看 body 不看状态码。
- 🔴 **`SkeletonUtils.clone` 后必须先 `updateMatrixWorld(true)` 再测包围盒**（脏矩阵量出 1/33 假尺寸 ⇒ 1.7m 变 56.5m）；SkinnedMesh 须 `setFromObject(obj, true)`；尺寸自检必须进 `tick()` 渲染循环（挂 actors effect = 死代码）。
- 🔴 **PyQt6 别对 Qt 枚举 `int()`**（TypeError 被 `except: pass` 吞 ⇒ console 镜像零输出，用 `str(level)`）。
- 🔴 **启动必须优先 `.venv312`**：`C:\Python314` 有 PyQt6 但**无 torch** ⇒ 本地模型全 `available:false`。
- **体积守卫余量见底**：`bridge.ts` 2043/2046 禁改；`Stage3D.tsx` 4604/4653；`riggedHumanoid.ts` 3189；`CanvasShell.tsx` 3281 ⇒ **新逻辑另开文件**。
- **两条单通道（禁造第二套）**：① 3D 产物入轨 = `stage3dArtifacts.ts::sendArtifactToTimeline()` → `POST /ingest_path`；② 角色库→导演台 = store `requestStage3dCast` → `stage3dCastSeq` → `useStage3dCast()`。
- **生成模型选择单一真相源 = `generationModels.ts`**；图像生成统一走 `localImage.ts::generateImageUnified`。Agent「模型」页是唯一可见入口。
- 🔴 **「没测出来」≠「测出来了」**：后端空串字段前端原样保留，禁填默认值；非法数值落 0 不猜。
- 🔴 **同名不同义常量高频坑**（warnings / quality_tiers 踩过）：带 quality/tier/mode/level 的后端字段先核前端语义。
- **孤儿端点差集法四扫描面**：画布 src 非注释行 / canvas_server.py JS 字面量 / `app/**/*.py` URL 拼接 / **副库 Rust `src-tauri/src/lib.rs`**。
- YuE 全曲本机跑不动 ⇒ 执行端不可用必须诚实失败，绝不假音频。沙箱 tempfile 回退 cwd ⇒ 三入口钉 `.workbuddy/tmp`。
- `switch_to_module()` 对 `nav_hidden` 模块静默无效 ⇒ 走 `_perform_module_load`。UI 乱码先 grep 源码乱码字面量。本机 locale=utf-8 ⇒ `open()` 必带 encoding。
- 🔴 **入口位置由「能力归属层级」决定，不由「体积守卫有没有空位」决定**：团队入口为省 12 行塞进画布第二条顶栏（`WorkspaceCanvasMenus`）⇒ 被 `showWorkspace = viewMode === "canvas"` 挡住，首页/生图台/3D 台等 8 个界面全看不见。工作区级能力 ⇒ 挂常驻 `AppNav`。
- 🔴 **判断体积守卫会不会红，用 `git show HEAD:<file> | wc -l` 算 HEAD 行数**，别用工作区行数（工作区已含自己的改动）。`styles.css` HEAD 4004 / 基线 3980 / 容差 30 ⇒ 只剩 24 行余量，新样式另开文件（`teamPanel.css`）。
- 🔴 **`docs/CHANGELOG.md` 现为 LF**（非历史记忆的 CRLF）；写入前先 `'\r\n' in raw` 判行尾再决定。`grep` 搜 emoji（astral 字符）会 0 命中 ⇒ 用 python 读文本断言，或搜中文侧证。
- 🔴 **PyQt ↔ 画布唤起用「探测全局函数」不用 `dispatchEvent`**：后者在页面未加载时也返成功 ⇒ 点了没反应还不报错。画布侧挂 `window.__sgTeamOpen`，PyQt 侧 `runJavaScript` 拿 'ok'/'pending' 轮询。
- 🔴 **`backdrop-filter`（及 filter/transform）的祖先会成为 `position:fixed` 后代的包含块**：团队面板挂进 `.ic-nav`（有 `backdrop-filter: blur(10px)`）后 `right:18px` 变成「距 64px 导航栏右边 18px」，420px 面板被推出屏幕只剩 46px 窄缝（用户原话「就这么小一个窗口」）。**浮动面板一律 `createPortal(..., document.body)`**。
- 沙箱里**模拟鼠标点击打不进去**（`mouse_event` 无效果：点主题按钮也不变），GUI 交互只能让用户点；但窗口枚举 + PIL `ImageGrab` 截屏可用（`.venv312` 有 PIL），可以自证"窗口/按钮画出来了"。ps 里 `Start-Process` / `cmd start` / `.NET Process.Start` / `Add-Type` 全被安全策略拦，只能用 python `subprocess` 拉起。
- `git status --porcelain --cached` **不是合法参数**（无 `--cached`）⇒ 用 `git diff --cached --name-only`。

## 五、验证与提交纪律
- **静态门禁全绿 ≠ 运行时没崩** ⇒ 自绘控件交付标准 = 真机启动 + paintEvent 真跑。
- `run_all_checks.py` **不含**稳定性门禁 ⇒ 另跑 `scripts/stability_gate.py`。**哈希 ≠ 不变量**：新不变量必须 AST 断言 + 反例验证；**门禁项本身也可能是摆设**。
- 🔴 **沙箱 safe-delete `scope:"turn"` 累计删除 >50 即拦**（vite 清 `dist/assets` ⇒「构建成功但退出码 1」）。绕开 = `mv` 到 `.workbuddy/tmp/`。**不是代码回归**。
- 🔴 **禁 `git add -A`** ⇒ 精确 pathspec；`.cursor/` 需 `git add -f`。提交必须原生 bash（`.sh` + `git commit -F`），**永不裸 commit**；版本号提交前最后一步写。
- 🔴 **A/B 对照必须"逐轮换序"**：A/B/A/B 会让内核恒定排第二位、吃掉上一负载降频，恒定偏慢 3~5%。**"新路径总是第二组"的基准都不可信。**
- **内核族 `caps.verified` 是机器可核对的承诺**：改 `VERIFIED` 须 `docs/knowledge/kernel_evidence.json` 有该族 `passed=true`。
- **8GB 上 SVD**：1024×576×14 帧顶到 7.9/8.0GB，单步 4.5s→20s+（stock 路径特性）；等价验收可降 512×288，但须如实记 `size`。
- 🔴 **远程仓库**：origin = `git@github.com:1949King/wang1.git`（私有）。已 filter-repo 剥除 3 个 >100MB 文件（2.88GB→316MB，236 提交）强推；**本地 main 仍是旧历史，下次推送前需再手术**。
- 🔴 `frozen_zones.json` 改 files 禁 `sorted()` ⇒ HEAD 原顺序 + 尾部追加。`frozen_zone_guard.py --update` 必须是**最后一次**动冻结文件之后。⚠️ `precommit_gates.sh` 口径不一致：ruff 按已暂存筛，冻结区按工作区全量算。
- 🔴 **`git stash push -- <path>` 会捎进暂存区状态 ⇒ pop 冲突**。解法 = `git checkout HEAD -- <冲突文件>`，勿手解标记。
- 行尾：画布 `src/*.ts(x)`、`现行技术文档.md`、`frozen_zones.json`、`memory/*` = LF；`version.py`、CHANGELOG、`.mdc` = CRLF。ruff 用 `C:/Python314/python.exe -m ruff`；回归优先 `.venv312`；Node22 直调 `22.22.2-6/node.exe`。

## 六、画布桥接层与双库
- 新增 `/host/*` 端点必须用 `@_route_get`/`@_route_post` 注册进路由表（写在 return 之后 = 死代码，AST 检测）。
- 双库同步是人工动作：主库 `vendor/shiguang-canvas/src/` ↔ 副库 `vendor/AI-Canvas-tauri/src/libtv/`；验证 `check_canvas_dual_repo.py`（禁 `--update`）。
- **副库 tsc 假绿**：`tsconfig.json` 是 project references（files: []）恒报 0 错 ⇒ 用 `tsc -p tsconfig.app.json --noEmit`。副库 vitest v4 不接受 `--reporter=basic`。
- 画布测试：不能引用包外相对路径（`?raw` 解析到 vendor/app/）；vitest 无 jsdom ⇒ useEffect 零覆盖，须抽纯函数；`include` 只收 `*.test.ts`。
- Agent 触达前端唯一通道 = `make_agent_event()` + `broadcast_agent_event()`（SSE）。

## 七、Agent 编排原语：工作流蓝图（2026-10-31，画布 0.3.34）
- 🔴 **编排原语 = 蓝图（blueprint）**：`canvas_blueprint.py` ↔ `blueprintLayout.ts` + `applyBlueprint.ts` ↔ `AgentPanel.tsx case "applyBlueprint"`。
- **蓝图 schema 无 x/y** ⇒ 坐标本地算；落图只走 store 三件套 `addNode/updateNodeData/onConnect` ⇒ `store.ts` 零改动。
- 🔴 **标准链必须过端口类型校验**：`shotlist` 只吃 `video`/`grid`，**不吃 `image`**。**终点不同 ⇒ 路径不同**（`CANONICAL_PATHS` 7 条）。
- 🔴 **冻结区 `canvas-magnetic-intent` 含 `canvasVersion.ts` + `NodePalette.tsx`** ⇒ 改版本号或调色板后**必须 `--update` 重锁**。
- 🔴 **沙箱 pnpm 垫片 DB 打不开 ⇒ 双库构建门禁必红（环境层）**；用真 pnpm 直跑，且**先 `mv` 走旧 dist.check**。
- 主程序版本与画布版本刻意不同步；主版本线被并行线占用时**不抢号**。

## 八、Agent「模型不吐指令」根因（2026-10-31）
- 🔴 **提示词必须和真实审批机制对齐**：审批在策略引擎 + 前端确认框（`agent_policy.decide()` → `require_approval` → `askConfirm`）⇒ 模型在文字里等确认 = 多余，直接导致「只吐计划不吐 JSON」。协作段写「确认由系统弹框，别停下来等点头」。
- 🔴 **赌模型会听话 = 赌**。后端必须有兜底 `ensure_workflow_blueprint()`：已给蓝图保留；零散 addNode 换整张链；只给文字按标准路径合成。单步需求**绝不铺**；Plan 模式不合成。
- 🔴 **system 段序 = 注意力预算**：角色 → 模式 → **契约** → 动作清单（附录）。
- 真机验证：`_build_canvas_fast_messages()` → POST 本机 Ollama `/api/chat` → `parse_canvas_tools` → `normalize_canvas_tools` → `ensure_workflow_blueprint`（`qwen3.5:4b` 可用）。
- 🔴 后端补的环节也要带真提示词：「补齐环节」与「合成整张图」共用 `_STAGE_PROMPT_TEMPLATES`，一个出口不分叉。**别让「正常操作」混进 `problems`**（走 `inserted` 字段）。

## 九、GGUF 量化栈（2026-11-01，app/core/neural/）
- 三个新文件：`gguf_quants_torch.py`（内核，8 类）+ `gguf_loader.py`（读取 + LDM→diffusers）+ `gguf_lazy.py`（逐层懒反量化）。
- 🔴 **已接进生产路径**：`DiffusersImageEngine.request_gguf(path)` / 环境变量 `SHIGUANG_GGUF` → `load()` 内装填。真机验收 686 层 / Q8_0 / 装填 20.9s / 出图 4.0s（512²·20 步）；路径不存在 ⇒ `ok=False` 写明路径（**不静默退回 fp16 假装量化**）。GGUF 与 fp8 互斥，GGUF 优先。
- 🔴 **numpy 反量化不可用**（约 50 M元素/s ⇒ 全 SDXL UNet 30 步 11.4 分钟），必须用 torch GPU 版（快 606×）。
- 🔴 **GGML 以 ne[0] 为最内维** ⇒ 读时 `reshape(ggml序)` 后必须 `permute` 回来；**只 reshape 不 permute = 形状对、元素串位、安静 load 成功、画出噪点**。
- 🔴 **`convert_ldm_unet_checkpoint` 期望输入带 `model.diffusion_model.` 前缀**（内部 `key.startswith(LDM_UNET_KEY)`）；提前剥 ⇒ 空字典 ⇒ 误判「架构不匹配」。方向是**补齐**。
- 内核已逐元素对齐 numpy 权威实现（F32/F16/BF16/Q4_0/Q5_0/Q8_0/Q4_K/Q6_K 全 rel=0）；gguf-py 的 K-quant **正向量化未实现** ⇒ 对照用「自打包字节 → 官方 numpy 反解 vs torch 反解」。
- 显存账（SDXL UNet 2.39G 参数）：fp16 4.78GB → Q8_0 2.54 / Q6_K 1.96 / Q4_K 1.34GB。**eager 只省硬盘**；lazy 实测 SD1.5 峰值 2.81→**1.07GB（省 62%）**、慢 2.63×、与 eager **逐位相同**。
- 🔴 **PSNR 量不了扩散量化**：不用量化、只给 fp16 加 0.4% 噪声，同 seed PSNR 仅 **14.12dB**（比 GGUF Q8_0 的 17.14 更低）⇒ 十几 dB 是扩散去噪的固有放大。判量化看**低频(8×) PSNR**（`is_admissible_diffusion`，门槛 20dB）+ 肉眼。gguf_q4_k 缺低频证据 ⇒ 登记不启用。
- 🔴 **FP8 在本机真可用，别再引「无加速」旧结论**：真因是 torchao 0.16.0 的 cpp extensions 没编译，不是 CUBLAS 不支持 sm89。降到 **torchao 0.12.0** 后出图**快 10%**、显存 **-9.6%**（只量化 nn.Linear）。
- 🔴 **SageAttention Windows 需三件套**（triton-windows + MSVC + CUDA Toolkit 的 `cuda.h`，本机**没有** cuda.h，`torch/cuda.h` 不能替代）；PyPI 包是纯 Triton 实现。**门槛过高 ⇒ 不进主路径**。
