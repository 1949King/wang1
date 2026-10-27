# -*- coding: utf-8 -*-
"""自适应标定：让引擎装到未知设备上，自己把档位找对。

设计依据见 `docs/design/自适应标定设计.md`，本文件对应 P1 阶段：
  D-A1 只测「能不能跑 + 多快」，不测画质
  D-A2 阶梯爬升，不做网格搜索
  D-A3 失败零成本回退
  D-A4 档案可失效
  D-A5 后台标定，不阻塞首次使用
  D-A6 图像结果可外推给视频

**本模块不 import torch**（与 `quant_descriptor` 同款约束）：
真跑一次推理这件事由调用方以 `probe_run` 回调注入，
因此本文件可在画布 HTTP 线程里安全使用，也能纯逻辑单测。

调用范式
--------
    from app.core.neural import calibration as CAL
    from app.core.neural import device_profile

    prof = device_profile.probe()
    ok, why = CAL.admit(prof)
    if not ok:
        ... # 诚实拒绝，展示 why

    store = CAL.CalibrationStore()          # data/calibration.json
    cal = CAL.Calibrator(store, prof, probe_run=my_probe)
    entry = cal.best_for("sdxl-base", res=(1024, 1024))   # 命中档案则秒回
    cal.start_background("sdxl-base", res=(1024, 1024))   # 未命中则后台爬
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ── 准入门槛（设计文档 §1.2，2026-10-28 定稿）──────────────────────────────
MIN_VRAM_GB = 8.0

# ── 档位阶梯：从最保守 → 最激进（设计文档 D-A2）──────────────────────────
# 值为 memory_policy.MODE_* 的同名字符串。此处独立定义是为了保持本模块
# 零依赖；一致性由 test_calibration.test_ladder_matches_memory_policy 双向守卫。
MODE_LAYER_CPU_OFFLOAD = "layer_cpu_offload"
MODE_SEQUENTIAL_OFFLOAD = "sequential_offload"
MODE_MODEL_OFFLOAD = "model_offload"
MODE_WHOLE_GPU = "whole_gpu"

#: 保守在前。第一个失败的上一档即答案。
LADDER: Tuple[str, ...] = (
    MODE_LAYER_CPU_OFFLOAD,
    MODE_SEQUENTIAL_OFFLOAD,
    MODE_MODEL_OFFLOAD,
    MODE_WHOLE_GPU,
)

# ── 档案 ───────────────────────────────────────────────────────────────────
CALIB_VERSION = 1

#: 证据来源三态。**禁止把 derived 标成 measured**（设计文档 §4.2 红线）。
SOURCE_MEASURED = "measured"
SOURCE_DERIVED = "derived"
SOURCE_DEFAULT = "default"

#: 准入三态，沿用 quant_descriptor 语义
VERDICT_VERIFIED = "verified"
VERDICT_UNVERIFIED = "unverified"
VERDICT_REJECTED = "rejected"

#: 显存水位线：超过即判「这一档太激进」（与 memory_policy._OFFLOAD_HIGH_WATER 对齐）
DEFAULT_WATER_LINE = 0.95

#: 512²→1024²（像素 4 倍）的外推系数。
#: **2026-10-28 实测校正**：SD1.5 + model_offload，512²峰值 1.75GB → 1024²峰值 2.55GB，
#: 比值 1.457（此前文档里猜的 1.6 偏高 9.8%，已否决）。
#: 注意：这是单个数据点，不同模型/档位的固定开销占比不同，系数会变
#: ⇒ 优先走 `extrapolate(base_gb=...)` 的线性模型，本系数仅作兜底。
EXTRAPOLATE_COEF_4X = 1.46

#: 已知后端 → 可信度。不在表里的一律 unverified，不猜。
_KNOWN_BACKENDS = {
    "nvidia": VERDICT_VERIFIED,
    "apple": VERDICT_UNVERIFIED,
    "amd": VERDICT_UNVERIFIED,
    "musa": VERDICT_UNVERIFIED,
    "intel": VERDICT_UNVERIFIED,
}


# ══════════════════════════════════════════════════════════════════════════
# 纯函数区（无副作用，全部可单测）
# ══════════════════════════════════════════════════════════════════════════


def res_class(width: int = 0, height: int = 0) -> str:
    """分辨率粗分档。档案 key 用它，避免每种尺寸都建一条。"""
    px = max(int(width), int(height))
    if px <= 0:
        return "unknown"
    if px <= 512:
        return "512"
    if px <= 768:
        return "768"
    if px <= 1024:
        return "1024"
    return "1536plus"


def _torch_mm(torch_version: str = "") -> str:
    """torch 只取 major.minor。patch 参与会让每次小版本更新全部重标（D-A4）。"""
    parts = (torch_version or "").split(".")
    if len(parts) >= 2:
        return "%s.%s" % (parts[0], parts[1])
    return torch_version or "?"


def make_key(profile: Dict[str, Any], model_id: str,
             width: int = 0, height: int = 0,
             torch_version: str = "") -> str:
    """档案主键。任一维度变化即自然失效（D-A4）。"""
    vendor = str(profile.get("vendor") or "cpu")
    arch = str(profile.get("arch") or "cpu")
    vram = profile.get("vram_gb")
    vram_class = str(int(round(float(vram)))) if vram else "0"
    tv = torch_version or str(profile.get("torch_version") or "")
    return "|".join([
        vendor, arch, vram_class, _torch_mm(tv),
        str(model_id or "?"), res_class(width, height),
    ])


def admit(profile: Dict[str, Any]) -> Tuple[bool, str]:
    """准入判定：显存门槛 + 后端可信度（设计文档 §1.2 / §1.3）。

    返回 ``(是否准入, 说明)``。拒绝时说明里必须给出**需要多少显存**，
    不能只说「不行」——这是「拒绝静默降级」的具体体现。
    """
    vendor = str(profile.get("vendor") or "cpu")
    if vendor == "cpu":
        return False, "无 GPU 后端（CUDA/MPS/ROCm/MUSA 均不可用），本引擎不做 CPU 推理"

    try:
        vram = float(profile.get("vram_gb") or 0.0)
    except (TypeError, ValueError):
        vram = 0.0

    if vram < MIN_VRAM_GB:
        return False, (
            "显存 %.1fGB 低于适配门槛 %.0fGB（SD1.5 需约 3GB、SDXL 需约 5.3GB，"
            "再留系统余量后 8GB 是能跑 SDXL 的最低实用线）" % (vram, MIN_VRAM_GB)
        )

    verdict = _KNOWN_BACKENDS.get(vendor, VERDICT_UNVERIFIED)
    if verdict == VERDICT_UNVERIFIED:
        return True, (
            "%s 后端（%s / %.1fGB）显存达标，但该后端成熟度未验证，"
            "标定结果标 unverified" % (vendor, profile.get("arch") or "?", vram)
        )
    return True, "%s 后端（%s / %.1fGB）显存达标" % (
        vendor, profile.get("arch") or "?", vram)


def ladder(start: str = "") -> Tuple[str, ...]:
    """返回待试的档位序列。给 start 则从该档起（跳跃式起步，省试跑次数）。"""
    if not start or start not in LADDER:
        return LADDER
    return LADDER[LADDER.index(start):]


def decide(trials: Sequence["Trial"],
           water_line_gb: Optional[float] = None) -> Tuple[Optional["Trial"], List[str]]:
    """阶梯爬升的裁决（D-A2 修正版）。

    规则：
      · 试跑失败 → 停，不再往上爬（更激进的档位风险更高，没有意义）
      · 峰值超水位线 → 停，同上
      · 在上述约束下，**按实测耗时挑最快的那一档**，而不是取最后一个

    ⚠️ 为什么不是「取最激进」——这是本文件的一处重要修正：
       原设计按「越激进越省时间」的单调假设取最后一个，但项目自己的实测
       （`diffusers_image.py:212-218`）显示反例：
         offload=model : 首图 5.4s + 稳态 4.17s/张（加载 31s）
         whole_gpu     : 首图 7.2s + 稳态 3.08s/张（加载 55.7s，峰值 4.34GB）
       单张生成 model_offload 更快；「越激进越快」只在批量/稳态成立。
       标定要回答的是「这次任务怎么最快」，所以必须按实测时间选，
       不能靠档位顺序猜。
    """
    chosen: Optional[Trial] = None
    rejected: List[str] = []
    for t in trials:
        if not t.ok:
            rejected.append("%s: %s" % (t.mode, t.error or "试跑失败"))
            break
        if water_line_gb is not None:
            eff = effective_peak_gb(t)
            if eff is not None and eff > water_line_gb:
                rejected.append("%s: 占用 %.2fGB 超水位线 %.2fGB"
                                % (t.mode, eff, water_line_gb))
                break
        # 时间缺失（None）视为不可比较，不参与「最快」的竞争，但仍是候选
        if chosen is None:
            chosen = t
            continue
        if t.seconds is not None:
            if chosen.seconds is None or t.seconds < chosen.seconds:
                chosen = t
    return chosen, rejected


def extrapolate(peak_gb: Optional[float], probe_px: int, target_px: int,
                base_gb: Optional[float] = None,
                coef_4x: float = EXTRAPOLATE_COEF_4X) -> Optional[float]:
    """把探针规格下测到的峰值外推到目标规格。

    两种模型，优先用更准的那个：
      · 给了 ``base_gb``（权重固定占用）⇒ **线性模型**
        ``peak = base + (peak_probe - base) × 像素比``
        这是物理上正确的：权重不随分辨率变，只有激活随像素线性涨。
      · 没给 ⇒ **幂律兜底**，锚点是「像素 4 倍 → 系数 coef_4x」。

    ⚠️ ``coef_4x=1.6`` 是经验值、**未经实测校正**（设计文档 §10 缺口 1）。
       调用方拿到的结果应标 ``SOURCE_DERIVED``，不得标 ``measured``。
    """
    if peak_gb is None or probe_px <= 0 or target_px <= 0:
        return None
    if target_px <= probe_px:
        return round(float(peak_gb), 2)

    px_ratio = (float(target_px) / float(probe_px)) ** 2

    if base_gb is not None and 0 < base_gb < peak_gb:
        return round(base_gb + (float(peak_gb) - base_gb) * px_ratio, 2)

    if px_ratio <= 1.0 or coef_4x <= 1.0:
        return round(float(peak_gb), 2)
    exponent = math.log(coef_4x) / math.log(4.0)
    return round(float(peak_gb) * (px_ratio ** exponent), 2)


_STORE_SINGLETON: Optional["CalibrationStore"] = None
_STORE_LOCK = threading.Lock()


def default_store() -> "CalibrationStore":
    """进程内共享的档案实例。

    `pick_memory_policy()` 是高频调用（每次 load 都走），每次都 new 一个
    `CalibrationStore` 会重复读 JSON。这里做单例，内部 `_cache` 保证只读一次盘。
    """
    global _STORE_SINGLETON
    if _STORE_SINGLETON is None:
        with _STORE_LOCK:
            if _STORE_SINGLETON is None:
                _STORE_SINGLETON = CalibrationStore()
    return _STORE_SINGLETON


# ══════════════════════════════════════════════════════════════════════════
# 档案查询（供 memory_policy 决策时调用）
# ══════════════════════════════════════════════════════════════════════════


def lookup(store: "CalibrationStore", profile: Dict[str, Any],
           model_id: str, width: int = 0, height: int = 0,
           torch_version: str = "") -> Optional[Tuple[str, "Entry"]]:
    """按设备画像与模型找最佳档案条目；返回 ``(key, Entry)`` 或 None。

    **分辨率是宽松匹配**，这是刻意的：
    `pick_memory_policy()` 在 `load()` 阶段被调用，那时还不知道本次出图尺寸
    （尺寸是 `generate()` 才确定的）。所以：
      · 先试精确 ``res_class``；
      · 不中则在同 ``(vendor, arch, vram_class, model_id)`` 下取 **peak_gb 最大**的那条
        —— 用最坏情况做决策，宁可保守，符合项目「宁慢勿炸」的取舍。

    ``torch_version`` 只用于排除**明确不同 minor** 的旧档案；不传则不做该过滤
    （memory_policy 侧拿不到版本，宁可多匹配也不错失）。
    """
    try:
        keys = store.keys()
    except Exception:
        return None
    if not keys:
        return None

    vendor = str(profile.get("vendor") or "")
    arch = str(profile.get("arch") or "")
    try:
        vram_class = str(int(round(float(profile.get("vram_gb") or 0))))
    except (TypeError, ValueError):
        vram_class = "0"

    want_res = res_class(width, height)
    want_tv = _torch_mm(torch_version) if torch_version else ""

    exact: Optional[Tuple[str, Entry]] = None
    fallback: Optional[Tuple[str, Entry]] = None

    for k in keys:
        parts = k.split("|")
        if len(parts) != 6:
            continue
        if (parts[0], parts[1], parts[2], parts[4]) != (
                vendor, arch, vram_class, str(model_id)):
            continue
        if want_tv and parts[3] != want_tv:
            continue
        e = store.get(k)
        if e is None:
            continue
        if parts[5] == want_res:
            exact = (k, e)
            break
        if fallback is None or e.peak_gb > fallback[1].peak_gb:
            fallback = (k, e)

    return exact if exact is not None else fallback


# ══════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Trial:
    """一次试跑的结果。由注入的 ``probe_run`` 产出。

    ``peak_gb`` 是 PyTorch 分配器口径（``max_memory_allocated``），
    ``reserved_gb`` 是缓存池口径（``max_memory_reserved``）。

    ⚠️ 为什么两个都要：2026-10-28 实测（SD1.5 model_offload）显示
       reserved 的涨幅**明显大于** allocated——
         512² ：allocated 1.75 / reserved 2.00（差 0.25）
         1024²：allocated 2.55 / reserved 4.36（差 1.81）
       1024² 下差值达 70%。**只按 allocated 判水位线会系统性低估真实占用**，
       8GB 卡上这正是 OOM 的典型路径。水位判定请用 :func:`effective_peak_gb`。
    """

    mode: str
    ok: bool
    peak_gb: Optional[float] = None
    seconds: Optional[float] = None
    error: str = ""
    reserved_gb: Optional[float] = None
    #: 分项耗时（2026-10-28 新增）。``seconds`` 是加载+生成的总和，
    #: 分项存下来**只为可证**：冷启动偏差要能被观测到「加载耗时收敛了」，
    #: 否则「我加了预热」只是一句无凭的自述（同 R9 精神）。
    load_seconds: Optional[float] = None
    gen_seconds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def effective_peak_gb(t: "Trial") -> Optional[float]:
    """判水位线用的口径：取 allocated 与 reserved 的更保守者。

    reserved 含可回收缓存，单看它会偏保守；但 allocated 会漏掉碎片膨胀。
    取两者最大值，宁可少升一档（慢），不要撞上 OOM（崩）——
    符合本项目「宁可慢、不可糊/不炸」的一贯取舍。
    """
    if t is None:
        return None
    cands = [v for v in (t.peak_gb, t.reserved_gb) if v is not None]
    return max(cands) if cands else None


@dataclass(frozen=True)
class Entry:
    """档案条目。``source`` 三态是本模块最重要的字段。"""

    mode: str
    peak_gb: float
    seconds: float
    source: str = SOURCE_MEASURED
    measured_at: str = ""
    verdict: str = VERDICT_VERIFIED
    tried: Tuple[str, ...] = field(default_factory=tuple)
    rejected: Tuple[str, ...] = field(default_factory=tuple)
    derived_from: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tried"] = list(self.tried)
        d["rejected"] = list(self.rejected)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Entry":
        return cls(
            mode=str(d.get("mode") or MODE_LAYER_CPU_OFFLOAD),
            peak_gb=float(d.get("peak_gb") or 0.0),
            seconds=float(d.get("seconds") or 0.0),
            source=str(d.get("source") or SOURCE_DEFAULT),
            measured_at=str(d.get("measured_at") or ""),
            verdict=str(d.get("verdict") or VERDICT_UNVERIFIED),
            tried=tuple(d.get("tried") or ()),
            rejected=tuple(d.get("rejected") or ()),
            derived_from=str(d.get("derived_from") or ""),
            note=str(d.get("note") or ""),
        )


# ══════════════════════════════════════════════════════════════════════════
# 档案存储
# ══════════════════════════════════════════════════════════════════════════


class CalibrationStore:
    """JSON 档案读写。损坏即重建（设计文档 §5 失败矩阵）。"""

    def __init__(self, path: str = "") -> None:
        if not path:
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))))
            path = os.path.join(root, "data", "calibration.json")
        self.path = path
        self._lock = threading.Lock()
        self._cache: Optional[Dict[str, Dict[str, Any]]] = None

    # ── 内部 ──
    def _read(self) -> Dict[str, Dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        data: Dict[str, Dict[str, Any]] = {}
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict) and int(raw.get("version") or 0) == CALIB_VERSION:
                    ent = raw.get("entries")
                    if isinstance(ent, dict):
                        data = ent
                else:
                    logger.info("[calibration] 档案版本不符，重建")
        except Exception:
            logger.warning("[calibration] 档案损坏，重建（不阻断）", exc_info=True)
            data = {}
        self._cache = data
        return data

    def _write(self, data: Dict[str, Dict[str, Any]]) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": CALIB_VERSION, "entries": data},
                          f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            self._cache = data
            return True
        except Exception:
            logger.warning("[calibration] 档案写入失败（不阻断）", exc_info=True)
            return False

    # ── 对外 ──
    def get(self, key: str) -> Optional[Entry]:
        with self._lock:
            d = self._read().get(key)
        return Entry.from_dict(d) if isinstance(d, dict) else None

    def put(self, key: str, entry: Entry) -> bool:
        with self._lock:
            data = dict(self._read())
            data[key] = entry.to_dict()
            return self._write(data)

    def invalidate(self, key: str = "") -> int:
        """清空指定条目；key 为空则全清。返回清掉的条数。"""
        with self._lock:
            data = self._read()
            if not key:
                n = len(data)
                self._cache = {}
                self._write({})
                return n
            if key in data:
                data = dict(data)
                data.pop(key, None)
                self._write(data)
                return 1
            return 0

    def keys(self) -> List[str]:
        with self._lock:
            return sorted(self._read().keys())

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
        by_source: Dict[str, int] = {}
        for v in data.values():
            s = str((v or {}).get("source") or SOURCE_DEFAULT)
            by_source[s] = by_source.get(s, 0) + 1
        return {
            "path": self.path,
            "entries": len(data),
            "by_source": by_source,
        }


# ══════════════════════════════════════════════════════════════════════════
# 标定器
# ══════════════════════════════════════════════════════════════════════════

#: probe_run(mode, px) -> Trial
ProbeRun = Callable[[str, int], Trial]


class Calibrator:
    """阶梯爬升 + 档案复用（D-A2 / D-A3 / D-A5）。

    ``probe_run`` 由调用方注入：真机上传一个「用该档位跑一次最小推理」的函数，
    测试里传假函数。本类自身不做任何 GPU 操作。

    预热（2026-10-28 新增，消冷启动偏差）
    ------------------------------------
    阶梯固定从保守爬到激进，于是**第一档总是替冷启动背锅**：首次加载要付
    模型文件冷读、cuDNN/cuBLAS 句柄初始化、分配器首次扩张等一次性成本。
    2026-10-28 两次实测的加载耗时 16.62→15.02 / 6.90→4.01 / 2.73→1.07 /
    2.52→1.28，第二次整体快一个量级 —— 这不是档位差异，是缓存差异。
    两档耗时接近时，这个偏差会把结论**翻转**。

    故在阶梯之前插一次**丢弃式预热**（``warmup_run``，同样由调用方注入）：
    结果不进 ``tried``、不参与 ``decide``，只记录 ``warmup_seconds`` 供观测。
    预热失败**不阻断**标定（D-A3：它是增强，不是前置依赖）。
    ``warmup_run=None`` ⇒ 不预热（纯逻辑测试默认，保持既有行为零变化）。
    """

    def __init__(self, store: CalibrationStore, profile: Dict[str, Any],
                 probe_run: Optional[ProbeRun] = None,
                 *, water_line_gb: Optional[float] = None,
                 probe_px: int = 512,
                 torch_version: str = "",
                 warmup_run: Optional[Callable[[], Optional[float]]] = None) -> None:
        self.store = store
        self.profile = dict(profile or {})
        self.probe_run = probe_run
        self.probe_px = int(probe_px)
        self.torch_version = torch_version
        self.warmup_run = warmup_run
        #: 预热耗时（秒）。None = 没预热；-1 = 预热跑了但失败。
        self.warmup_seconds: Optional[float] = None
        self.warmup_error: str = ""
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()

        # 水位线按总显存算绝对值；总显存取不到就不判（宁松不误杀）
        if water_line_gb is not None:
            self.water_line_gb: Optional[float] = water_line_gb
        else:
            try:
                total = float(self.profile.get("vram_gb") or 0.0)
            except (TypeError, ValueError):
                total = 0.0
            self.water_line_gb = (total * DEFAULT_WATER_LINE) if total > 0 else None

    # ── 查询 ──
    def key_for(self, model_id: str, res: Tuple[int, int] = (0, 0)) -> str:
        w, h = (res + (0, 0))[:2] if res else (0, 0)
        return make_key(self.profile, model_id, w, h, self.torch_version)

    def best_for(self, model_id: str,
                 res: Tuple[int, int] = (0, 0)) -> Optional[Entry]:
        """命中档案直接返回；未命中返回 None（调用方走保守档）。"""
        return self.store.get(self.key_for(model_id, res))

    # ── 标定 ──
    def calibrate(self, model_id: str, res: Tuple[int, int] = (0, 0),
                  *, force: bool = False) -> Optional[Entry]:
        """跑一轮阶梯爬升并写档。**失败不抛异常**（D-A3）。"""
        ok, why = admit(self.profile)
        if not ok:
            logger.info("[calibration] 拒绝适配 %s：%s", model_id, why)
            return None
        if self.probe_run is None:
            logger.info("[calibration] 未注入 probe_run，跳过标定")
            return None

        key = self.key_for(model_id, res)
        if not force:
            hit = self.store.get(key)
            if hit is not None:
                return hit

        # ★ 预热：必须在「确认真的要爬梯」之后、第一档之前。
        #   放在档案命中之前会白白多跑一次（命中场景应该是秒开，AC-5）。
        self._run_warmup()

        trials: List[Trial] = []
        try:
            for mode in LADDER:
                if self._cancel.is_set():
                    logger.info("[calibration] 已被取消，止于 %d 次试跑", len(trials))
                    break
                t = self._safe_probe(mode)
                trials.append(t)
                if not t.ok:
                    break
                if self.water_line_gb is not None and t.peak_gb is not None \
                        and t.peak_gb > self.water_line_gb:
                    break
        except Exception:
            logger.warning("[calibration] 试跑异常，回退到已得结果", exc_info=True)

        chosen, rejected = decide(trials, self.water_line_gb)
        if chosen is None:
            logger.info("[calibration] %s 全档位均失败：%s", model_id, "；".join(rejected))
            return None

        verdict = _KNOWN_BACKENDS.get(
            str(self.profile.get("vendor") or ""), VERDICT_UNVERIFIED)
        # 记账用保守口径（allocated 与 reserved 取大），不记乐观值
        peak = effective_peak_gb(chosen) or 0.0
        note = "探针 %dpx；peak=%s reserved=%s（取大者记账）" % (
            self.probe_px, chosen.peak_gb, chosen.reserved_gb)
        # 预热信息必须落档：否则「这份档案已经剔除冷启动」这件事无从考证。
        if self.warmup_seconds is not None:
            note += "；预热 %.2fs（已剔除首档冷启动）" % self.warmup_seconds
        elif self.warmup_error:
            note += "；未预热（%s）⇒ 首档耗时可能含冷启动" % self.warmup_error[:60]
        if chosen.load_seconds is not None:
            note += "；加载 %.2fs 生成 %.2fs" % (
                float(chosen.load_seconds), float(chosen.gen_seconds or 0.0))
        entry = Entry(
            mode=chosen.mode,
            peak_gb=round(float(peak), 2),
            seconds=round(float(chosen.seconds or 0.0), 2),
            source=SOURCE_MEASURED,
            measured_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            verdict=verdict,
            tried=tuple(t.mode for t in trials),
            rejected=tuple(rejected),
            note=note,
        )
        self.store.put(key, entry)
        return entry

    def _run_warmup(self) -> None:
        """丢弃式预热。**永不抛异常、永不阻断标定**（D-A3）。

        结果只进 ``self.warmup_seconds`` / ``self.warmup_error`` 供观测：
        预热跑的是哪个档位、多快，都不该影响「哪一档最快」的裁决。
        """
        self.warmup_seconds = None
        self.warmup_error = ""
        if self.warmup_run is None:
            return
        t0 = time.time()
        try:
            secs = self.warmup_run()
        except MemoryError:
            self.warmup_error = "预热 OOM"
            logger.info("[calibration] 预热 OOM，继续标定（首档将含冷启动成本）")
            return
        except Exception as e:
            # 预热是增强，任何异常都不该冒泡到标定主流程（D-A3）
            self.warmup_error = repr(e)[:120]
            logger.info("[calibration] 预热失败（不阻断）：%s", e)
            return
        dt = time.time() - t0
        if secs is None:
            self.warmup_seconds = round(float(dt), 2)
        else:
            self.warmup_seconds = round(float(secs), 2)
        logger.info("[calibration] 预热完成 %.2fs，阶梯从此处都是热态", self.warmup_seconds)

    def _safe_probe(self, mode: str) -> Trial:
        """单档试跑，异常一律转成失败 Trial（D-A3 零成本回退）。"""
        try:
            t = self.probe_run(mode, self.probe_px)  # type: ignore[misc]
            if not isinstance(t, Trial):
                return Trial(mode=mode, ok=False, error="probe_run 返回值非 Trial")
            return t
        except MemoryError:
            return Trial(mode=mode, ok=False, error="MemoryError")
        except Exception as e:
            return Trial(mode=mode, ok=False, error=repr(e)[:160])

    # ── 后台（D-A5）──
    def start_background(self, model_id: str,
                         res: Tuple[int, int] = (0, 0)) -> bool:
        """空闲时后台标定。已在跑则返回 False，不排队（重复标定无意义）。"""
        if self._thread is not None and self._thread.is_alive():
            return False
        self._cancel.clear()

        def _run() -> None:
            try:
                self.calibrate(model_id, res)
            except Exception:
                logger.warning("[calibration] 后台标定失败（不阻断）", exc_info=True)

        th = threading.Thread(target=_run, name="calibration", daemon=True)
        self._thread = th
        th.start()
        return True

    def cancel(self) -> None:
        self._cancel.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """等后台标定结束（测试与退出流程用）。"""
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    # ── 外推（D-A6）──
    def derive_for_video(self, image_entry: Entry, image_key: str,
                         model_id: str, frames: int = 25,
                         per_frame_gb: Optional[float] = None) -> Optional[Entry]:
        """把图像标定结果外推成视频条目，不重复跑 40s 的视频探针。

        ``per_frame_gb`` 是每帧的边际显存；不给则按峰值的 1.2%/帧粗估。
        产出标 ``SOURCE_DERIVED``，**永不标 measured**（D-A6 / AC-8）。
        """
        if image_entry is None or image_entry.peak_gb <= 0:
            return None
        per = per_frame_gb
        if per is None:
            per = image_entry.peak_gb * 0.012  # 1.2%/帧，粗估，待实测校正
        peak = round(image_entry.peak_gb + per * max(0, int(frames)), 2)
        key = self.key_for(model_id, (0, 0))
        entry = Entry(
            mode=image_entry.mode,
            peak_gb=peak,
            seconds=round(image_entry.seconds * max(1.0, frames / 16.0), 2),
            source=SOURCE_DERIVED,
            measured_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            verdict=image_entry.verdict,
            tried=(),
            rejected=(),
            derived_from=str(image_key or ""),
            note="由图像标定外推，%d 帧；每帧 %.3fGB（估）" % (frames, per),
        )
        self.store.put(key, entry)
        return entry

    def stats(self) -> Dict[str, Any]:
        return {
            "profile": {
                "vendor": self.profile.get("vendor"),
                "arch": self.profile.get("arch"),
                "vram_gb": self.profile.get("vram_gb"),
            },
            # 暴露出来便于排查「档案 key 里为什么是 ?」这类问题
            "torch_version": self.torch_version or "(未提供，key 内退化为 ?)",
            "torch_mm": _torch_mm(self.torch_version),
            "water_line_gb": self.water_line_gb,
            "probe_px": self.probe_px,
            "running": self.is_running(),
            "store": self.store.stats(),
        }


def peak_for_resolution(entry: "Entry", key: str,
                        width: int = 0, height: int = 0) -> float:
    """档案条目在**目标分辨率**下的峰值估计（2026-10-28 新增）。

    为什么需要这一步
    ----------------
    标定探针跑的是 512²（省时间），而正式出图可能是 1024²。档案里记的
    ``peak_gb`` 是**探针那个尺寸**的峰值，直接拿去跟水位线比会低估——
    `load()` 阶段拿不到出图尺寸，所以过去只能靠「取最坏情况那条」兜。
    有了本函数，`pick_memory_policy(width, height)` 传了尺寸时就能把峰值
    按 `extrapolate()` 换算过来，安全闸判的才是「本次」而不是「当时」。

    ``res_class`` 是 "1536plus"（非数字）或目标尺寸未知时**不做换算**，
    原样返回 —— 宁可承认不知道，也不编一个比例。
    """
    peak = float(getattr(entry, "peak_gb", 0.0) or 0.0)
    parts = str(key or "").split("|")
    probe_px = 0
    if len(parts) == 6 and parts[5].isdigit():
        probe_px = int(parts[5])
    target_px = max(int(width or 0), int(height or 0))
    if probe_px <= 0 or target_px <= 0 or peak <= 0:
        return peak
    scaled = extrapolate(peak, probe_px, target_px)
    return float(scaled) if scaled is not None else peak


__all__ = [
    "MIN_VRAM_GB", "LADDER", "CALIB_VERSION", "DEFAULT_WATER_LINE",
    "EXTRAPOLATE_COEF_4X",
    "MODE_LAYER_CPU_OFFLOAD", "MODE_SEQUENTIAL_OFFLOAD",
    "MODE_MODEL_OFFLOAD", "MODE_WHOLE_GPU",
    "SOURCE_MEASURED", "SOURCE_DERIVED", "SOURCE_DEFAULT",
    "VERDICT_VERIFIED", "VERDICT_UNVERIFIED", "VERDICT_REJECTED",
    "Trial", "Entry", "CalibrationStore", "Calibrator", "ProbeRun",
    "res_class", "make_key", "admit", "ladder", "decide", "extrapolate",
    "effective_peak_gb", "lookup", "peak_for_resolution",
]
