# -*- coding: utf-8 -*-
"""验收证据台账（规范 §5.2 第 8 条：数字 + 来源脚本 + 日期）。

## 为什么证据落 JSON 文件而不是写死在 Python 里

写死在 Python 里的数字会**过期**：模型换了、驱动升了、权重文件重下了一次，
代码里的 35.2dB 还静静地写着，看起来像刚测的。落成 JSON 文件后：
  · 每条记录带 `measured_at` / `script` / `machine`，过期一眼可见；
  · `bench_kernel_parity.py` 每次跑都会覆盖并追加历史，不存在"手抄"环节；
  · 守卫可以查"verified 的族必须有未过期的证据"。

## 本模块只做两件事

1. `psnr(a, b)` —— 验收要用的 PSNR（自己实现 12 行，免得多一个 scikit-image 依赖）；
2. `record()/load()` —— 台账读写。

**不在这里放任何"计划值"。** 没测出来就是没有，不是填个好看的数字。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 证据台账位置（项目根相对）
EVIDENCE_PATH = os.path.join("docs", "knowledge", "kernel_evidence.json")

#: 记录超过这么多天就提示"该重测了"（不自动判红：机器不同节奏不同）
FRESH_DAYS = 120


def _root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # app/core/neural/kernel → 上溯 4 层到项目根
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))


def path() -> str:
    return os.path.join(_root(), EVIDENCE_PATH)


# ══════════════════════════════════════════════════════════════════
# PSNR
# ══════════════════════════════════════════════════════════════════

def psnr(a: Any, b: Any, *, data_range: float = 255.0) -> float:
    """两图 PSNR（dB）。完全相同返回 `float("inf")`。

    输入可以是 PIL.Image、numpy 数组或 torch 张量；统一转成 float64 numpy。
    **必须完全相同才返回 inf** —— 用 `> 1e9` 之类的阈值冒充"一致"会把
    "几乎一样"和"一模一样"混为一谈，而验收第一门要的正是"一模一样"。
    """
    import numpy as np

    arr_a = _to_numpy(a)
    arr_b = _to_numpy(b)
    if arr_a.shape != arr_b.shape:
        raise ValueError("尺寸不同无法比 PSNR：%s vs %s" % (arr_a.shape, arr_b.shape))
    diff = arr_a.astype(np.float64) - arr_b.astype(np.float64)
    mse = float(np.mean(diff * diff))
    if mse == 0.0:
        return float("inf")
    return float(10.0 * np.log10((data_range ** 2) / mse))


def _to_numpy(x: Any) -> Any:
    import numpy as np

    if isinstance(x, np.ndarray):
        return x
    if hasattr(x, "convert"):                      # PIL
        return np.asarray(x.convert("RGB"))
    if hasattr(x, "detach"):                       # torch
        t = x.detach().float().cpu()
        if t.ndim == 4:
            t = t[0]
        if t.ndim == 3 and t.shape[0] in (1, 3):   # CHW → HWC
            t = t.permute(1, 2, 0)
        return t.numpy()
    return np.asarray(x)


# ══════════════════════════════════════════════════════════════════
# 台账
# ══════════════════════════════════════════════════════════════════

def load() -> Dict[str, Any]:
    """读台账；不存在返回空结构（**不报错**：没测过是正常状态）。"""
    p = path()
    if not os.path.isfile(p):
        return {"version": 1, "families": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "families": {}}
        data.setdefault("version", 1)
        data.setdefault("families", {})
        return data
    except Exception:  # stability-gate: allow-swallow（台账损坏时按"没证据"处理：宁可判未验收，不可读到假数据）
        logger.warning("[kernel.evidence] 证据台账无法解析，按空处理：%s", p, exc_info=True)
        return {"version": 1, "families": {}}


def record(family: str, data: Dict[str, Any], *, script: str = "") -> str:
    """写入一次验收记录（同名族覆盖，历史追加到 `history`）。返回台账路径。"""
    doc = load()
    fam = doc["families"].setdefault(str(family), {})
    entry = dict(data)
    entry["measured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry["script"] = script or entry.get("script", "")
    entry["machine"] = entry.get("machine") or _machine()
    hist = fam.get("history") or []
    # 历史条目要能回答"这次比上次好在哪/差在哪"，所以按**判据**投影，不整条拷贝。
    # 视频族的 `frames_match` / `cancelled_ok` 必须进历史：否则"帧数对不上"这种事
    # 只留在被下一次覆盖的顶层字段里，翻历史时看不见它曾经红过。
    hist.append({k: entry.get(k) for k in (
        "measured_at", "kind", "psnr_min_db", "frame_psnr_min_db", "latency_ratio",
        "vram_ratio", "tensor_max_delta", "frames_match", "cancelled_ok",
        "passed", "script")})
    fam.update(entry)
    fam["history"] = hist[-20:]
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return p


def _machine() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            return "%s / torch %s / cuda %s" % (name, torch.__version__,
                                                torch.version.cuda)
        return "cpu-only / torch %s" % torch.__version__
    except Exception:  # stability-gate: allow-swallow（只用于标注来源，取不到就写 unknown）
        return "unknown"


def stale_families(days: int = FRESH_DAYS) -> List[str]:
    """超过 `days` 天未重测的族（守卫用来提示，不直接判红）。"""
    doc = load()
    out: List[str] = []
    now = time.time()
    for fam, rec in (doc.get("families") or {}).items():
        ts = rec.get("measured_at") or ""
        try:
            t = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:  # stability-gate: allow-swallow（时间格式不认识 ⇒ 当作过期，提示重测）
            out.append(fam)
            continue
        if (now - t) / 86400.0 > days:
            out.append(fam)
    return out


def summary() -> Dict[str, Any]:
    doc = load()
    fams = doc.get("families") or {}
    return {
        "path": EVIDENCE_PATH,
        "families": {
            fam: {
                "kind": rec.get("kind"),
                "measured_at": rec.get("measured_at"),
                "psnr_min_db": rec.get("psnr_min_db"),
                "frame_psnr_min_db": rec.get("frame_psnr_min_db"),
                "frames_match": rec.get("frames_match"),
                "cancelled_ok": rec.get("cancelled_ok"),
                "tensor_max_delta": rec.get("tensor_max_delta"),
                "latency_ratio": rec.get("latency_ratio"),
                "vram_ratio": rec.get("vram_ratio"),
                "passed": rec.get("passed"),
            }
            for fam, rec in fams.items()
        },
        "stale": stale_families(),
    }


def has_fresh_evidence(family: str, days: int = FRESH_DAYS) -> Optional[bool]:
    """该族是否有"新鲜且通过"的证据。None = 完全没有记录。"""
    doc = load()
    rec = (doc.get("families") or {}).get(str(family))
    if not rec:
        return None
    if not rec.get("passed"):
        return False
    return str(family) not in stale_families(days)
