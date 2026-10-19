# 「代码 × 扩散」混合视频 · V4.45 渲染引擎刀规划

> **状态**：**已落地（V4.45.0，2026-10-19）**——T2-T7 完成；真渲染 + QC + ffprobe 门禁全绿；
> 仅 T8（用户真机验收：3 镜头分镜 → inbox 播放）待交回用户执行。
> **日期**：2026-10-19
> **上游**：[`docs/CHANGELOG.md`](CHANGELOG.md) V4.44.0 条目 · `app/core/code_video/spec.py`
> **下游**：V4.46 画布刀（`codeVideo` 节点 + 端点 + SSE 进度，需解冻 `canvas-magnetic-intent`）
> **纪律**：本刀**零冻结区**、**零画布改动**、**零 `_clips` 改动**；渲染产物只落 inbox，不形成第二套时间线真相源。

---

## 0. 一句话结论

V4.44 已把「两条视频路线」收进一个 **JSON 契约**（`CodeVideoSpec`）。
V4.45 要做的是**只实现一条权威渲染路径**：把 `compiled` 契约按 `frame(t)` 逐帧画出来、用 ffmpeg 编码、诚实地报告每一步失败——**先做对，再做快**。

```
compiled spec ──► 资源解析/安检 ──► Chromium frame(t) 逐帧截图 ──► ffmpeg 编码 ──► inbox mp4
                         │                    │                       │
                    security.py          render_worker.py          render_host.py
                         └──────────── video_critic.py（同 t 双乱序质检）────────────┘
```

---

## 1. 现状核实（2026-10-19 实测，非转抄）

| 项 | 实测结果 | 证据 |
|---|---|---|
| V4.44 契约域 | `spec.py` **677 行**，零 Qt/ffmpeg 依赖，可独立 import | `_verify/check_code_video.py` A 节 |
| 契约测试 | **23 passed / 0.40s** | `pytest app/tests/test_code_video_spec.py -q` |
| 契约门禁 | 全绿（注册↔目录↔别名、lineage 六键同源、文字层反例被拒、行数棘轮） | `python _verify/check_code_video.py` |
| 计划态能力 | `pipeline.code_video_plan`（read / 免费）已三处注册 | `agent_capability_catalog.py:447` · `capability_handlers.py:1677` · `agent_action_registry.py:67` |
| 渲染能力 | **未注册**（刻意不建空壳） | CHANGELOG V4.44「明确不做」 |
| Chromium | Playwright 可用，`chromium-1243` / `chromium_headless_shell-1243` 已安装 | `%LOCALAPPDATA%\ms-playwright` |
| FFmpeg | `C:\ProgramData\chocolatey\bin\ffmpeg.EXE` 可用；项目内统一入口 `ffmpeg_utils.find_ffmpeg()` | `shutil.which` 实测 |
| 隔离先例 | OTIO 走 `_otio_worker.py` 独立子进程（Qt 段错误红线）；pose 走 `pose_worker.py` | `app/core/interchange/_otio_worker.py:1-14` |
| inbox 出口 | `video_gen.publish_to_inbox()` → `canvas_bridge.canvas_inbox_dir()` + `/inbox_file/<name>` | `app/core/neural/video_gen.py:623` |
| 体积守卫 | 单文件 ≤ 2000 行，新文件不许一上来超标 | `_verify/check_file_size.py` |
| V4.44 提交状态 | **未提交**（工作区含 8 个修改 + 新增 code_video 三件套） | `git status --short` |

> **前置动作 P0**：先提交 V4.44（精确 pathspec，禁 `git add -A`——工作区有 `vendor/_tmp_*`、
> 并行线文档与用户报告，历史上已两次因 `-A` 误提交）。
> 提交前跑：`_verify/check_code_video.py` + `pytest app/tests/test_code_video_spec.py` +
> `frozen_zone_guard.py` + `check_capability_catalog.py`。
> 建议提交信息：`feat(code_video): V4.44 契约刀——CodeVideoSpec 渲染契约 + pipeline.code_video_plan`。

---

## 2. 设计决策（先定不做什么）

### D1. 只做 **一条** 权威渲染路径：Chromium `frame(t)`

**决策**：V4.45 **不** 实现「纯素材 ffmpeg 快速路径」。所有渲染统一走「合成页面 + 逐帧截图」。

理由：
1. **单一实现**。项目反复踩过「同一动作两条链路必然漂移」的坑（§5 磁吸区、3D 产物入轨单通道、生成视频单分支）。两条渲染路径 = 两套 fit/speed/overlap 语义，必然对不齐。
2. **先对后快**。快速路径的正确性证明成本（像素等价、音画对齐、转场）远高于收益；V4.45 先把 `frame(t)` 做成事实标准。
3. **可量化再优化**。V4.45 产出基准数据（每帧截图耗时、编码耗时、总耗时），V4.45.5 再决定是否加 ffmpeg 直通，届时必须有「双路径等价测试（容差）」作为前置。

**性能预算（诚实写死）**：≤60s、≤12 clips、1080×1920、fps∈{24,30} ⇒ 最多 **1800 帧**。
单帧截图目标 ≤60ms ⇒ 帧捕获 ≤108s；H.264 编码 ≤20s。**总上限 6 分钟**，超时即诚实失败。
（若实测超预算：优先降 `render.parallel_pages` 并发、再评估快速路径，**不偷偷降分辨率/帧率**。）

### D2. 子进程隔离：`render_worker.py` 不 import Qt

沿用 OTIO worker 纪律：主进程必然先加载 PyQt6，**Chromium/Playwright 驱动放在无 Qt 子进程**，
主进程只做编排、编码、发布。`render_host.py` 模块顶层**不得** import PyQt6/QtWebEngine。

### D3. HTML 镜头必须「自包含单文件」

`html://name.html` 的语义在 V4.45 收紧为：**自包含**（样式/脚本内联，零外部请求）。
- 技术原因：用 `iframe srcdoc` 内联注入可保证同源、可控、无网络面；外部 `<script src>`/`<link href>`/`@import` 一律拒绝。
- 安全原因：LLM 生成的 HTML 是唯一不可信输入，**能少一个入口就少一个**。
- 该收紧是 `spec.py` 文档级约定，不改结构（`html://` 仍是 `<name>.html`），由 `security.py` 在渲染前强制。
- 若 LLM 需要图片素材，走 `asset://` 登记，由合成页以 `<img>` 加载**本地 file/inbox 资源**（仍受路径 jail 约束）。

### D4. 音频单独用 ffmpeg 合成，不从 Chromium 抓

Chromium 只负责**画面帧**。音频由 `render_host` 用 ffmpeg 精确拼：
- 每个有声 clip：`-ss source_range.start -t (range 长 × speed)` → `atrim` → `asetpts` → `volume` → `adelay` → `amix`；
- `speed ≠ 1` 时用 `atempo`（链式支持 0.25–4.0），**不静默丢弃变速片段的声音**；
- 全片无音源 ⇒ `anullsrc` 静音轨（诚实：输出有音轨但为静音，不是「无声视频」）。
- 不引入第二套混音器；纯函数生成 filter graph，可单测。

### D5. 质检（QC）只报「测到的」，测不到就明说

`video_critic.py` 三项 V4.45 必做：
1. **同 t 双乱序**（OpenFilm `look` 的核心）：取 5 个采样 t，按固定顺序 A 渲染一次、顺序 B 渲染一次，
   逐帧比对 PNG 哈希。不一致 ⇒ 报告「哪个 t 出了两张不同的画」+ 疑似根因（时钟/未播种随机/帧间状态）。
2. **文字安全区**：合成页给文字层加 `data-sg-text`；worker 逐帧回传元素 rect，
   critic 判断是否越出 `qc.text_safe_area`（默认 5% 边距，竖屏避让）。
3. **平色帧检测**：采样帧颜色方差过低 ⇒ 报告「可能是空画面/黑场」，**只是 warning，不判失败**（黑场也可能是创作意图）。
4. 响度（EBU R128）**V4.45 不做**：在 `qc.checks` 里显式 `not_wired` 并写原因，不假装测过。

### D6. 失败语义（与项目铁律一致）

| 情况 | 行为 |
|---|---|
| spec 未通过 `compile_spec` | 拒绝渲染，原样返回 errors |
| Playwright/Chromium 缺失 | `success=False`，error 明写安装指引；**绝不回退到「直接拼接素材」假装成功** |
| 素材缺失/越界 | 拒绝渲染，列出 clip id 与原因 |
| HTML 安检不过 | 拒绝渲染，列出文件与命中规则 |
| 单帧截图超时 | 重试 1 次；仍失败 ⇒ 中止并报告 frame index/t，不产出半成品 |
| 渲染超总时限 | 中止、清理临时目录、报告已渲染帧数与耗时 |
| ffmpeg 编码失败 | 保留帧目录路径供排查，返回 stderr 尾部（脱敏后） |
| 成功 | 只在「mp4 存在 + ffprobe 时长/fps 校验通过」后返回 `ok=True` |

---

## 3. 模块拆解与行数预算

| 文件 | 职责 | 预算 | 关键约束 |
|---|---|---|---|
| `app/core/code_video/security.py` | HTML 静态安检、路径 jail、资源限额、自包含判定 | ≤260 行 | 纯标准库；零 Qt；返回错误列表 |
| `app/core/code_video/page_builder.py` | 合成时间线页面（纯函数）：叠层/fit/iframe srcdoc/确定性时钟/postMessage | ≤380 行 | 零 I/O；可字符串断言；iframe 用 postMessage（file:// 跨源实测） |
| `app/core/code_video/render_worker.py` | 子进程：启动 Chromium、`frame(t)`、截图、回传文字 rect | ≤380 行 | **禁止 import PyQt6**；只依赖 playwright + stdlib |
| `app/core/code_video/render_host.py` | 编排：安检→解析→生成合成页→拉 worker→音频→编码→inbox→QC | ≤420 行 | 顶层零 Qt；ffmpeg 走 `ffmpeg_utils` |
| `app/core/code_video/video_critic.py` | 双乱序比对、文字安全区、平色检测、报告结构 | ≤260 行 | 纯函数优先；PIL 缺失时诚实 not_wired |
| `app/core/code_video/audio_graph.py` | 音频 filter graph 纯函数（atrim/atempo/volume/adelay/amix） | ≤180 行 | 单独可测，避免 render_host 膨胀 |
| `app/core/capability_handlers_code_video.py` | 增 `code_video_render` 薄壳 | 96 → ≤150 行 | 只转发，算法都在 code_video/ |
| `app/core/agent_capability_catalog.py` | +1 行 `pipeline.code_video_render` | +1 行 | 单一事实源 |
| `app/core/agent_action_registry.py` | +1 行别名 + help 文案 | +2 行 | 与目录一致 |
| `app/tests/test_code_video_render.py` | 纯函数/安检/失败路径单测 | ≤320 行 | 不依赖真 Chromium |
| `_verify/check_code_video_render.py` | 渲染引擎门禁（含可选真渲染冒烟） | ≤240 行 | 缺 Chromium 时显式 SKIP，不假绿 |
| `_verify/check_code_video.py` | 扩 F/G 节（引擎依赖隔离 / 注册一致 / 行数棘轮） | +80 行 | 原 E 节保留 |

> 所有新文件 ≤2000 行；实施中若超预算先拆分，**不允许抬 `check_file_size.py` 基线**。

---

## 4. 数据流与接口契约

### 4.1 输入（能力参数）

```jsonc
{
  "spec": { /* CodeVideoSpec.to_dict()，或 */ },
  "storyboard": [ /* 可选：与 spec 二选一，走 from_storyboard */ ],
  "html_root": "data/code_video/html",   // 可选；默认路径，必须存在
  "output_name": "code_video_20261019_1.mp4", // 可选；默认时间戳
  "qc": { "dual_shuffle": true, "sample_count": 5 } // 可选；默认 true
}
```

**二选一规则**：给 `spec` 用它；只给 `storyboard` 走 `from_storyboard`；两者都给 ⇒ `spec` 优先并把 warning 写进输出（不静默二选一）。
两者都没给 ⇒ `success=False`（与 `code_video_plan` 一致）。

### 4.2 输出（成功）

```jsonc
{
  "ok": true,
  "video_path": "<inbox 绝对路径>",
  "url": "http://127.0.0.1:18765/inbox_file/<name>",
  "duration": 23.5, "fps": 30,
  "render": { "frames": 705, "elapsed_s": 84.2, "path": "chromium" },
  "qc": {
    "ok": true,
    "checks": [
      {"name": "dual_shuffle", "status": "pass", "detail": "5/5 帧一致"},
      {"name": "text_safe_area", "status": "pass", "detail": "2 个文字层均在安全区内"},
      {"name": "flat_frame", "status": "pass", "detail": "5 个采样帧方差正常"},
      {"name": "loudness", "status": "not_wired", "detail": "V4.45 未接 EBU R128，不假装测过"}
    ]
  },
  "warnings": []
}
```

### 4.3 输出（失败）

```jsonc
{"ok": false, "error": "asset://shot_2.mp4 不存在（clip clip_shot_2；基准=canvas_inbox_dir 根）", "stage": "resolve_assets"}
```

`stage` ∈ `compile | security | resolve_assets | render | encode | publish | qc`，便于 V4.46 前端如实展示进度/失败点。

### 4.4 能力注册

| 字段 | 值 |
|---|---|
| id | `pipeline.code_video_render` |
| category | `pipeline` |
| effect | **`file_write`**（写 mp4 到磁盘；比 `read` 重，比 `canvas_write` 准确——它不改画布） |
| paid | `False`（纯本地 Chromium + ffmpeg） |
| 模式门禁 | 沿用 `agent_policy`：collaborative 写操作需确认；autonomous 可执行；plan 禁止；**写操作永不自动重试** |
| action 别名 | `code_video_render`（**级别在 T7 定**：action 表只有 `safe`/`dangerous` 两档——长耗时文件写按 `pipeline.submit` 先例应为 `dangerous`；若实测 `agent_policy` 的 `file_write` 已在 collaborative 模式强制确认，可留 `safe` 并写明依据） |

---

## 5. 安全模型（威胁 → 对策 → 验证）

**威胁假设**：HTML/JS 来自 LLM 或不可信模板；`asset://` 路径来自 spec；渲染结果会进画布 WebView。

| # | 威胁 | 对策（`security.py` + worker） | 验证 |
|---|---|---|---|
| S1 | HTML 外联（把素材/密钥/内网打出去） | 静态拒绝 `http(s)://`、协议相对 `//`、`fetch/XHR/WebSocket/EventSource/sendBeacon`、`import(`、`<script src>`、`<link href>`、`@import`；运行时 `page.route("**/*")` 只放行 `data:`/`about:`/`blob:`/`file:` 白名单根 | 单测逐条反例；守卫断言规则表在册 |
| S2 | 路径穿越（读任意盘文件） | `html://` 文件名正则（契约已有）+ realpath 必须在 `html_root` 内；`asset://` realpath 必须在 `canvas_inbox_dir()` 内；禁符号链接出根 | 单测 `..`/盘符/绝对路径/软链 |
| S3 | 主进程 RCE | LLM 只产 HTML/JS，**永不写 Python**；Chromium 在子进程，主进程不 eval 任何模板 | 守卫断言 `render_host` 无 `eval/exec` |
| S4 | 资源耗尽（fork 炸弹/死循环） | 单帧截图超时 10s、总时限 6 分钟、HTML 单文件 ≤512KB/总数 ≤12、页面禁止 `window.open`；超限杀 worker 进程树 | 单测限额；集成测试超时路径 |
| S5 | 沙箱缺口被静默忽略 | 任一项安检**无法执行** ⇒ `success=False` 并报告；**绝不「先跑着」** | 守卫断言 no-fallback |

---

## 6. 分步任务单（每步独立可验收）

### T0 · V4.44 收尾缺口（本轮已补一项）
- **已补**：`_verify/check_code_video.py` 此前**没有挂进 `run_all_checks.py`**（新守卫不
  入册 = 看起来有守卫、实际没守卫，是本项目反复出现的病）⇒ 已登记为 `CODEVIDEO`（93→94 项）。
- **待确认**：`scripts/precommit_gates.sh` 是否要把 `check_code_video.py` 也挂进提交前卡点
  （它 0.4s 可跑，建议挂；但 precommit 已 14 道，需评估时长）。
- 验收：`run_all_checks.py` 输出含 `== CODEVIDEO ... exit=0`。

### T1 · 提交 V4.44 基线（前置）
- 精确 pathspec 提交：`app/core/code_video/`、`app/core/capability_handlers_code_video.py`、
  `app/core/agent_capability_catalog.py`、`app/core/agent_action_registry.py`、
  `app/core/capability_handlers.py`、`app/version.py`、`app/tests/test_code_video_spec.py`、
  `_verify/check_code_video.py`、`docs/CHANGELOG.md`、`docs/PROJECT_CONTEXT_PACK.md`、
  `docs/现行技术文档.md`、`README.md`。
- **不提交**：`vendor/_tmp_*`、`docs/_reports/*.html`、`启动画布诊断.bat`、本规划文档（T1 后单独提交）。
- 验收：`git diff --cached --name-only` 与上面清单逐项核对；门禁全绿。

### T2 · `security.py` + 单测（无渲染）✅ 2026-10-19 已落地
- 函数：`check_html(name, text) -> list[str]`、`resolve_html(compiled, root) -> (文本, errors)`、
  `resolve_assets(compiled, inbox_dir) -> (路径, errors)`、`check_limits(compiled) -> errors`；
  规则表 `FORBIDDEN_RULES`（19 条：外联/脚本外链/协议相对/fetch/XHR/WS/SSE/beacon/动态 import/
  eval/Function/window.open/跳转/parent 逃逸/base/meta refresh/storage）。
- 实测：**240 行**；`test_code_video_security.py` **47 例（46 通过 + 1 软链跳过）**；
  spec 公开 `HTML_NAME_RE` 供 security 复用（单一来源，不另写一套）。
- 顺手修正：`asset://` 基准 = `canvas_inbox_dir()` 根（`shot_N.mp4`，不是 `inbox/shot_N.mp4`）。

### T3 · 合成页生成器（纯函数）✅ 2026-10-19 已落地
- `page_builder.py`（**353 行**）：`build_timeline_page(compiled, html_contents, asset_paths)`；
  轨道叠层 z-index、cover/contain/blur-fill、iframe srcdoc、确定性时钟（performance.now/Date.now/
  rAF/CSS 动画冻结/Math.random 按 t 播种）、`__sgSeek(t)`、`__sgReady`、`__sgTextRects`。
- 实测：`test_code_video_page.py` **8 例**；真 Chromium 冒烟（540×960）：
  `__sgSeek(1.5)` → 文字层回传 `t=1.50`；`__sgSeek(0.5)` → `t=0.50`（确定性成立）。
- 🔴 **关键发现（写进设计约束）**：`file://` 页面里父页面直接读 `iframe.contentWindow`
  会抛 `SecurityError`（opaque origin）⇒ HTML 镜头时钟与文字 rect **必须走 postMessage**。
  T4 实现不得回退到直接访问 iframe DOM。

### T4 · `render_worker.py`（真 Chromium）✅ 2026-10-19 已落地
- CLI：`python -m app.core.code_video.render_worker --job job.json`；`--check` 只探测 Playwright/Chromium。
- job：`{page_path, out_dir, fps, width, height, start_frame, end_frame, sample_ts?, tmp_dir, progress_path}`。
- 实现（**245 行**）：`page.route` 运行时网络兜底（只放行 file/data/about/blob，拦截记入
  `blocked_requests`）、`__sgSeek(t)` 逐帧、PNG + sha256 manifest、progress.json、失败写
  `worker_error.json` 并非零退出；`--disable-gpu / font-render-hinting=none / force-color-profile=srgb`。
- 实测：10 帧 ×2 次逐帧 sha256 一致；540×960 单帧 ~30ms；PNG 尺寸正确。
- 注：`SHIGUANG_RENDER_INPROCESS=1` 仅供测试/受限环境；生产必须子进程（Playwright sync API 线程约束）。

### T5 · `render_host.py` + 音频 + 编码 ✅ 2026-10-19 已落地
- 编排（**421 行**）：compile → security → resolve → build page → worker → audio_graph →
  ffmpeg（libx264/aac）→ ffprobe 校验（时长 ≤1.5 帧 / 宽高 / 帧率）→ publish → QC。
- 失败带 `stage`（compile/security/resolve_assets/render/encode/publish/qc）+ `work_dir`；
  成功才清理工作目录。
- publish：给 `inbox_dir` 时落该目录（测试/自定义），否则复用 `video_gen.publish_to_inbox`。
- 实测（2s 540×960 + 正弦音轨）：输出 mp4 同时含 video+audio 流；时长 2.000s；QC ok
  （dual_shuffle pass / flat_frame warning / text not_wired / loudness not_wired）。

### T6 · `video_critic.py` + QC 接线 ✅ 2026-10-19 已落地
- 实现（**136 行**）：`choose_sample_ts`（5 个中点）、`compare_dual_shuffle`（按 t 比 sha256，
  报「哪个 t 画出两张不同的画」）、`text_safe_area_check`（读 manifest text_rects，默认 5% 边距，
  无 `data-sg-text` 即 not_wired）、`flat_frame_check`（PIL 灰度方差，warning 不判失败）、`build_report`。
- 实测：`test_code_video_critic.py` **12 例**；真渲染双乱序 5/5 一致。
- 响度 EBU R128 显式 `not_wired`（不假装测过）。

### T7 · 能力注册 + 守卫 + 文档 ✅ 2026-10-19 已落地
- 三处注册（catalog / handlers / action 表）：`pipeline.code_video_render`（file_write / 免费 /
  action=dangerous）；`capability_handlers.py` 1,999 行（未破 2000 守卫）。
- `check_code_video.py` 扩 B（渲染能力注册/级别）、E（七模块 + 薄壳行数棘轮）、F（顶层零
  Qt/playwright、失败带 stage、`worker_error.json`、无 eval/exec）；新增 `check_code_video_render.py`
  并登记 `CODEVIDEORENDER`（**95 项**）。
- 文档：`现行技术文档.md` §6.10 状态回正 + §6.5 能力数 122，CHANGELOG V4.45.0，version/README/上下文包同步。
- 验收：`check_capability_catalog` / `check_action_wiring` / `check_code_video` / `check_code_video_render` 全绿。

### T8 · 真机验收（交回用户）
- 用一份 3 镜头分镜生成 spec → 渲染 → 画布 inbox 播放。
- 验收清单：时长/fps/分辨率正确；字幕与标题卡清晰且未被裁切；音画同步；重复渲染两次结果一致
  （同机）；故意删一个素材 ⇒ 诚实失败且信息可定位；故意写外联 HTML ⇒ 安检拒绝。

---

## 7. 门禁与测试矩阵

| 层 | 内容 | 何时跑 |
|---|---|---|
| 单测 | `test_code_video_render.py`：安检/路径/限额/音频 graph/合成页结构/失败路径 | pre-commit（快） |
| 守卫 | `check_code_video.py` A-E 原样 + F（引擎零 Qt、规则表在册、no-fallback）+ G（行数棘轮） | run_all_checks |
| 守卫 | `check_code_video_render.py`：注册一致 + 真渲染冒烟（1s/12fps/360×640，缺 Chromium 显式 SKIP） | run_all_checks |
| 回归 | 原 23 例 + 新增 ≥20 例 | pre-commit |
| 全量 | `run_all_checks.py`（当前 **95** 项：CODEVIDEO + CODEVIDEORENDER 均已入册）+ `pytest app/tests -q`（736+） | 提交前 |
| 冻结 | `frozen_zone_guard.py` 必须 **107 locks intact**（本刀零冻结区改动） | 提交前 |

**禁用的「省事」做法**：不 `--update` 冻结基线；不抬 `check_file_size` 基线；不为新能力建空壳注册；
不把 Chromium 缺失写成「降级为纯素材拼接」；不在 `render_host` 顶层 import PyQt6。

---

## 8. 风险与回退

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Chromium 逐帧截图比预期慢（>6 分钟） | 中 | 体验差 | T4 先做基准；超预算时先调并发/降采样 QC，**不降画质**；快速路径另立 V4.45.5 |
| 字体/GPU 差异导致跨机帧哈希不同 | 高 | 质检误报 | 确定性定义限定「同机同运行」；固定 `--disable-gpu`、`--force-device-scale-factor=1`；跨机只比结构指标 |
| `iframe srcdoc` 内脚本拿不到宿主时钟 | 中 | HTML 动画不确定 | ✅ 已解决（T3）：确定性时钟随 srcdoc 注入；父页面经 `postMessage` 驱动（`file://` 直接读 contentWindow 会 SecurityError，实测）；worker 在 iframe load 后 `__sgSeek` |
| 视频 seek 精度不足（GOP 长） | 中 | 帧错位 | `currentTime+0.001` 补丁；必要时 V4.45.5 做「近无损关键帧副本缓存」（OpenFilm `seekable` 思路） |
| 音频 `atempo` 与视频变速不同步 | 低 | 音画漂移 | 音频窗口按 `range 长` 而非源时长；抽帧校验总时长 |
| 海量临时 PNG 占磁盘 | 中 | 磁盘满 | 单作业临时目录、编码后立即清理；失败保留路径但上限 2 个作业 |
| V4.44 未提交就叠 V4.45 | 高 | 回滚困难 | **T1 强制前置**；V4.45 独立提交，信息带 `V4.45.0` |

**回退**：V4.45 只新增文件 + 3 处注册 + 文档；回退 = `git revert` 单提交，不触及冻结区/真相源。

---

## 9. 与 V4.46 的边界（防 scope 蔓延）

V4.45 **不做**：
- 画布 `codeVideo` 节点、`hostCodeVideo.ts` 桥、`CodeVideoInspector` 面板；
- `/host/code-video/render|status|cancel` 端点与 SSE 进度（V4.46）；
- 用户授权解冻 `canvas-magnetic-intent`（V4.46 前置）；
- LLM 生成 HTML（`llm_html.py`，V4.46）；
- 快速路径（V4.45.5，需基准数据 + 等价测试）；
- 响度 QC、跨机确定性、ProRes/Alpha 导出。

V4.46 接手时只需：把 `render_host.render()` 挂到端点、把 `progress.json` 转 SSE、把结果 URL 写节点 data。

---

## 10. 验收定义（Definition of Done）

1. `code_video_render` 能力可被 dispatcher 调用，成功返回 inbox URL，失败返回可定位的 `stage+error`。
2. 6s 样例（含标题卡 + 2 个素材镜头 + 字幕轨）渲染成功，ffprobe 验证 1080×1920/30fps/时长误差 ≤1 帧。
3. 同机重复渲染两次，采样帧 sha256 一致；双乱序 QC 通过。
4. 反例全部被拦：外联 HTML、路径穿越、缺素材、超时长、超 clip 数、非法 fps。
5. 全量门禁绿（95 项）+ pytest 全绿 + 冻结区 107 锁完整。
6. 文档回正：`现行技术文档.md` §6.10、CHANGELOG V4.45.0、本规划状态改「已落地」。
7. 用户真机验收清单（T8）逐项打勾。

---

## 附：落地顺序建议（依赖图）

```
T1 提交 V4.44
 └─► T2 security ─► T3 合成页 ─► T4 worker ─► T5 host/编码 ─► T6 QC
                                                        └─► T7 注册/守卫/文档
                                                                 └─► T8 真机验收
```

T2/T3 可并行（都无 Chromium 依赖）；T4 是关键路径，先做 **2s 静态样例** 打通再扩到视频 seek。
