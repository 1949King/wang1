# -*- coding: utf-8 -*-
"""B 实验脚本（v2 定稿）：SDXL 分裂驻留 —— UNet 独占整卡 + 手写去噪循环时序测量。

⚠️ 结论先行（2026-10-29 实测，数据 data/sdxl_split_residency_bench.json）：
  · 本脚本只测**时序**：787ms/步 vs model_offload 基线 1.07s/步 = 1.36×；
  · 但产物是**灰图**——手写 denoise 循环的数学不可信（v2 逐项修过：
    TE2 pooled 取法、time_ids 展平、timesteps 1-D 化，仍灰）；
  · 正确性以官方管线为准 ⇒ 产品形态测法见 bench_sdxl_split_v3.py
    （官方 __call__ + prompt_embeds 直传，结论 0.60× 慢于基线，维持现状）。
  · 本脚本保留价值：证明「offload 搬运空隙 ≈36%」这一结论的原始证据链。

对照三态（同 seed / 同提示词 / 20 步 / 1024² / cfg 7.5）：
  A. baseline —— enable_model_cpu_offload（现行策略；UNet 每步 CPU↔GPU 搬运）
  B. split    —— 双 CLIP 留 CPU（编码时临时上卡、算完即回），VAE 留 CPU（解码时上卡），
                 UNet 整卡驻留 ⇒ denoise 循环零搬运
  C. steady   —— split 连跑 5 次看稳态
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


def vram_used_gb() -> float:
    import torch

    return round(torch.cuda.memory_allocated() / 1024**3, 2)


def vram_peak_gb() -> float:
    import torch

    return round(torch.cuda.max_memory_allocated() / 1024**3, 2)


def bench_pipe_once(pipe) -> float:
    import torch

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


def med(xs) -> float:
    return round(statistics.median(xs), 1)


def main() -> int:
    import torch
    from diffusers import StableDiffusionXLPipeline

    result: dict = {
        "exp": "sdxl_split_residency_v2",
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

    # ── A. baseline ─────────────────────────────────────────────────
    print("== A. baseline: enable_model_cpu_offload ==")
    pipe.enable_model_cpu_offload()
    bench_pipe_once(pipe)
    times = [bench_pipe_once(pipe) for _ in range(RUNS)]
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    bench_pipe_once(pipe)
    result["states"]["baseline_model_offload"] = {
        "times_ms": times,
        "median_ms": med(times),
        "per_step_ms": round(med(times) / STEPS, 1),
        "peak_gb": vram_peak_gb(),
    }
    print("A:", result["states"]["baseline_model_offload"])

    # ── B. split ────────────────────────────────────────────────────
    print("== B. split: TE/VAE on CPU, UNet resident ==")
    pipe.remove_all_hooks()
    pipe.to("cpu")
    gc.collect()
    torch.cuda.empty_cache()
    unet = pipe.unet.to("cuda")
    print(f"   unet resident: {vram_used_gb()}GB allocated")
    tok1, tok2 = pipe.tokenizer, pipe.tokenizer_2
    te1, te2 = pipe.text_encoder, pipe.text_encoder_2
    vae = pipe.vae

    def encode_prompt_split(prompt: str, negative: str):
        """SDXL 口径：hidden[-2] 双编码器拼接 + TE2 pooled。TE 用完即回 CPU。"""

        def enc(texts):
            hiddens, pooled = [], None
            for tok, te in ((tok1, te1), (tok2, te2)):
                te.to("cuda")
                try:
                    with torch.no_grad():
                        out = te(
                            tok(
                                texts,
                                padding="max_length",
                                max_length=te.config.max_position_embeddings,
                                truncation=True,
                                return_tensors="pt",
                            ).input_ids.to("cuda"),
                            output_hidden_states=True,
                        )
                    hiddens.append(out.hidden_states[-2])
                    if hasattr(out, "text_embeds") and out.text_embeds is not None:
                        pooled = out.text_embeds  # 仅 TE2（WithProjection）有
                finally:
                    te.to("cpu")
            torch.cuda.empty_cache()
            return hiddens, pooled

        # 2026-10-29 实测本机 te2.hidden[-2] = (1,77,1280)、pooled = (1,1280)，
        # 拼接 = (1,77,2048)，与 SDXL 管线口径一致 ⇒ 下方 (2,77,2048) 才是对的。
        # 报 2816x1280 说明 pe_c 只有 2048 维而 add_embedding 期望 2816(=256*6+1280)——
        # 即 denoise 循环里 add_embedding 收到的是 encoder_hidden_states(2048) 而非
        # text_embeds(1280)+time_embeds(1536) 拼的 2816。核查点：added dict 键名。
        h_pos, pooled_p = enc([PROMPT])
        h_neg, pooled_n = enc([NEG])
        pe = torch.cat(h_pos, dim=-1)
        ne = torch.cat(h_neg, dim=-1)
        return pe, ne, pooled_p, pooled_n

    # timesteps 必须是 1-D 张量（UNet 内部 get_timestep_embedding 有 shape 断言）；
    # v3/v4 传的是 0-D 标量 ⇒ broadcast 成 (2,) 后 add_embedding 把 (2,2816) 与
    # (2,2048) 相乘才报 2816x1280 的形状错。
    def split_run():
        device = "cuda"
        gen = torch.Generator("cpu").manual_seed(SEED)
        pe, ne, pooled_p, pooled_n = encode_prompt_split(PROMPT, NEG)
        # dtype 对齐 unet（TE 是 fp16，hidden 直接用；pooled 走 fp32→unet dtype 亦可）
        pe_c = torch.cat([ne, pe], dim=0).to(device=device, dtype=unet.dtype)
        pooled_c = torch.cat([pooled_n, pooled_p], dim=0).to(device=device, dtype=unet.dtype)
        h, w = SIZE // 8, SIZE // 8
        lat = torch.randn((1, 4, h, w), generator=gen, device=torch.device("cpu")).to(
            device=device, dtype=unet.dtype
        )
        sched = pipe.scheduler
        sched.set_timesteps(STEPS)
        added = {
            "text_embeds": pooled_c,
            "time_ids": torch.tensor(
                [[SIZE, SIZE, 0, 0, SIZE, SIZE]], device=device, dtype=unet.dtype
            ),
        }
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.no_grad():
            for ts in sched.timesteps:
                ts_t = (
                    torch.as_tensor(int(ts), device=device, dtype=unet.dtype)
                    if not torch.is_tensor(ts)
                    else ts.to(device)
                )
                if ts_t.ndim == 0:
                    ts_t = ts_t.unsqueeze(0)
                lat_in = torch.cat([lat] * 2)
                ts_in = ts_t.expand(lat_in.shape[0])
                time_ids_in = added["time_ids"].expand(lat_in.shape[0], -1)
                noise = unet(
                    lat_in,
                    ts_in,
                    encoder_hidden_states=pe_c,
                    added_cond_kwargs={
                        "text_embeds": added["text_embeds"],
                        "time_ids": time_ids_in,
                    },
                ).sample
                nu, nc = noise.chunk(2)
                lat = sched.step(nu + CFG * (nc - nu), ts, lat).prev_sample
        torch.cuda.synchronize()
        return round((time.perf_counter() - t0) * 1000, 1), lat

    def decode_split(lat):
        vae.to(device="cuda", dtype=torch.float32)  # 官方 upcast_vae 同款
        vae.enable_tiling()  # 1024² 解码省激活显存
        try:
            with torch.no_grad():
                img = vae.decode(
                    lat.to(torch.float32) / vae.config.scaling_factor, return_dict=False
                )[0]
        finally:
            vae.to("cpu")
            torch.cuda.empty_cache()
        return (img / 2 + 0.5).clamp(0, 1)

    split_run()  # 干跑：cublas 句柄 / 缓存
    times = [split_run()[0] for _ in range(RUNS)]
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    _, lat_keep = split_run()
    peak_b = vram_peak_gb()
    result["states"]["split_unet_gpu"] = {
        "times_ms": times,
        "median_ms": med(times),
        "per_step_ms": round(med(times) / STEPS, 1),
        "peak_gb": peak_b,
    }
    print("B:", result["states"]["split_unet_gpu"])

    # ── C. 稳态 5 连跑 ──────────────────────────────────────────────
    times_c = [split_run()[0] for _ in range(5)]
    result["states"]["split_steady_5x"] = {
        "times_ms": times_c,
        "median_ms": med(times_c),
        "per_step_ms": round(med(times_c) / STEPS, 1),
    }
    print("C:", result["states"]["split_steady_5x"])

    # 样图（证明真出图）
    try:
        img = decode_split(lat_keep)[0]
        from PIL import Image

        arr = (img.float().cpu().permute(1, 2, 0).numpy() * 255).round().astype("uint8")
        out_png = os.path.join(ROOT, "data", "sdxl_split_bench_out.png")
        Image.fromarray(arr).save(out_png)
        result["sample_image"] = out_png
    except Exception as e:
        result["notes"].append(f"decode/save failed: {type(e).__name__}: {e}")

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
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("saved ->", OUT)
    print("ratios:", json.dumps(result["ratios"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
