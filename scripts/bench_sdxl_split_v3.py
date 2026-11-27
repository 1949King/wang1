# -*- coding: utf-8 -*-
"""B 实验 v3：SDXL 分裂驻留 ——「产品形态」测法。

v2 教训（留档）：手写 denoise 循环时序对了（1.32~1.36×）但产物是灰图，
手写循环的数学不可信。v3 改用**官方管线自身**做去噪/解码：
  · encode：把双 CLIP 临时搬上卡，调 pipe.encode_prompt()（官方数学），
    编码完立刻回 CPU（峰值只多一份 TE-G 1.7GB）；
  · 去噪+解码：UNet+VAE 整卡驻留，用 pipe.__call__(prompt_embeds=...,
    negative_prompt_embeds=..., pooled_prompt_embeds=..., ...) ——
    官方 __call__ 支持 prompt_embeds 直传，TE 不被触碰，天然正确。
这就是将来接进 diffusers_image 的真实形态，测出来的数字可直接写进 _MEASURED。
"""

import gc
import json
import os
import statistics
import sys
import time

ROOT = r"D:\拾光剪影"
sys.path.insert(0, ROOT)

PROMPT = "a cinematic photo of a lighthouse on a cliff at dusk, waves crashing"
NEG = "blurry, low quality, watermark"
SIZE = 1024
STEPS = 20
CFG = 7.5
SEED = 20261029
RUNS = 3
OUT = os.path.join(ROOT, "data", "sdxl_split_residency_bench.json")


def vram_used_gb():
    import torch

    return round(torch.cuda.memory_allocated() / 1024**3, 2)


def vram_peak_gb():
    import torch

    return round(torch.cuda.max_memory_allocated() / 1024**3, 2)


def med(xs):
    return round(statistics.median(xs), 1)


def main() -> int:
    import torch
    from diffusers import StableDiffusionXLPipeline

    result = {
        "exp": "sdxl_split_residency_v3_product",
        "date": time.strftime("%Y-%m-%d"),
        "size": f"{SIZE}x{SIZE}",
        "steps": STEPS,
        "cfg": CFG,
        "seed": SEED,
        "runs_per_state": RUNS,
        "gpu": torch.cuda.get_device_name(0),
        "vram_total_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1),
        "states": {},
        "notes": [],
    }
    print("== load SDXL fp16 ==")
    from app.core.neural.diffusers_image import get_diffusers_image_engine

    eng = get_diffusers_image_engine()
    pipe = StableDiffusionXLPipeline.from_single_file(
        eng.local_file("sdxl-t2i"),
        config=eng.local_dir("sdxl-t2i"),
        original_config=eng.local_config_file("sdxl-t2i"),
        torch_dtype=torch.float16,
        use_safetensors=True,
        local_files_only=True,
        safety_checker=None,
        feature_extractor=None,
    )

    # ── A. baseline（现行策略同款）───────────────────────────────────
    print("== A. baseline: enable_model_cpu_offload ==")
    pipe.enable_model_cpu_offload()

    def base_once():
        gen = torch.Generator("cpu").manual_seed(SEED)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.no_grad():
            pipe(
                prompt=PROMPT,
                negative_prompt=NEG,
                num_inference_steps=STEPS,
                guidance_scale=CFG,
                height=SIZE,
                width=SIZE,
                generator=gen,
            ).images[0]
        torch.cuda.synchronize()
        return round((time.perf_counter() - t0) * 1000, 1)

    base_once()
    times = [base_once() for _ in range(RUNS)]
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    base_once()
    result["states"]["baseline_model_offload"] = {
        "times_ms": times,
        "median_ms": med(times),
        "per_step_ms": round(med(times) / STEPS, 1),
        "peak_gb": vram_peak_gb(),
    }
    print("A:", result["states"]["baseline_model_offload"])

    # ── B. split（产品形态）─────────────────────────────────────────
    print("== B. split: TE CPU (encode-on-demand), UNet+VAE resident ==")
    pipe.remove_all_hooks()
    pipe.to("cpu")
    gc.collect()
    torch.cuda.empty_cache()
    pipe.unet.to("cuda")
    pipe.vae.to("cuda")
    pipe.vae.enable_tiling()  # 1024² 解码省激活显存（官方支持，不损画质档位）
    print(f"   unet+vae resident: {vram_used_gb()}GB allocated")
    te1, te2 = pipe.text_encoder, pipe.text_encoder_2

    def encode_once():
        """双 TE 临时上卡 → 官方 encode_prompt → 回 CPU。"""
        te1.to("cuda")
        te2.to("cuda")
        try:
            with torch.no_grad():
                pe, npe, po, npo = pipe.encode_prompt(
                    prompt=PROMPT,
                    device="cuda",
                    num_images_per_prompt=1,
                    do_classifier_free_guidance=True,
                    negative_prompt=NEG,
                )
        finally:
            te1.to("cpu")
            te2.to("cpu")
        gc.collect()
        torch.cuda.empty_cache()
        return pe, npe, po, npo

    pe, npe, po, npo = encode_once()
    print(f"   embeds ready: {tuple(pe.shape)} pooled {tuple(po.shape)}")

    def split_once():
        gen = torch.Generator("cpu").manual_seed(SEED)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.no_grad():
            pipe(
                prompt_embeds=pe,
                negative_prompt_embeds=npe,
                pooled_prompt_embeds=po,
                negative_pooled_prompt_embeds=npo,
                guidance_scale=CFG,
                height=SIZE,
                width=SIZE,
                num_inference_steps=STEPS,
                generator=gen,
            ).images[0]
        torch.cuda.synchronize()
        return round((time.perf_counter() - t0) * 1000, 1)

    split_once()  # 干跑
    times = [split_once() for _ in range(RUNS)]
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    split_once()
    peak_b = vram_peak_gb()
    result["states"]["split_unet_gpu"] = {
        "times_ms": times,
        "median_ms": med(times),
        "per_step_ms": round(med(times) / STEPS, 1),
        "peak_gb": peak_b,
    }
    print("B:", result["states"]["split_unet_gpu"])

    # ── C. 稳态 5 连跑 ──────────────────────────────────────────────
    times_c = [split_once() for _ in range(5)]
    result["states"]["split_steady_5x"] = {
        "times_ms": times_c,
        "median_ms": med(times_c),
        "per_step_ms": round(med(times_c) / STEPS, 1),
    }
    print("C:", result["states"]["split_steady_5x"])

    # 样图（官方链路，必须非灰图才算数）
    img = pipe(
        prompt_embeds=pe,
        negative_prompt_embeds=npe,
        pooled_prompt_embeds=po,
        negative_pooled_prompt_embeds=npo,
        guidance_scale=CFG,
        height=SIZE,
        width=SIZE,
        num_inference_steps=STEPS,
        generator=torch.Generator("cpu").manual_seed(SEED),
    ).images[0]
    import numpy as _np

    arr = _np.array(img)
    gray = bool(arr.std() < 3.0)  # 灰图判定：全图标准差极小
    out_png = os.path.join(ROOT, "data", "sdxl_split_bench_out_v3.png")
    img.save(out_png)
    result["sample_image"] = out_png
    result["sample_gray_flag"] = gray
    if gray:
        result["notes"].append("样图标准差<3 ⇒ 疑似灰图，本轮数据不得采信")
    print("sample saved; gray_flag =", gray, "std =", round(float(arr.std()), 2))

    a = result["states"]["baseline_model_offload"]["median_ms"]
    b = result["states"]["split_unet_gpu"]["median_ms"]
    c2 = result["states"]["split_steady_5x"]["median_ms"]
    result["ratios"] = {"baseline/split": round(a / b, 2), "baseline/steady": round(a / c2, 2)}
    result["conclusion"] = {
        "baseline_median_ms": a,
        "split_median_ms": b,
        "steady_median_ms": c2,
        "peak_gb": {
            "baseline": result["states"]["baseline_model_offload"]["peak_gb"],
            "split": peak_b,
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("saved ->", OUT)
    print("ratios:", json.dumps(result["ratios"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
