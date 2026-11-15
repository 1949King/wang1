# 本地模型 / 权重 / 内核等价性（深水区）

> 入口摘要见 `memory/MEMORY.md` 第三节。这里放正文，别把细节抄回主档。

## 一、两个 `verified` 不是一回事（2026-11-15 查证，别再混）

1. `app/core/neural/model_family.py:185` 的 `verification=VERIFIED` 是**手工写死**的
   「这个族在某台机器上真机跑通过」（10-24 M5 背书）。`_probe_local_video` 只回答
   **权重在不在盘**，**不参与** verification 判定。我曾把它当成 verification 的来源，
   凭空编出一个"不诚实"的问题 —— 下判断前先分清「手工写死」还是「动态推导」。
2. `docs/knowledge/kernel_evidence.json` 记的是**内核 vs stock 的等价性四门**
   （张量 / 画质 / 速度 / 显存），与上一条无关。

wan 有 kernel adapter（`app/core/neural/kernel/adapters/wan.py`），2026-10-30
`_verify/bench_wan_kernel_parity.py` 跑过，落 `data/wan_kernel_parity.json`：

- `kernel_ok=true`，但 **PSNR 未产出**（`kernel_frames` 缺失 ⇒ 画质门没完成）；
- 总耗时 **265.2s vs 上游 50.3s = 5.27×**，但口径不齐：kernel 的
  `encode_ms=207,671ms` 是内部重做 UMT5 编码，上游吃的是**预编码 embeds**；
  同口径比去噪 `loop_ms=52,583ms` vs 50.3s ≈ **1.05×**。
- ⇒ 缺画质数据 + 速度门按总耗时不过 ⇒ **不能登记 `verified`**。

⚠️ `capability_manifest.py:66` 注释「wan 仍只有一腿（无 adapter）」**已过时**。

## 二、权重探测修复（2026-11-15，`abef0745`，别退回）

`is_downloaded` 在 `diffsynth_image` / `diffusers_image` / `video_gen` 里
**都是 Engine 静态方法**（`DiffsynthImageEngine` / `DiffusersImageEngine` / `VideoGenEngine`），
**没有模块级同名函数**。写 `from ... import is_downloaded` 会 ImportError 被 `except` 吞掉
⇒ 恒 False。

`_probe_local_video` **禁止**再用 `_guess_model_kind(族名)`：族名必然命中自己的关键词
⇒ 恒 True。

实测该 bug 让 sd15/sdxl/svd 被判「权重不在盘」、cogvideox/ltx/mochi 被谎报「在盘」，
9 个族的判定几乎全反。修好后 9 族与磁盘一一对上（4 True / 5 False）。

防回归：`app/tests/test_model_family.py::test_probes_have_no_legacy_wrong_patterns`
**用 AST 断言（`ast.ImportFrom` 的 names / `ast.Name`），别用字符串匹配** ——
第一版用 `assert "import is_downloaded" not in src`，被自己注释里那句
「不要再写 import is_downloaded」绊倒。

## 三、检查器 `scripts/check_models.py`（2026-11-15，`c4e59ee` + 扩展）

**只做展示，不做判定**：判定全部来自 `model_family.status()` / `resolve()`，
避免又多一个漂移源。它只答「配置层能不能用」，不担保真能生成出东西。

行为：默认**只显示权重在盘的族**；`--all` 全量；`--missing` 只列缺的；
`--pull <id|all>` 走引擎的 `pull()`。

三种「没有」必须分清，说人话时别混：

| 类型 | 判定 | 出口 |
|---|---|---|
| 有下载源，没下 | catalog 里有 repo | `--pull` |
| 有源但硬件不够 | 内存/显存 < 需求 | 下了也跑不动，别下 |
| 连下载源都没登记 | 无 repo | 只能手动放 / 待适配 |

`_catalog()` 从 `VIDEO_MODELS` / `IMAGE_MODELS` 取 repo、体积、显存、内存；
`_hw()` 用 psutil 探内存 + shutil 探磁盘。本机实测：内存 15.3GB（可用 7.2GB）、
磁盘余 414.1GB ⇒ Wan2.2 TI2V-5B 需 20GB 内存，属第 2 类。

**5 个族（cogvideox / hunyuan / ltx / mochi / minimax_h3）只有 `_infer_*` 推理代码，
`VIDEO_MODELS` 里没有 repo** ⇒ 既拉不了也还没适配完。

## 四、Ollama 的边界

Ollama **只服务文本模型，拉不了扩散模型**。`ollama` pip 包没装但服务在跑
（`127.0.0.1:11434`，已装 `qwen3.5:4b`、`qwen3.5-ue:latest`）。
用户说「通过 Ollama 拉」时，扩散模型这条路走不通，只有魔搭 / HuggingFace / GitHub 三条。

## 五、Wan 2.1 真机实测（2026-11-15）

本机只有 **T2V-1.3B** 权重（`models/cache/Wan-AI_Wan2.1-T2V-1.3B-Diffusers`），
传 `reference_image` 会 fail-fast 拒绝（I2V 缺 encoder）。
硬约束：帧数 **4k+1**、宽高被 **16** 整除。
5 秒 = 81 帧 / 480×832 / 20 步 = **927 秒**，显存 6.6 / 8.2GB。

## 六、五族下载源登记（2026-11-15，`app/core/neural/local_family_catalog.py`）

上一轮只做到「说清楚拉不了」，这一轮把 **repo 和体积真登记上**了。

**ModelScope 只有两个端点可用**（搜索 API 全 404：`/api/v1/dolphin/models`、
`/api/v1/models/search` 都不通）：
- 存在性 `GET /api/v1/models/<owner>/<name>` → 200
- 体积 `GET .../repo/files?Revision=master&Recursive=True` → **无 FileSize 汇总，自己求和**

HuggingFace 全线超时，只有 ModelScope 通。

| id | repo | 整仓 | 下载子集 | diffusers 布局 |
|---|---|---|---|---|
| cogvideox-2b | ZhipuAI/CogVideoX-2b | 12.8GB | 12.8GB | ✓ |
| cogvideox-5b | ZhipuAI/CogVideoX-5b | 20.1GB | 20.1GB | ✓ |
| ltx-video-13b | Lightricks/LTX-Video | 236.7GB | **26.5GB** | ✓ |
| ltx-video-095 | Lightricks/LTX-Video-0.9.5 | 23.9GB | 23.6GB | ✓ |
| mochi-1-preview | genmo/mochi-1-preview | 124.3GB | **85.2GB** | ✓ |
| hunyuan-video | Tencent-Hunyuan/HunyuanVideo | 37.1GB | — | **✗ 原版 .pt** |
| minimax-h3 | 4 个候选 repo 全 404 | — | — | 无开放权重 |

三条硬结论：① **整仓体积 ≠ 下载量**（LTX 236.7GB 里 210GB 是 13B 单文件 + media/；
Mochi 有重复 bf16 分片）⇒ `download()` 必须带 `DIFFUSERS_PATTERNS`；
② hunyuan 缺 `model_index.json`，`HunyuanVideoPipeline.from_pretrained()` 直接失败 ⇒ `pull=False`；
③ minimax_h3 官方只有 API，`PIPELINE_CLASS_MAP` 里那项是给「已自行拿到权重的人」用的。

**落盘对齐最容易哑火**：`repo_local_dir()` 把 `owner/name` 换成 `owner_name`，
`_scan_local_models()` 靠目录名匹配关键词 ⇒ `ZhipuAI_CogVideoX-2b` 含 `cogvideox` ✓。
测试 `test_download_dir_name_matches_keyword` 钉死这条。

**`--all` 的「可拉取」列别写成 `bool(cand)`**（该族在 catalog 里有没有条目）——
那样 hunyuan / minimax_h3 也显示「是」，是假的可操作承诺。
判据必须是「有 repo 且无 `no_pull_reason`」。

**`ram_gb` 是估算**：`权重体积 × 1.3` 取整，`public_list()` 带 `ram_gb_estimated=True`。
本机现实：五族全落「磁盘够、内存不够」（17 / 31~35 / 111 GB vs 15.3GB）
⇒ 收益是「从拉不了变成能拉但跑不动」，**没有多出可用模型**。
