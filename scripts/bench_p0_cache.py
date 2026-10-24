# -*- coding: utf-8 -*-
"""P0 推理缓存 + 显存预算 真机标定台（V4.47.0，2026-10-25）。

对标定协议 `docs/_reports/2026-10-25-P0推理缓存真机标定协议.md` 的可执行部分。
所有子命令都遵循同一纪律：
  · n≥3（墙钟类取中位数；PSNR 逐对计算）；
  · 任何一步失败 ⇒ 诚实记录 skip + 原因，**绝不编造数字**；
  · 默认关不变：标定只经 env 显式开启，跑完无条件还原；
  · 结果落 `.workbuddy/tmp/bench_p0_cache_<ts>.json` + 人读表（stdout）。

子命令：
  --list                打印标定计划 + 本机模型齐备性（无需 GPU/权重）
  pool                  VramBlockPool 微标定：acquire/release 往返（无权重）
  encoder               编码器缓存记账标定：miss→hit 序列 + LRU 双闸（无权重）
  deepcache --model M   DeepCache 墙钟 + PSNR：同 seed 开关缓存对比（需 GPU+权重）
  lowrank --model M     低秩 rank sweep：0.125/0.25/0.5 → energy/压缩比/PSNR
  overhead --model M    step_cache_overhead 实测：Σ(up_block 通道×空间×2B)

模型 id（与 DIFFUSERS_IMAGE_MODELS 对齐）：sd15-t2i / sdxl-t2i / svd-xt-i2v
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 沙箱/真机临时目录钉项目内（同 run_all_checks 纪律）
_TMP = os.path.join(ROOT, ".workbuddy", "tmp")
os.makedirs(_TMP, exist_ok=True)

ENV_KEYS = ("SHIGUANG_STEP_CACHE", "SHIGUANG_ENCODER_CACHE",
            "SHIGUANG_STEP_CACHE_INTERVAL", "SHIGUANG_STEP_CACHE_BRANCH",
            "SHIGUANG_STEP_CACHE_LOWRANK", "SHIGUANG_CACHE_POOL")


# ────────────────────────── 工具 ──────────────────────────

def _restore_env(saved: dict) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class env_on:
    """上下文管理器：临时开一组 env，退出无条件还原。"""

    def __init__(self, **kw: str):
        self._kw = kw

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in set(ENV_KEYS) | set(self._kw)}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self._kw.items():
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        _restore_env(self._saved)
        return False


def _load_ic():
    """按路径加载 inference_cache（绕开 app 包的硬件探测链）。"""
    import importlib.util

    path = os.path.join(ROOT, "app", "core", "neural", "inference_cache.py")
    spec = importlib.util.spec_from_file_location("_bench_ic", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_bench_ic"] = mod
    spec.loader.exec_module(mod)                      # type: ignore[union-attr]
    return mod


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _psnr(a, b) -> float:
    """两张同形状 uint8/float 图的 PSNR（dB）。全等 ⇒ inf。"""
    import math

    import torch

    ta = torch.as_tensor(a, dtype=torch.float32)
    tb = torch.as_tensor(b, dtype=torch.float32)
    if ta.shape != tb.shape:
        return -1.0
    mse = float(((ta - tb) ** 2).mean())
    if mse <= 0:
        return float("inf")
    return round(10.0 * math.log10(255.0 ** 2 / mse), 2)


def _dump(tag: str, payload: dict) -> str:
    ts = time.strftime("%H%M%S")
    path = os.path.join(_TMP, "bench_p0_cache_%s_%s.json" % (tag, ts))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print("  [落盘] %s" % path)
    return path


def _model_availability() -> list:
    """本机权重齐备性（与 DiffusersImageEngine.is_downloaded 同口径）。"""
    from app.core.neural.diffusers_image import DiffusersImageEngine as E

    rows = []
    for mid in ("sd15-t2i", "sdxl-t2i"):
        ok = E.is_downloaded(mid)
        rows.append({"model_id": mid, "ready": bool(ok),
                     "dir": E.local_dir(mid)})
    svd_dir = os.path.join(ROOT, "app", "models", "cache",
                           "stabilityai_stable-video-diffusion-img2vid-xt")
    rows.append({"model_id": "svd-xt-i2v",
                 "ready": os.path.isfile(os.path.join(svd_dir, "model_index.json")),
                 "dir": svd_dir})
    return rows


# ────────────────────────── 子命令 ──────────────────────────

def cmd_list() -> int:
    print("标定计划（协议 §3/§4；验收阈值见协议文档）：")
    plan = [
        ("pool", "VramBlockPool 5 循环往返", "无权重",
         "5 循环 < 60s 且 hit_rate 收敛 > 0"),
        ("encoder", "编码器缓存记账（miss→hit×8 + LRU 双闸）", "无权重",
         "8 次命中后 hit_rate = 8/9；超闸即淘汰"),
        ("deepcache", "DeepCache 墙钟 + PSNR（sd15/sdxl/svd）", "GPU + 权重",
         "墙钟提速 ≥1.15× 且 PSNR ≥ 30dB（草稿档）"),
        ("lowrank", "低秩 rank sweep 0.125/0.25/0.5", "GPU + 权重",
         "energy ≥ 0.99 且 PSNR ≥ 25dB"),
        ("overhead", "step_cache_overhead 实测替换 estimated", "GPU + 权重",
         "与 vram_budget 登记值偏差 < 20%"),
    ]
    for name, what, need, accept in plan:
        print("  %-10s %-42s [%s]  验收：%s" % (name, what, need, accept))
    print("\n本机模型齐备性：")
    ready_any = False
    for row in _model_availability():
        print("  %-12s %s  %s" % (row["model_id"],
                                  "就绪" if row["ready"] else "缺失", row["dir"]))
        ready_any = ready_any or row["ready"]
    if not ready_any:
        print("  （无任何权重 ⇒ 只能跑 pool/encoder 两项微标定）")
    return 0


def cmd_pool() -> int:
    ic = _load_ic()
    import torch

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    pool = ic.VramBlockPool(device=dev)
    # 模拟 DeepCache 缓存形态：末块特征树 (B,C,H,W)，sd15@512 量级
    shapes = [(1, 1280, 64, 64), (1, 1280, 64, 64), (1, 640, 64, 64)]
    t0 = time.perf_counter()
    n_cycles = 5
    for _ in range(n_cycles):
        handles = [pool.store_tree(torch.empty(s, device=dev))
                   for s in shapes]
        for h in handles:
            h.release()
    elapsed = time.perf_counter() - t0
    st = pool.stats()
    ok = elapsed < 60.0 and st["hits"] > 0
    print("VramBlockPool %d 循环：%.3fs（acquires=%d hits=%d hit_rate=%.2f "
          "live=%d）" % (n_cycles, elapsed, st["acquires"], st["hits"],
                         st["hit_rate"], st["live_blocks"]))
    print("  验收（5 循环 < 60s 且 hit_rate > 0）：%s" % ("通过" if ok else "未过"))
    _dump("pool", {"device": dev, "cycles": n_cycles, "elapsed_s": round(elapsed, 4),
                   "stats": st, "accept": ok})
    return 0 if ok else 1


def cmd_encoder() -> int:
    ic = _load_ic()
    import torch

    cache = ic.EncoderOutputCache(max_entries=8, max_bytes=64 * 1024 ** 2)
    key = ic.make_cache_key(arch="sd15", model_id="sd15-t2i", prompt="p",
                            negative_prompt="n", lora_set="", max_length=77)
    embeds = {"prompt_embeds": torch.zeros(1, 77, 768),
              "negative_prompt_embeds": torch.zeros(1, 77, 768)}
    cache.put(key, embeds, device="cpu")
    misses = hits = 0
    for _ in range(8):
        got = cache.get(key)
        if got is None:
            misses += 1
        else:
            hits += 1
    st = cache.stats()
    # LRU 双闸：灌 9 条 ⇒ 条目闸（max_entries=8）淘汰最旧
    for i in range(9):
        k = ic.make_cache_key(arch="sd15", model_id="m", prompt="p%d" % i,
                              negative_prompt="n", lora_set="", max_length=77)
        cache.put(k, {"prompt_embeds": torch.zeros(1, 4, 4)}, device="cpu")
    st2 = cache.stats()
    ok = hits == 8 and st2["entries"] <= 8 and st2["evictions"] >= 1
    print("编码器缓存：8 次读取 hits=%d misses=%d hit_rate=%.2f"
          % (hits, misses, st["hit_rate"]))
    print("  LRU 双闸：灌 9 条后 entries=%d evictions=%d（条目闸 %d）"
          % (st2["entries"], st2["evictions"], st2["max_entries"]))
    print("  验收（8 命中 + 超闸即淘汰）：%s" % ("通过" if ok else "未过"))
    _dump("encoder", {"hits": hits, "misses": misses, "stats_before": st,
                      "stats_after_lru": st2, "accept": ok})
    return 0 if ok else 1


def _engine_generate(model_id: str, prompt: str, seed: int, steps: int,
                     preset: str, out_dir: str, seconds: float = 0.0,
                     fps: int = 0, tag: str = ""):
    """走真实引擎 generate。

    返回 (dict, 净生成秒, 产物路径)。计时用**引擎自报的 seconds_elapsed**
    （diffusers_image 的 t0 在 load 之后；video_gen 的 t_gen0 同理）——
    外层墙钟会把 6 次权重加载算进去，把 A/B 比压缩向 1.0，是假持平。
    """
    from app.core.neural.diffusers_image import DiffusersImageEngine

    eng = DiffusersImageEngine()
    suffix = ("_%s" % tag) if tag else ""
    out = os.path.join(out_dir, "bench_%s_%d%s.png" % (model_id, seed, suffix))
    t0 = time.perf_counter()
    if model_id == "svd-xt-i2v":
        from app.core.neural.video_gen import VideoGenEngine

        eng = VideoGenEngine()
        out = out.replace(".png", ".mp4")
        r = eng.generate(model_id, prompt=prompt, seconds=seconds or 2.0,
                         fps=fps or 7, seed=seed, out_path=out,
                         steps=steps, quality=preset)
    else:
        r = eng.generate(model_id, prompt=prompt, seed=seed, steps=steps,
                         cfg=0.0, out_path=out, preset=preset)
    net = r.get("seconds_elapsed")
    net = float(net) if isinstance(net, (int, float)) else time.perf_counter() - t0
    return r, net, out


def _load_image(path: str):
    import numpy as np

    try:
        import imageio.v2 as iio
    except ImportError:
        import imageio as iio
    return np.asarray(iio.imread(path))


def cmd_deepcache(model_id: str, n: int, steps: int, preset: str) -> int:
    """同 seed 开关缓存各跑 n 次：墙钟（中位数）+ 与 baseline 的 PSNR。"""
    out_dir = os.path.join(_TMP, "bench_p0_imgs")
    os.makedirs(out_dir, exist_ok=True)
    prompt = "a cinematic portrait of a woman in a red dress, soft rim light, 35mm"
    seed = 1234

    base_times, cached_times = [], []
    base_img = cached_img = None
    failures = []

    for i in range(n):
        with env_on():
            r, dt, out = _engine_generate(model_id, prompt, seed, steps,
                                          preset, out_dir, tag="base%d" % i)
        if not r.get("ok"):
            failures.append("baseline#%d: %s" % (i, r.get("message")))
            continue
        base_times.append(dt)
        base_img = _load_image(out)
        print("  baseline #%d: %.1fs -> %s" % (i, dt, os.path.basename(out)))

    for i in range(n):
        with env_on(SHIGUANG_STEP_CACHE="deepcache"):
            r, dt, out = _engine_generate(model_id, prompt, seed, steps,
                                          preset, out_dir, tag="cached%d" % i)
        if not r.get("ok"):
            failures.append("cached#%d: %s" % (i, r.get("message")))
            continue
        cached_times.append(dt)
        cached_img = _load_image(out)
        print("  cached   #%d: %.1fs -> %s" % (i, dt, os.path.basename(out)))

    if not base_times or not cached_times:
        print("FAIL deepcache 标定失败（真实失败，不编数字）：")
        for f_ in failures:
            print("  -", f_)
        return 1

    speedup = round(_median(base_times) / max(1e-6, _median(cached_times)), 3)
    psnr = _psnr(base_img, cached_img) if base_img is not None else -1.0
    ok = speedup >= 1.15 and psnr >= 30.0
    print("DeepCache %s（%d 步 · preset=%s）：baseline 中位 %.1fs / cached 中位 "
          "%.1fs ⇒ 提速 %.2f×；PSNR %.2f dB"
          % (model_id, steps, preset, _median(base_times), _median(cached_times),
             speedup, psnr))
    print("  验收（≥1.15× 且 ≥30dB）：%s" % ("通过" if ok else "未过（记录备查）"))
    _dump("deepcache_%s" % model_id,
          {"model_id": model_id, "steps": steps, "preset": preset,
           "base_times": [round(x, 2) for x in base_times],
           "cached_times": [round(x, 2) for x in cached_times],
           "speedup": speedup, "psnr_db": psnr, "accept": ok,
           "failures": failures})
    return 0


def cmd_lowrank(model_id: str, ratios, n: int, steps: int, preset: str) -> int:
    """rank sweep：每个 ratio 跑 n 次取中位墙钟 + PSNR（vs baseline）。"""
    out_dir = os.path.join(_TMP, "bench_p0_imgs")
    os.makedirs(out_dir, exist_ok=True)
    prompt = "a cinematic portrait of a woman in a red dress, soft rim light, 35mm"
    seed = 1234

    r0, _dt, out0 = _engine_generate(model_id, prompt, seed, steps, preset, out_dir)
    if not r0.get("ok"):
        print("FAIL lowrank baseline 失败：%s" % r0.get("message"))
        return 1
    base_img = _load_image(out0)
    rows = []
    for ratio in ratios:
        times = []
        img = None
        for i in range(n):
            with env_on(SHIGUANG_STEP_CACHE="deepcache",
                        SHIGUANG_STEP_CACHE_LOWRANK=str(ratio)):
                r, dt, out = _engine_generate(model_id, prompt, seed, steps,
                                              preset, out_dir,
                                              tag="lr%s_%d" % (ratio, i))
            if not r.get("ok"):
                print("  ratio=%.3f #%d 失败：%s" % (ratio, i, r.get("message")))
                break
            times.append(dt)
            img = _load_image(out)
        if len(times) < n:
            continue
        psnr = _psnr(base_img, img)
        # 原始三次全记录（中位数会被并发抢占污染——2026-10-25 实测 110s  outlier）
        rows.append({"ratio": ratio, "times_s": [round(x, 2) for x in times],
                     "median_s": round(_median(times), 2),
                     "min_s": round(min(times), 2), "psnr_db": psnr})
        print("  ratio=%.3f：原始 %s · 中位 %.1fs · PSNR %.2f dB"
              % (ratio, [round(x, 1) for x in times], _median(times), psnr))
    ok = bool(rows) and all(r["psnr_db"] >= 25.0 for r in rows)
    print("低秩 sweep 验收（energy 见遥测日志；PSNR ≥25dB）：%s"
          % ("通过" if ok else "未过（记录备查）"))
    _dump("lowrank_%s" % model_id, {"model_id": model_id, "steps": steps,
                                    "preset": preset, "rows": rows,
                                    "accept": ok})
    return 0 if ok else 1


def _unet_overhead_forward(unet, frames: int = 0, native=None):
    """真实前向 hook 抓全部 up_blocks 输出形状。

    返回 (shapes, itemsize)：
      shapes  = [(B, C, [F,] H, W), ...]  与 up_blocks 顺序一一对应
      itemsize = 参数 dtype 字节数（fp16=2；缓存按原 dtype 存，公式×itemsize）
    失败抛异常 ⇒ 调用方回落 config 推导（不编数字）。

    2026-10-25 首轮教训（都按失败回落，不用默认值糊）：
      · fp32 输入喂 fp16 UNet ⇒ dtype mismatch ⇒ dtype/device 必须跟参数走；
      · SDXL（addition_embed_type='text_time'）缺 text_embeds/time_ids ⇒ ValueError；
      · SVD 是 UNetSpatioTemporalConditionModel：sample 为 (B,F,C,H,W)、
        encoder_hidden_states 为 (B,1,cad)、
        added_time_ids 个数须反推（= 3，不是 6）。
    """
    import torch

    p = next(unet.parameters())
    dt, dev = p.dtype, p.device
    cfg = unet.config
    cad = int(getattr(cfg, "cross_attention_dim", 768) or 768)
    ss = int(getattr(cfg, "sample_size", 64) or 64)
    # latent 空间用「生产分辨率/8」而非 config.sample_size：
    # SVD 的 sample_size=96，但生产跑 576×1024 ⇒ latent 72×128（差 1.5×）
    lw, lh = ss, ss
    if native:
        lw, lh = max(1, int(native[0]) // 8), max(1, int(native[1]) // 8)
    is3d = "SpatioTemporal" in type(unet).__name__
    if is3d:
        f = max(1, (frames - 1) // 4 + 1) if frames else 1
        lat = torch.zeros(1, f, int(cfg.in_channels), lh, lw,
                          dtype=dt, device=dev)
        # added_time_ids 个数由 add_embedding.linear_1.in_features 反推：
        # in = n_ids × 2 × half_dim（SVD = 3 个：fps/motion/noise_aug ⇒ 768）
        half = int(getattr(getattr(unet.add_time_proj, "frequencies", None),
                           "shape", [1, 128])[-1])
        in_f = int(getattr(unet.add_embedding.linear_1, "in_features", 768))
        n_ids = max(1, in_f // max(1, 2 * half))
        kw = {"added_time_ids": torch.zeros(1, n_ids, dtype=dt, device=dev)}
        # SVD 的图像条件是 (B, 1, cad)——序列维为 1（不是 77）
        ehs = torch.zeros(1, 1, cad, dtype=dt, device=dev)
    else:
        lat = torch.zeros(1, int(cfg.in_channels), lh, lw, dtype=dt, device=dev)
        ehs = torch.zeros(1, 77, cad, dtype=dt, device=dev)
        kw = {}
        if getattr(cfg, "addition_embed_type", None) == "text_time":
            # SDXL：add_embedding 是 TimestepEmbedding（diffusers
            # unet_2d_condition.py:685）。它的输入 = concat(text_embeds, time_embeds)，
            # linear_1.in_features 是两者之和（2816 = 1280 text + 1536 time），
            # ⇒ pooled 维度 = in_features − 6×2×half_dim，不能直接拿 in_features。
            lin = getattr(unet.add_embedding, "linear_1", None)
            in_f = int(getattr(lin, "in_features", 2816))
            freq = getattr(unet.add_time_proj, "frequencies", None)
            half = (int(freq.shape[-1]) if freq is not None
                    else int(getattr(cfg, "addition_time_embed_dim", 256)) // 2)
            pooled = max(1, in_f - 6 * 2 * half)
            kw["added_cond_kwargs"] = {
                "text_embeds": torch.zeros(1, pooled, dtype=dt, device=dev),
                "time_ids": torch.zeros(1, 6, dtype=dt, device=dev),
            }
    captured = []

    def _hook(_m, _i, out):
        t = out[0] if isinstance(out, (tuple, list)) else out
        captured.append(tuple(t.shape))

    handles = [b.register_forward_hook(_hook) for b in unet.up_blocks]
    try:
        with torch.no_grad():
            unet(lat, timestep=torch.tensor([1.0], dtype=dt, device=dev),
                 encoder_hidden_states=ehs, **kw)
    finally:
        for h in handles:
            h.remove()
    if not captured:
        raise RuntimeError("hook 未捕获任何 up_block 输出")
    return captured, int(p.dtype.itemsize)


def _unet_overhead_config(unet, frames: int = 0, native=None):
    """config 推导 up_blocks 输出形状（diffusers 源码核实，非实测）。

    unet_2d_condition.py:436-441：up_blocks[i].out_channels =
        reversed(block_out_channels)[i]；
    空间演进（**2026-10-25 真机前向实测校正**）：up_block i 输出 =
        latent >> max(0, n-2-i)（n = up_blocks 数）——
        即非末块各升一级、末块不升。原公式 >> (n-1-i) 整体错位一级
        （sd15 实测 [16,32,64,64] vs 旧推 [8,16,32,64]）。
    3D 多一帧维 (frames-1)//4+1。
    """
    cfg = unet.config
    boc = list(getattr(cfg, "block_out_channels", []) or [])
    ss = int(getattr(cfg, "sample_size", 0) or 0)
    n = len(list(getattr(unet, "up_blocks", []) or []))
    if not boc or not ss or not n:
        return None
    rev = list(reversed(boc))
    is3d = "SpatioTemporal" in type(unet).__name__
    f = max(1, (frames - 1) // 4 + 1) if (is3d and frames) else 1
    lw, lh = ss, ss
    if native:
        lw, lh = max(1, int(native[0]) // 8), max(1, int(native[1]) // 8)
    shapes = []
    for i in range(n):
        ch = int(rev[min(i, len(rev) - 1)])
        k = max(0, n - 2 - i)
        w, h = max(1, lw >> k), max(1, lh >> k)
        shapes.append((1, f, ch, h, w) if is3d else (1, ch, h, w))
    return shapes


def cmd_overhead(model_id: str) -> int:
    """step_cache_overhead 实测：加载真实 UNet，累加 up_blocks 输出字节。

    公式（与 vram_budget.step_cache_overhead_gb 同口径）：
        Σ_up_blocks (out_channels × 空间 × itemsize)，视频再含帧维
    两条路：A 真实前向 hook（basis=forward，最可信）；
            B config 推导（basis=config，diffusers 源码核实）。
    两者皆失败 ⇒ exit 1 诚实失败——**绝不报 0.0000 冒充测量值**
    （2026-10-25 首轮就是把前向失败落成 0.0000，违反不编数字纪律）。
    成功 ⇒ 与登记值算偏差，<20% 判「一致」，否则如实上报待人工定夺。
    """
    from app.core.neural.vram_budget import MODELS, step_cache_overhead_gb

    video = model_id.startswith("svd")
    frames = 14
    native = (MODELS.get(model_id) or {}).get("native")
    if video:
        from app.core.neural.video_gen import VideoGenEngine

        eng = VideoGenEngine()
        r = eng.load(model_id, frames=frames)
    else:
        from app.core.neural.diffusers_image import DiffusersImageEngine

        eng = DiffusersImageEngine()
        r = eng.load(model_id)
    if not r.get("ok"):
        print("FAIL overhead 加载失败：%s" % r.get("message"))
        return 1
    try:
        unet = getattr(eng._pipe, "unet", None)
        if unet is None:
            print("FAIL pipeline 无 unet")
            return 1
        basis = "forward"
        try:
            shapes, itemsize = _unet_overhead_forward(unet, frames, native)
        except Exception as e:  # 前向失败回落 config 推导（诚实失败，不编数字）
            print("  （前向抓形状失败 %s: %s ⇒ 回落 config 推导）"
                  % (type(e).__name__, e))
            shapes = _unet_overhead_config(unet, frames, native)
            itemsize = int(next(unet.parameters()).dtype.itemsize)
            basis = "config"
        if not shapes:
            print("FAIL overhead：前向与 config 推导两条路都失败，不报数")
            return 1
    finally:
        eng.unload()
    total = 0
    per_block = []
    for i, s in enumerate(shapes):
        # 字节 = 整个张量元素数 × itemsize。
        # 注意 3D 模型的 up_block 输出是**展平后**的 (B*F, C, H, W)——
        # 首维 B*F=4 是真实帧数据，不能当 batch 维剔掉（2026-10-25 SVD 首轮
        # 正是这么少算 4×）。batch 恒为 1 ⇒ 全维乘积即真实占用。
        elems = 1
        for d in s:
            elems *= d
        ch_i = 1 if len(s) == 4 else 2
        ch = int(s[ch_i])
        spatial = elems // ch if ch else elems
        b = elems * itemsize
        per_block.append({"block": i, "channels": ch, "spatial": spatial,
                          "elements": elems, "bytes": b, "shape": list(s)})
        total += b
    gb = total / 1024 ** 3
    reg = step_cache_overhead_gb(model_id, frames if video else 0)
    dev_pct = (abs(gb - reg) / reg * 100.0) if reg > 0 else float("nan")
    print("step_cache_overhead 实测（%s，basis=%s，dtype=%dB）：%.4f GB"
          "（%d 个 up_block）" % (model_id, basis, itemsize, gb, len(per_block)))
    for pb in per_block:
        print("  up_block[%d]: shape=%s ⇒ %.2f MB"
              % (pb["block"], tuple(pb["shape"]), pb["bytes"] / 1048576.0))
    print("  登记值（vram_budget，2026-10-25 实测基准确认）= %.4f GB ⇒ 偏差 %.1f%%"
          % (reg, dev_pct))
    ok = reg > 0 and dev_pct < 20.0
    print("  验收（<20%%）：%s" % ("一致" if ok else "不一致——如实上报，不自动回填"))
    _dump("overhead_%s" % model_id,
          {"model_id": model_id, "basis": basis, "itemsize": itemsize,
           "total_gb": round(gb, 6), "registered_gb": reg,
           "deviation_pct": round(dev_pct, 1), "accept": ok,
           "per_block": per_block})
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="P0 推理缓存真机标定台")
    ap.add_argument("cmd", nargs="?", default="",
                    choices=["", "plan", "pool", "encoder", "deepcache",
                             "lowrank", "overhead"])
    ap.add_argument("--list", action="store_true",
                    help="打印标定计划 + 本机模型齐备性（同 plan）")
    ap.add_argument("--model", default="sd15-t2i",
                    help="sd15-t2i / sdxl-t2i / svd-xt-i2v")
    ap.add_argument("--n", type=int, default=3, help="每组重复次数（n≥3）")
    ap.add_argument("--steps", type=int, default=0, help="步数（0=注册表默认）")
    ap.add_argument("--preset", default="fast", help="质量档（白名单内才开缓存）")
    ap.add_argument("--ratios", default="0.125,0.25,0.5",
                    help="lowrank sweep 的 rank_ratio 列表")
    args = ap.parse_args()

    if args.cmd == "" and not args.list:
        ap.print_help()
        return 2
    if args.list or args.cmd == "plan":
        return cmd_list()
    if args.cmd == "pool":
        return cmd_pool()
    if args.cmd == "encoder":
        return cmd_encoder()
    if args.cmd == "deepcache":
        return cmd_deepcache(args.model, args.n, args.steps, args.preset)
    if args.cmd == "lowrank":
        ratios = [float(x) for x in args.ratios.split(",") if x.strip()]
        return cmd_lowrank(args.model, ratios, args.n, args.steps, args.preset)
    if args.cmd == "overhead":
        return cmd_overhead(args.model)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
