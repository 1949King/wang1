# -*- coding: utf-8 -*-
"""fp8 · SDXL 真机基准（2026-10-25）。

前置：Ada/Hopper/Blackwell + 安装 torchao + SDXL 权重已下载。
缺失任一条件 ⇒ 打印 SKIP 并退出 0（不误报、不假装跑过）。

用法：
    python _verify/bench/bench_fp8_sdxl.py
    FP8_PROMPT="a cat on grass" python _verify/bench/bench_fp8_sdxl.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def main() -> int:
    from app.core.neural import diffusers_image as D
    from app.core.neural import quant_policy as QP

    probe = QP.probe_usable()
    if not probe.get("usable_fp8"):
        print("SKIP 当前环境 fp8 不可用（需 Ada/Hopper/Blackwell + torchao）：", probe)
        return 0
    if not D.DiffusersImageEngine.is_downloaded("sdxl-t2i"):
        print("SKIP SDXL 权重未下载")
        return 0

    eng = D.get_diffusers_image_engine()
    eng.request_precision("fp8")
    res = eng.generate(
        "sdxl-t2i",
        prompt=os.environ.get("FP8_PROMPT", "portrait of a woman, soft light"),
        width=1024, height=1024, steps=20, out_path="短剧AI剪辑输出/_bench_fp8_sdxl.png")
    print("fp8 ok=%s precision=%s seconds=%s message=%s" % (
        res.get("ok"), res.get("precision"), res.get("seconds_elapsed"),
        res.get("message")))
    eng.request_precision("")
    eng.unload()
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
