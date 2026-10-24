# -*- coding: utf-8 -*-
"""图像生成引擎（DiffSynth 主选通道） —— 主备制下**主选引擎的首个落地**（2026-10-02）

为什么是这个模块
================
V4.40.22 裁定「主选 DiffSynth / 备选自研」；V4.40.25 完成实装（可 import）。
本模块把主选**真正接进生成路径** —— 首个落地形态选 **SD1.5 文生图**，原因（当日实测）：

  - **RAM 硬墙**：Wan 系视频绑 umt5-xxl T5 = **10.58GB**，cpu_offload 需全量权重驻留
    RAM（≈13.7GB > 本机 15.3GB 总量扣 OS）—— 视频侧主选**本机不可行**（量化 T5
    双渠道无货，详见 `docs/_reports/2026-10-02-自主迭代规划与开源参照.md` §C1/C2）。
  - **图像无此墙**：SD1.5 的 CLIP 仅 0.46GB，一体化权重 3.97GB，RAM/VRAM 都无压力。
  - **补 M3 缺口**：一个月路线图要求「图像 ≥2 族（当前为 0）」，本模块是第 1 族。

与自研通道的关系
================
- 视频生成（SVD）**不动**：继续走自研 `video_gen`（本机最优，已调优 1.6x）。
- 本模块是**图像**通道；两条通道共用同一套纪律（见下）。
- 主备切换：`execution_decider.resolve_execution_engine()` 已认 `diffsynth` 为主选；
  本模块内部仍对每个方法做**诚实失败** —— 模型没下/依赖缺失一律明说，绝不返回占位图。

纪律（与 video_gen 一致）
==========================
1. **诚实失败**：缺模型/缺依赖/CUDA 不可用 → 返回 ok=False + 具体原因。
2. **绝不抛异常**：所有对外方法异常一律吞掉记日志，返回 ok=False。
3. **不自动下载**：`generate()` 不触发下载；必须显式 `pull()`。
4. **moviepy shim 前置**：import diffsynth_engine **必须**走
   `diffsynth_compat.import_diffsynth_engine()`（V4.40.25 实装排障，裸 import 必炸）。
5. **下载走 ModelScope**（diffsynth 模型的原生渠道，国内直连，**不经 HF 镜像**）；
   落盘目录沿用项目约定 `app/models/cache/<repo>/`（.gitignore 已忽略）。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ────────────────────── 模型注册表（唯一真源）──────────────────────
# size_gb 为 2026-10-02 经 ModelScope API 实测。
# ★ 只登记**已验证可跑**的模型（诚实原则：不登记没实测过的）。
IMAGE_MODELS: Dict[str, Dict[str, Any]] = {
    "sd15-t2i": {
        "label": "Stable Diffusion 1.5（文生图）",
        "arch": "sd15",
        "ms_repo": "AI-ModelScope/stable-diffusion-v1-5",
        "ms_file": "v1-5-pruned-emaonly.safetensors",   # 一体化：UNet+CLIP+VAE
        "size_gb": 3.97,
        "params": "0.9B",
        "modes": ["t2i", "i2i"],
        "native_size": 512,             # SD1.5 原生分辨率（pipeline 默认 1024 是给 SDXL 的）
        "steps": 20,
        "cfg": 7.5,
        "vram_gb": 3.0,
        "ram_gb": 4.5,
        "license": "CreativeML OpenRAIL-M",
        "note": "主选引擎首个落地模型；RAM/VRAM 均无压力（CLIP 仅 0.46GB）",
    },
    # ── 刀2（2026-10-03）：SDXL 1.0，双栈同步登记（与对岸 ms_repo/ms_file 一致）──
    "sdxl-t2i": {
        "label": "Stable Diffusion XL 1.0（文生图）",
        "arch": "sdxl",                 # load() 按 arch 选 SDXLPipelineConfig/SDXLImagePipeline
        "ms_repo": "AI-ModelScope/stable-diffusion-xl-base-1.0",
        "ms_file": "sd_xl_base_1.0.safetensors",   # 一体化：UNet+双CLIP+VAE
        "size_gb": 6.46,                # 6,938,078,334B（2026-10-03 ModelScope API 实测）
        "params": "3.5B",               # UNet 2.6B + TE-G 0.7B + TE-L 0.12B + VAE 0.08B
        "modes": ["t2i", "i2i"],
        "native_size": 1024,            # SDXL 原生分辨率
        "steps": 20,
        "cfg": 7.5,
        # fp16 权重全量 ≈7.0GB + 激活余量（暂定登记值，刀2-4 四档实测后校准）。
        # 该值落在 8GB×(60%, 95%] ⇒ 自研侧 policy 会判 layer_cpu_offload；
        # 主选侧固定 cpu_offload（DiffSynth 自有机制），本值仅作展示与决策输入。
        "vram_gb": 7.0,
        "ram_gb": 9.0,                  # 权重 7.0GB + 加载转换开销（暂定）
        "license": "CreativeML OpenRAIL++-M",
        "note": "刀2 双栈第二族；与自研侧共享同一权重文件（from_single_file 直载）",
    },
}


def available_models() -> List[Dict[str, Any]]:
    """列出可选图像模型（供 UI/决策层渲染；含体积与资源需求）。"""
    out = []
    for mid, spec in IMAGE_MODELS.items():
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


class DiffsynthImageEngine:
    """DiffSynth 图像生成引擎（主选通道）。**模型不自动下载**，须先 `pull()`。"""

    def __init__(self) -> None:
        self._pipe = None
        self._loaded_id = ""
        self._dse = None          # diffsynth_engine 模块句柄（经 compat shim 导入）

    # ── 能力探测（不加载模型）──────────────────────

    @staticmethod
    def is_available() -> bool:
        """diffsynth_engine + torch + CUDA 是否齐备。

        ★ 只做 find_spec，**绝不真 import**（2026-10-01/10-02 两次组合场景硬崩血泪：
        重型推理库在 pytest 全量环境下 import 会把进程搞崩，且单跑侥幸不崩）。
        """
        import importlib.util as _u
        for mod in ("torch", "diffsynth_engine"):
            if _u.find_spec(mod) is None:
                return False
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            logger.debug("[diffsynth_image] CUDA 探测失败", exc_info=True)
            return False

    @staticmethod
    def unavailable_reason() -> str:
        """不可用时给出**具体**原因。同样**不真 import diffsynth_engine**。"""
        import importlib.util as _u
        if _u.find_spec("torch") is None:
            return "未安装 torch"
        if _u.find_spec("diffsynth_engine") is None:
            return "未安装 diffsynth_engine（pip install diffsynth_engine，见 V4.40.25）"
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
        spec = IMAGE_MODELS.get(model_id) or {}
        repo = (spec.get("ms_repo") or model_id).replace("/", "_")
        return os.path.join("app", "models", "cache", repo)

    @staticmethod
    def local_file(model_id: str) -> str:
        spec = IMAGE_MODELS.get(model_id) or {}
        return os.path.join(DiffsynthImageEngine.local_dir(model_id),
                            spec.get("ms_file") or "")

    @staticmethod
    def is_downloaded(model_id: str) -> bool:
        f = DiffsynthImageEngine.local_file(model_id)
        # 1GB 以下视为残件（SD1.5 一体权重 3.97GB）
        return bool(f) and os.path.isfile(f) and os.path.getsize(f) > 1e9

    @staticmethod
    def downloaded_bytes(model_id: str) -> int:
        tot = 0
        d = DiffsynthImageEngine.local_dir(model_id)
        for root, _dirs, files in os.walk(d):
            for f in files:
                try:
                    tot += os.path.getsize(os.path.join(root, f))
                except OSError:  # stability-gate: allow-swallow（逐文件累加体积只为展示估计值；文件在 walk 途中消失(OSError)无需诊断）
                    pass
        return tot

    # ── 拉取（ModelScope 原生通道，国内直连）──────

    def pull(self, model_id: str,
             progress_cb: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """下载模型到 `app/models/cache/<repo>/`。异常绝不外抛。"""
        spec = IMAGE_MODELS.get(model_id)
        if not spec:
            return {"ok": False, "model_id": model_id,
                    "message": f"未知模型 id（可选：{', '.join(IMAGE_MODELS)}）"}
        if self.is_downloaded(model_id):
            return {"ok": True, "model_id": model_id, "path": self.local_file(model_id),
                    "bytes": self.downloaded_bytes(model_id), "message": "已在本机，无需重复下载"}
        try:
            from modelscope import snapshot_download
            if progress_cb:
                progress_cb(f"开始下载 {spec['label']}（{spec['size_gb']}GB，ModelScope）")
            try:
                path = snapshot_download(spec["ms_repo"], local_dir=self.local_dir(model_id),
                                         allow_patterns=[spec["ms_file"]])
            except TypeError:
                path = snapshot_download(spec["ms_repo"], local_dir=self.local_dir(model_id),
                                         allow_file_pattern=[spec["ms_file"]])
        except Exception as e:
            logger.debug("[diffsynth_image] pull 异常", exc_info=True)
            return {"ok": False, "model_id": model_id, "message": f"{type(e).__name__}: {e}"}
        if not path or not self.is_downloaded(model_id):
            return {"ok": False, "model_id": model_id,
                    "message": "下载未落盘完整权重（ModelScope 通道失败）"}
        return {"ok": True, "model_id": model_id, "path": self.local_file(model_id),
                "bytes": self.downloaded_bytes(model_id), "message": "下载完成"}

    # ── 加载 / 生成 / 卸载 ─────────────────────────

    def load(self, model_id: str) -> Dict[str, Any]:
        """加载 pipeline（cpu_offload：权重驻留 RAM，按需整模型换入 GPU）。

        SD1.5 fp16 全量 ≈2GB RAM，本机无压力；同一模型已加载则直接复用。
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
            # ★ 必须走 compat 入口（moviepy 1.x 环境下裸 import diffsynth_engine 必炸，V4.40.25）
            from app.core.neural.diffsynth_compat import import_diffsynth_engine
            dse = import_diffsynth_engine()
            if dse is None:
                return {"ok": False,
                        "message": "diffsynth_engine 导入失败（moviepy 兼容层未建立），"
                                   "详见 diffsynth_compat.py"}
            spec = IMAGE_MODELS[model_id]
            # ★ 刀4 前哨（B-1 裁决，2026-10-04）：主选侧此前硬编码 cpu_offload、
            #   绕开 memory_policy（「单一决策点」只管了一半）。此处**只观测不改行为**：
            #   把 policy 对该模型的决策与理由打出来与硬编码对照，并记进程 RSS ——
            #   SDXL 20s/180s 双态的头号嫌疑是 cpu_offload ~7GB 权重驻留 RAM 触发
            #   换页，没有观测永远查不出（M2 未决与 M5 同源）。
            try:
                from app.core.neural.memory_policy import pick_memory_policy
                _pol = pick_memory_policy(
                    model_id, frames=0,
                    params_b=float(spec["params"].rstrip("B")),
                    tuned={"steps": spec["steps"], "decode_chunk_size": 1, "offload": True},
                    registered_vram_gb=spec.get("vram_gb"))
                logger.info("[diffsynth_image] memory_policy 观测（行为不变，仍 cpu_offload）"
                            ": mode=%s floor=%s", _pol.get("mode"), _pol.get("floor_gb"))
                for _r in _pol.get("reasons", []):
                    logger.info("[diffsynth_image]   · %s", _r)
            except Exception:
                logger.debug("[diffsynth_image] memory_policy 观测失败（不影响加载）",
                             exc_info=True)
            try:
                import psutil
                logger.info("[diffsynth_image] RAM 观测: 进程 RSS %.2fGB / 系统可用 %.2fGB",
                            psutil.Process().memory_info().rss / 1e9,
                            psutil.virtual_memory().available / 1e9)
            except Exception:
                logger.debug("[diffsynth_image] RAM 观测不可用", exc_info=True)
            if spec.get("arch") == "sdxl":
                # 刀2：SDXL 双 CLIP（clip_l + clip_g），config 字段与 SD1.5 不同
                from diffsynth_engine import SDXLImagePipeline, SDXLPipelineConfig
                cfg = SDXLPipelineConfig(
                    model_path=self.local_file(model_id),
                    model_dtype=torch.float16,
                    clip_l_dtype=torch.float16,
                    clip_g_dtype=torch.float16,
                    # vae_dtype 保持默认 fp32（VAE 精度敏感）
                    device="cuda",
                    offload_mode="cpu_offload",   # 权重驻留 RAM（~7GB），按需换入 GPU
                )
                self._pipe = SDXLImagePipeline.from_pretrained(cfg)
            else:
                from diffsynth_engine import SDImagePipeline, SDPipelineConfig
                cfg = SDPipelineConfig(
                    model_path=self.local_file(model_id),
                    model_dtype=torch.float16,
                    clip_dtype=torch.float16,
                    # vae_dtype 保持默认 fp32（VAE 精度敏感，且 SD 的 VAE 很小）
                    device="cuda",
                    offload_mode="cpu_offload",   # 权重驻留 RAM（~2GB），按需整模型换入 GPU
                )
                self._pipe = SDImagePipeline.from_pretrained(cfg)
            self._dse = dse
            self._loaded_id = model_id
            logger.info("[diffsynth_image] 已加载 %s（%s）", model_id, spec["label"])
            return {"ok": True, "message": f"已加载 {spec['label']}（offload=cpu_offload）"}
        except Exception as e:
            logger.debug("[diffsynth_image] load 失败", exc_info=True)
            self._pipe = None
            self._loaded_id = ""
            return {"ok": False, "message": f"加载失败：{type(e).__name__}: {e}"}

    def unload(self) -> None:
        """释放显存与管道引用。"""
        self._pipe = None
        self._loaded_id = ""
        self._dse = None
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
        返回与 video_gen 对齐的 dict（`image_path`/`image_url` 对应 `video_path`/`video_url`）。
        """
        spec = IMAGE_MODELS.get(model_id)
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
            t0 = _time.time()
            n_steps = int(steps) if steps else int(spec["steps"])
            n_cfg = float(cfg) if cfg else float(spec["cfg"])
            native = int(spec["native_size"])
            n_w = int(width) if width else native
            n_h = int(height) if height else native
            kw: Dict[str, Any] = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "cfg_scale": n_cfg,
                "height": n_h,
                "width": n_w,
                "num_inference_steps": n_steps,
                "seed": int(seed) if seed else None,
            }
            if image_path:
                from PIL import Image as _PILImage
                kw["input_image"] = _PILImage.open(image_path).convert("RGB")
                kw["denoising_strength"] = 0.75
            image = self._pipe(**kw)     # 返回单张 PIL.Image

            if not out_path:
                out_path = os.path.join("短剧AI剪辑输出",
                                        f"image_{model_id}_{int(seed)}.png")
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
            logger.debug("[diffsynth_image] generate 失败", exc_info=True)
            return {"ok": False, "message": f"生成失败：{type(e).__name__}: {e}"}


_engine: Optional[DiffsynthImageEngine] = None


def get_image_engine() -> DiffsynthImageEngine:
    """进程级单例。"""
    global _engine
    if _engine is None:
        _engine = DiffsynthImageEngine()
    return _engine
