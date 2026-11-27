# DeepSeek 推理设计理念移植至自研 diffusers 栈 · 设计方案

> 日期：2026-10-24 ｜ 状态：待评审 ｜ 关联：V4.44 契约刀收尾后启动  
> 输入：用户提出将 DeepSeek 三项推理设计（MLA / PagedAttention / MoE 专家卸载缓存）移植进项目自营引擎，并适配其他模型与视频生成类模型，参考其他推理引擎理念。  
> 本机基线：RTX 4060 Laptop **8GB** · sm89 (Ada) · CUDA 12.4 (torch 2.6.0+cu124) · 系统内存 15.3GB（可用约 5GB）· diffusers 0.40.0 · **torchao 实测未安装**（2026-10-25 复验：`pip list` 与 `find` 双证不存在；早前目录疑被并行会话/清理移除——矩阵中「已装未用」不成立，M4 第一锹 = 装回 + pin + 探针） · 无 triton / 无 xformers

> **2026-10-27 基线更新（实测回填）**：torchao 已装回项目 venv —— **0.16.0**，torch 未动（仍 2.6.0+cu124）。
> 版本墙实测：torchao **0.17.0 起要求 `torch >= 2.11`**（`torch.utils._pytree.register_constant` 缺失 ⇒ 直接 AttributeError），
> 而 Windows 上 torch ≥2.11 只有 cu130 轮子（cu126/cu128 的 cp312/313 轮子止于 2.9.1）⇒ **想用 0.17+ 必须连 torch 一起升**。
> 0.9.0~0.16.0 逐版本实测均可在 torch 2.6 上导入，**0.16.0 是上限**。⇒ M4-0 状态改为「已完成」。

---

## 1. 结论摘要（先看这一页）

### 1.1 三项技术的移植判定

| 技术                 | 官方省的「池子」     | 官方量级                                                                 | 项目有没有这个池                                                                                                                           | 判定                                                                     |
| ------------------ | ------------ | -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| **MLA**（低秩 KV 压缩）  | 自回归 KV Cache | 8192→576 标量/层/token（-92.97% vs 32 头 MHA）；128K×batch8 场景 960GB→67.5GB | **没有**。扩散模型每步全前向、无自回归 KV 增长；项目唯一 AR 模型（YuE 音乐）走云端档                                                                                 | **不直接移植**；但其「低秩+吸收+解耦」三件套有完整移植方案（§10：低秩特征缓存骑在 DeepCache 上；条件流低秩留给视频模型） |
| **PagedAttention** | 显存碎片浪费       | 浪费率 60.6%→<6%，挽回 40–60% 无效占用，支撑 2–8× 并发                              | **有，且已流血**：SD1.5 卸载→SDXL 重载碎片换页卡死 **>22min**（`diffusers_image.py:551-555`）；SVD 8 帧 chunk=2 触发 WDDM 分页 **377s**（`video_gen.py` 实测注） | **高价值移植**（对应物：显存块池 / 编码器输出缓存 / 抽卡连续批）                                  |
| **MoE 专家卸载**       | 权重峰值显存       | ExpertFlow -93.72%；Qwen3-30B-A3B 峰值 7.16GB                           | **条件性有**：Wan2.2-TI2V-5B 本身就是双专家 MoE（公开架构信息，项目未实测）；组件级等价物（文本编码器/VAE 分时卸载）现在就有                                                       | **条件移植**（对应物：组件冷热调度 / Wan2.2 专家按段卸载 / LoRA 热缓存）                        |

### 1.2 为什么不能照搬名字（关键论证）

LLM 的显存危机来自 **KV Cache 随 token 数线性增长**；扩散模型没有这个增长源——它每一步都对**整个潜空间**做一次全前向。扩散世界的「MLA」就是 **VAE 潜空间本身**（8× 空间压缩 + 通道压缩），所以扩散模型的显存大头是另外三个池子：

| 扩散模型的真实池子                | 项目实测证据                                                            | 对应技术                                     |
| ------------------------ | ----------------------------------------------------------------- | ---------------------------------------- |
| ① 权重（fp16）               | SDXL 6.46GB 恰好占满 8GB 卡（加载后空闲 0.00GB，`diffusers_image.py:170-171`） | 量化（FP8/INT8/INT4/NF4，torchao 需重装）/ 组件卸载 / MoE 专家卸载 |
| ② 激活（注意力矩阵随 token 数平方增长） | SVD 每帧 ≈0.4GB；视频 DiT 万级 token 场景是主要瓶颈                             | SageAttention（INT8/FP8 注意力）/ 序列并行        |
| ③ 碎片与换页                  | >22min 卡死惨案；377s WDDM                                             | 显存块池 / 编码器缓存（省重复驻留）/ 批量调度                |

**三项技术要对着这三个池子打，而不是把 LLM 的名字搬过来。**

### 1.3 落地清单（按 ROI 排序，收益均以项目实测基线折算）

| #    | 项目                                   | 家族                | 期望收益（基于本机实测基线）                                                                                                     | 成本                                 | 优先级    |
| ---- | ------------------------------------ | ----------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------- | ------ |
| P0-1 | **DeepCache 步间特征缓存**（含 3b 低秩缓存层，§10） | MLA 家族            | SDXL final 24.99s → **~14.8s（-41%）**；SVD 35.68s → ~21s（官方 1.7×）；SD1.5 基数小收益有限；低秩层再省缓存显存 ×4（rank 25%）并解锁更大 interval | 中（新模块 ~200 行 + 三 arch 适配 + SVD 校准） | **P0** |
| P0-2 | **编码器输出缓存**（prefix cache 对应物）        | PagedAttention 家族 | 抽卡会话省重复文本编码；**Wan 场景 RAM 墙 13.7GB → ~4GB**（T5 编码后即可卸），是把「本机不可行」变「可行」的关键                                            | 小（~80 行）                           | **P0** |
| P0-3 | **显存块池 + 卸载序列化**                     | PagedAttention 家族 | 消除 22min 碎片死亡 / 377s WDDM（保命，非提速）                                                                                  | 小（~100 行）                          | **P0** |
| P1-1 | **组件冷热调度**（expert offload 对应物）       | MoE 家族            | SDXL 去噪期峰值 **-1.2GB**（双 CLIP 卸 CPU）；Wan 场景 -10.6GB（T5）                                                             | 中                                  | P1     |
| P1-2 | **SageAttention 接入**                 | MLA 家族            | 视频 DiT 激活内存约减半；官方内核级 2.1–3.1× vs FA2（端到端须实测）；**当前 U-Net 场景收益有限**（激活不是瓶颈）                                           | 中（需编译装包，Windows 有风险）               | P1     |
| P1-3 | **抽卡连续批调度**                          | PagedAttention 家族 | best_of_n 从逐张串行 → 编码一次 + N 路去噪 + 逐张 VAE 解码；8GB 上 N≤2、大卡放开                                                          | 中                                  | P1     |
| P2-1 | **Wan2.2 MoE 双专家按段卸载**               | MoE 家族            | 单专家 ~2.5GB 驻留，8GB 卡有戏（条件：P0-2 落地 + 权重落地）                                                                           | 大                                  | P2     |
| P2-2 | **序列并行 USP/xDiT**                    | MLA 家族            | 长视频（>10s）万级 token 的平方级激活内存；多卡场景                                                                                    | 大                                  | P2     |
| P2-3 | **LoRA 热缓存 / 本地 AR KV 量化**           | MoE / MLA 家族      | LoRA LRU 常驻；YuE 本地化（24GB 档）时 KV 量化 -90% 量级                                                                         | 小/大                                | P2     |

### 1.4 三个决策点（需用户拍板）

- **A. 范围**：只做 P0 三项（DeepCache + 编码器缓存 + 块池），还是 P0+P1 全做？
- **B. DeepCache 实现路线**：原生 hook 实现（推荐：零新依赖、可测试、可门禁、可遥测）vs 官方 `DeepCache` 包（`pip install`，作交叉验证基准）？
- **C. 默认策略**：缓存默认**关闭、显式开启**（推荐：质量风险前置）vs 抽卡档（fast/high）默认开启？

---

## 2. 逐项设计

### 2.1 P0-1 DeepCache 步间特征缓存（MLA 家族的扩散对应物）

**官方口径**（已核实，diffusers v0.40.0 官方文档页即项目所装版本）：

- 「accelerates StableDiffusionPipeline and StableDiffusionXLPipeline by strategically caching and reusing high-level features while efficiently updating low-level features **by taking advantage of the U-Net architecture**」
- 机制：U-Net 相邻去噪步的深层特征变化极小（时序冗余）⇒ 每 `cache_interval` 步完整计算并缓存深层（up-blocks）特征，中间 N-1 步只跑 down-blocks + mid-block + 取缓存，**跳过大部分层**
- 官方倍率：SD1.5 **2.3×**（CLIP 仅 -0.05）、SDXL **2.6×**、SVD-XT **1.7×**；官方 benchmark（A5000/SD2.1/50 步）：I=3,B=0 → 2.32×；I=5,B=0 → 3.02–3.24×
- 官方支持列表 = SD1.5 / v2.1 / XL / SVD / inpaint / img2img / DDPM——**与项目现役模型全重叠**
- 参数语义：`cache_interval`（缓存更新间隔，越大越快越糊）、`cache_branch_id`（缓存分支深浅，越浅越快越糊）

**与 MLA 的思想同构性**：MLA 压缩「最大的那个内存/计算对象」并复用；DeepCache 复用「相邻步冗余度最高的那块计算」。两者都是 training-free 的缓存跳步，只是一个缓存在序列 token 间、一个缓存在去噪步间。（TeaCache 是同一思想的 DiT 版，官方不支持 U-Net，已排除；diffusers 0.40 内置的 FirstBlockCache 同理只支持 transformer 系，留给未来 DiT 模型。）

**项目插入点**：

- `app/core/neural/diffusers_image.py:472-525`（load 内 offload 挂载区之后）——建 `StepFeatureCache` 并按 arch 白名单挂 hook
- `diffusers_image.py:580`（`generate`）——按质量档位决定是否激活
- `app/core/neural/video_gen.py`——SVD 同构接入（3D UNet，需单独适配时序结构）

**收益折算**（本机基线）：

- SDXL final 24.99s 中 ~7s 是 offload 固定开销（占 28%，`diffusers_image.py:170-172`）压不掉；可压部分 ~18s，按官方 2.3× ⇒ **~14.8s（-41%）**
- SVD 常驻 35.68s ⇒ 官方 1.7× ⇒ **~21s（省 14.7s/条视频）**
- SD1.5 3.10s 基数太小，绝对值收益 ~1s，但抽卡批量场景累积可观

**风险与对策**：

- 抽卡场景（draw_book/score_book）对细节敏感；LCM 8 步「目视偏软」是前车之鉴（`diffusers_image.py:165`）⇒ **fast/high 档可用，final 档保持纯净**；默认关、显式开（决策点 C）
- 官方倍率是 A5000/无 offload 口径，**不得写入项目结论**，必须本机重测（遥测 n≥3 才采纳）

### 2.2 P0-2 编码器输出缓存（PagedAttention 的 prefix cache 对应物）

**思想对应**：vLLM 的 prefix caching = 相同 prompt 前缀的 KV 只算一次；扩散世界的对应物 = **相同 (模型, prompt, negative, LoRA 集) 的文本编码输出只算一次**。

**项目痛点**（为什么这是 P0 而不是优化）：

- 抽卡循环（`draw_orchestrator.py` best_of_n）对同一 prompt 反复生成 N 张，每次重跑文本编码
- **Wan 系的真正死因不是显存是内存**：umt5-xxl T5 单独 10.58GB，cpu_offload 需 ≈13.7GB 权重驻留 RAM > 本机 15.3GB 扣 OS（`video_gen.py:20-30`、`diffsynth_image.py:11-17`）⇒ T5 编码完即可卸到磁盘/CPU，只保留编码结果（~MB 级）⇒ **RAM 墙从 13.7GB 打到 ~4GB**，Wan2.1-T2V-1.3B 从「本机不可行」变「可验证」

**设计**：

- 键：`sha256(arch | model_id | prompt | negative_prompt | lora_set | max_length)`；值：`prompt_embeds` + `pooled_prompt_embeds`（SDXL）
- 驻留策略：VRAM 感知——空闲显存 > 阈值驻 GPU，否则驻 CPU（`torch.Tensor.to("cpu")`），淘汰 LRU
- 生命周期：随引擎单例，`unload()` 时清空；容量上限（条数 + 字节）双闸
- 与现有缓存体系的关系：`model_registry.py` 已有 LRU 骨架（`:70-75`），编码器缓存是**张量级**缓存，不复用其模型级 LRU，但遵守同一纪律

**插入点**：`diffusers_image.py` 的 `_encode_prompt` 路径（generate 内）+ `video_gen.py` 同构 + 未来的 DiT pipeline。

### 2.3 P0-3 显存块池 + 卸载序列化（PagedAttention 的 paged allocation 对应物）

**思想对应**：vLLM 用固定大小 block 池管理 KV，杜绝可变尺寸 malloc/free 造成的碎片；扩散世界的对应物 = **固定块 latent/激活池 + 严格的卸载序列**。

**项目已流血两处**（设计依据）：

1. SD1.5 整卡常驻 → unload → 同进程再 load SDXL ⇒ 显存碎片换页卡死 **>22min**；现有解法是「先 gc 掉引用、再 synchronize、最后 empty_cache」（`diffusers_image.py:551-567`）——纪律已有，但**没有池**
2. SVD 8 帧 chunk=2 ⇒ 显存随帧数增长触发 WDDM 分页 ⇒ 377s（47s/帧）；chunk=1 修复（`video_gen.py` 注①）

**设计**：

- `VramBlockPool`：预分配固定大小 latent block（如 1GB/块，按引擎实测峰值定），申请/归还走池，杜绝逐张可变尺寸分配
- 卸载序列化助手 `release_vram_sequence()`：把现有 gc→synchronize→empty_cache 三歩收口成一个可复用函数（现在散落在 `unload()` 和 `release_under_pressure` 两处）
- 与 `local_video_pipe_cache.release_under_pressure`（`:448` 调用点）打通：让位请求也走同一序列

**验收判据**：SDXL load/unload 循环 5 次，每次 < 60s（现状：第二次起可能 22min 级卡死）——这是**保命项**，不是提速项。

### 2.4 P1-1 组件冷热调度（MoE expert offload 的组件级对应物）

**思想对应**：ExpertFlow 按「热/冷」决定专家驻 GPU 还是 CPU；扩散管线的组件天然有冷热时序：

- **text encoder**：只在第 0 步（编码 prompt）用 ⇒ 去噪期是「冷专家」
- **VAE decoder**：只在结尾用 ⇒ 去噪期是「冷专家」
- **UNet/DiT**：每一步都用 ⇒ 唯一「热专家」

**设计**：去噪开始前把 text encoder / VAE 卸到 CPU（accelerate hook 或 DiffSynth layer offload 已有能力），VAE 解码前再搬回。收益：SDXL 去噪期峰值 **-1.2GB**（双 CLIP 0.82GB + VAE 0.08GB + 激活余量）；Wan 场景 **-10.6GB**（T5）。

**与现有四档策略的关系**：`memory_policy.py` 四档（whole_gpu / model / sequential / layer_cpu）管的是 UNet 权重；组件调度是**正交的第三维**，挂在 load 后的管线级，不改四档判据。

### 2.5 P1-2 SageAttention 接入（MLA 原则的激活池移植）

**官方口径**（已核实）：

- thu-ml/SageAttention（ICLR 2025 / ICML 2025 / NeurIPS 2025 Spotlight，Apache-2.0 可商用）
- INT8 QK^T + FP8 PV 量化注意力；**内核级 2.1–3.1× vs FlashAttention2**、2.7–5.1× vs xformers；端到端「不掉指标」
- 内核覆盖 Ampere / **Ada (sm89 ✓ 本机)** / Hopper；Ada 的 FP8 需 CUDA 12.4（本机 cu124 ✓）
- 官方建议：「For image and video models, we suggest **only replacing the attention in DiT**」——U-Net（SD/SDXL）需走 AttnProcessor 替换路径，且**当前 8GB U-Net 场景激活不是瓶颈**（权重+搬运才是）⇒ 收益主要在未来的视频 DiT（Wan/HunyuanVideo 万级 token）

**成本与风险**：需源码编译（CUDA 扩展），Windows 上 nvcc 工具链是风险；建议先做**探针**（`find_spec` + 能力位登记 + 最小 benchmark），不进生产路径。

### 2.6 P1-3 抽卡连续批调度（PagedAttention 的 continuous batching 对应物）

**现状**：best_of_n 逐张串行；批量 N=4 实测仅省 2.8%（8GB 上 1024² 批量直接换页卡死，`diffusers_image.py:914-919`），且首次新 batch size 有 kernel autotune（N=4 首轮 21.19s）。

**设计**：三级流水——① 文本编码一次跑 N 个 prompt（与 P0-2 缓存共用编码器输出）；② 去噪 N 路并行（8GB 上 N≤2，由 `promotion_fits` 式判据动态定）；③ VAE 逐张解码（守住 chunk=1 纪律）。大卡上放开 N。

### 2.7 P2 条件项（触发条件写明，不提前做）

- **P2-1 Wan2.2 MoE 双专家按段卸载**：Wan2.2-TI2V-5B 的 high-noise / low-noise 专家按去噪阶段分工（公开架构信息，项目未实测）⇒ 天然确定性专家交换（比 ExpertFlow 的预测调度更稳），单专家 ~2.5GB 驻留。触发：P0-2 落地 + ModelScope 权重落地。
- **P2-2 序列并行 USP/xDiT**：长视频万级 token 的平方级激活内存，切序列到多卡。触发：多卡硬件。
- **P2-3 LoRA 热缓存 + 本地 AR KV 量化**：LoRA LRU 常驻（model_registry LRU 骨架扩展）；YuE 本地化（24GB 档）时 KV 量化（MHA2MLA 公开验证：Llama2-7B KV -92.19%、LongBench -0.5~1%，可作路线图参考）。触发：YuE 本地化排期。

---

## 3. 模块架构设计

### 3.1 新文件（遵守「新逻辑另开文件」铁律，不抬主文件基线）

```
app/core/neural/inference_cache.py   # 新模块，预算 ~450 行
├── StepFeatureCache      # DeepCache 移植：U-Net hook 式步间特征缓存
│   ├── attach(pipe, arch, interval, branch_id) -> CacheReport
│   ├── detach()
│   └── stats() -> {full_steps, skipped_steps, hit_rate}
├── LowRankFeatureCache   # MLA 三件套移植（§10）：缓存特征低秩 + 折入 conv_out
│   ├── calibrate(samples) -> U_r           # svd_lowrank，MHA2MLA 同款恢复
│   ├── fold_into(conv_out) -> 新权重       # 吸收：W̃[r,Δ]=Σ_c W[c,Δ]·U[c,r]
│   └── compress(h) -> M / decompress 不需要（已折叠）
├── EncoderOutputCache    # prefix cache 对应物：文本编码输出 LRU
│   ├── get(key) / put(key, tensors, device)
│   └── clear() / stats()
├── VramBlockPool         # paged allocation 对应物：固定块 latent 池
│   ├── acquire(n_bytes) / release(block)
│   └── release_vram_sequence()   # gc→synchronize→empty_cache 收口
└── cache_gate(...)       # 统一门控：device_profile 能力位 × 质量档位 × 环境开关 × 遥测
```

**为什么原生实现而非官方 `DeepCache` 包**（决策点 B 推荐理由）：① 零新依赖（项目依赖纪律）；② 可单测（hook 行为可用假 UNet 验证，不烧 GPU）；③ 可过门禁（AST/行为断言）；④ 可遥测（命中率/跳过步数进 engine_telemetry）。官方包装作交叉验证基准，仅在校准期引入。

### 3.2 插入点总表（均为非冻结区，已核实 `docs/knowledge/frozen_zones.json` 9 zone 无一覆盖 neural 栈）

| 文件                                   | 行号                   | 改动                                 | 规模    |
| ------------------------------------ | -------------------- | ---------------------------------- | ----- |
| `app/core/neural/diffusers_image.py` | 472-525（offload 挂载后） | `StepFeatureCache.attach()` + 门控查询 | <25 行 |
| `app/core/neural/diffusers_image.py` | 580+（generate）       | 缓存查询/激活/遥测                         | <20 行 |
| `app/core/neural/video_gen.py`       | generate 同构点         | SVD 适配 + 门控                        | <25 行 |
| `app/core/neural/device_profile.py`  | 47-66（能力位）           | 加 `sageattn` 探测（P1-2 探针用）          | <5 行  |
| `app/core/ai/draw_orchestrator.py`   | best_of_n 循环         | 连续批调度入口（P1-3）                      | <20 行 |

### 3.3 数据流（文字版）

```
generate(prompt, preset)
  ├─ cache_gate(arch, preset, env) ──否──▶ 原路径（零行为变化）
  ├─ EncoderOutputCache.get(hash) ──命中──▶ 跳过文本编码（P0-2）
  ├─ pipe(prompt_embeds=...)          ──▶ StepFeatureCache 按 interval 跳步（P0-1）
  │     └─ 每步遥测：full/skipped + 墙钟
  ├─ VAE decode（chunk=1 纪律不变）
  └─ telemetry.record(cache_hit, saved_ms) ──▶ n≥3 才进采纳报告
```


## 5. 验证计划（真机协议）

**沙箱即真机**：RTX 4060 Laptop 8GB · sm89 · CUDA available（已实测 `torch.cuda.is_available()=True`）⇒ 全部标定可在本机跑，无需用户代跑。

### 5.1 标定协议（每项）

| 项                    | 协议                                        | 判据                                                  |
| -------------------- | ----------------------------------------- | --------------------------------------------------- |
| DeepCache SD1.5      | 20 步 × {基线, I=3/B=0, I=5/B=0} × 3  prompt | 墙钟、峰值显存、CLIP 对齐（沿用 fast/high 档既有测法）、PSNR vs 基线、目视抽检 |
| DeepCache SDXL       | 20 步同三组                                   | 同上；预期 -41% 须复现（官方 2.3× 是 A5000 无 offload 口径，只作预期）   |
| DeepCache SVD        | 14 步 × {基线, I=3/B=0} × 5 帧                | 墙钟、峰值、首帧 PSNR、运动保留率（沿用 video_gen.py 既有运动/PSNR 方法论）  |
| 编码器缓存                | 同 prompt × 8 次生成                          | 命中率 100%（第 2 次起）、编码阶段耗时 →0                          |
| 块池                   | SDXL load/unload × 5 循环                   | 每次 <60s（治 22min 碎片死亡）                               |
| SageAttention 探针（P1） | 装包 + SVD 5 帧 × {SDPA, sageattn}           | 内核可达性 + 端到端墙钟/PSNR；不可达则诚实记录「Windows 编译失败」           |

### 5.2 门禁清单（交付前全绿）

- `pytest app/tests/test_inference_cache.py`（新增：hook 行为用假 UNet、缓存键稳定性、LRU 淘汰、块池 acquire/release、门控矩阵反例）
- `_verify/check_inference_cache.py`（新增：三处注册一致性 / 档位矩阵 AST 断言 / 行数棘轮 / 反例验证——守卫本身不能是永远绿的摆设）
- `run_all_checks.py`（108 项存量）+ `scripts/stability_gate.py` + `frozen_zone_guard.py`（neural 栈不在冻结区，应零变化）
- ruff（`C:/Python314/python.exe -m ruff` 存量棘轮口径）

### 5.3 文档同步

CHANGELOG（V4.45 节）+ `app/version.py`（4.44.0 → 4.45.0）+ README/PROJECT_CONTEXT_PACK 版本三角 + 本报告归档 `docs/_reports/`。

---

## 6. 与其他推理引擎的理念对照

| 引擎                             | 理念                                                                          | 本项目对应物 / 现状                                                 |
| ------------------------------ | --------------------------------------------------------------------------- | ----------------------------------------------------------- |
| vLLM                           | PagedAttention（块池）                                                          | P0-3 VramBlockPool                                          |
| vLLM                           | Continuous batching                                                         | P1-3 抽卡连续批                                                  |
| vLLM                           | Prefix caching                                                              | P0-2 EncoderOutputCache                                     |
| vLLM/SGLang                    | 量化推理（FP8/Marlin）                                                            | **M4（升级 P0）：torchao 需重装 + pin**；diffusers 0.40 无 `TorchAoConfig` ⇒ 走原生 `quantize_()`；device_profile fp8 位已认 sm89       |
| SGLang                         | RadixAttention（前缀树共享）                                                       | P0-2 的进阶形态（多 prompt 共享前缀，二期）                                |
| SGLang                         | TeaCache 集成                                                                 | ❌ U-Net 不兼容（官方口径）；DiT 模型未来可直接用 diffusers 内置 FirstBlockCache |
| TensorRT-LLM                   | In-flight batching / FP8                                                    | 同 continuous batching 对应物                                   |
| **DiffSynth（项目主选）**            | Block 级 VRAM 管理 / FP8-INT8-NF4 / layer offload                              | 主选通道已有；本设计只进自研备选通道                                          |
| ComfyUI                        | WanVideoVRAMManagement（封装 diffsynth）/ TeaCache 节点 / SageAttention 节点 / GGUF | 生态宽度参照；项目刻意不引第二套真源（`video_gen.py:14-22`）                    |
| xDiT / ParaAttention           | USP 序列并行（长视频）                                                               | P2-2                                                        |
| DeepCache / TeaCache / FBCache | 步间特征缓存三兄弟                                                                   | **P0-1 落地 DeepCache**（唯一官方支持 U-Net 的）                       |
| SageAttention                  | INT8/FP8 量化注意力                                                              | P1-2（视频 DiT 场景）                                             |
| MHA2MLA（论文）                    | MHA→MLA 架构转换（KV -92.19%）                                                    | **§10 MLA 专项：其 SVD 恢复法直接用于低秩缓存校准**                          |

---

## 7. 风险与纪律

1. **质量回归风险**：抽卡场景对细节敏感 ⇒ 档位矩阵 + 默认关 + 遥测 n≥3 才采纳；任何「目视偏软」报告即回退对应档位。
2. **官方倍率不入结论**：DeepCache 2.3×/2.6×/1.7×、SageAttention 2.1–3.1× 均为官方口径（他卡他条件），只作预期；项目结论一律本机重测——「没测出来 ≠ 测出来了」。
3. **诚实失败**：arch 不在白名单 / 包缺失 / 编译失败 ⇒ 禁用 + `reasons` 留痕，绝不静默降级成别的行为。
4. **新依赖纪律**：P0 全项零新依赖；SageAttention（P1）是唯一需装包项，且只做探针不进生产，装包失败不影响任何现有路径。
5. **冻结区**：已实测 9 zone 无一覆盖 `app/core/neural/`；新文件无冻结符号，不触发 `frozen_zone_guard` 变化。
6. **主备不重复造**：DiffSynth 主选侧自有 VRAM 管理，本设计不平行造第二套；切换语义（`SHIGUANG_EXEC_ENGINE`）不变。
7. **沙箱环境噪声**：早前 diffusers 管线 import 报错已定性为沙箱 sitecustomize 权限噪声（`StableDiffusionXLPipeline` 实测 IMPORT OK）；验证脚本一律 subprocess 包一层（wmic 黑栏纪律）。

---

## 8. 实施顺序建议（评审通过后）

```
第 1 步  P0-3 块池（最小、保命、无质量风险）      → 5 循环卸载实测
第 2 步  P0-2 编码器缓存（小而准，收益可证）       → 命中率 + Wan RAM 墙测算
第 3 步  P0-1 DeepCache（大头收益，SD1.5→SDXL→SVD 逐 arch 标定）
         └─ 3b 低秩缓存层（§10，与 DeepCache 同一 hook 挂载点，标定 rank×interval 矩阵）
第 4 步  （可选）P1 三件套按 组件调度 → SageAttention 探针 → 连续批
每步交付 = 代码 + 测试 + _verify 门禁 + 真机标定数据 + CHANGELOG
```

## 9. 待拍板

- **A**：范围 = 仅 P0（三步，预计一个实施周期）/ P0+P1（六步）
- **B**：DeepCache = 原生 hook（推荐）/ 官方包对照
- **C**：默认 = 关、显式开（推荐）/ fast+high 默认开
- **D**（新增，§10）：低秩缓存层 = 随 P0-1 第 3 步一并落地（推荐）/ 单独排期 / 暂缓

---

## 10. MLA 专项解法：把「低秩压缩 + 吸收」种进扩散栈

> 起因：§1.1 判定 MLA「不直接移植」，用户要求解决该问题或使用其理念。本节给出解法——不移植 MLA 的**名字**（KV cache），移植它的**四条原则**，并在项目里找到配得上的对象。

### 10.1 MLA 拆解：真正的可移植资产是四条原则

| # | MLA 的做法                            | 本质                 |
| - | ---------------------------------- | ------------------ |
| ① | 找到显存里随序列增长的主导对象（KV cache）          | **对象识别**：省显存先找对池子  |
| ② | 低秩压缩它（8192→576 标量/层/token，-92.97%） | **低秩化**：用投影矩阵换存储   |
| ③ | 吸收式重构：上投影折进 Q，运行时零解压开销             | **吸收**：压缩不许带来解压税   |
| ④ | 不可压缩的部分（位置信息 RoPE）解耦保留             | **解耦**：识别并豁免不可压缩分量 |
| ⑤ | MHA2MLA：从既有 MHA 权重 SVD 恢复投影，免训练    | **免训练恢复**：不重训也能低秩化 |

**MLA 省显存的因果链不是「低秩」本身，而是「低秩 + 吸收 + 解耦」三件套**——只做低秩会有解压税，只做吸收没有可压对象。移植必须三件套一起搬。

### 10.2 对账：项目里哪个对象配得上这四条原则

| 候选对象                                     | 冗余性                        | 主导性                                                | 适配判定                                                      |
| ---------------------------------------- | -------------------------- | -------------------------------------------------- | --------------------------------------------------------- |
| **步间特征缓存**（DeepCache 缓存的 up-block 输出 h）  | ✅ 相邻步高度相似（DeepCache 成立的前提） | ✅ 缓存的 h 占 VRAM（SDXL 128² 潜空间 × 1280 通道 ≈ 42MB/层特征） | **②③④全中** —— 主交付物                                         |
| 条件流 K/V（cross-attn 的文本 K/V，T5 512 token） | ✅ 每步重复投影同一文本流              | ⚠️ 视频模型才主导（当前 SD 77 token 无意义）                     | ②③ —— 视频模型路线图（§10.5）                                      |
| 注意力矩阵 QK^T（万级 token 的平方级激活）              | ❌ 不冗余                      | ✅ 主导                                               | **不适配** —— 它是计算不是存储，低秩化改变数学；归 SageAttention/序列并行赛道（§7 边界） |
| U-Net 权重（SDXL 6.46GB）                    | ❌ 不冗余                      | ✅ 主导                                               | 归 M4 量化赛道（torchao 重装后 int8/int4/nf4），不重复造                 |
| AR 模型的 KV（YuE 本地化时）                      | ✅                          | ✅                                                  | ⑤直接可用（MHA2MLA 论文已验证 -92.19%）—— 触发式                        |

### 10.3 主交付物：`LowRankFeatureCache`（MLA 三件套的扩散实例）

**对象**：DeepCache 在缓存步得到的 U-Net 深部特征 h ∈ R^(C×H×W)（up-blocks 输出，SD/SDXL）；SVD 侧同构（3D UNet 时序特征）。

**三件套落地**：

1. **低秩化（原则②）**：校准期对采样得到的 h 做 `torch.svd_lowrank`（MHA2MLA 同款恢复法，原则⑤），得 U_r ∈ R^(C×r)；缓存步存 **M = S_rV_r^T ∈ R^(r×H×W)** 而非 h。存储从 C×H×W 降为 r×H×W，**压缩比 = C/r**（r=25% ⇒ 4×；r=12.5% ⇒ 8×）。
2. **吸收（原则③）**：h 的唯一消费者是收尾的 `conv_out`（Conv2d(C, 4, 3)）。由于 U_r 是逐位置的通道混合、与 conv 的空间求和可交换：  
   `conv_out(h) = Σ_c W[c,Δ]·h[p,c] = Σ_c W[c,Δ]·Σ_r U[c,r]·M[p,r] = Σ_r W̃[r,Δ]·M[p,r]`，其中 **W̃[r,Δ] = Σ_c W[c,Δ]·U[c,r]**——把 U_r 预先折进 conv_out 权重（校准期一次完成），运行时**直接消费压缩表示，零解压开销**。附带收益：conv_out 计算量从 C 通道降为 r 通道。
3. **解耦（原则④）**：h 是特征图不是 token 序列，无位置结构要豁免 ⇒ 本对象不需要解耦项。但**路线图教训入库**：若未来对潜空间 token 流做低秩/合并（ToMe 式），RoPE 位置分量必须解耦保留——这是 MLA ④ 的扩散版教训。

**为什么这个压缩是安全的（结构性保险）**：DeepCache 每 `cache_interval` 步做一次全精度计算刷新缓存 ⇒ 低秩近似误差**不跨缓存周期累积**，每周期被全精度刷新清零。误差上界 = 单次近似误差 × 1（非 ×N），这是 DeepCache 结构免费给的保险，也是它敢用激进 rank 的原因。

**收益链**（与 P0-1 相乘而非相加）：

- 缓存显存 ×(C/r)（rank 25% ⇒ 4×）
- conv_out 计算 ×(r/C)
- **同显存预算下 cache_interval 可开更大**（缓存更小 ⇒ 放得下更激进的跳步）⇒ DeepCache 的 -41% 还能再进一档
- 标定旋钮：`rank_ratio ∈ {0.125, 0.25, 0.5}` × `cache_interval ∈ {3, 5}`，与质量档位矩阵（§4.1）正交叠加

**插入点**：与 P0-1 同一 hook 挂载区（`diffusers_image.py:472-525` 之后）；校准产物（U_r 与折转后的 W̃）按模型 id 落盘缓存，与权重同目录（`models/cache/<repo>/`，已被 .gitignore 忽略）；不落盘则每次加载重新校准（前若干缓存步采样，~秒级）。

### 10.4 标定与验证协议（真机，SD1.5 先行）

| 阶段         | 动作                                                                    | 判据                                     |
| ---------- | --------------------------------------------------------------------- | -------------------------------------- |
| 采样         | 前 8 个缓存步采集 h，`svd_lowrank` 累计协方差估计 U_r                                | 奇异值衰减曲线：r 取「能量 95%」拐点作默认               |
| rank sweep | SD1.5 20 步 × rank {0.5, 0.25, 0.125} × interval 3，对比全精度 DeepCache 与基线 | PSNR/CLIP 掉幅 + 缓存字节数 + 墙钟              |
| 采纳线        | rank 0.25 时 PSNR 掉 <0.5dB 且缓存显存 4× ⇒ 采纳；掉幅超标 ⇒ 回退 rank 或禁用该层          | 遥测记录 full/skipped/rank/saved_bytes，n≥3 |
| SDXL/SVD   | 同协议复测（SDXL 特征通道最大，压缩收益最高）                                             | 同上                                     |

**反例验证**（守卫不能是永远绿的摆设）：构造「rank 极小（0.03）应显著掉质量」与「interval 极大应触发回退」两个反例，断言质量指标劣化被检出——证明标定链真的在测东西。

### 10.5 路线图两项（触发条件写明）

- **`ConditioningKVCompressor`（条件流低秩 + 吸收）**：T5 类视频模型的 cross-attention 中，文本 K/V 每步被重新投影（512 token × 全通道）——这正是「每步重算的冗余对象」。MLA 式低秩文本 KV + 折进 Q 投影，cross-attn 成本 ×(r/512)。**触发 = Wan 权重落地 + P0-2 编码器缓存就绪**（当前 SD 系 77 token 上无意义，不做）。
- **GQA-ification（MHA→GQA 训练-free 头合并）**：MHA 类视频 DiT（HunyuanVideo/CogVideoX 等）的 K/V 头按组平均/SVD 合并，Q 头分组吸收——KV 投影计算与权重 ×(1/g)。**触发 = 视频 DiT 接入**。
- **AR 视频/世界模型**：若未来引入逐帧 AR 生成，跨帧 KV cache 真实存在，MLA ⑤（MHA2MLA 恢复）与 KV 量化直接可用，无需再发明。

### 10.6 诚实边界（MLA 治不了什么）

1. **治不了平方级注意力矩阵**：万级 token 的 QK^T 是计算与激活问题，低秩化会改变注意力数学 ⇒ 归 SageAttention（INT8/FP8）与序列并行（USP），本设计已单列 P1-2/P2-2。
2. **当前模型集上条件压缩无意义**：SD1.5/SDXL/SVD 的文本流只有 77 token，cross-attn 不是瓶颈 ⇒ §10.5 是路线图不是当期交付。
3. **低秩质量代价必须本机实测**：rank 曲线与 DeepCache 的 interval 曲线一样是模型相关的，论文/官方数字只作预期。「没测出来 ≠ 测出来了」。
4. **不碰主选通道**：DiffSynth 自有 VRAM 管理体系，低秩缓存只进自研 diffusers 备选通道。

---

## 11. 待拍板（汇总）

- **A. 范围**：仅 P0（三步）/ P0+P1（六步）
- **B. DeepCache 路线**：原生 hook 实现（推荐：零新依赖、可单测、可门禁、可遥测）/ 官方 `DeepCache` 包对照
- **C. 默认策略**：缓存默认关、显式开（推荐：质量风险前置）/ fast+high 档默认开
- **D. 低秩缓存层（§10）**：随 P0-1 第 3 步一并落地（推荐：同一 hook 挂载点、标定协议共享）/ 单独排期 / 暂缓

---

## 12. 补缺路线图与统一标准（2026-10-25 增补）

> 输入：用户提供四栈对账矩阵（自研 / DiffSynth / ComfyUI / SGLang 级推理引擎），指令「把这些完善，该制定统一标准的就制定统一标准」。本章 = 实证修正 + M4 量化升级 + 六条统一标准 + 修订总路线图。

### 12.1 矩阵实证修正（先纠三处，再规划）

| 矩阵单元格 | 矩阵口径 | 2026-10-25 实测 | 影响 |
|---|---|---|---|
| 低精度量化 | 「torchao 0.7.0 已装未用」 | **torchao 不在 venv**（`pip list`/`find` 双证；早前目录疑被并行会话/清理移除）；且 diffusers 0.40.0 全库无 `TorchAoConfig` | M4 第一锹 = 装回 + pin + 探针；量化路径 = torchao 原生 `quantize_()` 直作用 UNet，非 pipeline 配置 |

> **2026-10-27 更新（本行已过期，以实测为准）**：torchao **0.16.0 已装入项目 venv**（`pip show torchao` 可验），
> 探针不再返回 False。但「装得上」≠「用得了」——int8 实测画质崩，见新增 §12.3.1；INT4 在 Windows 上无可用内核。
| 视频模型覆盖 | 「6 族已登记未验证」 | 注册表实为 **3 族**（`video_gen.py:214` VIDEO_MODELS：svd-xt-i2v / wan22-ti2v-5b / wan21-t2v-1.3b），仅 SVD 验证；混元/CogVideoX 只存在于注释 | 验收协议按 3 族跑，「6 族」数字不外引 |
| 治理层数字 | 「12 切片 + 21 家云」 | 本次未能复验（backend_registry 无云厂商条目；渠道解析在 `execution_decider._resolve_aigc_channel`） | 对外材料引用前需复验，本文只用可证组件名（capability_catalog / engine_registry / execution_planner / draw_ledger / 渠道解析） |

### 12.2 战略判读：四栈各执一轴，答案不是补齐所有 ❌

矩阵的真实结构：**每家各执一轴**——DiffSynth 执卸载粒度（Layer 四态状态机 + 量化配置）、ComfyUI 执节点生态（TeaCache/SageAttention/GGUF 即插）、SGLang 级执服务级工程（continuous batching / PD 分离 / radix attention / FlashMLA）、自研执治理与集成（统一决策出口 + 画布/时间线/抽卡账本 + 诚实失败纪律）。

**补齐每一个 ❌ = 重新实现三个竞品。** 正确打法：**自研方拥有契约（标准），按需租用或自建实现**——凡是竞品已成熟且本项目无差异化的（GGUF 节点生态、FlashMLA 内核），走「能力清单登记 + 按需选路」；凡是构成护城河的（治理、账本、验收纪律），自建并升格为书面标准。

### 12.3 M4 量化（升级 P0，硬指标 = 8GB 卡点亮 14B 级）

| 步 | 内容 | 硬验收判据 |
|---|---|---|
| M4-0 环境修复 | torchao 重装 + `requirements` pin 版本 + `device_profile._libs()` 探针转 True 才算数（探针已存在，当前诚实返回 False——设计自洽的实证） | `python -c "import torchao"` 通过 + 探针 True + 版本写入 CHANGELOG |
| M4-1 INT8 weight-only | torchao 原生 `quantize_(unet, int8_weight_only())`（diffusers 0.40 无 TorchAoConfig，绕开 pipeline 配置）；SDXL 6.46GB → ~3.3GB | PSNR/CLIP 不掉级（对照同 prompt 同种子）+ 8GB 上免 model-offload（省 ~7s/次固定开销）+ 遥测 n≥3 |
| M4-2 INT4 weight-only（group 128） | 权重 ~1.8GB；Windows kernel 可用性实测（不可用则诚实记录并停在此档） | 质量 delta 可量化；反例（极端 rank/group）质量劣化被检出 |
| M4-3 FP8 | sm89 + cu124 满足（device_profile fp8 位已认）；权重 ~3.2GB | 近无损判据同上；SVD/SDXL 双 arch 复测 |
| M4-4 14B 点亮 | **组合拳验收，非单点银弹**：Wan2.1-T2V-1.3B（扩散权重 5.29GB）INT4/NF4 + P0-2 编码器缓存（T5 编码后卸，RAM 墙 13.7→~4GB）+ layer offload + DeepCache（降激活）⇒ 8GB 首次出片；Wan2.2-TI2V-5B 双专家 MoE 留 P2 | 真机出片 + 四档显存策略实测 + 质量档位标定 + 状态 unverified→verified |

### 12.3.1 实测回填：M4-1 / M4-2 / M4-3 真机结论（2026-10-27）

> 环境：RTX 4060 Laptop 8GB · torch 2.6.0+cu124 · torchao **0.16.0** · diffusers 0.40.0。
> 方法：同 prompt / 同 seed=42 / 20 步，先跑 **fp16 自比对照组**（PSNR 99.00 ⇒ 严格可复现）再比 int8。
> **结论：M4-1 → rejected（否决）；M4-2 → Windows 不可用；M4-3 → 能跑但无加速。**

| 模型 | 方案 | UNet 权重 | 峰值显存 | 耗时比 | PSNR | 判定 |
|---|---|---|---|---|---|---|
| SD1.5 | fp16 基线 | 1.60 GB | 2.02 GB | 1.00 | 99.00（自比） | — |
| SD1.5 | int8 v2（PerRow） | 1.35 GB（**-15.7%**） | 1.76 GB | 1.09 | 27.44 | rejected |
| SDXL | fp16 基线 | 4.78 GB | 5.21 GB | 1.00 | 99.00（自比） | — |
| SDXL | int8 v2（PerRow） | **2.71 GB（-43.4%）** | 4.07 GB | 0.96 | **5.29（整张全黑）** | **rejected** |

- **覆盖率**：SDXL `Linear 743/743` 全部量化（Linear 2.08GB / Conv2d 0.62GB）；SD1.5 仅部分 Linear（0.50GB vs Conv2d 1.10GB）⇒ **Conv2d 不被 int8 weight-only 覆盖，是 SD1.5 收益只有 15.7% 的根因**。
- **显存目标成立、画质失效**：本行 M4-1 写的「6.46GB → ~3.3GB」在量级上达成（实测 4.78 → 2.71），但按同行的「PSNR 不掉级」判据**不合格，不得接入主路径**。SDXL 输出像素 `mean=0 / std=0`，且不是覆盖率不足（Linear 全量化）。
- **耗时无收益**（0.96~1.12x）：fp16 激活 × int8 权重要走反量化，吃不到 tensor core。
- **M4-2 INT4 不可用**：torchao 0.16 的 int4 走 mslk，而 `mslk-1.3.0+cu130-py3-none-win_amd64.whl` 是 **351KB 纯 Python 空壳（0 个 .pyd/.dll）**，且强制 `import triton`；实测装上前者会让 **torchao 整体 import 失败**（`mslk.quantize.triton.fp8_quantize` → `ModuleNotFoundError: triton`）。已卸载恢复。
- **M4-3 FP8 仅能跑**：本机 `torch._scaled_mm` 报 `CUBLAS_STATUS_NOT_SUPPORTED` ⇒ 反量化回退，**无加速**；画质/显存对照未做 ⇒ 状态 `unverified`。

**落点**：以上数字已固化为代码资产 `app/core/neural/quant_descriptor.py`（量化描述符 + 实测证据台账 + 三态判定 + `is_admissible()` 准入裁决，`rejected` 的否决权高于门槛权）。复跑脚本在会话工作目录 `verify_int8_diffusers.py`。

**三个测量陷阱**（写进来免得重犯）：
1. 量化后 weight 是 `Int8Tensor`：`.dtype` 仍报 fp16、`.data` 返回 fp16 视图，真实存储是 `qdata`(int8) + `scale`。按 `parameters()` 的 `element_size` 求和会得出「零收益」的假结论，必须用 `torch.cuda.memory_allocated()` 差值。
2. torchao 0.16 断言 `version=2` 只支持 `group_size=None`（传 32 直接 `AssertionError`）；`version=1` 在本组合下未产生可测压缩。
3. `diffusers_image.local_dir()` 返回**相对路径**，外部脚本必须先 `os.chdir(项目根)`，否则误报「模型未下载」。

### 12.4 统一标准（六条契约——先立契约，再填细胞）

> 原则：M4/P0/P1 每一项**先登记进契约再实现**，杜绝「四项缓存四种写法、三种量化三套配置」的孤岛结局（engine_registry 9/56 闲置的教训前置使用）。

**标准 1 · 引擎能力清单（Engine Capability Manifest）**
每个引擎/后端声明：`quant ∈ {fp8,int8,int4wo,nf4}`、`offload_tiers`、`step_cache ∈ {deepcache,teacache,fbcache,none} + interval 范围`、`attn ∈ {sdpa,sageattn,flash}`、`compile`、`batch.max_n`、`verified ∈ {unverified,verified,retired}`。消费方（execution_planner/execution_decider）按「能力 × 能力」匹配选路，不按引擎名硬编码。与 `device_profile` 能力位形成对偶（设备有能力位，引擎也必须有）。落点：`engine_registry.py` 扩展字段 + `verify_catalog_consistency` 式双向守卫。

**标准 2 · 显存预算账本（VRAM Budget Ledger）**
每次 load/generate 记账：权重 / 激活 / 缓存 / VAE 分块 / 编码器驻留，分项列账；**超预算在加载前诚实失败，不等 OOM**。所有优化（量化/卸载档/步缓存/组件调度/块池）挂同一账本 ⇒ 节省可加、可归因、可复核——这是「-41% 凭什么可信」的制度答案。

**标准 3 · 缓存语义契约（Cache Contract）**
所有缓存（DeepCache/TeaCache/FBCache/EncoderOutput/LowRank）统一接口：key 定义、失效条件、遥测字段（`full_steps/skipped_steps/hit_rate/saved_bytes`）、质量档位门控。新缓存不实现契约 = 不合入。

**标准 4 · 量化描述符（Quant Descriptor）**
单一真相源：`{scheme: fp8|int8|int4wo|nf4, scope: weights|weights+act, group_size, calibration: none|static|dynamic, backend: torchao|nunchaku|gguf|native}`。引擎声明支持面，policy 按 device 能力位 × 模型兼容 × 实测质量 delta 选择；**禁止调用点各自硬编码量化参数**。

**标准 5 · 模型验收协议（登记→验证生命周期）**
M5「登记即接入」的另一半：每族过 checklist——权重落盘 → 首跑 → 四档显存策略实测 → 质量档位标定 → 遥测基线 n≥3 → 状态翻转 verified。防「登记即摆设」。

**标准 6 · 优化准入判据**
进主路径必须：对照实验（同 prompt 同种子）+ 质量判据（CLIP/PSNR/目视）+ 遥测 n≥3 + 反例验证 + 书面回退路径。已是项目文化，升格为书面标准写入 `docs/现行技术文档.md`。

**渠道演进**：主备制（primary DiffSynth / fallback builtin）→ **能力制**——manifest 齐备后，decider 按请求能力匹配选路（如「本请求要 step_cache ⇒ 路由到已实现该能力的通道」），`SHIGUANG_EXEC_ENGINE` 语义保留为强制覆盖。

### 12.5 修订总路线图（顺序即依赖）

```
S0 立契约：标准 1（能力清单）+ 标准 4（量化描述符）落 engine_registry —— 后置全部 cell 的登记处
S1 环境修复 + M4-1 INT8（SDXL）           —— 权重池第一刀，验收 = 免 offload + 质量不掉
S2 P0-3 显存块池                          —— 保命（22min 碎片死亡）
S3 P0-2 编码器输出缓存                    —— Wan 前置（RAM 墙 13.7→~4GB）
S4 P0-1 DeepCache + §10 低秩层            —— 最大提速头（SDXL -41% 预期）
S5 M4-2/3/4：INT4 → FP8 → 14B 点亮        —— 硬指标验收
S6 P1 三项：组件调度 → SageAttention 探针 → 抽卡连续批
S7 模型验收协议跑通 Wan 2 族 unverified→verified（+ 混元/CogVideoX 是否扩登记由 S7 数据定）
每步交付 = 契约登记 + 代码 + 测试 + _verify 门禁 + 真机标定 + CHANGELOG

> **2026-10-27 路线图调整**：**S1 的 "M4-1 INT8" 已按实测否决**（见 §12.3.1），不可再按原计划推进。
> 修订后的 S1 应收敛为：**M4-0 环境修复（已完成）+ M4-3 FP8 的画质/显存对照**（FP8 能跑但无加速，需先证明不掉级再看值不值得留）。
> 若仍要打「8GB 点亮更大模型」这张牌，候选换成 **NF4 / GGUF 选路**（ComfyUI 生态成熟，项目已有 `comfy_provider` 可接），
> 且必须先过 `quant_descriptor.is_admissible()` 这道闸再谈收益。
```

### 12.6 拍板项更新

- **E. M4 范围**：仅 INT8（稳）/ INT8+INT4（推荐，够到 14B 点火）/ 全量含 FP8（激进）
- **F. 标准落地**：六条契约全量写入 `docs/现行技术文档.md`（推荐）/ 先落标准 1/3/4（实现相关三条）/ 暂缓
