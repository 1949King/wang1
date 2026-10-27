# -*- coding: utf-8 -*-
"""资源仲裁：显存/内存不够时，按"谁让位更便宜"从低到高请人腾地方（P1 · 2026-10-28）。

## 为什么需要它

`local_video_pipe_cache` 与 `diffusers_image` 已经有一处**点对点**的礼貌让位
（图像引擎加载前叫视频常驻缓存清场）。但那是硬编码的：只有这两个引擎互相认识，
再来第三、第四个占资源的角色（LLM、语音、抠图）就得两两写一遍。

本模块把那处点对点逻辑收成**一张来源表**：谁占着资源、谁能让位、让位多贵，
登记一次；需要腾地方的人只说"我要 N GB"，不必知道对方是谁。

## 三条口径（都有实测依据，不是设计洁癖）

### 1. 让位"释放了多少"一律**实测 delta**，不信自报

2026-10-28 实测（RTX 4060 Laptop 8GB，qwen3.5:4b Q4_K_M）：

| 时点 | nvidia-smi used | free |
|---|---|---|
| 加载前 | 1358 MiB | 6599 MiB |
| 加载后 | 5060 MiB | 2897 MiB |
| `keep_alive=0` 卸载后 | 1372 MiB | 6585 MiB |

显存实际占用 **3.62GB**，而 Ollama `/api/ps` 自报 `size_vram = 2.92GB`
⇒ **自报低估约 0.7GB**（CUDA 上下文 + 运行时不自报）。
所以本模块的记账口径是：`release()` 前后各测一次池子的可用量，**差值才算数**；
源自己返回什么都只写进 note，不参与记账。这样即便某个源明天改了口径，
账本也不会跟着错。

### 2. 判断"够不够"取**两个读数里更保守的那个**

同机实测 5 组样本，`torch.cuda.mem_get_info()` 报的可用量比 nvidia-smi
**稳定高 544~558 MiB**（Windows WDDM 下 nvidia-smi 更保守）：

```
sample0  torch_free=7090MiB  smi_free=6532MiB  delta=+558MiB
sample3  torch_free=7090MiB  smi_free=6546MiB  delta=+544MiB
```

偏乐观的方向恰好是危险方向：以为够 ⇒ 不让人让位 ⇒ 真加载时 OOM。
故判据取 `min(torch, smi)`；nvidia-smi 不可用（非 NVIDIA / MUSA）时退回 torch，
并把 `readings["smi"]=None` 如实记下来，不假装两个读数都有。

### 3. 让位是**优化不是前提**，失败绝不阻断生成

任何一步失败都只让 `Decision.ok=False` + note 说明，调用方照常走自己的加载路径，
最坏退回"没腾地方"的现状。这与 `diffusers_image` 现行让位调用的纪律一致。

## 回退

`SHIGUANG_BROKER=off`（或 `0` / `false` / `no`）⇒ `ensure_capacity()` 直接返回
`action="disabled"`，一次探测都不做，退化为 P0 之前的行为。

## 用法

```python
from app.core.neural.resource_broker import ensure_capacity

dec = ensure_capacity(4.2, reason="加载 SDXL")
if not dec.ok:
    logger.info("让位后仍不足：%s", dec.note)   # 不阻断，照常尝试
```
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 资源池 ──────────────────────────────────────────────────────────────
POOL_VRAM = "vram"
POOL_RAM = "ram"

#: 关闭开关的取值（与项目其他开关一致：空串也视为关闭，见 ⑪ 开关门禁）
_OFF_VALUES = ("", "0", "off", "false", "no")

#: Ollama 自报 size_vram 与真实占用的缺口（GB）。实测 3.62 - 2.92 ≈ 0.70。
#: 用途仅限 `probe()` 的**预估**：真实记账一律用实测 delta。
CUDA_CTX_OVERHEAD_GB = 0.70

#: 安全余量：判据要求 free >= need × SAFETY。留 8% 吸收驱动/碎片抖动
#: （实测卸载后 nvidia-smi free 在 6585~6638MiB 间抖动，约 ±50MiB）。
SAFETY = 1.08


# ══════════════════════════════════════════════════════════════════════
# 池子读数
# ══════════════════════════════════════════════════════════════════════

def _torch_free_gb() -> Optional[float]:
    """torch 视角的可用显存（GB）。复用 `memory_policy.probe_vram()`，不另写一份。

    ⚠️ 注意取的是返回里的 `torch_free_gb`（**原始 torch 读数**），不是 `free_gb`：
    2026-10-28 起 `free_gb` 已经是「torch 与 nvidia-smi 的较小值」（见 P1.5）。
    本模块要把两个原始读数**分开呈现**，再自己取 min，这样诊断时能看出差多少。

    ⚠️ 副作用：首次调用会 import torch 并初始化 CUDA 上下文，
    这**本身**会占掉几百 MB 显存。调用方若在"还没打算用显卡"的路径上探测，
    等于为了测量先把显卡点着了 —— 故只在真要加载权重前调用。
    """
    try:
        from app.core.neural.memory_policy import probe_vram

        info = probe_vram()
        if not info:
            return None
        return float(info.get("torch_free_gb", info["free_gb"]))
    except Exception:  # stability-gate: allow-swallow（读不到显存时上层按"不知道"处理，绝不阻断生成）
        logger.debug("[broker] torch 显存探测失败", exc_info=True)
        return None


def _smi_free_gb() -> Optional[float]:
    """nvidia-smi 视角的可用显存（GB）。不可用（非 NVIDIA / 未装驱动）返回 None。

    实现收口在 `memory_policy.nvidia_smi_free_gb()`（带 1s 缓存），本函数只是
    本模块的取数口 —— **不复制第二份 subprocess 逻辑**，否则两处口径迟早分家。
    """
    try:
        from app.core.neural.memory_policy import nvidia_smi_free_gb

        return nvidia_smi_free_gb()
    except Exception:  # stability-gate: allow-swallow（nvidia-smi 缺失/超时是常态：退回 torch 单读数并如实记录 smi=None）
        return None


def free_ram_gb() -> Optional[float]:
    """可用内存（GB）。复用视频缓存里已有的三降级链（psutil → kernel32 → /proc）。"""
    try:
        from app.core.local_video_pipe_cache import available_ram_gb

        return available_ram_gb()
    except Exception:  # stability-gate: allow-swallow（内存读数取不到时上层按未知处理）
        logger.debug("[broker] 可用内存探测失败", exc_info=True)
        return None


def read_pool(pool: str) -> Tuple[Optional[float], Dict[str, Optional[float]]]:
    """读池子可用量，返回 (决策用值, 各读数明细)。

    决策用值 = 各读数里**最小的那个**（保守方向），全读不到才是 None。
    """
    if pool == POOL_RAM:
        ram = free_ram_gb()
        return ram, {"ram": ram}

    torch_gb = _torch_free_gb()
    smi_gb = _smi_free_gb()
    known = [v for v in (torch_gb, smi_gb) if v is not None]
    return (min(known) if known else None), {"torch": torch_gb, "smi": smi_gb}


# ══════════════════════════════════════════════════════════════════════
# 让位来源
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ReclaimSource:
    """一个可以让位的资源占用方。

    字段:
      name: 唯一名（出现在 Decision.reclaimed 与日志里）
      pool: 让位腾出的是哪个池子（`vram` / `ram`）—— **必须对**：
        叫视频缓存腾显存是南辕北辙（它占的是 CPU 内存里的 offload 权重）。
      cost_s: 让位代价（下次要用时重载约需几秒）。**便宜的先让**。
      release: 执行让位；返回值不参与记账，只写进 note。
      probe: 预估能腾出多少 GB；None 表示"不知道"（诚实优于编数字）。
      available: 该来源此刻是否真的可让位（如 Ollama 服务没起就没必要问）。
    """
    name: str
    pool: str
    cost_s: float
    release: Callable[[str], Any]
    probe: Optional[Callable[[], Optional[float]]] = None
    available: Optional[Callable[[], bool]] = None


@dataclass
class Reclaimed:
    """一次让位的记账结果。"""
    name: str
    estimated_gb: Optional[float]
    actual_gb: Optional[float]
    ok: bool
    note: str = ""

    @property
    def bias_gb(self) -> Optional[float]:
        """估算与实测的偏差（实测 - 估算）。None = 缺一边数据，不做差。"""
        if self.estimated_gb is None or self.actual_gb is None:
            return None
        return round(self.actual_gb - self.estimated_gb, 2)


@dataclass
class Decision:
    """一次资源仲裁的结论。

    action:
      `disabled`     — 开关关闭，未做任何事（调用方行为与 P0 之前完全一致）
      `skipped`      — 资源本来够，没让位（**保住常驻收益，这是常态而非异常**）
      `released`     — 让位后够了
      `insufficient` — 让位后仍不够（调用方照常尝试，只是提前知道风险）
    """
    action: str
    pool: str
    need_gb: float
    free_before_gb: Optional[float]
    free_after_gb: Optional[float]
    readings: Dict[str, Optional[float]] = field(default_factory=dict)
    reclaimed: List[Reclaimed] = field(default_factory=list)
    note: str = ""

    @property
    def ok(self) -> bool:
        """是否"可以放心加载"。`insufficient` 也只是 False —— 不是异常。"""
        return self.action in ("disabled", "skipped", "released")

    @property
    def freed_gb(self) -> float:
        """本次净腾出多少（实测口径）。任一读数缺失时为 0.0（不编）。"""
        if self.free_before_gb is None or self.free_after_gb is None:
            return 0.0
        return round(self.free_after_gb - self.free_before_gb, 2)

    def describe(self) -> str:
        """一行摘要（日志/诊断面板用）。"""
        head = "[broker] %s pool=%s need=%.2fGB" % (
            self.action, self.pool, self.need_gb)
        if self.free_before_gb is not None:
            head += " free=%.2f→%s" % (
                self.free_before_gb,
                "%.2fGB" % self.free_after_gb if self.free_after_gb is not None else "?")
        if self.freed_gb:
            head += " freed=+%.2fGB" % self.freed_gb
        if self.note:
            head += " ｜ " + self.note
        return head


# ── 来源实现 ────────────────────────────────────────────────────────────

def _ollama_loaded_gb() -> Optional[float]:
    """Ollama 当前占用的显存预估（GB）；无加载模型返回 0.0。"""
    try:
        from app.modules.lego.ollama_client import OllamaClient

        loaded = OllamaClient().ps()
        if not loaded:
            return 0.0
        # 自报体积 + CUDA 上下文开销（实测低估 0.70GB/模型；多模型共用一份上下文，
        # 这里按"每个模型都带一份"偏高估 —— 偏高估在"能不能腾出足够空间"这个问题上
        # 是安全方向，且真实值随后由实测 delta 覆盖，不会进入账本。
        return round(sum(m.size_vram_gb for m in loaded)
                     + CUDA_CTX_OVERHEAD_GB * len(loaded), 2)
    except Exception:  # stability-gate: allow-swallow（ollama_client 缺失/异常时按"不知道能腾多少"处理，让位仍会尝试）
        logger.debug("[broker] 读 Ollama 占用失败", exc_info=True)
        return None


def _ollama_available() -> bool:
    try:
        from app.modules.lego.ollama_client import OllamaClient

        return bool(OllamaClient().is_available())
    except Exception:  # stability-gate: allow-swallow（可用性探测失败即视为不可用，不必二次报错）
        return False


def _release_ollama(reason: str) -> Any:
    from app.modules.lego.ollama_client import OllamaClient

    logger.info("[broker] 请 Ollama 让位：%s", reason)
    return OllamaClient().unload()


def _video_cache_available() -> bool:
    """视频常驻缓存此刻是否有可释放的管线。"""
    try:
        from app.core import local_video_pipe_cache as C

        cache = getattr(C, "_CACHE", None) or getattr(C, "_PIPES", None)
        if isinstance(cache, dict):
            return bool(cache)
        # 拿不到内部结构就乐观返回 True：release_under_pressure 本身幂等且很便宜，
        # 空转一次的代价远低于漏掉一次该腾的机会。
        return True
    except Exception:  # stability-gate: allow-swallow（结构变化不应让让位通道整体失效）
        return True


def _release_video_cache(reason: str) -> Any:
    from app.core.local_video_pipe_cache import release_under_pressure

    logger.info("[broker] 请视频常驻缓存让位：%s", reason)
    return release_under_pressure(reason=reason)


def default_sources() -> List[ReclaimSource]:
    """内置来源表（按 `cost_s` 升序）。

    cost_s 依据：
      · Ollama —— 实测冷加载 + 8 token 生成共 **5.54s**（2026-10-28）；
      · 视频常驻缓存 —— SVD 管线重载约 **40s**（`推理引擎架构设计.md` P3 实测口径）。
    ⇒ LLM 先让位、视频缓存后让位。方向也符合直觉：聊一句的等待成本远低于重载视频管线。
    """
    return [
        ReclaimSource(
            name="ollama",
            pool=POOL_VRAM,
            cost_s=5.5,
            release=_release_ollama,
            probe=_ollama_loaded_gb,
            available=_ollama_available,
        ),
        ReclaimSource(
            name="video_pipe_cache",
            pool=POOL_RAM,
            cost_s=40.0,
            release=_release_video_cache,
            probe=None,          # 无法预估：内部管线数 × 各自 offload 体积不对外暴露
            available=_video_cache_available,
        ),
    ]


#: 运行时来源表（可被 `register_source()` 扩展；测试可整体替换）
_SOURCES: List[ReclaimSource] = default_sources()


def get_sources() -> List[ReclaimSource]:
    return list(_SOURCES)


def register_source(src: ReclaimSource) -> None:
    """登记一个新来源（同名则替换）。"""
    global _SOURCES
    _SOURCES = [s for s in _SOURCES if s.name != src.name] + [src]
    _SOURCES.sort(key=lambda s: s.cost_s)


def reset_sources() -> None:
    """恢复内置来源表（测试用；生产代码不应调用）。"""
    global _SOURCES
    _SOURCES = default_sources()


def enabled() -> bool:
    """仲裁开关。`SHIGUANG_BROKER=off` ⇒ 完全退化为 P0 之前的行为。"""
    return str(os.environ.get("SHIGUANG_BROKER", "on")).strip().lower() not in _OFF_VALUES


# ══════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════

def ensure_capacity(
    need_gb: float,
    *,
    pool: str = POOL_VRAM,
    reason: str = "",
    safety: float = SAFETY,
) -> Decision:
    """确保 `pool` 里至少有 `need_gb × safety` 可用，不够就按代价从低到高请人让位。

    参数:
      need_gb: 即将占用的量（GB）。**由调用方按自己的注册表给**，本模块不猜。
      pool: `vram`（默认）或 `ram`。
      reason: 写进日志与 note 的人话原因，如"加载 SDXL"。
      safety: 安全余量倍数。

    返回: `Decision`。**永不抛异常** —— 让位是优化，任何失败都应让调用方继续尝试。

    行为要点:
      · 本来就够 ⇒ `skipped`，**一个来源都不碰**（常驻收益不能因为"顺手清一下"而丢掉）；
      · 每让位一个来源，前后各测一次池子，差值记账；
      · 一旦够了立即停手（不顺手多关一个，省得下次白等重载）；
      · 全让完还不够 ⇒ `insufficient`，如实报缺口，不虚报成功。
    """
    need = max(0.0, float(need_gb or 0.0))
    if not enabled():
        return Decision(action="disabled", pool=pool, need_gb=need,
                        free_before_gb=None, free_after_gb=None,
                        note="SHIGUANG_BROKER=off，未仲裁")

    free, readings = read_pool(pool)
    dec = Decision(action="skipped", pool=pool, need_gb=need,
                   free_before_gb=free, free_after_gb=free, readings=readings)

    if free is None:
        dec.action = "insufficient"
        dec.note = "读不到可用%s，无从判断（按不足处理，不虚报）" % (
            "显存" if pool == POOL_VRAM else "内存")
        logger.info("%s", dec.describe())
        return dec

    target = need * max(1.0, float(safety))
    if free >= target:
        dec.note = "本来够（%.2f ≥ %.2f），未让位" % (free, target)
        logger.debug("%s", dec.describe())
        return dec

    # ── 不够，开始按代价升序请人让位 ──
    candidates = [s for s in get_sources() if s.pool == pool]
    candidates.sort(key=lambda s: s.cost_s)
    touched = 0

    for src in candidates:
        if free >= target:
            break
        try:
            if src.available is not None and not src.available():
                continue
        except Exception:  # stability-gate: allow-swallow（可用性检查本身失败不应中断整条让位链）
            logger.debug("[broker] %s 可用性检查失败，跳过", src.name, exc_info=True)
            continue

        est = None
        if src.probe is not None:
            try:
                est = src.probe()
            except Exception:  # stability-gate: allow-swallow（预估失败只影响 note 里的偏差，不影响让位本身）
                logger.debug("[broker] %s 预估失败", src.name, exc_info=True)

        before = free
        raw: Any = None
        err = ""
        try:
            raw = src.release(reason or "资源仲裁")
        except Exception as e:  # stability-gate: allow-swallow（单个来源让位失败不应中断其余来源；结果在 reclaimed 里如实上报）
            err = "%s: %s" % (type(e).__name__, e)
            logger.warning("[broker] %s 让位异常：%s", src.name, err)

        after, _ = read_pool(pool)
        actual = None if (before is None or after is None) else round(after - before, 2)
        if after is not None:
            free = after

        note = ""
        if err:
            note = "让位抛异常（%s）" % err
        elif raw is not None:
            note = "源返回 %s" % (raw if isinstance(raw, (int, float, str)) else type(raw).__name__)
        dec.reclaimed.append(Reclaimed(
            name=src.name, estimated_gb=est, actual_gb=actual,
            ok=not err and (actual is not None and actual > 0), note=note))
        touched += 1

    dec.free_after_gb = free
    if free is not None and free >= target:
        dec.action = "released"
        dec.note = "让位 %d 个来源后够了（%.2f ≥ %.2f）" % (touched, free, target)
    else:
        dec.action = "insufficient"
        gap = None if free is None else round(target - free, 2)
        dec.note = "让位 %d 个来源后仍差 %s GB" % (
            touched, "?" if gap is None else "%.2f" % gap)
    logger.info("%s", dec.describe())
    return dec


def describe() -> Dict[str, Any]:
    """诊断快照（面板/日志用）：开关、来源表、当前读数。**只读，不触发让位**。

    注意：本模块不提供 `__main__` 打印入口 —— 产品代码禁止 `print()`
    （稳定性门禁 ④）。命令行体检请用 `python scripts/broker_status.py`。
    """
    vram, vram_detail = read_pool(POOL_VRAM)
    ram, _ = read_pool(POOL_RAM)
    return {
        "enabled": enabled(),
        "safety": SAFETY,
        "vram_free_gb": vram,
        "vram_readings": vram_detail,
        "ram_free_gb": ram,
        "sources": [
            {"name": s.name, "pool": s.pool, "cost_s": s.cost_s,
             "has_probe": s.probe is not None}
            for s in get_sources()
        ],
    }
