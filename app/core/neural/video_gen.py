# -*- coding: utf-8 -*-
"""视频生成引擎（本地） —— 走项目自己的模型获取链路，**不经 ComfyUI**

为什么单独一个模块
==================
`app/core/neural/` 下现有 5 个引擎（人脸修复/超分/重绘/抠像/风格）都是 **ONNX**，
走 `neural_engine` 的 ONNX 后端；而视频扩散模型必须走 **PyTorch + diffusers**，
产物也不一样（video 而非 image）。所以单独成模块，但**复用**：
  - 模型下载：`neural_engine.download_snapshot()`（含 **HF 镜像兜底 → ModelScope** 链路）
  - 后端探测：`neural_engine` 的 CUDA 检测
  - 缓存落盘：`models/cache/<repo>/`（**已被 .gitignore 忽略**，不会污染仓库）

为什么不用 ComfyUI 拉取
=======================
ComfyUI 会引入第二套模型管理（它自己的 models/ 目录、它自己的下载器、它自己的节点包），
与本项目的 `models/cache` + `neural_engine` 形成**两套真源**。本模块坚持项目单一链路。

★ 选型是按**本机实测约束**定的，不是照抄榜单
============================================
本机：RTX 4060 Laptop **8GB VRAM** · 系统内存 **15.3GB**（可用约 5GB）。
实测各仓库体积（2026-10-01，经 hf-mirror API `?blobs=true`）：
  - Wan2.2-TI2V-5B 全仓 **31.9 GB**，其中 **T5 文本编码器单独 10.58 GB**
  - Wan2.1-T2V-1.3B 全仓 **16.4 GB**，同样那个 **10.58 GB T5**
  - SVD img2vid-xt 全仓 30.4 GB，但 **fp16 推理子集仅 ~4.2 GB**（CLIP 编码器，无巨型 T5）
⇒ **Wan 系在 15GB 内存上 offload 不动那个 T5**（会疯狂换页）；
  **SVD 是唯一在「8GB 显存 + 15GB 内存」下真正跑得起来的**，而且它是 **图生视频（i2v）**，
  正好补项目一直缺的「图→视频」。

纪律（与项目其它引擎一致）
--------------------------
1. **诚实失败**：模型没下 → 返回明确的下载指引；显存/内存不足 → 明说，
   **绝不返回占位视频、绝不静默降级成别的模型**。
2. **绝不抛异常**：所有对外方法异常一律吞掉并记日志，返回 ok=False。
3. **不自动下载**：`generate()` **不触发下载**；必须显式 `pull()`。
   理由：一个模型 4~32GB，默默开始下载是极差的体验。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# data URL 解析（与 canvas_enhance 同口径）
_DATA_URL_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,(.+)$", re.S)


# ────────────────────── 实测调优参数（唯一真源）──────────────────────
# 2026-10-01 在**本机 RTX 4060 Laptop 8GB** 上逐项实测得出，不是抄来的经验值。
# 结论与两次**被推翻的中间判断**都记在下面 —— 因为这里每一条都反直觉，
# 不写清依据，后人（包括我自己）复盘时必然凭直觉改回去。
#
#  ★ 最终配置：**offload 保持开启 + decode_chunk_size=1 + 14 步**
#    实测（14 步 / chunk=1 / offload 开）：
#      5 帧 40.0s（4.66GB）· 8 帧 63.9s（5.58GB）· 10 帧 75.7s（6.2GB）
#      稳定 ~8 s/帧，各种帧数都远低于 8GB 上限。
#    对比 V4.40.17 的原默认（offload + chunk=2 + 25 步）10 帧 133s ⇒ **约 1.8 倍**。
#
#  ① **`decode_chunk_size` 必须用 1**（收益最稳的一项，也是唯一真正的大头）
#     chunk=1 的 VAE 解码 **2.4~3.8s** vs chunk=2 的 **37.5s**（5 帧）——**小了反而快约 6 倍**，
#     且显存更低（6.51→5.84GB）。原因：chunk=2 让时序 VAE 走更重的分块路径并吃满显存；
#     帧数一高就压到显存上限触发 WDDM 分页，实测 **8 帧 chunk=2 要 377s（47 s/帧）**。
#     已验证输出等价：与 chunk=2 逐帧 PSNR **46.0 dB**、拼图肉眼不可区分。
#
#  ② **offload 保持开启** —— ⚠️ 这条经过**两次反转**，务必看完整推理再动：
#     · 最初判断「offload 是最大瓶颈」⇒ 改成不 offload。**该判断是错的**：
#       它是在 **chunk=2** 下测出来的（offload+chunk2 时 VAE 被反复搬运，双重惩罚），
#       把 chunk 的锅记到了 offload 头上 —— 典型的**混淆变量**。
#     · 固定 chunk=1 重测后反转：**offload 开启反而更快**
#       （5 帧 40.0s vs 不 offload 42.5s），且显存更低（4.66 vs 5.84GB）。
#     · 更关键的是**安全性**：不 offload 时显存随帧数增长（≈0.4GB/帧），
#       10 帧达 7.7GB 直接触发 WDDM 分页 ⇒ 实测 **>600s 卡死**（从 75.7s 退化）。
#     ⇒ 结论：offload 又稳又快，**没有理由关掉**。别再试「8GB 装得下就去掉 offload」。
#
#  ③ **步数是唯一的质量/速度旋钮**：每步约 **2.27s**（14 步实测，与总步数无关）。
#     25→14 步省约 25s；减步会削平动作，故默认 **14**
#     （实测：14 步运动保留 98%，10 步运动升到 132%，属采样不足，不作默认）。
#
# 未采用（都**实测排除**，别再试 —— 括号内是实测证据）：
#   · **关掉 CFG**（`max_guidance_scale=1.0`）—— 每步快 1.85x，但输出直接废掉：
#     首帧保持 35.1→15.9dB、拼图上噪声糊满画面。（本项现已显式传参 + 守卫断言锁死）
#   · **`torch.compile`** —— ① 本机无 Triton：`Cannot find a working triton installation`
#     （Windows 上 inductor 无法生成代码，回退 eager，等于没编译）；
#     ② 即便能编，`OptimizedModule` **打断 accelerate 的 offload 钩子**
#     （`AttributeError: 'OptimizedModule' object has no attribute '_hf_hook'`）；
#     ③ 首步编译实测 **97.5s**。
#   · **换调度器** —— SVD 用 EDM 定制计划（`sigma_max=700`），
#     `deis`/`dpm++`/`heun` **直接崩**（`IndexError: index N out of bounds`）；
#     `euler_ancestral` 运动爆表（1.07→26.05、PSNR 6.1dB）；
#     `kdpm2` 完全静止（运动 0.000、PSNR 4.2dB）且更慢。
#   · **VAE fp32** —— `Input type (Half) and bias type (float) should be the same`
#   · **`vae.enable_slicing()`** —— 该 VAE（AutoencoderKLTemporalDecoder）未实现
#   · **`decode_chunk_size` 调大（4/8）** —— 更慢且爆显存（9.88GB > 8GB）
#   · **注意力优化** —— 已是 `AttnProcessor2_0`（PyTorch SDPA），无免费空间；
#     xformers 未安装且 SDPA 已等价
#   · **「分帧数决定是否 offload」的自适应策略** —— 一度实现过，
#     但数据表明 offload 全程不亏 ⇒ **复杂度不成立**，已删除。
# ── 质量档位（steps）：唯一真正的质量/速度旋钮 ────────────────────────
# 2026-10-01 真实立绘实测（6 帧 / chunk=1 / offload 开）：
#   10 步 → 2.14x 速度（相对 25 步）
#   14 步 → 1.74x          ← 默认（前 4 帧画面与 25 步肉眼同级）
#   20 步 → 1.24x
#   25 步 → 1.00x（原默认）
# 实测结论：**在动漫立绘上，10 步与 25 步的前 4 帧肉眼几乎无差**；
# 后段漂移是 SVD 对「分布外素材」的固有局限，**不是步数造成的**。
# ⇒ 默认 14 步在「画质看不出差、速度快 1.7 倍」的平衡点上。
#   真实照片（SVD 的训练域）若觉得细节不足，可上 `best`（25 步）。
QUALITY_PRESETS: Dict[str, int] = {
    # ★ 蒸馏预览档（2026-10-02 引入）：**需配步数蒸馏权重**（lightx2v / Wan22-Lightning 4步 LoRA、
    #   HunyuanVideo 1.5 的 8/12 步、FastVideo 的 3 步之一）。实测社区共识：
    #   **4 步能出图但明显偏软，舒适区在 6~8 步** ⇒ 故取 6 而非 4。
    #   ⚠️ 蒸馏模型**要求 CFG=1.0**（训练时就是无 CFG 的）—— 由 `TUNED[..]["distilled"]` 控制，
    #   见 `generate()` 里的分支与 `_verify/check_video_gen.py` 的旁路。
    "preview": 6,
    "fast": 10,  # 极速：动漫/立绘素材够用
    "balanced": 14,  # 默认
    "best": 25,  # 原默认质量
}

# ── 运动档位（motion_bucket_id）：★ 漫剧素材的**免费画质提升** ──────────
# SVD 的 `motion_bucket_id`（默认 127）控制运动幅度。**不是越大越好**。
# 2026-10-01 真实立绘实测（14 步 / 6 帧）：
#   mb80  → 运动 19.9 · 抖动 15.48 · 首帧保持 **23.0dB**  ← **主体 6 帧全程稳定**
#   mb127 → 运动 18.8 · 抖动 17.68 · 首帧保持 22.5dB      ← 后 2 帧开始崩
#   mb180 → 运动 23.4 · 抖动 21.77 · 首帧保持 22.4dB      ← 第 4 帧起就明显变形
# **拼图肉眼结论（决定性）**：mb80 下角色的脸/头发/服饰在**全部 6 帧**都保持连贯；
# mb127 与 mb180 都在后段崩坏。而三者**耗时相同（约 48~50s）** ⇒ 这是纯赚的画质提升。
# ⇒ **本项目主力素材是漫剧/立绘 ⇒ 默认取 `calm`(80)**。
#   真实照片若确实需要更大幅度运镜，再上 `normal`(127) / `lively`(180)。
MOTION_PRESETS: Dict[str, int] = {
    "calm": 80,  # 默认：立绘/漫剧，主体保得住
    "normal": 127,  # SVD 原默认（真实照片场景）
    "lively": 180,  # 明显运动，但形变风险高
}

# SVD 的 CFG 参数。**必须显式传入**（别依赖隐式默认）：
# `do_classifier_free_guidance = (max_guidance_scale > 1.0)`；
# 实测把它设成 1.0（关 CFG）会让每步快 1.85x，但**输出直接废掉** ——
# 首帧保持从 35.1dB 崩到 15.9dB，拼图上噪声糊满画面（2026-10-01 实测+眼看）。
# ⇒ 显式写死 + 守卫断言，防止有人「为了提速」把它关掉。
#
# ⚠️ **这条结论的适用范围（2026-10-02 补充，很重要，别当成普适规律）**：
#   上述「关 CFG 必崩」只对**未蒸馏的基模**成立。
#   社区/官方的**步数蒸馏**产物（如 lightx2v / Wan22-Lightning 4 步 LoRA、
#   HunyuanVideo 1.5 的 8/12 步 checkpoint、FastVideo 的 3 步）是
#   **专门训练来在 CFG=1.0 下工作**的 —— 对它们而言关 CFG 不但不崩，反而是**必要条件**。
#   ⇒ 将来若引入蒸馏模型，**必须按该模型的说明设 CFG**，不要把本模块的 `_CFG_MAX` 硬套过去。
#   守卫里的「CFG 不得关闭」断言同样只针对 **TUNED 表内已登记的非蒸馏模型**。
_CFG_MIN = 1.0
_CFG_MAX = 3.0

TUNED: Dict[str, Dict[str, Any]] = {
    "svd-xt-i2v": {
        "steps": QUALITY_PRESETS["balanced"],  # 14
        "decode_chunk_size": 1,
        "offload": True,
        "offload_max_frames": 0,
        # ★ 漫剧/立绘素材取 calm(80)：实测主体 6 帧全程稳定，
        #   而默认 127/180 后段崩坏 —— 且三者耗时相同（纯赚）。
        "motion_bucket_id": MOTION_PRESETS["calm"],
        "noise_aug_strength": 0.02,  # SVD 默认，未发现需要改
        "cfg_min": _CFG_MIN,
        "cfg_max": _CFG_MAX,
        # ★ 是否**步数蒸馏**权重（2026-10-02 引入）。
        #   SVD-xt 是**未蒸馏基模** ⇒ False ⇒ 必须开 CFG（关掉出废片，实测见上）。
        #   若将来换成蒸馏权重（lightx2v / Wan22-Lightning 4步 / HunyuanVideo 1.5 8-12步 /
        #   FastVideo 3步），把此项置 True：蒸馏产物**训练时就是无 CFG 的**，
        #   此时 **CFG 必须为 1.0**，否则反而劣化。
        #   守卫 `_verify/check_video_gen.py` 对 `distilled=True` 的条目**跳过**「CFG 不得关闭」断言。
        "distilled": False,
    },
}
_DEFAULT_TUNED: Dict[str, Any] = {
    "steps": 25,
    "decode_chunk_size": 2,
    "offload": True,
    "offload_max_frames": 0,
}


def tuned_for(model_id: str) -> Dict[str, Any]:
    """取该模型的实测最优参数（未登记的模型退回保守默认，保证不炸显存）。"""
    return dict(TUNED.get(model_id) or _DEFAULT_TUNED)


def should_offload(model_id: str, frames: int = 0) -> bool:
    """是否 offload。

    当前实测结论：**所有帧数都 offload**（见文件顶部 ②，经过两次反转后定稿）。
    短片段关掉它收益为负（更慢且更费显存），长片段关掉它直接分页卡死。

    ★ V4.40.24 起本函数只是 `memory_policy.pick_memory_policy()` 的**薄壳**：
    显存判定已收口到 `app/core/neural/memory_policy.py`（W1 显存分级的单一决策点），
    此处保留签名仅为兼容既有调用方与测试/守卫。
    """
    from app.core.neural.memory_policy import pick_memory_policy

    spec = VIDEO_MODELS.get(model_id) or {}
    return bool(
        pick_memory_policy(
            model_id,
            frames=frames,
            tuned=tuned_for(model_id),
            registered_vram_gb=spec.get("vram_gb"),
        )["offload"]
    )


# ────────────────────────── 模型注册表（唯一真源）──────────────────────────
# size_gb 均为 **2026-10-01 经 hf-mirror API 实测**，不是估的。
VIDEO_MODELS: Dict[str, Dict[str, Any]] = {
    "svd-xt-i2v": {
        "label": "SVD img2vid-xt（图生视频）",
        "repo": "stabilityai/stable-video-diffusion-img2vid-xt",
        "pipeline": "StableVideoDiffusionPipeline",
        "params": "1.5B",
        "modes": ["i2v"],
        "full_repo_gb": 30.4,
        "subset_gb": 4.2,  # 只取 fp16 推理子集
        "vram_gb": 7.0,
        "ram_gb": 8.0,
        "note": "8GB 显存 + 15GB 内存下唯一跑得动的；CLIP 编码器，无巨型 T5",
        "license": "Stability 社区许可",
    },
    "wan22-ti2v-5b": {
        "label": "Wan 2.2 TI2V-5B（文/图生视频）",
        "repo": "Wan-AI/Wan2.2-TI2V-5B",
        "pipeline": "WanPipeline",
        "params": "5B",
        "modes": ["t2v", "i2v"],
        "full_repo_gb": 31.9,
        "subset_gb": 31.9,
        "vram_gb": 8.0,
        "ram_gb": 20.0,  # ← T5 单独 10.58GB，需大内存 offload
        "note": "质量最好，但 T5 编码器 10.58GB，本机 15GB 内存**不够 offload**",
        "license": "Apache-2.0",
    },
    "wan21-t2v-1.3b": {
        "label": "Wan 2.1 T2V-1.3B（文生视频，轻量）",
        "repo": "Wan-AI/Wan2.1-T2V-1.3B",
        "pipeline": "WanPipeline",
        "params": "1.3B",
        "modes": ["t2v"],
        "full_repo_gb": 16.4,
        "subset_gb": 16.4,
        "vram_gb": 8.2,
        "ram_gb": 20.0,
        "note": "扩散权重仅 5.29GB，但同样要那 10.58GB T5",
        "license": "Apache-2.0",
    },
}

# SVD 只取 fp16 推理子集：24 个文件里 2 个 9GB 的原始 .pth 完全用不上。
_SVD_FP16_PATTERNS = [
    "model_index.json",
    "scheduler/*",
    "feature_extractor/*",
    "unet/config.json",
    "vae/config.json",
    "image_encoder/config.json",
    "unet/*.fp16.safetensors",
    "vae/*.fp16.safetensors",
    "image_encoder/*.fp16.safetensors",
]


def available_models() -> List[Dict[str, Any]]:
    """列出可选视频模型（供 UI 渲染；含体积/显存/内存需求，便于用户判断）。"""
    out = []
    for mid, spec in VIDEO_MODELS.items():
        out.append(
            {
                "id": mid,
                "label": spec["label"],
                "params": spec["params"],
                "modes": list(spec["modes"]),
                "download_gb": spec["subset_gb"],
                "vram_gb": spec["vram_gb"],
                "ram_gb": spec["ram_gb"],
                "note": spec["note"],
                "license": spec["license"],
            }
        )
    return out


class VideoGenEngine:
    """本地视频生成引擎。**模型不自动下载**，须先 `pull()`。"""

    def __init__(self) -> None:
        self._pipe = None
        self._loaded_id = ""
        self._offload = ""  # "" / "model" / "sequential" / "none"
        self._tuned: Dict[str, Any] = dict(_DEFAULT_TUNED)
        self._memory_policy: Dict[str, Any] = {}  # 最近一次 load 的显存策略（可见性）
        # M3：svd 驻留合一后，本引擎持有的管线可能同时活在共享缓存里；
        # unload/OOM 时必须连带 evict，否则「释放显存」只释放了引用、缓存还留着。
        self._shared_key = None

    # ── 能力探测（不加载模型）──────────────────────

    @staticmethod
    def is_available() -> bool:
        """diffusers + torch + CUDA 是否齐备。

        ★ **探测只做 `find_spec`，绝不真的 import diffusers**（2026-10-01 血泪）：
          在 `is_available()` 里 `from diffusers import DiffusionPipeline` 会触发
          diffusers 的懒加载链；在全量 pytest 环境下（已有大量模块占用）
          **直接把进程搞崩**（不是抛异常，是硬崩，整个测试套件中断）。
          而单独跑该模块的测试时又侥幸不崩 —— 这种「只在组合场景炸」的问题最难查。
          ⇒ 探测存在性用 `find_spec`（纯查文件，零副作用）；
             真正 `import diffusers` 只放在 `load()` 里，即**只在用户明确要加载模型时**才发生。
        """
        import importlib.util as _u

        for mod in ("torch", "diffusers"):
            if _u.find_spec(mod) is None:
                return False
        try:
            import torch  # torch 是本项目的基础依赖，导入代价可接受

            return bool(torch.cuda.is_available())
        except Exception:
            logger.debug("[video_gen] CUDA 探测失败", exc_info=True)
            return False

    @staticmethod
    def unavailable_reason() -> str:
        """不可用时给出**具体**原因（而不是笼统说"不可用"）。同样**不 import diffusers**。"""
        import importlib.util as _u

        if _u.find_spec("torch") is None:
            return "未安装 torch"
        if _u.find_spec("diffusers") is None:
            return "未安装 diffusers（pip install diffusers accelerate）"
        try:
            import torch

            if not torch.cuda.is_available():
                return "已装依赖但 CUDA 不可用（视频扩散会极慢或不可行）"
        except Exception:
            return "torch 探测异常"
        return ""

    # ── 本地是否已下载 ─────────────────────────────

    @staticmethod
    def local_dir(model_id: str) -> str:
        """该模型在本地的落盘目录（可预测；不下载）。

        ★ 2026-10-25 修：Wan 系在 ModelScope 有 **diffusers 变体**仓库名
        （`Wan-AI/Wan2.1-T2V-1.3B-Diffusers`），M5 真机验收下的就是它。
        注册表写的是模型本体名，直接拼目录会把「已下载」误判成「未下载」
        ⇒ 这里按 本体名 → `-Diffusers` → `-diffusers` 依次找**已存在的目录**，
        都没有才返回本体名（让 is_downloaded 如实 False）。
        """
        from app.core.neural_engine import get_neural_engine

        spec = VIDEO_MODELS.get(model_id) or {}
        repo = spec.get("repo") or model_id
        engine = get_neural_engine()
        nominal = engine.repo_local_dir(repo)
        if os.path.isdir(nominal):
            return nominal
        for suffix in ("-Diffusers", "-diffusers"):
            cand = engine.repo_local_dir(repo + suffix)
            if os.path.isdir(cand):
                logger.info("[video_gen] %s 命中 diffusers 变体目录：%s", model_id, cand)
                return cand
        return nominal

    @staticmethod
    def is_downloaded(model_id: str) -> bool:
        """判断是否已落盘：`model_index.json` + 主网络权重。

        ★ 2026-10-25 修：SVD 的主网络目录是 `unet/`，但 **Wan 系用 `transformer/`**
        （WanPipeline 的 DiT 叫 transformer）⇒ 旧实现只认 unet，把真下好的 Wan 判成
        「未下载」。现在 unet / transformer 二者其一有 safetensors 即算落盘。
        """
        d = VideoGenEngine.local_dir(model_id)
        if not os.path.isfile(os.path.join(d, "model_index.json")):
            return False
        for net in ("unet", "transformer"):
            nd = os.path.join(d, net)
            if os.path.isdir(nd) and any(
                    n.endswith(".safetensors") for n in os.listdir(nd)):
                return True
        # 单文件一体化权重（如社区整合包）也认
        return any(n.endswith(".safetensors") for n in os.listdir(d))

    @staticmethod
    def downloaded_bytes(model_id: str) -> int:
        """已落盘字节数（用于进度/展示）。"""
        tot = 0
        for root, _dirs, files in os.walk(VideoGenEngine.local_dir(model_id)):
            for f in files:
                try:
                    tot += os.path.getsize(os.path.join(root, f))
                except OSError:  # stability-gate: allow-swallow（逐文件累加体积只为展示估计值；文件在 walk 途中消失(OSError)无需诊断）
                    pass
        return tot

    # ── 拉取（项目原生链路：neural_engine → HF 镜像 → ModelScope）──

    def pull(
        self, model_id: str, progress_cb: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """下载模型到 `models/cache/<repo>/`。**异常绝不外抛。**

        返回 ``{ok, model_id, path, bytes, message}``。
        """
        spec = VIDEO_MODELS.get(model_id)
        if not spec:
            return {
                "ok": False,
                "model_id": model_id,
                "message": f"未知模型 id（可选：{', '.join(VIDEO_MODELS)}）",
            }

        if self.is_downloaded(model_id):
            return {
                "ok": True,
                "model_id": model_id,
                "path": self.local_dir(model_id),
                "bytes": self.downloaded_bytes(model_id),
                "message": "已在本机，无需重复下载",
            }

        try:
            from app.core.neural_engine import get_neural_engine

            eng = get_neural_engine()
            patterns = _SVD_FP16_PATTERNS if model_id == "svd-xt-i2v" else None
            path = eng.download_snapshot(
                spec["repo"], allow_patterns=patterns, progress_cb=progress_cb, max_workers=4
            )
        except Exception as e:
            logger.debug("[video_gen] pull 异常", exc_info=True)
            return {"ok": False, "model_id": model_id, "message": f"{type(e).__name__}: {e}"}

        if not path:
            return {
                "ok": False,
                "model_id": model_id,
                "message": "两条下载通道都失败（HF 镜像 / ModelScope），未落盘任何东西",
            }
        return {
            "ok": True,
            "model_id": model_id,
            "path": path,
            "bytes": self.downloaded_bytes(model_id),
            "message": "下载完成",
        }

    # ── 加载 / 生成 / 卸载 ─────────────────────────

    def load(self, model_id: str, frames: int = 0) -> Dict[str, Any]:
        """加载 pipeline（走**实测调优表**；`frames` 仅用于日志）。

        为什么保留 `frames` 参数：它一度用于「按帧数决定是否 offload」的自适应策略，
        但实测表明 offload 全程不亏（见文件顶部 ②，结论两次反转后定稿），
        该策略已删除。保留入参是为将来真有需要时不必改签名。

        同一模型已加载则直接复用（不重复加载，省 15~18s）。异常绝不外抛。
        """
        if not self.is_available():
            return {"ok": False, "message": self.unavailable_reason()}
        if not self.is_downloaded(model_id):
            d = self.local_dir(model_id)
            return {"ok": False, "message": f"模型未下载。请先拉取（目标目录: {d}）"}
        if self._pipe is not None and self._loaded_id == model_id:
            return {"ok": True, "message": "已加载"}

        try:
            import torch
            from diffusers import DiffusionPipeline

            spec = VIDEO_MODELS[model_id]
            d = self.local_dir(model_id)
            tun = tuned_for(model_id)
            # ★ 显存策略由 memory_policy 统一决策（V4.40.24 收口，W1）。
            #   SVD 定稿结论仍是 model_offload（实测又稳又快，见文件顶部 ②）；
            #   别改成「8GB 装得下就不 offload」——10 帧实测会分页卡死。
            from app.core.neural.memory_policy import (
                MODE_SEQUENTIAL_OFFLOAD,
                MODE_WHOLE_GPU,
                pick_memory_policy,
            )

            pol = pick_memory_policy(
                model_id, frames=frames, tuned=tun, registered_vram_gb=spec.get("vram_gb")
            )
            _offload_state = {"label": "none"}

            def _build_pipe():
                kwargs: Dict[str, Any] = {"torch_dtype": torch.float16, "use_safetensors": True}
                if model_id == "svd-xt-i2v":
                    kwargs["variant"] = "fp16"
                p = DiffusionPipeline.from_pretrained(d, **kwargs)
                if pol["mode"] != MODE_WHOLE_GPU:
                    try:
                        if pol["mode"] == MODE_SEQUENTIAL_OFFLOAD:
                            p.enable_sequential_cpu_offload()
                            _offload_state["label"] = "sequential"
                        else:
                            p.enable_model_cpu_offload()
                            _offload_state["label"] = "model"
                    except Exception:
                        logger.debug("[video_gen] cpu offload 不可用，直接上卡", exc_info=True)
                        p = p.to("cuda")
                        _offload_state["label"] = "none"
                else:
                    p = p.to("cuda")
                    _offload_state["label"] = "none"
                # ★ offload 实际状态随管线走：缓存命中时 loader 不执行，
                #   必须从管线对象上读回「建它的人启用了什么」，否则会误报 none。
                p._sg_offload_mode = _offload_state["label"]
                return p

            # ★ M3 驻留合一（统一引擎，2026-10-24）：svd 与 ③ local_video_infer._infer_svd
            #   共用进程级缓存（同 key = ("svd", abspath(同一目录)，两侧解析已实测相等)）
            #   ⇒ 两条实现不再各持一份 4.2GB（此前顺序使用会双驻留 8.4GB）。
            #   loader 只在未命中时执行；offload 语义两侧一致（都 model_offload，实测定稿）。
            #   其余模型（未下载/未验证）维持单槽行为，不扩大改动面。
            if model_id == "svd-xt-i2v":
                from app.core import local_video_pipe_cache as VPC

                pipe, src = VPC.get_or_load(("svd", os.path.abspath(d)), _build_pipe)
                self._shared_key = ("svd", os.path.abspath(d))
            else:
                pipe, src = _build_pipe(), "miss"
                self._shared_key = None
            # 命中共享缓存时 loader 没跑过 ⇒ 以管线对象上标注的实际 offload 为准。
            self._offload = getattr(pipe, "_sg_offload_mode", _offload_state["label"])
            self._tuned = tun
            self._memory_policy = pol
            for _r in pol.get("reasons", []):
                logger.info("[video_gen] 显存策略: %s", _r)

            self._pipe = pipe
            self._loaded_id = model_id
            logger.info(
                "[video_gen] 已加载 %s（%s·%s）· offload=%s（frames=%s）· steps=%s · chunk=%s",
                model_id,
                spec["label"],
                "共享缓存命中" if src == "hit" else "新载入",
                self._offload,
                frames,
                tun["steps"],
                tun["decode_chunk_size"],
            )
            return {
                "ok": True,
                "pipe_source": src,
                "message": f"已加载 {spec['label']}（offload={self._offload}"
                + ("·复用常驻管线）" if src == "hit" else "）"),
            }
        except Exception as e:
            logger.debug("[video_gen] load 失败", exc_info=True)
            self._pipe = None
            self._loaded_id = ""
            return {"ok": False, "message": f"加载失败：{type(e).__name__}: {e}"}

    def unload(self) -> None:
        """释放显存。M3：svd 走共享缓存后，这里必须连带 evict ——
        只断 self._pipe 引用而缓存还持着，「卸载」就是假的（weakref 实测过这条链）。"""
        self._pipe = None
        self._loaded_id = ""
        k = getattr(self, "_shared_key", None)
        self._shared_key = None
        if k is not None:
            try:
                from app.core import local_video_pipe_cache as VPC

                VPC.evict(k)
            except Exception:  # stability-gate: allow-swallow（evict 失败最坏是缓存多留一条管线，下次 LRU/让位仍会收；卸载语义已在本侧完成）
                logger.debug("[video_gen] 共享缓存 evict 失败", exc_info=True)
        # 卸载序列收口（gc → synchronize → empty_cache）：evict 成功时内部已跑过一次，
        # 此处是幂等收尾——evict 失败时本路径就是唯一回收点（self._pipe 引用已断）。
        try:
            from app.core.neural.inference_cache import release_vram_sequence

            release_vram_sequence()
        except Exception:  # stability-gate: allow-swallow（回收失败最坏是显存晚一步释放，不影响引用已断的事实）
            logger.debug("[video_gen] unload 回收序列失败", exc_info=True)

    # ── 步缓存挂载/摘除（P0-1，app/core/neural/inference_cache.py）──────────
    def _attach_step_cache(self, arch: str, quality: str) -> Any:
        """按门控结果挂步缓存并激活；未开/失败一律返回 None（生成路径零感知）。

        质量档位传**原始** quality（空串=默认档≈balanced，不在白名单 ⇒ 不开，
        与「默认关、显式开」一致；未知档名同样不开——不猜用户意图）。
        """
        try:
            from app.core.neural.inference_cache import (
                LowRankFeatureCache, StepFeatureCache, cache_gate, default_pool,
            )

            gate = cache_gate(arch=arch, preset=quality, component="step_cache")
            if not gate["ok"]:
                logger.debug("[video_gen] 步缓存未启用：%s", "；".join(gate["reasons"]))
                return None
            p = gate["params"]
            pool = None
            if p["pool"]:
                try:
                    import torch

                    pool = default_pool(device="cuda" if torch.cuda.is_available()
                                        else "cpu")
                except Exception:  # stability-gate: allow-swallow（池建不出 ⇒ 不用池，缓存照常）
                    logger.debug("[video_gen] 缓存池创建失败（按无池继续）", exc_info=True)
            lowrank = (LowRankFeatureCache(p["lowrank"]) if p["lowrank"] > 0 else None)
            sc = StepFeatureCache()
            rep = sc.attach(self._pipe, arch=arch, interval=p["interval"],
                            branch_id=p["branch_id"], pool=pool, lowrank=lowrank)
            if not rep["ok"]:
                logger.info("[video_gen] 步缓存挂载失败（按不启用继续）：%s",
                            "；".join(rep["reasons"]))
                return None
            sc.activate()
            logger.info("[video_gen] 步缓存已激活：%s", "；".join(rep["reasons"]))
            return sc
        except Exception:  # stability-gate: allow-swallow（缓存层任何异常都不得影响出片）
            logger.debug("[video_gen] 步缓存挂载异常（按不启用处理）", exc_info=True)
            return None

    def _detach_step_cache(self, sc: Any) -> None:
        """摘除步缓存并落遥测日志（detach 内部保证 forward 全还原 + 缓存全释放）。"""
        if sc is None:
            return
        try:
            st = sc.detach()
            logger.info("[video_gen] 步缓存遥测：full=%d reuse=%d hits=%d "
                        "fallback=%d skip=%.2f cached=%.1fMB",
                        st["full_steps"], st["reuse_steps"], st["reuse_hits"],
                        st["reuse_fallbacks"], st["skip_ratio"],
                        st["cached_bytes"] / 1048576.0)
        except Exception:  # stability-gate: allow-swallow（detach 失败最坏是缓存晚一步释放）
            logger.debug("[video_gen] 步缓存 detach 异常", exc_info=True)

    def generate(
        self,
        model_id: str,
        *,
        prompt: str = "",
        image_path: str = "",
        seconds: float = 2.0,
        fps: int = 7,
        seed: int = 0,
        out_path: str = "",
        steps: int = 0,
        quality: str = "",
        motion: str = "",
    ) -> Dict[str, Any]:
        """生成视频。**不自动下载模型**；未加载会先尝试加载。

        `quality`（质量/速度档，基于实测）：
          "fast"=10 步（2.14x）· "balanced"=14 步（1.74x，**默认**）· "best"=25 步（原默认）
        `steps`：直接指定步数，>0 时覆盖 `quality`。

        `motion`（运动幅度档，★ 影响**画质**）：
          "calm"=80（**默认**，漫剧/立绘主体 6 帧全程稳定）
          "normal"=127（SVD 原默认）· "lively"=180（运动大但形变风险高）

        诚实失败：返回 ``{ok:False, message}`` 并说明**具体缺什么**。
        """
        spec = VIDEO_MODELS.get(model_id)
        if not spec:
            return {"ok": False, "message": f"未知模型 id: {model_id}"}
        if "i2v" in spec["modes"] and not image_path:
            return {"ok": False, "message": f"{spec['label']} 是图生视频，必须提供 image_path"}
        if "t2v" in spec["modes"] and not prompt and not image_path:
            return {"ok": False, "message": "需要 prompt 或 image_path"}

        tun = tuned_for(model_id)
        # 档位解析：显式 steps 优先；档位名未知时退回默认并如实提示
        n_steps = (
            int(steps) if int(steps) > 0 else int(QUALITY_PRESETS.get(quality or "", tun["steps"]))
        )
        n_mb = int(MOTION_PRESETS.get(motion or "", tun.get("motion_bucket_id", 127)))
        n_frames = max(2, int(round(seconds * fps)))

        # ★ 先把帧数交给 load：offload 的取舍依赖帧数（见文件顶部 ② 实测）。
        #   load() 自带幂等 + 需要切换装载方式时自动重载，所以这里无条件调用。
        r = self.load(model_id, frames=n_frames)
        if not r.get("ok"):
            return {"ok": False, "message": r.get("message") or "加载失败"}

        try:
            import time as _time

            t_gen0 = _time.time()
            import imageio.v3 as iio
            import numpy as np
            import torch

            # ★ CFG：**蒸馏与否决定取值**（2026-10-02）
            #   · 未蒸馏基模（默认）：必须 CFG>1，关掉出废片（实测首帧保持 35→16dB）
            #   · 步数蒸馏权重：**训练时就是无 CFG 的** ⇒ 必须 =1.0，否则反而劣化
            _is_distilled = bool(tun.get("distilled"))
            # ★ chunk 由 memory_policy 决策（V4.40.24 收口）：
            #   load() 已按同一帧数算出策略，直接复用（单一决策点，不重复计算）。
            #   SVD 实测必须 1（比 2 快约 6 倍且更省显存）。
            _chunk = int(self._memory_policy.get("decode_chunk_size") or tun["decode_chunk_size"])
            kw: Dict[str, Any] = {
                "num_frames": n_frames,
                "decode_chunk_size": _chunk,
                "num_inference_steps": n_steps,
                "min_guidance_scale": 1.0 if _is_distilled else float(tun.get("cfg_min", _CFG_MIN)),
                "max_guidance_scale": 1.0 if _is_distilled else float(tun.get("cfg_max", _CFG_MAX)),
                # 运动幅度：漫剧素材取 calm(80) 明显更稳（实测）
                "motion_bucket_id": n_mb,
                "noise_aug_strength": float(tun.get("noise_aug_strength", 0.02)),
            }
            if seed:
                kw["generator"] = torch.manual_seed(int(seed))
            # ★ P0-1 步缓存（DeepCache）：默认关，SHIGUANG_STEP_CACHE=deepcache 显式开。
            #   arch 由 pipeline 类名推导（SVD ⇒ "svd"）；未来 Wan 等 DiT 不在白名单，
            #   门控自动拒（DiT 的对应物是 diffusers 内置 FBCache，属后续探针，不冒充）。
            _sc_arch = ("svd" if "StableVideoDiffusion"
                        in str(spec.get("pipeline") or "") else "")
            step_cache = self._attach_step_cache(_sc_arch, quality)
            try:
                if image_path:
                    if not os.path.isfile(image_path):
                        return {"ok": False, "message": f"输入图不存在: {image_path}"}
                    img = iio.imread(image_path)
                    if img.ndim == 2:
                        img = np.stack([img] * 3, axis=-1)
                    # ★ diffusers 的 SVD 管道只接受 PIL.Image / torch.Tensor，
                    #   **不接受 numpy**（实测报 ValueError: `image` has to be of type ...）
                    from PIL import Image as _PILImage

                    kw["image"] = _PILImage.fromarray(img[:, :, :3])
                    frames = self._pipe(**kw).frames[0]
                else:
                    kw["prompt"] = prompt
                    frames = self._pipe(**kw).frames[0]
            finally:
                self._detach_step_cache(step_cache)

            if not out_path:
                out_path = os.path.join("短剧AI剪辑输出", f"video_{model_id}_{int(seed)}.mp4")
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            # ★ diffusers 返回的是 **list[PIL.Image]**，不是 numpy 数组。
            #   直接丢给 imageio 会报 `'Image' object has no attribute 'shape'`（实测踩过）。
            arr = _to_uint8_array(frames)
            if arr is None:
                return {"ok": False, "message": "生成结果无法转成视频帧（非预期类型）"}
            # 显式用 FFMPEG 插件（imageio_ffmpeg 已随项目安装），
            # 不让 imageio 自己猜插件，避免在无 pyav 的机器上静默选错。
            iio.imwrite(out_path, arr, fps=int(fps), plugin="FFMPEG", codec="libx264")
            # 落画布 inbox ⇒ 前端拿到的是**能直接播的 URL**（WebView 读不了本地路径）。
            # 落箱失败不影响产物本身：video_path 仍然有效，只是前端播不了。
            published = publish_to_inbox(out_path)
            elapsed = _time.time() - t_gen0
            return {
                "ok": True,
                "path": out_path,
                "frames": len(frames),
                "video_path": out_path,
                "video_url": published.get("url", ""),
                "inbox_path": published.get("inbox_path", ""),
                # 把实测参数与耗时一并回传：用户能直接看到快了多少
                "steps": n_steps,
                "motion_bucket_id": n_mb,
                "offload": self._offload or "none",
                "seconds_elapsed": round(elapsed, 1),
                "s_per_frame": round(elapsed / max(1, len(frames)), 2),
                "message": f"生成完成：{out_path}（{n_steps} 步 · motion {n_mb} · "
                f"{elapsed:.0f}s · {elapsed / max(1, len(frames)):.1f}s/帧）",
            }
        except torch.cuda.OutOfMemoryError:
            self.unload()
            return {"ok": False, "message": "显存不足（OOM）。请缩短时长/降低帧数，或换更小模型。"}
        except Exception as e:
            logger.debug("[video_gen] generate 失败", exc_info=True)
            return {"ok": False, "message": f"生成失败：{type(e).__name__}: {e}"}


def write_data_url(data_url: str, dest_dir: str, name_hint: str = "input") -> Optional[str]:
    """把 data URL（画布传图的方式）落成临时文件，返回路径。失败返回 None。

    为什么要落盘而不是直接把字节喂给管道：diffusers 的 i2v 管道入口是
    **文件/PIL**，且 `generate()` 的对外契约就是 `image_path`（保持一个入口，
    避免「内存里传 PIL」和「传路径」两条并行实现 —— 那正是本项目一直在避免的反模式）。
    """
    if not data_url or not isinstance(data_url, str):
        return None
    m = _DATA_URL_RE.match(data_url.strip())
    if not m:
        return None
    try:
        import base64

        raw = base64.b64decode(m.group(1), validate=False)
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, f"_{name_hint}_input.png")
        with open(path, "wb") as f:
            f.write(raw)
        return path
    except Exception:
        logger.debug("[video_gen] data URL 落盘失败", exc_info=True)
        return None


def publish_to_inbox(video_path: str, name: str = "") -> Dict[str, str]:
    """把生成的视频落到**画布 inbox**，返回 WebView 能播的 URL。

    为什么必须落箱：画布跑在 **WebView** 里，**加载不了 `D:\\...` 这种本地路径**；
    bridge 只把 `canvas_bridge.canvas_inbox_dir()` 下的文件以 `/inbox_file/<name>`
    暴露出来。不落箱的话前端拿到路径也播不了 —— 这正是「差最后一步」的那个缺口。

    端口与目录**复用项目既有约定**（与 `comfy_provider` / `pose_extract_service` /
    `yue_music` 同一套：`canvas_bridge.DEFAULT_PORT` + `canvas_inbox_dir()`）。
    ⚠️ `canvas_bridge.py` 属冻结区 `stage3d-core` —— 这里**只 import，绝不改它**。

    失败返回 `{}`（诚实失败，不编造 URL）。
    """
    try:
        import shutil
        import time
        from urllib.parse import quote

        from app.core.canvas_bridge import DEFAULT_PORT, canvas_inbox_dir

        if not video_path or not os.path.isfile(video_path):
            return {}
        inbox = canvas_inbox_dir()
        os.makedirs(inbox, exist_ok=True)
        safe = name or f"{int(time.time())}_{os.path.basename(video_path)}"
        dest = os.path.join(inbox, safe)
        # 已在 inbox 内就不重复拷（避免自拷自）
        if os.path.abspath(dest) != os.path.abspath(video_path):
            shutil.copy2(video_path, dest)
        return {
            "inbox_name": safe,
            "inbox_path": dest,
            "url": f"http://127.0.0.1:{int(DEFAULT_PORT)}/inbox_file/{quote(safe)}",
        }
    except Exception:
        logger.debug("[video_gen] 落画布 inbox 失败", exc_info=True)
        return {}


def _to_uint8_array(frames) -> Any:
    """把 diffusers 的产物统一成 `(N,H,W,3) uint8`，供 imageio 落盘。

    兼容三种形态：
      - `list[PIL.Image]`（SVD / diffusers 常见）← **实测就是这个**
      - `np.ndarray`（已经是数组）
      - `torch.Tensor`（(N,C,H,W) 或 (N,H,W,C)）
    不可识别时返回 None（调用方如实报错，不硬编）。
    """
    try:
        import numpy as np

        if isinstance(frames, np.ndarray):
            arr = frames
        elif isinstance(frames, (list, tuple)) and frames:
            first = frames[0]
            if hasattr(first, "convert"):  # PIL.Image
                arr = np.stack([np.asarray(f.convert("RGB")) for f in frames])
            else:
                arr = np.stack([np.asarray(f) for f in frames])
        elif hasattr(frames, "detach"):  # torch.Tensor
            t = frames.detach().cpu().numpy()
            if t.ndim == 4 and t.shape[1] in (1, 3):  # (N,C,H,W) → (N,H,W,C)
                t = np.transpose(t, (0, 2, 3, 1))
            arr = t
        else:
            return None
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        if arr.ndim == 4 and arr.shape[-1] == 4:  # 丢 alpha
            arr = arr[..., :3]
        return arr if arr.ndim == 4 else None
    except Exception:
        logger.debug("[video_gen] 帧数组转换失败", exc_info=True)
        return None


_engine: Optional[VideoGenEngine] = None


def get_video_engine() -> VideoGenEngine:
    """进程级单例。"""
    global _engine
    if _engine is None:
        _engine = VideoGenEngine()
    return _engine
