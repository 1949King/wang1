# 拾光剪影 — 变更日志

## V4.40.5 (2026-09-27) — A4 路由巨石拆分完成（批次 2/3：POST 全迁）

> 评价报告架构债 #2「`do_POST` 1,048 行 / ~45 端点串一条 if 链」**拆解完成**。

### 批次 2/3 · POST 29 端点全迁

新增 `app/core/canvas_routes_post.py`（`CanvasPostRoutesMixin`，1,183 行）承接：
`/host/tauri-closing` · `agent/{session,reply,start,chat}` · `compliance-check` ·
`video-generate` · `budget/set` · `/ingest` · `/ingest_path` · `/push_from_editor` ·
`generate-image|video|audio|music` · `comfyui/run` · `pose-extract` ·
`pose-video-encode` · `inpaint` · `video-batch` · `interpolate` · `video-concat` ·
`batch-to-timeline` · `project-agent/chat` · `upload-asset` · `tools/run` ·
`storyboard-breakdown` · `storyboard-camera-plan` · `canvas-ai-review`

| 指标 | 原始 | 现在 |
|---|---|---|
| `canvas_server.py` | 3,273 行 | **1,740 行（−47%）** |
| `do_GET` / `do_POST` | 678 / 1,048 行 if 链 | 各约 10 行薄分发 |
| 老 if 链残留 | 61 个端点 | **1 条（404 兜底）** |
| 路由表 | GET 4 / POST 10 | **GET 30 / POST 39** |

**搬移手法**：AST 辅助脚本自动完成 —— 提取块（含块首注释）、缩进 −4、
给模块级符号的裸引用加 `cs.` 前缀、注入 `cs = _cs()`。1,040 行机械搬移零手抄。

### ⚠️ 踩坑与加固（本版最重要的产出）

**批次 1 埋的雷**：A4 把端点迁走后，`ruff --fix` 把「canvas_server 不再直接
使用、但被 mixin 经 `cs.xxx` 引用」的 import **当死代码删除**，导致 4 个符号
失效：

| 被删符号 | 受影响端点 |
|---|---|
| `_load_canvas_plugins_manifest` | `/host/plugins` |
| `build_character_prompt` | `/host/characters` |
| `list_editor_outbox` | `/editor_outbox` |
| `build_host_ai_config_patch` | 5 个 `*-models` 端点（**当时无测试覆盖**） |

**处置（三道防线）**：
1. 两处 import 块加**语句级 `noqa: F401`** + 详细说明（为什么不能删）。
2. 新增常驻守卫 **`_verify/check_canvas_route_attrs.py`** —— 纯静态，校验
   mixin 里每个 `cs.xxx` 都能在 canvas_server 顶层绑定中找到，找不到即失败并
   给出修法。已注册 `run_all_checks`（ROUTEATTR）并进 hook **第⑨道**（卡点 8 → 9）。
3. 顺手修 mixin 的 `Any` 缺失（4 处 F821）与冗余 import；
   另修一处误删：`threading` 被 F401 误判（实际在 `CanvasBridgeServer` 用），已恢复。

### 验证

e2e 真起服务**全过** · 路由契约 65 条不重叠（老链仅 404）· 全量 **383/383** ·
ruff 全净 · 冻结区 85 锁 · 稳定性 249 ≤ 269 · 粘合层 18/0 · 架构 0 警告 ·
双库无漂移 · 文件规模守卫通过。

> 至此 A4 收尾：**路由巨石消失**，加端点不再改千行方法。
> 报告架构债 #2 清除；剩余债 #1（`EditorModule` 上帝类）、#3（双库）。

## V4.40.4 (2026-09-27) — A4 路由巨石拆分（批次 0+1：GET 全迁）

> 评价报告架构债 #2「`do_POST` 1,048 行 / ~45 端点串一条 if 链」的拆解起点。
> 分 4 批做，本轮完成**批次 0（基建）+ 批次 1（GET 全迁）**。

### 批次 0 · 路由表下沉（解循环导入）

- 新增 `app/core/canvas_route_registry.py`：路由表（`_ROUTES_GET/_ROUTES_POST`）
  + `@_route_get/@_route_post` + `dispatch_table`。
- **为什么必须下沉**：端点按域拆到 mixin 模块后，mixin 需要装饰器；若从
  `canvas_server` 导入即形成「canvas_server → mixin → canvas_server」循环。
  两边都从 registry 取即解。
- `canvas_server._dispatch_table` 变薄转发（行为不变）。

### 批次 1 · GET 全迁（25 个端点 / 约 520 行）

新增 `app/core/canvas_routes_get.py`（`CanvasGetRoutesMixin`，650 行）承接：
`/host/budget` · `calls` · `compliance-check` · `characters` · `prefs` ·
`prompt-fetch` · `prompt-bundled` · `prompt-image` · `providers` ·
`ai-config-patch` · `comfyui/status` · `image|video|audio|music|chat-models` ·
`tools` · `agent/session` · `agent/tasks` · `agent` · `editor_outbox` ·
`timeline-snapshot` · `plugins` · `video-batch` · `video-postprocess` ·

| 指标 | 前 | 后 |
|---|---|---|
| `canvas_server.py` | 3,314 行 | **2,757 行（−557）** |
| `do_GET` | 678 行 if 链 | 约 150 行（薄分发 + 5 个兜底块） |
| 路由表注册 | GET 4 / POST 10 | **GET 30 / POST 10** |
| 单文件规模基线 | 3,273（且实际 +41 越界） | **2,757（同步下调）** |

**行为等价优先**：每个 handler 与迁出前逐行等价；401 响应体的差异
（`chat-models` 带 `providers: []`、`tools` 带 `tools: []`）原样保留，不统一。
依赖的模块级符号经函数内 `_cs()` 取 `canvas_server` 模块访问（同一对象）。

**未迁出**（有意保留在 `do_GET`）：`/` 与 `/health`、`/inject.js`、
`/host/agent/events`（SSE 长连接，结构特殊）、`/editor_file/*` 与
`/inbox_file/*`（前缀路由，路由表是精确匹配）、404 兜底。

### 契约守卫同步升级（`check_canvas_routes.py`）

迁出端点会让守卫**失真**，两处必须同步改，否则等于给契约检查开天窗：

1. **服务端路由来源从单文件改为 `SERVER_FILES` 多文件** —— 否则迁出的
   端点从「服务端路由」集合里消失，前端调用它反而被判「静默 404」
   （实测误报 16 个）。修后服务端精确路由 41 → **63**。
2. **「路由表 vs 老链重复注册」检测按 HTTP 方法分离** —— `do_GET`/`do_POST`
   同名端点（如 `/host/video-batch` 的查询与启动）是正常设计，整文件扫描
   会误判（实测误报 3 个）。新增 `method_bodies()` 用 AST 切分方法体。

### 门禁补漏（hook 第⑧道）

**单文件规模守卫此前不在 pre-commit 里** —— 导致「写代码把文件撑过 2000 行」
无人拦（`canvas_server.py` 因负缓存 +41 行越界即是一例，直到本次才被发现）。
现加入第⑧道，**卡点 7 → 8 道**。

### 顺带

- `bridge.ts`（2,016 行，V4.39.8 异步接线后越线 2000）作为**存量冻结**入
  规模基线，标注 `⚠️ 待拆分`（异步编排宜独立成模块），未在本轮动它
  （画布真源改动需同步副库，另立任务更稳）。

### 验证

端到端 `check_canvas_bridge_e2e.py`（**真起服务打端点**，含 401 鉴权、
快照端点、诚实语义）**全过** · 路由契约 OK · 全量 **383/383** · ruff 全净 ·
冻结区 85 锁 · 稳定性 249 ≤ 269 · 粘合层 18/0 · 架构守护 0 警告 · 双库无漂移。

> 剩余：**批次 2/3**（`do_POST` 29 个端点 / 约 1,046 行，按域分两批迁）。

## V4.40.3 (2026-09-27) — 整改 P2 起步：文档数字回正 + CI 全量 + scrub 压测

> 按「未修清单」推进其中**无冻结区、零/低风险**的三项（A1-A3）。

### A1 文档数字回正（评价报告点名「单一事实源自身三处失准」）

| 位置 | 旧 | 新（2026-09-27 实测） |
|---|---|---|
| §10 `editor_module.py` | 8,553 行 | **9,718 行**（并补 371 个函数） |
| §10 `except: pass` | 173 处 | **38 处 / 8 文件**（ok 25 · ui 1 · needs_log 3 · frozen 9） |
| §10 画布 tsc 存量 | 40 处（37 冻结 + bridge 3） | **37 处全部在冻结区**（bridge.ts 3 处已于 V4.39.8 修完） |
| §2f 画布真源 | 106 文件 / 43,210 行 | 106 文件 / **43,603 行** |
| §2f 副库副本 | 99 文件 / 42,533 行 | 100 文件 / **42,954 行** |

§10 优先级段落同步现状（「立刻做」两条均已落地）。

### A2 CI 改造为真回归

现状问题（报告 §7.2 第 5 条）：单测只跑一个文件、另一 step 跑 `app/temp/` 草稿、
两处 `continue-on-error`、触发路径不含 `tests/**` 与 `vendor/**`。

改造后 5 个 job：

| job | 内容 | 拦截 |
|---|---|---|
| unit-tests | **全量** `app/tests` + `tests/test_pipeline_optimizations.py`（383 项） | ✅ 真拦截 |
| guards（新） | 冻结区 / 稳定性棘轮 / 粘合层契约 / 架构守护 / 双库一致性 | ✅ 真拦截 |
| frontend-tests（新） | `npm ci` + vitest（画布真源 81 项） | ✅ 真拦截 |
| integration-tests | Qt offscreen + 主程序启动导入验证 | ✅ 真拦截 |
| build-smoke | PyInstaller 打包验证 | ⚠️ 仅此保留宽容（注释说明） |

- **关键修正**：必须在仓库根跑 pytest —— `app/` 下没有 `conftest.py`，
  原来的 `cd app && pytest` 在跑全量时会因导入失败**假红**。
- 触发路径补 `tests/**` · `vendor/**` · `_verify/**` · `scripts/**`。
- 新增守卫/前端两个 job 均 `needs: unit-tests`，单测不过不必跑后续。

### A3 长对白 scrub 压测（报告 §6.1 第 3 条 + §10「立刻做」）

新增 `_verify/check_scrub_perf.py`，并注册进 `run_all_checks`（SCRUBPERF）。

- **做法**：不 `import app.*`（会拉起 config_manager 的 wmic 探测，撞沙箱黑名单），
  改用 **AST 从 `editor_module.py` 提取 `_clips_at_playhead` / `_clip_at_playhead`
  真实函数体**编译执行——测的是真代码，源码改动即反映（函数指纹 sha 会打印）。
- **覆盖**：scrub 每帧必经的纯计算路径（命中查找 + video/audio 选层）。
  构造「长对白」时间线（对白段 + 音频轨 + 字幕轨），拖动序列 70% 连续小步
  + 30% 跳跃，3000 次采样。
- **实测结果**：

| 对白段数 | 总片段 | p50 | p99 | 均值 | 超 33ms 预算 |
|---|---|---|---|---|---|
| 150 | 450 | 0.094 | 0.123 | 0.094 ms | 0/3000 |
| 300 | 900 | 0.188 | 0.326 | 0.196 ms | 0/3000 |
| 600 | 1800 | 0.376 | 0.642 | 0.389 ms | 0/3000 |

- **结论（重要）**：成本随段数**精确线性**（现值确为 O(n) 全表扫描 + sort），
  但 600 段仅占 30fps 帧预算的 **1.2%** ⇒ **查找层不是长对白掉帧源**；
  瓶颈若存在必在解码/合成层（`_render_timeline_frame` → PreviewManager），
  脚本已如实标注该未覆盖面，不假装测过。
- 退出码语义：均值超 `--budget-ms`（默认 33）即 1，可入 CI。

### 测试与门禁

全量 **383/383**；ruff 全净；冻结区 85 锁完好；稳定性 249 ≤ 269；双库无漂移。

## V4.40.2 (2026-09-26) — 整改 P1③：needs_log 静默异常补日志

> 实测整改方案 P1 第三项（收官）。`check_glue_contract` 判定的 needs_log
> 静默 except **25 处全部处置**：22 处补日志，3 处在冻结区转入待解冻队列。
> 至此整改 P1 全部落地（①②=V4.40.1，③=本版）。

### 22 处补 `logger.debug(..., exc_info=True)`（14 文件）

| 文件 | 处 | 语义 |
|---|---|---|
| `llm_editor.py` | 3 | LLM 响应三级降级解析（直接→代码块→数组），排查 LLM 问题的关键线索 |
| `editor_preview_ux.py` | 3 | resolve_abs 展开失败回退、cache_dir 绝对化失败 |
| `prompt_library_store.py` | 3 | 提示词缓存读损坏走远端、写失败、降级缓存也不可用 |
| `editor_timeline_tools.py` | 2 | clip speed 非数值按 1.0、清样式 UI 容错 |
| `i18n.py` / `copywriting_module.py` / `deformity_repair_skill.py` / `editor_ai_process_mixin.py` / `editor_ai_tools_mixin.py` / `editor_export.py` / `model_config.py` / `performance_module.py` / `video_processor.py` | 各 1 | 占位符替换失败 / Provider 配置读取 / LLM JSON 提取 / busy 框关闭 / 历史插入 / 导出代理路径检查 / 激活配置读取 / 渲染统计刷新 / 烘焙临时文件清理 |
| `test_render_fallback.py` | 2 | 源码收集 OSError 跳过（C 扩展不可得） |

- 5 文件补 `logger = logging.getLogger(__name__)` 定义。
- **冻结区 3 处转入待解冻队列**：`canvas_bridge.py` L144、
  `character_management_module.py` L793/847（stage3d-core 整文件锁）。

### 纪律事件（如实记录）

P1-③ 中途误改 `character_management_module.py`（stage3d-core 整文件锁，
files 清单成员），冻结区守卫报 `FROZEN ZONE DRIFT` 后**立即全量回滚**，
守卫恢复 85 锁完好。教训：needs_log 清单动手前应先逐文件核对冻结区
files 清单（canvas_bridge 拦下了，漏了同区的 character_management）。

### 增量门禁拦下即清：15 文件存量 ruff 120 处全清

- **F401 死 import ×96**：限定规则安全 `--fix`（F401/F541/B009/RUF100），
  全量测试验证零破坏（import 级错误会立刻炸）。
- **F811 函数内冗余 re-import ×8**（copywriting_module）：顶部已有
  QFileDialog/QMessageBox/QApplication/os/json，函数内重复——手动删除
  （不跑 --fix，防误删 BYOX 类覆盖地雷）。
- **F841 死变量 ×7**：逐个定性——有副作用的保留调用去赋值
  （`smgr.add_subtitle`、`subprocess.run`、`SceneChangeDetector()` 可用性
  实例化），纯死的删行（`clip_id`、`content_summary`、`cpu_indicators`）。
- PIE810 startswith 合并元组 ×2、B905 zip 补 `strict=False` ×2。
- `canvas_runtime` 可用性探测 import 加 `# noqa: F401` 保留
  （改 `find_spec` 会跳过模块初始化，行为不等价）。

### 测试与门禁

- 全量 **383/383**；ruff 15 文件全净；冻结区 85 锁完好；
  **稳定性门禁 269→249（清除 20 项存量静默，棘轮只减不增方向正确）**；
  粘合层 18/0；双库无新增漂移。

## V4.40.1 (2026-09-26) — 整改 P1：前端三卡点接线 + prompt-image 负缓存

> 实测整改方案 P1 剩余三项之前两项落地（第三项 needs_log 25 处另行推进）。

### 前端三卡点（pre-commit 第⑦道，§2f.3 P0-a 闭环）

画布改动此前只有「双库一致性」一道卡点，类型检查与单测都没强制。
已把已有脚本接进手写 hook（零新增检查代码，只接线），**仅暂存画布文件时触发**
（与 ① ruff 增量哲学一致，不拖慢纯 Python 提交）：

- **⑦a tsc 类型棘轮**：错误数 ≤37 只减不增。基线 37 个错误全部位于
  stage3d-core 冻结区 2 文件（`Stage3D.tsx` / `riggedHumanoid.ts`），
  清零需解冻，解冻后下调基线。
- **⑦b vitest 单测**：81/81 失败即拦截。必须 `--pool=threads`——
  默认 forks pool 会把 SSR 编译结果写临时目录供 worker 读取，被
  fs-shim 拦截（EPERM）造成假失败；threads 走内存通道不写盘。
- **⑦c 质量棘轮**：`check_canvas_frontend_quality.mjs`（此前纯摆设）
  改造为卡点：dupNames ≤8 / fnOver300 ≤9 / cycloOver60 ≤5 只减不增。
  基线 8 组同名已人工定性＝启发式误报（`const next = arr.map((n) => {`
  多行箭头回调被识别为函数定义），非模块级静默覆盖；新增同名即拦。

### prompt-image 失败负缓存（§2d.3 P0-b 闭环）

- 端点实际在 `canvas_server.py`（非 canvas_bridge；**不在冻结区**，无需解冻）。
- 拉取失败写 `{sha256(url)}.fail` 标记（mtime 判定），TTL **6 小时**内
  同一 URL 不再重试（502 + 明确 message「负缓存 TTL 内不再重试」）——
  根治每次启动对 `pbs.twimg.com` 等死链重复多轮 45s 超时轰炸、刷日志拖慢启动。
- TTL 取 6h：覆盖一次工作会话；隔天重启允许重试一次；拉取成功主动
  清除标记（远端恢复自愈）。判定/写入出错一律不拦不炸（宁可重试）。
- 测试 `test_prompt_image_negative_cache.py` 6 项：未标记/标记命中/
  过期不命中/成功清除/幂等刷新/判定出错 fail-open。
  （import 顺序坑：直接 import canvas_server 触发部分初始化循环，
  需先 import canvas_bridge 全量初始化桥接层。）

### 顺带清理

- `canvas_server.py` 存量 ruff 11 处（增量门禁拦下即清先例）：
  死 `# noqa` ×7（A003/D401/N802×4/BLE001×2，对应规则集未启用）、
  死变量 `last_ping` ×2（SSE 循环内外各一）、`except as e` 未用、
  `zip()` 补 `strict=False`。

### 测试与门禁

- 全量 **383/383**；ruff 触碰文件全净；冻结区 85 锁完好；
  稳定性 269=269；粘合层 18/0；双库无新增漂移。

## V4.40.0 (2026-09-26) — 优秀三件事③：5 个真转场（ffmpeg 金标准对齐）

> 代码评价报告「距离优秀只差三件事」之**第三件事（收官）**：新增 5 个
> 真转场插件，预览与导出语义对齐——不信 ffmpeg 文档，抓 n9.0 源码推公式、
> 用本机二进制实测渲染做金标准逐像素验证。至此三件事全部落地：
> ① runGeneration（V4.39.8）② 调色 LUT（V4.39.9）③ 真转场（本版）。

### 新增 5 个转场插件（`app/plugins/`）

| 插件 | 效果 | 导出模式 | 依据 |
|---|---|---|---|
| `transition_radial` | 径向/时钟擦除（12 点起顺时针） | **exact**（xfade 直出） | 与 n9.0 公式+本机渲染 ≤4 LSB |
| `transition_diag` | 对角擦除（tl/tr/bl/br 四方向） | **exact**（xfade 直出） | 同上 ≤4 LSB |
| `transition_fadeblack` | 黑场过渡（经黑闪切） | **bake**（预览同码烘焙） | n9.0 公式与本机二进制漂移 ~13 LSB |
| `transition_fadewhite` | 白场过渡（经白闪切） | **bake** | 同上 |
| `transition_page` | 翻页（左/右，带脊线阴影带） | **bake** | 无 xfade 等价物，回退 coverleft/right（标注近似） |

- bake = 导出用**预览同一份代码**烘焙重叠窗 ⇒ 预览==导出由构造保证，
  免疫 ffmpeg 版本漂移；`export_degradation_note` 如实写明回退近似。
- exact 两者由**金标准测试常驻锁定 ≤6 LSB**（radial + diag×4 方向，
  与本机 ffmpeg 实际渲染逐像素对比，ffmpeg 缺失时自动 skip）。

### 关键发现与锁定

- **P↔帧号标定**：fade 线性探针确立 duration=1/offset=1/10fps 下
  f(n) 的 P=(n-11)/10（R+B=254 恒等），金标准采样 P∈{0.1,0.2,0.5,0.8,0.9}。
- **diag 命名反向**：ffmpeg `diagtl/tr/bl/br` 的命名角是**残留角**而非
  揭示起始角（`diagtl` 新画面从右下进入）。插件 direction（揭示起始角）→
  xfade 名做反转映射（tl→diagbr 等），`_DIAG_XFADE` 注释 + 测试双重锁定，
  禁止「顺手改正」。
- **radial 固有细缝**：P=1 时 12 点左侧残留 ~3% atan2 间断细缝
  （ffmpeg 同源行为），测试放宽为 `frac_b>0.9` 并注释记录。
- **fadeblack 本机行为**（实测，与 n9.0 源码不同）：红通道 ≈clip(1-6P)
  快降、P∈[0.2,0.3] 全黑驻留、谷底在 P≈0.3；中点蓝通道精确 86。

### 注册表扩展（`transition_plugin_registry.py`）

- 11 个中文标签（黑场/黑场过渡/白场/白场过渡/径向/径向擦除/时钟擦除/
  对角/对角擦除/翻页/翻页转场）→ 新插件；UI 下拉自动可见。
- `_PLUGIN_TO_XFADE` +3、`_DIAG_XFADE`（反向）、`_PAGE_XFADE`（回退）、
  `_EXPORT_FIDELITY` +5、`_KNOWN_XFADE` +4（diag 四名）。
- 映射表全员 ⊆ 本机 ffmpeg 实装 xfade 名单（测试硬编码 58 名核对，
  防止指向不存在的滤镜名）。

### 顺带修复存量地雷 ×2

- **根 `core/__init__.py` 空包遮蔽**：初始提交遗留的空壳包在 pytest
  路径序下遮蔽 `app/core`，导致全部旧式 `core.*` 插件导入静默失败
  （存量潜伏 bug，pytest 下插件从未真正加载过）。改为 `__path__` 转发
  shim（追加 app/core 为命名空间路径），两种路径序均可解析，无 bare
  `import core` 消费者（grep 核实）。
- **cv2.imread 中文路径坑**（4.11.0/Windows）：打不开**任何**含中文的
  绝对路径（fopen 按 ANSI 解释 UTF-8 字节序列），ffmpeg 写文件本身正常。
  金标准测试读取改 `read_bytes()+cv2.imdecode` 绕过（pathlib 走宽字符
  API）；相对 ASCII 路径不受影响——三场景对照实验定位（`_verify` 探针）。

### 测试与门禁

- 新增 `app/tests/test_transition_new_plugins.py` **19 项全绿**：注册发现、
  映射表核对（×10 方向 ⊆ ffmpeg 名单）、diag 反向映射、page 回退、
  fidelity 模式/降级说明/可烘焙性、中文标签解析、fadeblack 端点+中点+
  深降恢复、fadewhite 中点、radial 死区+顺时针象限+端点、diag 揭示角+
  软渐变带+端点、page 揭示/阴影/端点、**金标准 radial + diag×4（≤6 LSB）**。
- **全量 377/377**（358+19）；ruff 触碰文件全净（顺手清 registry 2 处：
  死 import numpy、C416）；冻结区 85 锁完好；稳定性门禁 269=269；
  粘合层契约 18/0；架构守护 0 警告；双库无新增漂移。

## V4.39.9 (2026-09-26) — 优秀三件事②：基础调色全量 LUT 化

> 代码评价报告「距离优秀只差三件事」之**第二件事**：预览调色链逐点浮点运算
> （每帧每通道 7 次全图遍历）折叠为 256 项查找表（LUT），查表一次完成。
> 1080p 实测：**401.9→174.0ms = 2.31x**（含饱和度）/ **300.0→83.1ms = 3.61x**
> （无饱和度），与旧链逐像素平价（≤1 LSB）。

### 条件化 LUT 架构 —— 宁可慢，不可偏

- `_pointwise_lut(steps)`：把逐点运算（亮度/对比度/曝光/伽马/高光/阴影）
  折叠成 uint8 (256,) 表；内部 float32、**中间不裁剪**（单次输出量化，保 ≤1 LSB）。
- **路径① 全链单表**（`saturation==1.0 and hue==0`）：整条逐点链合成一张表——
  输入恒为 uint8、无中间值损失，**无条件 ≤1 LSB，无需安全检查**。
- **路径② 分段**（有饱和度/色相）：亮度+对比度保持浮点（LUT 输出域 [0,255]
  会丢失无界中间值、污染饱和度灰度耦合——实测曾现 34 LSB 偏差）；
  曝光/伽马/高光/阴影段由 `_lut_entry_safe` 门控：复合函数在 x∈{0,255} 满足
  `F(0)≤0 且 F(255)≥255` 才 LUT（单调步 ⇒ 越界输入裁剪到同一最终输出），
  否则整段浮点回退。
- `_apply_effects`（EffectsWorkerThread）与 `_apply_effects_sync`
  （PreviewManager）两条链同架构改造，各自的路径特有语义
  （亮度两档换算、伽马预裁剪、preview_fast 中性化、色温逐通道表）原样保留。

### 锐化整帧化 + 暗角遮罩缓存

- 锐化：逐通道 `cv2.filter2D` 循环 → **单次整帧调用**（多通道卷积通道间独立，
  测试验证逐位一致），工人/同步两路同改。
- 暗角：`_vignette_mask(h,w,v)` 模块级缓存（≤8 项，GIL 原子操作）——
  遮罩与帧内容无关，消除逐帧 ogrid+sqrt。

### 顺带修复与发现（均有测试记录）

- **修复潜在生产缺陷**：负中间值（如饱和度>1 产生）经分数次幂伽马 → NaN →
  `astype(uint8)` 垃圾黑像素；LUT 入口裁剪输出定义的 0。
- **128 阈值间断带**（固有、非缺陷）：高光/阴影阈值本身不连续
  （Δinput 0.1 → Δoutput 23），LUT 入口 ±0.5 量化会在 ±1.5 带内翻转分支
  （对抗噪声帧 0.73% 像素）；带外 ≤2 LSB，测试量化记录。
- **死参数发现**：`color_params` 被 `_normalize_effects` 先行扁平化，
  `cp = effects.get("color_params")` 恒为空 → 色温读取点全应用零消费者
  （GL 路径也未实现）。如实记录为待接线候选，**未擅自「修复」**。

### 测试与门禁

- 新增 `app/tests/test_preview_lut.py` **14 项全绿**：工人/同步两路平价
  （NaN 与间断带掩码）、锐化逐位 ×2、恒等 ×2、负值组合、NaN 修复文档化、
  亮度两档、色温 LUT-C 数学、`_pointwise_lut` 恒等+无中间裁剪、
  暗角缓存与公式平价、1080p 基准断言 `t_new < t_old`（打印倍率）。
- **全量 358/358 连跑 4 次**；冻结区 85 锁完好；稳定性门禁 269=269；
  双库无新增漂移；ruff 三文件全净。

### 顺带修复存量抖动用例

- `test_safe_import.py::test_attribute_missing_tries_alternate_path`：
  `_safe_import` 替代路径 `core.editor_scheduler` 命中 sys.modules 缓存
  （`conftest` 把 app/ 加进 sys.path 后该包随时可解析，registry 测试链
  触发旧式 `core.*` 导入后即缓存）且属性完好时，用例 DID NOT RAISE ——
  与导入序/哈希种子相关，全量跑偶发 1 红。修复：预导入双路径、两个模块
  对象一并摘除属性、finally 还原、并新增断言「两条路径均被尝试」。
  该测试原本的 `del` 不还原问题（污染后续用例）一并消除。
- 清理存量死 import：`preview_manager.py` ×4（QSemaphore/QMutex/QPixmap/os）、
  `test_safe_import.py` ×2（sys/MagicMock）——均 grep 核实零引用。

## V4.39.8 (2026-09-26) — 优秀三件事①：画布生成异步化（generateForNode → runGeneration）

> 代码评价报告（综合 6.9/10）结论「距离优秀只差三件事」之**第一件事**，也是报告认定的
> 「整个体验整改里性价比最高的一项」：服务端 `/host/generation/*` 与前端 `generationQueue.ts`
> 都是现成的，断点只剩主路径 `App.tsx:generateForNode` 走同步阻塞端点。

### 接线层（bridge.ts）—— 一处改动，全部调用点异步化

- `generateImageViaHost` / `generateVideoViaHost` 新增可选 `awaitOpts`
  （`signal` / `onProgress` / `timeoutMs` / `maxAttempts`）：
  count==1 分支从同步 `POST /host/generate-image|video` 改走 `runGeneration`
  （submit → 轮询 status → 终态取 result）；count>1 批量循环递归自身、自动继承。
- **契约已逐键核对**：服务端 `_GEN_PAYLOAD_KEYS` 白名单（image 7 键 / video 10 键）
  与旧同步端点发送键完全一致；`_build_gen_callable` 为保真搬运
  （画质档→size 换算、NG 计数、GFPGAN 后台预载、视频后处理注册一个不少）。
  GFPGAN 预载轮询块（幂等去重）原样保留。
- **语义映射**：任务 `failed` → `{ok:false, message:上游原文}`；
  `AbortError` → `{ok:false, message:"已取消"}` —— 旧返回形状不变，
  11 个现有调用点（App.tsx ×9、mediaExtraNodes、VideoStudio）零改动直接获益。

### 交互层（App.tsx）—— 诚实进度 + 真取消

- `onGenerate` 持 `AbortController`；`onProgress` **如实上报**：
  `job.progress` 为 null（上游无真实信号）时只显示「阶段 · 已用时 Ns」，
  绝不编造百分比；仅视频后处理回传真值时才写节点 progress。
- 「中断」按钮复用升级：除原有的批量轮次中断外，现在同时 `abort()` 在飞的
  单节点任务与批量当前节点任务（`awaitGeneration` 收到 signal 后会调后端 cancel，
  后端任务一并取消、结果不落盘）。
- 取消语义：节点回 `idle`、不亮红、不残留 errorMessage；批量中被取消的节点
  同样回 idle 不计失败。

### 验证

- 新增 5 个异步接线单测（payload 键一致性 / done 映射 / 失败映射 / 取消映射 /
  视频 postprocess_job_id 透传），`bridge.test.ts` 10/10 绿；
  全套 8 个测试文件 76 断言逐文件跑全绿（整跑受沙箱 fs-shim 影响收集数抖动，
  逐文件确定性全绿）。
- tsc：主库 37 个冻结区基线报错零新增（App/bridge/generationQueue 零错误）；
  副库 0 错。
- 双库：`bridge.ts` / `App.tsx` / `bridge.test.ts` 已逐字节同步
  `vendor/AI-Canvas-tauri/src/libtv/`；双库检查 exit=0（bridge.test.ts 顺带收敛，
  副库缺失 7→6，基线已同步清理）。
- 冻结区守卫 85 锁点完好（本版本改动文件均不在冻结区）。
- 注：`canvasVersion.ts` 整文件冻结，画布版本号三件套待解冻后补。

## V4.39.7 (2026-09-26) — P0 整改：卡点真生效 + 门禁去假红 + 红测试清零

> 依据实测整改方案（合格线 8 绿 / 11 失守，其中 6 条是「标准写了没接线」）。
> P0 六项全部完成，核心是 **F1：卡点此前一道都没在跑，是所有问题的放大器**。

### P0-1 提交前卡点真生效

- `pip install pre-commit` 被沙箱硬杀（SIGTERM），按 §11 退路**手写** `.git/hooks/pre-commit`：
  ruff（仅暂存文件，存量不炸/增量严格）+ 冻结区/稳定性/粘合层/架构/双库五守卫。
- 空提交与真实提交均实测跑通；紧急跳过仍可用 `--no-verify`。
- ⚠️ 事故记录：曾用系统 ruff 0.16.3 `--fix` 意外修改 **167 个存量文件**，已全部还原；
  保留文件经 import 级排查，仅 3 处死 import 删除被保留（全文核实零使用）。

### P0-2 stability_gate 去假红（基线键去行号化）

- 基线键 `file:line:rule` → **`file:rule[:name]` + 计数棘轮**：插一行代码不再全红；
  同文件新增第二个同类违规仍被拦。旧基线加载时自动迁移。
- 新增逐行豁免：`# stability-gate: allow-print / allow-swallow`（必须附理由）。
- 验收实测：插空行 exit=0 ✓；加裸 print 必拦 ✓。

### P0-3 清 11 项真违规

- `main_qt6.py` 5 处 print：1 处改 `logging.getLogger`；4 处是**有意的控制台兜底**
  （`_safe_print` 实现本体 ×2、启动崩溃最后输出 ×2）→ 豁免注释保行为。
- `director_skill.py` / `video_editing_skill.py` 6 处 `except:pass` →
  `logger.debug(..., exc_info=True)`（JSON 降级链、ffprobe 兜底、临时文件清理、cv2→PIL 降级）。
- 基线 `--update` 固化：269 = 269，无新增。

### P0-4 红测试清零（pytest 349/349）

| 测试 | 病因 | 修法 |
|---|---|---|
| `test_register_includes_ripple` / `test_brain_taxonomy_has_ripple` | `len(ids)==25` 硬编码，能力已 69 个 | 改「必需集合包含 + 无重复注册」 |
| `test_funclip_autoclip_call_highlight_helpers` | 源码 grep 单文件，调用点已迁 mixin | 跟随真实调用点（`editor_ai_process_mixin.py`）+ 实现函数存在性 |
| `test_agent_methods_delegate_to_private` | 同上（mixin 拆分） | 拼接 `editor_module.py + editor_*_mixin.py` 全量源码断言 |
| `test_mask_api_key` | 实现 `[:2]` vs 语义裁定 | **按裁定改实现留前 4 位**（`sk-1***cdef`，便于辨认哪把 key） |

### P0-5 守卫 UTF-8 化

- `frozen_zone_guard.py` / `stability_gate.py` / `arch_guard.py` / `check_glue_contract.py`
  开头加 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`，
  GBK 控制台不设环境变量也能跑（pre-commit 钩子环境必需）。

### P0-6 校验只读化 + e2e 假失败修复

- **根因 1**：`plugin_store` 模块级单例 `plugin_store = PluginStore()`，import 即
  `init_official_items` → 无条件 `_save_*` 刷 `updated_at` ⇒ 任何只读引用都弄脏 git。
  修复：`_write_json_if_changed`（内容未变不写盘）。
- **根因 2**：e2e 写 `~/.video_editor_cache/canvas_plugins.json`，venv 沙箱下
  Permission denied 让 install/toggle/uninstall 三项假失败。
  修复：e2e 把 `cb._CANVAS_PLUGINS_JSON` 重定向 `tempfile.mkdtemp`（也符合「校验不污染真实数据」）。
- 一键回归 **53/53 全绿**（注意：须用 `.venv312`，managed 3.13 缺 numpy/pypinyin 会假红 6 项）。

---

## V4.39.6 (2026-09-26) — LibTV 1.5 对标升级（四件落地）

> 依据：`docs/_reports/2026-09-26-LibTV1.5对标升级方案.md`。
> 核心判断：LibTV 1.5 的五件事，拾光剪影已有四件半的零件，缺的是三根连接线。
> 本版本落地全部**非冻结区**升级；冻结区项列在文末待用户解冻。

### ① P0-1 导演分身落时间线（`director_skill.py` v1.1.0）

- 新增技能步骤「落地时间线」：传入 `source_dir`（素材目录）且有分镜表时触发，
  按分镜顺序把目录内媒体文件（循环映射）批量送入剪辑时间线。
- **复用已接线路由** `EventType.MATERIAL_TO_TIMELINE`（素材库拖入/画布回流同一条），
  不新造旁路；先检查订阅者存在，剪辑模块未打开时**诚实跳过**（`applied=False` + 原因），不阻塞技能。
- 报告字段 `edit_instructions_applied_to_timeline` 由硬编码 `False` 改为真实执行结果，
  新增 `timeline_apply_note`。
- 验证：`_verify/test_director_timeline_apply.py` **13/13**（含空目录、无订阅者两条诚实跳过路径）。

### ② 导演分身能力化（两个新 Agent 能力）

| 能力 | 作用 | effect | 验证 |
|---|---|---|---|
| `pipeline.director_breakdown` | 剧本→分镜表（LLM 优先 / 启发式降级） | read · 免费 | 启发式产出 3 个镜头 ✓ |
| `pipeline.director_camera_plan` | 分镜→机位/运镜/提示词（可直传 shots 或从剧本级联） | read · 免费 | cameras==shots、键齐全 ✓ |

- 已登记 `agent_capability_catalog.py`（大脑分类：breakdown→右脑 / camera_plan→左脑），
  通过目录↔注册双向启动自检。验证：`_verify/check_director_capabilities.py` **15/15**。

### ③ P1-3 封面选帧变真 + 片头标题卡（`CoverGeneratorSkill` v1.1.0）

- **选帧变真**：真实抽取 3 帧代理图（320px JPEG），cv2 打分选最优——
  清晰度(Laplacian) 0.45 / 曝光 0.20 / 对比度 0.20 / 饱和度 0.15；
  替代原「永远取中间帧」的占位实现；引擎不可用时**诚实标记 placeholder** 不冒充。
- **片头标题卡**（新步骤，可选）：PIL 底部 30% 渐变条 + 居中描边中文标题 + 副标题，
  字号自动收缩防溢出；无中文字体且标题含非 ASCII 时诚实跳过。
- 修复 **cv2 中文路径静默失败**（`np.fromfile`+`imdecode`，本项目路径含「拾光剪影」必踩）。
- 顺带修复历史 bug：技能从未 `set_output`，Skill 工坊报告恒为空——现已输出全部关键结果。
- 验证：`_verify/test_cover_scoring.py` **11/11**（含真机素材端到端 + 片头卡目视确认中文渲染正确）。

### ④ 题材设定包 `shiguang-genre.json`（8 题材）

- 8 条：**末世生存基建 / 重生复仇爽剧 / 非遗国潮视觉 / 仙门团宠日常**（LibTV UI 对标四题材）
  + 都市甜宠契约 / 赘婿逆袭龙王 / 悬疑反转单元剧 / 古风权谋虐恋。
- 每条 prompt 内嵌**四要素：世界观 / 主线 / 角色位 / 禁忌**（禁忌即合规护栏）。
- 与分镜层 `shiguang-drama.json` **分层不合并**；格式同为 5 字段（`id/title/category/tags/prompt`）。
- 已注册 `promptLibrary.ts`（`shiguang-genre-pack`），双库 `public/prompts` + 副库 `dist/prompts` 三处字节一致。
- 验证：`_verify/check_genre_pack.py` **10/10**。

### ⚠️ 冻结区待解冻项（本次未动）

| 升级项 | 涉及冻结区 | 说明 |
|---|---|---|
| P0-2 角色形象图入库 | `stage3d-core` | `CHARACTER_FIELD_SCHEMA` 无形象图字段，加字段必碰 `character_management_module.py` |
| P0-3 画布绑角色丢字段 | `canvas-magnetic-intent` | 节点绑定角色时 visual/inner 字段丢失 |
| P1-1 剧本设定器 UI | `canvas-magnetic-intent` | ScriptNode 现为纯文本框，设定器需改 `nodes.tsx` 等 33 整文件锁范围 |
| P2 3D 体型↔角色库 / 白模入轨 | `stage3d-core` | `riggedHumanoid.ts` HUMAN_PRESETS 与角色库互通 |

另：画布版本号 `canvasVersion.ts` 属整文件锁，本次**不递增**，待解冻画布改动时一并 bump。

### 质量门

- 冻结区守卫：`OK frozen zones intact (85 locks)` ✓
- 双库校验：`check_canvas_dual_repo.py` exit=0，无新增漂移 ✓
- 画布 tsc：与文档基线一致，错误全部位于 stage3d-core 冻结区文件，与本次改动无关 ✓

---

## V4.39.5 (2026-09-25) — 虚拟形象提示词包（12 条）

> 用户需求：给项目做「漂亮好看的女性的虚拟形象动态视频」的**参考提示词**。

### 产出：`vendor/shiguang-canvas/public/prompts/shiguang-avatar.json`（12 条）

**三组分工**：

| 组 | 条目 | category | 用途 |
|---|---|---|---|
| ① 设定卡 | avatar-001 定妆三视图 · 002 面部锚定特写 · 003 全身比例设定 | `consistency` | 供 `character_anchor` 做**跨镜头一致性锚定**（先定妆，后续镜头复用同一套外观描述） |
| ② **动态视频** | 004 口播播报 · 005 窗边侧光静立 · 006 转身回眸 · 007 走向镜头 · 008 微笑抬头特写 · 009 霓虹光影扫过 · 010 国风执扇回眸 | `storyboard` | 直接用于文生视频 |
| ③ 首帧图 | 011 半身正面（留白）· 012 动态预备姿势 | `portrait` | 用于图生视频（i2v）的起始帧 |

**每条动态提示词的必备要素**（这是与静态人像提示词的关键差别）：
**动作** + **动态细节**（发丝摆动 / 衣料起伏 / 呼吸幅度 / 微表情渐变）+ **镜头运动**
（缓推 / 环绕 / 跟拍 / 手持浮动）+ 光线 + 风格 + 画幅。

### 格式严格对齐现有包

| 校验项 | 结果 |
|---|---|
| 字段集合 vs `shiguang-drama.json` | **完全一致**（`id/title/category/tags/prompt`） |
| id 唯一性 | ✓ 12 条无重复 |
| 分类合法性 | 沿用现有词表：`consistency` / `storyboard` / `portrait` |
| 技术提示（画幅/时长/渠道） | 写进 **tags**（`t2v`/`i2v`、`5s`/`10s`、`9:16`/`16:9`）——保持 5 字段格式不变 |
| 合规 | **全部条目 prompt 明确标注「成年女性」**（沿用项目既有惯例，如 `curated-002/012/013`） |
| 动态要素 | 7 条动态条目**全部含动作/镜头/飘动/变化**类描述 |

### ⚠️ 关键接线：必须注册，否则前端读不到

`promptLibrary.ts` 的本地包清单是**显式枚举**（`localAssetSource(...)`），
与 Agent 能力「四处接线」同理 —— **新文件不注册就等于不存在**。
已在 `shiguang-drama-pack` 之后注册：

```
localAssetSource("shiguang-avatar-pack", "拾光·虚拟形象包", "shiguang-avatar.json", false)
```

### 双库同步（先 diff 再动手）

1. 双库检查**先精确抓到新增分叉** `promptLibrary.ts`（一致 64→63，exit=1）—— 守卫正常工作；
2. **diff 证明**副库 `src/libtv/promptLibrary.ts` 与主库本次改动前**完全一致**（仅 1 个 hunk = 本次 6 行）
   ⇒ 可安全同步（若副库已有其它差异，则只能手工合并）；
3. 按纪律**先备份** `.bak-avatar` → 补 6 行注册 → 复制提示词包到
   副库 `public/prompts/` 与 `dist/prompts/`；
4. 复跑双库校验：**回到基线**（一致 64 / 分叉 22 / 缺失 16，**exit=0**）
   —— 用「同步消除分叉」而非「上调基线」，这是正确做法。

### 验证

| 检查 | 结果 |
|---|---|
| `vitest` | **76 例全过**（批量 7 文件 68 例 + `MagneticEngine` 单跑 8 例；沙箱少收集为已知现象） |
| `tsc --noEmit` | **37 处 = 文档基线**（零新增） |
| `vite build` | ✓ 成功（7.16s） |
| 双库漂移 | **无新增**（exit=0） |
| 冻结区守卫 | **85 locks intact**（`promptLibrary.ts` 不在冻结区） |

### 用法指引

1. **先定妆**：用 avatar-001/002 生成角色设定卡 → 作为 `character_anchor` 的一致性基准；
2. **再生成动态**：选 004~010 中一条，配合上面同一套外观描述（模型才能保持同一张脸）；
3. **长镜头用 i2v**：先用 011/012 出首帧，再驱动动作（比纯文生视频更可控）；
4. **时长适配渠道**：tags 里标了 `5s`（dashscope 万相单段上限）/ `10s`（Seedance 上限）。

---

## V4.39.4 (2026-09-25) — 技术债止血：单文件规模守卫 + UI 归属/依赖纪律固化

> 用户要求「明确的技术债，能优化一点就优化一点」。
> 本轮**只做零风险高价值项**，高风险重构（拆 9,717 行文件）不动。

### ① 新增：单文件规模守卫 `_verify/check_file_size.py`（阈值 2000 行）

**为什么**：`editor_module.py` 已 **9,717 行**（09-19 时 9,479 → **仍在涨**），
而项目**没有任何机制阻止它继续变大**。每加一个功能，认知负荷就再涨一截。

**做法**（不要求立刻拆，先止血）：

| 情形 | 结果 |
|---|---|
| 基线内文件增长 > 容差 30 行 | ✗ 失败（债务增长） |
| 基线外新文件 > 2000 行 | ✗ 失败（新增超标） |
| 基线内文件变小 > 30 行 | ✓ PASS + 提示「已收敛，可下调基线」 |
| 基线文件消失 | · 提示确认后从基线移除 |

**冻结为基线的 12 个文件**：

| 文件 | 行数 |
|---|---|
| `app/modules/lego/editor_module.py` | **9,717** |
| `vendor/shiguang-canvas/src/Stage3D.tsx` | 4,660 |
| `vendor/shiguang-canvas/src/riggedHumanoid.ts` | 3,707 |
| `vendor/shiguang-canvas/src/CanvasShell.tsx` | 3,199 |
| `app/core/canvas_server.py` | 3,273 |
| `app/core/canvas_aigc.py` | 2,905 |
| `app/modules/lego/settings_module.py` | 2,823 |
| `app/modules/lego/video_processor.py` | 2,732 |
| `vendor/shiguang-canvas/src/store.ts` | 2,452 |
| `app/modules/lego/editor_agent_panel_mixin.py` | 2,330 |
| `app/modules/lego/extensions_module.py` | 2,198 |
| `app/modules/lego/drama_understanding_engine.py` | 2,160 |

**已通过负向测试**（造 2100 行文件 → 正确 FAIL 并给出拆分指引）——
证明它不是"永远 PASS 的假守卫"。已注册进 `run_all_checks`（第 53 项）。

### ② 固化两条被反复误读的事实（写进《现行技术文档》§2b）

**(a) UI 归属真相 —— 不是「双前端」**

| 角色 | 位置 |
|---|---|
| Qt 桌面壳 | `app/main_qt6.py` + `app/modules/lego/`（PyQt6） |
| **画布前端（唯一源码）** | `vendor/shiguang-canvas/`（102 文件 / 38,707 行） |
| 宿主 A（默认） | `engine=shiguang` → WebEngine **嵌入** Qt6 |
| 宿主 B | `engine=tauri` → `vendor/AI-Canvas-tauri/` **独立进程** |

⇒ 准确表述：**「一个 Qt 桌面壳 + 一份 React 画布源码 × 两个宿主」**。
切换见 `app/core/canvas_runtime.py`。⚠️ 副库**未被 git 跟踪** ⇒ 改前必须备份。

**(b) 依赖升级纪律**：patch 直接打 · minor 需回归 · **MAJOR 禁止盲升**。
硬约束：**`numpy 1.26.4` 被钉死**（numba 0.64 要 numpy<2.1；opencv/torch ABI 绑 1.x）。

### ③ 待授权的债（本轮未动，附理由）

**前端 37 处 tsc 存量错误** —— 性质已查明：绝大多数是
`Object3D | null` 与 `Object3D | undefined` 的**类型标注不一致**（TS2322 ×20 / TS2345 ×7 /
TS2556 ×4 / TS18048 ×3 / TS2339 ×2 / TS2554 ×1），**纯类型问题、运行时零影响**。
受影响文件 `Stage3D.tsx` / `riggedHumanoid.ts` **位于冻结区 `stage3d-core`** ⇒
**须获「解冻 stage3d-core」授权**方可修复。修完的好处：A/B 对比流程可简化
（基线清零后，任何新错都是真错）。

**其余债（本轮未做，非零风险）**：`editor_module.py` 拆分（大工程）、
两套插件系统合并（需架构决策）、lego 81 模块分层、副库纳入 git（15.8 万行）、
双库 22 分叉收敛（需逐项判定是否「有意不同步」）。

### 验证

`SIZE` 守卫 PASS（含负向测试）· `run_all_checks` 全绿（53 项）。

---

## V4.39.3 (2026-09-25) — 全项目官方补丁排查与打补丁

> 按用户要求排查「所有可打的官方补丁」。**两个维度都查了**，
> 并严格区分「已打」与「刻意不打（附理由）」——不盲目升级。

### 维度一 · 数据源（延续 V4.39.2 的 Unihan 工作）

把 Unihan 的**其他拼音字段**全部排查了一遍：

| 字段 | 条目数 | 对 pypinyin 缺口的补充 |
|---|---|---|
| `kMandarin` | 44355 | **2517**（V4.39.2 已用） |
| `kHanyuPinyin` | 34130 | **0** |
| `kXHC1983` | 11072 | **0** |
| `kTGHZ2013` | 8105 | **0** |

⇒ **数据源侧已榨干**：后三个字段覆盖的字 pypinyin 全都认识
（价值仅在「多音字候选交叉校验」，不能扩大覆盖面）。
kMandarin 的 2517 字补丁即为开源数据的上限。

### 维度二 · Python 依赖（28 个直接依赖 × 89 个可升级包求交）

**✅ 已打 4 个安全补丁**（patch 级 + API 极稳定的安全相关库）：

| 包 | 升级 |
|---|---|
| `cryptography` | 50.0.0 → **50.0.1**（安全库） |
| `imageio` | 2.37.3 → **2.37.4** |
| `Pillow` | 12.2.0 → **12.3.0**（图像库，CVE 高发区） |
| `requests` | 2.32.5 → **2.34.2**（网络库） |

**⛔ 刻意不打 6 个 MAJOR**（会连锁炸）：

| 包 | 现状 | 为什么不能升 |
|---|---|---|
| `numpy` | 1.26.4 → 2.5.3 | **被钉死**：numba 0.64 要求 numpy<2.1，opencv/torch 的 ABI 建立在 1.x |
| `moviepy` | 1.0.3 → 2.2.1 | API 大改（视频合成主链路） |
| `opencv-python-headless` | 4.13 → 5.0 | 大版本，图像链路 |
| `librosa` | 0.11 → 1.0 | 大版本，音频分析 |
| `mediapipe` | 0.10 → 1.0 | 大版本，姿态检测 |
| `anthropic` | 0.25 → 1.8 | SDK API 大改 |

**⏸ 待评估 12 个 minor**（需专项回归，未擅自升级）：
PyQt6/PyQt6-Qt6/PyQt6-sip（GUI 核心）· transformers（AI 核心）·
dashscope（视频生成）· onnxruntime · aiohttp · numba · pillow✅已升 · playwright · zhipuai 等。

### 维度三 · 前端依赖（画布 `vendor/shiguang-canvas`）

**✅ 已打 semver 范围内全部官方补丁**（`npm update`）：

| 包 | 升级 |
|---|---|
| `@xyflow/react` | 12.11.2 → **12.11.6**（**画布磁吸核心依赖**） |
| `react` / `react-dom` | 19.2.8 → **19.3.0** |
| `zustand` | 5.0.14 → **5.0.15** |
| `@types/react` / `@types/react-dom` | 19.2.x → **19.3.0** |

**⚠️ npm audit 报 5 个漏洞（1 critical + 1 high + 3 moderate）→ 刻意不打**：

全部集中在 **`vitest` 测试工具链**（vitest / vite / @vitest/mocker / vite-node / esbuild）：
- critical：`vitest` — "Vitest UI server 监听时可任意读/执行文件"
- high：`vite` — Optimized Deps `.map` 路径穿越 / launch-editor NTLMv2 哈希泄露

判定依据（三点）：
1. **全是 devDependencies**（测试工具链），**不进发布包** ⇒ 对发布版零影响；
2. 触发场景是**本地 vitest UI server 在监听**，而本项目只用 `vitest run`（不启 UI server）；
3. 唯一修复路径是 **vitest 2→5 + vite 6→8 双 major 跳跃** —— 会改动测试配置与构建链，
   收益（修 dev-only 漏洞）**远小于**破坏面风险。

⇒ 保持现状，并把决策所需信息留在案。若确需修复：
`npm audit fix --force`（一次性升 vitest 5 + vite 8，之后需重跑测试与构建回归）。

**⛔ 不能升的前端 major**：vite 6→8 · typescript 5→7 · vitest 2→5 · @vitejs/plugin-react 4→6 · three 0.185→0.186。

### 验证

| 检查 | 结果 |
|---|---|
| Python `run_all_checks` | **全绿**（4 个补丁升级后） |
| 前端 `vitest run` | **8 文件 76 例全过** |
| 前端 `tsc --noEmit` | **37 处 = 文档基线**（Stage3D 16 + riggedHumanoid 21），**零新增** |
| 前端 `vite build` | ✓ built in 4.29s |
| 双库漂移 | **无新增**（一致 64 / 分叉 22 / 缺失 16 = 基线） |

---

## V4.39.2 (2026-09-25) — A：Unihan 补丁表 + B：LLM 消歧候选约束

> 用户选定「A 和 B 同时」。两条都在**实测数据**驱动下完成，并纠正了上版
> 用抽样得出的两个不准口径。

### A｜Unihan 官方补丁表（补 2517 个「原本完全无法注音」的字）

数据源：Unicode 官方 Unihan 数据库 `kMandarin` 字段（44355 条，100% NFC）。
筛选口径：**仅保留 pypinyin 已查不到的字**（避免重复、不覆盖主词典
—— 否则官方读音会被 pypinyin 的常用读音顶掉）。

产物：`app/core/ai/pinyin_unihan_patch.py`（**编译进代码**，64KB）。
为什么不用 JSON：`data/*.json` 被 .gitignore 排除；PyInstaller 打包还需额外配置
数据文件 —— 编译进 .py 则零配置、必定随包发布（pypinyin 自身也是这么做的）。

工具：`scripts/gen_unihan_pinyin_patch.py`（正式工具，可重复运行；Unihan 发新版时重跑）。

**精确实测（逐字遍历，纠正上版抽样口径）**：

| 区 | 总量 | pypinyin | 补丁命中 | 合计 |
|---|---|---|---|---|
| CJK 基本区 | 20992 | 99.7% | 0 | 99.7% |
| 扩展 A 区 | 6592 | 87.7% | 9 | 87.8% |
| 扩展 B 区 | 42720 | **34.0%**（上版抽样误报 31.1%） | 94 | 34.2% |
| 三区合计 | 70304 | 58.6% | 103 | **58.8%** |

**⚠️ 诚实的价值边界**：补丁 2517 字的分布**极冷门** ——
扩展 G 1098 · 扩展 E 705 · 扩展 C 386 · 扩展 I 99 · 扩展 B 94 ·
扩展 D 64 · 扩展 F 61 · 扩展 A 9 · 扩展 H 1。
与影视字幕实际相关的**仅约 103 字**（扩展 A/B），其余为甲骨文/金文级罕用字。
对三区总覆盖率提升 **+0.2%** ⇒ 保留理由是「成本极低、遇到就赚到」，
**不是**「补齐了扩展区」。彻底补齐需《汉语大字典》级数据（非开源）。
两库皆无的字仍标 `unknown`、`coverage=0.0`，**绝不编造读音**。

### B｜LLM 消歧：把「填空」变成「选择题」+ 判卷

原实现让 LLM 直接写拼音（填空）⇒ 可能编造不存在的读音，且同字两次结果可能不同。
现三步改造（`tts_guard.py`）：

1. **候选约束**（`_candidate_hint`）：字典先检出文本中的多音字并列出**全部合法候选**
   （例：`重 ∈ [zhòng, chóng, tóng]`），提示词要求 LLM **只能从候选里选**；
2. **判卷**（`_validate_polys`）：返回后逐项校验，读音不在候选集内的一律丢弃
   —— **没有这一步，候选约束就只是提示词里的礼貌用语**；
3. **跨段防串味**：批量模式下额外校验「该字确实出现在本段文本中」
   （候选约束是全局生成的，LLM 可能把别段的字标进本段）。

兜底衔接收紧：LLM 产出被全部判废 → 字典兜底接管（`llm_annotated=0 /
dict_annotated>0`，实测确认）。

### 验证

| 检查 | 结果 |
|---|---|
| `check_pinyin_dict.py` | **64/64 全过**（新增 15 项：补丁链路 / 诚实边界 / 判卷拦截 / 串味拦截 / 兜底衔接） |
| `check_tts_guard.py` | 47 项全过 |
| 判卷实测 | `chóng` 保留 · `zhǒng`(编造) 丢弃 · `zhòng`(另一合法候选) 保留 |
| 补丁链路 | 扩展 A `㟥`→`cēn` · 扩展 B `𠇐`→`yú`（source=unihan）· SAPI `cen1` |
| 冻结区守卫 | 85 locks intact（改动全在冻结区外） |

---

## V4.39.1 (2026-09-25) — 注音字典补齐（专名校订 + lip_sync 挂载）

> **起因**：用户问「这个字典是不是不够齐全」。**先体检、再补**，不凭感觉。

### 体检实测（硬数据，2026-09-25）

| 维度 | 实测 | 判定 |
|---|---|---|
| CJK 基本区 | **99.7%**（20924/20992） | 缺口 68 字，多为度量衡合字（兙兡嗧桛烪瓧瓰瓱） |
| 扩展 A 区 | **87.7%**（5779/6592） | 缺口 813 字 |
| 扩展 B 区 | **31.1%**（抽样） | 近七成缺失 |
| **专名读音** | **20/25（错误率 20%）** | ✗ 致命：古装短剧古人名/地名密度极高 |
| 易错词 | 25/26 | ✗ 削苹果 → xuē |

专名错例：大宛→`dà wǎn`(应 yuān)、皋陶→`gāo táo`(应 yáo)、
金日磾→`jīn rì dī`(应 mì dī)、樊於期→`fán yú qī`(应 wū jī)、曹参→`cáo cān`(应 shēn)。

### 补齐① 人工校订表（169 词组 + 24 单字）

经 `pypinyin.load_phrases_dict` / `load_single_dict` 注入，覆盖：古人名 ·
复姓 · 古国地名 · 成语典故 · 常见易错词 · 生僻单字。

**校订后：专名 25/25、易错词 24/24。** 两条纪律：
- **字数不符的条目自动跳过并报告**（`stats()["overrides"]["skipped"]`）——
  拼音音节数 ≠ 词字数时宁可跳过，**绝不静默错位**把整句读错；
- 数据性质诚实声明：**人工校订表**（依据普通话异读词审音表常见条目），
  非权威数据库；只收高置信度条目，拿不准的不写。

### 补齐② 项目自定义读音表 `data/pinyin_overrides.json`

`override_template()` 给模板。用途：**剧中人名 / 门派名 / 招式名读音全项目统一**
（短剧高频需求）。优先级最高，可覆盖内置条目；缺失时不报错。

### 补齐③ `lip_sync` 改走字典入口

原 `lip_sync.py:505` **直接 `import pypinyin`** ⇒ 拿不到校订。改后：
- 口型与 TTS 正音**同源** ⇒ 消除「配音读 chóng、口型按 zhòng」的音画不一致；
- 用 `chars` 详情过滤非汉字 ⇒ 修掉「`'abc123'` 被当成一个音素传给 Viseme 查表」；
- 字典不可用时诚实降级字符级兜底（行为同旧版）。
- 实测：大宛→`d+a, y+uan`（=yuan ✓）、龟兹→`q+iu, c+i`（=qiui ✓）、
  重庆→`ch+ong, q+ing`。

### 诚实边界（本次**没做**）

**扩展 A/B 区未补齐**：补齐需引入 Unihan 数据库（约 8MB）离线数据，
而扩展 B 区字在实际字幕中几乎不出现（成本高、收益低）。
覆盖率缺口已在 `stats()["coverage_measured_2026_09_25"]` **显式标注**；
查不到的字仍标 `unknown`、`coverage=0.0`，**绝不编造读音**。
如需补全：可接 Unihan `kMandarin` 字段生成补丁表。

### 验证

| 检查 | 结果 |
|---|---|
| `check_pinyin_dict.py` | **49/49 全过**（新增专名 25 例 + 易错词 24 例 + 校订表规模 + lip_sync 3 项接线断言） |
| `check_tts_guard.py` | 47 项全过 |
| 三向一致核对 | 全绿 |
| 冻结区守卫 | **85 locks intact**（含 `lip_sync.py` 在内全部改动均在冻结区外） |

---

## V4.39.0 (2026-09-25) — 汉字注音字典（离线确定性）+ 四处接线

> **痛点**：`tts_guard` 的「多音字注音」原本**让 LLM 现场猜拼音**——LLM 不可用/
> 调用失败即「降级为不注音」，**整段注音静默消失**，配音「后面发音错/与字幕不符」
> 的老问题随之复发；且同字两次调用可能给出不同拼音（不可复现）。

### 新模块：`app/core/ai/pinyin_dict.py`（离线字典服务层）

纯模块（只标准库 + 惰性 import pypinyin），异常不抛，**不 import `app.*`**。

| API | 用途 |
|---|---|
| `is_available()` | 可用性 + 人话原因（库缺失时不抛错、不返假数据） |
| `annotate(text, style)` | 整段注音（词组级消歧）；`style` = tone / tone3 / normal |
| `lookup(text)` | 逐字：读音 + **全部候选** + 是否多音字 + 未知标记 |
| `polyphones(text)` | 多音字清单（**带候选集** → 把 LLM 的「填空」降级成「选择题」） |
| `to_sapi(text)` | SAPI 数字式（`chong2`），对接 TTS |
| `to_ssml(text)` | **按位置**标注多音字的 SSML（同一字多处不同音各自正确） |
| `stats()` | 覆盖自述（含**不覆盖**的诚实边界） |

### 实测覆盖能力（pypinyin 0.55.0，2026-09-25）

| 场景 | 结果 |
|---|---|
| 常用字 | ✓ 中国导演 → zhōng guó dǎo yǎn |
| **多音字词组消歧** | ✓ 重庆→chóng qìng · 银行→yín háng · 长大→zhǎng dà · 音乐→yīn yuè |
| 生僻字 | ✓ 鑫淼焱垚犇 / **龘靐齉爨彧** / 三叠字 羴猋麤 全部注出 |
| **CJK 扩展 B 区**（𠀋𠮷） | ✗ **字典未覆盖 → 标 `unknown`，绝不编造读音**（`coverage=0.0` + 人话提示） |
| 英文/数字/标点 | ✓ 原样保留，不误标 |

### 挂载到相关模块（用户要求「挂到相关模块里面去」）

**① tts_guard（离线兜底，性质变化）**
- 新增 `TtsSegment.annotated_source`（`llm` / `dict` / `""`）——注音来源可审计；
- `plan_tts` 加字典兜底：LLM 未产出或未接 LLM 时，字典按位置标注多音字。
  **改前**：`llm=None` → `annotated=""`，一个字的注音都没有；
  **改后**：字典接管，`dict_annotated > 0`，仍产出 `<phoneme>` SSML；
- 新增返回字段 `llm_annotated` / `dict_annotated`，`message` 诚实标明来源。
- 检查脚本期望同步升级为更强断言（原断言要求「降级后零注音」，现要求
  「不崩 + 字典确有注音 + 来源标 dict」）。

**② Agent 能力 4 处接线（`pipeline.pinyin_lookup`）**
| # | 位置 | 内容 |
|---|---|---|
| 1 | `agent_capability_catalog.py` | 目录行（effect=`read`，半球=**left** 语言/逻辑） |
| 2 | `capability_handlers.py` | `pinyin_lookup` handler + `dispatcher.register` |
| 3 | `agent_action_registry.py` | `_AGENT_ACTION_ROWS` 加 action（★ 守卫不覆盖，漏了 Agent 不会调） |
| 4 | `agent_action_registry.py` | 帮助文案参数说明 + L2 执行段（★ 守卫不覆盖） |

### 依赖

`pypinyin>=0.53.0` 加入 `requirements.txt` 与 **`app/requirements-optional.txt`**
（可选语义：缺失时注音能力**诚实降级**、不影响其他功能，故不进 REQUIRED）；
`main_qt6.DependencyChecker.OPTIONAL_PACKAGES` 同步登记（缺失不报错）。

### 验证

| 检查 | 结果 |
|---|---|
| `_verify/check_pinyin_dict.py`（新） | **40/40 全过**（含确定性、SSML 按位置、四处接线静态断言、dispatcher 端到端） |
| 三向一致手工核对 | catalog↔dispatcher OK · `ACTION_TO_CAPABILITY` 正确 · 在白名单 · 神经元表含它 |
| 端到端调用 | `重庆银行` → chóng qìng yín háng，多音字 `['重','行']` |
| `check_tts_guard.py` | 47 项全过（含升级后的 3 条字典断言） |
| 冻结区守卫 | `85 locks intact`（改动全在冻结区外） |

### 已知未做 / 边界

- **CJK 扩展 B 区及以后不覆盖**（如 𠀋𠮷）→ 标 unknown，需人工/外部数据补；
- LLM 消歧路径**尚未接入候选约束**（字典已提供 `candidates`，可作为 prompt 约束
  提升 LLM 准确率，属下一步）；
- 字典未参与 `lip_sync` 口型链路（其拼音→Viseme 映射目前独立）。

---

## V4.38.6 (2026-09-23) — 画布卡片尺寸统一 + 上端吸附对齐（画布 0.3.1）

> **性质**：画布缺陷修复（用户反馈两条）。冻结区 `canvas-magnetic-intent`
> **已获用户授权解冻**，改完重锁（85 locks intact）。

### 行为变更表

| 位置 | 变更前 | 变更后 | 依据 |
|---|---|---|---|
| `novice/types.ts` `CARD_GEOMETRY` | `minHeight: 200` | **`height: 200`** | 用户裁定「卡片大小不统一」 |
| `novice/NoviceCard.tsx` 内联样式 | `minHeight`；body 内联 `minHeight` | `height`；body 无内联 | 同上 |
| `novice/novice-cards.css` `.nv-card-body` | `flex:1`（可被撑高） | `+ min-height:0; overflow:hidden` | 同上 |
| `.nv-card-thumb` / `img,video` | 固定 `height: 96px` | 容器 `flex:1 1 auto; min-height:40px`；媒体 `height:100%; max-height:72px` | 用户裁定「缩略图 96→72 + 文字 3→2 行」 |
| `.nv-card-text` | `-webkit-line-clamp: 3` | `2` | 同上 |
| `magnetic/MagneticEngine.ts` `getSnapPosition` `top`/`bottom` | `x: keepX`（拖拽卡当前 x） | **`x: targetPos.x`**（顶边对齐） | 用户裁定「最上端的吸附没有对齐」 |
| `.nv-card-hint` | flex 默认（**可收缩**，被压扁裁字） | `flex: 0 0 auto` | 渲染实测抓获（见下） |
| `.nv-card-meta` | 无约束 | `flex: 0 0 auto` + 单行省略号 | 同上 |
| `.nv-card-body:has(.nv-card-thumb) .nv-card-hint` | 显示 | **折叠**（`display:none`） | 渲染实测：四层内容在 200px 内数学上装不下 |
| `.nv-card-body:has(.nv-card-thumb) .nv-card-text` | 2 行 | 1 行 | 同上 |
| `.nv-card-thumb` `min-height` | 40px | 24px | 同上（让预览图吃满剩余空间） |

### 修复的实际缺陷（带证据）

1. **卡片大小不统一** — `NoviceCard.tsx:226-231` 原为 `minHeight`；正文区内容
   叠加实测 ≈**306px**（hint 31 + 缩略图 96 + 正文 3 行 72 + meta 17 + padding/gap），
   空卡仅 200px。**同时违反冻结不变量「DOM 实尺寸必须 240×200（磁吸落位基准）」**
   ⇒ 本次修复属**恢复**不变量。
2. **最上端吸附没对齐** — `MagneticEngine.ts:254-263` 原 `top`/`bottom` 保留拖拽
   卡 x，上下贴合后两卡左右边缘错开、不成列。改为 `targetPos.x` 后成列；
   水平位移受磁吸范围约束（edge-gap < 120px），无瞬移观感。
3. **渲染实测又抓出两处**（本轮「必须渲染出来亲眼看」纪律的收益，见证据图
   `docs/_reports/2026-09-23-画布卡片尺寸实测.png`）：
   - `.nv-card-hint` 作为 flex 子项**默认可收缩**，卡片固定高后空间紧张时被压扁裁字
     ⇒ 提示语/元信息补 `flex: 0 0 auto`（让缩略图独自承担收缩）；
   - **四层内容在 200px 内数学上装不下**：正文区可用高度实测仅 **106px**
     （200 − header 40 − footer 32 − border 2 − padding 20），而「提示语 31 +
     缩略图下限 40 + 正文 2 行 44 + 元信息 17 + 间隙 16」需 **148px** ⇒ 实测裁切 **45px**。
     故有图时按信息价值收敛：**提示语折叠 + 正文收 1 行**（缩略图获 ≈51px 可见高度）。
     收敛后复测：4 张卡全部 **240.0×200.0**、正文区裁切 **0px**、底栏贴底 ✓。

### 保留不变量（本次未动）

磁吸阈值 120/50/60/instant10 · 落位 `gap=-2` · 阻力三段式（30/50/0.28）·
跟手浮起 · 松手落座 `animateNodeTo(200ms)` + 强吸 `overshootPx(5)` · 整列让位 ·
Bond 判据（2px/40px）· 圆角 16 · 大圆角色块与选中态 · 交互分级 ·
`left`/`right` 单轴语义（09-18 修掉的「横吸 y 瞬移一整卡高」保留）。

### 验证表

| 检查 | 结果 |
|---|---|
| `vitest run` | **8 文件 76 例全绿**（含修订后的顶边对齐断言）。注：本沙箱下批量运行偶发只收集部分文件（vitest 写 `%TEMP%\…\ssr\` 模块缓存被文件代理拒绝，EPERM，**发生在 vitest 内部缓存写入、不是测试失败**）；实测拆批亦可累计全覆盖：批量 6 文件 46 例 + `stage3dPoseVideo` 18 例 + `comfyToCanvas` 12 例 = 76 例 |
| **渲染实测**（Edge 无头截图 + `getBoundingClientRect`） | 探针页引用真实 `novice-cards.css`，4 种卡片形态（空卡/典型/带缩略图/选中长文本）：全部 **240.0×200.0**、正文区裁切 **0px**、底栏贴底 ✓ |
| `tsc --noEmit` | **37 处** = `Stage3D.tsx` 16 + `riggedHumanoid.ts` 21（文档基线），**改动文件 0 命中** |
| `vite build` | ✓ built in 6.64s |
| 冻结区守卫 | `--update` 重锁后 **OK frozen zones intact (85 locks)** |
| 双库漂移 | **无新增**（`canvasVersion.ts` 已同步副库；一致 64 / 分叉 22 / 缺失 16 = 基线） |
| 副库 tsc | 54 行 / 6 文件（记录基线 55/7，未超） |
| 漂移清单核对 | = 本次 5 个改动文件 + 遗留 `styles.css`（`git diff` 证实与 HEAD 一致，属基线哈希过期，随本次重锁吸收） |

### 文档同步

`docs/knowledge/frozen_zones.json`（不变量 316 补固定高度、341 改写 top/bottom、
新增「卡片尺寸统一」条、reason 追加解冻记录）· `docs/现行技术文档.md` §5（文件数
29→33 修正 + 两条不变量更新）· `docs/_archive/knowledge/17-canvas-magnetic-invariants.md`
（新增第九节修订记录，并修正已失效的「bonds.ts 未登记」提示）。

### 已知未做 / 取舍

- 有缩略图的卡片：提示语折叠、正文收 1 行（实测驱动，非拍脑袋）——若希望
  「保留提示语、接受正文裁 1 行」，删掉两条 `:has()` 规则即可回退。
- 探针页（引用真实 CSS 的独立 HTML）为一次性验证工具，已删除；如需复测，
  重建方式见本轮做法：`novice-cards.css` + 4 种卡片 DOM + JS 测 `scrollHeight`。

---

## V4.38.5 (2026-09-23) — 引擎接口规范 + 错误码体系（规格书切片⑫·终篇）

> **收官**：异构动态协作引擎 12 切片全部落地。本版给引擎装上统一门面——
> 内外系统对接只认这一个入口、这一套错误码。

### 新模块：`app/core/ai/engine_api.py`（统一门面）

1. **四大标准接口**（第十篇）：
   - `create_task`：模块校验（未注册/暂停/不健康）→ DAG 提交（成环/幂等各自错误码）；
   - `submit_unit`：月账单耗尽**硬拒**（ERR_BUDGET_EXHAUSTED）→ 生成 →
     **归因五件套**（实际渠道 / 执行模式 / 模式计划 / 降级终态 / 融合溯源）；
   - `route_callback`：凭 unit_id 取回全归因（LRU 200 条）；
   - `resource_report`：L1 日预算 / L0 月账单 / 模块调度 / 抽检漂移**四视图**。
2. **统一响应信封**：`{ok, code, message, data}`；闭环冻结以 `frozen_note`
   提示（软提示不硬拒——生成是业务主链路，冻结只停先验回写）。
3. **错误码单一来源**：11 个 `ERR_*` 常量（禁裸字符串，同 agent_constants
   纪律），全部带人话标签，门面层把一切异常翻译成错误码。

### 规格书 14 篇完成度对照（12 切片，V4.37.4 ~ V4.38.5）

| 篇 | 内容 | 落点 |
|---|---|---|
| 一 总体架构 | 收益驱动统一目标函数 | V4.37.4 / 4.37.8 |
| 二 模块调度器 | 注册/配额/优先级/DAG | **V4.38.3** |
| 三 模型调度器 | 六模式/收益函数/投影 | **V4.37.8** |
| 四 A 探针 | 分歧度/自适应阈值/成本保护 | **V4.37.9** |
| 五 B 评分器 | 质量先验/真值观测 | V4.37.4 / 4.37.5 |
| 六 C PI 控制器 | 剩余法/抗卷绕/门控 | V4.37.7 / **4.38.1** |
| 七 多层级 λ | L0+L1/配额拍卖/共振抑制 | **V4.38.1** |
| 八 融合器 | 三分算子/Provenance | **V4.38.0** |
| 九 六级降级 | 六级+L3 降质重试 | V4.37.6 |
| 十 接口规范 | 四接口/信封/错误码 | **V4.38.5** |
| 十一 仿真器 | 五属性/四用途 | **V4.38.4** |
| 十二 落地路线 | 先修饱和振荡→收敛→多任务 | 全程按此序实施 |
| 十三 系统边界 | O(1) 红线/核心无 AI 推理 | 仿真器实测 <1ms |
| 十四 抽检子系统 | 抽样/预审/漂移/人工红线 | **V4.38.2** |

显性偏差（已在各自切片声明，非静默省略）：§6.5 进程级沙箱（桌面单进程
不落地）；§75 预审小模型/高阶大模型（规则层已就位，模型接入属后续
LLM provider 工程）；λ_l 延迟影子价格（接口预留，延迟观测源未接入）。

### 验证

`_verify/check_engine_api.py` **19 项全过**；`run_all_checks.py` 51 → **52 项**。

---

## V4.38.4 (2026-09-23) — 端到端仿真器（规格书切片⑪）

> **承上**：引擎九大部件全部就位。本版给整座引擎建「试飞风洞」——
> 不烧一分钱、不调一次网，把十种部件的协作跑给你看。

### 新模块：`app/core/ai/simulator.py`（纯模块）

**五属性全落地**（第十一篇原文逐条对账）：

| 规格属性 | 落地 |
|---|---|
| 同代码 | 直接驱动生产控制器（pacer/gprice/priors/probe/modes/sched/review），只替换模拟执行层 |
| 零成本 | 独立 tmp 存储（绝不碰 `data/*.json`），虚拟拍推控制器、不 sleep |
| 可复现 | `random.Random(seed)` + 报告指纹 digest |
| 可回归 | digest + 不变量断言直接进 `_verify` |
| 可故障注入 | 429 风暴 / 断网（观测门控）/ 超支 / 评分漂移 |

**四大用途**：参数标定（κ 三档 `parameter_sweep`）；收敛验证（λ 序列尾部
方差 <0.01）；多任务不变量（每轮拍卖 Σ≤剩余逐轮断言，零违反）；极限压力
（200 单元决策均时 **<1ms**，§69 O(1) 红线实测）。

### 踩坑（测试驱动抓获）

- **指纹里混进时钟**：首版 digest 含决策耗时（wall-clock）→ 同种子也不同
  指纹。「可复现」的边界 = 只覆盖引擎状态，时钟类字段必须排除。
- **漂移故障抽不到样**：2% 基础采样率下漂移标签不足 5 个、永不冻结——
  按 §76「分布外新题材强制必检」处理：漂移 = 分布外 → 强制全检，语义
  自洽且直接来自规格。

### 验证

`_verify/check_simulator.py` **17 项全过**；`run_all_checks.py` 50 → **51 项**。

---

## V4.38.3 (2026-09-23) — 模块调度器 DAG 核心（规格书切片⑩）

> **承上**：模型调度器（③~⑨切片）管「单元由谁执行」；本版补上规格书的
> 另一半——**模块调度器**管「哪个模块先跑、谁隔离、谁降级」（§4 两层严格边界）。

### 新模块：`app/core/ai/module_scheduler.py`（纯状态机，调用方驱动执行）

1. **模块注册中心**（§6.1）：能力 / 配额 / 健康度 / 暂停热更新。
2. **P0–P4 独立优先级队列**（§6.2）：依赖阻塞、暂停、取消、重试、
   **幂等键**去重（同 idem_key 二次提交返回 None）。
3. **优先级仲裁**（§6.3）：P0 画布预览 > P1 画布生成 > P2 AI 剪辑 >
   P3 视频音频生成 > P4 后台批量；高优可抢占低优运行中任务——
   **视频/长音频生成按 §13 不可抢占**（`non_preemptible` 双重拦截：
   `should_preempt` 判定 + `preempt` 执行都拦）。
4. **配额管理器**（§6.4）：单模块并发上限，占满不再出该模块任务、
   不影响其他模块独立配额。
5. **依赖 DAG**（§6.6）：拓扑就绪（blocked→ready）；提交时 DFS 环检测；
   **动态依赖失效降级**——上游 failed/cancelled，下游连锁 `skipped`
   且带人话理由（不静默照跑）。
6. **状态上报**（§7）：progress / by_status / degraded_tasks / modules。
7. 默认单例注册 §5.2 托管七模块（脚本解析/视频/音频/AI剪辑/画布/融合/转码）。

### 诚实边界（显性偏差声明）

§6.5 **进程级沙箱隔离**在桌面单进程应用不落地：模块以线程内执行体运行，
崩溃隔离由任务状态机（failed/重试）兜底——文档声明而非静默省略。
与 `pipeline_jobs` 的消费级对接属切片⑫（接口规范）。

### 验证

`_verify/check_module_scheduler.py` **32 项全过**；`run_all_checks.py` 49 → **50 项**。

---

## V4.38.2 (2026-09-23) — AI 辅助人工抽检子系统（规格书切片⑨）

> **承上**：机器评分只是低成本观测代理，不等于质量真值（§69 铁律）。
> 本版落地第十四篇——给整个闭环装上「人工刹车」。

### 新模块：`app/core/ai/sampling_review.py`（纯模块，RLock + JSON 原子写）

1. **自适应分层抽样**（§71.1）：`P = clamp(0.02×(1+4·r̂+2·Δ̂), 0.005, 1)`——
   预测残差大、分歧度高自动提采样率；新模型版本/新题材**强制必检**；
   `unit_id` 哈希**确定性抽样**（同单元永远同决定，可复现可审计）；
   24h prompt 签名去重（§71.5 重复样本过滤）。
2. **规则预审**（§71.2，确定性优先、零模型零成本）：文件缺失 / Schema 缺
   字段 → 高；体积 / 时长异常 → 中；灰区机器分 → `uncertain` 上交（识别
   不了不硬判——§75 小模型「存疑自动上送」精神的规则层落地）。
3. **预填表单**（§71.3）：机器分 / 分歧度 / 执行模式 / 模型版本 / 建议标签
   一次填好，人工只判 合格/存疑/不合格。
4. **漂移监控**（§71.4 + §29）：残差 EMA 均值 >0.15 → 告警（权重校正位）；
   **>0.30 → 冻结闭环 + 告警**；≥5 样本才判定（防小样本误冻结）。
5. **红线**（§72/§76）：`submit_ai_score` **永不写先验**（检查 C1 用计数
   writer 断言 0 次）；先验唯一写入通道 = `submit_human_label`；
   `unfreeze` 也只能人工触发，解冻重置残差基线。
6. **指标**（§74）：召回率 / 精确率 / 人工减负率 + 目标线（≥80% / 70~90%）。

### 接线（additive，旁路不阻塞）

- `pipeline._sampling_hook`：初检后计算 残差=|机器分−先验|、分歧=探针估计、
  prompt 签名去重 → 抽中即规则预审入池，高风险日志告警；
- `pipeline._record_quality_prior`：**冻结闸**——闭环冻结时机器观测停写
  先验（§29「冻结闭环、切静态降级」），仅人工标签可写、可解冻。

### 踩坑

- 默认 `prior_writer` 把 `record_outcome(ok=)` 写成 `success=`——参数名错
  被 except 静默吞掉，检查 G（人工标签必须真写进先验库）抓获。**静默
  except + 写错参数名 = 功能死了都不知道**，正是项目不变量 #9 的反面教材。

### 验证

`_verify/check_sampling_review.py` **31 项全过**；`run_all_checks.py` 48 → **49 项**。

---

## V4.38.1 (2026-09-23) — L0 全局价格层 + 配额拍卖（规格书切片⑧）

> **承上**：L1 任务层 λ（V4.37.7）只管单任务日预算。本版补全第七篇
> **多层级 λ 架构**：`λ_eff = λ^G + λ^τ`（§2 有效价格叠加规则）。

### 新模块：`app/core/ai/global_price.py`（纯模块，RLock + JSON 原子写）

1. **L0 全局层**（§2 职责表）：保障**月度账单上限**（默认 ¥500）；
   误差 = 全局剩余预算比 − 剩余时间比（只看全局账单，不看单任务——
   §41 第一件套「公共误差因子剥离」）；
   **积分主导慢环**（T=60s、Kp 0.1 < Ki 0.3，与 L1 比例主导快环
   **分层频域解耦**——第二件套）；**单步限幅 |Δλ^G| ≤ 0.1**（第三件套）。
2. **抗卷绕**（§34）：λ 停在界上**且原始目标越界**才冻结积分
   （限幅器会把 λ 拉下界——冻结只有把目标压在界外才观测得到，测试用
   `i_term=0.6` 积压构造，踩坑记录在案）。
3. **观测门控**（§35，两层同语义）：`set_observation(False)` 断网/暂停
   冻结 λ 更新；恢复首拍只建基线防阶跃。`budget_pacer` 同步补齐该接口。
4. **配额拍卖**（§39）：关键任务保底下界 → 欠账自动扣款（`report_task_spend`
   超配额记欠账）→ 余量按压力占比分配（高压优先）；
   **永久不变量 Σ 配额 ≤ 全局剩余**（assert 守护）。
5. **灵敏度归一化**（§33）：无量纲 κ 三档 {0.5, 1.0, 2.0} 整体缩放增益。

### 接线

- client 选路：`λ_eff = pacer.get_lambda() + global_price.get_lambda()`；
- `_record_spend`：同一笔花费两层各自记账（日窗/月窗各算各的误差）；
- 4 个旧检查脚本（PACER/QPRIOR/DEGRAD/FUSION）注入隔离 global，防污染真数据。

### 验证

`_verify/check_global_price.py` **24 项全过**（方向性 / 限幅 / 积分主导 /
撞界冻结 / 门控恢复 / 拍卖四规则 / λ_eff 改变路由 / 跨月回退）；
`run_all_checks.py` 47 → **48 项**。

---

## V4.38.0 (2026-09-23) — 置信度融合器三分 + D 双路执行体（规格书切片⑦）

> **承上**：切片⑤定义六模式、切片⑥给 D 装上守门探针。本版让 **D 真正可执行**：
> 双路出活 → 实测分歧 → 三分融合 → 全程溯源。

### 新模块：`app/core/ai/fusion.py`（纯模块）

铁律（§42）：**禁止通用张量加权平均**——三介质独立算子，均返回
`(result, provenance)`：

1. **文本 = 字段锁域 + 命名空间仲裁**：`locks={字段: 锁域}` 不可翻越；
   未锁字段给了逐字段质量分按分择优（优先于命名空间优先级）；
   溯源逐字段记 `lock/score/priority/only` 规则。
2. **视频 = 关键帧择优 + 片段时序拼接**：同槽多来源按质量分择优，
   `keyframe_ok=False` 先 ×0.7 降权**且不享受 prefer 让步**（关键帧择优 >
   稳定偏好）；差 <0.05 让给 prefer 防逐槽抖源；输出按 slot 升序的
   **拼接计划**（纯决策不碰文件，ffmpeg 拼接由调用方执行）。
3. **音频 = 轨道分离混音 + 响度对齐**：角色基础增益（人声 1.0 / 音效 0.7 /
   配乐 0.5）；单轨 峰值×增益 > target_peak 压回（防爆音）；总线 >1 等比压缩；
   溯源记 `pre_bus_gain` + 压总线后 `final_gain`（与计划一致）。

### D 双路执行体（`video_generation_client._execute_dual`）

- `generate()` 新 additive 参数：`mode="D"` 显式强制 / `allow_dual=True`
  且模式计划选中 D（探针已判候选）自动触发。**默认关**——双路=双倍云端花费。
- 顺序双路（本地占位秒出先跑，云端后跑）→ 分歧实测（探针成本门控内入库）→
  逐槽融合（云端质量=先验 route_mean，本地占位 0.3）→ 溯源存 `last_fusion()`。
- 云端失败**诚实退化**：实际模式记 `C→L` + L6，不冒充 D 交付。
- 记账齐全：先验回写 / 花费记账 / 额度池上报 / 降级统计。

### 踩坑（测试驱动抓获）

- 端到端首跑 D 没触发：收益排序第一名随先验/λ 浮动（实测 seedance 排前），
  测试只给 dashscope 注假实现 → `first_real` 拿不到云端。**三渠道全注入 +
  先验库一并隔离**。
- 稳定偏好会让关键帧崩坏的云端「让回去」——修规则：broken 候选不享受让步。

### 验证

`_verify/check_fusion.py` **28 项全过**；`run_all_checks.py` 46 → **47 项**。

---

## V4.37.9 (2026-09-23) — A 模块分歧度探针（规格书切片⑥）

> **承上**：切片⑤把「谁执行」形式化为六模式。本版落地第四篇——
> **D 模式的守门员**：分歧度不够，双路就是浪费钱。

### 新模块：`app/core/ai/divergence_probe.py`（纯模块，RLock + JSON 原子写）

1. **定位红线**（§16）：量化本地/云端输出差异 Δ，**仅筛 D 候选、不改收益打分**
   ——删候选走投影层（§12 正交），理由带「探针：」前缀，归因可查。
2. **分介质独立指标**（§17，杜绝跨介质混用）：
   - 文本：结构化字段差异率（dict 并集比对 / 字符串按行比对）；
   - 视频/音频：确定性廉价代理 = 内容哈希 0.6 + 体积相对差 0.25 + 时长相对差 0.15
     （前 64KB 采样控成本；诚实边界=粗代理，升级真感知指标换函数即可、调用方零改动）。
3. **自适应阈值**（§16.3）：`τ = clamp(0.5 − (var_q + var_Δ), 0.15, 0.8)`——
   质量方差/分歧方差越大，阈值越低，越容易开启双路校验。
4. **D 开启条件**（§16.4）：`Δ > τ`；`delta=None` 时复用 EMA 估计（抽样探针语义）。
5. **成本保护**（§16.1/§18）：累计探针成本 ≤ 2% 累计单元成本；超限拒绝并给出
   「降级抽样探针」人话理由；冷启动（无成本基数）放行首次。
6. **分歧入库**（§19）：EMA 均值/方差滑更（α=0.3，与 quality_prior 同形式），
   持久化 `data/divergence_probe.json`，损坏容错。

### 接线（additive）

- `client` 模式计划新增 `probe` 裁决字段（delta/threshold/reason/estimated）；
  非候选时 D 被投影删除、理由 `探针：Δ=…≤τ=…`。
- `_record_spend` 顺带把单元成本喂给探针预算分母（`note_unit_cost`）。

### 验证

`_verify/check_divergence_probe.py` **32 项全过**；`run_all_checks.py` 45 → **46 项**。

---

## V4.37.8 (2026-09-23) — 六种执行模式 + 可行集投影（规格书切片⑤）

> **承上**：切片④把 λ 变成连续调节的影子价格。本版落地第三篇核心抽象——
> 「单元由谁执行」从隐式的 provider 链升级为**六模式收益决策 + 可归因投影**。

### 新模块：`app/core/ai/execution_modes.py`（纯模块，不 import app 包）

1. **六枚举**（§10）：`L / C / D / L→C / C→L / SkipMerge`，各带人话标签。
2. **定稿收益函数**（§11 v4.1）：`V = q̂ − λ_c·(ĉ−c_base) − λ_l·(l̂−l_base) − κ_sw·1{switch}`
   - **基线锚点写死为本地**：本地模式惩罚恒 0（测试 A1/A2 断言 λ 任意变本地分不动）；
     宽松预算下系统自然收敛本地，从根上杜绝 v4.0 的 D 模式泛滥 / λ 顶饱和。
   - 融合质量上界 `q_D = 1−(1−q_L)(1−q_C)`（独立误差「两路都错才错」）。
   - `L→C` / `C→L` 按达标概率求期望值；`SkipMerge` = 单路直出省融合算力奖励。
3. **可行集投影正交铁律**（§12）：打分层纯收益最大化；投影层**只删除**不可行
   选项、**绝不修改打分**（检查 E1 用快照断言守护）；删除项必须带人话理由；
   全删光回退本地锚点 L。`collect_infeasible` 把断网 / 无云端 key / 显存不足
   翻译成模式删除清单（断网删全部含云模式；无 key 仍留 C→L 回退语义）。
4. **完整归因**：`choose_mode` 返回 {mode, scores, kept, dropped+理由, baseline, λ…}，
   日志可完全归因、闭环可解释（§12 核心目的）。

### 接线（additive，执行语义不变）

- `video_generation_client._resolve_provider_order`：选路时用先验 + 动态 λ 产出
  **模式计划**存 TLS（`last_mode_plan()`）；`generate()` 末尾记录**实际执行模式**
  （`last_execution_mode()`：C / C→L / L）——计划 vs 实际偏差可审计。
- 既有 provider 链的执行语义就是 C→L（云端优先失败回退本地），本版只把它
  **显式化、可归因化**；D 双路执行体在切片⑦（融合器）接线。

### 验证

`_verify/check_execution_modes.py` **28 项全过**（基线锚点 / 增量成本语义 /
融合上界 / 切换成本 / 投影不改分快照 / 硬约束采集 / 端到端归因）。
`run_all_checks.py` 44 → **45 项**。

---

## V4.37.7 (2026-09-23) — PI 预算影子价格控制器（规格书切片④ C 模块）

> **承上**：切片①②③建成「先验+收益路由+真值回写+六级降级」闭环。
> 本版补上规格书的控制器核心——**λ 从写死的 0.2 变成连续调节的影子价格**
> （规格书：静态 λ 是 v4.0 的根本缺陷，长期饱和）。

### 一、新模块 `app/core/ai/budget_pacer.py`（纯模块）

| 件 | 落地 |
|---|---|
| 误差信号（§31 剩余法） | `e = 剩余预算比 − 剩余时间比`（无量纲，天然归一化）；e<0=超支趋势 |
| PI 迭代（§32） | 比例与积分**都作用于 −e**：超支 → λ 升（偏好便宜渠道）；富余 → λ 降（偏好质量渠道） |
| 抗卷绕（§34） | λ∈[0.05, 1.0] 钳位；**撞界冻结积分**（e_prev 不更新，阻断继续累积） |
| 观测门控（§35） | 30s 最小更新周期，间隔不足直接返回当前 λ；**首读只建误差基线不动作**（防启动比例踢） |
| 跨日结转（§35 恢复） | 自然日滚动：预算重置 + **λ 指数回退 ×0.5**（不清零，杜绝阶跃抖动） |
| 持久化 | JSON 原子写 `data/budget_pacer.json`；损坏容错；异常绝不抛出 |

默认日预算 ¥50（`set_budget` 可调）；初始 λ=0.2 无缝接管原静态值。

### 二、接线（additive，全部向后兼容）

- `provider_caps.resolve_order` 加可选 `lambda_price` 参数（不传 → 静态 0.2 兜底）；
- `video_generation_client` 选路时传 `pacer.get_lambda()`；控制器挂了自动回静态；
- 真实渠道成功按 `price_per_clip × 段数` 记账（local 免费不记；金额是声明表估算单价，
  账单真值回写属后续 A2 方向）。

### 三、端到端证据（检查脚本实测）

同一个先验库（dashscope 0.6 / seedance 0.55）：
**λ=0.05（预算富余）→ 贵而好的 dashscope 排前；λ=1.0（预算紧张）→ 被反超**——
预算松紧直接改变路由决策，这就是规格书「影子价格」的物理意义：
*每牺牲 1 单位质量，愿意换取多少成本节省*。

### 四、踩坑（测试驱动抓获）

1. **比例项符号写反**（超支反而 λ 降）——方向性测试抓获；
2. **首读 e_prev=0 的比例踢**（λ 一启动就阶跃）——加「首读只建基线」语义；
3. QPRIOR/DEGRAD 检查会写真 `data/budget_pacer.json`——同步注入隔离 pacer。

### 五、验证

- 新增 `_verify/check_budget_pacer.py`（**20 项全过**）：误差方向/PI 双向调节/
  抗卷绕冻结/观测门控/跨日回退/持久化/端到端路由切换 + 花费记账；
- 注册 run_all_checks（**43→44 项**）。

### 六、规格书切片进度（全四片完成）

① 质量先验+收益路由 V4.37.4 → ② 真值观测 V4.37.5 → ③ 六级降级 V4.37.6 →
**④ PI 预算控制 V4.37.7**。至此规格书的「收益函数 + 先验 + 降级 + 价格控制」
核心闭环全部落地；剩余为更大件（模块调度器 DAG、双路 D 模式、仿真器、抽检子系统），
建议按项目北极星（先剪辑后 AI 闭环）排期。

---

## V4.37.6 (2026-09-23) — 六级降级体系 + L3 降质重试（规格书切片③）

> **承上**：切片①②建成「先验+收益路由+真值回写」闭环。本版把规格书 §44-46
> 的**六级降级**形式化——降级从「静默兜底」变成「可观测状态」，
> 并新增一个真实行为：L3 质量降级重试。

### 一、新模块 `app/core/ai/degradation.py`

| 级别 | 规格定义 | 本项目落地 | 状态 |
|---|---|---|---|
| L0 | 完整交付（观测用） | 首选渠道按原规格出齐 | ✅ |
| L1 | 双路降级 | 无双路模式 | 🔲 预留 |
| L2 | 云端降级 | provider 回退链/模型降档 | ✅ |
| L3 | 质量降级 | **资源类失败 → 480p 重试一次** | ✅ 新增真实行为 |
| L4 | 功能降级 | 暂无可砍环节 | 🔲 预留 |
| L5 | 部分交付 | 段数 < 请求数检出 | ✅ |
| L6 | 失败兜底 | 本地占位生成 | ✅ |

- `classify_error` 失败四分类：**resource**（超时/OOM/429/限流——降质可能救回来）/
  auth / model（降质无意义，直接兜底）/ unknown；
- `DegradationSession` 轨迹 + 终态取最严重（6>5>4>3>2>1>0）；
- 24h 滚动统计：各级计数 / degradation_rate / worst_level（与 llm_fallback_stats 同款纪律）。

### 二、L3 质量降级（新增真实行为，成本封顶）

全部真实渠道失败 + 含资源类错误 + 原请求 >480p ⇒ 本地兜底**之前**用首个真实渠道
480p 重试**一次**（只试一次、只降一档）。认证/模型类失败不触发（降了也白降）。

### 三、关键修正（测试驱动发现）

**local 占位实际在 provider 链循环内交付**（不在循环后兜底块）——首版把 L6 标记
和 L3 重试放在循环后，实测四种终态全错。修正：L3 重试移到「local 尝试之前」，
L6 标记移到链内 local 成功分支；循环后兜底块降为安全网（local 返回空/链中无 local）。
另：显式 `provider="local"` 是用户主动选择，**不算降级**（规格：降级是被动行为）。

### 四、可观测性

- `video_generation_client.last_degradation()`：本线程最近一次的降级终态
  （level/level_name/level_label/events）——Agent 能回答「这次降到哪一级」；
- 终态进全局统计：能回答「最近 24h 降级率、哪级最频繁」。

### 五、验证

- 新增 `_verify/check_degradation.py`（**33 项全过**）：级别优先级/分类器八例/统计/
  端到端五种终态（L0/L2/L3/L5/L6）/ 显式 local 豁免；
- 注册 run_all_checks（**42→43 项**）。

---

## V4.37.5 (2026-09-23) — 真值质量观测回写（规格书切片② B 模块评分器）

> **承上**：V4.37.4 落地了先验库 + 收益路由，但样本只是「执行成败」（可用性）。
> 本版把**真值质量观测**接进同一条通道——规格书 B 模块评分器的最小落地。

### 一、观测器即初检

`ai_video_generation_pipeline._generate_and_inspect` 的**初检（+守护质检）就是本项目
已有的质量观测器**：通过/未过即真值样本，经新纯函数
`quality_prior.quality_from_inspection` 映射后写入 `quality` 桶：

| 初检结论 | 样本 | 理由 |
|---|---|---|
| 通过 | 1.0 | 质量达标 |
| 未过 | 0.3 | 内容生成了但质量不达标（非零——区别于「根本没生成」的 0.0） |
| 跳过 | **None 不记录** | 观测门控（规格 §35）：无有效观测不污染先验 |

### 二、渠道归因（Provenance）

`provider="auto"` 时实际渠道在 client 内部解析，管线层不知道用了谁——
新增**线程局部归因**：`video_generation_client.last_used_provider()`，
生成成功/兜底时在本线程盖章，管线同线程读取；多并发生成任务互不串扰。
`local` 占位仍不产生质量信号（与可用性回写同一条纪律）。

### 三、真值接管路由（route_mean）

`quality_prior.route_mean(provider)`：**quality 真值桶优先** → default 可用性桶兜底
→ 无数据中性 0.5。选路的 priors 构建切换为 route_mean——**真值一记录就自动接管
路由，可用性信号退居兜底，路由代码零改动**（V4.37.4 预留的通道兑现）。

### 四、验证

- `check_quality_prior_routing` **28→41 项全过**（新增四组：观测映射/桶优先级/
  TLS 归因/管线静态接线文本断言）；全量回归 42 项除已知 GUARD 基线外全绿。

---

## V4.37.4 (2026-09-23) — 质量先验库 + 收益函数选路（规格书切片①）

> **触发**：用户提供《异构动态协作引擎 — 完整开发规格说明书》v4.3（微信附件），
> 指令「优化进项目里面」。策略：**最小可行切片**——取规格书 §11（收益函数）、
> §14（质量先验库）、§39（冷启动不确定度）三段思想落地，与现有 provider 体系对接。

### 一、新模块 `app/core/ai/quality_prior.py`（质量先验库）

| 项 | 内容 |
|---|---|
| 分桶 | (provider, kind) 键，kind 预留介质/模型版本分桶（默认 default） |
| EMA | mean += α·(x−mean)，var = (1−α)·(var + α·δ²)，α=0.3；样本夹紧 [0,1] |
| 冷启动 | 首样本 var=0.25；`inherit()` 新桶继承均值、方差×4（规格 §39 不确定度） |
| 持久化 | JSON + 原子写（tempfile+os.replace）到 `data/quality_prior.json`；损坏文件按空库启动 |
| 纪律 | 纯模块不 import app 包；记录异常绝不抛出（不拖垮生成主链路）；**RLock**——首版 Lock 嵌套 `_ensure_loaded` 自我死锁（SIGTERM 挂死），与 `_clips_lock` 同款约束，已修 |

### 二、收益函数选路（provider_caps）

- `resolve_order` 加可选 `priors: Dict[str, float]` 参数（**additive 向后兼容**）：
  给了先验 → `V = q̂ − λ_c·price` 排序（λ_c=0.2，「每元愿牺牲多少期望质量」）；
  q̂ 缺失用中性 0.5（冷启动探索位）；tier 做平局 tiebreak；不给 → 旧 tier 降序不变。
- `local` 永远兜底、显式 provider 路径、quote() 行为均不受影响。

### 三、闭环回写（video_generation_client）

- 每次生成成败后 `_record_prior` 回写先验（成功 1.0 / 失败 0.0）；
  **local 占位不记录**（占位成功 ≠ 质量信号）；先验库异常静默降级。
- 选路时从先验库快照构建 priors 传入 resolve_order；先验库为空自动退回 tier 排序。
- **诚实边界**：当前样本是执行成败（可用性先验）；待 B 模块评分器接入后
  `record_outcome(quality=五维分)` 直接改喂真值，路由零改动——通道已就位。

### 四、验证

- 新增 `_verify/check_quality_prior_routing.py`（**28 项全过**）：EMA 数学精确值断言
  （0.7/0.385）、样本夹紧、inherit 三性质、原子写+重载+损坏容错、λ_c 常量、
  priors 反超排序（seedance 0.9 反杀 dashscope）、向后兼容、端到端假 provider
  成败回写、local 门控。
- 注册 run_all_checks（**41→42 项**），全量回归除已知 GUARD 基线外全绿。

### 五、踩坑记录

- **threading.Lock 嵌套持锁 = 自我死锁**：record 持锁调 `_ensure_loaded`（也持锁），
  进程挂死零输出（SIGTERM）。定位手法：`-u` 无缓冲仍零输出 ⇒ 挂在第一个 print 之前。
  修法同 `_clips_lock`：RLock。

---

## V4.37.3 (2026-09-22) — 云端视频渠道接线：DashScope 万相（探测 + 掌控验证）

> **触发**：用户要求「找免费视频生成 API + 测云端可用性 + 测渠道掌控」。
> 结论：**不需要第三方集成站**——项目已有的 `DASHSCOPE_API_KEY`（阿里云百炼）
> 自带万相文生视频，key 已实测有效；缺的最后一步是控制台开通模型（需用户手动）。

### 一、渠道调研与选型

- 国际站（fal.ai $10 / LinkModel 16 段 Kling / Runway 125 credit）：要海外卡、有墙、额度一次性；
- **阿里云百炼（选型胜出）**：国内直连、万相（Wan）系列、新账号免费 50s 视频/90 天
  （仅北京地域）、项目 key 从 2026-04 起就在 `API Keys.env`（该文件已于前一提交停止 git 跟踪）。

### 二、新模块 `app/core/ai/dashscope_video.py`（纯模块，不 import app 包）

| 项 | 内容 |
|---|---|
| 协议 | legacy 异步：POST `video-synthesis`（`X-DashScope-Async: enable`）→ GET `tasks/{id}` 轮询（5s 间隔/360s 超时）→ SUCCEEDED 后**当场下载**（video_url 24h 有效不缓存） |
| 模型回退链 | `wan2.2-t2v-flash` → `wanx2.1-t2v-turbo` → `wanx2.1-t2v-plus`（命名坑：**wan2.1 系带 x**，官方模型广场核对） |
| 降档判定 | `_is_model_error` 含 `Model not exist / 无权限 / AccessDenied`——实测老账号对未开通模型返 **403 AccessDenied**（≠ key 失效） |
| 零成本探测 | `probe()`：用非法模型名触发 400——拿到结构化错误即证明认证+端点通（实测 PASS） |
| 诚实降级 | 认证失败/额度耗尽/超时 → 抛 RuntimeError 带平台原始 message，由额度池记账，不静默 |

### 三、三处接线（渠道掌控的实体层）

1. `provider_caps.py`：声明表加 `dashscope`（t2v=True / i2v·kf2v 暂 False 待接线 / 5s 段 /
   480p-1080p / tier 1 / 估价 ¥1.5/段）+ `DEFAULT_REAL_ORDER` 排首位（唯一有模块+key 的渠道）；
2. `video_generation_client.py`：`_load_dashscope` 延迟加载（**key 缺失返回 None 自动跳过**，
   省一次注定失败的 HTTP 往返）+ `list_providers` 展示行；
3. `provider_pool.py`：降级回退顺序表补 dashscope。

### 四、实测结果（三个证据）

| 测试 | 结果 | 证据 |
|---|---|---|
| 零成本探测 | ✅ 通 | 非法模型 → `400 InvalidParameter: Model not exist`（认证+端点可达） |
| 鉴别诊断 | ✅ 账号健康 | `qwen-turbo` 文本调用成功（说明不是 key 失效/欠费/百炼未开通） |
| 真实生成 | ❌ 模型未开通 | 三个模型 ID 全 `403 AccessDenied` → **需用户在百炼控制台模型广场开通 wan2.2-t2v-flash**（开通即送 50s/90 天免费额度） |

### 五、渠道掌控验证（`app/temp/test_channel_control.py`，20 项全过）

- **A 能力路由**：auto 文生视频首选 dashscope、报价 ¥1.5×段、i2v 请求正确筛除（人话理由）；
- **B 延迟加载**：handler 可用、list_providers 带 caps/单价；
- **C 额度池记账**：credential 掩码、健康号可选中、三连败进冷却退避；
- **D 端到端回退**：真实 403 被记录 → 无中断降级 seedance/cogvideo（缺模块跳过）→ **本地占位照常出片**（掌控链不中断的核心证据）。

### 六、教训（同一文件并行 Edit = 丢失更新）

本次三次踩中：同文件两个 Edit 并行执行时后写覆盖前写（`provider_caps` 声明表丢失、
`_load_dashscope` 方法体丢失、检查断言丢失）。**同一文件的多处修改必须串行发送。**

### 七、验证

- `check_provider_caps` 24 项 / `check_quote_health` 30 项全过（断言随渠道表更新）；
- `run_all_checks` 41 项中除已知基线 GUARD/styles.css 外全过。

---

## V4.37.2 (2026-09-22) — 撤销反馈回路 + LLM 降级指标化（报告 B1 + A4）

> **触发**：《2026-09-22 bug猎捕与优化方向报告》建议的下一批。B1 是把用户每天的
> 撤销行为变成免费训练数据；A4 是把「质量在暗处打折」变成数字。不触碰冻结区。

### 一、B1 撤销反馈回路（用户 Ctrl+Z = 最诚实的负反馈）

| 项 | 内容 |
|---|---|
| 问题 | Agent 的 Hebbian 学习（成功+Δ/失败-Δ）已就位，但异常路径之外**没有任何负反馈信号源**——用户撤销 Agent 操作时，这个最强信号白白流失，Agent 下次还犯 |
| 方案 | **来源标记 → 盖章 → 撤销钩子**三段式：① 新模块 `app/core/agent_origin.py`（线程局部 `agent_origin_scope`，不 import app 包）；② `capability_dispatcher.invoke` 用 scope 包住 handler 执行——handler 内落到撤销栈的任何动作都算 Agent 来源（含委托链 `_resize_clip`/`move_clip`）；③ `EditorModule._record_action` 盖 `origin` 章（agent/user） |
| 撤销/重做 | `_undo` 撤到 agent 动作 → `_on_agent_action_undone` 触发 Hebbian 弱化（quality/medium），提示语标注「Agent 操作 · 已反馈学习」；`_redo` → `_on_agent_action_redone` 收回负反馈（净学习量归零） |
| 精确打击 | 新增 `_infer_agent_action_capabilities`：把撤销栈动作映射回具体 capability——label 关键词 > type 关键词 > `edit_clip` 的 before/after diff（start_time 变→move / duration 变→trim / 其他→properties）> compound 步骤递归；映射不出走文本推断兜底 |
| 兼容 | `_agent_brain_learn` 加可选 `related` 覆写参数（不传行为不变）；线程局部保证 Agent 能力与用户 UI 操作并发时互不污染 |

### 二、A4 LLM 降级指标化（降级不再是暗处打折）

| 项 | 内容 |
|---|---|
| 问题 | LLM 优先 + 关键词降级（8 维情绪向量，`drama_understanding_engine.py`）在 LLM 不可用时静默降级——功能没断、质量打折，且无任何指标能回答「最近降级了多少次」 |
| 方案 | 新模块 `app/core/ai/llm_fallback_stats.py`：纯内存滚动窗口（24h，deque+锁，5000 条上限），`record(site, degraded, reason)` / `summary()`；记录失败绝不抛出（指标不拖垮主链路） |
| 埋点 | `_get_emotion_vector` 三处：LLM 成功（degraded=False）/ LLM 异常（reason=llm_error:类型）/ 未探测（reason=ollama_not_probed） |
| Agent 暴露 | 新只读能力 `pipeline.llm_health`（safe/left）四处接线：各站点近 24h 尝试数/降级数/降级率/最近原因 + 最差站点；高降级率 = 该查 Ollama/模型渠道 |

### 三、验证与回归资产

- 新增 `_verify/check_undo_feedback_llm_health.py`（**31 项**，已注册 run_all_checks → **40 项**）：
  agent_origin 作用域/嵌套/线程隔离 · editor 静态接线断言 · `_infer_agent_action_capabilities`
  推断矩阵（AST 提取动态测试，不 import Qt 重模块）· fake brain 捕获 feedback ·
  llm_fallback_stats 统计/窗口裁剪/重置 · 情绪向量三埋点 · pipeline.llm_health 四处接线 + invoke 真跑
- `py_compile` 八文件全过 · 冻结区唯一漂移仍为已知历史项（styles.css，待决策）

---

## V4.37.1 (2026-09-22) — 全库 bug 猎捕 · AST 作用域扫描入回归

> **触发**：用户要求「抓取项目里存在的 bug + 深度思考算法优化与能力迭代方向」。
> 产出：`docs/_reports/2026-09-22-bug猎捕与优化方向.md`。

### 一、新增：AST 作用域扫描器（防 NameError 类硬缺陷）

- `_verify/scan_nameerror_scope.py`：真词法作用域链 Frame（非扁平集合）；
  `global`/`nonlocal` 只在本 frame 收；推导式**最外层 iter** 按外围作用域判定
  （`{e: i for i, e in enumerate(D)}` 合法 / `[D[0] for _ in range(1)]` NameError）；
  读文件 `utf-8-sig`；含 `import *` 文件跳过并列出；模块级「使用先于赋值」单独检测。
  命中时退出码 1。
- `_verify/selftest_scan_nameerror_scope.py`：10 个合成用例正反双向验证检测能力
  （5 阳性必命中 + 5 阴性必静默）——扫描器报 0 时靠它反证「不是检测器瞎了」。
- **全库结果：386 个 .py，SCOPE 0 命中 / ORDER 0 命中 / 跳过 0**——
  一跑就崩的 NameError 类硬缺陷为零。
- 已注册进 `run_all_checks`（SCOPE 项，38→**39 项**），防未来回归。

### 二、修复：2 处违反不变量 #9 的静默 except

| 位置 | 问题 | 修复 |
|---|---|---|
| `app/core/agent_runtime.py:169` | **状态机** `agent_tasks.transition(task_id, RUNNING)` 失败静默 `pass`——状态机路径按纪律必须 `logger.debug(exc_info=True)` | 已补 |
| `app/modules/lego/editor_module.py:8182`（`agent_apply_storyboard_durations`） | `out_point` 联动失败静默——`duration` 已改而 `out_point` 未同步会留**数据不一致**；同函数 `:8188` 本就有正确写法 | 已补 `logger.debug` |

> 语义级扫描全量：P1 可变默认参数 **0** · P2 裸 except **0** · P3 静默吞没 **127 处**
> （抽查 8 处高风险：除上述 2 处外，其余为幂等 unregister / 二次异常兜底 / UI 绘制 /
> 清理兜底 / 回调隔离等可接受模式；完整分级见报告）。

### 验证

`py_compile` 双过 · STORYAPPLY **17/17** · 扫描器自测 **10/10** · 全库扫描 EXIT=0 ·
`run_all_checks` 39 项除已知历史项（GUARD/styles.css 基线漂移，待决策）外全通过。

---

## V4.37.0 (2026-09-21) — 异步任务模型：submit / status / cancel（P1-3）

> **触发**：升级任务清单第 3 批首项。全链路执行从「一发不可取消的阻塞调用」
> 升级为「可查询、可取消的后台任务」。核心改动在 `app/core/ai/pipeline_jobs.py`
>（新）+ 三处 catch-all 放行 + Agent 三能力 + 面板任务化，不触碰冻结区。

### 一、复用而非重建（`app/core/ai/pipeline_jobs.py` 新模块）

| 项 | 内容 |
|---|---|
| 问题 | 全链路 `run_full` 经 `invoke_async` 起一个裸线程跑到黑：无任务号、无状态查询、无取消；长视频期间用户只能干等 |
| 方案 | 任务表**直接复用 `canvas_gen_jobs`**（画布生图/生视频/生音频同一张表）——状态机/协作式取消/诚实进度/并发限流/终态裁剪零重复造，Agent 与画布统一任务视图（`kind="pipeline"`） |
| API | `submit_full_pipeline`（立即返回任务快照）/ `job_status`（单查 done 附完整结果 = fetch 语义；列表模式带队列统计）/ `fetch_result` / `cancel_job` |
| 语义 | 预览等待不是失败：任务 `done + paused=True`，等用户确认后**提交新任务**续跑；`max_attempts` 恒 1（管线级自动重试 = 双倍花钱，重试交给段内回溯 + 额度池换号）；全链路失败时详细 output 按任务层语义丢弃、error 经 message 保留（与旧路径口径一致） |

### 二、取消穿透到生成深处（协作式令牌）

- 取消令牌经**线程局部**注入（gen-jobs 工作线程绑定），任务体同线程直连
  `orchestrator.execute` → `pipeline.execute` → `client.generate`（全程无再分叉），
  深处检查点天然生效：
  - `client.generate`：入口 / provider 尝试之间 / 占位生成段与段之间
  - `pipeline.execute`：场景与场景之间 / 回溯重试之间
- **三处 catch-all 放行 `except GenCancelled: raise`**（client / orchestrator / dispatcher）——
  取消是控制流不是执行失败；无令牌的旧调用方零影响（独立加载场景空元组兜底永不匹配）
- 诚实降级：正在跑的单段（一次阻塞调用）不打断，跑完即止；取消后**结果一律丢弃不落盘**

### 三、进度上报零签名改动

- `StageReporter` 同样线程局部注入，`pipeline.execute` 深处经 `pipeline_stage()`
  （创意拆解 / 生成片段 i/N）/ `pipeline_progress()`（真实完成数百分比）上报；
  orchestrator / dispatcher / 管线签名一个都不用改；拿不到真信号不伪造平滑条

### 四、Agent 三能力（四处接线）

| 能力 | effect/paid | 动作 | 危险级 |
|---|---|---|---|
| `pipeline.submit` | file_write / paid | `submit_pipeline` | **dangerous**（生成线花钱，须用户确认——与 P1-1 成本确认同一哲学） |
| `pipeline.job_status` | read / 免费 | `job_status` | safe（单查+列表+队列统计） |
| `pipeline.job_cancel` | read / 免费 | `job_cancel` | safe（排队真取消；运行中段间生效） |

### 五、面板任务化（`editor_agent_panel_mixin.py`）

- 全链路按钮（含「确认预览并继续」分支）改走 `submit_full_pipeline` + QTimer 1s 轮询；
  新增「⏹ 取消」按钮（仅任务运行期可见，主题样式 `btn_danger`）
- 轮询只管终态判定（进度/阶段仍由 orchestrator→EventBus 实时驱动，两套信号不打架）；
  终态统一回 `_on_full_pipeline_done`（消息口径不变）
- 预览等待不再误报 ❌ 失败（paused 安静收尾，⏸️ 消息已由事件发出）
- 单任务守卫：已有任务在跑时拒绝重复启动，提示先取消

### 六、验证

- 新增 `_verify/check_pipeline_jobs.py` **39 项全过**：提交即返/中间态可见/终态语义/
  fetch/失败丢弃不重试/预览等待 paused/运行中取消/终态幂等/**取消穿透
  client.generate 与 pipeline.execute 两层深度**（假 provider 模拟阻塞调用）/
  统一任务表/三能力四处接线/面板接线
- `run_all_checks` 37 → **38 项**；除已知历史项（GUARD/styles.css 基线漂移，与 HEAD
  零差异，待你决策是否 `--update` 重锁）外全通过
- 任务体绕过 dispatcher 直连 orchestrator 的原因已写进模块 docstring：
  dispatcher 的 catch-all 会吞取消（虽已补放行，仍取最短路径）；
  提交动作本身（pipeline.submit）在 Agent 侧已过 policy 门

## V4.36.0 (2026-09-21) — 生成前报价 + 渠道健康灯（P1-1 / P1-2）

> **触发**：升级任务清单第 2 批。花多少钱、死没死号，生成前一眼可见。
> 全部改动在 `app/core/ai/` + Agent 接线 + 面板 UI，不触碰冻结区。

### 一、三层报价（P1-1 `quote`）

| 层 | 模块 | 职责 |
|---|---|---|
| ① 声明层 | `provider_caps.quote()` | `price_per_clip × 段数`，纯声明估算（seedance 1.0 / cogvideo 0.8 / local 0.0 元/段） |
| ② 账号层 | `provider_pool.quote()` | 谁接单：健康账号→有号；账号全灭→死号跳过；无账号→环境变量兜底；**`remember=False` 试演语义，不占 `_last_pick` 记账位**（避免并发生成把成功/失败记到报价头上）；pool 改选 provider 时单价随之重算 |
| ③ 客户端层 | `video_generation_client.quote()` | 叠加 **handler 可用性修正**（镜像 generate() 实际循环）：选中渠道无 handler 时沿 fallback 链找第一个真可用的，找不到诚实降级 local ¥0 |

**报价 = 生成会真实发生的事**：选谁、花多少、还剩多少配额、死号有哪些，一次问清。

### 二、管线与 Agent 接线

- `GenerationPipelineResult` 新增 `cost_estimate` 字段；生成循环前报价并 `logger.info` 审计（`生成前报价：xxx × N 段 ≈ ¥X.XX`）
- generate 输出附带 `cost_estimate`
- **`pipeline.quote` 四处接线**（catalog 表 / capability_handlers / 动作表 `quote_cost` / 帮助块参数行），Agent 可答「这次要花多少钱」「还有多少额度」；**只读不生成**
- `list_providers()` 每行新增 `price_per_clip` + `health`

### 三、UI：成本确认 + 健康灯（P1-2）

- **成本确认弹窗**（`_on_run_full_pipeline`，主线程、worker 启动前）：仅生成线（无素材+有简报）且预估 ¥>0 时弹出，**默认「否」**；取消 → `🛑 已取消生成（预估 ¥X，未产生任何花费）`；报价失败不阻塞生成（仅 debug 日志）
- **健康灯**（`_refresh_provider_status` 重写）：
  - auto：云端渠道清单 + 预计 ¥X
  - local：灰字 + 免费
  - 显式渠道：健康（含配额余量）/ 异常（原因 + 降级链提示）三级态
  - **死渠道下拉项变灰不可选**（`QStandardItemModel.item().setEnabled(False)`）：无 handler 或账号全不健康即判死；auto/local 永不禁用
- 主题纪律：`_agent_panel_styles()` 新增 `status_ok/status_warn/status_dim` 三键，健康灯全部走 ThemeManager，**零内联硬编码**

### 四、验证

- 新增 `_verify/check_quote_health.py` **30 项全过**：三层报价数学/死号跳过/单价重算/配额耗尽/显式死渠道→local/试演只读语义（remember + used_today 不变）/handler 修正/四处接线断言
- `run_all_checks` 37 项：除已知历史项 **GUARD（styles.css 基线漂移，与 HEAD 零差异，待你决策是否 `--update` 重锁）** 外全通过
- 环境纪律：回归必须用 `.venv312/Scripts/python.exe`（托管 Python 缺 numpy 会让 GUARDINTEG 假失败）

## V4.35.0 (2026-09-21) — 生成链路三件套：能力路由 + 额度池 + 评分回写（P0-1/2/3）

> **触发**：按 `docs/_reports/2026-09-21-升级任务清单.md`（对照鲸影 dsh-video-studio
> 学习报告产出）直接开工，P0 三项一次落地。全部新模块在 `app/core/ai/`，
> **纯逻辑、不 import app 包**，不触碰任何冻结区。

### 一、P0-3 能力声明 + 自动路由（`app/core/ai/provider_caps.py`）

| 项 | 内容 |
|---|---|
| 问题 | `_resolve_provider_order()` 是写死的名字顺序，没有能力概念——要「首尾帧」可能选中不支持的 provider 白试一轮 |
| 方案 | 三个 provider 的 **capabilities 声明表**（文生/图生/首尾帧/口型/`max_duration`/`resolutions`/`quality_tier`）+ `resolve_order()`：按请求 spec 筛选 → tier 降序 → **local 永远兜底**（保住无网络可演示） |
| 接入 | `generate()` 新增 `spec` 参数；`_resolve_provider_order` 委托能力路由，声明模块不可用时诚实降级回名字顺序 |
| 扩展 | **新增 provider 只加声明**（表加一行或 `register_caps()`），路由代码零改动 |
| 验收 | 首尾帧请求 → cogvideo 不在候选 ✔；duration=12 → 两个云渠道都被过滤 ✔ |

### 二、P0-1 额度池调度（`app/core/ai/provider_pool.py`）

| 项 | 内容 |
|---|---|
| 问题 | 一次调用 = 一次赌，撞死号整段失败落 ffmpeg 占位片；无账号/配额/健康概念 |
| 方案 | 多账号条目（`daily_quota`/`used_today`/`quality_tier`/`health`/`cooldown_until`）；选路 **tier 降序 → 配额未耗尽 → 最久未用**；失败**指数退避 60s→30min 封顶** + `pick_next_after_failure()` 当场换号；跨天自动清零 |
| 持久化 | `~/.shiguang/accounts.json`（**0600 权限 + 原子写**）；credential 只存引用名，接口只回掩码 |
| 接入 | `generate()` 循环前 `reorder_providers()`（有健康账号的渠道排前），成功 `report_success`、失败 `report_failure`；**空池完全透传**（未配置账号 = 行为与旧版一致） |
| 验收 | 换号/配额尽不再选/连败 3 次进 cooling/重启用量保持/审计有理由，19 项全过 ✔ |

### 三、P0-2 评分回写闭环（`app/core/ai/score_book.py`）

| 项 | 内容 |
|---|---|
| 问题 | 五维打分卡打完就丢（只渲染 QListWidget），守护/质检学不到任何东西 |
| 方案 | 风格评分簿：按 `style_dna` 命名空间隔离存条目（dims/gains/negatives/score/retake）；`best_combo()` 按 (增益,负面词) 组合聚合出历史最优；**retake 条目分数按 0.4 折算**（重拍过的组合下次不再优先） |
| 闭环 | 生成前：`enhance_prompt()` 第⑤步查同风格高分组合 → 负面词换历史验证过的组合 + 增益词注入提示词；生成后打分：`_render_score_results()` 自动写回 |
| 接入 | `build_guards_from_context()` 新增 `style_dna` 参数；capability_handlers 的 generate 在未显式给时用 `platform` 当命名空间 |
| 验收 | 落盘/高分组合复用/重拍降权/风格隔离 20 项全过 ✔（含 enhance_prompt 集成路径） |

### 四、回归与顺手修

- 新增校验：`check_provider_caps.py`(24) / `check_provider_pool.py`(19) / `check_score_book.py`(20)
- **`run_all_checks` 从 22 项扩到 37 项**：补登记了此前一直没注册进一键回归的守护族 11 项
  （GUARDBASE/TTSGUARD/CHARANCHOR/EXPGUARD/PROPGUARD/GUARDS/GUARDPIPE/GUARDINTEG/ACTIONWIRE/CTXBUDGET/AGENTLOOPCTX）
- 顺手收敛上轮遗留：`AgentPanel.tsx` 主库→副库（AI-Canvas-tauri/src/libtv）已同步，CANVASDUAL 无新分叉
- 已知历史项（非本轮引入，**待你决策**）：冻结区守卫仍报 `styles.css` drift ——
  该文件与 HEAD **零差异**，是早前已提交的 auto-commit 没重新锁基线；如确认要重锁基线，
  跑 `python scripts/frozen_zone_guard.py --update`（按解冻纪律走）

## V4.34.1 (2026-09-21) — Agent 空间策略：对话区弹性 + 三档可调配

> **触发**：用户指出 Agent 面板「不符合使用习惯 + 面积难受 + 对话体验难受」，
> 并追问「Agent 占用与剪辑体验如何平衡」。**这不是样式问题，是布局架构问题。**

### 一、根因（三个，都有代码证据）

| # | 证据 | 后果 |
|---|---|---|
| ① | `self._edit_agent_chat.setFixedHeight(72)` | **面板叫「Agent」，对话区却最小**（72px ≈ 3 行），且被塞在 `QScrollArea` 里与卡片抢空间 |
| ② | `top_splitter.setSizes([280, 750, 380])` | 右栏**固定 380px**，既容不下对话、又不许用户调 |
| ③ | `_add_lazy("🤖 Agent", …)` 排在第 10 位 | Agent 被埋在「属性/调色/特效/文字/贴纸/音频/角色/AI/**Agent**/导出」里，难找 |

### 二、核心主张：**不预设唯一宽度，改为「空间可调配」**

剪片时 Agent 该窄（让位预览/时间线），对话时该宽 —— 两种状态**切换频繁**，
任何固定尺寸都会有一边长期难受。故做成**用户随时可切的三档**：

| 档 | 触发 | 右栏 | 说明 |
|---|---|---|---|
| **默认档** | 启动默认 | 380px | 剪辑优先，不挤压预览 |
| **展开档** | 头部「⤢」 | 620px | 对话优先，从预览区借空间 |
| **自由** | 拖分隔条 | 任意 | 宽度用 QSettings 记忆（夹在 300~760 防记忆值搞坏布局）|

### 三、面板内部重排（不动主布局、零风险）

- 对话区**移出滚动区**，由面板布局直接给 `stretch=1` + `minimumHeight(220)`
- 滚动区 `stretch` 降为 0（只装卡片）
- 唯一常驻的「执行参数卡」改为**默认收起**
- 输入区 6 个平铺按钮 → `[输入框][发送][终止(按需)][⋯]`
  （暂停/继续/重规划收进 ⋯ 菜单；控件保留为不可见宿主，避免别处 `setEnabled` 报错）

### 四、调用体验

- 工具栏标题栏加「**🤖 Agent**」直达按钮（不必在 11 个 Tab 里数到第 10 个）
- `Ctrl+Shift+A` 快捷键（`_focus_agent_panel` 统一切 Tab 并聚焦输入框）

### 五、★ 纪律事件：及时回退了冻结区改动

开发中发现上一轮（V4.34.0）**误改了冻结区文件** `vendor/shiguang-canvas/src/styles.css`
（它在 `canvas-magnetic-intent` zone 的 files 列表里），守卫当即报 drift。

**处理**：`git checkout` 回退该文件，并把 `AgentPanel.tsx` 里依赖它的语义 class 一并改回 inline。
**理由**：① 画布前端**只有深色主题**，那次「去硬编色」本无实际收益；② 不值得为此解冻。

> 另记录：守卫即使回退后**仍报 `styles.css` drift** —— 经哈希比对（当前 `146f1a0a…` vs
> 基线 `7718f27a…`，而当前内容 == HEAD），确认**该漂移在本轮之前就存在**（历史改动未 `--update`），
> **非本轮引入**，未擅自 `--update`。

### 六、验证

| 项 | 结果 |
|---|---|
| 4 个改动文件 `py_compile` | **全通过** |
| `run_all_checks.py` | 22/22 通过（**排除上述既有 styles.css 漂移**）|
| 真实启动 + 截图（`_verify/smoke_agent_ui.py`） | 见截图 |

---

## V4.34.0 (2026-09-21) — Agent UI 重设计第一步：治主题盲区 + 头部瘦身

> **触发**：用户反馈两块 Agent UI「不符合日常使用」。
> 定位到两个真问题：① **主题盲区**；② **头部主次不分**。风格定为「现代 IM 风格」，分两步走。

### 一、问题①：剪辑面板是一块「深色孤岛」

`_create_edit_agent_panel` 里**约 30 处 `setStyleSheet` 内联硬编深色**
（`#0f1117` / `#21262d` / `#c9d1d9` / `#2a1f24` …）——浅色主题下整块面板仍是深色，与周围割裂。
这正是项目纪律「**内联样式 = 主题盲区**」的典型案例。

**修复**：新增 `_agent_panel_styles()` **样式工厂** —— 所有颜色集中由
`ThemeManager.get_colors()`（项目既有 18 色主题色板）提供，深/浅自动适配：

| 覆盖范围 | 说明 |
|---|---|
| 面板 / 卡片 / 输入 / combo / spin | 全部改为引用色板 |
| 滚动条 / 计划卡 / 脚本卡 / 配置卡 | 同上 |
| 脚本 **HTML 渲染** | `_render_editing_script` 的内联 style 也改为色板取色 |

**业务代码硬编颜色清零**（残留仅样式工厂的兜底色板 + HTML 默认值，均属合理兜底）。

### 二、问题②：头部 4 个同权重按钮

| 位置 | 改前 | 改后 |
|---|---|---|
| **剪辑侧** | 「模式」「模型」文字标签 + 260px 固定宽下拉 + 项目行 3 个标签 | 去掉标签（语义交给 tooltip）；模型下拉**弹性宽**；项目行改用 placeholder |
| **画布侧** | 暂停 / 继续 / 停止 / 收起 **常驻 4 个** | **按状态显示**：忙碌 → 暂停 / 停止；空闲 → 继续 |

### 三、画布侧预算仪表盘去 inline 硬编

`AgentPanel.tsx` 预算 tab 的 `style={{background:"#1e293b"}}` 等 → CSS 变量 + 语义 class
（`.is-accent` / `.is-warn` / `.is-danger`）；`styles.css` 的 `:root` 补 `--warn` / `--danger`，
预算样式统一变量化。

### 四、一条判定线

**画布前端只有深色主题**（`:root { color-scheme: dark }`，无浅色变量）——故不存在「深色孤岛」问题；
**主题化只在剪辑侧（PyQt 双主题）有实际意义**。别把画布的深色当 bug。

### 五、验证

| 项 | 结果 |
|---|---|
| `py_compile`（剪辑面板） | **通过** |
| `run_all_checks.py` | **22/22**（无回归） |
| 画布 `tsc --noEmit` | 改动文件**无错误**（`riggedHumanoid.ts` 的既有报错与本轮无关，未触碰该文件） |

### 六、第二步（待确认）

消息区升级（头像 / 时间 / 角色标签 + 富文本渲染）、「画布引用」收成一行摘要、
快捷操作折叠（默认 3 个 + 更多 ▾）、模型 / 工具 / 预算**设置抽屉化**。

---

## V4.33.5 (2026-09-21) — 补三处管线缺口：TTS 分段 / 质检节流 / 自动装配

> **触发**：上一轮盘点出三个真实缺口，按 ① → ② → ③ 顺序补齐。

### ① TTS 守护挂进配音链路（四守护里漏掉的一个）

此前 `plan_tts` 只挂了 Agent 能力、**没挂配音链路**。接入点选
`voice_generator.generate_audio` —— 画布路径（`canvas_server` → `canvas_aigc` → `VoiceGenerator`）
与 AIEngine 路径（`ai_engine.generate_audio` → `self._tts`）都汇聚于此，一处改动覆盖两条路径。

| 项 | 说明 |
|---|---|
| 新增 `_generate_audio_guarded` | 切段 → 逐段 `generate_voice` → `np.concatenate` 拼接 → `_write_wav` |
| 开关 | `guard=True`（默认关，零行为变化）；短句（≤40 字）不分段走原路径 |
| 调用点 | `canvas_aigc` 本地后端 + `ai_engine` TTSAdapter |

> ⚠️ **只切段、不喂 SSML 注音**：现有本地 TTS（gTTS/Coqui）不支持 SSML，喂进去会把
> `<phoneme>` 当文字念出来。注音留给支持 SSML 的后端（edge-tts）后续接入——**宁可不注音、不念标签**。

### ② 守护质检默认不烧 LLM

`augment_inspection` 的 `use_llm` 默认 `True → False`；`_guard_inspect` 从 `guards["use_llm"]`
显式读开关。理由：它**每轮**都会跑，默认调 LLM 意味着 MAX_RETRIES 轮 = 同样多次额外费用。

> 顺带修一处逻辑缺陷：`use_llm=False` 时**绝不调**（旧实现即使显式传了 `llm` 也会调）。

### ③ 守护上下文自动装配

新增 `build_guards_from_context`：

| 来源 | 方式 |
|---|---|
| 角色 | 显式传 > 按名查角色库 `library.json`（**只读 JSON、不 import 冻结区的 `character_management_module`**） |
| 道具 | 参数构造 |
| 表情档位 | 按场景情绪词推断 `intense` |

`capability_handlers.pipeline.generate` 支持 `guards="auto"` 或
`{"auto": true, "character_name": "林晚", ...}` —— 免去手填 `{"character": {...}}`。

### 验证

| 项 | 结果 |
|---|---|
| `_verify/check_guard_integration.py`（新） | **23 checks** |
| 11 个 check 脚本 | **339 checks 全通过** |
| `app/tests/test_agent_policy.py` | **14 passed** |
| `run_all_checks.py` | **22/22** |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |

---

## V4.33.4 (2026-09-21) — 上下文预算按模型自适应（128K 窗口放大约 12 倍）

> **触发**：用户问「能做到 300K 上下文吗」。查证发现真正的问题不是「不够大」，而是**阈值写死**。

### 一、问题：一把尺子量所有模型

`compress_messages` 的 `max_chars` 曾**硬编码 12000 字符**（按 `ai_engine._estimate_tokens`
的「中文 0.6 token/字」折算 ≈ **7200 token**），**与接入的模型无关**：

| 模型窗口 | 12000 字符的占比 | 结果 |
|---|---|---|
| 8K | **90%** | ≈7200 token **已超该窗口可用输入**（偏大） |
| 32K | 22% | 偏保守 |
| 128K | **5.6%** | **浪费 94% 窗口** |
| 200K | 3.6% | 浪费更多 |

### 二、新增 `app/core/context_budget.py`

| 函数 | 职责 |
|---|---|
| `KNOWN_WINDOWS` | 常见模型窗口表（OpenAI / Anthropic / Gemini / 国内主流） |
| `window_for(model, provider)` | 「小写包含 + **最长键优先**」匹配；未知 → `None` |
| `chars_budget(window)` | 取两约束较小者（`窗口×0.7` 留波动 / `窗口−4096` 给输出预留），再按 1 token≈1.67 字符折算 |
| `resolve_max_chars(...)` | **override > 窗口推导 > 保守默认** |

**换算结果**：8K → **6826** · 128K → **149333**（放大 ~12 倍）· 300K → **350000**

> **最长键优先**是必需的：否则 `"gemini"`（32K）会抢先匹配 `"gemini-1.5-pro"`（2M），把大窗口算成小窗口。

### 三、`compress_messages` 向后兼容改造

`max_chars` 默认由 `12000` 改为 **`None`**：

| 调用方式 | 结果 |
|---|---|
| 显式 `max_chars=3000` | **以它为准**（原行为） |
| 传 `model="gpt-4o"` | 按窗口推导 → 149333 |
| 都不给 | **12000 —— 与改造前逐字一致**（零行为变化） |

三个调用点已传 `model` / `provider`：`project_agent_host`（画布/项目侧）·
`editor_agent_panel_mixin`（剪辑侧）· `agent_loop`（多轮循环）。

### 四、验证

| 项 | 结果 |
|---|---|
| `_verify/check_context_budget.py`（新） | **28 checks** |
| `app/tests/test_agent_policy.py` | **14 passed** |
| 10 个 check 脚本 | 全部通过 |
| `run_all_checks.py` | **22/22** |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |

> 开发中由测试抓出一处文档错误：`chars_budget(8192)` 示例写成 6827，
> 实际 `int(4096 × 1.6666…)` = **6826**（已修正）。

---

## V4.33.3 (2026-09-21) — Agent 循环上下文压缩 + 压缩边界加固

> **触发**：用户问「Agent 会有上下文限制吗」。查证发现项目已有三层管理
> （会话截断 20 轮 / 12000 字符 · 窗口压缩 12000 字符 · 循环预算 12 轮 / 24 工具），
> **但 `agent_loop` 的轮内 messages 未走窗口压缩** —— 一处真实的对齐缺口。

### 一、缺口：agent_loop 轮内无压缩

Agent 多轮循环每轮追加 2 条消息（assistant 的工具调用 + user 的观测结果）；
观测自体截断在 400~600 字符，**但 assistant 那条含完整 params** —— 12 轮可累积到数十 KB。

| 场景 | 影响 |
|---|---|
| 128K 窗口模型 | 无碍 |
| **窄窗口模型（8K / 32K）** | **有撑爆风险** |

### 二、修复

**① `agent_loop` 循环体逐轮压缩**（位置在预算检查之前，与另两条 Agent 路径对齐）：

| 路径 | 状态 |
|---|---|
| `project_agent_host.py:406`（画布 / 项目侧） | ✅ 原本已有 |
| `editor_agent_panel_mixin.py:890`（剪辑侧） | ✅ 原本已有 |
| `agent_loop.py` | **← 本版补上** |

只改「发给模型的窗口」，**不动 `result.steps` 里的原始记录**；未超限时函数直接返回原列表
（仅一次字符统计），逐轮调用无性能顾虑。

**② `compress_messages` 边界加固**：原实现把中间轮次收成摘要、**原样保留最近 6 条** ——
若这 6 条本身就顶超上限（单轮 params 数千字符的场景），压缩后仍超限且随轮数缓慢爬升。
现于摘要分支追加「tail 按预算裁剪」（**从最早的开始**，优先保留最近上下文，
与 `len(rest) <= keep_tail` 分支的截断策略一致）。

### 三、实测对比（`_verify/check_agent_loop_context.py`）

| | 每轮 messages 字符数（11 轮） | 峰值 |
|---|---|---|
| **加固前** | 383 → … → 14047（持续爬升） | 14047 |
| **加固后** | 383 → … → 11962 → **12007 × 5（稳定）** | **12007** |

不压缩估算 41083 字符 → 实测稳定在 12007（紧贴 12000 上限）。

### 四、验证

| 项 | 结果 |
|---|---|
| `_verify/check_agent_loop_context.py` | **7/7** |
| `app/tests/test_agent_policy.py` | **14 passed**（含 compress 用例） |
| 9 个 check 脚本 | 全部通过 |
| `run_all_checks.py` | **22/22** |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |

---

## V4.33.2 (2026-09-21) — 守护挂进生成管线：与已接入的 LLM 联动

> **触发**：用户要求「更深一点，达到守护真正挂进生产管线那种，能和接入的大模型进行联动互动，
> 而不是只限于 Agent」。此前四个守护是 `pipeline.*` **Agent 能力** —— 要人 / Agent 主动调用才生效。

### 一、关键认识：守护的两级形态

| 形态 | 何时生效 | 问题 |
|---|---|---|
| **Agent 能力**（V4.32.7 ~ V4.33.1） | 人 / Agent **主动调用** | 想不起来调 = 等于没有 |
| **管线守门人**（本版） | 生成管线**自动调用** | ✅ 无需谁记得 |

### 二、新增适配层 `app/core/ai/guard_pipeline.py`

| 函数 | 时机 | 做什么 |
|---|---|---|
| `make_llm()` | 通用 | **LLM 联动入口**：把 `ai_engine.chat_with_fallback` 包成守护需要的 `(prompt)->str` |
| `enhance_prompt()` | 生成前 | 注入角色卡 / 道具结构 / 表情幅度 + 全量负面词 |
| `augment_inspection()` | 生成后 | 两层质检：规则层（道具 / 角色漂移）+ **LLM 层（大模型针对守护维度聚焦审核）** |
| `revise_hint()` | 修订 | 把守护问题转成明确 avoid 提示 |
| `run_guard_round()` | 干跑 | 一轮守护（不真的生成视频），供预览 / 测试 |

### 三、接入 `AIVideoGenerationPipeline`（全部可选参数，缺省 None 行为不变）

```
execute(guards=)
  └─ _gen_prompts(guards=)              ← 每个提示词调 enhance_prompt（生成前守护）
  └─ _generate_and_inspect(guards=)
       └─ _inspect(...)                 ← 原有 LLM 初检
       └─ _guard_inspect(...)           ← 【新】守护质检，问题并入 issues → 走同一条回溯
       └─ _revise_prompt(guard_hint=)   ← 【新】合并守护的明确提示（avoid 截断 80→160）
```

**LLM 联动**的双重体现：
1. `make_llm()` 让守护真正调用项目已接入的大模型；
2. `augment_inspection` 的 LLM 层让大模型**针对守护维度聚焦审核**
   （角色一致性 / 表情幅度 / 道具结构 / 手部），比管线原有泛泛「穿模 / 畸形」初检更精准。

> 开发中由测试抓出并修复一处边界缺陷：`enhance_prompt` 在**空提示词**时会以 `" | "` 开头（污染下游）。

### 四、新增持久校验 `_verify/check_action_wiring.py`

补齐「AGENTMAP 只覆盖目录↔dispatcher、**对话面无人管**」的缺口；
**自动从 catalog 派生**校验清单，新增能力无需改它。

> **记录一条判定线**：画布侧 action（`addNode` / `undo` 等 28 个）由**前端 `executeRemoteTask` 本地执行**，
> **不在后端白名单是设计如此、非缺陷** —— 校验时必须先剔除，否则 28 条假阳性。

### 五、验证

| 项 | 结果 |
|---|---|
| 7 个 check 脚本 | **274 checks 全通过** |
| `_verify/check_action_wiring.py` | **7/7** |
| `run_all_checks.py` | **22/22** |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |

---

## V4.33.1 (2026-09-21) — 四守护深度优化：共享基座 + 统一门面 + 四项增强

> **触发**：用户要求「把上面提到的那几个都进行深度优化」。
> 复核四个守护后看到两类债：① **四份重复代码**（`_norm` / 指纹 / `diff_*` 各写一遍，改一处要改四处，
> 违背项目「单一事实来源」纪律）；② 都有「浅」处（tts 逐段调 LLM、expression 无稀疏化等）。

### 一、抽共享基座 `app/core/ai/guard_base.py`

| 基座函数 | 原重复点 |
|---|---|
| `normalize_text` | `character_anchor._norm` + `prop_guard._norm` |
| `normalize_traits` | `extract_traits` + `extract_prop_traits` |
| `stable_fingerprint` | `fingerprint` + `prop_fingerprint` |
| `diff_traits` | `diff_anchor` + `diff_prop_anchor` 内核 |
| `to_float` | `expression_guard._to_float` |
| `extract_json_array` | `tts_guard._extract_json_array` |
| `merge_unique` | （门面合并负面词用） |

四模块改为复用，**对外接口与行为完全不变** —— 由四个既有 check 脚本（159 checks）全绿验证。
旧的私有名（`_norm` / `_to_float` / `_extract_json_array`）保留为**兼容别名**。

### 二、统一门面 `app/core/ai/guards.py` + 新能力 `pipeline.guard_all`

- `list_guards()` —— 四守护元信息（含 capability id）
- `plan_guards(kinds, params)` —— **一次跑多个守护**，单守护失败不影响其余
- `guard_negative_all()` —— **合并全部负面词并去重**：生成时一次拼齐约束

### 三、四项深度增强

| 模块 | 增强 | 解决什么 |
|---|---|---|
| `tts_guard` | `detect_polyphones_batch` —— 多音字消歧**一次调 LLM**（原逐段 N 次） | 省 token/延迟；跨段上下文更准 |
| `expression_guard` | `sparse_frames` —— 关键帧稀疏化（保首尾） | 表情轨数据瘦身 |
| `character_anchor` | `plan_multi_anchor` —— 多角色批量 + 跨角色冲突检查 | 一次建多卡；揪「同名」/「同指纹」错误 |
| `prop_guard` | `dual` 双持武器（`off_prop_type`） | 双持最易长成一团，主副武器各自约束 |

### 四、测试侧

- 新增 `_verify/check_guard_base.py`（基座）+ `_verify/check_guards.py`（门面 + 四项增强）
- 四个既有 check 的模块加载改为**「伪包」方式**（`_sg_ai_pkg`）—— 使包内相对导入可用，
  且仍**不 import `app` 包**（不触发硬件探测）

### 五、验证

| 项 | 结果 |
|---|---|
| 6 个 check 脚本 | **237 checks 全通过**（35+43+44+41+35+39） |
| 手工三向一致（五能力） | **37/37** |
| `run_all_checks.py` | **22/22 全通过**（含 AGENTMAP） |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |

---

## V4.33.0 (2026-09-21) — 手持道具守护：结构约束 + 握持描述（四守护集齐）

> **触发**：用户提供 MidJourney 实图并指出关键诊断——手持武器出现「一横一竖」的
> **三通 / T 形交叉结构**，本应是连续贯通、无分支的长杆。
> 至此「AI 生成质量守护」四个能力**全部落地**。

### 一、★ 实图诊断：这是「结构拓扑错误」，不是「握持一致性」

用户看图后明确纠正了诊断方向：重点不是「手有没有握稳」，而是**道具结构本身错了**
（握持处长出多余分支，像一根三通管件）。故本轮核心是**结构拓扑约束**。

### 二、新增能力 `pipeline.prop_consistency` + 核心模块 `app/core/ai/prop_guard.py`

| 函数 / 常量 | 职责 |
|---|---|
| `PROP_STRUCTURE_TEMPLATES` | 7 类道具正确结构（长枪/剑/法杖/弓/斧…），**每条明确「单一主干无分支」**——直击「三通」 |
| `build_prop_prompt(prop_type, grip, hand)` | 组合「结构约束 + 握持姿态」描述 |
| `GRIP_TEMPLATES` | 5 种握法（单手握 / 双手握 / 举起 / 肩扛 / 前指） |
| `build_prop_anchor` / `diff_prop_anchor` | 道具特征锚定 + 指纹漂移（治「这次长枪下次变刀」） |
| `prop_negative()` | 防畸形负面词（**结构项**：多余分支 / 三通 / T 形接口；**接触项**：手指融合 / 武器穿过手） |
| `check_hand_keypoints` | 21 点手部关键点合理性规则（MediaPipe Hands 格式；低置信度 = 融合、指尖过近 = 粘连、掌尺度塌缩 = 无效） |
| `plan_prop` | 统一入口（只出计划，effect=read） |

> 未知道具类型**降级仍带结构约束** —— 结构约束宁可有、不可无。

### 三、四个守护能力集齐

| 问题 | 能力 | 版本 |
|---|---|---|
| ① 配音长文本漂移 | `pipeline.tts_polish` | V4.32.7 |
| ② 表情夸张 | `pipeline.expression_clamp` | V4.32.9 |
| ③ 人物跨镜头漂移 | `pipeline.character_anchor` | V4.32.8 |
| ④ 手持武器结构畸形 | `pipeline.prop_consistency` | **V4.33.0** |

### 四、验证

| 项 | 结果 |
|---|---|
| `_verify/check_prop_guard.py` | **39/39 全通过**（结构模板/降级/提示词/负面词/道具漂移/手部关键点/脏数据/四处接线） |
| 手工三向一致（四个守护能力） | **30/30** |
| `run_all_checks.py` | **22/22 全通过**（含 AGENTMAP） |
| 冻结区守卫 | `OK frozen zones intact (85 locks)`（四轮全部零冻结区改动） |

---

## V4.32.9 (2026-09-21) — 表情幅度守护：权重钳制 + 帧间限幅 + 幅度质检

> **触发**：承「AI 生成质量守护」系列，本轮落地问题 ② 脸部表情夸张
> （用户实测：「鼓腮生气时整个腮帮变化过于剧烈，不符合人体机能」）。

### 一、两个根因

| 根因 | 表现 |
|---|---|
| 无「人体合理幅度」约束 | 表情权重可拉到极值（鼓腮到 1.0 = 吹气球） |
| 无「时间轴平滑」约束 | 帧间可**瞬间跳变**（突变比绝对幅度更刺眼） |

### 二、新增能力 `pipeline.expression_clamp` + 核心模块 `app/core/ai/expression_guard.py`

表情维度采用 **ARKit `ARFaceAnchor` blendshape** 标准命名（与 `lip_sync.py` 出口一致）：
用户说的「鼓腮」= **`cheekPuff`**。

| 函数 / 常量 | 职责 |
|---|---|
| `NATURAL_CAPS` | 各维度保守经验上限（参考 FACS 强度分级 + ARKit 常见范围；**非精确人体测量**，可用 `overrides` 覆盖） |
| `resolve_caps(profile, overrides)` | 上限 = NATURAL_CAPS × profile 缩放（subtle 0.65 / natural 1.0 / intense 1.3） |
| `clamp_frame` | 单帧绝对幅度钳制，记录削减明细 |
| `clamp_sequence` | 帧序列：绝对幅度 + **帧间跳变限幅**（治「变化过于剧烈」） |
| `check_amplitude` | 质检：定位超限帧 / 超限维度 / 跳变点 |
| `build_expression_hint` / `expression_negative` | 提示词约束 + 防夸张负面词（文生视频路径） |
| `plan_expression` | 统一入口（只出计划，effect=read） |

> **未登记维度走 `FALLBACK_CAP` 兜底** —— 否则生成端新增一个 blendshape 维度即可绕过全部限制。

### 三、四处接线

| # | 文件 | 改动 |
|---|---|---|
| 1 | `agent_capability_catalog.py` | `CAPABILITY_ROWS` 加 `pipeline.expression_clamp` |
| 2 | `capability_handlers.py` | `PipelineCapabilityHandlers.expression_clamp` + 注册 |
| 3 | `agent_action_registry.py` | `_AGENT_ACTION_ROWS` 加 `expression_clamp`（★ 守卫不覆盖） |
| 4 | 同上 | `build_agent_actions_help_block` 补参数说明（★ 守卫不覆盖） |

### 四、验证

| 项 | 结果 |
|---|---|
| `_verify/check_expression_guard.py` | **35/35 全通过**（上限表/单帧钳制/profile/帧间限幅/质检/脏数据/四处接线） |
| 手工三向一致（三个守护能力） | **23/23** |
| `run_all_checks.py` | **22/22 全通过**（含 AGENTMAP） |
| 冻结区守卫 | `OK frozen zones intact (85 locks)`（零冻结区改动） |

---

## V4.32.8 (2026-09-21) — 角色一致性锚定：跨镜头特征卡 + 漂移检测

> **触发**：承 V4.32.7「AI 生成质量守护」系列，本轮落地问题 ③ 人物形象漂移
> （同一角色在不同镜头/片段长相不一致）。

### 一、关键判断：漂移有一半根因在「我们自己」

生成模型缺身份保持能力是外因，但**内因更可控**——每次生成时角色描述拼得不一致
（这次写短发、下次写长发；这次拼了外貌、下次漏了），漂移就必然发生。
本轮先守住「我们能控的那一半」，做**文本层的一致性锚定**。

### 二、新增能力 `pipeline.character_anchor` + 核心模块 `app/core/ai/character_anchor.py`

| 函数 | 职责 |
|---|---|
| `extract_traits(character)` | 提取应稳定特征（对齐 `CHARACTER_FIELD_SCHEMA` 的 visual 组 + 关键 base）；空值不收录 |
| `fingerprint(traits)` | 特征指纹（sha1 前 12 位）；改一字即变 |
| `build_anchor(character, prompt=, reference_image=)` | 锚定卡：**优先复用** `canvas_bridge.build_character_prompt` 的派生（保 SSOT）+ 防漂移负面词 + 参考图标记 |
| `diff_anchor(anchor, character)` | 漂移检测：定位到具体特征项与前后值 |
| `check_shot_alignment(anchor, shot_prompts)` | 校验各镜头 prompt 是否**漏拼**强特征（appearance / memory_anchors），返回需重试镜头 |
| `plan_anchor(...)` | 统一入口（只出计划，effect=read） |

### 三、四处接线

| # | 文件 | 改动 |
|---|---|---|
| 1 | `agent_capability_catalog.py` | `CAPABILITY_ROWS` 加 `pipeline.character_anchor` |
| 2 | `capability_handlers.py` | `PipelineCapabilityHandlers.character_anchor` + `register_builtin_handlers` 注册 |
| 3 | `agent_action_registry.py` | `_AGENT_ACTION_ROWS` 加 `character_anchor`（★ 守卫不覆盖） |
| 4 | 同上 | `build_agent_actions_help_block` 补参数说明（★ 守卫不覆盖） |

### 四、验证

| 项 | 结果 |
|---|---|
| `_verify/check_character_anchor.py` | **41/41 全通过**（空值不收录/指纹稳定/漂移定位/漏拼校验/脏数据/四处接线静态断言） |
| 手工三向一致（tts_polish + character_anchor） | **14/14** |
| `run_all_checks.py` | **22/22 全通过**（含 AGENTMAP） |
| 冻结区守卫 | `OK frozen zones intact (85 locks)`（**零冻结区改动**；`character_management_module.py` 在锁内，本能力只读不改） |

---

## V4.32.7 (2026-09-20) — TTS 正音守护：长台词切段 + 多音字注音

> **触发**：用户提出「AI 生成视频里最常见的问题」——① 配音在长片段里
> 「前面正常、后面发音错/与字幕不符」；② 人物表情夸张（如鼓腮过剧）。
> 随后补充 ③ 人物形象漂移 ④ 手持武器畸形。四个问题**病根同一个**：
> AI 生成是黑盒 —— 一次性吐结果、中间插不上手、事后没人检查。
> 解法同一套：**两道防线**（生成前 LLM 约束 + 生成后质检回读）。
> 本轮先落地最痛、最独立、零冻结区的问题 ①。

### 一、问题诊断（证据）

| 现象 | 根因 | 项目现状 |
|---|---|---|
| 长片段配音「后面发音错/与字幕不符」 | 长文本 TTS 注意力漂移 + 文本-音频对齐错位（**非多音字随机错**） | `voice_generator._generate_tts_audio` 与 `canvas_aigc.py:1035 generate_audio_via_host` 均**整段直喂、零分段零消歧** |

> 15 秒片段正常、长了才错 —— 这条规律排除了多音字（多音字是随机错，不是「后面才错」）。

### 二、新增能力 `pipeline.tts_polish` + 核心模块 `app/core/ai/tts_guard.py`

| 函数 | 职责 |
|---|---|
| `segment_text(text, max_chars=40)` | 按句读边界切长台词；**不变量**：拼接去空白 == 原文去空白 |
| `detect_polyphones(text, llm)` | LLM 多音字消歧；失败/非 JSON → `[]`（诚实降级，不瞎猜读音） |
| `build_ssml(text, polyphones)` | 转 SSML `<phoneme>` 注音 |
| `diff_readback` / `verify_segments` | ASR 回读比对，返回需**定向重生成**的段下标 |

**纪律**：只读只出计划（effect=read）、不 import app 包（可脱离 Qt 单测）。

### 三、四处接线（按 `agent-capability-wiring`）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `agent_capability_catalog.py` | `CAPABILITY_ROWS` 加 `pipeline.tts_polish` |
| 2 | `capability_handlers.py` | `PipelineCapabilityHandlers.tts_polish` + `register_builtin_handlers` 注册 |
| 3 | `agent_action_registry.py` | `_AGENT_ACTION_ROWS` 加 `tts_polish`（★ 守卫不覆盖） |
| 4 | 同上 | `build_agent_actions_help_block` 补参数说明（★ 守卫不覆盖） |

### 四、★ 开发中抓出并修复的真缺陷

LLM prompt 模板里的 JSON 示例 `{"word": ...}` 含大括号，被 `str.format()` 当占位符解析抛 `KeyError`，
被 `except` 吞成「降级」——**接真 LLM 时注音会永远静默失效**。改为 `str.replace` 修复。
（本缺陷由 `_verify/check_tts_guard.py` 的「假 LLM 注入」用例抓出 —— 测试的价值正在于此。）

### 五、验证

| 项 | 结果 |
|---|---|
| `_verify/check_tts_guard.py` | **44/44 全通过**（切段不丢字/脏数据容错/LLM 降级/回读质检/四处接线静态断言） |
| 手工三向一致 | **8/8**（catalog ↔ dispatcher ↔ action 白名单，含守卫不覆盖的第 3/4 处） |
| `run_all_checks.py` | **22/22 全通过**（含 AGENTMAP 动作表一致性） |
| 冻结区守卫 | `OK frozen zones intact (85 locks)`（**本轮零冻结区改动**） |

### 六、后续（问题 ②③④）

统一框架与后续落地计划见 `docs/_reports/2026-09-20-AI生成质量守护方案.md`：
- ② 表情夸张 → `pipeline.expression_clamp`（参数化权重钳制 / 提示词约束）
- ③ 人物漂移 → `pipeline.character_anchor`（复用现有角色库 + 参考图 + 人脸相似度质检）
- ④ 武器畸形 → `pipeline.prop_consistency`（手部姿势参考 + 接触检测）

---

## V4.32.6 (2026-09-20) — 全库 NameError 审计：AST 作用域清零

> **触发**：用户要求「阅读所有代码，抓取 bug，反思不足，进行修改，理解项目」。
> 全库 **409,192 行 / 1,319 文件**（529 个 .py = 183,859 行），逐行通读不现实 ⇒
> 转为**多检测器系统性审计**。本轮做最高价值的一档：AST 词法作用域分析找
> 「引用不存在的名字」——这类缺陷 **pyflakes 会漏、编译期不报、只在执行到那一行才崩**。

### 一、自建检测器：`_verify/scan_undefined_names.py`

四代演进，**每代踩的坑都写进 docstring**（避免后人重踩）：

| 代 | 错误 | 教训 |
|----|------|------|
| v1 | 把整棵子树 Store 名扁平并成一个集合 | 闭包变量全漏判 → `200KB` 假阳性 |
| v2 | 用 `ast.walk` 收集 `global/nonlocal` | 走进**内层函数**把内层 `nonlocal buf` 当外层声明 → 外层 `lookup` 跳过自己的 `bound`（`project_agent_host.py` 13 条假阳性） |
| v3 | `loads_of`/`_collect_scope` 只 `iter_child_nodes` **不看根节点** | 函数体内 `import x as mod` 整条语句漏登记（`verify_mlt_api.py` 等大量假阳性） |
| v4 | 推导式一律按「推导式作用域」判 | 漏掉**最外层可迭代对象在外围作用域求值**规则（见下） |

**最终结果：扫 528 个 .py —— 语法错误 0 · 扫描器异常 0 · 可疑项 0。**

### 二、修复的 3 个真实缺陷

| # | 文件 | 缺陷 | 后果 |
|---|------|------|------|
| 1 | `app/core/log_manager.py` | 模块级 `logger` **从未定义**，但 `cleanup_old_logs()` 的 `except` 分支引用它 | 删日志失败时 **except 体内自己抛 `NameError`** —— 把「记一条 debug」变成「崩一次」。**已反证实测复现 → 修复 → 复测通过** |
| 2 | `app/core/video_processing/mlt_engine_cpp.py` | `extract_highlights()` 用 `int(time.time())`，但全文件**无 `import time`** | 每次调用**必** `NameError`（非仅异常路径）。已补模块级 `import time` |
| 3 | `tests/legacy/test_license.py` | `QGridLayout` 用于 L559 但**未导入**（`QFormLayout` 导了、`QGridLayout` 漏了） | 进入该 UI 分支即 `NameError`。已补进导入列表 |

> 缺陷 1 的修复顺带兑现了该文件 docstring 第 12 行的承诺
> `新代码推荐: from core.log_manager import logger`（此前这句话是**空的承诺**）。

### 三、归档：根目录孤儿 `update_manager.py`

按 `docs/_archive/2026-09-19-root-cleanup` 的先例，移到
**`docs/_archive/2026-09-20-update-manager-dup/`**（含 MANIFEST，MD5 校验一致后删原件）。

| 核实项 | 结论 |
|--------|------|
| 静态 import / 字符串 / 动态导入 三重核实 | **零引用**（唯一引用 `app/core/editing_capabilities.py` 指向 `app/core` 版） |
| git 历史 | 仅首次「完整项目代码上传」出现，此后**从未改动** |
| 与 `app/core/update_manager.py` 相似度 | 仅 **2.2%** —— 两套完全不同的实现，非互为副本 |
| 自带缺陷 | `class UpdateDialog:` **基类为空**（未继承 `QDialog`，`super().__init__(parent)` 必 `TypeError`）+ 14 个 PyQt6 名写在使用方 `_setup_ui()` 却导入在 `__init__` 里 + `time` 未导入 |

> 两个缺陷**互相掩护**：类根本构造不出来 ⇒ 后面 14 个 `NameError` 永远执行不到，
> 误用者只会看到一个错、看不到其余 13 个。

### 四、检测器沉淀的两条判定线（防后人误判）

1. **类体里的推导式读同类体名是合法的** —— Python 规定推导式的**最外层可迭代对象在外围作用域求值**。
   实测（3.13）：
   ```python
   class A:
       D = ['a','b']
       I = {e: i for i, e in enumerate(D)}   # OK：enumerate(D) 在外层求值
       J = [D[0] for _ in range(1)]          # NameError：D[0] 在推导式作用域内
   ```
   `drama_understanding_engine.py:542` 正是此模式，**曾被误报**，非缺陷。
2. **带 UTF-8 BOM 的文件须用 `utf-8-sig` 读** —— 全库 5 个文件带 BOM
   （`app/__init__.py`、`app/modules/__init__.py`、`core/__init__.py`、`mcp_server.py`、`start_mcp.py`）。
   用纯 `utf-8` 读会留下 `U+FEFF`，`ast.parse` 假报 `invalid non-printable character`。
   **CPython 本身按 utf-8-sig 解码源码，这些文件运行完全正常** ⇒ 是扫描器假警报，不是项目缺陷。

### 五、验证

| 项 | 结果 |
|---|---|
| `_verify/scan_undefined_names.py` | **可疑项 0**（528 个 .py，语法错误 0） |
| `_verify/run_all_checks.py` | **22/22 全通过**（含 AGENTMAP） |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |
| 修复模块真实导入 | `app.core.log_manager` / `app.core.video_processing.mlt_engine_cpp` 子进程导入 `rc=0` |
| 崩溃路径实测 | `cleanup_old_logs()` 触发 `except` 分支 → **删除 `logger` 可复现 `NameError`；保留则通过** |

## V4.32.5 (2026-09-20) — 词锚定阶段 5：重锚接入 Agent

> **承接**：V4.31.x 阶段 3 完成「重锚引擎」纯函数（`app/core/dialogue_anchor.py`），阶段 4 接 UI。
> 本版打通**对话面** —— 让 Agent 能驱动重锚，而不只是点按钮。

### 一、解决的问题

锚点记在「台词的第 a~b 个词」上。改文案 → 重跑 ASR → **词级时间整体变化** → 锚点必须重新求解。
此前这套计算只能由 UI 触发，Agent 无从调用，闭环缺一环。

### 二、改动（4 个文件，全部**不在冻结区**，无需解冻）

| 层 | 文件 | 改动 |
|----|------|------|
| 执行 | `app/modules/lego/editor_module.py` | 新增 `agent_reanchor_clips()` 公开接口（约 +160 行，插在 `agent_move_clip` 之后） |
| 能力 | `app/core/capability_handlers.py` | `EditorCapabilityHandlers.reanchor_clips` + `dispatcher.register("editor.reanchor_clips", ...)` |
| 目录 | `app/core/agent_capability_catalog.py` | `CAPABILITY_ROWS` 加 1 行（新增能力的**唯一入口**） |
| 对话 | `app/core/agent_action_registry.py` | `_AGENT_ACTION_ROWS` 加 `reanchor_clips`（safe）+ 帮助文案 + L2 分层说明 |

### 三、三条防误伤设计（本能力的核心风险面）

1. **`dry_run` 默认 `True`** —— 重锚会**成批**挪片段。Agent 必须先出差异计划给用户看，
   确认后才带 `dry_run=false` 落地。最危险的失效模式是「静默成批重排」，默认值即防线。
   注意这是**双层默认**：handler 层 `req.params.get("dry_run", True)` 与
   `agent_reanchor_clips` 的关键字默认都取 True，任一层漏传都不会误写时间线。
2. **一条 `compound` 撤销** —— 所有片段改动收进单个 compound action，
   用户按一次 Ctrl+Z **整包回滚**。历史上曾因「每片一条 undo」导致用户误判「撤销坏了」。
3. **无可重排时不写撤销栈** —— 全孤儿/全无锚点时直接 `applied=False` 返回，
   不压空撤销（否则 Ctrl+Z 弹出「什么也没变」的操作）。

### 四、落地纪律

- 先 `_clips_snapshot()` 取稳定列表交给纯函数 —— **绝不把 `self._clips` 引用交出去**；
- 整段持 `_clips_lock` 写入（RLock 可重入，覆盖画布桥 / Agent 线程的并发读）；
- 纯函数 `plan_reanchor` 仍然只读、只出计划 —— **计算与落地严格分离**的纪律未破。

### 五、新增 `spread` 开关

默认按新词区间长度调整片段时长（词区间比段落时间更精确，用段落时长会与区间打架），
并保持 `out_point = in_point + duration` 契约；`spread=false` 则只平移 `start_time`、时长不动。

### 六、验证

| 项 | 结果 |
|---|---|
| 新增 `_verify/check_reanchor_capability.py` | **22/22 通过** |
| └ 其中「持锁」实证 | 用**另一线程** `acquire(blocking=False)` 全 False ⇒ 证明确实持锁 |
| `_verify/run_all_checks.py` | **22/22 全通过**（含 AGENTMAP 动作表一致性） |
| 目录 ↔ dispatcher 注册 | **56 = 56**，`verify_catalog_consistency()` 0 问题，启动自检 `total=0` |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |
| 隔离验证 | 空镜片段零改动 · 坏锚点不崩 · 空台词/坏 threshold 诚实报错 |

> **测试自身踩坑**：探锁第一版用同线程 `acquire(blocking=False)`，因 `_clips_lock` 是 **RLock（可重入）**
> 而同线程重入永远成功 → 得到假阴性、误报失败。改为**另一线程**探锁才成立。

## V4.32.4 (2026-09-20) — 视频动捕第四刀：白模动作录制（画布 0.3.0）

> **触发**：Hypit 适配调研后，用户要求出「视频动捕 → Stage3D 方案」。
> **过程反转**：回代码核实发现**方案原定的起点（第三刀）早已完成** —— 差点写出一份「把已完成工作重新设计一遍」的方案。

### 一、先纠正一个前提（否则会做重复劳动）

`docs/_archive/knowledge/17-motion-ref-design.md` §五 表格记「刀 3 关键点→白模 IK 时序 = 待开工」，
但代码核实显示**早已落地**：

| 验收项（文档原文） | 实际 | 证据 |
|---|---|---|
| 3D 导演台逐帧驱动 | ✅ | `togglePoseDrive` `Stage3D.tsx:3219` · `applyPoseFrameToActor:3131` |
| OpenPose 逐帧可视化 | ✅ | `COCO18_SKELETON` / `COCO18_CN` / `KP_VIS_THRESHOLD`（`stage3dPoseRetarget.ts:40,47,54`） |
| 可拖拽修坏帧 | ✅ | `togglePoseBadFrame:3281` + `poseEditOn:815`（叠加小窗可拖拽）+ `lerpJointPose` 自动插值 |

核心模块 `vendor/shiguang-canvas/src/stage3dPoseRetarget.ts`（336 行，头注释即写明「模式 B 第三刀」）
导出 `solveFramePose`（单帧 COCO18+BlazePose z → 25 关节角）/ `solveFrameRoot` / `findStandHipY` / `isFrameEmpty`。

**根因**：该表格是 2026-08-26 写的，之后代码推进、文档没跟上；而它还是**代码注释的引用源**
（`pose_extract_service.py` 头部指向它）。**已订正 §五 表格并补写 §5.2/§5.3，表下加显式警示**。

### 二、本版实现：第四刀「录制白模动作视频」

链路：3D 导演台逐帧渲染 → 采集 PNG → 后端 FFmpeg 合成 mp4 → `setMotionRefVideo` 挂为 `reference_video`
→ 走**已有的**第一刀通道送生成。

| 层 | 文件 | 改动 |
|----|------|------|
| 新增（纯逻辑） | `vendor/shiguang-canvas/src/stage3dPoseVideo.ts` | `planPoseVideoFrames`（保首尾抽稀）· `capturePoseFrames`（逐帧采集 + 让出主线程）· `encodePoseVideo`（上传）。**不依赖 THREE**，渲染/读像素经回调注入 ⇒ 可脱离 WebGL 单测 |
| 新增（单测） | `stage3dPoseVideo.test.ts` | 18 例：帧规划 8 + 采集 8 + 上传 2 |
| 新增（后端） | `app/core/ai/pose_video_service.py` | 解码 data URL → 写帧 → FFmpeg 合成 → 落 canvas inbox → 返回 `/inbox_file/` URL |
| 后端端点 | `app/core/canvas_server.py` | 新增 `POST /host/pose-video-encode`（**未冻结**，故未登记冻结区） |
| 前端调用 | `vendor/shiguang-canvas/src/bridge.ts` | 新增 `poseVideoEncodeViaHost`（**未冻结**） |
| 冻结文件 | `vendor/shiguang-canvas/src/Stage3D.tsx` | `recordPoseVideo()` + 两处状态 + 一处 import + 动作 tab 一个按钮 |

### 三、技术选型：为什么不用前端实时录制

| 方案 | 判定 |
|---|---|
| 前端 `MediaRecorder` 实时录制 | ❌ 录到的是「实时发生」的过程，渲染一慢就**掉帧**——运动参考视频恰恰最怕掉帧；且主画面 canvas 是 `preserveDrawingBuffer:false`（`Stage3D.tsx:990` 注释说明原因），拿不到稳定像素；开该选项又要每帧复制全屏缓冲 |
| **逐帧导出帧序列 → 后端 FFmpeg** | ✅ 采用。「要哪帧渲染哪帧」，帧率精确；复用既有离屏 RenderTarget 读像素机制（`readRenderTargetToDataURL:2738`）；FFmpeg 是项目既有能力 |
| 后端离屏渲染 3D | ❌ 项目无 Python 侧 3D 渲染，等于从零造 |

### 四、修复的实际缺陷（带证据）

| # | 缺陷 | 证据 |
|---|---|---|
| 1 | **抽稀公式会丢一半帧且不保尾帧** | 首版用 `step = ceil(total/limit)`：total=1000/limit=900 时 step=2 只取到 **500** 帧；且 `i += step` 循环取不到最后一帧 → 白模「动到一半停住」。改为保首尾、均匀取 limit 个 |
| 2 | **走位会丢失** | `applyPoseFrameToActor` 的 root 位移依赖 `poseDriveBasePosRef`（仅在 `togglePoseDrive` 设置）。录制若不自己设基准，只应用原地姿态、**走位丢失**——而走位是漫剧刚需。`recordPoseVideo` 已记录并设置该基准，录制后恢复 |
| 3 | **`EffectComposer.render()` 调用签名错误（既有）** | Three.js 的签名为 `render(deltaTime?: number)`，scene/camera 在 `RenderPass` 构造时绑定。既有代码 `composer.render(api.scene, api.camera)` 把 scene 当 deltaTime 传（类型报 TS2554）。**新代码已用正确签名**；既有调用点（`_exportSingleCamMeta:2594` 等）**未擅自改动**，留待用户裁定 |

### 五、保留不变量（逐条核对，一条未碰）

`stage3d-core` 的 8 条不变量全部不涉及本次改动：
`bodyFigureUrl` 只返回 bodychan/bodykun · `prepareBodyFigureMeshes` 不覆盖材质 ·
`loadGLBRiggedHumanoid` 不做材质替换 · **端口 18765 / 3011 / 3010 未改** ·
`export_vinchau_glb.py` 骨名映射未改 · 画布预热时机未改 · 角色库 schema 未改。

录制**只读渲染结果**，不写入任何材质/骨名/GLB 加载逻辑。

### 六、验证表

| 项 | 结果 |
|---|---|
| `tsc --noEmit` | **37 处存量 → 37 处**：用 `.bak` 还原跑 A/B 实测，**B 多出的错误 = 无**；与 `现行技术文档.md:322` 记录的基线「37 处在冻结区（riggedHumanoid 21 · Stage3D 16）」**吻合** |
| 新增/改动文件 tsc | `stage3dPoseVideo.ts` **0 处** · `bridge.ts` **0 处** |
| `vitest run` | **8 文件 / 76 测试全通过** |
| `vite build` | **rc=0 · 299 modules · 4.33s** |
| 冻结区 | 解冻 → `--update` → 复跑 **`OK frozen zones intact (85 locks)`** |
| 漂移核对 | 清单**仅 `Stage3D.tsx` 一项**（唯一冻结文件），不多不少 |
| 后端服务单测 | 诚实失败矩阵 **7/7**；真合成 90 帧 → 3.6s mp4；**ffprobe 独立复核时长 3.600000**；落 inbox 正确；临时目录残留 **0** |
| 前端模块单测 | **18/18** |

### 七、已知未做

1. **刀 5（模式 A 真模型接入）**：通道与能力探测已就位（`reference_video` 贯通 5 个文件 + `_probe_video_motion_support`），
   但**无模型声明 `video_motion`** ⇒ 传入参考视频会诚实返回「当前模型不支持视频运动参考」。**接一个支持 motion-ref 的模型即可点亮。**
2. **既有 `EffectComposer.render(scene, camera)` 调用点未修**（见四·3）—— 属存量，超出本刀授权范围。
3. 录制分辨率固定 ≤540 宽（运动参考不需要高分辨率）；若将来要出高分辨率白模预览片，另开需求。

## V4.32.3 (2026-09-20) — 冷启动提速：8.24s → 1.21s（-85%）

> **背景**：用户问「怎么提升核心模块的冷启动速度」。遵循「先测量再动手」——不对未证实的瓶颈写代码。
> **结果反转**：第一直觉指向的 `editor_module`（9451 行）完全是冤枉的；真凶是一个 40 行的探测函数。

### 一、先纠正一个测量错误（否则会改错地方）

第一轮分阶段计时显示 `import editor_module` 耗时 **11.05s**，一度被判定为瓶颈。但 `-X importtime` 只测出 **0.78s**。矛盾用 `os._exit(0)` 分离后解开：

| 脚本 | wall | 内部自测 import | 推算 shutdown |
|------|------|----------------|--------------|
| `import editor_module` 正常退出 | 11.06s | 0.705s | **≈10.35s** |
| 同上，结尾 `os._exit(0)` | **1.00s** | — | — |

**那 10 秒是解释器退出清理开销，与业务代码无关。** `subprocess.run` 的 wall time 包含子进程 shutdown——**测 Python 启动必须用 `os._exit(0)` 收尾，否则虚高 10 倍**。

### 二、真实耗时拆解

| 阶段 | 耗时 | 占比 |
|------|------|------|
| PyQt6 + QApplication + 授权 + `import MainWindow` | 0.32s | 4% |
| `_setup_ui` | 0.13s | 2% |
| **`_setup_default_modules` → 加载 `HomeModule`** | **7.79s** | **94%** |
| 主题 / 懒加载标记 | 0.00s | 0% |
| **窗口可见合计** | **8.24s** | 100% |

### 三、根因（四跳，可核对）

1. `MainWindow.__init__` → `_setup_default_modules()`（`main_window.py:684`）
2. → `_lazy_import_widget_class()`（`:713`）—— 注释称「延迟导入：避免启动时一次性加载所有 UI 代码」，**实为对每个启用模块同步 `importlib.import_module()`**
3. → `import .modules` → 触发 `modules.py:1517-1547` **顶层 eager import 块**（含 `from .editor_module import EditorModule`）—— 从**底部击穿**懒加载设计
4. → `drama_understanding_engine.py` 模块级调用 `_detect_whisper()` → `import faster_whisper` → **`torch` 全量加载**

**实测证据**：
```
起点                        torch=- cv2=- numpy=-
IMPORT faster_whisper        6.97s OK  torch=LOADED   ← 真凶
IMPORT whisper               0.00s FAIL（永远不会执行到）
IMPORT drama_understanding_engine  0.12s OK
```

一个**只想问「Whisper 装没装」**的函数，真的把它导了进来。

### 四、修复（`app/modules/lego/drama_understanding_engine.py`）

| 改动 | 说明 |
|------|------|
| **删除模块级 `_detect_whisper()` / `_check_ollama()` 调用** | 两处均为导入期副作用 |
| **新增 `_ensure_whisper_probed()` / `_ensure_ollama_probed()`** | 惰性探测 + 单次缓存，语义等价（探测时机从「模块导入」推迟到「首次使用」） |
| **6 处消费方改用 `_ensure_*`** | 第 282/283（构造日志）、291（`_load_whisper`）、546（情绪向量）、945（场景分类）、1110（情绪走势）、2022（高光精修） |
| ⚠️ **`_load_whisper` 内补探测** | 该方法读全局 `_whisper_model_type`，若只删调用不补探测，`if/elif` 两分支**都不会命中**（隐性死锁） |

**附带修复**：`_check_ollama()` 原本在导入期执行 `client.list()`，**真连本地 Ollama 服务**。检测型代码不应有外部副作用——现已一并为惰性。

### 五、实测收益

| 指标 | 改前 | 改后 | 变化 |
|------|------|------|------|
| `MainWindow()` 构造 | **8.24s** | **1.21s**（中位，3 次） | **-85%** |
| `HomeModule` 加载 | 7.76s | 0.91s | -88% |
| `torch` 启动后状态 | **LOADED** | **未加载** | ✅ |
| `sys.modules` 数量 | 2091 | **755** | -64% |

### 六、验证

- **语法**：`py_compile` 通过
- **功能回归**：导入后 `torch` 未加载 ✅ / 首次使用探测正常返回 `True` 且正确赋值 `_whisper_model_type` ✅ / 二次调用命中缓存 `0.0000s` ✅ / 引擎构造成功 ✅ / `_load_whisper` 分支可命中 ✅
- **守卫**：`_verify/run_all_checks.py` **24/25 通过**（唯一失败 `CANVASDUAL` 为既有双库漂移，与本次无关）；冻结区 `OK frozen zones intact (85 locks)`

### 七、遗留（按优先级）

| 优先级 | 项 | 预期收益 | 风险 |
|--------|-----|---------|------|
| P1 | 拆 `modules.py:1517-1547` eager import 块，改用 `module_registry.py` 已有的 `import_module`/`import_class` 声明 | ~-0.9s | 中（需核对 `MODULE_CLASSES` 外部引用） |
| P2 | 落实 `_lazy_import_widget_class` 真懒加载（当前需真实 class 才能 `register_module`） | 配合 P1 | 中高 |
| P3 | 修 `app/core/canvas_server.py` 循环导入（`cannot import name '_check_host_token' from partially initialized module`） | 稳定性 | 低（涉冻结区，需按纪律解冻） |

> 诊断全过程见 `docs/冷启动性能诊断报告.md`。

---

## V4.32.2 (2026-09-19) — 插件体系旧残留归档（8 文件 / 29.4 KB）

> **背景**：V4.32.1 结尾把「插件体系清理」单列出来提问，用户确认后处理。这批与上一批同属「归档而非删除」，但**核实结论一边倒** —— 归档对象含**真实缺陷**，不是单纯死代码。

### 起点：项目里四套插件机制并存

| # | 体系 | 位置 | 判定 |
|---|------|------|------|
| 1 | **ExtensionsRegistry** | `app/core/extension_base.py` | ✅ 现行（Plugin/Skill/MCP 统一注册表） |
| 2 | **PluginManager** | `app/core/plugin_manager.py` | ✅ 现行（`editor_module.py:868` 真实实例化） |
| 3 | `plugin_loader` / `plugin_hotloader` / `plugin_authentication` / `plugin_sandbox` | `app/core/plugin_*.py`（5 文件 / 127.5 KB） | ⚠️ **保留** —— B3 收敛标记（2026-05-31）明确「5 个文件职责不重叠，不需要合并，仅作系统级归档」 |
| 4 | **`app/modules/plugins/`** | 本批归档 | ❌ 零引用，且含必崩缺陷 |

> 第 3 套 5 个文件**全部存在且依赖链完整**（已核实，不存在断链）。本批不动。

### 归档清单（8 文件 / 29.4 KB → `docs/_archive/2026-09-19-plugin-legacy/`）

**① `plugin/` 转发壳（2 文件 / 806 B）** → `plugin_shim/`

两文件（`__init__.py` / `plugin_system.py`）**逐字节完全相同**，内容清一色：
```python
from app.modules.plugins.plugin_system import (PluginManager, plugins, ...)
```
全库 `from plugin` / `import plugin` 正则扫描 → **0 命中**。存在的唯一理由是把 `app.modules.plugins` 换个短名字，但没人用。

**② `app/modules/plugins/`（3 文件 / 27.5 KB）** → `modules_plugins/`

| 缺陷 | 证据 |
|------|------|
| **无 `__init__.py`** | 仅靠 Python 3 隐式命名空间包才可导入 —— 从未被当正式包用 |
| **`plugin_sandbox.py` 必崩** | `:93` 用 `builtins.print`，但 `:7-10` 只导入了 `os` / `logging` / `typing`，**没有 `builtins`**。实测沙箱 `__builtins__` 61 项中**无 `builtins` 键** → `install_plugin()` 调 `create_sandbox_globals()` 时**必抛 NameError**，该流程从未跑通 |
| **`plugin_system.py:360` 断链** | `from .full_video_editor import FullVideoEditorPlugin` —— 该文件**不存在**，靠 `except ImportError` 吞掉 → 每次导入都向 stderr 打 `警告: 无法导入FullVideoEditorPlugin`（实机已复现） |
| **`pyqt_plugin_manager.py` 副作用** | `:10` **模块导入时**执行 `os.makedirs("plugins", exist_ok=True)` → 在 CWD 静默建目录；`:4` 用 `from PyQt6.QtWidgets import *`（星号导入，破坏静态作用域分析）；`:12` 注释写「PyQt5」但代码是 `PyQt6`；`:78/:79` 的 `QFont.Bold` / `Qt.AlignCenter` 在 PyQt6 已变更 |
| **与现行体系重名冲突** | 本目录 `PluginManager` vs 现行 `app/core/plugin_manager.py:13` —— 同名不同实现；`plugin_sandbox.py` vs 现行 `app/core/plugin_sandbox.py`（587 行，功能完整）—— 同样同名不同实现 |

> 此残留此前已被两份体检报告点出：
> `docs/_reports/2026-09-14-代码实测体检与产品定位.md:331-335`（「另一套，无人引用」）与
> `docs/_reports/2026-09-15-项目定位与迭代方向分析.md:53`（「零引用的第二套插件体系，与正文档 §9 冲突」）。

**③ 三个 print 探针测试（3 文件 / 3.8 KB）** → `broken_tests/`

| 文件 | 断链点 |
|------|--------|
| `test_plugin_import.py` | `:14` `from modules.plugins.plugin_system import ...`、`:22/:39` `modules.plugins.full_video_editor`（不存在） |
| `test_full_video_editor.py` | `:10` **裸** `from modules.plugins.full_video_editor import ...`（不在 try 内）→ 收集阶段直接 ImportError |
| `test_all_imports.py` | `:18` `from moviepy.editor import`（moviepy 2.x 已移除 `.editor`）、`:32` `modules.utils.logger`、`:38` `config.settings`、`:44` `modules.plugins.plugin_system` —— 四处全是旧路径 |

三者均为 `print()` 探针脚本，**无 `assert`、无 `def test_*`**，pytest 收集即失败。

### 同步变更

**`plugin_config.json` —— 移除死目录项**
```diff
- "plugin_dirs": ["app/plugins", "app/modules/plugins"]
+ "plugin_dirs": ["app/plugins"]
```
依据：`app/core/plugin_hotloader.py:66-78` 读取该键并逐个 `add_plugin_dir()`。其余键（`enabled_plugins` / `plugin_registry`）**原样保留**。
> 编码验证：511 字节 / 严格 UTF-8 通过 / 无 U+FFFD / `name == "AI特效制作"` 吻合原值。

**顺带修真断链 3 处（存量缺陷，非本批产物）**

| 文件:行 | 修改前 → 修改后 |
|---|---|
| `app/core/ai_tools.py:4` | `from modules.utils.logger import logger` → `from app.modules.utils.logger import logger` |
| `app/core/preview_manager.py:2` | 同上 |
| `app/core/gl_filter_widget.py:29` | 同上 |

依据：`modules/` 顶层目录**不存在**；正确路径 `app/modules/utils/logger.py` 存在（1,035 B）。对照参考：同目录 `app/core/thread_safety.py:14` 早已用正确路径。此 3 处只要被 import 即 `ModuleNotFoundError`（`preview_manager` / `gl_filter_widget` 是 UI 侧文件，风险实在）。

### 验证

| 项目 | 结果 |
|------|------|
| 全库 `from plugin` / `import plugin` | **0 命中** |
| 全库 `modules.plugins` | **0 命中** |
| 全库 `full_video_editor` | **0 命中** |
| 全库 AST | 524 个 py，**0 语法错误** |
| 已移除项 | 8/8 全部 GONE |
| 现行插件体系关键文件 | 9/9 全部在位 |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |
| `app/version.py` | `compile + exec` 通过、`VERSION_INFO` keys 精确匹配、无重复赋值、无旧 codename 残留 |

### 保留不变量

- 冻结区 85 locks / 9 zone 完好 —— 本批**未触碰任何冻结符号**
- 现行插件体系（`ExtensionsRegistry` + `plugin_manager.py` + `app/plugins/`）**未改动一行**
- 第 3 套 `app/core/plugin_*.py`（5 文件）**未动** —— 属 B3 有意保留
- `_clips` 并发纪律、Agent 能力目录 SSOT 等既有不变量无关

---

## V4.32.1 (2026-09-19) — 根目录残留归档（19 文件 / 214 KB，归档不删）

> **背景**：V4.32.0 挖 Bug 时顺带列出一批「根目录残留」，用户确认后处理。**采用归档而非删除** —— 全部通过三重零引用核实，但保留可恢复性。

### 核实方法（三重，扫描 918 个文本文件）

| 检查 | 说明 |
|------|------|
| 静态 import | `import X` / `from X import` |
| 字符串引用 | `"X"` / `'X.py'` 字面量 |
| 动态导入 | `import_module("X")` / `__import__("X")` |

扫描范围含 `.py` / `.json` / `.yaml` / `.toml` / `.md` / `.cfg` / `.ini` / `.mdc` / `.ps1` / `.bat` / `.sh`。

**⚠️ 关键教训：英文常用词会误报。** `trend.py` / `scheduler.py` 各有 3 处「字符串引用」，逐条核实**全是误匹配**：

- `"trend"` 是网关统计 dict 的 key（`app/core/ai_engine.py:820` → `gw.trend(days=14)`）
- `"scheduler"` 是 ComfyUI workflow 的节点名（`{"name": "scheduler"}`）+ `vendor/` 下 React 的 npm 包 + Qt 控件 `name=`

> 核实字符串引用**必须逐条看上下文**，不能只数命中数。

### 归档清单（19 个 / 214.2 KB）

| 类别 | 文件 |
|------|------|
| 大快照 | `_tmp_original_timeline.py`（**159 KB** — 拆分 `timeline_widget.py` 前的原始版） |
| 扫描探针 | `count_code.py` / `scan_fast.py` / `scan_files.py` |
| 诊断脚本 | `_nav_diag.py` / `_nav_diag2.py` / `_serve_final.py` / `_test_breakdown.py` / `_test_breakdown2.py` |
| 环境探针 | `check_torch.py` / `find_mediapipe_path.py` |
| 一次性脚本 | `copy_project_to_desktop.py` / `generate_project_viewer.py` / `remove_bom.py` / `remove_all_bom.py` / `install_top0_deps.py` |
| 旧模块 | `trend.py` / `scheduler.py` / `monitor_service.py`（依赖**已下线**的 `app.modules.lego.data_collector`） |

**归档位置**：`docs/_archive/2026-09-19-root-cleanup/`

**含 `MANIFEST.md`**：逐文件核实结论 + 恢复命令 + 未纳入本批的待决项。

**恢复方式**：

```powershell
Move-Item "docs\_archive\2026-09-19-root-cleanup\<文件名>" .
```

### 刻意**没动**的（保守策略的成果）

| 文件 | 为何保留 |
|------|---------|
| `config.py` | **有真实引用** — `app/core/ai_tools.py:3` `from config import OUTPUT_PATH` |
| `update_manager.py` | 被 `app/core/editing_capabilities.py` 引用（且 V4.32.0 刚修了其 `shutil` Bug） |
| `models.py` | 根目录脚本在使用 |
| `main_qt6.py` / `_launch_qt6.py` | 启动器 |
| `conftest.py` | pytest 配置 |
| `installer.py` / `login_window.py` / `mcp_server.py` / `start_mcp.py` | 模块级脚本，独立用途 |
| `plugin/`（2 文件） | 转发壳，re-export `app.modules.plugins.plugin_system`，自身零引用 → **写入 MANIFEST 待决** |
| `app/modules/plugins/`（3 文件 / 26.9 KB） | 零引用第二套插件体系 → **未纳入本批** |

> **保守策略的价值**：若按「名字像探针」就删，会误删 `config.py` 这个被活代码依赖的文件。**核实优先于直觉。**

### 验证

| 项目 | 结果 |
|------|------|
| 根目录 py 文件 | 31 → **12 个** |
| 全库 AST | 523 个 py，**0 语法错误** |
| 归档文件名残留引用 | **0** |
| 归档目录完整性 | 20 项 / 216.6 KB（19 文件 + MANIFEST） |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |

### 保留不变量

冻结区 85 locks 完好、`_clips` 唯一真相源、所有活代码路径零改动（本轮**只动根目录残留**，未碰 `app/` / `vendor/`）。

---

## V4.32.0 (2026-09-19) — 挖 Bug · 隐蔽缺陷围剿（4 处 NameError + 1 处调试漏网）

> **背景**：用户要求「挖 bug，优化项目」。做了**七轮静态扫描**，每轮换一个检测角度，**只找「真会崩 / 真静默失效」，不找风格问题**。全程贯彻一条纪律：**扫描器报出的每一项都亲自读源码复核**——结果第一轮 4 项全是自己的误报，而后面几轮挖出的才是真缺陷。

### ① 先修扫描器：第一轮 4 项「重复定义」全是误报

首轮把 `@property` 与 `@x.setter` 判成「同类内重复定义」，报了 4 处（`keyframe_animation.py` + `core.py` 3 处）。

**根因**：用 `{d.id for d in decorator_list}` 收集装饰器名 —— 而 `@x.setter` 是 `ast.Attribute`（**没有 `.id`**），所以 setter 名永远收不到，配对判定必然失败。

**修正**：改为看装饰器**表达式形状**（`Name(id='property')` vs `Attribute(attr='setter')`）→ 全库重复定义确认为 **0**（说明历史修复保持住了，没新增）。

> 教训：**误报比漏报更消耗信任**。修复前必须先怀疑检测器。

### ② `_cleanup_temp_files` 调用未导入的 `shutil`（`update_manager.py:298`）

```python
elif os.path.isdir(path):
    shutil.rmtree(path)      # ← shutil 从未导入
```

- **触发**：清理**目录**（不是文件）时必抛 `NameError`
- **后果**：被 `except Exception` 吞成一句「清理临时文件失败」，**临时目录永远不被删除** → **磁盘泄漏，且完全静默**
- **是活代码**：该模块被 `app/core/editing_capabilities.py` 引用

### ③ `canvas_server.py:2305` 使用未导入的 `Mapping`

```python
existing_by_id = {c.get("id"): c for c in existing if isinstance(c, Mapping) and c.get("id")}
```

- **触发**：`/host/storyboard-memory/plan` 带 `apply=true`（分镜记忆「建议时长」写回时间线）
- **后果**：走到这行即 `NameError` → **该功能完全不可用**
- **易被误解**：文件顶部有 `from __future__ import annotations`，但那只影响**注解**，不影响 `isinstance()` 的**运行时求值**
- **修法**：从 `collections.abc` 导入（**不是** `typing`）—— `isinstance` 需要运行时可用的类型

### ④ `license/license_manager.py` 三处使用未导入的 `QWidget`

`:348` / `:359` / `:377` 分别创建「授权信息 / 激活 / 购买」三个标签页，全部 `QWidget()` —— 而 `:19-22` 的 PyQt6 导入清单里**没有 `QWidget`**。

**后果**：授权对话框一打开就 `NameError` → **整个授权 UI 打不开**。

### ⑤ 调试代码漏网（上一轮清理的同类）

`timeline_subwidgets.py` 的 `_report_timeline_widget_debug` 与 V4.31.0 删掉的 `_report_video_import_debug` **同款**（向 `127.0.0.1:7777` 发 HTTP、`timeout=0.8`）。

链路取证：

| 位置 | 状态 |
|------|------|
| `timeline_subwidgets.py:92` | 定义（零调用） |
| `timeline_widget.py:49` | **仍在 re-export** |
| `clip_widget.py:58` | 调用**已被注释禁用**（注释写「避免网络超时」） |
| `_tmp_original_timeline.py:2429` | 同上被注释 |
| `scripts/_split_timeline_phase1.py:82` | 代码生成模板里也有一份 |

**处理**：删定义 + 删 re-export + 删 import + 删注释残留，并**顺手清掉因此变成死导入的 `os` / `json` / `time` / `urllib.request`**（删函数后实测使用 0 次）。

### ⑥ `_cleanup_temp_files` 的异常处理加牙齿

修复 ② 时发现，「缺陷被静默」的元凶正是那个笼统的 `except Exception`。改为**按类型分流**：

| 异常 | 处理 |
|------|------|
| `OSError`（占用/权限/不存在，**可预期**） | 仅告警 |
| 其它（`NameError`/`AttributeError`… = **代码缺陷**） | 打 `[内部错误]` 后 **re-raise** |

避免同类缺陷再次被「清理失败」四个字掩盖。

### 验证

| 项目 | 结果 |
|------|------|
| 全库疑似 `NameError` | 3 → **0** |
| 全库同类内重复定义 | **0**（历史修复保持） |
| 7 个改动文件 AST | 全绿 |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |
| re-export 一致性 | 18 符号**零缺失**（不会 `ImportError`） |
| `build.py` 真实执行 | `exec` 前 12 行不再抛 `NameError` |
| `shutil.rmtree` / `Mapping` 语义 | 实测通过 |

### 顺带发现（未改，记录待议）

| 项 | 说明 |
|---|---|
| `app/core/video_processing/cpp_engine/build.py` | `logger` 曾被错放在文件中部（`:71`），而 `:10` 起就在用 → **该构建脚本从未成功跑过**，一执行即 `NameError`。本轮已把定义提到文件头 |
| `_tmp_original_timeline.py`（根目录 159KB） | 拆分 `timeline_widget.py` **之前的原始快照**，零引用、带 BOM、含调试代码。属临时备份，**未删待用户确认** |
| `root` 目录 31 个 py 文件 | 多数零引用（`count_code.py` / `scan_*.py` / `_nav_diag*.py` / `_test_breakdown*.py` 等），另 `monitor_service.py` 依赖**已下线的** `app.modules.lego.data_collector` → 一 import 即失败 |
| `app/modules/plugins/*` | 零引用第二套插件体系，`pyqt_plugin_manager.py` 用 `import *` |
| `pyqt_plugin_manager.py:10` | **模块导入时**执行 `os.makedirs("plugins")` → 在 CWD 创建文件夹的副作用 |

### 保留不变量

冻结区 85 locks 完好、`_clips` 唯一真相源、磁吸阈值与卡片尺寸未动、音画纠偏 ~280ms。

---

## V4.31.0 (2026-09-19) — 全库体检修复（5 项工程加固，零功能变更）

> **背景**：依据《全库代码评价报告》（2026-09-19）的缺陷清单，按「风险从低到高 + 改动收益」排序做修复。报告结论为「工程化中期偏上、未到生产级」，核心卡点是**防御有骨架没牙齿**——自检只 warning、异常静默吞、跨线程共享数据无锁。本轮把这个卡点逐条补上。

### ⑤ `_clips` 并发加固（本轮核心 · 唯一真·数据损坏风险）

**实测：全文件 `threading.Lock/RLock` 创建 0 处、`with self.<lock>` 0 处**，而 `_clips` 是**跨线程共享的真相源**：

| 接触方 | 路径 | 线程 |
|--------|------|------|
| 画布桥 | `project_snapshot.set_full_clips_provider` / `set_clips_writer`（`editor_module.py:591-592`） | **HTTP 线程** |
| 自动保存 | `_autosave_project` → `export_project` → `json.dump`（每 3s 防抖触发） | 主线程（定时器） |
| 渲染/导出 | 72 个只读方法遍历 `_clips` | 主线程 |

修复的三处：

| 位置 | 原缺陷 | 后果 |
|------|--------|------|
| `export_project:4524`（原） | `"clips": self._clips` 把**引用**交给 `json.dump` | dump 遍历期间列表被 append → 抛 `RuntimeError` 或**写出半截列表的损坏工程文件** |
| `agent_replace_timeline_clips:7895→7918` | `self._clips = []` 后逐个 `append`，**非原子** | 画布写回瞬间，渲染/导出/autosave 读到**空时间线** |
| `import_project:4776→4799` | 同上 | 导入工程瞬间同上 |

新增 `self._clips_lock = threading.RLock()`（`__init__:480`）+ 公开原子快照接口 `_clips_snapshot()`（`:7867`），并把 provider 从裸 `list(self._clips)` 改为 `self._clips_snapshot()`（`:591`）。

**并发压测证据**（3 线程 × 60 轮，写者做非原子替换 + 两个读者做 `json.dump`）：

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 读到不完整列表 | **120 次** | **0 次** |
| `RuntimeError` | 0 | 0 |
| 死锁自检（RLock 嵌套取锁） | — | **OK**（可重入，不挂） |

> 120 次「读到不完整列表」正是用户侧现象：**画布写回瞬间导出/自动保存，产出的工程文件片段丢失**。

顺带修正 `agent_replace_timeline_clips` 中 `break` 的**缩进错误**——原 `break` 与 `if` 同级（在 `for` 循环体首行），导致「主选优先视频片」**只检查了 `_clips[0]`**、循环形同虚设。

### ① 删除调试代码（`editor_module.py` −73 行）

`_report_video_import_debug` 向 `http://127.0.0.1:7777/event` 发 HTTP（`timeout=0.8`），**挂在入片热路径**上，共 1 处定义 + 5 处调用（`:1340-1349` / `:1355-1363` / `:1378-1383` / `:8908-8918` / `:9026-9031`）。删除时暴露一个**真 Bug**：`logger` 在原 `:54` 才定义，而原 `:51` 的 `logger.debug(...)` 已引用它 → **`except` 分支一执行即 `NameError`**。备份：`editor_module.py.bak_before_debug_removal`。

### ② 消除字符串协议（新建 `app/core/agent_constants.py`）

`"waiting_approval"` 原**硬编码在 4 文件 8 处**，产出方（`capability_dispatcher`）与消费方（`agent_loop`）靠**字面量握手**——改一处文案即**静默破坏整条审批流**。现统一为 `ERR_WAITING_APPROVAL`（错误通道）与 `STATUS_*`（状态机，语义域刻意分开），全库残留仅 `_verify/check_agent_loop.py:116` 测试夹具 1 处。

### ③ 能力目录守卫「加牙齿」（`capability_handlers.py`）

启动自检原三处**全部只 `logger.warning`**、自身异常还降级为 `logger.debug`——等于没有守卫。现抽出 `_run_startup_selfcheck(dispatcher) -> Dict`，结果存模块级 `_STARTUP_SELFCHECK` 并汇总为**一条可见摘要**（含计数），自身异常升为 `logger.warning(exc_info=True)` 并计入 `guard_errors`；新增公开只读接口 `get_startup_selfcheck()`。

### ④ 清理状态机/资源管理路径的静默 `except`

| 位置 | 原静默内容 | 为何必须留痕 |
|------|-----------|-------------|
| `clip_widget.sleep_media_workers` × 3 | `_thumb_debounce.stop()` / `_media_worker_gate.cancel_owner()` / `_thumb_gen_token += 1` | **token 自增失败 → 旧缩略图任务回写覆盖新状态**，表现为「拖动后缩略图错帧」这类极难复现的 bug；gate 取消失败 → worker 泄漏 |
| `timeline_widget._clear_marquee_state` × 2 | `grab_w.releaseMouse()` / `_apply_selection_visual()` | **releaseMouse 失败 → 该 widget 继续吃鼠标事件 → 框选卡死**；视觉复位失败 → 选中态不刷新 |

全部改为 `logger.debug(..., exc_info=True)`，并在代码中注明「为何这处不能静默」。`clip_widget.py:1242` 保留的 `except RuntimeError: pass` 是**有意**的——C++ 侧已析构属正常时序，已在原处加注释说明。**UI 绘制类的静默按原样保留**（不制造日志噪音）。

### 验证

| 项目 | 结果 |
|------|------|
| `editor_module.py` AST | OK |
| `clip_widget.py` / `timeline_widget.py` AST | OK |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |
| 并发压测 | 不完整读 120 → **0**；RLock 死锁自检 OK |
| 行数 | `editor_module.py` 9406 → **9450**（锁与快照方法净增） |
| 全库残留检查 | `waiting_approval` 硬编码仅剩测试夹具 1 处 |

### 保留不变量

音画纠偏 ~280ms（冻结区）、冻结区 **85 locks** 全完好、`_clips` 为唯一真相源（未抽 `TimelineModel`——它涉及 196 处提及 / 72 个读方法，属上帝类拆分另一半工程，风险不可控，本轮刻意不做）、磁吸阈值与卡片尺寸全部未动。

---

## V4.30.1 (2026-09-19) — 画布版本号治理（画布 0.1.0 → 0.2.0）

> **背景**：用户问「画布的那个版本号为什么没有进行一个迭代升级」。核查确认：`vendor/shiguang-canvas` 是**独立子项目**，其版本号被硬编码在 **3 处**且自项目建立起一直停在 **`v0.1.0`**，历经 V4.21~V4.30 十余轮画布改动**从未维护过**——而该版本号**真实显示在画布导航栏右上角**（`.ic-nav-ver`），导致「主程序已 4.30.0、画布还写 0.1.0」的严重脱节。

### 版本号策略（用户裁定）

**画布独立版本号**——画布版本线与主程序**刻意不同步**，画布可单独迭代交互/视图，不必等主程序发版。

### 行为变更

| 位置 | 处理 |
|------|------|
| `src/canvasVersion.ts` | **新增** — 画布版本的**单一事实来源**：`CANVAS_VERSION`（`0.2.0`）/ `_LABEL`（`v0.2.0`）/ `_CODENAME`（「磁吸手感成型」）/ `_TITLE`（tooltip 文案） |
| `src/CanvasShell.tsx:827` | 删硬编码 `version="v0.1.0"`，改传 `CANVAS_VERSION_LABEL` + `CANVAS_VERSION_TITLE` |
| `src/AppNav.tsx:37` | **删除默认值** `version = "v0.1.0"` → `version` 改为**必填**（漏传会在界面直接暴露）；新增 `versionTitle` 参数接 tooltip（原 tooltip 写死「拾光导演台」） |
| `package.json` | `version` `0.1.0` → **`0.2.0`**（与常量对齐） |
| `docs/knowledge/frozen_zones.json` | `canvasVersion.ts` 与 `AppNav.tsx` **纳入 zone 保护**（后者此前不在清单内）；新增 1 条不变量；追加解冻记录 |

画布版本定为 **`0.2.0`**（MINOR）——因 V4.29.0/V4.30.0 已实质改动画布交互（跟手浮起 / 单轴吸附 / 落座动画 / 空间记忆 / 整列让位），属功能级变更而非补丁。

### 修复的实际缺陷

| # | 缺陷 | 证据 |
|---|------|------|
| 1 | **画布版本号从未维护**：3 处硬编码各自停留在 `v0.1.0` | `package.json:4` / `CanvasShell.tsx:827` / `AppNav.tsx:37` 全部为 `0.1.0`；同一时刻主程序 `app/version.py` 已是 `4.30.0` |
| 2 | **默认值掩盖了漏传**：`AppNav` 的 `version = "v0.1.0"` 让「忘记传参」也能正常渲染，没有任何提示 | 改为必填参数后，任何漏传都是编译期错误 |

### 保留不变量

主程序版本号（`app/version.py`）与画布版本号仍是**两套独立**体系；画布功能、磁吸阈值、卡片尺寸、落位基准 全部不变。

### 验证

| 项 | 结果 |
|----|------|
| tsc --noEmit | 改动 3 文件 **0 错误**；存量错误仍只在 `riggedHumanoid.ts` / `Stage3D.tsx`（与基线一致） |
| vitest | **58 passed / 7 文件全绿** |
| vite build | 成功（4.00s，**298** 模块 ← 297+1 = 新增 `canvasVersion.ts`） |
| dist 产物 | `"0.2.0"` 进包、`v0.1.0` **已消失**、codename 与 `title` 链路接通（`sT="0.2.0"` → `` lT=`v${sT}` `` → `.ic-nav-ver`） |
| frozen_zone_guard | 漂移恰 1 文件（`CanvasShell.tsx`，与预期一致）→ 补登记 2 文件 → `--update` → **`OK frozen zones intact (85 locks)`** |

### 发布清单（新增 · 防止再次漏维护）

改动画布后，**必须同时**执行：

1. 改 `vendor/shiguang-canvas/src/canvasVersion.ts` 的 `CANVAS_VERSION`
2. 同步 `vendor/shiguang-canvas/package.json` 的 `version`（无 `v` 前缀）
3. 在本文档新增/更新画布版本段落
4. 若主程序也发版：**两个版本号各自独立递增**，不要互相拷贝

## V4.30.0 (2026-09-18) — 整列让位（手机主屏手感第 2 条机制）

> **背景**：V4.29.0 落地了手机主屏手感的第 1、3、4 条（跟手浮起 / 靠近吸附 / 格点落位），P2「整列让位」当时标注为「完全缺失」。本轮把它补上：**把卡片拖到一个已被占用的位置时，那一行/列的卡片会让开一格**，而不是让你把卡片叠上去。

### 新增模块（vendor/shiguang-canvas/src/magnetic/）

| 文件 | 职责 |
|------|------|
| `reflow.ts`（新） | 纯函数 `planReflow(draggingRect, others, config)` → `{ ghost, shifts, axis, blocked }`。**一对多的位移规划**，与 `computeMagnetic`（一对一吸附落点）、`computeBonds`（静态咬合）、`SpatialAnalyzer`（布局模式识别）职责正交 |
| `SlotGhost.tsx`（新） | 落位预览：`ViewportPortal` 内画 2px 虚线坑位框（`#378ADD` + 淡蓝填充 + 圆角 16），标示拖拽卡松手后将占住的位置。**纯展示**，不参与任何计算 |
| `reflow.test.ts`（新） | 15 条回归测试，覆盖三条红线 + 层叠排除 + 左右/上下双向让位 + 锚点选择 + 配置生效 + 纯函数无副作用 |

### 三条红线（设计约束）

| # | 红线 | 实现 |
|---|------|------|
| ① | **只推同一行 / 同一列** | 垂直于让位轴方向投影重叠 `≥ MIN_OVERLAP(40px)`——与 `bonds.ts` 同一把尺子，避免出现「算作咬合但不算挡路」的自相矛盾。斜对角卡一律不推 |
| ② | **链式只推一格，绝不递归** | 链上卡片**整体平移** `step = 卡尺寸 + LANDING_GAP(-2)`（= 238 / 198），相对间距不变，没有「越推越远」的放大 |
| ③ | **撞非链卡即断** | 推动后若链尾与某张链外卡变成「同行 + 紧贴」，整条链放弃（`blocked: true`），宁可不让位也不撞乱别人的布局 |

另加一条前置排除：**层叠不让位**——落位矩形在让位轴上也已插进某卡（两轴均重叠）时，属层叠语义，交给层叠徽章处理。

### 行为变更

| 位置 | 处理 |
|------|------|
| `magnetic/useMagneticDrag.ts` | 新增 `reflowPlan` state；`onNodeDrag` 用磁吸算出的 `snapPos` 作为落位矩形调 `planReflow`，**只记录预览**；`onNodeDragStop` 执行落位，顺序为「**邻居先滑开（`animateNodesTo` / 180ms）→ 拖拽卡再落进 `ghost`**」 |
| `magnetic/useMagneticDrag.ts` | 新增 `animateNodesTo(shifts, duration)`：批量平移邻居，**单次 `setState`**（避免 n 张卡各建一个动画帧循环），从各卡**当前真实位置**起算，不带过冲（过冲是拖拽卡落座的专属手感） |
| `magnetic/useMagneticDrag.ts` | 返回值新增 `reflowPlan` |
| `CanvasShell.tsx` | 引入并挂载 `<SlotGhost plan={reflowPlan} />`（`magneticActive` 时），透传 `reflowPlan` |
| `docs/knowledge/frozen_zones.json` | `canvas-magnetic-intent` 的文件清单补登记 2 个新文件；新增 2 条不变量（整列让位 / 让位与吸附·咬合的分工）；`reason` 追加第 2 次解冻记录 |

### 修复的实际缺陷（开发中自曝）

| # | 缺陷 | 证据 |
|---|------|------|
| 1 | **链生长误用候选池阈值**：候选池按「离落位点 `≤ weakDistance(120)`」筛选，但链上第 2、3 张卡天然离落位点越来越远。沿用该阈值会把链截断成单卡，随后红线③的「链外卡」检测把**本该在链上的卡**误判成障碍，导致一条正常的链被整条否决 | 回归用例「链整体推一格」实测 `blocked=true`（应为 `false`）；改为链生长遍历**全部节点**后转绿 |
| 2 | **层叠判据用错轴**：初版用 `overlapOn`（垂直于让位轴的重叠）判层叠，与 `MIN_OVERLAP` 同源，导致**所有正常让位都被误判为层叠**而直接返回 | 7 个用例同时失败（`axis` 全为 `null`）；引入 `overlapAlong`（让位轴**本身**的重叠）后恢复，仅剩 2 例真问题 |
| 3 | **红线③判据在推动前不可触发**：「同行 + 紧贴」必然被链生长吸收，因此「推动前紧贴的链外卡」恒为空集——该判据永远为假 | 改为**预测碰撞**：把链整体平移 `step` 后检查链尾是否与链外卡变成「同行 + 紧贴」 |

### 保留不变量

拖拽中**绝不覆写任何卡位置（含邻居）**、卡片尺寸 **240×200**、磁吸阈值 **120/50/60/10px**、贴合落位 **`gap=-2`**、三段式阻力（30/50/`bondGiveRatio=0.28`）、`snapToGrid` 关闭、方向无语义、拖拽占位缝、大圆角色块、空间记忆第一层配色红线（只改颜色） 全部不变。

### 验证

| 项 | 结果 |
|----|------|
| tsc --noEmit | 本任务 4 文件 **0 错误**（存量 67 行错误全在 `riggedHumanoid.ts`/`Stage3D.tsx`，与基线一致，非本轮引入） |
| vitest | **58 passed / 7 文件全绿**（43→58，新增 15 条让位回归） |
| vite build | 成功（4.22s，**297** 模块 ← 295+2）；dist 产物正向断言：`#378ADD`、`rgba(55, 138, 221, 0.06)`、`2px dashed`、`borderRadius:16`、`reflowPlan` 导出 全部进包 |
| frozen_zone_guard | 漂移恰 **2** 文件（与改动一致，无扩散）→ 补登记 2 新文件 → `--update` 后 **`OK frozen zones intact (83 locks)`** |
| 不变量同步 | 新增 2 条；`docs/现行技术文档.md` 同步（锁点 81→83、文件数 29→31） |

### 已知未做（下一轮）

- **`beginGraphEdit` 推迟到松手**：解「按下瞬间全图 JSON 深拷贝」卡顿（`CanvasShell.tsx:1498` → `history-store.ts:47 cloneGraph`）。
- **`hypot(gapX, gapY)` 合并双轴**：水平已贴合时垂直稍拉开就吸不上，应改分轴独立判定。
- **`medium` 死档**：`strongDistance(60)` 排在 `mediumDistance(50)` 前，`gap∈[50,60)` 永远命中 strong，medium 不可达。
- **让位与磁吸的耦合**：当前让位只在磁吸命中（`level !== "none"`）时计算，无磁吸时不会让位。

## V4.29.0 (2026-09-18) — 跟手浮起 + 单轴吸附 + 空间记忆（下一代概念首落）

> **背景**：用户裁定「借鉴手机操作系统桌面的排序拖拽手感，再往里面加入靠近即吸附」。手机主屏手感 = **跟手浮起 + 整列让位 + 靠近吸附 + 格点落位**，而本项目原实现「进入 120px 范围即整卡瞬移」+「吸 X 轴时把 Y 也拽走」，与该手感**恰好相反**。本轮修前三条，并把「下一代概念」的第一层（空间记忆）一并落地。

### 行为变更（vendor/shiguang-canvas/src/）

| 位置 | 处理 |
|------|------|
| `magnetic/useMagneticDrag.ts` `onNodeDrag` | **删除 `writeNodePos`**——拖拽中不再覆写卡片位置，卡片 1:1 跟指针走；只记录 `magState`（「若现在松手会落在哪」）。推翻 V4.28.2「进入范围即整卡瞬移」 |
| `magnetic/MagneticEngine.ts` `getSnapPosition` | 新增 `dragPos` 参数，**只动被吸附的那一轴**：吸左右时 `y` 取 `dragPos.y`（不再硬取 `targetPos.y`），吸上下时 `x` 取 `dragPos.x`；`stack` 除外。`computeMagnetic` 调用处传入 `{x: dragRect.x, y: dragRect.y}` |
| `magnetic/useMagneticDrag.ts` `onNodeDragStop` | 吸附落座改用 `animateNodeTo(snapAnimationMs=200)` **平滑滑入**（不再瞬间 `writeNodePos` 跳过去）；强吸附（strong/instant）带 `overshootPx(5)` 过冲，weak/medium 不带 |
| `novice/NoviceCard.tsx` | 挂 `data-depth`（= 已有 `intentDepth` 1~3）；顺修陈旧注释（圆角 4px → 实际 16px） |
| `novice/novice-cards.css` | 新增 `[data-depth]` 三档配色（surface 提亮提饱和 / semantic 基准 / implementation 降饱和降亮）。**严格只改 `filter` + 描边透明度**，不改尺寸、不加 `box-shadow`、不改圆角 |
| `magnetic/MagneticEngine.test.ts` | 新增「单轴吸附」describe（3 例）：吸左右时 y 不被拽走、吸上下时 x 不被拽走、同轴时新旧结果一致 |

### 修复的实际缺陷

| # | 缺陷 | 证据 |
|---|------|------|
| 1 | **「上下吸附不对」的真实根因**：`getSnapPosition` 的 `case "left"/"right"` 硬取 `y: targetPos.y` | 几何实测：目标 T=(1000,1000)，拖拽卡在 T 右侧水平间隙 10px、垂直错开 180px 时，落点 y 被拉回 1000 —— **瞬移一整个卡高（200px）** |
| 2 | **卡顿正反馈**：拖拽中每帧 `writeNodePos` → 重建 nodes 数组 → 触发全店重渲染 + 每帧重算 bonds/`bondedSidesMap` + `SpatialIndex` 重建 | `useMagneticDrag.ts:245`（V4.28.2 引入），**越靠近目标越卡** |
| 3 | **「按下瞬间」卡顿** | `CanvasShell.tsx:1498 onNodeDragStart → beginGraphEdit()` → `history-store.ts:47 cloneGraph` → `JSON.parse(JSON.stringify(nodes))` 全图深拷贝（**本轮未改，留待 P2**） |

### 保留不变量

磁吸阈值 **120/50/60/10px**、卡片尺寸 **240×200**、贴合落位 **`gap=-2`**、三段式阻力（30/50/`bondGiveRatio=0.28`）、`snapToGrid` 关闭、XYDrag 时序、方向无语义、拖拽占位缝、大圆角色块、`.nv-card.on` 白色描边环 全部不变。

### 验证

| 项 | 结果 |
|----|------|
| tsc --noEmit | 本任务 4 文件 **0 错误**（存量 67 行错误全在 `riggedHumanoid.ts`/`Stage3D.tsx`，Three.js 类型，非本轮引入） |
| vitest | **43 passed / 6 文件全绿**（40→43，新增 3 条单轴吸附回归） |
| vite build | 成功（4.32s，295 模块）；dist CSS 正向断言 `[data-depth="1"]`/`[data-depth="3"]`/`saturate(1.15)` 全部进包 |
| frozen_zone_guard | 漂移恰 4 文件（与改动一致，无扩散）→ `--update` 后 **`OK frozen zones intact (81 locks)`** |
| 不变量同步 | 改写 2 条过时项（「instant 拖拽中直接 writeNodePos」「靠近即吸附瞬移」）+ 新增 3 条（跟手浮起/单轴吸附/落座动画/空间记忆红线） |

### 已知未做（下一轮）

- ~~**P2 整列让位**（手机主屏第 2 条机制）：完全缺失，需新增 `reflow.ts` + `SlotGhost.tsx`。~~ → **已在 V4.30.0 完成**
- **`beginGraphEdit` 推迟到松手**：解「按下瞬间全图 JSON 深拷贝」卡顿。
- **`hypot(gapX, gapY)` 合并双轴**：水平已贴合时垂直稍拉开就吸不上（写回归测试时被暴露，见测试内注释）。
- **`medium` 死档**：`strongDistance(60)` 排在 `mediumDistance(50)` 前，`gap∈[50,60)` 永远命中 strong，medium 不可达。

## V4.28.2 (2026-09-18) — 磁吸卡片 · 靠近即自动吸附

> **背景**：用户裁定「把磁吸卡片改成只要靠近就会自动吸附」。推翻 V4.28.0/V4.28.1 的「instant 档（gap<10px）直接 snap + weak/medium/strong 三档渐进吸引」模型——渐进吸引的「平滑被吸过去」手感不达预期，改为只要进入磁吸范围就立刻贴齐。

### 行为变更（vendor/shiguang-canvas/src/magnetic/）

| 位置 | 处理 |
|------|------|
| `useMagneticDrag.ts` `onNodeDrag` | 对 `weak/medium/strong/instant` **一律直接 `writeNodePos` 到 snapPos**，废除 `getMagneticOffset` 渐进吸引分支 |
| `useMagneticDrag.ts` `onNodeDragStop` | 松手把卡片**钉回落点**（抵消 XYDrag 结束时的鼠标位置覆写，否则直接吸附会在松手瞬间「回弹脱开」），并对形成咬合者闪光「已吸附」 |
| `MagneticEngine.ts` | 删除 `magneticStrength` / `getMagneticOffset` 两个死函数；`computeMagnetic` 的 level 判定与 `levelRank`（instant:4 最高档）保留，仅用于目标优先级与 UI 反馈 |
| `MagneticEngine.test.ts` | 删 `magneticStrength` / `getMagneticOffset` 两个 describe 块（5+3 用例），`computeMagnetic` 方向吸附 + levelRank 回归保留 |

### 保留不变量

磁吸阈值 **120/50/60/10px**、卡片尺寸 **240×200**、贴合缝机制（`bondedSidesMap`+`gap=-2`）、交互态、三段式阻力（30/50/`bondGiveRatio=0.28`）、`snapToGrid` 关闭、XYDrag 时序全部不变。

### 验证

| 项 | 结果 |
|----|------|
| vite build | 成功，新 bundle 验证 `getMagneticOffset` 清空、直接吸附路径进包 |
| vitest | 40 passed（删 9 个强度/偏移用例后，MagneticEngine.test.ts 14→5） |
| tsc --noEmit | 本任务文件 0 错误 |
| frozen_zone_guard | `OK frozen zones intact`（invariants 改写「靠近即吸附」后 --update 重锁） |

## V4.28.1 (2026-09-18) — 剥离方向业务语义 · 磁吸回归纯空间

> **背景**：用户质疑「为什么上下是对照关系？我什么时候跟你说过这是对照关系」。核实确认：早期规格文档 v3.1 给空间方向（left/right/top/bottom/stack）硬套了「输入/输出/对照/分支/导演卡/历史」业务语义，**用户从未确认过**，属过度设计。拍板方案 A——彻底剥离方向业务语义，磁吸回到纯物理空间关系。

### 删除的臆造语义（7 处 + 1 组件）

| 位置 | 处理 |
|------|------|
| `magnetic/types.ts` | 删除 `DIRECTION_SEMANTICS`、`SOFT_CONNECTION_SEMANTICS` 两套语义表 + `Bond.color` 死字段；`SpatialDirection` 注释改纯方位 |
| `magnetic/SnapSlotHighlight.tsx` | **整个组件删除**（六向槽位彩色语义条 + 标签 + "松手即吸附"） |
| `magnetic/MagneticLines.tsx` | 删方向语义标签胶囊，只留蓝色占位缝 |
| `magnetic/SoftConnectionLines.tsx` | 删语义标签，虚线改统一中性青色 |
| `magnetic/bonds.ts` | 删 `DIRECTION_SEMANTICS` 引用 + `color` 赋值 |
| `novice/NoviceInspector.tsx` | 删「六向放置」图例 |
| `magnetic/SpatialAnalyzer.ts` | 布局 description 文案去「对照关系/版本对照/备选方案/一场戏」等臆造猜测，改纯几何描述 |
| `CanvasShell.tsx` | 移除 SnapSlotHighlight 渲染 |

### 保留

`SpatialDirection` 类型（纯物理方位，Bond 咬合 side 计算 / getSnapPosition / bondedSidesMap 依赖它）、`BOND_COLORS`（拉扯阻力反馈色：拉伸琥珀/临界红/落座绿/断裂红，非语义）。

### 验证

| 项 | 结果 |
|----|------|
| vite build | 成功，新 bundle 验证「对照/备选/版本对照/历史版本/松手即吸附/一场戏」全清、`#378add` 占位缝 + `fbbf24` 阻力反馈保留 |
| vitest | 49 passed |
| tsc --noEmit | 本任务文件 0 错误；存量错误全在 riggedHumanoid/Stage3D（Three.js，非本任务） |
| frozen_zone_guard | `OK frozen zones intact (81 locks)`（files 30→29、六向语义 invariant 改写为「方向无语义」） |

## V4.28.0 (2026-09-18) — 磁贴画布 1+4 结合 · 大圆角色块 + 蓝色占位缝

> **背景**：用户反馈「小白模式 UI + 磁贴胶囊卡片操作/吸附逻辑仍不如人意、未达商用水准」，且难以用文字精确描述。经 4 套可视化方案（①Windows 磁贴风 ②白板对齐线风 ③节点拼图风 ④列表块风）供选择，用户拍板 **「1+4 结合」** = Windows 磁贴无缝吸附 + 列表块大圆角/蓝色拖拽占位线。

### 改动（全部在 vendor/shiguang-canvas，走完解冻纪律）

**① 卡片视觉（novice/types.ts + novice-cards.css）**

| 维度 | 旧（V4.24.0 四周灯光包围） | 新（1+4 结合） |
|------|--------------------------|---------------|
| 圆角 | 4px | **16px** |
| 卡片身体 | 四周一圈发光光晕（1px 亮芯 + 双层 box-shadow） | **深色实色块** `#151a26` + `1px rgba(255,255,255,0.08)` 描边，去光晕 |
| 类型色 | `.nv-card::before` 左缘内缘色条 | **标题栏整块背景承载**（`.nv-card-head` background=var(--nv-accent)，文字改深色 `#0f1115`） |
| 选中态 | 绿色灯光 | **白色描边环** `border #fff` + `0 0 0 1px rgba(255,255,255,0.35)` |

**② 拖拽占位线（MagneticLines.tsx）**

弯曲发光磁力线（Q 曲线 + 两端发光圆点）→ **蓝色直线占位缝**（`#378ADD`，3px 核心线 + 10px 柔光晕 opacity 0.25，滤镜 seam-blur）。占位缝标在**目标卡被贴的那条边全长**：目标在右→贴其左缘竖线、在左→右缘、在下→上缘横线、在上→下缘、stack→目标整卡外框。方向语义标签胶囊保留。

**③ 修复 V4.23.1 遗留 bug（MagneticEngine.ts + magneticLevels.ts）**

`computeMagnetic` 的 `levelRank` 映射漏 `instant` 档——`instant` 会被后遍历到的 `strong/medium` 错误覆盖，正是「instant snap 时灵时不灵」的根因。补 `instant:4`（最高档）并加回归测试；`magneticLevels.ts` 等级元数据表补 `instant` 档（消除 tsc 类型错误）。

### 验证

| 项 | 结果 |
|----|------|
| vite build | 成功（4.03s），新 bundle 验证 `#378add`/`seam-blur`/`instant:4` 进包、旧 `mag-glow` 滤镜移除 |
| vitest | 49 passed（6 文件，含 2 个新回归：instant strength=1.0 + levelRank 优先） |
| tsc --noEmit | 本任务文件 0 错误；存量错误全在 riggedHumanoid.ts / Stage3D.tsx（Three.js 类型，非本任务） |
| frozen_zone_guard | `OK frozen zones intact (82 locks)`（invariants 24→25，追加解冻登记后 --update） |

**未动**：磁吸阈值 120/50/60/10、卡片尺寸 240×200、贴合缝机制（bondedSidesMap+gap=-2）、三段式阻力、snapToGrid 关闭、XYDrag 时序。

## V4.27.2 (2026-09-18) — 导航折叠图标 · Agent 面板贴右

> **背景**：用户发截图反馈两个 UI 问题：① 导航栏隐藏折叠后不显示各模块图标；② AI 画布 Agent 展开后交互界面不在最右边靠齐。均已定位根因并修复，问题②涉及 `canvas-magnetic-intent` 冻结区，走完解冻纪律。

### 问题① 根因（main_window.py · NavigationBar.add_module）

`MainWindow.__init__` 的执行顺序：`_setup_ui()`（第 606-611 行按持久化 `nav_mode=compact` 调 `set_collapsed(True)`）→ `_setup_default_modules()`（创建按钮）。而 `set_collapsed(True)` 只循环 `self._buttons`——此时**还是空表**，折叠没作用到任何按钮；随后每个新按钮按**展开态**初始化（text=`"  🏠  首页"`、`text-align:left + padding-left:16px`、不限宽），塞进 60px 窄栏（可用 44px）后文字被裁没 → 图标消失。

> 之前独立脚本 `_nav_diag.py` 因「先加模块再折叠」顺序相反，一直复现不出来；换真实 `MainWindow` 复现（`_nav_diag2.py`）后，诊断数据显示按钮 `text='  🏠  首页'` / `minW=0 maxW=16777215`，与用户截图吻合。

### 问题① 修复

`NavigationBar.add_module` 创建新按钮时继承栏当前折叠态：`if self._collapsed: button.set_collapsed(True)`。覆盖全部三条建按钮路径（`register_module` / `register_module_lazy` / 运行时 `_apply_module_changes_impl`）。

### 问题② 根因（styles.css）

`agentPanelOpen` 时 inspector `<aside>` 本就不渲染（冻结不变量已锁定「Agent 打开时隐藏右侧设置面板」），DOM 只有 `sidebar / canvas-wrap / AgentPanel` 三个子元素，但 `.workspace.agent-open` 仍是 4 列模板 `200px 1fr 240px minmax(300px,360px)`——残留的 240px inspector 列把 AgentPanel 挤进第 3 列，最右 360px 空置。

### 问题② 修复

`.workspace.agent-open` 系列 grid 由 4 列改 3 列 `200px 1fr minmax(300px,360px)`（删除 240px 残留列）；`right-collapsed` 对 Agent 面板无效（Agent 打开期间始终贴右）。磁吸行为/阈值/卡片尺寸/贴合缝机制全部不变。

### 验证

| 项 | 结果 |
|----|------|
| 问题① 回归（真实 MainWindow） | 按钮 text 从 `'  🏠  首页'`→`'🏠'`，`minW/maxW` 从 `0/16777215`→`44/44`，图标恢复居中显示 |
| vite build | 成功（4.20s），新 3 列 grid 已进 bundle（`index-*.css`），旧 240px 残留列消失 |
| frozen_zone_guard | `OK frozen zones intact (82 locks)`（canvas-magnetic-intent 追加解冻登记后 --update） |

## V4.27.1 (2026-09-17) — 磁吸方向修复

> **背景**：用户反馈「胶囊卡片上下吸附不准、左右吸附会直接甩到最右边、左边吸不上」。定位为方向 180° 反了的 bug，属 `canvas-magnetic-intent` 冻结区，走完解冻纪律。

### 根因（MagneticEngine.ts）

`computeMagnetic` 里 `getDirection` 返回「**目标相对拖拽**」的方位（`dx = 目标中心 - 拖拽中心`，用于六向语义标签），却被**直接**传给 `getSnapPosition`（其语义 =「**拖拽节点应放到目标哪一侧**」）。两者相反：

| 目标在… | getDirection 返回 | 错误 snap 到 | 正确应 snap 到 |
|---------|------------------|-------------|---------------|
| 拖拽右侧 | `"right"` | 目标右侧（甩到最右） | 目标**左侧** |
| 拖拽下侧 | `"bottom"` | 目标下侧 | 目标**上方** |

### 修复

- 新增 `oppositeDirection()`（left↔right / top↔bottom，stack 不变），`getSnapPosition` 调用前取反；`best.direction` 仍保留原方位供 `MagneticLines` 语义标签展示（六向语义不变）。
- 新增 4 个方向回归测试（`MagneticEngine.test.ts`：目标在右/左/下/上四向，断言 snap 落点在目标正确一侧）。

### 验证

| 项 | 结果 |
|----|------|
| vitest | 12 passed（含新增 4 个方向测试） |
| vite build | 成功（296 modules，新 bundle `index-hQPYlemz.js`），方向取反逻辑 `dT`/`fT` 已进 bundle |
| frozen_zone_guard | `OK frozen zones intact (82 locks)`（canvas-magnetic-intent 追加解冻登记后 --update） |

## V4.27.0 (2026-09-17) — 知心秘书 · 有温度的剪辑助手

> **背景**：用户希望 Agent 不只是「冰凉的机器」，而是「知心秘书」。经三轮确认：称呼由用户自定义、温度做成可切换开关（默认轻量省 token、开启才多耗）、下一步走「记忆深挖」。纯新增，不涉冻结区。

### 改动 1：秘书人格与称呼管理（app/core/agent_persona.py 新建）

- 温度分档：`lite`（默认，一句语气提示 ~30 token）/ `full`（完整人格 + 称呼 + 偏好召回 + 多轮历史 + 秘书问候 + 空闲关怀）。
- 称呼与开关都落 `memory_store.user_preference`（key 区分），不新开存储。
- 人格延续 `affect_model` 边界：语气可暖、**不说假拟人话**；四条铁律（不编造关心/不谄媚/记得不复述/有温度没灵魂）。

### 改动 2：温度开关 UI + 主动关怀（editor_agent_panel_mixin.py）

- Agent 面板标题行新增「🌡 知心秘书：开/关」+「✏️ 称呼」按钮（`QInputDialog` 自定义称呼）。
- 开关默认关；首次打开轻量档给成本提示，让用户自行决定开不开。
- 完整档打开时秘书问候（有称呼→欢迎回来 XX，无→引导起名）；空闲 30 分钟主动关怀（每分钟检查、自愈重置）。

### 改动 3：接通多轮历史（editor_agent_panel_mixin.py + editor_module.py）

- `_build_edit_agent_messages` 完整档拼入 `agent_sessions.get_history_messages("editor")`（轻量档不接、省 token）。
- 新增 `_record_agent_turn`：结果回调里写入本轮，历史只在「一轮完整结束」后追加，避免与当前 user 重复。

### 改动 4：长期记忆召回用户偏好（memory_store.py）

- `get_agent_context` 新增 `include_preferences=False` 参数，完整档才召回 `user_preference`（排除称呼/开关自身），让「记住用户的事」进入 system prompt；默认关保持零额外成本。
- 修复：偏好召回**先过滤再截断**——称呼/开关条目 score 高，若先 `limit` 会把偏好挤掉，导致召回为空。

### 改动 5：记忆深挖——从对话自动提炼偏好（editor_agent_panel_mixin.py）

- `_record_agent_turn` 里新增 `_mine_preference_from_chat`：本地规则检测用户话里的偏好信号词（我喜欢/我习惯/我偏好/以后/下次/尽量/最好…），命中且长度适中则原句归档 `user_preference`（`key=auto_note`）。
- 零 token（不调模型）、去重防刷屏、不阻塞主链路；始终进行，完整档召回使用。
- 定位对齐项目特性：挖的是「用户在剪辑 Agent 里说的话」，天然落在剪辑/生成偏好，不跑偏到生活琐事。

### 验证

| 项 | 结果 |
|----|------|
| py_compile | 4 文件全通过（agent_persona / memory_store / editor_agent_panel_mixin / editor_module） |
| 隔离验证 | `_verify/test_agent_persona_manual.py`：默认 lite/称呼读写/开关心态/问候/偏好召回/信号词检测 全通过（临时存储、不污染真实记忆） |

## V4.26.0 (2026-09-17) — 模型网关统计 · Token 消耗与用量仪表盘

> **背景**：用户提出「模型管理里做网关统计，统计所有接入大模型的 token 消耗程度与使用情况」。经确认做「完整版」（含真实 usage + 趋势 + 缓存命中 + 预算告警 + 异常检测）。纯新增功能，不涉冻结区。

### 改动 1：计量持久化层（app/core/gateway_stats.py 新建）

- SQLite 落盘 `usage_log` 表（每次调用：provider/model/prompt+completion token/耗时/成败/错误/成本/是否缓存命中），重启不丢。
- 聚合查询：`total_summary()` / `by_provider()`（按成本降序）/ `trend(days=14)`（按天补零）/ `recent()` / `health()`（24h 失败率 + P95 + token 突增）。
- 单例 + threading.Lock + WAL；record 失败仅告警不抛出（计量不拖垮主链路）。

### 改动 2：真实 token 采集（替代估算）

- `cloud_providers/base.py`：`__init__` 加 `last_usage`；新增 `_extract_usage(data)`（无 usage 返回 0 触发降级）。
- `providers.py`：**19 个 OpenAI 兼容 provider** 非流式分支批量加 `self.last_usage = self._extract_usage(data)`（`replace_all` 统一接入；wenxin/claude 等非兼容 provider 自动保持估算）。
- `ai_engine.py`：调用前取 provider 实例引用，调用后读 `last_usage` 覆盖估算值；拿不到则沿用「中文 0.6/字」估算。

### 改动 3：AIEngine 网关接入

- 缓存命中计数 `_cache_hits/_cache_total`；缓存命中 / 成功 / 失败（`_on_failure`）三类都落盘 gateway_stats。
- `get_gateway_snapshot()`：一次返回 总览/按供应商/趋势/最近/健康/缓存命中/熔断/预算。

### 改动 4：网关统计仪表盘（gateway_stats_panel.py 新建）

- 模型管理 `_main_tabs` 新增「📊 网关统计」tab：总览卡片（总调用/token/成本/成功率/缓存命中率）+ 供应商明细表 + 14 天趋势 + 最近调用 + 告警横幅（预算超支 / 熔断 / token 突增）。
- 3s 自动刷新 + 手动刷新按钮。

### 验证

| 项 | 结果 |
|----|------|
| py_compile | 6 文件全通过（gateway_stats / ai_engine / base / providers / panel / model_management） |
| 端到端存储 | 4 条测试记录 → 聚合/降序/趋势/缓存命中/P95/失败率 全部正确，测试 DB 已清理 |
| usage 提取 | 有 usage 提取正确、无 usage/null 返回 0 触发降级；providers 接入 19 处 |
| frozen_zone_guard | `OK frozen zones intact (82 locks)` |

## V4.25.2 (2026-09-17) — 导航栏折叠图标残缺修复

> **背景**：用户发截图反馈「折叠后的导航栏不能显示完整的图标，悬浮显名也用不了」。纯 PyQt6 布局 bug，不涉冻结区。

### 根因（几何账算错，两刀叠加）

| # | 问题 | 证据（main_window.py） |
|---|------|------|
| ① | 折叠宽 56px，但主布局边距仍是展开态左右各 16px → 按钮可用空间仅 56-32=**24px**，塞 44px 固定宽按钮**被裁掉一半** | `set_collapsed` 原 `setFixedWidth(56)` + `_setup_ui` 原 `setContentsMargins(16,20,16,20)` 未随折叠调整 |
| ② | 按钮六态样式表全部写死 `text-align:left; padding-left:16px`（展开态设计），折叠态没有切居中 → 图标即使可见也**偏右** | `NavigationButton._update_style` 六处硬编码 |
| ③ | 悬浮显名失效是①的连带：按钮可 hover 面积被裁剩 24px，tooltip 难触发 | — |

### 修复

- **折叠几何**：折叠宽 56→**60**；`set_collapsed` 时主布局边距动态收窄为左右各 8（展开恢复 16/20/16/20）→ 可用 44px 与按钮折叠固定宽 44 **精确吻合**。
- **样式参数化**：`_update_style` 六态样式表 `text-align`/`padding-left` 抽为 `palette["align"]`（折叠=`center; padding-left:0`、展开=`left; padding-left:16px`）；`set_collapsed` 末尾触发 `_update_style()` 重算（此前切换折叠不重算样式）。
- **折叠按钮居中**：窄栏内 `»/«` 切换按钮水平居中（`_logo_layout` 存引用 + setAlignment）。
- **tooltip 增强**：折叠态悬浮显名带上图标：`f"{icon} {text}"`。

### 验证

- `py_compile main_window.py` 通过；Qt6 实例重启后折叠态图标完整居中、悬浮显名恢复（用户目测验收）。

---

## V4.25.1 (2026-09-17) — 画布白屏修复 + 单实例锁 + 端口健康探测

> **背景**：用户发截图反馈 AI 画布整页白屏、状态卡「正在加载画布页面… 127.0.0.1:3011」。诊断定位两个结构性根因，落地两个加固项。
> **解冻**：stage3d-core 授权解冻（仅 canvas_runtime.py 端口探测逻辑，未动 18765/3011/3010 任何端口值，基线重写 82 锁点 intact）。

### 根因（psutil 实测）

| 环节 | 发现 |
|------|------|
| ① 多实例叠加 | 机器上 4 个残留 python（两对 shim+真身），含旧会话遗留旧实例 |
| ② 旧实例霸端口 | 旧实例占 3011 画布静态 + 18765 桥接，但 socket 只剩 LISTEN 壳、不响应请求 |
| ③ 新实例误判 | `port_open()` 只做 TCP 探活，误判「端口开着=服务就绪」→ 加载死监听 → 白屏 |
| ④ 干扰项 | 系统代理 127.0.0.1:53872 未排除 localhost，诊断时 urllib 走代理测出 502 假象 |

### 改动 1：端口探测加固（canvas_runtime.py）

- 新增模块级 `http_probe(url)`：无代理 GET（`ProxyHandler({})`）校验 200 + 响应体含画布挂载点，避开本机代理干扰。
- 新增 `CanvasRuntime._port_serves_canvas(port)`：`port_open` + `http_probe` 双重健康校验。
- `is_ready()` / `_start_static_server()` 的「端口占用则复用」由纯 TCP 探活升级为 HTTP 健康校验；半死监听**不复用**。
- `_start_static_server` 的 OSError 分支补友好提示（「端口被占用但服务不健康，可能有残留进程」）。

### 改动 2：单实例锁（main_qt6.py）

- QLocalServer/QLocalSocket 单实例守卫：第二个实例检测到主实例 → 写 `activate` → 退出（在 `_init_modules` 之前拦截，省下 MainWindow 初始化）；主实例收到 `activate` 则 `show/raise_/activateWindow`。

### 验证

| 项 | 结果 |
|----|------|
| 半死监听对比 | 旧 `port_open`=True（误判）/ 新 `http_probe`=False（正确识别） |
| 单实例锁 | 实例 B 日志「检测到已运行的编辑器实例…本实例退出」，且早于 `_init_modules` |
| py_compile | canvas_runtime.py / main_qt6.py 均通过 |
| frozen_zone_guard | 重写基线后 `OK frozen zones intact (82 locks)` |

## V4.25.0 (2026-09-17) — 画布资产自动分类整理

> **背景**：用户提出「画布资产里加一个自动分类整理算法，把各种资产自动分类，按类别与文件夹收纳形式展现」。经确认采用「类型 + 语义细分」两层方案 + 文件夹网格点开导航。本版本仅改前端 vendor（未触碰冻结区）。

### 改动 1：分类引擎（localLibrary.ts）

- 新增 `AssetTypeKind` 三类型：`image/video/text`，标签 `图片/视频/文本`。
- 新增 `AssetSemantic` 五类：`character/scene/storyboard/cover/other`，标签 `角色/场景/分镜/封面/未分类`。
- `SEMANTIC_RULES`：正则按优先级命中（**角色 > 场景 > 分镜 > 封面**），匹配 `title + prompt`，规则可读可预期、**零随机**。
- `semanticOfAsset(a)`：确定性判类，兜底 `other`。
- `buildAssetTree(assets)`：构建「类型 → 语义」两层文件夹树；文本类型仅一层（无语义细分）；只返回 `count > 0` 的文件夹，避免空文件夹；返回 `{ types, folders, foldersOfType }`。

### 改动 2：资产页三层导航（StudioPages.tsx）

- 新增 `assetNav` 状态：`null` = 顶层类型文件夹；`{kind, semantic:null}` = 语义层；`{kind, semantic}` = 资产列表。
- 顶层类型文件夹 → 语义文件夹 → 资产卡片，面包屑（`全部分类 / 图片 / 角色`）+ 侧栏「← 返回分类」按钮。
- 搜索态直接平铺结果，不套文件夹；空态提示「暂无本地资产 / 没有匹配的资产」。

### 改动 3：文件夹视图样式（assets-folder.css 新建）

- `.asset-folder-grid`：响应式网格 `repeat(auto-fill, minmax(150px, 1fr))`。
- `.asset-folder-card`：文件夹卡片（📁 图标 + 名称 + 数量徽章），沿用画布暗色主题（`#1a1a1a→#131313` 渐变、`#262626` 边框），hover 上浮 3px + 青色灯光 `rgba(34,211,238)` 光晕，与磁吸卡片同源视觉。
- `.asset-breadcrumb`：面包屑导航条。

### 验证

| 项 | 结果 |
|----|------|
| vite build | exit=0，新 bundle StudioPages-BSfaFlpN.js + StudioPages-BF6aL2gF.css |
| dist 验证 | 类名 asset-folder-card/breadcrumb 进 JS+CSS；语义规则英文关键词 storyboard/portrait/landscape/poster/character 进共享 chunk |
| tsc --noEmit | 本任务文件 StudioPages.tsx / localLibrary.ts 0 错误（存量 40 错误全在 riggedHumanoid.ts / Stage3D.tsx 的 Three.js 类型） |
| frozen_zone_guard | OK frozen zones intact (82 locks)，未触碰冻结区 |

## V4.24.0 (2026-09-17) — 四周灯光包围 + 贴合即连接

> **解冻**：canvas-magnetic-intent 授权解冻（CanvasShell.tsx / novice-cards.css / styles.css 三文件，invariants 三处修订 + 一条新增，基线重写 82 锁点 intact）。设计经多轮渲染对照确认后落地。

### 改动 1：四周灯光包围（推翻「咬合侧隐形」）

 novice-cards.css：

| 项 | 旧（V4.23.x） | 新（V4.24.0） |
|----|--------------|---------------|
| 卡片描边 | 1px #2a2f42，贴合边透明+直角 | 1px 亮芯 rgba(165,243,252,.75)，四角完整 4px |
| 光晕 | 无 | 0 0 10px rgba(34,211,238,.16) + 0 0 3px rgba(165,243,252,.55) |
| 选中态 | accent 色 1px ring（贴合时退纯投影） | 绿色灯光 rgba(187,247,208,.85) + 0 0 12px rgba(74,222,128,.22) |
| 类型色条 | border-left 3px | .nv-card::before 内缘伪元素（z-index:1，不破坏灯光圈） |

贴合处由相邻两圈灯光并排成「双光带」分界——无缝贴合 + 边界一眼可见，两全。

### 改动 2：贴合即连接（砍掉贴上后的连线与徽章）

- CanvasShell.tsx onSoftDragStop：移除 pushSoftConnection 自动生成——吸附 strong 时不再画软连接虚线与「此节点输出」方向徽章（用户裁定：贴上了就是连上了，双重表达违反无感化）。
- softConnections 状态与固化/丢弃链路保留（恒空、渲染空列表），未来手动血缘可复用；SOFT_CONNECTION_SEMANTICS 标签定义保留。

### 改动 3：修复 Agent-IM 面板按钮竖排

- styles.css .sg-agent-head：dock 窄面板下 flex 收缩把「暂停/继续/停止/收起」压成一字宽竖排。加 flex-wrap:wrap；按钮与 chip 加 flex-shrink:0 + white-space:nowrap。

### 验证

| 项 | 结果 |
|----|------|
| vite build | exit=0，新 bundle index-B27K2DWC.js |
| dist 验证 | pushSoftConnection 调用=0；发光样式进 CSS；bonded 透明规则 0 残留 |
| test_magnetic_instant_snap / check_canvas_capabilities / check_canvas_node_capabilities | 全部 exit=0 |
| frozen_zone_guard --update → 复核 | OK frozen zones intact (82 locks) |

## V4.23.2 (2026-09-17) — 磁吸真正上线 + 小白网格对齐贴合落位

> **背景**：用户发截图反馈「磁吸还是做不到 Win11 磁贴那样」。定位出两个根因，其中一个是流程级缺陷：**改了 src ≠ 改了产品**。
> **解冻**：canvas-magnetic-intent 授权解冻（store.ts 网格步进 + invariants 补条款 + 基线重写，82 锁点 intact）。

### 根因 1（流程级）：dist 从未重建，V4.23.1 等于没上线

- 实测旧 bundle dist/assets/index-D-E9awmy.js（构建于 09-16 18:53）：instantDistance 出现 **0 次**，磁吸配置仍是旧值 weakDistance:80 / strongDistance:25。
- 上轮回归脚本「dist 提取失败 fallback 源码 grep」掩盖了这一事实——只验证了 src，没验证 bundle。
- **修复**：vite build 重建 dist（新 bundle index-Dsa4pWgD.js），验证 instantDistance=2 处、阈值 120/50/60/10 全部进入运行时。

### 根因 2（布局级）：小白自动布局步进与卡片尺寸不匹配

- store.ts 拉片布局（breakdownScript）与导演卡拆解（breakdownDirectorCard）：x 步进 **230**、y 步进 200。
- 卡片 CARD_SIZE = **240×200** → 相邻卡水平**重叠 10px**：超出 bondTolerance(2px) 不构成 Bond 咬合，视觉却近乎贴死；用户一拖开（gap>80px）旧磁吸完全拉不回——这正是截图里「两张卡大缝隙对不齐」的来源。
- **修复**：x 步进 230→**238**、y 步进 200→**198**（= CARD_SIZE − 贴合落位 gap=-2，与 invariant 一致）。生成即贴合位：边距 -2 ≤ 2px 容差、投影重叠 ~198px ≥ MIN_OVERLAP(40px) → **直接构成 Bond 咬合**，拖一张整组联动；拖开再拖回 gap<10px 触发 instant snap 立刻咬死。

### 顺带发现（未改，登记在案）

- store.ts:2438 addStudioNode 落点用 Math.random()——与「拒绝随机效果」红线相悖，待专项处理。

### 回归

| 项 | 结果 |
|----|------|
| _verify/test_magnetic_instant_snap.py | exit=0 全绿 |
| 新 dist 验证（instantDistance/阈值/步进 238·198/旧 230 清零） | 通过 |
| frozen_zone_guard 默认检查 | 仅 store.ts 漂移（预期内）→ --update → 复核 OK 82 locks |

## V4.23.1 (2026-09-17) — 磁吸「边对边立刻贴齐」（对齐 Win11 磁贴手感）

> **解冻**：`canvas-magnetic-intent` 经用户授权解冻（追加改动，reason 已补记录），改完重锁（82 锁点 intact）。仅改磁吸数学层，不动视觉层/贴合缝/交互态。

### 改动 1：放大磁吸阈值（数学层）

`vendor/shiguang-canvas/src/magnetic/types.ts`：

| 字段 | 旧值 | 新值 |
|------|------|------|
| `weakDistance` | 80 | **120** |
| `mediumDistance` | 50 | 50（不动） |
| `strongDistance` | 25 | **60** |
| `instantDistance` | — | **新增 10** |

### 改动 2：新增 instant 等级（拖拽中直接 snap）

`MagneticEngine.ts`：

```ts
// 判断磁吸等级（2026-09-17 用户裁定：新增 instant 档）
let level: MagneticResult["level"] = "none";
if (gap < config.instantDistance) level = "instant";   // 新增
else if (gap < config.strongDistance) level = "strong";
else if (gap < config.mediumDistance) level = "medium";
else level = "weak";
```

`magneticStrength`：

```ts
if (level === "instant") return 1.0;   // 新增：直接 snap
if (level === "strong")  return 0.45;
if (level === "medium")  return 0.24;
if (level === "weak")    return 0.12;
```

`useMagneticDrag.ts`：

```ts
if (result.level === "instant" && result.targetId) {
  // 直接 writeNodePos 到 snapPos，不走 getMagneticOffset 渐进
  writeNodePos(draggingNode.id, { x: result.snapX, y: result.snapY });
  setMagState({...});
} else if (result.level !== "none" && result.targetId) {
  // 原渐进吸引分支不动
}
```

### 未触碰的不变量（实读确认）

- 卡片尺寸 **240×200**（`CARD_SIZE`）
- 交互态（hover/active/选中）+ 视觉层（CSS）
- 贴合缝机制（`bonds.ts` / `bondedSidesMap` / 落位 `gap=-2` / NoviceCard `bonded-*` class）
- 三段式阻力（`stretchThreshold=30` / `breakThreshold=50` / `bondGiveRatio=0.28`）
- `snapToGrid=关闭`
- React Flow v12 `XYDrag` 先写 store 再回调时序
- 落位过冲 `overshootPx=5` / 回弹 `snapAnimationMs=200ms`
- 六向语义 / Bond 只识别左/右/上/下四向

### 副库同步策略

`vendor/AI-Canvas-tauri/src/libtv/magnetic/` 是旧版（无 Bond/overshoot/stretch/break/instant 概念），与主库已漂移。按工作记忆「副库漂移为已知状态」，本轮**仅主库同步**。副库磁吸代码保持旧版不动。

### 回归

- 新增 `_verify/test_magnetic_instant_snap.py`（4 阈值 + magneticStrength 映射 + instant 分支不走渐进 + 未触碰不变量数值）—— 全绿
- 既有 `_verify/check_canvas_node_capabilities.py` + `check_canvas_capabilities.py` + `check_capability_catalog.py` —— exit=0 零破坏
- `scripts/frozen_zone_guard.py --update` 重写基线 —— `OK frozen zones intact (82 locks)`

### 解冻记录（已写入 `frozen_zones.json` reason）

> 2026-09-17 用户授权解冻（追加改动）：放大磁吸阈值 weak 80→120、strong 25→60（medium 50 不动）+ 新增 instant 等级（instantDistance=10，magneticStrength=1.0，拖拽中 gap<10 直接 writeNodePos 到 snapPos，对齐 Win11 磁贴「边对边立刻贴齐」手感）；卡片尺寸 240×200 / 贴合缝机制（bonds/bondedSidesMap+gap=-2）/ 交互态 / 三段式阻力（30/50/bondGiveRatio=0.28）/ snapToGrid=关闭 / XYDrag 时序 全部不变；改完重新上锁。

---

## V4.23.0 (2026-09-16) — 吸附全贴合无缝（磁贴式）+ 画布控件避让

> **解冻**：`canvas-magnetic-intent` 经用户授权解冻（今日第五次，冻结区 reason 已补记录⑤⑥），改完重锁（82 锁点 intact）。磁吸行为/阈值/阻力手感不变，只改贴合处视觉层与控件位置。

### ① 吸附描边透明化——两卡贴合处融为一块（用户裁定，对齐图 3 Windows 磁贴）

用户实测 V4.22.0 无缝化后接缝**仍有可见描边线 + 圆角缺口**：贴合边两条描边（1px 灰 + 3px 类型色 accent）叠成一条实色线，选中态还有 1px 外圈 ring。本次把贴合边彻底隐形：

- **咬合侧隐形表**：`bonds.ts` 新增 `bondedSidesMap()`——`bond.side` 描述「b 相对 a」，故 **a 隐 side 边、b 隐反方向边**（stack 层叠不产生贴合边）；纯几何推导、不落盘，与 Bond 同源同刷新周期。
- **下发链路**：`CanvasShell` 与 `bonds` 同一个 `useMemo` 周期算出 `bondedSides`，`useEffect` 写入 `store.bondedSides`（**瞬态 UI 态，不落盘**，与 proEditNonce 同类）；`NoviceCard` 订阅自身 id 的贴合方向，挂 `bonded-left/right/top/bottom` class——卡片自身不重复推导，单一计算点。
- **CSS**（`novice-cards.css`，排在 `.nv-card.on` 之后保证覆盖选中态）：贴合边 `border-*-color: transparent` + 贴合边两角**圆角归 0**（消除贴合角缺口）；选中态存在任一贴合边时 `box-shadow` 退为纯投影（1px ring 无法按边隐藏，会让接缝重新显形）。
- **圆角归属收口**：`NoviceCard` **移除内联 `borderRadius`**（内联会压过 `.bonded-*` 直角规则），圆角统一由 `novice-cards.css` 管理（4px，与 `CARD_GEOMETRY.radius` 对齐；head/foot/zoomed-out 同步 8→4）。
- **回归测试**：新增 `src/magnetic/bonds.test.ts` 5 项——右/左、下/上方向语义、重叠不足 40px 不咬合、三卡横排中间两侧都隐、田字格四卡各隐两边。
- 与 V4.21.1 无感化互补：**静止贴合既不画缝、也不留描边**；上下左右吸附统一生效。

### ② 左下角竖排缩放控件避让底栏（用户裁定「把竖排的向上挪一点」）

- `styles.css`：`.react-flow__controls.react-flow__panel { bottom: 68px !important }`——React Flow 自带竖排缩放控件（+/−/适配）原本贴底（15px），与 `libtv-dock`（资产管理行，bottom:10px、顶边 ≈52px）同处左下角相互压盖、图标重叠看不清；上移至 68px 完全抬到 dock 上方。

### 回归（全绿）

- `tsc --noEmit`：本轮 5 个改动文件（bonds/CanvasShell/store/NoviceCard + CSS×2）**0 编译错误**（68 行报错全为 riggedHumanoid/Stage3D 既有历史问题）。
- `vitest`：`bonds.test.ts`（新 5 项）+ `MagneticEngine.test.ts`（8 项）**13 passed**。
- `frozen_zone_guard`：漂移清单恰好本轮 6 文件、无意外漂移 → invariant 补「咬合侧隐形」「竖排控件避让」两条 → `--update` 重锁 → `OK frozen zones intact (82 locks)`。
- `check_canvas_dual_repo`：无新增漂移（61 一致 / 22 基线内分叉 / 13 基线内缺失）。

---

## V4.22.0 (2026-09-16) — 意图胶囊卡片交互分级 + 导航栏模式

> **解冻**：`canvas-magnetic-intent` 经用户授权解冻（第②次今日，冻结区 reason 已补记录），改完重锁（82 锁点 intact）。磁吸行为/阈值/阻力手感不变。

### ① 画布意图胶囊卡片交互升级（用户三项抱怨全部落地）

- **卡片内直接输入**：`NoviceCard` 单击选中后，内容区主文本原位变成输入框（`nv-card-editor`，`nodrag`/`nowheel` 防误拖），绑定 `KIND_TEXT_FIELD`（types.ts 新增，镜头/图片/视频/音频/音乐/生成器/动画/全景 → `prompt`，剧本/文档/文本/便签 → `content`，导演卡 → `script`，数字人 → `line`，提示词 → `text`）——全部是 node-factory 真实字段，专业模式原样可见。
- **单击 / 双击分级**：双击卡片 → `store.requestProEdit()`（新增 `proEditNonce` 信号）→ `NoviceInspector` 自动展开 L2 进阶设置进入精细编辑。
- **L1/L2 参数类型化**：`NoviceInspector` 按节点真实字段渲染——
  - L1：景别（shot）/ 画质（shot/image/video）/ 时长（shot/video/audio/music）/ 运动幅度、相似度（仅 video）；`applyQuality` 按类型分派（video 无 steps/补帧字段不伪造）。
  - L2：镜头 → 运镜/焦段/光圈/补帧开关/角色绑定（可解绑）；图片 → 补帧；视频 → 首帧/尾帧权重；音乐 → 风格/纯音乐/歌词；生成器 → 产出数量/产出类型/自动汇聚；动画 → 动作/帧数/帧率；数字人 → 角色名/台词；全景 → 水平/俯仰视角；纯文本类 → 「没有进阶参数」提示。
- **L3 折叠展开**：L2 底部新增「▸ 专业参数（L3）」向下展开箭头（`nv-insp-pro`/`nv-pro-arrow`），展开显示 steps/cfg/seed/补帧模式/目标帧率——仅渲染该类型真实拥有的字段。
- **假字段清除**：移除 `aspectRatio`/`styleStrength`/`negativePrompt`——三者不在 node-factory 类型定义中，bridge.ts 生成请求与后端 `canvas_aigc.py` 均无消费（写进 data 也不生效，属欺骗性设置）；冻结区 invariant 明确「不许复活」。
- **Agent 打开时聚焦交互界面**（用户追加）：`CanvasShell` 中 `agentPanelOpen` 时，右侧 `inspector`（小白 `NoviceInspector` / 专业「项目+选中节点」参数面板）整体不渲染，右侧只保留 Agent-IM 侧栏，界面聚焦到 Agent 对话；关闭 Agent 后设置面板恢复。
- **吸附贴合无缝化**（用户追加，对齐 Windows 磁贴观感）：① `MagneticEngine.getSnapPosition` 落位 gap `0 → -2`——相邻两卡描边互相融合成一条实色细线，消除此前两条描边并排形成的 2px 暗缝，上下左右吸附统一生效（重叠 ≤2px 在 Bond 容差内，磁吸/咬合/阻力行为不变）；② `.nv-card` 补 `box-sizing: border-box`——此前 content-box 下卡片 DOM 实占 244×202，与落位基准 240×200 差 2~4px；③ 卡片圆角 `8 → 4`（`CARD_GEOMETRY.radius`）——贴合边四角缺口减半。

### ② 主程序导航栏（PyQt6）

- **修复图标重叠根因**：`NavigationBar._setup_ui` 中 `logo_layout.addWidget(logo_widget)` 把容器加进**它自己的布局**（自嵌套），Qt 布局计算错乱导致 logo 与折叠按钮叠加——改为 `layout.addWidget(logo_widget)` 加入主布局。
- **悬浮显名**：`NavigationButton` 展开态不再清空 tooltip（原来只有折叠态悬浮才显示名称），两种模式悬停均显名。
- **主题设置新增「导航栏」显示模式**：设置 → 外观 → 主题设置 →「导航栏」下拉（显示图标和名称 / 仅显示图标（悬浮出名称））；`nav_mode` 写 QSettings 持久化，下拉即时生效（`settings_changed` 信号 → `_on_settings_changed` → `NavigationBar.set_nav_mode`），导航栏「«/»」折叠按钮手动切换同样写回同一设置（单一事实源），重启保持。

### 回归（全绿）

- `tsc --noEmit`：本轮涉及文件（novice/*、store.ts、magnetic/*）**0 编译错误**（68 行报错全部为 riggedHumanoid/Stage3D 既有历史问题）。
- `vitest`：5 文件 **38 tests passed**；`py_compile` main_window/settings_module 通过。
- `frozen_zone_guard`：漂移清单仅本轮 6 文件 → `--update` 重锁 → `OK frozen zones intact (82 locks)`；`check_canvas_dual_repo` 无新增漂移。

---

## V4.21.1 (2026-09-16) — 画布吸附视觉无感化

> **解冻**：`canvas-magnetic-intent` 经用户授权解冻一次（用户裁定「吸附提示要无感化，对齐 Windows 磁贴手感」，推翻「咬合缝常驻可见」invariant），改完重锁（82 锁点 intact）。磁吸**行为**（edge-gap 判据 / 80-50-25 阈值 / 吸引力系数 / 三段式阻力 / 回弹过冲）全部不变，只改视觉层。

### 改动（仅 1 个文件）

- **`vendor/shiguang-canvas/src/magnetic/SnapSeam.tsx` 重写**：
  - **静止吸附零视觉残留**：idle 咬合不再渲染任何东西（旧版常驻 9px 粗色带 + 白芯 + 「已吸附」文字胶囊，被用户判定为视觉干扰）；贴合就贴合，画面干净。
  - **瞬态阻力反馈保留**：拖拽拉扯中显示 3px 细线（拉伸中琥珀 `#fbbf24` / 即将断开红 `#f87171`）+ 两端小圆点，越拉越长越细（3→1.5px）；松手即消失。用于解释三段式阻力手感（为什么拖不动/绷住）。
  - **落座/断裂一次性细闪光**：保留 ring 扩散动画但厚度 16→8px，**删除文字胶囊**（Pill 组件整体移除）。
- `CanvasShell.tsx` 调用处 props 接口不变，零改动；`useMagneticDrag.ts` / `bonds.ts` / `types.ts` 等行为层零改动。
- 冻结区 invariant 同步：「咬合缝常驻可见」→「咬合缝无感化（静止零视觉 / 瞬态细线 / 一次性闪光无胶囊）」，reason 补 2026-09-16 解冻记录。

### 回归（全绿）

- `frozen_zone_guard`：漂移清单仅 SnapSeam.tsx 1 文件 → `--update` 重锁 → `OK frozen zones intact (82 locks)`。
- `tsc --noEmit`：SnapSeam.tsx **0 编译错误**（68 行报错全部为 `riggedHumanoid.ts`/`Stage3D.tsx` 既有历史问题，V4.20.0 已记录）。
- `vitest`：**5 文件 38 tests passed**（含 `MagneticEngine.test.ts` 磁吸引擎 8 项）。
- `check_magnetic_levels.mjs` 22 项全过（行为层未动）；`check_canvas_dual_repo` 无新增漂移（SnapSeam.tsx 属主库独有基线内，副库无需同步）。
- 冻结区 4 处文档核对：`08-frozen-zones.md` 已不存在（知识库重组后遗留路径）；`现行技术文档.md` / `frozen-zones.mdc` 中「常驻」均指 plugin-host-ui，无「咬合缝常驻可见」引用，无需改动。

---

## V4.21.0 (2026-09-16) — 本地美学预设包 + Agent 下一步主动建议

> 本轮为两个「参考功能」落地，**未动任何冻结区**（9 区 82 锁点 intact，无需 `--update`）。新增代码走 typed except + logger，未新增 `except: pass` / 裸 `print`。

### ① 本地美学预设包（#45/#46/#47/#48）

- **`app/core/preset_manager.py` 补齐**：原 `import_preset` / `export_preset` / `apply_preset` 三空壳补全为真读写；从纯内存改为 JSON 落盘（`项目根/data/presets.json`，只持久化「用户自定义」数据，默认预设/默认包代码内嵌重建，`_save`/`_load_from_disk` 按 id 去重合并）。
- **新增「美学预设包」概念**：`self.packs` + `list_packs`/`get_pack`/`create_pack`/`delete_pack`/`import_pack`/`export_pack`/`apply_pack`；step 种类 `PACK_STEP_KINDS = color/lut/filter/transition/blend_mode/opacity`（全部 clip 级，写真相源 `_clips`）。内置 4 包：电影感 / 复古暖调 / 日系清新 / 黑白经典。
- **`editor_module.py` 新增 `apply_aesthetic_pack(pack_id, target_clip_id=None)`**：遍历 steps 写片段 `effects`/顶层字段，作为单个 compound action 压撤销栈（一次撤销还原整包），同步时间线 + 预览；`_clips` 真相源兜底同步。新增 `list_aesthetic_packs()` 与 `_apply_selected_aesthetic_pack()`。
- **`editor_color_panel.py` 调色面板新增「🎨 美学预设包」区块**：下拉选包 + 一键套用（作用于当前选中片段）。

### ② Agent 下一步主动建议（#51/#49）

- **新增 `app/core/agent_proactive.py`**：状态→建议规则表 `_RULES`（美学包/转场/调色/字幕/导出 5 类），`suggest_next_actions(state, limit)` 确定性无随机；与 `agent_brain.suggest_next`（被动决策）分工明确——本模块生成候选，brain 负责在候选里选最优。`collect_proactive_state(editor)` 从 EditorModule 只读收集状态快照。
- **`editor_ai_panel.py` AI 面板新增「✨ 下一步建议」区块** + **`ai_agent_panel.py` 新增 `_refresh_proactive_suggestions` / `_apply_proactive_suggestion`**：刷新生成建议卡片，一键采纳双通道执行（`editor_method` 直调 + `capability` 走 dispatcher），执行后自动刷新。

### 回归

- 新增 `_verify/check_aesthetic_pack.py`（默认数据/解析/落盘 roundtrip/导入导出/AST 追踪写真相源）与 `_verify/check_proactive_suggestions.py`（规则命中/健壮/排序/状态收集），**全绿**。
- `apply_aesthetic_pack` AST 静态验证：调用 `_ensure_preset_manager` + `_record_action`（可撤销）+ `_sync_timeline_widget_state` + `_refresh_preview_with_effects`，读写 `self._clips`。

### ③ 遗留清理（上轮两项待办）

- **画布双库漂移收敛（4 项全清）**：主库 `vendor/shiguang-canvas` → 副库 `AI-Canvas-tauri/src/libtv` 单向同步 4 文件——`Stage3D.tsx`（录制运镜）、`storyNodes.tsx`（拉片，主库为副库超集）、`cameraRecorder.ts`/`cameraRecorder.test.ts`（副库补齐）。`check_canvas_dual_repo` 由「失败 4 项」→「OK 无新增漂移」（一致 57→61，无新分叉/新缺失）。
- **`except:pass` 硬红线回降**：265 → **245**（< 存量上限 249）。清理 10 处静默吞异常（`transition_plugin_registry`×2 / `lut_loader` / `canvas_aigc` / `canvas_server`×2 / `canvas_bridge` / `generation_postprocess` / `editor_color_panel`（本轮新增美学包下拉处）/ `ai_agent_panel`），全部改 `logger.debug(..., exc_info=True)`，逻辑不变。`check_code_health --strict` 判定由「需处理」→「OK（无阻断项）」。
- 注：裸 `print` 868 处里 676 处属 `scripts/`+`_verify/` 的 CLI/验证脚本**有意输出**（非技术债），`app/` 内 192 处调试 print 为可选清理项（非 `--strict` 判定）。

---

## V4.20.0 (2026-09-16) — 剪辑生态撑开 + 一键拉片 + 3D 录制运镜

> **解冻**：`canvas-magnetic-intent`（导演卡拆解带出相机计划）+ `stage3d-core`（仅 Stage3D.tsx 纯相机层新增）两冻结区经用户授权解冻后重锁；`frozen_zone_guard --update` 重建基线（82 锁点 intact）。**模型包（riggedHumanoid.ts / bodyFigureUrl / prepareBodyFigureMeshes / loadGLBRiggedHumanoid / GLB 材质 / 骨名映射）零 diff**——漂移清单仅 Stage3D.tsx + store.ts + node-factory.ts + mediaExtraNodes.tsx 四文件。

### ① 剪辑深工具补全（#37）

- 新增 `app/modules/lego/keyframe_curve_editor.py`：关键帧曲线可视化编辑器，拖拽点改 time/value、双击/右键改 10 种缓动、右键删除、点击空白新增；复用 `keyframe_animation.py` 后端插值采样曲线。
- `editor_module.py` 新增 `_open_keyframe_curve_editor()`（选属性通道 → 曲线编辑器 → 合并写回）；时间线标题栏加「📈 曲线」按钮。

### ② 转场生态 8→14（#38）

- 新增 6 个转场插件 `transition_{circle,vert,horz,cover,reveal,smooth}.py`（numpy 预览混合）。
- `transition_plugin_registry.py`：`_CIRCLE_XFADE` 等方向映射 + `xfade_name_for_transition` 6 分支 + `_EXPORT_FIDELITY` 6 个 exact。

### ③ 贴纸生态 12→48（#39）

- `editor_ui_builder_mixin.py` 贴纸库扩到 48 emoji（情感/特效装饰/符号气泡/物品四类）。

### ④ 字幕花字预设 +8（#40）

- `subtitle_manager.py` 内置花字预设库 +8 样式；`editor_subtitle_panel.py` 新增「花字预设」section + `apply_preset_style()` 一键套用。

### ⑤ 脚本→分镜→导演卡补全（#41，解冻 canvas-magnetic-intent）

- `ShotData` 新增 `camera3d?` 字段；`breakdownDirectorCard(directorId, shots, cameras?)` 第三参把 AI 相机计划（机位+运镜 pathPoints）写进分镜卡；`DirectorCardNode.onBreakdown` 拆解后调 `planStoryboardCameras` 串入相机计划。

### ⑥ 一键拉片：视频 → 分镜（#42）

- `canvas_aigc.py` 新增 `video_storyboard_breakdown()`：ffprobe 时长 → `SceneAnalyzer` 镜头检测（PySceneDetect → 帧差 → 均匀切段三级降级）→ ffmpeg 抽代表帧 → cv2 判色调/亮度 → 启发式景别，生成可编辑分镜表（不伪造画面内容）。
- `canvas_server.py` 新增 `@_route_post("/host/video-storyboard")`（路由表注册，非老 if 链）。
- `bridge.ts` 新增 `videoStoryboard()` + `VideoStoryboardShot`；`storyNodes.tsx` 分镜表加「📹 拉片」按钮（上传参考片 → 填分镜表，含画面缩略图）。

### ⑦ 3D 录制运镜（#43，解冻 stage3d-core）

- 新增 `cameraRecorder.ts`（纯相机层）：`CameraRecorder` 采样手动拖动的相机 pos/target 轨迹 → `thinRecordFrames` 抽稀成 pathPoints 动态 Layout。
- `Stage3D.tsx` 相机面板新增「录制运镜」：点录制 → 拖镜头 → 停止 → 写入当前机位（无当前机位则从视角新建）。
- 单元测试 `cameraRecorder.test.ts`（7 用例，全绿）。

### 回归

- `frozen_zone_guard.py`：`OK frozen zones intact (82 locks)`；旧基线备份 `frozen_zones.hashes.bak_20260915.json`。
- 后端：canvas_aigc.py / canvas_server.py ast 语法 0 错误；`check_canvas_routes.py` 契约一致（新路由可达、无死代码/无重复注册）。
- 前端：`tsc --noEmit` 新增代码 0 错误（仅 riggedHumanoid.ts / Stage3D.tsx 既有历史报错，非本轮引入）；`cameraRecorder.test.ts` vitest 7 passed。
- `check_capability_catalog.py`（55↔55）· `check_code_health.py` 复跑；本轮新增代码用 typed except + logger，未新增 `except: pass` 或裸 `print`。

---

## V4.19.0 (2026-09-15) — 账号运营 / 短剧筛选 / AI 剪辑流水线彻底下线

> **解冻**：`plugin-host-ui` + `plugin-store-catalog` 两冻结区经用户授权解冻清理后重锁；`frozen_zone_guard --update` 重建基线（82 锁点 intact）。其余改动均非冻结区。

### 背景：产品方向收敛，砍掉三条旁支

产品北极星收敛为「剪辑精剪 + AI 画布」两条活路径。账号运营、短剧筛选、AI 剪辑流水线（`ai_clip_flow`）三条旁支功能体早已卸载、壳与接线却深埋 30+ 文件、2 个冻结区与 Agent 能力单一事实源，硬删会炸启动。本轮做的是**彻底摘除壳与接线**，并保留 Agent 全链路闭环主线。

### 删除清单

| 类别 | 删除项 |
|------|--------|
| 插件壳 | `app/plugins/drama_finder_plugin/` · `app/plugins/account_ops_plugin/` |
| lego 残留模块 | `drama_crawler.py` · `drama_web_scraper.py` · `drama_send_to_editor.py` · `drama_crawler_example.py` · `account_ops_module.py` · `account_skills.py` · `account_widgets.py` · `account_analyzer.py` · `openclow_engine.py` · `platform_oauth.py` · `data_collector.py` · `workflow_manager.py` |
| 爬虫 API | `bilibili_playwright_api.py` · `douyin_playwright_api.py` · `tiktokhub_douyin_api.py` |
| AI 剪辑流水线 | `app/modules/lego/ai_clip_flow.py` + 子引擎 `integrations/{funclip,videofusion,olive,platforms}`（`autoclip` 保留，仍被 `video_processor` 引用） |
| 测试 | `test_drama_send_to_editor.py` · `test_drama_crawler_static.py` · `verify_drama_real.py` · `debug_drama_filter*.py` · `test_ai_clip_flow_steps.py` · `test_plugin_interface_shells.py` · `verify_playwright_crawler.py` |
| 数据 | `app/data/drama_data.json` · `items.json`/`installed.json` 各 18→16 项 |

### Agent 能力层清理

- `agent_capability_catalog.py`：移除 `account.*` 3 行 + `workflow.start`（保留 `workflow.submit_batch` 与全部 `pipeline.*`）。
- `agent_action_registry.py` / `agent_policy.py`：移除 `account_optimize`、`start_workflow`。
- `capability_dispatcher.py`：移除 `ACCOUNT` 枚举；`capability_handlers.py` 移除 `AccountCapabilityHandlers` 类 + `start_workflow` 方法 + 相关注册。
- `editor_module.py`：移除 `connect_to_workflow` / `_on_workflow_completed` / `_on_workflow_step_completed`（工作流集成段）。

### UI 清理（账号/短剧入口全撤）

- 插件中心 `plugins_module.py`：删除「🎭 短剧筛选」常驻按钮（原连接已删的 `_open_drama_finder_tab`，是运行时崩溃点）+ 短剧筛选 tab。
- 首页 `modules.py`：删除 `AccountAnalyzer` / `OpenClowEngine` 两个内联死类 + 「账号运营」快捷入口 + 欢迎弹窗短剧/账号行。
- `main_window.py`：删除 `drama_finder`/`account_ops` 导航分支 + `target=account` 迁移。
- 帮助 `help_module.py` / 商店 `plugin_store.py` / 数据 `items.json`：去除短剧筛选与账号运营条目。
- `skill_engine.py`：删除 `CATEGORY_ACCOUNT` 分类。

### 保留（关键判断）

`agent_pipeline_orchestrator.py` + `agent_pipeline_router.py` + `ai_video_generation_pipeline.py` 是 **Agent 全链路闭环**（七阶段：分流→生成/剪辑→预览校验→五维打分→脚本→精剪→成片），是可进化 Agent 的主线，**不属于本次「流水线」删除对象**——`ai_clip_flow`（「AI 剪辑流水线」实验模块，默认关、半通、不写 `_clips`）才是「流水线」所指。

### 回归

- `frozen_zone_guard.py`：`OK frozen zones intact (82 locks)`。
- 16 个改动 Python 文件 `ast.parse` 语法校验 0 错误；全库 Grep 确认 `短剧筛选/账号运营/drama_finder/account_ops/ai_clip_flow/account_analyzer/openclow` 无残留悬空引用（仅 `docs/_archive` 历史文档与日志保留）。

---

## V4.18.3 (2026-09-15) — 画布节点级操作后端化（canvas_tools → 统一 capability）

> **零解冻**：改动 `agent_action_registry.py` + `agent_capability_catalog.py` + `capability_handlers.py` + `project_agent_host.py`，均非冻结区。`_verify/check_canvas_node_capabilities.py` 全绿 + `check_capability_catalog.py`（目录 59 ↔ 注册 59）+ `check_canvas_capabilities.py` + `check_agent_action_mapping.py` 复跑零破坏。

### 背景：画布节点操作一直是「前端特判」，未纳入能力体系

画布节点级操作（`queryNodes`/`addNode`/`updateNode`/`connectNodes`/`deleteNode`/`groupNodes`/`breakdown`… 共 15+ 个）此前只在前端 `AgentPanel.executeRemoteTask()` 里硬编码执行（直接操作 Zustand store），后端只能经 `dispatch_canvas_tools` → SSE `task.create` 桥接。这意味着这些操作**不进能力目录、没有 policy effect、没有脑神经元、没有记忆 trace**，且 `run_project_agent_loop` 要为画布 action 单独写一套 executor 特判，与 `editor.*` 能力走 dispatcher 的路径分裂成两套。

### 本轮：把画布节点操作收口成统一后端 capability

节点状态存前端 Zustand，后端无法直接改——唯一通道仍是 `push_to_canvas("task.create")` → 前端 `executeRemoteTask` → `POST /host/agent/reply`。本轮做的是**让这条桥成为 dispatcher 里的一等 capability**：

1. **派生（单一事实来源）**：`agent_action_registry` 新增 `canvas_node_capabilities()`，由 `_CANVAS_ACTION_ROWS` 派生 18 个 canonical 节点 capability（`canvas.<snake_case>`），去别名、去 media_write 生成类；另加 `canvas_action_to_capability()`（含别名归一，`canvas_query`→`canvas.query_nodes`）、`canvas_capability_to_action()`（反向）、`canvas_generation_actions()`。

2. **目录**：`agent_capability_catalog.CAPABILITY_ROWS` 追加 `_canvas_node_catalog_rows()`，policy effect / brain 神经元 / 记忆 trace 三处自动跟进（无需手改）。

3. **handler**：`CanvasCapabilityHandlers.node_action` 统一桥接——反查 capability_id → 前端 action，`push_to_canvas("task.create")` + `wait_for_canvas_reply` 同步等回执。策略/预算/记忆/脑神经元由 dispatcher 统一处理，handler 内不重复 `decide`/`begin_tool_call`（避免双重计费）。

4. **统一 executor**：`ACTION_TO_CAPABILITY` 合并画布节点映射；`run_project_agent_loop` 去掉画布特判，节点级统一走 `_make_dispatcher_executor`（dispatcher），仅 `media_write` 生成类（`runGenerate`/`batchGenerate`）仍走 SSE 桥（前端 `onRequestGenerate` 触发）。

### effect 与 policy

| 类别 | capability | effect |
|------|-----------|--------|
| 只读查询 | `canvas.query_nodes` / `query_timeline` / `select_node` | read（Plan/协作自动放行） |
| 节点写 | `canvas.add_node` / `update_node` / `connect_nodes` / `delete_node` / `group_nodes` / `breakdown` … 15 个 | canvas_write（协作需确认） |

### 回归

- `_verify/check_canvas_node_capabilities.py`（新增）：A 18 个派生注册 / B 目录一致性 0 问题 / C effect / D 映射含别名 / E policy / F handler 诚实失败 / G 生成类仍走 SSE 桥——全绿。
- `_verify/check_capability_catalog.py`：补循环注册识别，目录 59 ↔ 注册 59 一致。
- 复跑 `check_canvas_capabilities.py`、`check_agent_action_mapping.py`：零破坏。

### 后续（未做，明确记录）

- 单轮 `project_agent_chat` 的画布 action 仍直接走 `dispatch_canvas_tools`（绕过 dispatcher，故节点操作在单轮路径暂无脑/记忆 trace）；若要完全统一，需把 `dispatch_canvas_tools` 内部也改走 dispatcher。
- 多轮循环协作模式下，节点写经 dispatcher 门（`waiting_approval`）后，前端 `executeRemoteTask` 的 `askConfirm` 仍会二次确认（纵深防御）；Track B 审批续接打通后可加 `approved` 透传去重。

---

## V4.18.2 (2026-09-15) — 剪辑模块 ↔ 画布 ↔ Agent 通信降延迟

> **零解冻**：改动 `agent_runtime.py`（dispatch 调度）+ `project_agent_host.py`（超时 + 节流常量），均非冻结区。`_verify/test_dispatch_concurrency.py` 全绿。

### 背景：定位延迟链路

用户问「怎么降低剪辑模块、画布、Agent 的通信延迟」。诊断结论：底层是「内存总线 + SSE 长连接」（`canvas_bridge` 端口 18765，同进程 queue.put_nowait 微秒级），**传输本身不慢**，延迟集中在三层设计模式：

| # | 延迟点 | 位置 | 量级 |
|---|--------|------|------|
| 1 | 工具串行派发（逐个 push→wait） | `agent_runtime.py` `for item in tools` | N × 回执往返 |
| 2 | 回执等待超时默认 120s | `dispatch_canvas_tools(timeout=120)` | 最坏 +120s |
| 3 | 跨线程 `_run_on_ui` 120s 阻塞 | `project_agent_host.py` | 主线程往返 |
| 4 | SSE 流式节流 0.08s/24 字 | `chat.delta` | 打字机感知延迟 |

### 本轮改动

1. **工具并行化（P0，收益最大）**：`dispatch_canvas_tools` 拆出 `_dispatch_one_tool` 原子单元，按 action 前缀分档——`effect=read` 工具（`editor.inspect_media`/`get_media`/`get_timeline_context`/`suggest_cleanup`/`canvas.query` 等）用 `ThreadPoolExecutor` 最多 3 路并发派发；写工具（`split_clip`/`trim_clip`/`move_clip`/`ripple_delete_range` 等）仍按序串行，避免时间线写入竞争。一次「5 工具」往返从 5 次压到约 2~3 次。

2. **超时收敛（P0）**：回执等待默认 120s → 写 20s / 读 8s（`_DEFAULT_TIMEOUT`/`_READ_TIMEOUT`）。画布不响应时不再干等 2 分钟卡死整轮。

3. **跨线程收敛（P2）**：`_run_on_ui` 的 `done.wait(120s)` → 5s。

4. **节流参数化（P3）**：`chat.delta` 的 `0.08s/24 字` 提为模块常量 `_DELTA_INTERVAL`/`_DELTA_MIN_CHARS`，长文场景可调小降感知延迟。

### 回归

`_verify/test_dispatch_concurrency.py`：只读并发（3 读 0.05s + 2 写 0.3s 总耗时 0.653s，串行旧逻辑 0.75s）/ 写串行保序 / Plan 拒绝写 / 空列表 / 超时回执——全绿。

---

## V4.18.1 (2026-09-15) — 画布生成 capability 补齐（Agent 亲手驱动 AI 画布）

> **零解冻**：改动 `agent_capability_catalog.py`（目录表）+ `capability_handlers.py`（handler + 注册），均非冻结区。`_verify/check_canvas_capabilities.py` 全绿 + 目录一致性 0 问题。

### 背景：能力真空定位

上一轮（V4.18.0 分析）发现：Agent 对画布只有 `open / sync_models / list_actions` 三个 read 能力，而**生图 / 生视频 / ComfyUI / 拼接 / 图转视频**这些生成能力只能靠前端 `canvas_tools` 的 `runGenerate` 触发，或 `pipeline.generate` 间接触发——AgentLoop 走 dispatcher 时**无法直接驱动画布生成链路**。

### 本轮：新增 5 个 `canvas.*` capability

全部复用 `/host/*` 端点背后的同一批纯 Python 函数，不重复实现：

| 能力 | 复用函数 | effect | paid |
|------|---------|--------|------|
| `canvas.generate_image` | `canvas_aigc.generate_image_openai_compatible` | media_write | ✅ 付费 |
| `canvas.generate_video` | `canvas_aigc.generate_video_via_host` | media_write | ✅ 付费 |
| `canvas.comfyui_run` | `comfy_provider.run_workflow_from_json`（支持 dry-run） | media_write | 免费（本地引擎） |
| `canvas.concat_videos` | `canvas_bridge._run_concat_demuxer/_run_concat_xfade` | media_write | 免费（FFmpeg） |
| `canvas.image_to_video` | `canvas_bridge._image_to_still_video`（含 inbox URL/data URL 归一化） | media_write | 免费 |

- **单一事实源**：目录表 `CAPABILITY_ROWS` 加 5 行 → `policy._CAPABILITY_EFFECTS`、`brain._NEURON_TAXONOMY`、`verify_catalog_consistency` 三处自动派生对齐
- **确认后执行**：effect=media_write，协作模式下这些能力都会 `require_approval`（生成媒体是有副作用的写操作）
- **诚实失败**：缺参/非法入参/文件不存在都在 handler 内早退返回 error，不假成功

### 回归

`_verify/check_canvas_capabilities.py`：A 已注册 / B 目录一致性 0 问题 / C effect·paid 正确 / D policy 确认后执行 / E handler 诚实失败——全绿。

### 剩余边界（诚实说明）

节点级操作（addNode/updateNode/connectNodes/groupNodes/…）仍由前端 `canvas_tools`（`AgentPanel.executeRemoteTask`）执行，不在后端 capability 内——因为节点状态在前端 Zustand store，Python 侧无法直接改。这是「Agent 亲手操作画布节点」的最后一块，若要补需走 SSE `task.create` 推前端执行，属下一阶段。

---

## V4.18.0 (2026-09-15) — Agent 内心状态层（小凌意识公式体系）

> **零解冻**：新增 `app/core/ai/affect_model.py` + 三处非冻结区接线。`_verify/check_affect_model.py` 全绿，`check_brain_routing.py` 复跑全绿（suggest_next 改动零破坏）。

### 背景

用户提供「小凌意识」手稿（10 组公式：感受生成 / 冷热感受 / 激活与进取欲 / 期望生成 / 天然惰性·信任 / SoulDrive / 心理落量 / 学习与期望更新），要求 Agent 达到 libtv（画布引擎）同级的工程水准。解读：按画布引擎的标准——纯函数内核 + 单例状态 + 回归脚本 + 冷启动不变量——给 Agent 补上缺失的「内心状态/动机层」。

### 新增 `app/core/ai/affect_model.py`

公式 → Agent 语境映射（身体状态→运行时环境：预算、失败率、重试、审批事件；全部夹紧 [0,1]）：

- `pain_signal`（②pain=S×I×C）、`discomfort`（③冷/热感受）、`arousal`（④≥0.6 进取/否则保守）、`disappointment`（⑤）、`trust_score`（⑥，α+β=1 保证中性=0.5）、`soul_drive`（⑦⑨，≥0.7 才允许主动建议）、`psych_impact`（⑧乘法结构）、`update_expectation`（⑩EWMA，M0=0.5）
- `AffectState` 单例：累积统计 + 期望模型 + 派生内心量；持久化复用 MemoryStore（category=brain_affect, latest_per_key）

### 接线（全部 try/except 静默降级）

1. `agent_brain.suggest_next(..., trust=None)`：低信任 → 学到的权重向中性 0.5 收缩（因子=clamp(0.5+trust, 0.5, 1.0)，只减幅不反向）；None=不干预
2. `agent_loop._finalize`：每次 run 观察成败/调用密度/审批事件/重试压力
3. `agent_pipeline_orchestrator`：`_consult_brain` 咨询带信任；`_emit_done` 会话结束按决策分支更新期望
4. `agent_console`：新增 `affect` 快照块（pain/trust/arousal/drive/impact + 门控结论），供 UI 直接消费

### 红线保持

冷启动行为与未接入时逐字节一致（空状态 mode=conservative、proactive=False、trust=0.5）；不做 ε 随机探索；永不自动执行写操作；诚实失败。

### 回归

- `_verify/check_affect_model.py`：A 纯公式 / B 冷启动一致性 / C 观察回路 / D 期望模型 / E loop 接线 / F orchestrator 接线 / G console 快照 / H 持久化往返——全绿
- `_verify/check_brain_routing.py` 复跑全绿
- 沙箱注意：config_manager 的 wmic 机器指纹探针会触发 PROGRAM BLOCKED 噪音但被 try/except 吞掉，脚本实际 exit=0（已在脚本 docstring 记录）

### 附

产出 `docs/_reports/2026-09-15-项目定位与迭代方向分析.md`：基于代码实读的项目定位/发展目标/使用人群/不足点清单与迭代优先级。

---

## V4.17.7 (2026-09-15) — 卡片生态补齐 + ComfyUI 转换结果纳入可复用模板闭环

> **零解冻**：全部改动在 `NoviceInspector.tsx` / `novice-inspector.css` / `WorkspaceCanvasMenus.tsx`，均不在冻结区。tsc 改动文件 0 新增错误，vitest 31 项全绿。

### 背景：纠正「模板库没做」的误判

摸码确认**模板系统早已完整存在**（`stores/templates.ts` 5 个内置模板 + `store` 的 `listTemplates/saveTemplate/loadTemplate/deleteTemplate` + 「模板▾」菜单）。真正的生态真空是三点：

1. 小白模式空状态没有任何模板入口，第一步只有「从一句话开始 / 直接生一张图」
2. `saveTemplate` 只能存**整张画布**，没有「选中卡片组」粒度（生态颗粒太粗，无法沉淀一个分镜片段 / 一组 ComfyUI 转换结果）
3. ComfyUI 转换结果没有「沉淀 → 复用」的落点

### 本轮改动

1. **小白空状态「快速开始 · 模板」画廊**（`NoviceInspector.tsx` + CSS）：
   - 新增 `listTemplates` / `loadTemplate` 选择器
   - 空状态把 5 个内置模板（✨）+ 用户自定义模板（💾）并列列出，点选即 `loadTemplate` 载入，与「从一句话开始」「直接生一张图」并列成三条起步路径
2. **`store.ts saveSelectionTemplate`（选择性沉淀）**：只存 `n.selected`（含 `selectedId`）节点 + 两端都在选中集内的连线，返回选中数；空选时给诚实状态提示，不产出空模板
3. **前端入口两处**：
   - `WorkspaceCanvasMenus.tsx`「模板▾」菜单新增「+ 存选中卡片为模板」（与「+ 存为模板」并列）
   - `NoviceInspector` 选中态面板新增「💾 沉淀为模板（选中的卡片可复用）」
4. **ComfyUI 闭环打通**：`applyComfyWorkflow` 产出的节点+连线结构天然与模板一致，用户框选转换结果 → 存选中卡片为模板 → 后续一键复用，完成 ComfyUI → 卡片生态闭环

回归：tsc 报错全为冻结区 `riggedHumanoid.ts` / `Stage3D.tsx` 历史遗留（与本轮无关），改动文件 0 错误；vitest 31 项全绿。

---

## V4.17.6 (2026-09-15) — 代码质量排查 + 修复 5 处真实缺陷

对 V4.17.3~V4.17.5 自检，修复 5 处真实缺陷（均为本轮自产代码的质量问题）：

1. **`comfyToCanvas.ts` graph 格式 edge 推导**：原逻辑冗余（`nodes.some` 内嵌套 `entries.some`）且会推入悬空边 + 重复边。重构为先收集合法节点 id 集合 + `Set` 去重。
2. **`comfyToCanvas.ts` UI 格式 links→edges**：同源同目标的 link（如两条 4→6）会产生重复边，加去重（测试断言随之修正 3→2）。
3. **`store.ts applyComfyWorkflow`**：删除未使用的 `leftKinds` 死变量；删除 `comfyClassType` 脏字段泄漏进 `node.data`（会污染项目序列化）。
4. **`NoviceInspector runIntentBreakdown`**：catch 分支原 `find` 画布上任意一张导演卡，多张导演卡时失败状态会落错；改为 `cardId` 提升作用域，精准定位刚建的那张。
5. **`App.tsx tryConcatToFilm`**：原收集画布所有带媒体节点（历史遗留素材会被误拼进本次成片）；改为只收集本次批量生成的 `shotIds`，保持时间链顺序、过滤非 `success`。
6. **`canvas_server.py still-video`**：`body` 缺 dict 类型校验（传数组会抛 AttributeError）；空数组 `items` 因 falsy 会 fallthrough 到 `paths`；补 dict 校验 + `None` 判空。

回归：前端改动文件 tsc 0 错误、vitest 31 项全绿、后端 py_compile 通过。

### ⚠️ 冻结区与双库基线（用户已确认 `--update`，2026-09-15）

- **GUARD（冻结区守卫）**：报 9 文件"漂移"均为文件级误报——逐条核对 invariants（磁吸阈值 80/50/25、吸引力 0.12/0.24/0.45、Bond 边距≤2px 重叠≥40px、拖拽阻力三段式、画质四档、snapToGrid 关闭）**无一条违反**，全部为非锁定区域增量。已 `--update` 重写基线，恢复 `OK frozen zones intact (82 locks)`。
- **CANVASDUAL（双库漂移）**：7 个新分叉（App.tsx/bridge.ts/CanvasContextMenu.tsx/stage3dScene.ts 等真实功能文件）+ 6 个新缺失（5 个 .test.ts + comfyToCanvas.ts）。用户确认选 A：接受「副库当前落后主库」为已知状态，已 `--update` 纳入基线观察（`OK 双库无新增漂移`）。副库抽包成 `@shiguang/libtv` 的 P0-1 大改造时再统一收敛。

---

## V4.17.5 (2026-09-15) — 成片闭环（补③路径 B）：静帧图 + 真视频混合拼接一键成片

> **零解冻**：`canvas_server.py` 不在冻结区；前端改动文件 `tsc` 0 错误，vitest 31 项全绿。

### 背景：概念 P1「一句话 → 一条能播的片」的最后一环

概念文档 P1 明确写了「15s 片段自动拼（首帧图 + 真视频 + 伪真图）+ 叠加拉长 + 入轨 round-trip」。摸码后发现**后端能力早已齐备**：

- `_run_concat_demuxer`（-c copy 极快）/ `_run_concat_xfade`（带转场）
- `_image_to_still_video`（图转静帧视频 = 伪真图）
- `POST /host/video-batch`（批量生成 + auto_concat）、`/host/video-concat`（拼接）、`/host/batch-to-timeline`（入轨）

**真正缺口是前端**：`onBatchGenerate` 批量生成完只报「成功 N 个」，没有拼成片；拼片逻辑藏在 `onExportBatch`（3D 导演台独立路径），两条线断开。

### 本轮：接线

**① 后端 `canvas_server.py`**：新增 `@_route_post("/host/still-video")`
- 接受三类输入：inbox URL（`/inbox_file/xxx`）、data URL（`data:image/...;base64,`）、本地绝对路径
- 图片复用 `_image_to_still_video` 转静帧视频；视频（.mp4 等）原样返回本地路径
- 统一产出 `paths` 本地路径数组，供拼接用

**② 前端**：
- `bridge.ts` 新增 `imagesToStillVideos(items, duration)`
- `App.tsx` `onBatchGenerate` 完成后自动调 `tryConcatToFilm`：
  - 收集成功节点媒体（shot/image/director/panorama 的 `imageUrl` + video 的 `videoUrl`）
  - 统一走 `/host/still-video` 转本地路径（图片→伪视频，视频→原路径）
  - `concatVideos({ paths, transition_sec: 0.4 })` 拼成一条成片
  - `addStudioNode("video", ...)` 落成片节点（标题含段数+时长，prompt 串联分镜名）

### 回归

- `check_canvas_routes.py` 通过：新端点可达、无死代码、前后端契约一致
- 前端 tsc 0 错误、vitest 31 项全绿

---

## V4.17.4 (2026-09-15) — 意图胶囊回归「解析发动机」（修正概念漂移）

> **零解冻**：仅改 `novice` 目录，改动文件 `tsc --noEmit` 0 错误，vitest 31 项全绿。

### 背景：概念文档 vs 代码实现的断层

概念文档《AI 画布磁吸四向卡片 · 该做不该做决策》里，**意图胶囊**的定义是：

> 横·左 · 意图胶囊：**一句自然语言，点击解析 → 生成剧本脚本 + 场景分镜图**，状态：待解析 → 解析中 → 已出脚本

即它是整个片子的「起点 / 发动机」。但代码里（`NoviceCard.tsx` / `NoviceInspector.tsx`），「意图胶囊」被做成了**卡片底部状态栏里的三个显示层级圆点**（点一下切 `intentDepth`），**没有任何解析能力**——发动机变成了仪表盘装饰灯。

### 本轮修正：空状态「从一句话开始」

`NoviceInspector` 空状态把原来的「从剧本开始」（只建一张空导演卡）升级为真正的意图解析入口：

1. 点「从一句话开始」→ 内嵌输入框展开（`Ctrl+Enter` 快捷提交）
2. 写一句剧情 → 自动建导演卡承载这句话（`script` 写入 + `status: "generating"`）
3. 调 `breakdownStoryboard`（后端 LLM 拆镜）→ `breakdownDirectorCard` 自动铺出一串分镜卡片（横向时间链）
4. 失败诚实落到导演卡（`status: "failed"` + 错误信息），不吞异常
5. 状态流转对齐概念文档：「待解析 → 解析中 → 已出脚本」

配套 `novice-inspector.css`（意图输入框 / 生成按钮 / 取消按钮 / disabled 态）。

### 诚实边界：补 ② / ③ 未在本轮硬做

- **补 ②（四向语义「动起来」→ 上卡全局广播 / 下卡备选收纳）**：需改磁吸 bond 状态传递机制（`computeBonds` 在 `CanvasShell` 运行时计算、不在 store），触碰 `canvas-magnetic-intent` 冻结区，风险高。
- **补 ③（成片闭环 → 一串卡片一键拼 15s 片段）**：P1 大工程，需后端拼片接口配合。

两者是下一阶段的 P1/P2 工程，本轮聚焦把「概念漂移最严重」的意图胶囊修到位，避免半吊子改动。

---

## V4.17.3 (2026-09-15) — 3D 导演台做进小白卡片生态 + ComfyUI 粘贴自动落节点闭环

> **零解冻**：全部改动在非冻结文件，改动文件 `tsc --noEmit` 0 错误，不碰 9 区 82 锁。
> 剩余 tsc 报错均为冻结区（`riggedHumanoid.ts` / `Stage3D.tsx`）历史遗留，与本次无关。

### 一、3D 导演台（director）做进小白模式卡片生态

此前小白模式选中 director 节点只套用通用「你想要什么 / 导演参数」面板，摆姿、机位、截图回写、打开舞台全被降维掉，卡片是「哑卡」。本轮补齐：

- **`NoviceInspector` 专属面板**：`kind === "director"` 时渲染导演台专属面板
  - 「打开舞台」按钮 → 复用 `store.openDirectorForNode`，切入内嵌 Stage3D
  - 主图预览（`imageUrl` / 最近一张截图）
  - 历史截图缩略图网格（点选设为主图，回写 `imageUrl`）
  - 最近机位（`lastCameraName`）+ 镜头意图备注（`prompt`）
- **`NoviceCard` 卡片菜单**：director 卡片新增「打开舞台」入口
- **`types.ts`**：补 director 专属 `noviceHint`；新增 `intentHintFor(kind, layer)` 覆盖三层意图胶囊文案（director / directorCard 各有专属语义）
- 配套 `novice-inspector.css`（预览框 / 缩略图网格 / 空态引导）

### 二、ComfyUI workflow 粘贴 → 解析 → 自动落画布节点（闭环打通）

此前 `importComfyWorkflowText` 只做 dry-run 解析 + 状态栏提示，节点**没有映射回画布**。本轮：

- **新增 `comfyToCanvas.ts` 纯函数**（零 DOM 依赖，可 vitest 直测）：
  - 兼容双格式：UI `nodes[]` / graph `class_type`
  - class_type → 画布节点 kind（`CLIPTextEncode`→prompt、`CheckpointLoader/LoraLoader/KSampler/VAE*`→config、`SaveImage`→image、`LoadImage`→source、未知→text 保底）
  - 提取提示词（text/prompt widget，UI 与 graph 两种取值路径）
  - links 数组 / graph inputs `[src_id, slot]` 引用 → edges
- **`store.applyComfyWorkflow`**：把映射结果批量落成画布节点 + 连线（config/prompt/source 左列、image 右列布局），进撤销栈
- **两个入口接入**：
  - 右键菜单「导入 ComfyUI 工作流」→ 粘贴后自动铺节点
  - 画布空白 Ctrl+V 粘贴 → 识别 workflow 自动铺节点
- 引擎未安装仍诚实提示（节点已落地、生成需引擎），不再只弹一句「解析成功」

### 三、回归 + 质量

- 新增 `comfyToCanvas.test.ts`（**12 断言**）：双格式 / class_type 分类 / 提示词提取 / 连线映射 / 非 workflow 诚实失败 / 未知类型保底
- vitest **31 项全绿**（19 → 31）
- 顺手修 `stage3dScene.test.ts` 的 `ActorState` 缺 `kind`/`rotation` 必填字段的类型瑕疵（历史遗留，非本次功能）

---

## V4.17.2 (2026-09-15) — 补工程质量 + 小白模式一键入口 + ComfyUI 生态回归

> **零解冻**：全部改动在非冻结文件，非冻结区 `tsc --noEmit` 0 错误，不碰 9 区 82 锁。

### 一、补工程质量：画布前端「零单测」破冰

`vendor/shiguang-canvas` 此前 0 单测 / 0 lint / 0 CI。本轮接入 **vitest**，先覆盖纯函数模块：

- 新增 `vitest.config.ts` + `package.json` 加 `test` / `test:watch` 脚本
- 3 个测试文件、**19 项断言全绿**：
  - `magnetic/MagneticEngine.test.ts`（8）：磁吸强度常量 0.45/0.24/0.12 + 偏移系数
  - `stage3dScene.test.ts`（6）：场景序列化往返 / 损坏输入不抛 / hex 回退 / diff 增删与预设变化
  - `bridge.test.ts`（5）：ComfyUI workflow 识别的 UI 格式 / graph 格式 / 非 workflow 拒绝

### 二、小白模式补全：空状态加「一键开始」

`NoviceInspector` 空状态原来只有静态文字引导，用户需先理解「拖卡片」。新增两个实操入口：

- **从剧本开始**（建 `directorCard` 导演卡）→ 复用 store 已有的 `breakdownDirectorCard` 拆镜能力
- **直接生图**（建 `shot` 镜头卡）
- 复用 `store.addNode`，配套 `novice-inspector.css` 样式

### 三、ComfyUI 生态兼容：核心转换器回归保护

后端 `workflow_importer.py`（UI→graph 透传）此前无任何测试。新增 `_verify/check_comfy_workflow_importer.py`（**11 断言全绿**）：

- 格式识别（ui / graph / unknown）
- UI→graph 透传 + widget 启发式映射（正样本 text / 连接引用 [4,0]）
- 引用完整性（悬空引用产生 warning）+ object_info 缺失节点检测
- 损坏输入诚实失败（返回 unknown + 不可执行）
- 注册进 `run_all_checks.py`（19 → **20** 项）

---

## V4.17.1 (2026-09-14) — 修复两个静默失效缺陷 + 补齐小白模式节点生态

> **零解冻**：全部改动在非冻结文件（`keyframe_animation.py` / `login_window.py` / 3 个测试 / `novice/` 3 文件 / `magneticLevels.ts` / `stage3dScene.ts`），不碰 9 区 82 锁。

### 一、修复缺陷 A：关键帧高级插值静默失效 🔴

`app/core/keyframe_animation.py` 的 `get_value` 定义了两次——283 行线性版生效，363 行增强版（含 BEZIER/STEP/SMOOTH 分支）被覆盖成死代码，导致三种插值**全部退化为线性**。

- 修法：删除 283 行旧版，保留增强版
- 验证：独立脚本实测 STEP 中点返回 0.0（修复前 5.0）、BEZIER 1/4 处返回 1.5625（修复前 2.5）、LINEAR 回归正常

### 二、修复缺陷 B：手机号注册 100% 失败 🔴

`app/modules/lego/login_window.py` 的 `_do_phone_register` 定义了两次——414 行旧版把 `nickname` 传进 `register_with_phone` 的 `code` 位（第 3 参），验证码输入框从未被读取；499 行带验证码版被覆盖。

- 修法：删除 414 行旧版，保留 499 行带验证码版
- 根因：`auth.register_with_phone(phone, password, code, nickname)` 第 3 位是 `code`

### 三、修复 3 个测试模块陈旧 import

`app/tests/test_cache.py` / `test_config.py` / `test_security.py` 的 `from core.*` → `from app.core.*`，恢复其可被 pytest 收集。

### 四、补齐小白模式节点生态

主库 `vendor/shiguang-canvas/src/novice/` 的卡面此前只覆盖 17 种内置节点，漏了 `generator` / `markdown` / `animation` / `panorama` 四种（`BUILTIN_NODE_KINDS` 共 21 种）。

- `types.ts`：KIND_STYLE 补 4 种颜色/图标/标签；noviceHint 补 4 条操作提示
- `NoviceCard.tsx`：summaryOf 补 4 种内容摘要 + 修 `digitalHuman`/`source` 摘要优先级；metaOf 补 mode/count/action/frames/yaw/pitch 元信息；thumbOf 补 `sheetUrl`（动画精灵图）；LooseData 类型补齐全部字段

### 五、顺手修掉 V4.16.1 遗留的两个非冻结区 tsc 错误

- `magnetic/magneticLevels.ts`：`MagneticResult` 误从 `./MagneticEngine` 导入（该类型定义在 `./types`），改 `./types`
- `stage3dScene.ts`：`_validateCameraPathPoint` / `_validateCamera` 参数 `any` → `unknown`，消除隐式 any

非冻结区 `tsc --noEmit` 错误清零（剩余 37 处全在冻结区 riggedHumanoid/Stage3D，为存量，攒解冻清单）。

---

## V4.17.0 (2026-09-14) — Agent 应用化：多轮循环 / 原生工具调用 / 控制台（Track B/C/D）

> **零解冻**：全部改动在新文件 `agent_loop.py` / `agent_console.py` + `project_agent_host.py` 末尾新增函数，不碰 9 区 82 锁。

### 一、问题：Agent 是「单轮遥控器」，不是「应用」

此前一次模型回复 → 正则抽 JSON → 执行 → 结束，观察结果不回流、模型不基于执行结果再决策；
预算（12 轮/24 工具）设了却从没被循环用过。

### 二、`app/core/agent_loop.py`（多轮 ReAct 循环）

- `AgentLoop.run()`：观察→规划→行动→观察 while 循环，模型每轮选工具 → 派发 → 观察回流 → 再决策，直到最终答复/预算耗尽/待确认
- 复用既有地基：预算 `agent_session`、策略 `agent_policy.decide`、大脑 `agent_brain.reinforce_path`、任务 `agent_task_store`
- **确认后执行**：协作模式写工具返回 `require_approval` 时循环立即停止、回传 `pending_commands`，绝不自动落地；Plan 只允许只读；诚实失败不假成功
- 模型/执行器可注入（`model_fn`/`tool_executor`），无 LLM 也能自包含回归

### 三、Track C 原生工具调用

- `build_tool_schemas()` 由能力目录派生 OpenAI 风格 function schema
- `parse_tool_calls()` 兼容 commands / tools / 裸数组 / 单对象 / 原生 `tool_calls` 五种写法
- `use_native_tools=True` 注入 tools，provider 不支持自动回退 JSON（最大兼容）

### 四、Track D 控制台数据层

- `app/core/agent_console.py`：`collect_agent_status()` 聚合 session / brain / tasks / active_loops / memory 快照（只读、不触发副作用）
- `project_agent_host.run_project_agent_loop()` + `get_agent_console()`（画布/项目侧入口）

### 五、回归

- `_verify/check_agent_loop.py`（31 断言：解析兼容 / 多轮循环 / 观察回流 / 预算 / 待确认 / Plan 只读 / 诚实失败 / schema 派生 / 控制台聚合）

---

## V4.16.1 (2026-09-14) — 画布原创件补强（4 件均纯新增、零冻结区改动）

> **不碰任何冻结区**：Stage3D.tsx / mediaExtraNodes.tsx / riggedHumanoid.ts 锁
> 全程未动（其周围补强以「配套辅助」形式新增，**桥不 import 上帝类**）。

### 一、磁吸意图系统 · 强度可量化

- `magnetic/MagneticEngine.ts`：抽出 `magneticStrength(level)` 纯函数（0.12/0.24/0.45）
- `magnetic/magneticLevels.ts`（新）：等级元数据 — `short/label/hint/color/strength/rank`，
  强项：UI 调 `magneticStrength` 与 `getLevelMeta(...).strength` 永远同值
- 现有 `getMagneticOffset` 重构为调 `magneticStrength`，行为不变

### 二、3D 导演台 · 场景快照序列化

- `stage3dScene.ts`（新，纯函数 + 无 three.js 依赖）：`SceneState` 类型 + `sceneToJSON` +
  `sceneStateFromJSON` + `diffScenes`，含 Vec3 / Hex / 嵌套花括号配平校验，**损坏输入不抛**
- 用途：让画布节点可承载 3D 场景的可还原信息（actor 姿势 / 机位路径 / 灯光 / 地面 /
  背景 / 雾 / 视口 / viewMode）

### 三、数字人节点 · 姿势元数据 + 缩略图 LRU

- `magnetic/poseThumbCache.ts`（新）：29 个姿势元数据（来源 `riggedHumanoid.ts: POSE_PRESETS`），
  按 `static / action / weapon / extreme / emotion` 五类分组
- `PoseThumbnailCache` LRU：按 `poseId × character` 维度，默认容量 64，含 `hits` 命中统计与 `stats()` Top-5 排行

### 四、分镜记忆 · 回灌校验

- `EditorModule.agent_apply_storyboard_durations(durations)`：新公开方法（与 `agent_replace_timeline_clips` 同风格），
  按 clip_id 匹配 `_clips` 改 `duration` + 同步 `out_point`（**不改其它字段**），未匹配计入 `unmatched`
- `/host/storyboard-memory-plan` 加 `apply=true` 分支：走 `project_snapshot` 的 provider/writer 通道
- 端点返回包**向后兼容**：`rows / totalSuggested` 平铺 + 新增 `applied` 字段
- 诚实失败：未注册 writer 时 `applied.ok=false` + 可读 message，**绝不假成功**

### 五、回归

- 新增 3 个 mjs：`check_magnetic_levels.mjs`（22）/ `check_stage3d_scene.mjs`（22）/
  `check_pose_thumb_cache.mjs`（22）
- 新增 1 个 py：`check_storyboard_apply.py`（17）
- e2e 增 `[G]` 段 8 项
- `run_all_checks.py` 15 → 19 项，全部通过（**2 个存量红灯 GUARD/CANVASDUAL 仍为存量**）

---

## V4.16.0 (2026-09-14) — Agent 能力面归一（Track A）

> **冻结区零新增漂移**：改动落在 `agent_capability_catalog.py`（新）、`agent_policy.py`、
> `agent_brain.py`、`capability_handlers.py`（均为非冻结文件），不碰 9 冻结区 82 锁。

### 一、问题：同一 capability 散落 4 处，漏一处就静默失效

此前一个 capability 要在 4 个文件各写一份靠人工对齐：`capability_handlers`（注册）、
`agent_policy._CAPABILITY_EFFECTS`（effect/paid）、`agent_brain._NEURON_TAXONOMY`（脑归属）、
`agent_action_registry`（对话映射）。已踩的坑：
- `editor.inspect_media` / `editor.get_media` 注册了却漏进 policy → 落「未登记=FILE_WRITE」兜底，读素材被误判成写文件；
- `memory.suggest` 在 policy 有、却从未注册 handler；
- 9 个已注册能力没脑归属，靠 `sync_from_dispatcher` 兜底成无标签胼胝体神经元。

### 二、方案：单一事实来源 `app/core/agent_capability_catalog.py`

一张表承载 `(capability_id, category, effect, paid, 描述, 脑归属, 标签, 关键词)`，
`capability_effect_paid()` 与 `neuron_taxonomy()` 两个派生函数供 policy/brain 引用。
新增能力唯一入口 = 本表加一行，其余三处自动跟上。

### 三、修复

| 项 | 修复前 | 修复后 |
|---|---|---|
| `editor.inspect_media` / `get_media` effect | 漏登记 → FILE_WRITE 兜底 | `read`（协作模式自动放行，不再误判写） |
| 神经元覆盖 | 27 个（9 个缺失靠兜底） | 36 个全覆盖，right 7 / left 19 / cc 10 |

### 四、守卫

`capability_handlers.register_builtin_handlers` 末尾加 `verify_catalog_consistency()` 双向对齐：
目录有但未注册 / 注册了但目录缺失，都会 `logger.warning` 告警，不再静默。

### 五、回归

- 新增 `_verify/check_capability_catalog.py`（5 组断言：目录↔注册一致 / policy 派生逐项相等 /
  神经元全覆盖 / 历史缺陷不回归 / 目录卫生）
- 既有 4 项 agent 回归全部通过：`check_agent_action_mapping` / `check_editor_write_capabilities`（8/8）/
  `check_brain_routing` / `check_capability_catalog`

---

## V4.15.1 (2026-09-14) — 工程级快照（P1-4）：带时间线 / 可回滚 / 可 diff / 直导剪辑器

> **冻结区零新增漂移**：全部改动落在新文件 `project_snapshot.py` 与 `canvas_server.py`（非冻结）、
> `editor_module.py`（非锁定符号的新增方法）、前端 `projectZip.ts`/`App.tsx`。
> 不碰 `canvas_bridge.py` / `mediaExtraNodes.tsx` 等冻结文件。

### 一、问题：`exportProjectZip` 只打包画布，丢了时间线

改前 `projectZip.ts` 只导 `project.json + media/*`，时间线（`EditorModule._clips`）在 PyQt6 侧，
画布拿不到；「换机带走 / 版本回滚 / 直导剪辑器」三者都断。

### 二、后端：`app/core/project_snapshot.py`（纯函数，可单测）

| 能力 | 实现 |
|---|---|
| 无损序列化 | `snapshot_timeline()` 深拷贝**完整 `_clips`**（非摘要），保留 volume/speed/effects/keyframes |
| 结构 diff | `diff_timelines()` → added/removed/字段级 changed/unchanged（id 主键、path@start 兜底） |
| 回滚栈 | `SnapshotStore`（线程安全、上限 50 条自动裁旧） |
| 读写解耦 | `set_full_clips_provider` / `set_clips_writer` 由 EditorModule 注册，桥不 import 上帝类 |

### 三、端点（走路由表，GET 4 条 / POST 8 条）

- `GET /host/project-snapshot/export` — 返回 `{ok, timeline:{clips,clip_count,taken_at}}`
- `POST /host/project-snapshot/import` — 把 `{clips}` 写回剪辑器（直导），导入前自动压回滚快照
- `GET /host/project-snapshot/history` — 回滚栈列表
- `POST /host/project-snapshot/restore` — 按 `snapshot_id` 回滚

### 四、直导剪辑器落点

`EditorModule.agent_replace_timeline_clips(clips)`：复用 `import_project` 的重建序列
（清空 `_clips` → 逐个 `add_clip` → `_sync_kernel_timeline` → `relayout_clips` → 刷首帧）。
诚实失败：未注册 writer 时 `import`/`restore` 返回 `ok:false` + 可读指引，绝不假成功。

### 五、前端 `projectZip.ts` / `App.tsx`

- `ProjectBundle` 加 `timeline` 字段；`fetchProjectTimeline` / `pushTimelineToEditor` / `diffTimelineClips`
- 导出自动并入时间线；导入若带时间线则 `confirm` 后直导剪辑器

### 六、回归

- 新增 `_verify/check_project_snapshot.py`（20 断言：序列化深拷贝 / diff / 回滚栈上限 / 诚实失败）
- `check_canvas_bridge_e2e.py` 增 `[F]` 段（8 断言：端点可达 + 未注册 provider 诚实语义 + 401 鉴权）
- `check_canvas_routes.py` 补登 `projectZip.ts`；回归项 14 → 15

---

## V4.15.0 (2026-09-14) — 生成链路异步任务化（P0-2）+ 批量并发队列（P0-3）

> **冻结区零新增漂移**：改动全部落在非冻结的 `canvas_server.py` / `canvas_aigc.py` 与**新文件**上。
> `canvas_bridge.py` / `mediaExtraNodes.tsx` 的两个既有漂移与本版无关，仍待用户定性。

### 一、问题：生成是「一次阻塞 POST」

改前实测：`bridge.ts:172 generateImageViaHost` / `:916 generateVideoViaHost` 都是 `await fetch`
一次阻塞（`canvas_aigc` 侧超时档 120/180/300s）；批量 `n>1` 走 `:253` 的 `for` **串行阻塞循环**；
全程无 `AbortController`。用户只能干等，且**取消不掉**。

### 二、后端：新增任务表 `app/core/canvas_gen_jobs.py`

| 能力 | 实现 |
|---|---|
| 异步 | `submit()` 入队即返回快照；`SG_GEN_CONCURRENCY`（默认 3）个守护线程 FIFO 消费 |
| 真进度 | 任务体通过 `StageReporter` 上报 `stage` / `progress` / `note` |
| 可取消 | `queued` → 直接作废（任务体**从不执行**）；`running` → `cancelling` + 关闭在途响应 |
| 重试 | `max_attempts` + 指数退避；**取消后不再重试** |
| 保留 | 只裁已终结任务，上限 200 条；排队/运行中的一个不动 |

**取消是怎么做到「真」的**：`canvas_aigc.py` 里 8 处 `urllib.request.urlopen` 全量换成
`canvas_gen_jobs.open_url(req, timeout)`。任务线程内它会把手上的响应对象登记到线程局部令牌上；
`cancel()` 逐个 `close()`，对端阻塞中的 `read()` 立刻抛错——**深层调用签名一处没改**。

**取消后结果必丢弃**：终态判定里 `if token.cancelled: job["result"] = None`，
即使上游已经返回，也不落盘、不进 UI。

### 三、后端：4 个新端点（走路由表，老 if 链一行未涨）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/host/generation/submit` | `{kind, payload, max_attempts, label}` → 立即返回 `{job}` |
| GET | `/host/generation/status` | `?job_id=` → `{job}` |
| GET | `/host/generation/list` | `?limit=` → `{jobs, stats}` |
| POST | `/host/generation/cancel` | `{job_id}` → 幂等取消 |

路由表 4 → 8 条；`_verify/check_canvas_routes.py` 复核「无重复注册 / 无不可达路由」仍全绿。

### 四、异步化是「保真搬运」，不是重写

老端点 `/host/generate-image` `/host/generate-video` 里的四件事**一件没丢**：
画质档 → size 换算、失败 NG 计数、GFPGAN 后台预载触发、后处理任务注册。
（`_build_gen_callable` 里逐条对齐，注释已标明。）

### 五、进度的「诚实」边界

⚠️ **不能伪造百分比**。上游 provider 只给一次阻塞响应，没有进度信号，
所以：

- `progress === null` → 前端只显示 **阶段标签 + 已用时**，**不画进度条**
- 只有**生视频后处理（超分/补帧）**回调是真值 → 才写真实百分比

实测 26 条断言里专门有两条守这个：运行中 `progress` 必须仍为 `null`；终态才允许 `100`。

### 六、前端：`generationQueue.ts` + 生图工作台改造

新增 `vendor/shiguang-canvas/src/generationQueue.ts`（**不改 `bridge.ts`**，避免把已分叉的双库再推远）：

- `submitGeneration` / `awaitGeneration` / `cancelGeneration` / `listGenerationJobs`
- `runGenerationPool(kind, tasks, {concurrency, maxAttempts, onItem})` —— 批量并发池，
  **逐条进度、逐条重试、逐条「重试」按钮**，返回结果与入参同序
- 轮询间隔先密后疏（0.5s → 1s → 2s），长任务不刷爆桥接层

生图工作台（`ImageStudio.tsx`）改用任务制 UI：阶段胶囊 + 已用时 + 取消按钮 +
批量逐条状态行 + 失败条目单独重试。**新增 UI 一律内联样式**——`styles.css` 在冻结清单里。

### 七、守卫

- 新增 `_verify/check_generation_jobs.py`（**26 条**：提交即返回、诚实进度、成功/失败/重试计数、
  queued 真取消且不执行、running 取消且结果丢弃、终态幂等、并发峰值 ≤ 上限、list 排序与 stats）
- `run_all_checks.py` 回归项 **13 → 14**
- `check_canvas_routes.py` 的 `CLIENTS` 补登 `generationQueue.ts`
  （此前只扫 `bridge.ts`，新模块调用的端点会对契约检查**隐身**）
- `tsc --noEmit`：本次改动文件 **0 错误**（41 处既有错误全在冻结文件 `riggedHumanoid.ts` / `Stage3D.tsx` 内）

### 八、未做（下一批）

- P0-1 Agent 薄弱点（对外 Skill/CLI 接口）+ 工作流模板社区
- P1-4 角色漂移锚点权重面板 —— 需改 `mediaExtraNodes.tsx` / `nodes.tsx`，**属冻结区，须先解冻**
- P1-5 工程级快照（时间线 + 回滚/diff + 直导剪辑器）
- P1-6 跨镜帧特征参考 —— 同样落在冻结节点文件上
- 副库 `AI-Canvas-tauri/src/libtv/` 同步（`bridge.ts` 等 5 文件已处于分叉状态，待用户定策略）

---

## V4.14.6 (2026-09-13) — 分镜加观众记忆维度（P1-3）+ 端到端回归固化

> 二次解冻 `canvas-magnetic-intent` 后改动，已完成并重新上锁（82 项基线）。

### 一、新能力：分镜表按「观众记忆」重排时长

`memory_model` 只会**评估**（这段三天后还剩多少记忆），不会告诉你因此剪多长。
新增 `app/core/ai/storyboard_memory.py` 补上**剪辑推论**这一层：

| 记忆类型 | 24h 基线保留率 | 剪辑推论 |
|---|---|---|
| 细节 | 11.5% | 衰减最快，本来就会被忘 → 让出时长，可剪短剪碎 |
| 意义 | 61.9% | 中性基准 |
| 情绪 | 82.5% | 留得最久，是「被记住」的真正载体 → 值得给足时长 |

**换算规则：总时长守恒，按保留率加权再分配。**
纯比例会把细节压到零点几秒，所以分配后夹紧到 `[0.8s, 12s]`，
再把夹紧产生的余量按比例摊回未夹紧的行 —— 总量仍然守恒。

另附**干扰告警**（模型的 I 项）：
- 相邻情绪锚点会互相覆盖 → 建议中间插一个低记忆密度的镜头
- 名场面太多（≥半数都是情绪锚点）→ 反而记不住

⚠️ λ0 是未校准初始值，所以输出是**相对建议**（哪几镜该让位给哪几镜），不是绝对值。

### 二、接线

- 新端点 `POST /host/storyboard-memory-plan` —— **走 V4.14.4 的路由表**，
  老 if 链一行没涨（正好兑现当初表化的收益）
- 两前端包 `ShotlistRow` 加可选字段 `memoryType`，默认 `meaning`
- 分镜表新增「记忆」列 + 「按记忆重排时长」按钮，显示后端回传的**真实**保留率

> **百分比一律由后端给，前端不硬编码** —— 这是 V4.14.5 修角色提示词时立的规矩
> （两份 λ 必然漂移）。前端注释里只写「细节衰减最快 / 情绪留得最久」这类相对描述。

### 三、回归

| 新增/增强 | 内容 |
|---|---|
| `check_storyboard_memory.py` | 20 条模型换算断言（保留率与模型一致 / 总时长守恒 / 方向正确 / 夹紧 / 退化输入 / 干扰告警） |
| `check_canvas_bridge_e2e.py` | **固化为常驻回归**：真起一个 bridge 服务打 HTTP，覆盖端点可用性、路由表回落、鉴权。之前 V4.14.4 那三个死端点如果有它，当年就抓到了 |

**回归项 11 → 13。**

### 四、类型检查（本次实际跑了）

两库 `tsc --noEmit`：**本次改动的 4 个文件（storyNodes.tsx / node-factory.ts / bridge.ts / store.ts）零错误**。
存量错误全在冻结文件 `riggedHumanoid.ts` / `Stage3D.tsx`，以及主库 bridge.ts 顶部
（环境缺 `@tauri-apps/api/core`，第 44 行动态 import，与我加的 1166 行无关）。

---

## V4.14.5 (2026-09-13) — 画布绑定角色只传外貌（visual 组 4 字段全通 + 幂等）

> 解冻 `canvas-magnetic-intent` 后改动，已完成并重新上锁（82 项基线）。

### 一、主缺陷：用户在角色库填的 3 个字段，一个字都进不了生图提示词

Python 侧 `build_character_prompt` 明明消费 **4 个 visual 字段**：

| 字段 | 标签 | Python 用 | 画布旧行为 |
|---|---|---|---|
| `appearance` | 外貌特征 | ✅ | ✅ 唯一用的 |
| `temperament` | 气质倾向 | ✅ | ❌ 丢 |
| `memory_anchors` | 标志性符号 | ✅ | ❌ 丢 |
| `personality` | 性格特征 | ✅ | ❌ 丢 |

`store.ts` 里只拼了 `target.appearance` ⇒ 填了「清冷疏离 / 左眼眼罩」，绑定角色后**完全不生效**，
且不报错 —— 典型静默失效。

### 二、改法：服务端下发，前端不再自己拼

不再让 TS 抄一遍 Python 的拼装逻辑（两份必然漂移），改为：

- `canvas_server.py` `/host/characters` 增加 `"prompt": build_character_prompt(c)`
- 两个前端包 `CharacterEntry` 补派生字段 `prompt`
- `store.ts` 直接消费 `target.prompt`

实测输出：`角色「沈砚」，男，年龄感青年，标签:清冷，外貌:白衣长发，气质倾向:清冷疏离，标志性符号:左眼眼罩，性格:寡言`
（`core_desire` 等 inner 字段正确排除，不污染画面描述）

主库 `vendor/shiguang-canvas` 与 Tauri 副库 `vendor/AI-Canvas-tauri` **同步改**。

### 三、顺带修掉两个幂等 bug

旧代码：

```ts
prompt: (d.prompt || "").replace(/^\[角色外貌:[^\]]*\]\s*/, "") + (appearance ? "\n" + appearance : "")
```

删除正则锚在开头 `^`，但新块是 **append 到末尾** ⇒

- **重复绑定越绑越长**：第二次绑根本删不掉第一次的块
- **解绑删不掉**：块在末尾，锚头正则 match 不到

改为行级幂等替换 `applyCharBlock(prompt, block)`，兼容旧版 `[角色外貌:]` 块，
空块即删除（解绑用它）。

### 四、守卫

| 脚本 | 作用 |
|---|---|
| `check_character_schema.py` | 「五处同步」→ **六处**，新增画布拼装侧静态检查（不许退化回只拼 appearance） |
| `check_char_prompt_block.mjs`（Node） | **直接从两库 store.ts 抽真实源码 eval** 后跑 14 条行为断言 |

> 关键设计：mjs 守卫不测「复制过来的逻辑」，而是 `src.slice()` 出线上那份源码再 eval ——
> 测试副本会漂移，源码抽取不会。

`run_all_checks.py` 支持 `.mjs`（自动定位 node），**回归项 10 → 11**。

---

## V4.14.4 (2026-09-13) — 画布桥接层路由表化 + 救活 3 个死了的插件端点

### 一、修真实缺陷：三个插件端点从来没生效过

`/host/plugins/install`、`/host/plugins/toggle`、`/host/plugins/uninstall` 这三个 POST 端点，
曾被**追加到文件末尾**，结果落进了 `_handle_ingest()` 内部、且位于第 1958 行 `return` **之后**。

- 语法合法、静态检查全绿、端点确实「写了」
- 但永远不会执行 —— 前端点插件安装 / 启用 / 卸载，只会拿到 `do_POST` 末尾的 `404`
- 且前端也没人调过（双向死亡），所以一直没被发现

现迁为 `@_route_post` 注册的类方法 `_h_plugins_install / _h_plugins_toggle / _h_plugins_uninstall`。

### 二、`canvas_server.py` 路由表化（绞杀者模式）

历史包袱：`do_GET` 607 行、`do_POST` 947 行，各是一条 `if path == ...` 链，共 49 个端点。
全量重写风险太高，改成：

```python
_ROUTES_GET: Dict[str, str] = {}
_ROUTES_POST: Dict[str, str] = {}

@_route_post("/host/plugins/install")
def _h_plugins_install(self, parsed, raw: bytes, ctype: str) -> None: ...
```

`do_GET` / `do_POST` 开头先查表（`_dispatch_table`），**未命中才回落老 if 链** ——
老链一行没动，行为完全不变；新增端点从此不用再往千行链里塞，老链后续可逐条迁出。

`_dispatch_table` 统一兜异常，路由表里的 handler 不必各自铺 try/except 大网。

### 三、回归守卫（这才是重点）

`_verify/check_canvas_routes.py` 扩到 4 项：

| # | 检查 | 拦什么 |
|---|---|---|
| 1 | 前端调了、后端没有 | 静默 404 |
| 2 | 后端有、前端没用 | 信息，不算错 |
| 3 | **不可达路由**（AST：函数体顶层 `return` 之后的路由分支） | 端点写了但永远走不到 —— 正是本次事故的死法 |
| 4 | **路由表 × 老链重复注册** | 迁进表后老链那条会变死代码 |

同时补认 `@_route_get` / `@_route_post` 写法 —— 否则迁进路由表的端点会从「服务端路由」里消失，
等于给契约检查开了后门。

`_verify/check_canvas_dual_repo.py` 与端点契约检查并入 `run_all_checks.py`，**回归项 8 → 10**。

### 四、已知遗留（未处理，非本次引入）

`canvas_server` ↔ `canvas_bridge` 存在**模块级循环导入**：
先 `import app.core.canvas_server` 会失败，先 `import app.core.canvas_bridge` 正常。
现有入口都是后者，暂不改。

---

## V4.14.3 (2026-09-13) — Agent 写能力补到 8 个（达硬门槛）+ 修裁剪不可撤销

### 背景：`06-roadmap.md §E` 硬门槛

> Dispatcher 至少 **8** 个真能改 `_clips` 且可撤销的 `editor.*` / 等价能力

此前只有 **6 个**（split_clip / apply_filter / add_transition / ripple_delete_range /
set_clip_properties / set_keyframes）。补上 `editor.trim_clip` 与 `editor.move_clip` 后达标。

### 一、两个新写能力

| 能力 | 实现 | 撤销 | 说明 |
|---|---|---|---|
| `editor.trim_clip` | `EditorModule.agent_trim_clip` | ✅ | 改时长走既有 `_resize_clip`（含撤销+联动音画）；改入/出点自建 before/after + 撤销栈 + 联动音画 + 同步 |
| `editor.move_clip` | `EditorModule.agent_move_clip` | ✅ | 薄封装既有 `move_clip`（已含撤销 + 联动音画 + 同步） |

参数兼容面板里已有的叫法：`new_duration` / `duration` / `end_time` / `in_point` / `out_point`。

### 二、顺带修掉一个真实缺陷：AI 面板的裁剪不可撤销

`ai_agent_panel.py` 原来的 `trim_clip` 分支是这样的：

```python
clip["duration"] = float(duration)
clip["out_point"] = clip.get("in_point", 0) + float(duration)
return {"success": True, ...}
```

**直接改数据，不进撤销栈（Ctrl+Z 回不去）、不同步内核时间线、不联动音画** ——
正好是「写能力」定义的反例。现已把面板分支改为 `self._agent_dispatch("editor.trim_clip", ...)`，
**面板与 capability 收敛到同一个实现**，不再有第二套分叉。`move_clip` 同理。

### 三、修 policy 漏登记（回归脚本查出来的）

`editor.set_clip_properties` 与 `editor.set_keyframes` **没有**登记进 `_CAPABILITY_EFFECTS`，
于是落到「未登记工具 → `EFFECT_FILE_WRITE`」兜底——但这两个改的是剪辑数据，
风险类应该是 `canvas_write`（`FILE_WRITE` 的语义是落盘改文件）。已对齐为 `canvas_write`。
（协作 B 档的确认行为不变：两种 effect 都需确认；修正的是风险分类与未来规则的可预期性。）

### 四、新增回归脚本

`_verify/check_editor_write_capabilities.py` —— 把门槛变成可自动校验项：

- 8 个写能力全部在 dispatcher 注册且数量 ≥ 8
- 每个都有明确 policy effect（**不允许落 FILE_WRITE 兜底**）
- 对话 action → capability 映射齐备
- **AST 静态追踪**：写能力实现必须能追到撤销路径（`_record_action` / `_resize_clip` / `move_clip`）
- **旧缺陷不回归**：`ai_agent_panel` 不得再直接写 `clip["duration"]`

### 验证

```
python _verify/run_all_checks.py  → ✓ 全部通过：8 项
  WRITECAP：写能力门槛达成 8/8
  GUARD 82 locks / SCHEMA 20 / PROMPT / MEMMODEL / MEMSTR / BRAINROUTE / AGENTMAP
10 个改动文件 py_compile 全部通过
```

## V4.14.2 (2026-09-13) — 学习回路闭合：突触权重参与路径选择

### 背景：AgentBrain 学了半天，决策还是老路

排查出的断点（`editor_agent_panel_mixin.py:1447` 注释自己也承认）：

```
执行 invoke → activate() 激活                 通
成功/失败 → reinforce_path() 写权重            通
权重被 correlate() 读取 → 显示一条 UI 消息      通（仅供展示）
选路径时不用这些权重                            断  ← 本次补上
```

### 一、AgentBrain 新增决策咨询 API（`app/core/agent_brain.py`）

- `synapse_weight(pre, post)` —— 无记录返回 `None`，与「学到 0.5」区分开。
- `score_candidates(from, cands)` —— 返回 `[(cand, weight, learned)]`，按权重降序。
- `suggest_next(from, cands, default)` —— 权重最高者胜；**default 置顶 + 稳定排序**
  ⇒ 平票必选默认。返回体自带 `weights` / `learned` / `changed` / `reason`，决策可解释。

**两条设计红线**：
1. 无数据时所有候选权重 = 中性 `0.5`，平票走默认 ⇒ **冷启动行为与未接入大脑时逐字一致**。
2. **不做 ε 随机探索** —— 本项目拒绝随机效果，宁可冷启动保守，也不要不可复现的抖动。

### 二、预览失败分支接入大脑（`app/core/agent_pipeline_orchestrator.py`）

预览校验是全链路**唯一真正的岔路**（原实现把「自动通过」埋在 `_run_preview_validation`
里，等于没有分支）。现拆出两个候选：

| 分支 | 含义 | 备注 |
|---|---|---|
| `pipeline.score`（**默认**） | 带瑕疵继续：打分→脚本→精剪 | 与接入前行为一致 |
| `pipeline.regenerate_clip` | 先局部重生成问题片段再继续 | 花钱/耗时，可能救回质量 |

- 选择结果追加进 `session.executed_path` ⇒ 会话结束 `reinforce_path` 自动回灌这次选择的好坏，
  **闭环无需额外代码**（这是选在这里下手的原因：executed_path 本来就在记录真实路径）。
- **自动核验模式**（`auto_preview_pass=True`）才真正执行重生成；**人工模式只给建议**（事件里带
  `brain_advice`），不擅自替人决定。
- 重生成失败/超上限 → 回退原策略（标记通过继续），行为不劣化。
- 双重节流：`preview_validation_loop._max_regen` + 单次会话上限 3 个片段；调用走
  `capability_dispatcher`，受 `agent_policy`（media_write / paid）约束。
- 重生成后的新片段**回写进 `clips` 的 path**，避免后续打分/精剪还在用旧片段。
- `PipelineSession.brain_advice` 进入 `to_dict()` 与等待事件，决策不再是黑箱。
- 总开关 `SG_BRAIN_ROUTE=0` 可整体关闭。

### 三、新增脚本

- `_verify/check_brain_routing.py` —— 冷启动/正反馈/负反馈/平票/接线/序列化/副作用 7 组断言
  （脚本会临时禁用 `memory_store.record`，避免把测试突触写进真实记忆库）
- `_verify/run_all_checks.py` —— 一键跑 7 项回归（GUARD/SCHEMA/PROMPT/MEMMODEL/MEMSTR/BRAINROUTE/AGENTMAP）

### 四、文档

- 校对 `docs/_archive/knowledge/09-tool-registry-design.md`：原文档仍把 ④ 对话白名单描述为
  「手写字符串集合 / 两个独立 frozenset」，实际 `agent_action_registry.py` 早已是**表驱动单一来源**，
  按现状校正并标注 2026-09-13。

### 验证

```
python _verify/run_all_checks.py  → ✓ 全部通过：7 项
  GUARD 82 locks / SCHEMA fields=20 / PROMPT / MEMMODEL / MEMSTR / BRAINROUTE / AGENTMAP
```

## V4.14.1 (2026-09-13) — 记忆强度机制 + 突触加载次序修复

### 背景
- 「一起修」：把 V4.14.0 新增的**记忆衰减模型**（math 层）与 **AgentBrain 突触**（数据层）接上，
  并修复排查中发现的 3 个记忆系统缺陷。
- ⚠️ 过程中发现另一 IDE 会话已并行改了 `memory_store.py` 的一半强度代码
  （缺 `import math` 会 NameError、常量未接线）——本次**补完接线而非覆盖**，保留其参数语义。

### 记忆强度机制（`app/core/memory_store.py`）
- `MemoryEntry` 新增 `recall_count: int = 0` / `last_recalled: float = 0.0`（默认值兼容旧 JSONL）。
- **强度公式**：`strength = base · e^(-λ·t)`，其中 `λ = λ0 · (1 - α·巩固度)`、
  `巩固度 = min(recall_count / 10, 1)` —— **被用过的记忆衰减更慢**，与记忆衰减模型的巩固语义同源。
- `get_agent_context()` 只对**真正注入上下文**的条目调 `reinforce()`；query 命中不计入，防误强化。
- 排序开关 `SG_STRENGTH_SORT=1` 启用强度排序，**默认关闭**（默认行为与 4.14.0 完全一致，灰度安全）。
- 存储路径改为绝对路径（`app/data/agent_memory.jsonl`），不再随 CWD 漂移。

### 修复的 3 个缺陷
1. **压缩吃掉消费中的追踪**：`_compress()` 现保留 `brain_synapse`、含错误的 `execution_trace`
   与高分条目 —— 原逻辑会把大脑正在消费的突触按轮换删掉。
2. **突触加载保留最低权重**：`load_synapses()` 按 score 倒序迭代 + 字典覆盖，
   实际留下的是**分数最低**的历史版本。改用新增的 `latest_per_key(pre, post)`，
   按 `(pre, post)` 逻辑键去重取**时间戳最新**。
3. **FIFO 注释错标 LRU**：更正为 FIFO（5000 条上限）。

### 新增回归脚本
- `_verify/check_memory_strength.py` —— 强度曲线、reinforce、latest_per_key、压缩保留策略全部断言
  （自包含执行，避开沙箱拦截的 import 链）。

### 验证
- `check_memory_strength.py` → 全部通过：
  搁置 30 天 unused=0.389 / used=0.792 / 新写入=0.600；真实数据 171 条（同 id 取最新）兼容。
- `python scripts/frozen_zone_guard.py` → `OK frozen zones intact (82 locks)`
- 全套回归（GUARD / SCHEMA / PROMPT / MEMMODEL / AGENTMAP / MEMSTR）→ 6/6 通过

## V4.14.0 (2026-09-13) — 角色库人格字段结构化 + 记忆衰减模型

### 背景
- 参考公开的「灵魂设计十模块 + 记忆六变量 / 遗忘数学模型」设计思路（抖音 @小凌的创… 的两页笔记）。
- 判断：**思路可借鉴，参数不可照搬**。他描述的是「虚构角色如何遗忘」，我们要的是「观众记住什么」——
  指数衰减形式相同，参数语义完全不同，混用会错位。

### 角色库人格字段结构化（`app/modules/lego/character_management_module.py`）
- `CHARACTER_FIELD_SCHEMA` **10 → 20 字段**，新增 10 个人格字段，与「灵魂设计十模块」一一对应：
  气质倾向 / 标志性符号 / 价值排序 / 核心欲望 / 关系网 / 关键经历 / 情绪触发点 / 思维模式 / 应激反应 / 语言风格。
- schema 升级为 5 元组并引入**分组**，字段流向由隐式变显式声明：
  - `base` 基础身份（头部单行控件）
  - `visual` 形象与符号 → **唯一进生图提示词的组**
  - `inner` 内在人格 → 供剧本与跨集一致性校验，**刻意不进提示词**
    （往画面描述里塞「核心欲望」只会污染出图）
  - `other` 其他长文本
- `CharacterEditorPanel` 从「硬编码 5 个控件」改为**按 schema 分组动态渲染**，
  以后加字段只需改一张表；`load_character` / `clear` / `set_enabled` / `_collect_data` 同步改为遍历式。

### 字段打通「五处同步」
一个角色字段横跨 5 个位置，任何一处漏改都**不报错**，只表现为「填了不生效」或「前端看不到」：

1. `CHARACTER_FIELD_SCHEMA`（本表）
2. `canvas_bridge.build_character_prompt`（仅 visual 组）——新增 `气质倾向:` / `标志性符号:` 片段
3. `canvas_server` 的 `/host/characters` —— **改为按 schema 派生白名单**，不再手工列字段
4. 5. `vendor/shiguang-canvas` 与 `vendor/AI-Canvas-tauri` 两处 `node-factory.ts` 的 `CharacterEntry`

**有意的行为变更**：提示词中 `personality` 的前缀由「气质:」改为「性格:」——
新增的 `temperament` 已占用「气质」语义，两词并存会互相稀释。老角色不含新字段，除此前缀外输出不变。

### 新增记忆衰减模型（`app/core/ai/memory_model.py`）
- 记忆六变量 `MemoryVector(S, D, R, E, C, I)` + 遗忘衰减曲线：
  `D(t)=D0·e^(-λ_D·t)`，`λ_D=λ0·(1-αE)·(1-βC)·(1+γI)`；`S(t)`、`E(t)` 各自独立衰减且 `λ_S < λ_D`。
- **补了原始公式缺的夹紧保护**：αE ≥ 1 时 λ ≤ 0，记忆会「永不遗忘」甚至反向增长 —— 用 `_MIN_RATE` 兜住。
- 派生 `memory_score()` / `explain()`：默认按观看后 72 小时给综合记忆分，供剪辑取舍参考。
- 默认 λ0 **是未校准的占位值**；模块 docstring 明确要求用真实完播 / 复看数据反推，勿长期沿用。

### 新增回归脚本（`_verify/`）
- `check_character_schema.py` —— 五处同步静态校验（ast 解析，不 import PyQt6）
- `check_character_prompt.py` —— 字段流向 + 向后兼容断言（ast 抽取函数体执行，避开 import 副作用）
- `check_memory_model.py` —— 记忆模型自包含断言（沙箱下 pytest 启动链会触发硬件探测被拦截）

### 验证
- `check_character_schema.py` → `OK 角色库字段五处同步 (fields=20, visual=4, groups=4)`
- `check_character_prompt.py` → 新字段进提示词、inner 组不泄漏、老角色行为不变
- `check_memory_model.py` → 全部断言通过（24h 细节保留 11.5% / 意义 61.9% / 情绪 82.5%）
- 新增单测 `app/tests/test_memory_model.py`（pytest）
- `python scripts/frozen_zone_guard.py` → `OK frozen zones intact (82 locks)`

## V4.13.0 (2026-09-12) — 小白模式磁吸吸附手感重构（咬合可见 · 分离有阻力）

### 🔍 根因：磁吸判据用错了度量
- `MagneticEngine.computeMagnetic` 一直用**中心距**（center-to-center）判等级，但卡片是 **240×200**。
  两张卡并排**紧贴**时，中心距正好是 **240px**，而强吸附阈值只有 **25px** ——
  也就是说**并排贴合这个最常用的动作，从一开始就不可能触发任何磁吸**，只有「拖到卡片上重叠」才勉强有反应。
  用户感觉「没有明显提示已经吸附成功」，本质是**吸附压根没成立**，而不是提示不够亮。
- 另有 `stretchThreshold: 30` / `breakThreshold: 50` 两个阈值**定义了很久却从未被使用**——
  规格里写的「拉伸 30、断裂 50」是空头支票。

### 🔧 重构
**① 判据改为「边缘间隙 edge-gap」**（`magnetic/MagneticEngine.ts`）
- 新增 `rectOf(node)` / `edgeGap(a,b)` → `{ gap, gapX, gapY, overlapX, overlapY }`：
  `gap` 为两卡**外边缘**的分离量（重叠时为 0），并同时给出分轴间隙与投影重叠长度。
- 等级判定改用 `gap`：`gap < 25 → strong`、`< 50 → medium`、`< 80 → weak`。
  并排紧贴（gap≈0）现在稳落 strong。
- `getDirection(dx,dy,gap)` 只在 `gap ≤ 1` 时才判 `stack`（真重叠），否则按四向方位，避免贴边被误判成层叠。
- 因判据从「中心距」变成「边缘距」（数值量级变大），吸引力强度整体下调以匹配手感：
  `weak 0.15→0.12`、`medium 0.35→0.24`、`strong 0.70→0.45`。

**② 新增「咬合 Bond」——吸附成功后的持久关系**（新增 `magnetic/bonds.ts`）
- `Bond` = 两张已贴合卡片的关系，由**几何推导**而非落盘：`边距 ≤ bondTolerance(2px)` 且 `投影重叠 ≥ 40px`。
  因此**刷新页面后咬合关系依然成立**，无需持久化。
- `makeBond` 识别 左/右/上/下 四种贴合缝（不含 stack 层叠），输出缝的中心线与语义色。
- `computeBonds(nodes)` 借 `SpatialIndex` 做邻域查询（不全量两两比对）；另有
  `findBondFor(nodeId,...)` / `neighborOf(bond,nodeId)` 供拖拽与渲染使用。

**③ 新增「咬合缝」SnapSeam —— 就是要显眼**（新增 `magnetic/SnapSeam.tsx` + `styles.css` 动画）
- 每条咬合在画布上常驻渲染一条缝：**色带 + 白色芯线 + 文字胶囊**，
  文字随阶段切换 **`已吸附` → `拉伸中` → `即将断开`**。
- 颜色随应变演进：常态语义色 → 拉伸琥珀 `#fbbf24` → 绷紧红 `#f87171`；应变越大缝越细（视觉上被「拉薄」）。
- **吸附成功 / 断裂各触发一次白光扩散闪烁**（`sg-seam-flash` + 扩散环），一次性、播完即散。

**④ 拖拽分离加入「阻力感」**（`magnetic/useMagneticDrag.ts` 重写）
- 用上一直闲置的 `stretchThreshold(30)` / `breakThreshold(50)`，做成三段式手感：
  - **拉力 ≤ 30px：卡片完全不动**（咬死，位移被压制）；
  - **30 < 拉力 < 50px：只跟动超出量的 28%**（`bondGiveRatio`），像橡皮筋绷住、越拉越沉；
  - **拉力 ≥ 50px：断裂**，邻居加入 `mutedRef` 本次拖拽不再吸它，同时播断裂闪光。
- 磁吸偏移改为**累加在当前显示位置**上（而非原始指针位置），捕捉感从「瞬移」变成「被吸过去」。
- `onNodeDragStop`：仍在咬合 → 150ms 平滑**回位**（不过冲）；强吸附 → 带 5px 过冲**落座**，落座后若形成咬合再补一次吸附闪光。
- 位置写入走 `writeNodePos`（跳过无变化写入）+ `animateNodeTo`（rAF 弹簧动画，`animFrameRef` 保证可取消），
  且 React Flow v12 是「先写 store、后回调」，所以回调里的位置覆盖必然生效——这正是阻力实现能成立的关键。

**⑤ 槽位高亮加强**（`magnetic/SnapSlotHighlight.tsx`）
- 强吸附槽位厚度 `5px → 9px`，并加一条白色芯线；透明度 weak 0.55 / medium 0.85 / strong 1.0。
- 强吸附时显示 **「松手即吸附」** 胶囊提示；strong / hint 两类走 CSS 动画 `sg-slot-strong`、`sg-slot-hint`。

**⑥ 小白模式关闭网格量化**（`CanvasShell.tsx`）
- `snapToGrid={isNovice ? false : snapGrid}`：原先 16px 量化会让「拉扯」变成阶梯跳，阻力感被吃掉。

### ✅ 验证
- `vite build` **EXIT=0**（`vendor/shiguang-canvas`）。
- `tsc --noEmit` 全量 40 个错误**全部在存量文件**：`riggedHumanoid.ts`(21)、`Stage3D.tsx`(16)、`bridge.ts`(3)；
  **本次改动涉及的文件（CanvasShell / magnetic / novice）零错误**。

### ⚠️ 冻结区漂移（待用户确认解冻）
- 本次改动落在 zone **`canvas-magnetic-intent`**：`types.ts`、`MagneticEngine.ts`、`useMagneticDrag.ts`、
  `SnapSlotHighlight.tsx`、`CanvasShell.tsx`、`styles.css` 均为该 zone 已登记文件；
  新增的 **`magnetic/bonds.ts`**、**`magnetic/SnapSeam.tsx`** 尚**不在**该 zone 的 `files` 清单内。
- 另有 V4.12.0 遗留的 `character_management_module.py`（zone `stage3d-core`）漂移未处理。
- 未跑 `--update`，等用户「解冻 stage3d-core」「解冻 canvas-magnetic-intent」授权后再重写基线。

---

## V4.12.0 (2026-09-12) — AI 画布启动性能重构（不再启动即预热）

### 🔍 根因
- **不是技术栈问题**。日志显示每次启动 `应用启动成功` 后 3s 就出现 `canvas bridge listening`，
  即**没点进「AI 画布」也在白烧**一份 桥(:18765) + 静态服(:3011) + WebEngine + 前端包。
- 触发点在 `character_management_module.setup_ui()` 末尾：`QTimer.singleShot(200, self._bootstrap)`
  **无条件**预热；而 `on_activated()` 是死钩子（宿主 `main_window` 从不调用），指望它兜底也指望不上。
- 分段实测（`.venv312` 探针）画出 4.2s 的账：
  `import canvas_bridge` 695ms + `bridge.start()` 20ms +
  **`ensure_active_provider_sensible()` 2148ms** + `is_ready()` 端口探活 521ms + 静态服 796ms。
  其中 2148ms 全部耗在 **`ollama_client.is_available()`**——对 `/api/tags` 的 HTTP 探活（超时 8s），
  且**是在 UI 线程上同步执行**。

### 🔧 重构
- **预热改为「仅可见时触发 + 幂等」**（`app/modules/lego/character_management_module.py`）：
  - `setup_ui` 末尾改为 `QTimer.singleShot(200, self._bootstrap_if_visible)`；新增 `_bootstrap_if_visible()`
    仅在 `self.isVisible()` 时预热，否则什么都不做。
  - 新增 `showEvent()`：切到本模块（宿主是 `QTabWidget.setCurrentIndex`）时预热，不依赖死掉的 `on_activated`。
  - `_bootstrap()` 开头加 `_booted` 幂等标志，重复进模块不再重复起桥/建 WebEngine；并加分段计时日志
    `画布预热计时 bridge=..ms prefs=..ms probe=..ms ready=.. total=..ms`。
- **`ensure_active_provider_sensible()` 惰性化**（`app/modules/lego/model_config.py`，非冻结区）：
  - 加**快路径**：`active` 已是具体云端 provider 时直接返回，零网络探测。
  - `_ollama_ok()` / `_configured_cloud()` 改为内部惰性函数，只在「未选 provider」或「选的正是 ollama」
    时才求值；`active` 为空时先查云 Key（纯本地读，便宜），没有再探 Ollama（贵）。
  - 判定语义与原实现**逐分支等价**：`2148ms → 0ms`（实测）。

### ✅ 验证
- **优化前**（`app_20260912.log`）：`应用启动成功`(18:39:59) → `canvas bridge ready`(18:40:02) → 静态服(18:40:06)，
  启动后 3~4s 稳定烧预热。
- **优化后**（`应用启动成功` 19:10:13 起）：4 分钟后日志**再无任何 canvas 桥/静态服记录**；
  进程存活（`python.exe` pid 1676 ≈ 1.1GB），而端口 **18765 / 3011 / 17371 全部 closed** → 未点进画布即零预热。
- 分段复测：UI 线程同步阻塞 **≈3.4s → ≈1.0s**；`ensure_active_provider_sensible` **2148ms → 0ms**。
- `py_compile` 通过。

### ⚠️ 冻结区漂移（待用户确认解冻）
- `frozen_zone_guard.py` 报 4 个文件漂移：`character_management_module.py`（zone `stage3d-core`）、
  `CanvasShell.tsx` / `styles.css` / `store.ts`（zone `canvas-magnetic-intent`，V4.11.0 双模式重构所致）。
- 均为**用户明确要求的功能改动**，未跑 `--update`，等用户授权后再重写基线。

---

## V4.11.0 (2026-09-12) — AI 画布双模式重构（小白模式 / 专业模式）

### 🆕 新增
- **画布档位 `editorTier`**（`vendor/shiguang-canvas/src/store.ts`）：`"novice" | "pro"`，持久化到 `shiguang-canvas:tier:v1`，默认 `pro`（存量用户行为不变）。
- **顶栏模式切换**（`AppNav.tsx`）：右上角「小白模式 / 专业模式」分段开关；「我的画布」页也加了同样的切换 + 当前档位工程数。
- **小白模式卡面**（新增 `src/novice/`）：
  - `NoviceCard.tsx` — 纯矩形磁吸卡片，对齐规格 4.1（宽 240 / 圆角 8 / 标题栏 40 / 内容区最小 120 / 状态栏 32），含类型色左边条、黄色意图提示条、状态灯、意图胶囊层数指示、卡片菜单（生成新版本 / 复制 / 删除）。
  - `NoviceInspector.tsx` — 右侧面板参数降维：L1 导演参数（提示词 / 画质 / 时长 / 运动幅度 / 相似度）常显，L2 进阶折叠（镜头运动 / 画面比例 / 风格强度 / 负面提示词 / 种子），**L3 专业参数完全不出现**；意图胶囊三层（表面 / 语义 / 实现）可视化并可选层。
  - `types.ts` — 规格常量：卡片几何、画质档位、运动幅度、镜头运动、`KIND_STYLE` 类型配色、`QUALITY_PRESET` 画质联动表、状态灯映射。
  - `index.ts` — `buildNoviceNodeTypes()`：内置节点（键不含 `:`）统一换成 `NoviceCard`，插件节点保留原渲染器。

### 🔧 重构
- **不重建第二张画布**：小白模式复用同一个 ReactFlow 实例与同一份 `nodes/edges`，只换卡面与参数面板；撤销重做、自动保存、入轨、Agent 全部原样复用，不存在两套数据。
- **小白模式交互收敛**：强制开启磁吸（`magneticMode`）、隐藏连线（`flowEdges = []`）、隐藏「节点/表单/分镜条」布局开关，改为显示「小白模式 · 磁吸意图画布」标识；切到小白自动回到 `flow` 布局。
- **缩小后视觉**（规格 4.5）：缩放到 60% 以下时卡片只留类型色块 + 标题，隐藏内容区与状态栏。
- **工程按档位隔离**：`ProjectMeta.tier` / `ProjectBundle.tier` 落地；`listProjects(tier)` 按档位过滤；保存时沿用原档位、新建/导入时按当前档位写入；`ensureWorkspace()` 只认当前档位的工程，不会抢占另一档的工程。

### ✅ 验证
- `vite build` 通过（`built in 3.91s`，dist 产物已刷新）。
- `tsc --noEmit`：新增的 `novice/*`、`AppNav`、`StudioPages`、`WorkspaceCanvasMenus`、`store.ts` **零错误**；`CanvasShell.tsx` 仅剩 2 处 **存量** `onNodeDrag`/`onNodeDragDone` 类型不匹配（`git diff` 确认本次未触及该行），`bridge.ts` / `riggedHumanoid.ts` / `Stage3D.tsx` 为存量错误。

---

## 未发布 (2026-08-21) — 时间线控件大文件治理

### 🔧 重构
- **`timeline_widget.py` 拆分**（3462 → 1427 行）：
  - 阶段1：底层常量 / 工具函数 / `_MediaWorkerGate` + 4 个子控件（`TimeRuler`、`TimelineMarkerLayer`、`TrackControlPanel`、`TrackViewport`）抽到 `timeline_subwidgets.py`。
  - 阶段2：`ClipWidget`（~1310 行）抽到 `clip_widget.py`，`_find_timeline_widget` 内延迟导入 `TimelineWidget` 解除 `isinstance` 循环依赖。
  - 原文件通过 re-export 保持外部 `import` 兼容。
- **`modules.py` 死代码清理**（3327 → 1903 行）：
  - 删除尾部重复的时间线控件实现（`TimeRuler` / `TrackControlPanel` / `TimelineWidget` / `ClipWidget`，约 1424 行），这些类已被 `timeline_widget.py` / `timeline_subwidgets.py` / `clip_widget.py` 取代。
  - 改为从新模块 re-export 保持向后兼容，`from .modules import TimelineWidget / ClipWidget / TimeRuler / TrackControlPanel` 等外部引用继续可用。
- **`canvas_bridge.py` AIGC 层拆分**（4700 → 2763 行，抽离 2072 行到 `canvas_aigc.py`）：
  - 关键词常量 `VIDEO/AUDIO/IMAGE_KEYWORDS`、`guess_capability`、`build_host_ai_config_patch`（模型广场渠道配置）、`_data_url_to_b64`、`generate_image_openai_compatible`、`inpaint_via_host`、`_resolve_aigc_channel`、`generate_audio_via_host`、`agent_chat_proxy`、`generate_video_via_host`、`generate_music_via_host` 及分镜拉片（`_parse_storyboard_json` / `_heuristic_storyboard` / `storyboard_breakdown`）统一迁移。
  - `canvas_aigc.py` 提供 `_canvas_inbox_dir()` 惰性代理（调用时再 `import canvas_bridge`），解除拆分后的循环导入。
  - 原文件通过 re-export 保持外部 `import` 兼容。
- **`canvas_bridge.py` HTTP 服务层拆分**（2763 → 870 行，抽离 2093 行到 `canvas_server.py`）：
  - 本地小 HTTP 桥（`_check_host_token`、`_BridgeHandler`、`_build_inject_js`、`CanvasBridgeServer`、`get_canvas_bridge`）及提示词远程代理、`/host/*`、`/ingest`、`/ingest_path`、`/push_from_editor`、`/inbox_file`、`/editor_outbox`、`/inject.js` 等 HTTP 端点与 SSE 事件流统一迁移。
  - `canvas_server.py` 顶部单向依赖 `canvas_bridge`（IO / 状态 / 媒体层符号，共 28 项）+ `canvas_aigc`（AIGC 能力，8 项）；`canvas_bridge.py` 末尾 re-export `canvas_server.py` 形成闭包，解除循环导入。
  - 端口 18765（stage3d-core 冻结）仍由 `canvas_bridge.py` 的 `DEFAULT_PORT` 唯一定义，`canvas_server.py` 仅引用不改写。

### ✅ 验证
- `py_compile` / `compileall` 通过；`TimelineWidget`、`ClipWidget`、`_TIMELINE_BASE_PPS` 均可正常导入（re-export 有效，无循环导入）。
- `modules.py` re-export 身份验证通过（`modules.TimelineWidget is timeline_widget.TimelineWidget`）。
- `canvas_bridge.py` re-export 身份验证通过（`canvas_bridge.storyboard_breakdown is canvas_aigc.storyboard_breakdown`），16 个拆分符号均可在原模块访问。
- `canvas_server.py` re-export 身份验证通过（`canvas_bridge.get_canvas_bridge is canvas_server.get_canvas_bridge` 等 5 个服务层符号 + 28 项 IO 层符号共享状态一致），无循环导入。
- `frozen_zone_guard.py` 52 锁完好（拆分后 `--update` 重写基线）；`stability_gate.py` 无新增违规（430 项存量固化，含随行号迁移的 11 项 `swallow-except`）。

---

## V4.10.3 (2026-08-19) — 打包就绪（spec 重写 + venv 清理）

### 🐞 修复
- **spec torch 子模块收集时序 bug** (`app/ai_video_editor_local.spec`): torch/torchvision/torchaudio 的 `collect_submodules` 在 `hiddenimports` 拼接**之后**才执行，结果收集结果从未进入 hiddenimports（打包后极易出现 `ModuleNotFoundError: torch.xxx`）。已将全部 11 个包的收集移到拼接之前，torch 2247 个子模块现可正确入包。

### 🆕 新增 / 增强
- **spec 重写**：datas 补齐 `license/`（入口 `main_qt6.py` 直接导入）与 `app/config.json`；hiddenimports 补齐 `PyQt6.QtWebChannel/QtPrintSupport`、`cv2`、`psutil`、`aiohttp`、`requests`、`imageio_ffmpeg` 等；easyocr/faster_whisper 数据文件经 `collect_data_files` 收集（easyocr 116 条）。
- **虚拟环境清理**：删除 5 个冗余/损坏 venv（`.venv`、`venv`、`app/venv`、`app/packaging_env`、`bmf_env`，合计约 1.9G），仅保留开发主力 `.venv312`。

### ✅ 验证
- 用 PyInstaller 同款机制（桩掉 Analysis/PYZ/EXE/COLLECT）exec 解析 spec：hiddenimports 6832 项、datas 125 条全部存在、关键项（license/cv2/psutil/QtWebChannel 等）全在列，RESULT: PASS。
- 旧 spec `AI短剧编辑器.spec` 已不存在，无残留冲突。

---

## V4.10.2 (2026-08-19) — add_clip 撤销支持补全

### 🐞 修复
- **AI剪辑/画布入轨/素材拖入的片段不可撤销** (`editor_module.py`): `_add_clip_to_timeline()` 此前不调用 `_record_action()`，导致所有通过 FunClip/AutoClip/LLM裁剪/画布「发送到剪辑」/素材库拖入进入时间线的片段按 Ctrl+Z 无反应。现新增 `"add_clip"` 类型的 undo/redo 处理（`_apply_action` 新增分支），同时处理视频片段与联动音频片段的撤销与重做。

### ✅ 验证
- `py_compile` 编译通过；`frozen_zone_guard.py` 确认 45 锁完好无 drift。
- 修改仅在 `_apply_action()` 新增分支 + `_add_clip_to_timeline()` 末尾追加 `_record_action()` 调用，未触碰任何冻结符号。

---

## V4.10.1 (2026-08-14) — Agent Plan/B/C 策略

### 🆕 新增 / 增强
- **会话模式**：剪辑 Agent 与画布 Agent-IM 统一 Plan / 协作 B / 自主 C（默认 B）。
- **Policy Engine**：`agent_policy.py` 按工具 effect 决定允许 / 需确认 / 拒绝；Plan 不向模型暴露写工具。
- **预算与停止**：每会话 12 轮模型、24 次工具；侧栏「停止」暂停后续轮次。
- **画布写确认**：协作模式下 `task.create` 改节点/生成前弹出确认；与后端矩阵一致。
- **任务与工具循环**：`agent_task_store` 持久化；B/C 可输出 `canvas_tools` 经 SSE 落画布；剪辑/画布支持排队、暂停、继续、重规划。

### 明确不做
- 未接入 Tauri MCP、通用网页搜索、会话文件授权、IndexedDB 任务持久化。

---

## V4.10.0 (2026-08-13) — AI画布与Agent调度

### 🆕 新增 / 增强
- **AI 画布** (`vendor/shiguang-canvas` + 宿主桥): 无限画布落地页顶栏/导航壳；默认 `shiguang-canvas`；3D 导演台单人/群像模板；AIGC 生成入轨链路持续对齐。
- **Agent 能力调度层**: 能力注册与剪辑面板拆分模块；Tool Registry 收敛设计落地起步。
- **账号运营插件化**: `account_ops_plugin`，入口改走拓展中心（注册表不再挂 `account` 内置模块）。
- **帮助中心**: 补充 AI 画布与 AIGC 模型说明。

### 🐞 修复
- **画布预热卡住 / 切换无反应**: 后台线程改用 `pyqtSignal` 回主线程。
- **AIEngine 单例腰斩**: `__init__` 被 `get_instance()` 中断导致 `_clients_loaded` 永不设置。
- **Agent publish**: `account.publish` 默认 `skill_id` 死值修复。
- **FFmpeg/ffprobe**: 路径自动检测统一；波形生成优先 FFmpeg；缩略图/初始化兼容修复。
- **高危/中低危批次**: Agent、剪辑核心与模块审计修复。

### 🧹 工程
- 删除零引用死代码（`AppState`、孤儿 render 包等）；`.venv312` 移出跟踪。
- 冻结区重新上锁并更新哈希基线；知识库同步至 2026-08。

---

## V4.9.2 (2026-07-13) — 贴纸预览与滤镜播放优化

### 🐞 修复

- **贴纸渲染后视频不更新** (`editor_module.py`): 贴纸渲染成功后仅调用 `_add_to_clips` 将结果加入素材列表，但未加载到 `QMediaPlayer`，用户看不到任何变化。现在渲染完成后自动将结果视频加载到播放器并切回 `QMediaPlayer` 预览，用户立即看到贴纸效果。
- **切换滤镜后播放卡顿** (`editor_module.py`): 滤镜激活时 `_refresh_preview_with_effects` 将预览切到 `PreviewManager`（OpenCV CPU 逐帧解码 + numpy 效果），1080p/720p 视频无法实时渲染导致严重卡顿。改为**分策略预览**：暂停/拖拽时用 `PreviewManager` 精确渲染滤镜效果，播放时切回 `QMediaPlayer` 硬件加速流畅播放。`_play_pause`、`_rewind`、`_fast_forward`、进度条拖拽释放均已联动此策略。

## V4.9.1 (2026-07-12) — 剪辑导出可用性修复（续）

### 🐞 修复（致命后端崩溃）

- **subprocess 参数拼写错误（致命）** (`video_processor.py`): 模块内 12 处 `subprocess.run(...)` 误用 `creation_flags=`（带下划线），而 `subprocess.Popen` 仅接受 `creationflags=`（无下划线）。该错误导致 **裁剪(`trim_video`)/滤镜(`apply_video_filter`)/合并(`merge_videos`)/转场(`merge_with_transitions`) 等所有 ffmpeg 调用** 在真正执行时立即抛出 `Popen.__init__() got an unexpected keyword argument 'creation_flags'`，整个剪辑后端完全瘫痪——用户在 UI 上点任何剪辑操作都会静默失败。已用 `replace_all` 统一为正确拼写 `creationflags=`，全项目 `app/` 目录已确认无残留错误拼写。

### ✅ 验证
- 用真实 ffmpeg 跑通「裁剪 → 滤镜烘焙(电影感/黑白) → 画面调节(eq) → 转场(xfade 淡入淡出) → 导出设置(640x360/24fps/2M/H.264/AAC)」完整管线。
- 产物 `final.mp4` 实测 `640 x 360 fps: 24`，`apply_export_settings` 返回 `True`，`RESULT: PASS ✅`。
- `editor_module.py` / `video_processor.py` / `editor_scheduler.py` 三模块 `py_compile` 全部通过。

---

## V4.9.0 (2026-07-12) — 剪辑导出可用性修复

### 🐞 修复（核心可用性）

- **导出致命崩溃修复** (`editor_module._build_edited_video`): `clip["effects"]` 曾被初始化为列表 `[]`，而导出时代码对其调用 `.get()` 触发 `AttributeError`；该异常在无 `except` 的 `try` 中上抛，被 `_export_video` 捕获后静默回退到原始单段素材——**所有剪切/复制/滤镜/转场编辑全部丢失**。现统一 `effects` 为字典并做安全访问，编辑成果可真实进入成品。
- **滤镜按钮全部接通** (`editor_module._make_effect_tab`): 原 12 个滤镜按钮创建后从未绑定点击事件，且「应用滤镜」按钮写死传入非法字符串 `"selected"`（不在滤镜表里），导致滤镜永不烘焙。现每个按钮映射到合法滤镜键并应用；新增 `梦幻/锐利/柔和/都市/黄昏` 五个滤镜（`video_processor._FILTER_CATEGORY_VF`）。
- **导出设置真实生效** (`video_processor.apply_export_settings` + `editor_scheduler.export_video`): 此前 UI 上选的 分辨率/帧率/码率/编码/音频 全部被忽略（轻量内核 `process([])` 仅原样复制）。新增最终转码环节，按设置套用 `scale/fps/编码/码率`。
- **画面调节写入并烘焙** (`editor_module._apply_video_adjustments`): 亮度/对比度/饱和度/色调此前只 `print` 不落盘。现写入当前片段 `effects.color_params`，导出时经 `map_filter_to_vf` 烘焙为 `eq` 滤镜（`map_filter_to_vf` 新增 hue 支持）。
- **传统 AI 剪辑 NameError** (`editor_module._ensure_ai_clip_algorithm`): `AIClipAlgorithm` 被使用却从未导入。改为懒加载（`from .modules import AIClipAlgorithm`）并 `try/except` 兜底，失败时优雅降级而非崩溃。

### ✅ 验证
- 已用真实 ffmpeg 跑通「裁剪 + 滤镜烘焙 + 转场 xfade + 调节 + 导出设置」完整管线，产出合法视频文件。

---

## V4.8.1 (2026-07-12) — AI特效制作插件

### 🆕 新增
- **AI特效制作插件** (`app/plugins/ai_effects_plugin/`): 完整的智能视频/图像特效处理系统（4316行代码），符合PLUGIN_STANDARD规范，实现IEffectPlugin接口全部必需方法
  - **风格迁移模块** (`effects/style_transfer.py`, 379行): 8种预设艺术风格——梵高星空🌀、莫奈睡莲💐、毕加索抽象🔷、赛博朋克🌃、动漫风✨、油画🎨、水彩画💧、素描✏️；可调节风格强度(0-100%)与颜色保留选项；基于双边滤波+边缘增强算法
  - **背景替换模块** (`effects/background_replace.py`, 300行): GrabCut语义分割自动识别前景；5种背景类型(纯色/模糊/自定义图片/渐变/透明)；边缘羽化平滑过渡；集成QColorDialog颜色选择器
  - **超分辨率模块** (`effects/super_resolution.py`, 385行): 支持2x/3x/4倍放大；3种质量模式(快速⚡/均衡⚖️/高质量🎯)；内置3级降噪算法(高斯/双边/NL-Means)；多尺度细节重建+USM锐化；含VideoSR子类支持帧间时序融合
  - **智能美颜模块** (`effects/beauty_filter.py`, 458行): 自动人脸检测(Haar级联)；4维美颜参数(磨皮/美白/瘦脸/大眼)；自然效果模式开关；**4个快捷预设**(自然清新/柔光女神/精致妆容/韩式偶像)；局部网格变形技术
  - **物体移除模块** (`effects/object_removal.py`, 639行): 3种移除模式(自动检测🤖/手动框选▢/笔刷涂抹🖌️)；4种填充算法(AI Inpainting/Content-Aware Fill/Blur Fill/Clone Stamp)；11类可检测物体(文字水印/Logo/印章日期戳/人物汽车建筑等)；FFT频域文字检测技术
  - **PyQt6控制面板** (`ui/ai_effects_widget.py`, 1003行): 5标签页UI架构；20+参数控件(滑块/下拉框/颜色选择器/复选框/SpinBox)；EffectProcessorThread后台线程处理避免UI阻塞；实时预览区；进度条显示

### 🔌 插件规范
- 实现IEffectPlugin完整接口: `plugin_info`属性、`initialize`/`shutdown`生命周期、`get_ui_config`配置、`apply_effect`核心方法、`get_effect_params`参数定义
- PLUGIN_INFO元信息: name/version/author/category/icon/entry_point/tags/compatibility完整定义
- manifest.json配置清单符合PluginStore发布格式
- 支持PluginLoader自动发现与热加载
- 单例模式确保资源唯一性 + 懒加载模型机制
- 完整README.md使用文档(17KB, 含8个API示例)

### 📦 依赖
- 必需: numpy>=1.21, opencv-python>=4.5, Pillow>=8.0, PyQt6>=6.2
- 推荐(高级功能): torch>=1.10, dlib>=19.22, mediapipe>=0.8

---

## V4.8.0 (2026-07-11) — 滤镜转场落盘与云 API 懒加载

### 🆕 新增
- **滤镜/转场烘焙进导出视频**: `video_processor` 新增 `map_filter_to_vf` / `apply_video_filter` / `merge_with_transitions`，将预览态的滤镜(黑白/复古/清新/暖色调/冷色调/电影感)与转场(淡入淡出/滑动/缩放/模糊/翻转/溶解/擦除)通过 ffmpeg `-vf` 与 `xfade`/`acrossfade` 真正写入成品；`editor_module._build_edited_video` 重构为「先逐段烘焙滤镜 → 再按需 xfade 合并」，实现预览即所得
- **Sprint 2 云 API 懒加载注册表**: `cloud_providers/registry.py` 的 `ProviderRegistry` 支持 `register` / `bulk_register` / 懒加载 `resolve`（首次调用才动态 `importlib` 导入并缓存）+ 动态注册；`cloud_api.py` 改用 `default_registry`，消除对 15 个 provider 类的急切导入依赖
- **ai_clip_flow 步骤契约单测**: `tests/test_ai_clip_flow_steps.py` 以 sys.modules 桩件在无 GUI 环境下加载模块，校验「84 行编排器 + 5 个 step 方法」的派发顺序与统一签名(settings/vp/work_dir/base_name/current_output/progress/results)，并验证 current_output 在步骤间正确透传

### 🧪 测试
- conftest `reset_core_singletons` 在缺少 PyQt6 的无头/CI 环境下静默跳过单例重置，避免阻断不依赖 GUI 的单元测试

## V4.6.0 (2026-06-19) — Sprint 1 清债与架构修复

### 🐛 Bug 修复
- **删除 3 个冗余旧类**: `modules.py` 中 `ThreadPool`/`HardwareDetector`/`PerformanceMonitor` 旧版定义覆盖了 `utils/` 的正确导入（隐蔽 Bug）
- **修复 editor 懒加载路径**: `module_registry.py` 中 `import_module` 从 `.modules` 改为 `.editor_module`，避免触发整个 modules.py 全量加载

### 🔧 架构重构
- **BaseModule 独立化**: 从 `modules.py` 提取 `BaseModule` 到 `base_module.py`，解除 9 个子模块的循环依赖风险
- **render 包瘦身**: `render/__init__.py` 从 277 行实现代码 → 9 行 re-export，实现类移至 `render/render_core.py`
- **SettingsModule/HelpModule 统一继承 BaseModule**: 获得 EventBus/DataBus 自动注入 + 统一 `set_theme()` 接口
- 9 个子模块的 `from .modules import BaseModule` 全部改为 `from .base_module import BaseModule`

### 📦 modules.py 精简
- `modules.py` 从 ~1925行 压缩到 ~1810行（删除冗余类 + BaseModule 提取）

---

## V4.5.0 (2026-06-19) — Sprint 0 深度拆分

### 🔧 重构
- **TimelineWidget 家族4类** 拆分为独立文件 `timeline_widget.py`（~1225行）: TimeRuler、TrackControlPanel、TimelineWidget、ClipWidget
- **HelpModule** 拆分为独立文件 `help_module.py`（~822行）
- `modules.py` 从 ~1925行 进一步压缩（TimelineWidget 家族已拆分）
- `settings_module.py` 从 ~3261行 压缩到 ~2439行（-25%）
- `module_registry.py` 同步更新 help 模块导入路径

### 🎨 UI
- **合并设置选项卡**: "主题"+"字体" → 统一 "外观" 选项卡
- **新增关于页面**: 精美 QSS 渐变设计，显示版本号 V4.5.0 + 技术栈标签

### 🐛 修复
- 窗口标题版本号同步: v3.0 → v4.4.0
- `materials_module.py`/`tasks_module.py` 中 `QMimeData`/`QUrl` 导入更正（PyQt6.QtGui → QtCore）

---

## V4.4.0 (2026-06-19) — Sprint 0 模块拆分

### 🔧 重构
- **CopywritingModule** 拆分为独立文件 `copywriting_module.py`（~1050行）
- **TasksModule** 拆分为独立文件 `tasks_module.py`（~750行）
- **MaterialsModule**（含 `_DraggableAssetList`）拆分为独立文件 `materials_module.py`（~570行）
- `modules.py` 从 ~5500行 压缩到 ~3150行（减少 ~43%）
- `module_registry.py` 同步更新3个模块的导入路径
- 修复 `materials_module.py` 缺失的 `_current_page/_page_size/_current_materials` 初始化和 `_change_page()` 方法

---

## V4.3.0 (2026-06-19) — 第二轮专项补全

### 🆕 新增
- **DramaWebScraper** (`drama_web_scraper.py`): 短剧Web抓取器，从公开数据聚合源获取真实热榜
- **drama_data.json**: 92条结构化短剧数据JSON缓存
- **CopywritingModule.batch_generate()**: C-1 批量文案生成，支持多输入并发LLM调用
- **CopywritingModule.ab_generate()**: C-3 A/B多版本文案对比，含5维评分引擎
- **BatchTaskManager 定时调度 (T-6)**: `schedule_task()` + 后台调度线程，支持延迟执行
- **BatchTaskManager 并发控制**: `threading.Semaphore` 限制真正并发数

### 🔧 修复
- **DramaCrawler._init_apis()**: 集成 DramaWebScraper 作为第四层兜底数据源
- **DramaCrawler.fetch_dramas()**: 在API失败后/Plywright失败后增加Web抓取器中间层
- **BatchTask 数据类**: 新增 `depends_on`(T-1), `max_retries/retry_count/retry_delay`(T-3), `scheduled_at`(T-6)
- **BatchTaskManager._process_queue()**: 集成T-1依赖检查——只有依赖完成的任务才执行
- **BatchTaskManager._execute_task_with_retry()**: T-3自动重试机制
- **BatchTaskManager.add_task()**: 支持 depends_on/max_retries/scheduled_at 参数

---

## V4.2.0 (2026-06-19) — 开源专项补全

### 🆕 新增
- 版本号管理体系 (`app/version.py`, `CHANGELOG.md`)
- DouyinUploader / BilibiliUploader: Playwright 自动化平台发布
- GenericUploader: 通用多平台导出器
- video_processor.py 新增7种操作类型: add_bgm, sharpen, denoise, saturation, stabilize, upscale, logo_removal

### 🔧 修复
- **video_processor.py**: `_find_highlights()` 对接 AutoClipIntegration 真实算法；`_classify_content()` 改为10类关键词匹配
- **platforms/__init__.py**: `publish_to_platform()` 从纯模拟→3级策略（Playwright→本地导出→错误）
- **account_skills.py**: `_collect_platform_data()` / `_do_publish()` / `_batch_publish()` 对接真实模块
- **workflow_manager.py**: 4个核心步骤 (下载/剪辑/文案/发布) 全部对接真实模块
- **llm_editor.py**: 6个action 全部真实映射 — add_transition→TransitionManager / add_effect→EffectManager / add_subtitle/add_title→SubtitleManager / change_speed→tm.update_clip / adjust_volume→tm.update_clip

---

## V4.1 (2026-06-19) — 乐高积木式插件架构

### 🆕 新增
- 乐高积木式模块架构: CORE(4) / ADVANCED(5) / EXPERIMENTAL(5)
- 自然语言编辑器 (LLMEditor)
- 全链路工作流管理器 (WorkflowManager)
- 账号运营Skills系统 (AccountOpsModule)
- 平台集成发布系统 (PlatformIntegrator)
- 开源项目专项补全方案 (第十一章)

### 🔧 修复
- AutoClip 5维高光检测算法 (运动40%+音频25%+场景15%+面部20%+综合)

---

## V3.0 (2026-06) — PyQt6 AI短剧编辑器

### 🆕 新增
- PyQt6 桌面端应用架构
- AI短剧剪辑流水线
- 多平台发布框架
- 14个模块插件系统
