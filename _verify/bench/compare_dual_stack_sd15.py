# -*- coding: utf-8 -*-
"""M1/M2 双栈对比实测（子进程）：同一 SD1.5 权重文件，自研(diffusers) vs 主选(DiffSynth)。

★ 已入库（刀 A1，2026-10-04，自 .workbuddy/tmp 迁入）：M1/M2 第一组基准可复测。
  运行：`python _verify/bench/compare_dual_stack_sd15.py`（需 GPU + 权重在盘）。

口径（路线图 V2 §2.3）：
  M1 = 自研峰值显存 ≤ 主选 × 110%（torch.cuda.max_memory_allocated，load+generate 全程）
  M2 = 自研 generate 耗时 ≥ 主选 × 80%（注意口径是「不慢于 80%」即比值 ≤ 125%）

★ 参数集中写死（两栈共用同一份常量，防「双栈漂移」）。
★ 每栈跑前 unload + empty_cache + reset_peak_memory_stats（冷态公平）。
★ 同 seed 出图**不像素一致**（两栈噪声生成器不同）—— 比显存/耗时/质量观感。
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# ── 两栈共用参数（单点常量，勿分散）──
COMMON = {
    "prompt": "masterpiece, best quality, 1girl, anime style, standing in a sunlit garden, "
              "flowing dress, detailed background",
    "negative_prompt": "lowres, bad anatomy, bad hands, text, error, blurry",
    "seed": 42,
    "steps": 20,
    "cfg": 7.5,
}
MID = "sd15-t2i"
OUT_DIR = os.path.join(".workbuddy", "tmp")


def _peak_gb() -> float:
    import torch
    return round(torch.cuda.max_memory_allocated() / (1024 ** 3), 2)


def _reset_peak() -> None:
    import torch
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()


def run_selfbuilt() -> dict:
    from app.core.neural.diffusers_image import get_diffusers_image_engine
    eng = get_diffusers_image_engine()
    eng.unload()
    _reset_peak()
    t0 = time.time()
    r_load = eng.load(MID)
    t_load = round(time.time() - t0, 1)
    if not r_load["ok"]:
        return {"ok": False, "message": r_load["message"]}
    t0 = time.time()
    g = eng.generate(MID, out_path=os.path.join(OUT_DIR, "sd15_selfbuilt.png"), **COMMON)
    t_gen = round(time.time() - t0, 1)
    peak = _peak_gb()
    eng.unload()
    return {"ok": g["ok"], "t_load": t_load, "t_gen": t_gen, "peak_gb": peak,
            "offload": eng._offload, "message": g.get("message", "")}


def run_primary() -> dict:
    from app.core.neural.diffsynth_image import get_image_engine
    eng = get_image_engine()
    eng.unload()
    _reset_peak()
    t0 = time.time()
    r_load = eng.load(MID)
    t_load = round(time.time() - t0, 1)
    if not r_load["ok"]:
        return {"ok": False, "message": r_load["message"]}
    t0 = time.time()
    g = eng.generate(MID, out_path=os.path.join(OUT_DIR, "sd15_primary.png"), **COMMON)
    t_gen = round(time.time() - t0, 1)
    peak = _peak_gb()
    eng.unload()
    return {"ok": g["ok"], "t_load": t_load, "t_gen": t_gen, "peak_gb": peak,
            "message": g.get("message", "")}


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=== 自研栈（diffusers from_single_file）===")
    a = run_selfbuilt()
    print(a)
    print("=== 主选栈（DiffSynth SDImagePipeline）===")
    b = run_primary()
    print(b)
    if not (a.get("ok") and b.get("ok")):
        print("COMPARE-FAIL")
        return 1
    m1_ratio = a["peak_gb"] / b["peak_gb"] if b["peak_gb"] else float("inf")
    m2_ratio = a["t_gen"] / b["t_gen"] if b["t_gen"] else float("inf")
    print("=== M1/M2 首批实测 ===")
    print(f"峰值显存：自研 {a['peak_gb']}GB / 主选 {b['peak_gb']}GB "
          f"⇒ M1 比值 {m1_ratio:.2f}（门 ≤1.10：{'PASS' if m1_ratio <= 1.10 else 'FAIL'}）")
    print(f"生成耗时：自研 {a['t_gen']}s / 主选 {b['t_gen']}s "
          f"⇒ M2 比值 {m2_ratio:.2f}（门 ≤1.25：{'PASS' if m2_ratio <= 1.25 else 'FAIL'}）")
    print(f"加载耗时：自研 {a['t_load']}s / 主选 {b['t_load']}s（参考，不计门）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
