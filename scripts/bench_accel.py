# -*- coding: utf-8 -*-
"""加速基准台：python scripts/bench_accel.py [--steps 8] [--json]

只跑**本机可用**的项；缺依赖打印 SKIP（退出码 0，不误报失败）。
结果写 data/accel_bench.json，供文档引用。
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.neural import accel_status as AS


def _arg(name: str, default: str) -> str:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _bench_pipe(pipe, steps: int, prompt: str = "a cat on grass") -> float:
    import torch

    torch.cuda.synchronize()
    t0 = time.perf_counter()
    with torch.no_grad():
        pipe(prompt=prompt, num_inference_steps=steps, guidance_scale=7.5,
             height=512, width=512).images[0]
    torch.cuda.synchronize()
    return round((time.perf_counter() - t0) * 1000, 1)


def main() -> int:
    steps = int(_arg("--steps", "8"))
    st = AS.status()
    out = {"steps": steps, "device": st["device"], "runs": {}, "skips": {}, "ratios": {}}

    try:
        from app.core.neural.diffusers_image import get_diffusers_image_engine

        eng = get_diffusers_image_engine()
        r = eng.load("sd15-t2i")
        if not r.get("ok"):
            print("SKIP 引擎不可用：", r.get("message"))
            return 0
        pipe = eng._pipe
    except Exception as e:
        print("SKIP 引擎加载失败：", f"{type(e).__name__}: {e}")
        return 0

    _bench_pipe(pipe, steps)  # 预热
    base = _bench_pipe(pipe, steps)
    out["runs"]["baseline"] = base
    print(f"BASELINE {base}ms（{base / steps:.1f} ms/步）")

    # 整卡驻留对照：消除 offload 空隙（这是本机最大的一块，实测 ~1.5×）
    try:
        if hasattr(pipe, "remove_all_hooks"):
            pipe.remove_all_hooks()
        pipe.to("cuda")
        _bench_pipe(pipe, steps)
        whole = _bench_pipe(pipe, steps)
        out["runs"]["whole_gpu"] = whole
        out["ratios"]["whole_gpu"] = round(base / whole, 2)
        print(f"WHOLE_GPU {whole}ms · 相对基线 {base / whole:.2f}×")
    except Exception as e:
        out["skips"]["whole_gpu"] = f"{type(e).__name__}: {e}"
        print("SKIP whole_gpu：", out["skips"]["whole_gpu"])

    if st["fp8"]["ok"]:
        try:
            eng.request_precision("fp8")
            if eng.load("sd15-t2i").get("ok"):
                _bench_pipe(eng._pipe, steps)
                fp8 = _bench_pipe(eng._pipe, steps)
                out["runs"]["fp8"] = fp8
                out["ratios"]["fp8"] = round(base / fp8, 2)
                print(f"FP8 {fp8}ms · 相对基线 {base / fp8:.2f}×")
        except Exception as e:
            out["skips"]["fp8"] = f"{type(e).__name__}: {e}"
            print("SKIP fp8：", out["skips"]["fp8"])
    else:
        out["skips"]["fp8"] = st["fp8"]["reason"]
        print("SKIP fp8：", st["fp8"]["reason"])
        print("    修复：", AS.install_hint()["fp8"])

    for key in ("int4", "compile", "tensorrt"):
        if not st[key]["ok"]:
            out["skips"][key] = st[key]["reason"]
            print(f"SKIP {key}：", st[key]["reason"])
            print("    修复：", AS.install_hint()[key])

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    pj = os.path.join(ROOT, "data", "accel_bench.json")
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n写入", pj)
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
