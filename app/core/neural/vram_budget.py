# -*- coding: utf-8 -*-
"""显存预算模型 + 档位准入预测（V4.47.0）——「这台卡预计能干什么」的单一真源。

为什么要有这个模块
==================
`memory_policy.pick_memory_policy` 回答「**这台卡**上该用哪档」（现场探测驱动）；
本模块回答互补的另一面：「**一台 12/16/24GB 的卡**上，哪些模型/分辨率进得来、
哪档最优」——预算驱动，给购卡/换卡/远程标定做预测，也让 8GB 开发机用户
提前知道引擎的能力边界。

口径（全部可追溯，禁止拍脑袋）
============================
1. 每个数字带 ``basis``：``measured``（本机实测，evidence 给文件:行号）/
   ``estimated``（由实测值按 documented 方法外推，方法写在 evidence 里）/
   ``registered``（只用注册表登记值，最粗）。三者**不许混用**。
2. 准入判据 = required ≤ total × headroom(mode)，headroom 与 memory_policy
   **同源**（whole_gpu 0.85 / offload 系 0.95，见 memory_policy._WHOLE_GPU_HEADROOM
   与 _OFFLOAD_HIGH_WATER）——两边不许各唱各调。
3. layer_cpu_offload 的准入用**装载瞬时峰**（实测 6.57GB），不是稳态 3.96GB——
   用稳态准入会漏掉「装得下但装不进去」的翻车场景（SDXL@8GB 峰值 6.57/7.6=86%，
   贴线但可过；6GB 卡 6.57/5.7=115% 必炸）。
4. 未实测的组合一律标 estimated 并写「需标定」——诚实优先于好看。
5. 步缓存（DeepCache）开销单列：由架构常量推算（up_blocks 输出张量合计），
   真机标定后由 measured 替换（见 .workbuddy/memory 实测纪律）。

与 memory_policy 的关系：本模块不替代它。pick_memory_policy 是运行时决策，
本模块是预算预测；两者对同一 (模型, 帧数, 档位) 的结论必须一致
（test_vram_budget.py 的交叉锁死这一条）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 档位表（GB）：覆盖本项目用户可能的卡型 ──────────────────────────
BUDGET_TIERS: tuple = (8, 12, 16, 24)

# headroom 与 memory_policy 同源（勿在此另立数值）
_WHOLE_GPU_HEADROOM = 0.85      # memory_policy._WHOLE_GPU_HEADROOM
_OFFLOAD_HIGH_WATER = 0.95      # memory_policy._OFFLOAD_HIGH_WATER


def _headroom(mode: str) -> float:
    return _WHOLE_GPU_HEADROOM if mode == "whole_gpu" else _OFFLOAD_HIGH_WATER


# ── 模型预算表 ────────────────────────────────────────────────────
# 结构：modes[mode] = {
#   required_gb  原生配置下的显存需求（layer 用装载峰，见模块 docstring 第 3 条）
#   basis        measured | estimated | registered
#   evidence     数字出处（文件:行号）或外推方法
#   first_s      首件耗时（秒；None=未测）
#   steady_s     稳态耗时（秒/件；None=未测）
#   load_s       加载耗时（秒；None=未测）
#   act_share    required 中随分辨率缩放的比例（权重部分不随分辨率变）
#   per_frame_gb 每帧增量（视频模型；0=图像）
# }
MODELS: Dict[str, Dict[str, Any]] = {
    "sd15-t2i": {
        "label": "Stable Diffusion 1.5（512²）",
        "kind": "image",
        "native": (512, 512),
        "weights_gb": 3.97,
        "ram_gb": 4.5,
        "modes": {
            # 实测：diffusers_image.py:213-215（SD1.5 512²/20步，同机同权重）
            "whole_gpu": {"required_gb": 4.34, "basis": "measured",
                          "evidence": "diffusers_image.py:215 峰值 4.34GB（whole_gpu 首图 7.2s/稳态 3.08s）",
                          "first_s": 7.2, "steady_s": 3.08, "load_s": 55.7,
                          "act_share": 0.09, "per_frame_gb": 0.0},
            # offload 的 VRAM 无直接实测：weights 在 CPU，卡上只有激活+单块换入
            # ⇒ 由 whole_gpu 峰值拆出激活份量（4.34-3.97=0.37）+ 块换入 ~0.4 外推
            "model_offload": {"required_gb": 0.8, "basis": "estimated",
                              "evidence": "estimated 需标定：由 4.34-3.97 激活份 + 单块换入外推（未实测 VRAM；耗时实测 5.4s/4.17s @diffusers_image.py:214）",
                              "first_s": 5.4, "steady_s": 4.17, "load_s": 31.0,
                              "act_share": 0.8, "per_frame_gb": 0.0},
        },
    },
    "sdxl-t2i": {
        "label": "Stable Diffusion XL 1.0（1024²）",
        "kind": "image",
        "native": (1024, 1024),
        "weights_gb": 6.46,
        "ram_gb": 9.0,
        "modes": {
            # 实测：四档对比 bench_sdxl_modes.py，diffusers_image.py:132-140
            # whole_gpu 在 8GB 上 420s 超时被杀（WDDM 分页）⇒ required 按「权重 7.0
            # + 激活 ~1.0」估，8GB 判据 = 实测死亡，不是估计
            "whole_gpu": {"required_gb": 8.0, "basis": "estimated",
                          "evidence": "estimated 需标定：diffusers_image.py:134 whole_gpu@8GB 420s 被杀（实测不可行）；required=权重7.0+激活~1.0 外推",
                          "first_s": None, "steady_s": None, "load_s": None,
                          "act_share": 0.12, "per_frame_gb": 0.0},
            "model_offload": {"required_gb": 5.21, "basis": "measured",
                              "evidence": "diffusers_image.py:135 定稿档 5.21GB/27.9s（R2/R3 受控复现）",
                              "first_s": None, "steady_s": 27.9, "load_s": None,
                              "act_share": 0.8, "per_frame_gb": 0.0},
            "sequential_offload": {"required_gb": 3.76, "basis": "measured",
                                   "evidence": "diffusers_image.py:138 3.76GB/61.6s（慢 2.2×，6GB 卡备选）",
                                   "first_s": None, "steady_s": 61.6, "load_s": None,
                                   "act_share": 0.8, "per_frame_gb": 0.0},
            "layer_cpu_offload": {"required_gb": 6.57, "basis": "measured",
                                  "evidence": "diffusers_image.py:139 稳态 3.96GB 但**装载峰 6.57GB**（准入用峰）；72.7s",
                                  "first_s": None, "steady_s": 72.7, "load_s": None,
                                  "act_share": 0.8, "per_frame_gb": 0.0},
        },
    },
    "svd-xt-i2v": {
        "label": "SVD img2vid-xt（576×1024，i2v）",
        "kind": "video",
        "native": (576, 1024),
        "weights_gb": 4.2,
        "ram_gb": 8.0,
        "modes": {
            # 实测：memory_policy.py:55-62 表 + :106-108 拟合（5f/8f/10f 三点）
            "model_offload": {"required_gb": 3.10, "basis": "measured",
                              "evidence": "memory_policy.py:106 拟合 base 3.10GB + 0.31GB/帧（5f 4.66/8f 5.58/10f 6.20 实测）",
                              "first_s": 40.0, "steady_s": None, "load_s": None,
                              "act_share": 0.6, "per_frame_gb": 0.31},
            # 实测存在但从未最优：5f 42.5s vs offload 40.0s；10f 直接 >600s 卡死
            "whole_gpu": {"required_gb": 3.98, "basis": "measured",
                          "evidence": "memory_policy.py:108 拟合 base 3.98GB + 0.37GB/帧；10f 实测 WDDM 分页 >600s（:62）",
                          "first_s": 42.5, "steady_s": None, "load_s": None,
                          "act_share": 0.6, "per_frame_gb": 0.37},
            # ★ policy 分支 2b 会在「model_offload 外推下限越 95% 水位」时返回
            #   sequential（如 8GB 卡 25 帧：floor 10.85 > 7.6）⇒ 预算表**必须**有
            #   此行，否则「policy 说跑 sequential、预算表查无此档」自相矛盾。
            #   数字 estimated：base = whole 3.98 ×（SDXL 实测 sequential/whole
            #   = 3.76/8.0 = 0.47）= 1.87；per_frame 取 whole 同值 0.37（每帧增量
            #   是激活份，两种模式下都驻留；权重不随帧数变）。无 SVD sequential
            #   实测 ⇒ 需标定。
            "sequential_offload": {"required_gb": 1.87, "basis": "estimated",
                                   "evidence": "estimated：base=3.98×0.47（SDXL 实测比 3.76/8.0 外推）；per_frame=0.37 同 whole（激活驻留）；需标定",
                                   "first_s": None, "steady_s": None, "load_s": None,
                                   "act_share": 0.6, "per_frame_gb": 0.37},
        },
    },
    "wan21-t2v-1.3b": {
        "label": "Wan 2.1 T2V-1.3B（轻量）",
        "kind": "video",
        "native": (480, 832),
        "weights_gb": 5.29,      # 扩散权重；另有 T5 编码器 10.58GB（内存侧）
        "ram_gb": 20.0,          # video_gen.py:250：T5 单独 10.58GB，需大内存 offload
        # ★ per_frame 全档 0.0 是**刻意的**：Wan 每帧增量无任何实测/文献依据，
        #   照抄 SVD 的 0.31 会造出假精度，且直接与 policy 矛盾——12GB 卡上
        #   policy 按登记值 8.2≤11.4 判 model_offload 可行，预算表却算出
        #   8.2+0.31×14=12.54>11.4「不准入」。两表不许互相打脸 ⇒ 无依据不计。
        #   代价：长片段的帧数缩放盲，由「需标定」标注 + Task 7 协议补。
        "modes": {
            # 本栈从未跑通过 Wan（走 local_video_infer，硬编码 model offload，
            # memory_policy 决策与实际执行脱节是已知欠账）⇒ 只有登记值
            "model_offload": {"required_gb": 8.2, "basis": "registered",
                              "evidence": "video_gen.py:249 vram_gb=8.2（登记值；本栈无 Wan 实测 ⇒ 粗）",
                              "first_s": None, "steady_s": None, "load_s": None,
                              "act_share": 0.6, "per_frame_gb": 0.0},
            # 8GB 卡上 policy 会选它（登记 8.2 > 7.6 水位）⇒ 必须给出行，
            # 否则预算表与 policy 决策互相矛盾。数字是 estimated：
            # 逐模块 offload 的语义 = 卡上仅驻留激活 + 单模块，与整模型登记值
            # 不是一回事。无本栈实测 ⇒ 标 estimated + 需标定。
            "sequential_offload": {"required_gb": 3.0, "basis": "estimated",
                                   "evidence": "estimated：逐模块 offload 仅驻留激活+单模块（无本栈实测，需标定）",
                                   "first_s": None, "steady_s": None, "load_s": None,
                                   "act_share": 0.6, "per_frame_gb": 0.0},
        },
        "ram_gate": "T5 编码器 10.58GB ⇒ 内存 <20GB 的机器**装不起来**（video_gen.py:238-251）",
    },
    "wan22-ti2v-5b": {
        "label": "Wan 2.2 TI2V-5B（质量最好）",
        "kind": "video",
        "native": (480, 832),
        "weights_gb": 10.0,      # 5B 参数 fp16 量级（登记 full_repo 31.9GB 含 VAE/T5）
        "ram_gb": 20.0,
        "modes": {
            "model_offload": {"required_gb": 8.0, "basis": "registered",
                              "evidence": "video_gen.py:236 vram_gb=8.0（登记值；本栈无 Wan 实测 ⇒ 粗）",
                              "first_s": None, "steady_s": None, "load_s": None,
                              "act_share": 0.6, "per_frame_gb": 0.0},
            "sequential_offload": {"required_gb": 4.0, "basis": "estimated",
                                   "evidence": "estimated：逐模块 offload 仅驻留激活+单模块（无本栈实测，需标定）",
                                   "first_s": None, "steady_s": None, "load_s": None,
                                   "act_share": 0.6, "per_frame_gb": 0.0},
        },
        "ram_gate": "T5 编码器 10.58GB ⇒ 内存 <20GB 的机器**装不起来**（video_gen.py:238）",
    },
}


def resolution_scale(width: int, height: int, native: tuple) -> float:
    """分辨率缩放系数（激活 ∝ 像素面积；权重不随分辨率变）。

    返回「激活部分的面积比」：scale = (w×h)/(nw×nh)。调用方按 act_share 加权。
    """
    nw, nh = int(native[0]), int(native[1])
    if nw <= 0 or nh <= 0:
        return 1.0
    return (float(width) * float(height)) / (float(nw) * float(nh))


def required_gb(model_id: str, mode: str, frames: int = 0,
                width: int = 0, height: int = 0) -> Optional[float]:
    """估计 (模型, 模式, 帧数, 分辨率) 下的显存需求（GB）。

    required = base × (1-act_share + act_share×area_scale) + per_frame×frames
    · 分辨率未给 ⇒ 用原生（scale=1）；
    · 无该模式登记 ⇒ None（不编数字）。
    """
    m = MODELS.get(model_id)
    if not m:
        return None
    row = m["modes"].get(mode)
    if not row:
        return None
    base = float(row["required_gb"])
    act = float(row.get("act_share", 0.0))
    scale = 1.0
    if width and height:
        scale = resolution_scale(width, height, m["native"])
    eff = base * ((1.0 - act) + act * scale)
    fr = max(0, int(frames))
    return round(eff + float(row.get("per_frame_gb", 0.0)) * fr, 2)


def admits(model_id: str, mode: str, tier_gb: float, frames: int = 0,
           width: int = 0, height: int = 0) -> bool:
    """准入判据：required ≤ tier × headroom(mode)（headroom 与 memory_policy 同源）。"""
    req = required_gb(model_id, mode, frames, width, height)
    if req is None:
        return False
    return req <= float(tier_gb) * _headroom(mode)


def _speed_key(row: Dict[str, Any]) -> tuple:
    """模式速度快慢排序键（小者优）。

    SVD 全模式 steady_s=None（视频只测了首件）⇒ 早年靠 dict 顺序决胜是隐式
    巧合。现在显式分四级：有稳态实测 > 无稳态但有首件实测 > 都无（按 dict 序，
    由「严格小于才替换」保证稳定）。
    """
    steady = row.get("steady_s")
    first = row.get("first_s")
    return (0 if steady is not None else 1, float(steady or 0.0),
            0 if first is not None else 1, float(first or 0.0))


def best_mode(model_id: str, tier_gb: float, frames: int = 0,
              width: int = 0, height: int = 0,
              supported_modes: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
    """该档位上「 admitted 且实测最快」的模式；无 admitted 或全无实测时效返回 None。

    排序键见 `_speed_key`；whole_gpu 在实测翻过车的组合里 required 已是估计值
    ⇒ 仍然参与比较，但 basis 随结果返回，调用方可见。
    """
    m = MODELS.get(model_id)
    if not m:
        return None
    modes = tuple(supported_modes) if supported_modes else tuple(m["modes"])
    best: Optional[Dict[str, Any]] = None
    best_key: Optional[tuple] = None
    for mode in modes:
        row = m["modes"].get(mode)
        if row is None or not admits(model_id, mode, tier_gb, frames, width, height):
            continue
        cand = {"mode": mode, "steady_s": row.get("steady_s"),
                "first_s": row.get("first_s"), "basis": row["basis"],
                "required_gb": required_gb(model_id, mode, frames, width, height)}
        key = _speed_key(row)
        if best is None or key < best_key:
            best, best_key = cand, key
    return best


# ── 准入预测的配置矩阵（UI/报告/测试共用，勿手抄）────────────────────
# (model_id, frames, width, height, 配置说明)
# 选取原则：每个模型覆盖「原生 ± 一档」的分辨率/帧数，即用户真实会拧的旋钮；
# 帧数取漫剧实际档位（7fps：14 帧=2s，25 帧≈3.5s）。
ADMISSION_CONFIGS: List[tuple] = [
    ("sd15-t2i", 0, 512, 512, "原生 512²"),
    ("sd15-t2i", 0, 768, 768, "高清 768²（激活 ×2.25）"),
    ("sdxl-t2i", 0, 768, 768, "降档 768²（激活 ×0.56）"),
    ("sdxl-t2i", 0, 1024, 1024, "原生 1024²"),
    ("sdxl-t2i", 0, 1280, 1280, "超原生 1280²（激活 ×1.56）"),
    ("svd-xt-i2v", 14, 576, 1024, "2s@7fps"),
    ("svd-xt-i2v", 25, 576, 1024, "3.5s@7fps"),
    ("wan21-t2v-1.3b", 14, 480, 832, "2s@7fps（T5 内存门见 ram_gate）"),
    ("wan22-ti2v-5b", 14, 480, 832, "2s@7fps（T5 内存门见 ram_gate）"),
]


def admission_table(tiers: tuple = BUDGET_TIERS) -> List[Dict[str, Any]]:
    """生成 estimated 准入预测表（UI/报告直接渲染，勿手抄）。

    每行：模型 × 代表性配置 × 各档位准入结论 + 该档最优模式。
    注意本表只回答「预算上装不装得下、哪档最快」；引擎**实际**会用的模式由
    `memory_policy.pick_memory_policy` 决定（运行时探测驱动），两者的一致性
    由 test_vram_budget.py 交叉锁死——sd15 是已知的「预算最优 whole_gpu、
    引擎保守 model_offload」分歧（policy 无 sd15 实测登记，见报告 §5）。
    """
    rows: List[Dict[str, Any]] = []
    for model_id, frames, w, h, caption in ADMISSION_CONFIGS:
        m = MODELS[model_id]
        per_tier: Dict[str, Any] = {}
        for tier in tiers:
            admitted = [mode for mode in m["modes"]
                        if admits(model_id, mode, tier, frames, w, h)]
            best = best_mode(model_id, tier, frames, w, h)
            per_tier[str(tier)] = {
                "admitted_modes": admitted,
                "best": best,
                "note": ("不可用" if not admitted else
                         ("可行未标定" if (best is None or best["basis"] != "measured")
                          else "最优 %s" % best["mode"])),
            }
        rows.append({"model_id": model_id, "label": m["label"],
                     "frames": frames, "width": w, "height": h,
                     "kind": m["kind"], "caption": caption, "tiers": per_tier,
                     "ram_gate": m.get("ram_gate", "")})
    return rows


def step_cache_overhead_gb(model_id: str, frames: int = 0,
                           width: int = 0, height: int =0) -> float:
    """DeepCache 附加显存（up_blocks 输出缓存）。

    方法：Σ(up_block 输出通道 × 空间尺寸 × 2B)，按各 block 输出分辨率累加。

    ★ 2026-10-25 真机标定后**从 estimated 转 measured**（基准 =
      `scripts/bench_p0_cache.py overhead --model M`，本机 RTX4060 8GB，
      真实 UNet 前向 hook 抓 up_blocks 输出形状）：
      · up_block 输出通道 = reversed(block_out_channels)[i]
        （diffusers unet_2d_condition.py:440）。
      · up_block 输出空间 = latent >> max(0, n-2-i)，n = up_blocks 数
        —— 非末块各升一级、末块不升。**旧表按 latent>>(n-1-i) 算，整体错位一级**
        （SD1.5 实测 [16,32,64,64]@512，旧表推 [8,16,32,64]）。
      · SDXL 本机权重实测是 **3 块**（block_out (320,640,1280)）⇒ up 3 块
        (1280,640,320)；旧表写的 4 块 + 2560 通道是**不存在的结构**。
      · SVD 通道与 SD1.5 同（block_out (320,640,1280,1280)），
        帧维乘 **latent 帧数**（输出帧 /4 + 1），不是输出帧数。
      实测值：sd15@512 = 0.010GB / sdxl@1024 = 0.039GB / svd@576×1024(14帧) = 0.093GB。
    """
    # (channels, 空间边长分母相对 latent 的缩放) —— latent = (H/8, W/8)
    _ARCH: Dict[str, List[tuple]] = {
        # SD1.5 block_out (320,640,1280,1280) ⇒ up 输出 (1280,1280,640,320)，
        # 空间 16/32/64/64²@512 ⇒ div = 32/16/8/8
        "sd15-t2i": [(1280, 32), (1280, 16), (640, 8), (320, 8)],
        # SDXL **3 块**（本机权重 config 实测）⇒ up (1280,640,320)，
        # 空间 64/128/128²@1024 ⇒ div = 16/8/8
        "sdxl-t2i": [(1280, 16), (640, 8), (320, 8)],
        # SVD block_out (320,640,1280,1280)（本机权重 config 实测）⇒ 同 SD1.5，
        # 帧维再乘 latent 帧数
        "svd-xt-i2v": [(1280, 32), (1280, 16), (640, 8), (320, 8)],
    }
    spec = _ARCH.get(model_id)
    if not spec:
        return 0.0
    m = MODELS.get(model_id) or {}
    nw, nh = m.get("native", (512, 512))
    lw, lh = max(1, nw // 8), max(1, nh // 8)      # latent 尺寸
    if width and height:
        lw, lh = max(1, width // 8), max(1, height // 8)
    total = 0
    for ch, div in spec:
        fw, fh = max(1, lw * 8 // div), max(1, lh * 8 // div)
        total += ch * fw * fh * 2                    # fp16
    if m.get("kind") == "video":
        # 帧维乘 **latent 帧数**（VAE 时间下采样 4×）：输出 14 帧 ⇒ latent 4 帧。
        # 旧公式乘输出帧数 ⇒ 高估 3.5×。
        out_frames = max(1, int(frames or 14))
        total *= (out_frames - 1) // 4 + 1
    return round(total / (1024 ** 3), 3)
