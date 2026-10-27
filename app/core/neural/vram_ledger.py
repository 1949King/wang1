# -*- coding: utf-8 -*-
"""跨模态显存账本（vram ledger）—— 5 分项归因（P0 · 2026-10-28）

它要回答的那一问
================
项目已经能测「峰值多少 GB」（`calibration.effective_peak_gb`），但答不了：

    **省下来的到底是权重、激活、还是解码？**

没有这个答案，「int8 省 43%」这种数字无法被质疑、也无法被复用——
2026-10-27 的实测就是教训：SDXL 的 UNet 4.78GB → 2.71GB（−43.4%）看着漂亮，
结果 PSNR 5.29dB、整张全黑（见 `quant_descriptor` 台账）。
**只报峰值不报归因，等于只报结论不报依据。**

5 个分项（架构文档 §3 定的口径，不许改名）
==========================================
``weight``      权重驻留（UNet / DiT 参数在卡上的部分）
``activation``  前向激活（含 CFG batch 展开）
``cache``       步级/编码缓存（`inference_cache.StepFeatureCache` 这类）
``decode``      VAE 解码（分块解码的瞬时峰值往往在这里）
``encoder``     条件编码（CLIP / T5，Wan 的 umt5-xxl 能到 10.58GB）

★ 一条必须写死的口径：**分项不可相加当峰值**
=============================================
峰值是「时间轴上的最大值」，分项是「每个阶段自己的增量峰值」——
两个不同维度的量。举例：权重占 2GB 一直在卡上，解码阶段又瞬时加 3GB，
峰值 5GB，两项之和也 5GB，看着刚好；但如果**权重在解码前被换出**，
两项之和 5GB 而真实峰值只有 3GB。反过来，缓存跨阶段复用时之和会小于峰值。
故本账本同时给出三个数，缺一个就会误导：

  · ``peak_gb``        真实峰值（时间轴最大值）—— **水位判定只看这个**
  · ``attributed_gb``  分项之和 —— 只用来看「大头是谁」
  · ``residual_gb``    ``peak − attributed`` —— 正数 = 未归因（含框架开销），
                       负数 = 阶段间有回收（`reclaim_gb` 记其绝对值）

纪律
====
· **纯 stdlib、零 torch**：读数靠注入的 reader（`snapshot/peak/reset_peak`），
  真机 reader 由 `torch_reader()` 在函数内惰性 import torch 构造（同 `memory_policy.probe_vram` 的戒律）。
· **不决定档位**：档位决策在 `memory_policy`。账本只记账，越权就变成第二个决策点。
· **测不出就报 None**：reader 缺失或读数异常一律 `None`，绝不回退成 0（0 会被读成"不占显存"）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 5 个分项（架构文档 §3 定的口径，改名即违约）
ITEMS: Tuple[str, ...] = ("weight", "activation", "cache", "decode", "encoder")

#: K4 门槛（峰值比 vs stock），见架构文档 §8
K4_MAX_RATIO_IMAGE = 1.05
K4_MAX_RATIO_VIDEO = 1.10


def _gb(x: Any) -> Optional[float]:
    """字节 → GB；拿不到给 None（不编 0）。"""
    try:
        if x is None:
            return None
        return round(float(x) / (1024 ** 3), 3)
    except (TypeError, ValueError):
        return None


@dataclass
class Snapshot:
    """一次读数（GB）。allocated = 分配器口径，reserved = 缓存池口径。"""

    allocated_gb: float
    reserved_gb: float

    @property
    def effective_gb(self) -> float:
        """与 `calibration.effective_peak_gb` 同口径：取二者较大者。

        只看 allocated 会漏掉碎片膨胀（实测 1024² 下 reserved 比 allocated 高 70%），
        只看 reserved 会把可回收缓存当死占用。取大者 = 宁保守勿乐观。
        """
        return max(float(self.allocated_gb), float(self.reserved_gb))


class _DictReader:
    """测试与离线复算用的假 reader。

    刻意做成**两条独立序列**（快照按次取、峰值按次取），因为真实 reader
    在 `enter` 时会 `reset_peak()`，两者本来就不同步。用单序列会让测试
    只能写出「恰好都对」的场景，掩盖口径 bug。
    """

    def __init__(self, samples: List[Tuple[float, float]],
                 peaks: Optional[List[float]] = None) -> None:
        self._samples = list(samples or [(0.0, 0.0)])
        self._peaks = list(peaks or [0.0])
        self._si = 0
        self._pi = 0
        self.resets = 0

    def snapshot(self) -> Tuple[float, float]:
        s = self._samples[min(self._si, len(self._samples) - 1)]
        self._si += 1
        return s

    def peak(self) -> float:
        v = float(self._peaks[min(self._pi, len(self._peaks) - 1)])
        self._pi += 1
        return v

    def reset_peak(self) -> None:
        self.resets += 1


def torch_reader(device: str = "cuda") -> Any:
    """真机 reader：读 torch.cuda 的 allocated / reserved / max_allocated。

    torch 在**函数内**才 import —— 本模块顶层必须零 torch，
    否则画布 HTTP 线程与门禁脚本都会被拖进重依赖。
    """
    import torch

    class _TorchReader:
        def snapshot(self) -> Tuple[float, float]:
            alloc = torch.cuda.memory_allocated() / 1024 ** 3
            resv = torch.cuda.memory_reserved() / 1024 ** 3
            return float(alloc), float(resv)

        def peak(self) -> float:
            a = float(torch.cuda.max_memory_allocated()) / 1024 ** 3
            r = float(torch.cuda.max_memory_reserved()) / 1024 ** 3
            return max(a, r)

        def reset_peak(self) -> None:
            torch.cuda.reset_peak_memory_stats()

    return _TorchReader()


@dataclass
class VramLedger:
    """一次运行的 5 分项记账。

    用法（配合既有 `diffusers_image.generate()` / 未来 kernel loop）::

        led = VramLedger(torch_reader(), model_id="sdxl-t2i")
        led.begin()
        led.enter("encoder");  ...编码...;  led.leave("encoder")
        led.enter("weight");   ...加载/上卡...;  led.leave("weight")
        led.enter("activation"); ...denoise...; led.leave("activation")
        led.enter("decode");   ...vae...;  led.leave("decode")
        out = led.close()      # → {"peak_gb":…, "weight_gb":…, "notes":[…]}

    ``enter`` 会 `reset_peak()`，于是每阶段拿到的是**该阶段自己的峰值**；
    ``leave`` 记增量 = 阶段峰值 − 阶段起点。**跨阶段峰值由 `close()` 用各阶段峰值求最大**
    —— 因为 reader 的 peak 已被逐阶段重置，不能直接读全局。
    """

    reader: Any = None
    model_id: str = ""
    kind: str = "image"                 # image | video（只影响 K4 门槛）
    _open: bool = field(default=False, repr=False)
    _baseline_gb: Optional[float] = field(default=None, repr=False)
    _stage_start: Dict[str, float] = field(default_factory=dict, repr=False)
    _stage_peak: Dict[str, float] = field(default_factory=dict, repr=False)
    _items: Dict[str, Optional[float]] = field(default_factory=dict, repr=False)
    _notes: List[str] = field(default_factory=list, repr=False)
    _missing: List[str] = field(default_factory=list, repr=False)
    _last: Optional[Dict[str, Any]] = field(default=None, repr=False)

    # ── 读数 ──
    def _snap(self) -> Optional[Snapshot]:
        if self.reader is None:
            return None
        try:
            a, r = self.reader.snapshot()
            return Snapshot(allocated_gb=float(a), reserved_gb=float(r))
        except Exception:
            logger.debug("[vram_ledger] 读数失败", exc_info=True)
            return None

    def _peak(self) -> Optional[float]:
        if self.reader is None:
            return None
        try:
            return float(self.reader.peak())
        except Exception:
            return None

    def _reset(self) -> None:
        try:
            self.reader.reset_peak()
        except Exception:
            logger.debug("[vram_ledger] reset_peak 失败（分项会偏高）", exc_info=True)

    # ── 生命周期 ──
    def begin(self) -> "VramLedger":
        """开账：记基线并把阶段峰值清零。"""
        snap = self._snap()
        self._baseline_gb = snap.effective_gb if snap else None
        self._open = True
        self._items.clear()
        self._stage_start.clear()
        self._stage_peak.clear()
        self._notes.clear()
        self._missing.clear()
        self._last = None
        if snap is None:
            self._notes.append("无 reader 或读数失败 ⇒ 仅记录阶段名，不报数字")
        self._reset()
        return self

    def enter(self, item: str) -> None:
        """进入某阶段（item 必须是 :data:`ITEMS` 之一）。"""
        name = self._check_item(item)
        snap = self._snap()
        floor = self._baseline_gb if self._baseline_gb is not None else 0.0
        self._stage_start[name] = snap.effective_gb if snap else floor
        self._reset()

    def leave(self, item: str) -> None:
        """离开某阶段：记该阶段自己的峰值增量。"""
        name = self._check_item(item)
        peak = self._peak()
        start = self._stage_start.get(name)
        if peak is None or start is None:
            self._items[name] = None
            self._missing.append(name)
            return
        self._stage_peak[name] = peak
        self._items[name] = round(max(0.0, peak - float(start)), 3)

    def _check_item(self, item: str) -> str:
        name = str(item or "").strip().lower()
        if name not in ITEMS:
            # 拼错的分项会被静默丢掉 ⇒ 账本悄悄少一项，这是最坏的失败方式
            raise ValueError("未知显存分项 %r，合法值：%s" % (item, ", ".join(ITEMS)))
        return name

    # ── 结算 ──
    def close(self) -> Dict[str, Any]:
        """结算：5 分项 + 峰值 + 残差 + K4 判定输入。可重复调用（第二次起返回同一份）。"""
        if self._last is not None:
            return self._last
        # 跨阶段峰值：各阶段峰值取最大（reader.peak 已被逐阶段 reset）
        cands = [v for v in self._stage_peak.values() if v is not None]
        tail = self._snap()
        if tail is not None:
            cands.append(tail.effective_gb)
        peak = round(max(cands), 3) if cands else None

        attributed: Optional[float] = None
        # 只有 5 项**全部**测到才算得出分项和；缺一项就报 None
        # （拿 3 项的和冒充 5 项，等于给一个不能用的数）
        if all(self._items.get(k) is not None for k in ITEMS):
            vals = [v for v in self._items.values() if v is not None]
            attributed = round(sum(vals), 3) if vals else None

        residual: Optional[float] = None
        reclaim: Optional[float] = None
        if peak is not None and attributed is not None:
            d = round(peak - attributed, 3)
            if d >= 0:
                residual = d
            else:
                reclaim = round(-d, 3)
                self._notes.append(
                    "阶段间发生回收：分项之和 %.3fGB > 峰值 %.3fGB ⇒ **分项不可相加当峰值**"
                    % (attributed, peak))

        out: Dict[str, Any] = {("%s_gb" % k): self._items.get(k) for k in ITEMS}
        out.update({
            "model_id": self.model_id,
            "kind": self.kind,
            "peak_gb": peak,
            "baseline_gb": self._baseline_gb,
            "attributed_gb": attributed,
            "residual_gb": residual,
            "reclaim_gb": reclaim,
            "missing": list(self._missing),
            "notes": list(self._notes),
        })
        self._open = False
        self._last = out
        return out

    # ── K4 ──
    def ratio_vs(self, baseline_peak_gb: Optional[float],
                 kind: str = "") -> Tuple[Optional[float], str, str]:
        """K4 显存比：本次峰值 / 基线峰值。返回 ``(ratio, verdict, why)``。

        verdict ∈ ``pass`` / ``over`` / ``unknown``。
        ``unknown`` 时**不猜**（基线缺失或本次没测到），并说明缺什么。
        """
        me = self.close().get("peak_gb")
        base = baseline_peak_gb
        k = (kind or self.kind or "image").lower()
        limit = K4_MAX_RATIO_VIDEO if k == "video" else K4_MAX_RATIO_IMAGE
        if me is None or not base:
            return None, "unknown", (
                "无法判定：本次峰值=%s，基线峰值=%s" % (me, base))
        ratio = round(float(me) / float(base), 3)
        if ratio <= limit:
            return ratio, "pass", "%.3f ≤ %.2f（K4）" % (ratio, limit)
        return ratio, "over", "%.3f > %.2f（K4 超限，%s）" % (ratio, limit, k)


def dict_reader(samples: List[Tuple[float, float]],
                peaks: Optional[List[float]] = None) -> Any:
    """构造一个离线 reader（测试 / 复算历史数据用）。"""
    return _DictReader(samples, peaks)


def describe(ledger: Dict[str, Any]) -> str:
    """一页账（日志/CLI）。缺失项如实写「未测」，不写 0。"""
    lines = ["显存账本 %s（%s）" % (ledger.get("model_id") or "?", ledger.get("kind"))]
    for k in ITEMS:
        v = ledger.get("%s_gb" % k)
        lines.append("  · %-10s %s" % (k, "未测" if v is None else "%.3f GB" % v))
    lines.append("  峰值 %s ｜ 分项和 %s ｜ 残差 %s ｜ 回收 %s"
                 % (ledger.get("peak_gb"), ledger.get("attributed_gb"),
                    ledger.get("residual_gb"), ledger.get("reclaim_gb")))
    for n in ledger.get("notes") or []:
        lines.append("  ! %s" % n)
    return "\n".join(lines)
