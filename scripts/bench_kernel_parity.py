# -*- coding: utf-8 -*-
"""内核等价性验收：`python scripts/bench_kernel_parity.py --families sd15,sdxl`
视频族：`python scripts/bench_kernel_parity.py --families svd --image <png> --frames 14`

## 跑什么（规范 §11 六门里的四门）

| 门 | 图像族判据 | 视频族判据 | 本脚本怎么测 |
|---|---|---|---|
| 张量门 | 初始 latents **比特一致**；每步 `max|Δ| ≤ 1e-3` | 同左（多一维，且随机数消耗顺序含噪声增广） | 同 seed 各造一次；stock 用 `callback_on_step_end` 抓每步 latents，内核用 hooks 抓 |
| 画质门 | 同后端 PSNR ≥ 35dB，n≥3 seed | **逐帧** PSNR 取**最低值** ≥ 35dB，且帧数必须一致 | 两边的帧逐张比 |
| 速度门 | 内核 ≤ stock × 1.00（1.00~1.03 记"持平"） | 同左 | **交错执行**（A/B/A/B…）后取各自 median |
| 显存门 | ≤ stock × 1.05 | ≤ stock × 1.10（分块解码让峰值抖动更大） | 每次前 `reset_peak_memory_stats()`，取 `max_memory_allocated` |

可观测门（中断）由单测覆盖；守卫门由 `_verify/check_kernel_contract.py` 覆盖。
视频族的中断另外在 `--families svd` 里真跑一次"第 0 步前取消"。

## 为什么要"交错执行"，以及为什么还要**逐轮换序**

跑完 A 再跑 B，GPU 会因持续负载降频，第二组系统性偏慢 —— 于是任何"新路径更慢"
都能被解释成"因为它是第二组"。交错后两组共享同一降频曲线，比值才有意义。

但**只做 A/B/A/B 还不够**：那样内核永远排在每组第二位，仍然恒定吃到"第二个"
的位置劣势。2026-10-28 实测：SVD 上同一份代码得到 1.032× / 1.042× / 1.051× / 1.056×，
几乎与步数无关 —— 这正是位置效应，不是实现更慢。现在按 `rep % 2` 逐轮换序，
让两条路各自当"第一个"的次数相等。
（`推理引擎开发指南.md` §6.4 已记这条坑。）

## 为什么先跑一次丢弃

首次调用含 lazy init / cuDNN autotune / 分配器首次扩张。不预热就测，
会得到"新路径快 100 倍"这种假数据。所以每组正式测量前先空跑一次。

## 视频族的两个额外纪律

1. **同一个 generator 形态**：生产代码 `video_gen.generate` 用的是
   `torch.manual_seed(seed)`（返回 CPU generator 且顺带种全局），不是
   `torch.Generator("cpu")`。两侧必须用同一种构造，否则"同 seed"本身就是假的。
2. **同一张输入图**：内核从 `image_path` 用自己的读法解码，stock 收到的是本脚本
   用 `PIL.Image.open` 读出来的对象。所以 `--image` 只接受 **PNG**（无损，
   两条读法逐像素相同）；喂 JPEG 会因两条解码路径的 IDCT 差异掉几个 dB，
   然后人会去查循环 —— 查半天发现是读图读法不同。
   **图的内容本身不影响判据**：两路吃同一张，等价性比的是"两条路是否一致"，
   不是"这张图好不好看"。所以验收产物不必入库，证据里只记 `size`/`frames`/`steps`/`seeds`。

## 结果落到哪

`docs/knowledge/kernel_evidence.json`（`evidence.record`），带日期与机器名。
**脚本自己不改 `adapter.caps.verified`** —— 验收通过后由人改代码，
这样"改验收状态"永远是一次可见的提交，不会悄悄发生。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app.core.neural import diffusers_image as DI
from app.core.neural.kernel import engine as K
from app.core.neural.kernel import evidence as EV
from app.core.neural.kernel import latents as LAT
from app.core.neural.kernel.contracts import GenRequest
from app.core.neural.kernel.hooks import Hooks

#: 族 → (模型 id, arch)
FAMILIES = {
    "sd15": ("sd15-t2i", "sd15"),
    "sdxl": ("sdxl-t2i", "sdxl"),
    "svd": ("svd-xt-i2v", "svd"),
}

#: 族 → 验收形态（决定走哪套判据）
KINDS = {"svd": "video"}

#: 视频族的显存门放宽到 1.10：分块解码让峰值抖动明显大于图像族
VRAM_LIMIT = {"image": 1.05, "video": 1.10}


class _Capture(Hooks):
    """抓每步 latents 的钩子（验收专用）。"""

    def __init__(self) -> None:
        super().__init__(collect_steps=False)
        self.lats = []

    def after_step(self, ev, latents) -> None:
        try:
            self.lats.append(latents.detach().float().cpu().clone())
        except Exception:  # stability-gate: allow-swallow（抓不到就少一条对照，不影响出图）
            pass


class _CancelAfter(Hooks):
    """跑完第 `n` 步后取消（可观测门：中断必须让**已完成的结果**返回，不是丢弃）。

    `n=0` ⇒ 第 0 步跑完后取消，期望 `step_count == 1` 且 `cancelled=True`。
    """

    def __init__(self, n: int = 0) -> None:
        super().__init__(collect_steps=False)
        self.n = int(n)
        self.seen = -1

    def cancelled(self) -> bool:
        return self.seen >= self.n

    def before_step(self, ev) -> None:
        self.seen = ev.index


def _peak_reset() -> None:
    import torch

    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()


def _peak_gb() -> float:
    import torch

    if not torch.cuda.is_available():
        return 0.0
    torch.cuda.synchronize()
    return round(torch.cuda.max_memory_allocated() / 1024 ** 3, 3)


def _per_step_max_delta(a, b):
    """逐 step latents 的 max|Δ|；步数不同返回 None。"""
    if not a or not b or len(a) != len(b):
        return None
    worst = 0.0
    for x, y in zip(a, b, strict=True):
        if x.shape != y.shape:
            return None
        worst = max(worst, float((x - y).abs().max().item()))
    return worst


def _fmt_psnr(p: float) -> str:
    return "inf（完全一致）" if p == float("inf") else "%.2f dB" % p


# ══════════════════════════════════════════════════════════════════
# 图像族
# ══════════════════════════════════════════════════════════════════

def _run_stock_image(pipe, *, prompt, negative, w, h, steps, cfg, seed):
    """stock 路径（一次 `pipe(...)` 调用），返回 (image, per_step_latents, peak_gb)。"""
    import torch

    per_step = []

    def _cb(_p, i, _t, kwargs):
        try:
            per_step.append(kwargs["latents"].detach().float().cpu().clone())
        except Exception:  # stability-gate: allow-swallow（抓点失败不应中断出图）
            pass
        return kwargs

    gen = torch.Generator("cpu").manual_seed(int(seed))
    _peak_reset()
    out = pipe(
        prompt=prompt, negative_prompt=negative,
        width=int(w), height=int(h),
        num_inference_steps=int(steps), guidance_scale=float(cfg),
        generator=gen,
        callback_on_step_end=_cb,
        callback_on_step_end_tensor_inputs=["latents"],
    )
    return out.images[0], per_step, _peak_gb()


def _run_kernel_image(pipe, *, family, model_id, prompt, negative, w, h, steps, cfg, seed):
    import torch

    hook = _Capture()
    gen = torch.Generator("cpu").manual_seed(int(seed))
    req = GenRequest(family=family, model_id=model_id, prompt=prompt,
                     negative_prompt=negative, width=int(w), height=int(h),
                     steps=int(steps), cfg=float(cfg))
    _peak_reset()
    res = K.run(pipe=pipe, req=req, generator=gen, hooks=hook)
    return res, hook.lats, _peak_gb()


def _check_initial_latents_image(pipe, w, h, seed):
    """初始 latents 比特一致（规范 §11 张量门第一条）。"""
    import torch

    net = getattr(pipe, "unet", None)
    if net is None:
        return None, "无 unet，跳过"
    channels = int(getattr(net.config, "in_channels", 4))
    scale = int(getattr(pipe, "vae_scale_factor", 8))
    dtype = next(iter(net.parameters())).dtype
    device = next(iter(net.parameters())).device

    g1 = torch.Generator("cpu").manual_seed(int(seed))
    ref = pipe.prepare_latents(1, channels, int(h), int(w), dtype, device, g1)

    g2 = torch.Generator("cpu").manual_seed(int(seed))
    sigma = float(getattr(pipe.scheduler, "init_noise_sigma", 1.0))
    ours = LAT.make(batch=1, channels=channels, height=int(h), width=int(w),
                    latent_scale=scale, generator=g2, device=device, dtype=dtype,
                    init_noise_sigma=sigma)

    same = bool(torch.equal(ref, ours))
    delta = float((ref.float() - ours.float()).abs().max().item())
    return same, "max|Δ|=%.3e" % delta


def _bench_image(fam, arch, model_id, args, seeds, engine):
    """图像族：返回 (result_dict, passed)。"""
    spec = DI.DIFFUSERS_IMAGE_MODELS.get(model_id) or {}
    w = h = int(spec.get("native_size") or 512)
    steps = int(args.steps or spec.get("steps") or 20)
    cfg = float(spec.get("cfg") or 7.5)

    print("=" * 66)
    print("族 %s ｜ 模型 %s ｜ %d×%d ｜ %d 步 ｜ cfg %.1f"
          % (fam, model_id, w, h, steps, cfg))
    print("=" * 66)

    r = engine.load(model_id)
    if not r.get("ok"):
        print("✗ 加载失败：%s" % r.get("message"))
        return None, False
    pipe = engine._pipe

    _run_stock_image(pipe, prompt=args.prompt, negative=args.negative, w=w, h=h,
                     steps=steps, cfg=cfg, seed=seeds[0])

    same, note = _check_initial_latents_image(pipe, w, h, seeds[0])
    lat_ok = bool(same)
    print("[张量门] 初始 latents 比特一致：%s（%s）" % ("✓" if lat_ok else "✗", note))

    ok_all = True
    psnrs, delta_max, lat_ratios, vram_ratios = [], 0.0, [], []
    for seed in seeds:
        t_stock, t_kernel = [], []
        last = None
        for rep in range(max(1, args.n)):
            # ★ 逐轮**换序**：只做 A/B/A/B 的话，内核永远排在每组第二位，
            #   而第二位的 GPU 已经被上一个 13s 的负载加热 ⇒ 恒定慢 3~4%。
            #   （2026-10-28 实测：1.032× / 1.042× / 1.051× / 1.056× 几乎与步数无关，
            #    正是"位置效应"而不是"实现更慢"；换序后能出现 0.981×。）
            first_is_stock = (rep % 2 == 0)
            res_s = res_k = None
            if first_is_stock:
                t0 = time.perf_counter()
                res_s = _run_stock_image(pipe, prompt=args.prompt, negative=args.negative,
                                         w=w, h=h, steps=steps, cfg=cfg, seed=seed)
                t_stock.append(time.perf_counter() - t0)
                t0 = time.perf_counter()
                res_k = _run_kernel_image(pipe, family=arch, model_id=model_id,
                                          prompt=args.prompt, negative=args.negative,
                                          w=w, h=h, steps=steps, cfg=cfg, seed=seed)
                t_kernel.append(time.perf_counter() - t0)
            else:
                t0 = time.perf_counter()
                res_k = _run_kernel_image(pipe, family=arch, model_id=model_id,
                                          prompt=args.prompt, negative=args.negative,
                                          w=w, h=h, steps=steps, cfg=cfg, seed=seed)
                t_kernel.append(time.perf_counter() - t0)
                t0 = time.perf_counter()
                res_s = _run_stock_image(pipe, prompt=args.prompt, negative=args.negative,
                                         w=w, h=h, steps=steps, cfg=cfg, seed=seed)
                t_stock.append(time.perf_counter() - t0)
            img_s, lat_s, peak_s = res_s
            res_k, lat_k, peak_k = res_k
            last = (img_s, res_k, lat_s, lat_k, peak_s, peak_k)

        img_s, res_k, lat_s, lat_k, peak_s, peak_k = last
        if not res_k.get("ok"):
            print("  ✗ seed=%s 内核失败：%s" % (seed, res_k.get("message")))
            ok_all = False
            continue

        p = EV.psnr(img_s, res_k["image"])
        psnrs.append(p)
        d = _per_step_max_delta(lat_s, lat_k)
        if d is not None:
            delta_max = max(delta_max, d)
        ms, mk = statistics.median(t_stock), statistics.median(t_kernel)
        lat_ratios.append(mk / ms if ms else 0.0)
        vram_ratios.append(peak_k / peak_s if peak_s else 0.0)
        print("  seed=%-4s PSNR=%s  逐step max|Δ|=%s  时延 %.2fs/%.2fs (%.3f×)  峰值 %.2f/%.2fGB"
              % (seed, _fmt_psnr(p), "n/a" if d is None else "%.3e" % d,
                 ms, mk, (mk / ms if ms else 0), peak_s, peak_k))

        if args.outdir:
            os.makedirs(args.outdir, exist_ok=True)
            img_s.save(os.path.join(args.outdir, "%s_%s_stock.png" % (fam, seed)))
            res_k["image"].save(os.path.join(args.outdir, "%s_%s_kernel.png" % (fam, seed)))

    psnr_min = min(psnrs) if psnrs else 0.0
    result, passed = _summarize(
        kind="image", lat_ok=lat_ok, delta_max=delta_max, psnr_min=psnr_min,
        lat_ratios=lat_ratios, vram_ratios=vram_ratios, steps=steps,
        size=[w, h], seeds=seeds, n=args.n, extra={})
    return result, (passed and ok_all)


# ══════════════════════════════════════════════════════════════════
# 视频族
# ══════════════════════════════════════════════════════════════════

def _video_params(model_id, args):
    from app.core.neural import video_gen as VG

    tun = VG.tuned_for(model_id)
    frames = int(args.frames or 14)
    steps = int(args.steps or tun.get("steps") or 25)
    mb = int(args.motion_bucket_id or tun.get("motion_bucket_id", 127))
    nas = float(tun.get("noise_aug_strength", 0.02))
    cfg_min = float(tun.get("cfg_min", VG._CFG_MIN))
    cfg_max = float(tun.get("cfg_max", VG._CFG_MAX))
    chunk = int(args.decode_chunk or tun.get("decode_chunk_size") or 1)
    return {
        "frames": frames, "steps": steps, "motion_bucket_id": mb,
        "noise_aug_strength": nas, "cfg_min": cfg_min, "cfg_max": cfg_max,
        "fps": int(args.fps), "decode_chunk": chunk,
        # 尺寸可覆盖：8GB 卡上 1024×576 会让"VAE fp32 编码 + 常驻模型"顶到 7.9/8.0GB，
        # UNet 单步从 4.5s 掉到 20s+（落到共享显存）。等价性判据与尺寸无关，
        # 所以小尺寸照样能验收 —— **前提是两路用同一个尺寸**（这里就是唯一来源）。
        "width": int(args.width or VG._WIDTH),
        "height": int(args.height or VG._HEIGHT),
    }


def _load_png(path):
    """损失less 读图。**只接受 PNG**：JPEG 的两条解码路径会差几个 LSB。"""
    from PIL import Image

    img = Image.open(path)
    if img.format != "PNG":
        raise SystemExit("✗ --image 必须是 PNG（JPEG 的两条解码路径差异会污染 PSNR 对照）：%s"
                         % (img.format or "?"))
    return img.convert("RGB")


def _run_stock_video(pipe, pil, p, seed):
    import torch

    per_step = []

    def _cb(_pipe, i, _t, kwargs):
        try:
            per_step.append(kwargs["latents"].detach().float().cpu().clone())
        except Exception:  # stability-gate: allow-swallow（抓点失败不应中断出片）
            pass
        return kwargs

    # ★ 与 `video_gen.generate` 同一种 generator 构造（`torch.manual_seed` 返回 CPU generator）
    gen = torch.manual_seed(int(seed))
    _peak_reset()
    out = pipe(
        image=pil,
        height=p["height"], width=p["width"],
        num_frames=p["frames"], num_inference_steps=p["steps"],
        min_guidance_scale=p["cfg_min"], max_guidance_scale=p["cfg_max"],
        fps=p["fps"], motion_bucket_id=p["motion_bucket_id"],
        noise_aug_strength=p["noise_aug_strength"],
        decode_chunk_size=p["decode_chunk"],
        generator=gen,
        output_type="pil",
        callback_on_step_end=_cb,
        callback_on_step_end_tensor_inputs=["latents"],
    )
    return out.frames[0], per_step, _peak_gb()


def _video_req(model_id, image_path, p):
    return GenRequest(
        family="svd", model_id=model_id, image_path=image_path,
        width=p["width"], height=p["height"], steps=p["steps"],
        cfg=p["cfg_max"], cfg_min=p["cfg_min"],
        frames=p["frames"], fps=p["fps"],
        motion_bucket_id=p["motion_bucket_id"],
        noise_aug_strength=p["noise_aug_strength"], batch=1,
    )


def _run_kernel_video(pipe, model_id, image_path, p, seed, hooks=None):
    import torch

    hook = hooks if hooks is not None else _Capture()
    gen = torch.manual_seed(int(seed))
    req = _video_req(model_id, image_path, p)
    _peak_reset()
    res = K.run(pipe=pipe, req=req, generator=gen, hooks=hook,
                decode_chunk=p["decode_chunk"])
    return res, getattr(hook, "lats", []), _peak_gb()


def _check_initial_latents_video(pipe, model_id, image_path, p, seed):
    """视频族的张量门第一条：**连随机数消耗顺序一起**比。

    SVD 在造初始 latents **之前**先抽一组"噪声增广"。所以对照序列是：

      stock：`randn(图像形状)` → `pipe.prepare_latents(...)`
      内核 ：`ad.encode()`（内部抽增广噪声）→ `ad.init_latents(...)`

    只比"同样 seed 造出来的 latents"而不先消耗掉增广噪声，两边必然差一整个序列 ——
    而这个错误的表现是"视频不一样"，不是"报错"。
    """
    import torch
    from diffusers.utils.torch_utils import randn_tensor

    from app.core.neural.kernel.adapters.base import ComponentBag

    ad = K.adapter_for("svd")
    ad.bind(ComponentBag.from_pipe(pipe, extras={"scheduler": pipe.scheduler}))
    bad = ad.validate()
    if bad:
        return None, "适配器体检未过：%s" % "；".join(bad)

    net = pipe.unet
    in_ch = int(getattr(net.config, "in_channels", 8))
    dtype = next(iter(net.parameters())).dtype
    device = pipe._execution_device
    pipe.scheduler.set_timesteps(int(p["steps"]), device=device)

    # —— stock 序列 ——
    pil = _load_png(image_path)
    px = pipe.video_processor.preprocess(pil, height=p["height"], width=p["width"]).to(device)
    g1 = torch.manual_seed(int(seed))
    randn_tensor(px.shape, generator=g1, device=device, dtype=px.dtype)   # 噪声增广
    ref = pipe.prepare_latents(1, int(p["frames"]), in_ch, p["height"], p["width"],
                               dtype, device, g1)

    # —— 内核序列 ——
    g2 = torch.manual_seed(int(seed))
    req = _video_req(model_id, image_path, p)
    cond = ad.encode(req, True, generator=g2)
    ours = ad.init_latents(req, cond, generator=g2, scheduler=pipe.scheduler)

    if tuple(ref.shape) != tuple(ours.shape):
        return False, "形状不同：stock %s vs 内核 %s" % (tuple(ref.shape), tuple(ours.shape))
    same = bool(torch.equal(ref, ours))
    delta = float((ref.float() - ours.float()).abs().max().item())
    return same, "shape=%s max|Δ|=%.3e" % (tuple(ref.shape), delta)


def _frames_psnr(frames_a, frames_b):
    """逐帧 PSNR：返回 (最低值, 均值, 帧数)。帧数不同返回 (None, None, n)。"""
    if len(frames_a) != len(frames_b):
        return None, None, len(frames_a)
    vals = [EV.psnr(a, b) for a, b in zip(frames_a, frames_b, strict=True)]
    finite = [v for v in vals if v != float("inf")]
    return min(vals), (statistics.fmean(finite) if finite else float("inf")), len(vals)


def _bench_video(fam, arch, model_id, args, seeds, engine):
    p = _video_params(model_id, args)
    print("=" * 66)
    print("族 %s ｜ 模型 %s ｜ %d×%d ｜ %d 帧 ｜ %d 步 ｜ cfg %.1f→%.1f ｜ chunk %d ｜ fps %d"
          % (fam, model_id, p["width"], p["height"], p["frames"], p["steps"],
             p["cfg_min"], p["cfg_max"], p["decode_chunk"], p["fps"]))
    print("=" * 66)

    if not args.image:
        return None, _fail_video("视频族必须给 --image <输入图.png>（SVD 没有文本条件）")
    if not os.path.isfile(args.image):
        return None, _fail_video("输入图不存在：%s" % args.image)

    r = engine.load(model_id, frames=p["frames"])
    if not r.get("ok"):
        return None, _fail_video("加载失败：%s" % r.get("message"))
    pipe = engine._pipe
    image_path = os.path.abspath(args.image)
    pil = _load_png(image_path)

    # ── 预热（丢弃）────────────────────────────────────────────
    _run_stock_video(pipe, pil, p, seeds[0])

    # ── 张量门第一条 ───────────────────────────────────────────
    same, note = _check_initial_latents_video(pipe, model_id, image_path, p, seeds[0])
    lat_ok = bool(same)
    print("[张量门] 初始 latents 比特一致（含噪声增广顺序）：%s（%s）"
          % ("✓" if lat_ok else "✗", note))

    ok_all = True
    psnrs, means, delta_max, lat_ratios, vram_ratios = [], [], 0.0, [], []
    frames_match = True
    for seed in seeds:
        t_stock, t_kernel = [], []
        last = None
        for rep in range(max(1, args.n)):
            # ★ 逐轮换序（理由见 `_bench_image` 里同名注释）：只做 A/B/A/B 会让
            #   内核永远排在第二位，吃到上一个 13s 负载的降频，恒定慢 3~4%。
            first_is_stock = (rep % 2 == 0)
            res_s = res_k = None
            if first_is_stock:
                t0 = time.perf_counter()
                # **在计时区内**读图：生产路径（`video_gen.generate`）就是
                # `t0 = time.time()` 之后才 `iio.imread(image_path)`，而内核也是从
                # `image_path` 自己读的。若这里复用循环外读好的 `pil`，
                # 就等于让 stock 少做一次 PNG 解码，量法不公平。
                res_s = _run_stock_video(pipe, _load_png(image_path), p, seed)
                t_stock.append(time.perf_counter() - t0)
                t0 = time.perf_counter()
                res_k = _run_kernel_video(pipe, model_id, image_path, p, seed)
                t_kernel.append(time.perf_counter() - t0)
            else:
                t0 = time.perf_counter()
                res_k = _run_kernel_video(pipe, model_id, image_path, p, seed)
                t_kernel.append(time.perf_counter() - t0)
                t0 = time.perf_counter()
                res_s = _run_stock_video(pipe, _load_png(image_path), p, seed)
                t_stock.append(time.perf_counter() - t0)
            fr_s, lat_s, peak_s = res_s
            res_k, lat_k, peak_k = res_k
            last = (fr_s, res_k, lat_s, lat_k, peak_s, peak_k)

        fr_s, res_k, lat_s, lat_k, peak_s, peak_k = last
        if not res_k.get("ok") or not res_k.get("frames"):
            print("  ✗ seed=%s 内核失败：%s"
                  % (seed, res_k.get("report").rejected_reason if res_k.get("report")
                     else res_k.get("message")))
            ok_all = False
            continue

        fr_k = res_k["frames"]
        pmin, pmean, n = _frames_psnr(fr_s, fr_k)
        if pmin is None:
            print("  ✗ seed=%s 帧数不同：stock %d vs 内核 %d" % (seed, len(fr_s), n))
            frames_match = False
            ok_all = False
            continue
        psnrs.append(pmin)
        means.append(pmean)
        d = _per_step_max_delta(lat_s, lat_k)
        if d is not None:
            delta_max = max(delta_max, d)
        ms, mk = statistics.median(t_stock), statistics.median(t_kernel)
        lat_ratios.append(mk / ms if ms else 0.0)
        vram_ratios.append(peak_k / peak_s if peak_s else 0.0)
        print("  seed=%-4s 帧数=%d 逐帧PSNR 最低=%s 均值=%s  逐step max|Δ|=%s"
              "  时延 %.2fs/%.2fs (%.3f×)  峰值 %.2f/%.2fGB"
              % (seed, n, _fmt_psnr(pmin), _fmt_psnr(pmean),
                 "n/a" if d is None else "%.3e" % d,
                 ms, mk, (mk / ms if ms else 0), peak_s, peak_k))

        if args.outdir:
            _save_frames(fr_s, os.path.join(args.outdir, "%s_%s_stock" % (fam, seed)))
            _save_frames(fr_k, os.path.join(args.outdir, "%s_%s_kernel" % (fam, seed)))

    # ── 可观测门：第 0 步前取消 ────────────────────────────────
    cancel_ok = _check_cancel(pipe, model_id, image_path, p, seeds[0])

    psnr_min = min(psnrs) if psnrs else 0.0
    result, passed = _summarize(
        kind="video", lat_ok=lat_ok, delta_max=delta_max, psnr_min=psnr_min,
        lat_ratios=lat_ratios, vram_ratios=vram_ratios, steps=p["steps"],
        size=[p["width"], p["height"]], seeds=seeds, n=args.n,
        extra={
            "frames": p["frames"], "frames_match": frames_match,
            "frame_psnr_mean_db": (None if not means else
                                   (round(min(means), 3) if min(means) != float("inf")
                                    else None)),
            "cancelled_ok": cancel_ok,
            "decode_chunk": p["decode_chunk"],
            "fps": p["fps"], "motion_bucket_id": p["motion_bucket_id"],
            "noise_aug_strength": p["noise_aug_strength"],
            "cfg_min": p["cfg_min"], "cfg_max": p["cfg_max"],
        })
    return result, (passed and ok_all and frames_match and cancel_ok)


def _check_cancel(pipe, model_id, image_path, p, seed) -> bool:
    """可观测门（视频）：第 0 步前取消 ⇒ `cancelled=True` 且 `ok=False`、`frames=None`。

    为什么单独测：取消路径是唯一"不产出结果也算正常"的分支，
    写错的表现是"取消后仍然把半成品当成功返回"，而那会让前端拿到一段糊片。
    """
    res, _lats, _peak = _run_kernel_video(pipe, model_id, image_path, p, seed,
                                          hooks=_CancelAfter(0))
    ok = bool(res.get("cancelled")) and not res.get("ok") and res.get("frames") is None
    print("[可观测门] 第 0 步前取消生效：%s（%s）"
          % ("✓" if ok else "✗", res.get("message") or res.get("report")))
    return ok


def _save_frames(frames, prefix) -> None:
    d = os.path.dirname(prefix)
    if d:
        os.makedirs(d, exist_ok=True)
    for i, f in enumerate(frames):
        f.save("%s_%03d.png" % (prefix, i))


def _fail_video(msg: str):
    print("✗ %s" % msg)
    return False


# ══════════════════════════════════════════════════════════════════
# 通用判据汇总 / 入口
# ══════════════════════════════════════════════════════════════════

def _summarize(*, kind, lat_ok, delta_max, psnr_min, lat_ratios, vram_ratios,
               steps, size, seeds, n, extra):
    psnr_ok = (psnr_min == float("inf")) or psnr_min >= 35.0
    tensor_ok = bool(lat_ok) and (delta_max <= 1e-3)
    lat_ratio = max(lat_ratios) if lat_ratios else 99.0
    vram_ratio = max(vram_ratios) if vram_ratios else 99.0
    speed_ok = lat_ratio <= 1.03
    vram_limit = VRAM_LIMIT.get(kind, 1.05)
    vram_ok = vram_ratio <= vram_limit

    print("-" * 66)
    print("  张量门 : %s（初始 latents %s，逐step max|Δ|=%.3e）"
          % ("✓" if tensor_ok else "✗", "一致" if lat_ok else "不一致", delta_max))
    print("  画质门 : %s（%s最低 %s，门槛 35dB）"
          % ("✓" if psnr_ok else "✗", "逐帧" if kind == "video" else "",
             "inf" if psnr_min == float("inf") else "%.2fdB" % psnr_min))
    print("  速度门 : %s（最差 %.3f×，>1.03 不通过，1.00~1.03 只能写持平）"
          % ("✓" if lat_ratio <= 1.0 else ("△ 持平" if speed_ok else "✗"), lat_ratio))
    print("  显存门 : %s（最差 %.3f×，门槛 %.2f）"
          % ("✓" if vram_ok else "✗", vram_ratio, vram_limit))

    passed = bool(tensor_ok and psnr_ok and speed_ok and vram_ok)
    result = {
        "kind": kind,
        "psnr_min_db": None if psnr_min == float("inf") else round(psnr_min, 3),
        "psnr_inf": psnr_min == float("inf"),
        "tensor_max_delta": delta_max,
        "initial_latents_identical": bool(lat_ok),
        "latency_ratio": round(lat_ratio, 4),
        "vram_ratio": round(vram_ratio, 4),
        "vram_limit": vram_limit,
        "steps": steps, "size": size, "seeds": seeds, "n": n,
        "passed": passed,
        "stock_backend": "diffusers=%s" % _diffusers_version(),
    }
    if kind == "video":
        # 与图像族的 `psnr_min_db` 区分开：视频族的判据是"**逐帧**最低"，不是"整片一张图"。
        # 同名列会让人以为"一张图 35dB"，所以视频族额外给一个语义明确的名字。
        result["frame_psnr_min_db"] = result["psnr_min_db"]
    result.update(extra or {})
    return result, passed


def main() -> int:
    ap = argparse.ArgumentParser(description="内核等价性验收")
    ap.add_argument("--families", default="sd15", help="逗号分隔：sd15,sdxl,svd")
    ap.add_argument("--seeds", default="3,42,777")
    ap.add_argument("--steps", type=int, default=0, help="0=用注册表默认")
    ap.add_argument("--n", type=int, default=3, help="速度测量重复次数（交错）")
    ap.add_argument("--prompt", default="a photo of a cat sitting on a wooden table")
    ap.add_argument("--negative", default="")
    ap.add_argument("--outdir", default="", help="保存对照图/帧（可选）")
    ap.add_argument("--no-record", action="store_true", help="不写证据台账")
    # —— 视频族专用 ——
    ap.add_argument("--image", default="", help="视频族输入图（必须是 PNG）")
    ap.add_argument("--frames", type=int, default=0, help="视频帧数，0=用调优表/默认 14")
    ap.add_argument("--width", type=int, default=0, help="出图宽，0=1024（SVD 原生）")
    ap.add_argument("--height", type=int, default=0, help="出图高，0=576（SVD 原生）")
    ap.add_argument("--fps", type=int, default=7)
    ap.add_argument("--motion-bucket-id", type=int, default=0, dest="motion_bucket_id")
    ap.add_argument("--decode-chunk", type=int, default=0, dest="decode_chunk",
                    help="分块解码大小，0=用调优表（SVD 实测 1）")
    args = ap.parse_args()

    # 内核开关：验收时必须允许未验收族，否则内核一律拒绝（那不是"跑不过"，是"没让跑"）
    os.environ["SHIGUANG_KERNEL"] = "on"
    os.environ["SHIGUANG_KERNEL_ALLOW_UNVERIFIED"] = "1"

    fams = [x.strip() for x in args.families.split(",") if x.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    overall_ok = True
    results = {}

    for fam in fams:
        if fam not in FAMILIES:
            print("✗ 未知族 %s（支持：%s）" % (fam, list(FAMILIES)))
            return 2
        model_id, arch = FAMILIES[fam]
        kind = KINDS.get(fam, "image")
        # 引擎必须按形态选：图像引擎的 `load(model_id)` **不接受 frames**，
        # 而视频引擎要靠帧数决定 offload 与分块策略（见 video_gen.load 的实测定调）。
        if kind == "video":
            from app.core.neural import video_gen as VG

            engine = VG.get_video_engine()
            result, passed = _bench_video(fam, arch, model_id, args, seeds, engine)
        else:
            engine = DI.get_diffusers_image_engine()
            result, passed = _bench_image(fam, arch, model_id, args, seeds, engine)

        overall_ok = overall_ok and bool(passed)
        if result is None:
            continue
        results[fam] = result
        if not args.no_record:
            p = EV.record(fam, result, script="scripts/bench_kernel_parity.py")
            print("  证据已登记：%s" % os.path.relpath(p, ROOT))

    print("\n" + "=" * 66)
    if overall_ok:
        print("✓ 验收通过（四门全绿）。下一步：把 adapter.caps.verified 改为 VERIFIED，"
              "并更新 capability_manifest 的 loop_owner")
    else:
        print("✗ 验收未通过 —— 不许把它写成 verified，也不许默认开 on")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if overall_ok else 1


def _diffusers_version() -> str:
    try:
        import diffusers

        return diffusers.__version__
    except Exception:  # stability-gate: allow-swallow（只用于证据标注）
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
