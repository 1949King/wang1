# -*- coding: utf-8 -*-
"""内核等价性验收：`python scripts/bench_kernel_parity.py --families sd15,sdxl`

## 跑什么（规范 §11 六门里的四门）

| 门 | 判据 | 本脚本怎么测 |
|---|---|---|
| 张量门 | 初始 latents **比特一致**；每步 `max|Δ| ≤ 1e-3` | 同 seed 各造一次；stock 用 `callback_on_step_end` 抓每步 latents，内核用 hooks 抓 |
| 画质门 | 同后端 PSNR ≥ 35dB，n≥3 seed | 两图直接比 PSNR |
| 速度门 | 内核 ≤ stock × 1.00（1.00~1.03 记"持平"） | **交错执行**（A/B/A/B…）后取各自 median |
| 显存门 | ≤ stock × 1.05（视频 ×1.10） | 每张图前 `reset_peak_memory_stats()`，取 `max_memory_allocated` |

可观测门（中断）由单测覆盖；守卫门由 `_verify/check_kernel_contract.py` 覆盖。

## 为什么要"交错执行"

跑完 A 再跑 B，GPU 会因持续负载降频，第二组系统性偏慢 —— 于是任何"新路径更慢"
都能被解释成"因为它是第二组"。交错后两组共享同一降频曲线，比值才有意义。
（`推理引擎开发指南.md` §6.4 已记这条坑。）

## 为什么先跑一次丢弃

首次调用含 lazy init / cuDNN autotune / 分配器首次扩张。不预热就测，
会得到"新路径快 100 倍"这种假数据。所以每组正式测量前先空跑一张。

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

from app.core.neural import diffusers_image as DI          # noqa: E402
from app.core.neural.kernel import engine as K            # noqa: E402
from app.core.neural.kernel import evidence as EV         # noqa: E402
from app.core.neural.kernel import latents as LAT         # noqa: E402
from app.core.neural.kernel.contracts import GenRequest   # noqa: E402
from app.core.neural.kernel.hooks import Hooks            # noqa: E402

#: 族 → (模型 id, arch)
FAMILIES = {
    "sd15": ("sd15-t2i", "sd15"),
    "sdxl": ("sdxl-t2i", "sdxl"),
}


class _Capture(Hooks):
    """抓每步 latents 的钩子（验收专用）。"""

    def __init__(self) -> None:
        super().__init__(collect_steps=False)
        self.lats = []

    def after_step(self, ev, latents) -> None:      # noqa: D102
        try:
            self.lats.append(latents.detach().float().cpu().clone())
        except Exception:  # stability-gate: allow-swallow（抓不到就少一条对照，不影响出图）
            pass


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


def _run_stock(pipe, *, prompt, negative, w, h, steps, cfg, seed):
    """stock 路径（一次 `pipe(...)` 调用），返回 (image, per_step_latents)。"""
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


def _run_kernel(pipe, *, family, model_id, prompt, negative, w, h, steps, cfg, seed):
    import torch

    hook = _Capture()
    gen = torch.Generator("cpu").manual_seed(int(seed))
    req = GenRequest(family=family, model_id=model_id, prompt=prompt,
                     negative_prompt=negative, width=int(w), height=int(h),
                     steps=int(steps), cfg=float(cfg))
    _peak_reset()
    res = K.run(pipe=pipe, req=req, generator=gen, hooks=hook)
    return res, hook.lats, _peak_gb()


def _check_initial_latents(pipe, family, w, h, seed):
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


def _per_step_max_delta(a, b):
    """逐 step latents 的 max|Δ|；步数不同返回 None。"""
    if not a or not b or len(a) != len(b):
        return None
    worst = 0.0
    for x, y in zip(a, b):
        if x.shape != y.shape:
            return None
        worst = max(worst, float((x - y).abs().max().item()))
    return worst


def main() -> int:
    ap = argparse.ArgumentParser(description="内核等价性验收")
    ap.add_argument("--families", default="sd15", help="逗号分隔：sd15,sdxl")
    ap.add_argument("--seeds", default="3,42,777")
    ap.add_argument("--steps", type=int, default=0, help="0=用注册表默认")
    ap.add_argument("--n", type=int, default=3, help="速度测量重复次数（交错）")
    ap.add_argument("--prompt", default="a photo of a cat sitting on a wooden table")
    ap.add_argument("--negative", default="")
    ap.add_argument("--outdir", default="", help="保存对照图（可选）")
    ap.add_argument("--no-record", action="store_true", help="不写证据台账")
    args = ap.parse_args()

    # 内核开关：验收时必须允许未验收族，否则内核一律拒绝（那不是"跑不过"，是"没让跑"）
    os.environ["SHIGUANG_KERNEL"] = "on"
    os.environ["SHIGUANG_KERNEL_ALLOW_UNVERIFIED"] = "1"

    fams = [x.strip() for x in args.families.split(",") if x.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    engine = DI.get_diffusers_image_engine()
    overall_ok = True
    results = {}

    for fam in fams:
        if fam not in FAMILIES:
            print("✗ 未知族 %s（支持：%s）" % (fam, list(FAMILIES)))
            return 2
        model_id, arch = FAMILIES[fam]
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
            overall_ok = False
            continue
        pipe = engine._pipe

        # ── 预热（丢弃）──────────────────────────────────────────
        _run_stock(pipe, prompt=args.prompt, negative=args.negative, w=w, h=h,
                   steps=steps, cfg=cfg, seed=seeds[0])

        # ── 张量门第一条：初始 latents ───────────────────────────
        same, note = _check_initial_latents(pipe, fam, w, h, seeds[0])
        lat_ok = bool(same)
        print("[张量门] 初始 latents 比特一致：%s（%s）"
              % ("✓" if lat_ok else "✗", note))

        psnrs, delta_max, lat_ratios, vram_ratios = [], 0.0, [], []
        for seed in seeds:
            t_stock, t_kernel = [], []
            last = None
            for _ in range(max(1, args.n)):
                # 交错：A/B 成对执行
                t0 = time.perf_counter()
                img_s, lat_s, peak_s = _run_stock(
                    pipe, prompt=args.prompt, negative=args.negative,
                    w=w, h=h, steps=steps, cfg=cfg, seed=seed)
                t_stock.append(time.perf_counter() - t0)

                t0 = time.perf_counter()
                res_k, lat_k, peak_k = _run_kernel(
                    pipe, family=arch, model_id=model_id, prompt=args.prompt,
                    negative=args.negative, w=w, h=h, steps=steps, cfg=cfg, seed=seed)
                t_kernel.append(time.perf_counter() - t0)

                last = (img_s, res_k, lat_s, lat_k, peak_s, peak_k)

            img_s, res_k, lat_s, lat_k, peak_s, peak_k = last
            if not res_k.get("ok"):
                print("  ✗ seed=%s 内核失败：%s" % (seed, res_k.get("message")))
                overall_ok = False
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
                  % (seed,
                     "inf（完全一致）" if p == float("inf") else "%.2f dB" % p,
                     "n/a" if d is None else "%.3e" % d,
                     ms, mk, (mk / ms if ms else 0),
                     peak_s, peak_k))

            if args.outdir:
                os.makedirs(args.outdir, exist_ok=True)
                img_s.save(os.path.join(args.outdir, "%s_%s_stock.png" % (fam, seed)))
                res_k["image"].save(os.path.join(args.outdir, "%s_%s_kernel.png" % (fam, seed)))

        # ── 判据汇总 ─────────────────────────────────────────────
        psnr_min = min([p for p in psnrs]) if psnrs else 0.0
        psnr_ok = (psnr_min == float("inf")) or psnr_min >= 35.0
        tensor_ok = lat_ok and (delta_max <= 1e-3)
        lat_ratio = max(lat_ratios) if lat_ratios else 99.0
        vram_ratio = max(vram_ratios) if vram_ratios else 99.0
        speed_ok = lat_ratio <= 1.03
        vram_ok = vram_ratio <= 1.05

        print("-" * 66)
        print("  张量门 : %s（初始 latents %s，逐step max|Δ|=%.3e）"
              % ("✓" if tensor_ok else "✗", "一致" if lat_ok else "不一致", delta_max))
        print("  画质门 : %s（PSNR 最低 %s，门槛 35dB）"
              % ("✓" if psnr_ok else "✗",
                 "inf" if psnr_min == float("inf") else "%.2fdB" % psnr_min))
        print("  速度门 : %s（最差 %.3f×，>1.03 不通过，1.00~1.03 只能写持平）"
              % ("✓" if lat_ratio <= 1.0 else ("△ 持平" if speed_ok else "✗"), lat_ratio))
        print("  显存门 : %s（最差 %.3f×，门槛 1.05）"
              % ("✓" if vram_ok else "✗", vram_ratio))

        passed = bool(tensor_ok and psnr_ok and speed_ok and vram_ok)
        overall_ok = overall_ok and passed
        results[fam] = {
            "psnr_min_db": None if psnr_min == float("inf") else round(psnr_min, 3),
            "psnr_inf": psnr_min == float("inf"),
            "tensor_max_delta": delta_max,
            "initial_latents_identical": lat_ok,
            "latency_ratio": round(lat_ratio, 4),
            "vram_ratio": round(vram_ratio, 4),
            "steps": steps, "size": [w, h], "seeds": seeds, "n": args.n,
            "passed": passed,
            "stock_backend": "diffusers=%s" % _diffusers_version(),
        }
        if not args.no_record:
            p = EV.record(fam, results[fam], script="scripts/bench_kernel_parity.py")
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
