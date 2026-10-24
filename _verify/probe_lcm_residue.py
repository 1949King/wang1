# -*- coding: utf-8 -*-
"""LCM-LoRA 档位残留探针（2026-10-25 标定期间发现的疑似生产 bug 取证）。

疑点（代码级，diffusers_image.py）
==============================
`generate()` 的质量档位分流（约 676-690 行）：
    pre = resolve_preset(model_id, preset)
    if pre["preset"]:
        if pre["sampler"] == "lcm":
            ok_l, why = self.enable_lcm(model_id)     # 只有 lcm 档装载 LoRA
        self._apply_sampler(pre["sampler"])           # 任何档位都只换调度器
`_apply_sampler()`（977-1000 行）在切到 dpm/default 时**只换 scheduler**，
不卸载 LoRA；`unload()` 之外的任何路径都不清 `self._lcm`。
⇒ 同一会话里先跑 fast（LCM 8 步 cfg1.0）再跑 high（DPM++ 12 步 cfg7.5），
   high 会带着权重 1.0 的 LCM-LoRA 跑 cfg 7.5——LCM-LoRA 的训练域是 cfg≈1，
   这是 off-distribution 推理。V4.46.8 的 high 档标定（CLIP 97.5%）是在干净
   进程里测的，生产会话拿不到那个数。

本探针取证三步
============
  ① fast 跑一次（触发 enable_lcm）→ 记录 unet.peft_config / 引擎 _lcm 状态；
  ② high 跑一次 → 再记录：LoRA 是否仍挂着（bug 判据）；
  ③ 全新引擎实例跑同一 seed 的 high（从未装过 LoRA）→ 与 ② 出图对比
     （PSNR + CLIP）：有差异 = 残留真的改了画，不是无害的理论问题。

用法：.venv312/Scripts/python.exe -u _verify/probe_lcm_residue.py
输出：.workbuddy/tmp/bench/p0/probe_lcm_residue_<ts>.json + 样图。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

OUT_DIR = os.path.join(ROOT, ".workbuddy", "tmp", "bench", "p0")
PROMPT = "a cinematic portrait of a woman in a red dress, soft rim light, 35mm"
NEG = "blurry, low quality, deformed, watermark"
SEED = 4242


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _adapters(pipe: Any) -> Dict[str, Any]:
    """LoRA 挂载状态：peft_config 键 + 活动适配器（diffusers 0.40 PeftAdapterMixin）。"""
    unet = getattr(pipe, "unet", None)
    out: Dict[str, Any] = {"peft_config_keys": [], "active": None}
    if unet is None:
        return out
    pc = getattr(unet, "peft_config", None)
    if isinstance(pc, dict):
        out["peft_config_keys"] = sorted(pc.keys())
    getter = getattr(unet, "get_active_adapters", None)
    if callable(getter):
        try:
            out["active"] = getter()
        except Exception:
            out["active"] = "查询失败"
    return out


def _psnr(path_a: str, path_b: str) -> float:
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(path_a).convert("RGB"), dtype=np.float64)
    b = np.asarray(Image.open(path_b).convert("RGB"), dtype=np.float64)
    if a.shape != b.shape:
        return -1.0
    mse = float(((a - b) ** 2).mean())
    if mse <= 0:
        return float("inf")
    return round(10.0 * np.log10(255.0 ** 2 / mse), 2)


def main() -> int:
    os.environ["SHIGUANG_HOT_PROMOTE"] = "0"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.makedirs(OUT_DIR, exist_ok=True)
    tag = "probe_lcm_residue_%s" % _ts()
    bench_dir = os.path.join(OUT_DIR, tag)
    os.makedirs(bench_dir, exist_ok=True)

    import app.core.neural.diffusers_image as DIF

    data: Dict[str, Any] = {"phase": "probe_lcm_residue", "prompt": PROMPT,
                            "seed": SEED, "steps": []}

    # ── 会话 A：先 fast（装 LoRA）再 high（疑点档位）──
    eng = DIF.get_diffusers_image_engine()
    t0 = time.time()
    lr = eng.load("sdxl-t2i")
    data["load_s"] = round(time.time() - t0, 1)
    print("[probe] load ok=%s offload=%s" % (lr.get("ok"), getattr(eng, "_offload", "?")))
    if not lr.get("ok"):
        print("[probe] 加载失败：%s" % lr.get("message"))
        return 2

    f_fast = os.path.join(bench_dir, "A_fast.png")
    r1 = eng.generate("sdxl-t2i", prompt=PROMPT, negative_prompt=NEG, seed=SEED,
                      preset="fast", out_path=f_fast)
    st1 = {"step": "A.fast", "ok": bool(r1.get("ok")), "seconds": r1.get("seconds_elapsed"),
           "engine_lcm": bool(getattr(eng, "_lcm", False)),
           "engine_lora": str(getattr(eng, "_lcm_lora", "")),
           "adapters": _adapters(eng._pipe)}
    data["steps"].append(st1)
    print("[probe] A.fast ok=%s · engine._lcm=%s · adapters=%s" % (
        r1.get("ok"), st1["engine_lcm"], st1["adapters"]))

    f_high = os.path.join(bench_dir, "A_high.png")
    r2 = eng.generate("sdxl-t2i", prompt=PROMPT, negative_prompt=NEG, seed=SEED,
                      preset="high", out_path=f_high)
    st2 = {"step": "A.high", "ok": bool(r2.get("ok")), "seconds": r2.get("seconds_elapsed"),
           "engine_lcm": bool(getattr(eng, "_lcm", False)),
           "engine_lora": str(getattr(eng, "_lcm_lora", "")),
           "adapters": _adapters(eng._pipe)}
    data["steps"].append(st2)
    print("[probe] A.high ok=%s · engine._lcm=%s · adapters=%s" % (
        r2.get("ok"), st2["engine_lcm"], st2["adapters"]))

    # ── 会话 B：全新引擎实例，直接 high（从未装 LoRA）──
    eng.unload()
    time.sleep(1.0)
    eng2 = DIF.DiffusersImageEngine()
    lr2 = eng2.load("sdxl-t2i")
    print("[probe] B.load ok=%s（全新实例）" % lr2.get("ok"))
    f_fresh = os.path.join(bench_dir, "B_high_fresh.png")
    r3 = eng2.generate("sdxl-t2i", prompt=PROMPT, negative_prompt=NEG, seed=SEED,
                       preset="high", out_path=f_fresh)
    st3 = {"step": "B.high_fresh", "ok": bool(r3.get("ok")),
           "seconds": r3.get("seconds_elapsed"),
           "engine_lcm": bool(getattr(eng2, "_lcm", False)),
           "adapters": _adapters(eng2._pipe)}
    data["steps"].append(st3)
    print("[probe] B.high_fresh ok=%s · adapters=%s" % (r3.get("ok"), st3["adapters"]))

    # ── 判定 ──
    residue = bool(st2["adapters"]["peft_config_keys"])
    data["verdict"] = {
        "lora_residue_after_high": residue,
        "residue_keys": st2["adapters"]["peft_config_keys"],
        "images_differ_psnr": _psnr(f_high, f_fresh) if (r2.get("ok") and r3.get("ok"))
                              else None,
        "fast_seconds": r1.get("seconds_elapsed"),
        "high_after_fast_seconds": r2.get("seconds_elapsed"),
        "high_fresh_seconds": r3.get("seconds_elapsed"),
    }
    v = data["verdict"]
    print("\n=== LCM 残留判定 ===")
    print("  high 跑完后 LoRA 仍挂载：%s（keys=%s）" % (residue, v["residue_keys"]))
    print("  A.high vs B.high_fresh 同 seed PSNR：%s dB"
          % (v["images_differ_psnr"] if v["images_differ_psnr"] is not None else "n/a"))
    print("  耗时：fast %ss · high(带残留) %ss · high(干净) %ss" % (
        v["fast_seconds"], v["high_after_fast_seconds"], v["high_fresh_seconds"]))
    if residue and v["images_differ_psnr"] is not None and v["images_differ_psnr"] != float("inf"):
        print("  ⇒ **残留 bug 证实**：生产会话里 fast→high 的 high 出图被 LCM-LoRA 改变")
    elif residue:
        print("  ⇒ 残留存在但出图未变（权重被调度器抵消？需人工看样图）")
    else:
        print("  ⇒ 未发现残留（疑点不成立，记录备查）")

    path = os.path.join(OUT_DIR, "%s.json" % tag)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("JSON: %s" % path)
    print("样图: %s" % bench_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
