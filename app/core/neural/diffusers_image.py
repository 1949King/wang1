# -*- coding: utf-8 -*-
"""图像生成引擎（**自研通道**，diffusers 栈） —— 一个月路线图刀1（2026-10-03）

为什么要有这个模块
==================
V4.40.22 裁定「主选 DiffSynth / 备选自研」；V4.40.26 主选图像落地（`diffsynth_image`）。
但主备制的终局是**自研达标后升为主用**（一个月路线图 M1~M5），而自研侧图像能力为 0 ——
若自研没有图像，切回后每个图像请求都成「常态降级到备选」，违反 R9 精神。

本模块是自研侧的**第一块图像拼图**，与对岸 `diffsynth_image.py` **契约逐键对齐**
（同注册表形态 / 同方法签名 / 同返回键集合），使双栈可互换、可对比。
刀2（2026-10-03）扩到第二族 **SDXL 1.0**（双 tokenizer / 双 text_encoder），
并成为 `layer_cpu_offload`（`layer_offload.py`，block 组逐层卸载）的首个落地引擎 ——
通过 ``supported_modes=ACTIVE_MODES`` 向 memory_policy 声明四档全实现。

三个关键设计
============
1. **零新下载**：复用 V4.40.26 已下载的 SD1.5 一体化 safetensors（3.97GB）。
   diffusers 0.40 的 ``StableDiffusionPipeline.from_single_file()`` 可直接加载
   **同一个文件**（注册表 ms_repo/ms_file 与对岸一致 ⇒ local_file 指向同一路径）。
2. **M1/M2 对比基准**：同权重、同 prompt/seed/步数，双栈各跑一次 ⇒
   一个月路线图的 M1（峰值显存 ≤110%）/ M2（耗时 ≥80%）第一次有真实数字。
   ⚠️ 两栈噪声生成器不同（diffusers cpu Generator vs DiffSynth cuda generate_noise），
   **同 seed 出图不像素一致** —— 对比的是显存/耗时/质量观感，不是像素对齐。
3. **显存策略走 memory_policy**（W1 收口成果复用）：SD1.5 登记 3.0GB < 95% 水位
   ⇒ 定稿 model_offload（与 SVD 结论一致）；对比脚本另测 whole_gpu 供演进参考。

纪律（与 video_gen / diffsynth_image 一致）
============================================
1. **诚实失败**：缺模型/缺依赖/CUDA 不可用 → 返回 ok=False + 具体原因，绝不返回占位图。
2. **绝不抛异常**：所有对外方法异常一律吞掉记日志，返回 ok=False。
3. **不自动下载**：``generate()`` 不触发下载；必须显式 ``pull()``。
4. **绝不真 import diffusers 于探测路径**（2026-10-01/10-02 两次组合场景硬崩）：
   ``is_available`` 只做 find_spec + import torch；真 import 只发生在 load() 内部。
5. 下载走 ModelScope（与对岸同一通道）；落盘目录同一约定 ⇒ **天然复用已下载权重**。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ────────────────────── 模型注册表（唯一真源）──────────────────────
# ★ ms_repo/ms_file 与 diffsynth_image.IMAGE_MODELS **刻意一致**：
#   local_file() 因此指向**同一个权重文件**（3.97GB 已下载），双栈共享、零复制。
# ★ 只登记**已验证可跑**的模型（诚实原则：不登记没实测过的）。
DIFFUSERS_IMAGE_MODELS: Dict[str, Dict[str, Any]] = {
    "sd15-t2i": {
        "label": "Stable Diffusion 1.5（文生图·自研栈）",
        "arch": "sd15",
        "ms_repo": "AI-ModelScope/stable-diffusion-v1-5",
        "ms_file": "v1-5-pruned-emaonly.safetensors",   # 一体化：UNet+CLIP+VAE
        "size_gb": 3.97,
        "params": "0.9B",
        # ★ from_single_file 全离线三件套（2026-10-03 探测定稿，probe_from_single_file.py）：
        #   a) original_config = v1-inference.yaml（LatentDiffusion 结构定义，1.9KB）
        #   b) config = 权重同目录（pipeline 组件 config，仓库布局，~1.6MB 共 8 文件）
        #   c) safety_checker=None + feature_extractor=None（transformers 5.x 已删
        #      CLIPFeatureExtractor；且 t2i/i2i 推理本不需要这两组件）
        #   缺任何一件，diffusers 都会去 HF Hub 拉取 —— 本机代理 502 实测炸加载。
        "original_config": "v1-inference.yaml",
        "config_files": [   # ★ 单一真源（仓库相对路径）：pull 拉取清单 / 下载校验清单共用
            "model_index.json",
            "scheduler/scheduler_config.json",
            "tokenizer/tokenizer_config.json",
            "tokenizer/vocab.json",
            "tokenizer/merges.txt",
            "tokenizer/special_tokens_map.json",
            "text_encoder/config.json",
            "feature_extractor/preprocessor_config.json",
        ],
        "modes": ["t2i", "i2i"],
        "native_size": 512,             # SD1.5 原生分辨率
        "steps": 20,
        "cfg": 7.5,
        "vram_gb": 3.0,
        "ram_gb": 4.5,
        "license": "CreativeML OpenRAIL-M",
        "note": "自研栈首图；与主选共享同一权重文件（from_single_file 直载）",
    },
    # ── 刀2（2026-10-03）：SDXL 1.0，双栈同步登记（ms_repo/ms_file 与对岸一致）──
    "sdxl-t2i": {
        "label": "Stable Diffusion XL 1.0（文生图·自研栈）",
        "arch": "sdxl",                 # load() 按 arch 选 StableDiffusionXLPipeline
        "ms_repo": "AI-ModelScope/stable-diffusion-xl-base-1.0",
        "ms_file": "sd_xl_base_1.0.safetensors",   # 一体化：UNet+双CLIP+VAE（6.46GiB）
        "size_gb": 6.46,                # 6,938,078,334B（2026-10-03 ModelScope API 实测）
        "params": "3.5B",               # UNet 2.6B + TE-G 0.7B + TE-L 0.12B + VAE 0.08B
        # ★ from_single_file 全离线三件套（同 sd15 定稿，复用 diffusers-single-file-offline 技能）：
        #   a) original_config = sd_xl_base.yaml（SGM DiffusionEngine 结构定义，2.8KB，
        #      仓库没有 —— 从 Stability-AI/generative-models 经 jsdelivr 直连落盘）
        #   b) config = 权重同目录（组件 config，仓库布局，14 文件 —— SDXL 是
        #      **双 tokenizer / 双 text_encoder**，清单与 SD1.5 不同勿照抄；
        #      仓库无 feature_extractor/，反正 load 跳该组件，不登记）
        #   c) safety_checker=None + feature_extractor=None（同 sd15 理由）
        "original_config": "sd_xl_base.yaml",
        # ★ 第二来源（刀 A1，2026-10-04）：ModelScope 权重仓库**不发货** yaml，
        #   allow_patterns 拉不到 ⇒ 换机从头 provisioning 时 is_downloaded 恒 False。
        #   pull() 在 ModelScope 拉取后若 yaml 仍缺，则从此 URL 直连补拉（jsdelivr，
        #   与 2026-10-03 手工落盘的来源一致；sd15 的 v1-inference.yaml 仓库有，不需要）。
        "original_config_url": ("https://cdn.jsdelivr.net/gh/Stability-AI/generative-models"
                                "@main/configs/inference/sd_xl_base.yaml"),
        "config_files": [   # ★ 单一真源（仓库相对路径）：pull 拉取清单 / 下载校验清单共用
            "model_index.json",
            "scheduler/scheduler_config.json",
            "unet/config.json",
            "vae/config.json",
            "text_encoder/config.json",
            "text_encoder_2/config.json",
            "tokenizer/tokenizer_config.json",
            "tokenizer/vocab.json",
            "tokenizer/merges.txt",
            "tokenizer/special_tokens_map.json",
            "tokenizer_2/tokenizer_config.json",
            "tokenizer_2/vocab.json",
            "tokenizer_2/merges.txt",
            "tokenizer_2/special_tokens_map.json",
        ],
        "modes": ["t2i", "i2i"],
        "native_size": 1024,            # SDXL 原生分辨率
        "steps": 20,
        "cfg": 7.5,
        # fp16 权重全量 ≈7.0GB + 激活余量（展示/决策输入；mode 选择由 prefer_mode 主导）。
        "vram_gb": 7.0,
        "ram_gb": 9.0,                  # 权重 7.0GB + 加载转换开销（暂定）
        # ★ 四档实测定稿（2026-10-03 bench_sdxl_modes.py，20 步 1024² fp16 同参，
        #   R2/R3 受控两轮复现：每档前冷却 + nvidia-smi 遥测）：
        #   whole_gpu  420s 墙钟超时已杀（WDDM 分页卡死，R1）
        #   model      5.21GB / 27.9s ← 定稿（速度 2.2× 胜 sequential，5.21GB 在 8GB 卡
        #             65% 水位可接受。⚠️ R1 曾测出 220s —— 是被 420s 硬杀的 whole_gpu
        #             污染的僵尸 CUDA 状态，受控复测证伪）
        #   sequential 3.76GB / 61.6s（更省显存但慢 2.2×，留作 6GB 卡备选）
        #   layer_cpu  3.96GB（装载峰 6.57 单列）/ 72.7s（v1 两轴皆未胜 ⇒ 留档）
        "prefer_mode": "model_offload",
        "license": "CreativeML OpenRAIL++-M",
        "note": "刀2 自研第二族；四档实测定稿 model_offload（R1 污染数据已排除）；与主选共享权重",
    },
}


def available_models() -> List[Dict[str, Any]]:
    """列出可选图像模型（供 UI/决策层渲染；与对岸同构）。"""
    out = []
    for mid, spec in DIFFUSERS_IMAGE_MODELS.items():
        out.append({
            "id": mid,
            "label": spec["label"],
            "params": spec["params"],
            "modes": list(spec["modes"]),
            "download_gb": spec["size_gb"],
            "vram_gb": spec["vram_gb"],
            "ram_gb": spec["ram_gb"],
            "native_size": spec["native_size"],
            "note": spec["note"],
            "license": spec["license"],
        })
    return out


class DiffusersImageEngine:
    """自研图像生成引擎（diffusers 栈）。**模型不自动下载**，须先 `pull()`。"""

    def __init__(self) -> None:
        self._pipe = None
        self._pipe_i2i = None     # AutoPipelineForImage2Image.from_pipe 共享组件（懒建）
        self._loaded_id = ""
        self._offload = ""
        self._memory_policy: Dict[str, Any] = {}

    # ── 能力探测（不加载模型）──────────────────────

    @staticmethod
    def is_available() -> bool:
        """diffusers + torch + CUDA 是否齐备。

        ★ 只做 find_spec，**绝不真 import diffusers**（组合场景硬崩 ×2 血泪：
        重型推理库在 pytest 全量环境下 import 会把进程搞崩，且单跑侥幸不崩）。
        """
        import importlib.util as _u
        for mod in ("torch", "diffusers"):
            if _u.find_spec(mod) is None:
                return False
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            logger.debug("[diffusers_image] CUDA 探测失败", exc_info=True)
            return False

    @staticmethod
    def unavailable_reason() -> str:
        """不可用时给出**具体**原因。同样**不真 import diffusers**。"""
        import importlib.util as _u
        if _u.find_spec("torch") is None:
            return "未安装 torch"
        if _u.find_spec("diffusers") is None:
            return "未安装 diffusers（自研栈依赖，项目基线应已具备）"
        try:
            import torch
            if not torch.cuda.is_available():
                return "已装依赖但 CUDA 不可用（扩散推理会极慢或不可行）"
        except Exception:
            return "torch 探测异常"
        return ""

    # ── 本地是否已下载 ─────────────────────────────

    @staticmethod
    def local_dir(model_id: str) -> str:
        spec = DIFFUSERS_IMAGE_MODELS.get(model_id) or {}
        repo = (spec.get("ms_repo") or model_id).replace("/", "_")
        return os.path.join("app", "models", "cache", repo)

    @staticmethod
    def local_file(model_id: str) -> str:
        spec = DIFFUSERS_IMAGE_MODELS.get(model_id) or {}
        return os.path.join(DiffusersImageEngine.local_dir(model_id),
                            spec.get("ms_file") or "")

    @staticmethod
    def local_config_file(model_id: str) -> str:
        """original_config（v1-inference.yaml）的本地路径（权重同目录，可为空串）。"""
        spec = DIFFUSERS_IMAGE_MODELS.get(model_id) or {}
        name = spec.get("original_config") or ""
        return os.path.join(DiffusersImageEngine.local_dir(model_id), name) if name else ""

    @staticmethod
    def is_downloaded(model_id: str) -> bool:
        f = DiffusersImageEngine.local_file(model_id)
        # 1GB 以下视为残件（SD1.5 一体权重 3.97GB）
        weights_ok = bool(f) and os.path.isfile(f) and os.path.getsize(f) > 1e9
        # ★ original_config 缺失 ⇒ from_single_file 会联网拉取（本机代理 502 必炸），
        #   视为「未完整下载」，由 pull() 补拉（诚实原则：不抱着半套文件硬上）。
        c = DiffusersImageEngine.local_config_file(model_id)
        config_ok = (not c) or (os.path.isfile(c) and os.path.getsize(c) > 500)
        # ★ pipeline 组件 config 同理（仓库布局，与权重同目录；缺了会在
        #   "Loading pipeline components" 阶段联网）。精确清单避免拉大权重文件。
        spec = DIFFUSERS_IMAGE_MODELS.get(model_id) or {}
        base = DiffusersImageEngine.local_dir(model_id)
        for rel in spec.get("config_files", []):
            p = os.path.join(base, rel)
            if not (os.path.isfile(p) and os.path.getsize(p) > 0):
                config_ok = False
                break
        return weights_ok and config_ok

    @staticmethod
    def downloaded_bytes(model_id: str) -> int:
        tot = 0
        d = DiffusersImageEngine.local_dir(model_id)
        for root, _dirs, files in os.walk(d):
            for f in files:
                try:
                    tot += os.path.getsize(os.path.join(root, f))
                except OSError:  # stability-gate: allow-swallow（逐文件累加体积只为展示估计值；文件在 walk 途中消失(OSError)无需诊断）
                    pass
        return tot

    # ── 拉取（ModelScope 通道，与对岸一致）─────────

    def pull(self, model_id: str,
             progress_cb: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """下载模型到 `app/models/cache/<repo>/`。异常绝不外抛。

        与对岸共享同一目标路径 ⇒ 任一侧下载完成，两侧 ``is_downloaded`` 都为真。
        """
        spec = DIFFUSERS_IMAGE_MODELS.get(model_id)
        if not spec:
            return {"ok": False, "model_id": model_id,
                    "message": f"未知模型 id（可选：{', '.join(DIFFUSERS_IMAGE_MODELS)}）"}
        if self.is_downloaded(model_id):
            return {"ok": True, "model_id": model_id, "path": self.local_file(model_id),
                    "bytes": self.downloaded_bytes(model_id),
                    "message": "已在本机，无需重复下载（双栈共享同一文件）"}
        try:
            from modelscope import snapshot_download
            if progress_cb:
                progress_cb(f"开始下载 {spec['label']}（{spec['size_gb']}GB，ModelScope）")
            # ★ 权重 + original_config + 组件 config 三件套一起拉
            #   （缺任何一件 from_single_file 都会联网，本机代理 502 必炸）。
            #   config_files 全是仓库相对路径的**精确小文件**（绝不写 text_encoder/*
            #   这种目录通配 —— 会把子目录里几百 MB 的分散权重也拉下来）。
            patterns = [spec["ms_file"]] + ([spec["original_config"]]
                                            if spec.get("original_config") else [])
            patterns += list(spec.get("config_files", []))
            try:
                path = snapshot_download(spec["ms_repo"], local_dir=self.local_dir(model_id),
                                         allow_patterns=patterns)
            except TypeError:
                path = snapshot_download(spec["ms_repo"], local_dir=self.local_dir(model_id),
                                         allow_file_pattern=patterns)
        except Exception as e:
            logger.debug("[diffusers_image] pull 异常", exc_info=True)
            return {"ok": False, "model_id": model_id, "message": f"{type(e).__name__}: {e}"}
        # ★ original_config 第二来源补拉（刀 A1）：权重仓库不发货 yaml 时
        #   （SDXL 的 sd_xl_base.yaml），ModelScope 拉完仍缺 ⇒ 直连注册表
        #   original_config_url 补拉；补不到则诚实失败（绝不抱着半套文件硬上）。
        cfg_path = self.local_config_file(model_id)
        cfg_url = str(spec.get("original_config_url") or "")
        if cfg_path and cfg_url and not (
                os.path.isfile(cfg_path) and os.path.getsize(cfg_path) > 500):
            if progress_cb:
                progress_cb("权重仓库未附带 original_config，直连第二来源补拉…")
            ok_fetch = False
            try:
                import urllib.request
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(cfg_url, timeout=30) as resp:
                            data = resp.read()
                        if len(data) > 500:
                            os.makedirs(os.path.dirname(os.path.abspath(cfg_path)),
                                        exist_ok=True)
                            with open(cfg_path, "wb") as f:
                                f.write(data)
                            ok_fetch = True
                            break
                    except Exception:
                        logger.debug("[diffusers_image] original_config 补拉第 %d 次失败",
                                     attempt + 1, exc_info=True)
            except Exception:
                logger.debug("[diffusers_image] original_config 补拉异常", exc_info=True)
            if not ok_fetch:
                return {"ok": False, "model_id": model_id,
                        "message": f"original_config 补拉失败（{cfg_url}）；"
                                   f"可手工下载放到 {cfg_path}"}
            logger.info("[diffusers_image] original_config 已从第二来源落盘: %s", cfg_path)
        if not path or not self.is_downloaded(model_id):
            return {"ok": False, "model_id": model_id,
                    "message": "下载未落盘完整权重（ModelScope 通道失败）"}
        return {"ok": True, "model_id": model_id, "path": self.local_file(model_id),
                "bytes": self.downloaded_bytes(model_id), "message": "下载完成"}

    # ── 加载 / 生成 / 卸载 ─────────────────────────

    def load(self, model_id: str) -> Dict[str, Any]:
        """加载 pipeline（**显存策略由 memory_policy 统一决策**，W1 收口成果复用）。

        SD1.5 fp16 ≈2GB 权重，登记 3.0GB < 8GB×95% 水位 ⇒ 定稿 model_offload
        （与 SVD 两次反转后的结论一致：又稳又快）。同一模型已加载则直接复用。
        异常绝不外抛。
        """
        if not self.is_available():
            return {"ok": False, "message": self.unavailable_reason()}
        if not self.is_downloaded(model_id):
            return {"ok": False,
                    "message": f"模型未下载。请先拉取（目标: {self.local_file(model_id)}）"}
        if self._pipe is not None and self._loaded_id == model_id:
            return {"ok": True, "message": "已加载"}
        try:
            import torch
            # ★ 真 import 只发生在 load 内部（探测路径只 find_spec，组合场景崩纪律）
            from diffusers import StableDiffusionPipeline, StableDiffusionXLPipeline

            spec = DIFFUSERS_IMAGE_MODELS[model_id]
            # ★ 全离线定稿组合（2026-10-03 三轮探测，probe_from_single_file.py）：
            #   config=权重同目录（组件 config）+ original_config=yaml（结构定义）
            #   + local_files_only + safety_checker/feature_extractor=None
            #   （transformers 5.x 已删 CLIPFeatureExtractor；两组件 t2i/i2i 本就不需要。
            #     内容合规由项目的合规审查层负责，不依赖推理期 safety_checker）。
            #   参数名用 original_config（0.40 起新名；original_config_file 1.0.0 将移除）。
            #   is_downloaded 已把「缺任何一件」判为未下载，走到这里三件套必然在盘上。
            # ★ 按 arch 选管道类（刀2：SDXL 双 CLIP 结构不同，类不通用）
            pipe_cls = {"sdxl": StableDiffusionXLPipeline}.get(spec.get("arch"),
                                                               StableDiffusionPipeline)
            pipe = pipe_cls.from_single_file(
                self.local_file(model_id),
                config=self.local_dir(model_id),
                original_config=(self.local_config_file(model_id) or None),
                torch_dtype=torch.float16,
                use_safetensors=True,
                local_files_only=True,
                safety_checker=None,
                feature_extractor=None,
            )

            # ★ 显存策略收口（V4.40.24 W1）：图像无帧概念，frames=0；
            #   tuned 显式传入（勿惰性解析视频调优表 —— 那是给 SVD 的）。
            # ★ supported_modes=ACTIVE_MODES：声明本引擎四档全实现（含刀2 layer_cpu_offload
            #   的 layer_offload 执行端），policy 才会把 layer 档判给我们。
            from app.core.neural.memory_policy import (
                ACTIVE_MODES, MODE_LAYER_CPU_OFFLOAD, MODE_SEQUENTIAL_OFFLOAD,
                MODE_WHOLE_GPU, pick_memory_policy)
            # tuned：注册表带 prefer_mode（四档实测结论）时一并传给 policy（分支 0 采纳）
            tuned: Dict[str, Any] = {"steps": spec["steps"], "decode_chunk_size": 1,
                                     "offload": True}
            if spec.get("prefer_mode"):
                tuned["prefer_mode"] = spec["prefer_mode"]
            pol = pick_memory_policy(
                model_id, frames=0,
                params_b=float(spec["params"].rstrip("B")),
                tuned=tuned,
                registered_vram_gb=spec.get("vram_gb"),
                supported_modes=ACTIVE_MODES)
            if pol["mode"] != MODE_WHOLE_GPU:
                try:
                    if pol["mode"] == MODE_SEQUENTIAL_OFFLOAD:
                        pipe.enable_sequential_cpu_offload()
                        self._offload = "sequential"
                    elif pol["mode"] == MODE_LAYER_CPU_OFFLOAD:
                        # 刀2：block 组 hook 逐层卸载（与 accelerate offload 互斥）
                        from app.core.neural.layer_offload import (
                            apply_layer_cpu_offload)
                        report = apply_layer_cpu_offload(pipe)
                        self._offload = "layer_cpu"
                        logger.info("[diffusers_image] layer_cpu_offload 挂接: %s", report)
                    else:
                        pipe.enable_model_cpu_offload()
                        self._offload = "model"
                except Exception:
                    logger.debug("[diffusers_image] cpu offload 不可用，直接上卡",
                                 exc_info=True)
                    pipe = pipe.to("cuda")
                    self._offload = "none"
            else:
                pipe = pipe.to("cuda")
                self._offload = "none"
            self._memory_policy = pol
            for _r in pol.get("reasons", []):
                logger.info("[diffusers_image] 显存策略: %s", _r)

            self._pipe = pipe
            self._pipe_i2i = None     # 换模型后 i2i 管道须重建
            self._loaded_id = model_id
            logger.info("[diffusers_image] 已加载 %s（%s）· offload=%s",
                        model_id, spec["label"], self._offload)
            return {"ok": True, "message": f"已加载 {spec['label']}（offload={self._offload}）"}
        except Exception as e:
            logger.debug("[diffusers_image] load 失败", exc_info=True)
            self._pipe = None
            self._pipe_i2i = None
            self._loaded_id = ""
            return {"ok": False, "message": f"加载失败：{type(e).__name__}: {e}"}

    def unload(self) -> None:
        """释放显存与管道引用。"""
        self._pipe = None
        self._pipe_i2i = None
        self._loaded_id = ""
        self._memory_policy = {}
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # stability-gate: allow-swallow（torch 未装/CUDA 不可用时无缓存可清；best-effort 回收，失败无后果）
            pass

    def generate(self, model_id: str, *, prompt: str = "",
                 negative_prompt: str = "", image_path: str = "",
                 width: int = 0, height: int = 0, seed: int = 0,
                 steps: int = 0, cfg: float = 0.0,
                 out_path: str = "") -> Dict[str, Any]:
        """生成图像。**不自动下载模型**；未加载会先尝试加载。

        `steps`/`cfg`/`width`/`height` 为 0 时取注册表实测默认（SD1.5: 20 步 / 7.5 / 512²）。
        返回与 `diffsynth_image.generate` **逐键对齐**的 dict（双栈可互换）。
        """
        spec = DIFFUSERS_IMAGE_MODELS.get(model_id)
        if not spec:
            return {"ok": False, "message": f"未知模型 id: {model_id}"}
        if "t2i" in spec["modes"] and not prompt.strip() and not image_path:
            return {"ok": False, "message": "文生图必须提供 prompt（或给 image_path 走图生图）"}
        if image_path and not os.path.isfile(image_path):
            return {"ok": False, "message": f"输入图不存在: {image_path}"}

        r = self.load(model_id)
        if not r.get("ok"):
            return {"ok": False, "message": r.get("message") or "加载失败"}
        try:
            import time as _time
            import torch
            t0 = _time.time()
            n_steps = int(steps) if steps else int(spec["steps"])
            n_cfg = float(cfg) if cfg else float(spec["cfg"])
            native = int(spec["native_size"])
            n_w = int(width) if width else native
            n_h = int(height) if height else native
            # ★ generator 固定在 cpu：offload 场景下设备错配会炸；
            #   且 cpu Generator 是 diffusers 可复现性的官方推荐。
            gen = torch.Generator("cpu").manual_seed(int(seed)) if seed else None

            if image_path:
                # i2i：AutoPipeline 共享 t2i 权重组件（零额外显存），懒建缓存
                from PIL import Image as _PILImage
                if self._pipe_i2i is None:
                    from diffusers import AutoPipelineForImage2Image
                    self._pipe_i2i = AutoPipelineForImage2Image.from_pipe(self._pipe)
                image = self._pipe_i2i(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    image=_PILImage.open(image_path).convert("RGB"),
                    strength=0.75,
                    guidance_scale=n_cfg,
                    num_inference_steps=n_steps,
                    generator=gen,
                ).images[0]
            else:
                image = self._pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    guidance_scale=n_cfg,
                    height=n_h,
                    width=n_w,
                    num_inference_steps=n_steps,
                    generator=gen,
                ).images[0]

            if not out_path:
                out_path = os.path.join("短剧AI剪辑输出",
                                        f"image_{model_id}_diffusers_{int(seed)}.png")
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            image.save(out_path)
            # 落画布 inbox（WebView 读不了本地路径，与 video_gen 同一机制）
            from app.core.neural.video_gen import publish_to_inbox
            published = publish_to_inbox(out_path)
            elapsed = _time.time() - t0
            return {"ok": True, "path": out_path,
                    "image_path": out_path,
                    "image_url": published.get("url", ""),
                    "inbox_path": published.get("inbox_path", ""),
                    "steps": n_steps, "cfg": n_cfg,
                    "width": n_w, "height": n_h,
                    "seconds_elapsed": round(elapsed, 1),
                    "message": f"生成完成：{out_path}（{n_steps} 步 · cfg {n_cfg} · {elapsed:.1f}s）"}
        except Exception as e:
            logger.debug("[diffusers_image] generate 失败", exc_info=True)
            return {"ok": False, "message": f"生成失败：{type(e).__name__}: {e}"}


_engine: Optional[DiffusersImageEngine] = None


def get_diffusers_image_engine() -> DiffusersImageEngine:
    """进程级单例。"""
    global _engine
    if _engine is None:
        _engine = DiffusersImageEngine()
    return _engine
