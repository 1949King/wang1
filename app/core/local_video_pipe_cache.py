"""本地视频管线进程级缓存 —— 视频侧「用法感知」的落点。

为什么需要（2026-10-24，用户指令「视频侧同样做用法感知策略」）：
  图像侧的固定开销是 offload 搬运，实测「首图后热提升整卡」能省 25%；
  但 **SVD 实测 offload 全程不亏、不能整卡**（见 local_video_infer._infer_svd 的血泪调优），
  所以视频侧的固定开销**不在搬运，而在每次 `from_pretrained` 重载 4.2GB 权重**——
  首帧慢，而且第二次、第三次同样慢（每次都重新读盘 + 建 offload hook）。
  本模块把「已准备好的 pipeline」按 (kind, model_path) 缓存在进程内，
  第二次起直接复用 ⇒ 省掉整段加载时间。

与既有模式一致：图像引擎本就是进程级单例常驻 `_pipe`（diffusers_image.get_diffusers_image_engine）。
这里只是把同一套「常驻复用」搬到视频侧，并按显存约束**只保留 1 个**视频管线（LRU 淘汰）。

纪律：
  · 顶层不 import torch/diffusers（延迟 import 原则）；loader 由调用方传入。
  · 加载在锁内串行：避免并发把两份 4.2GB 同时塞进内存。
  · 失败不写缓存；调用方可在 OOM 后 evict(key) 强制下次重载。
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.core.local_video_pipe_cache")

# 视频模型动辄数 GB，进程内最多常驻这么多个（默认 1，可经环境变量放宽）。
try:
    _MAX_PIPES = max(1, int(os.environ.get("SHIGUANG_VIDEO_PIPE_CACHE_MAX", "1")))
except (TypeError, ValueError):
    _MAX_PIPES = 1

_lock = threading.RLock()
# key -> pipeline；OrderedDict 做 LRU
_CACHE: "OrderedDict[Tuple[str, str], Any]" = OrderedDict()
# key -> 该 key 被命中复用的次数（观测用）
_HITS: Dict[Tuple[str, str], int] = {}


def get_or_load(key: Tuple[str, str], loader: Callable[[], Any]) -> Tuple[Any, str]:
    """返回 (pipeline, source)，source ∈ {"hit", "miss"}。

    loader() 只在未命中时调用；loader 抛异常 ⇒ 不写缓存、原样上抛（调用方决定回退）。
    """
    with _lock:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            _HITS[key] = _HITS.get(key, 0) + 1
            return _CACHE[key], "hit"
        # 锁内加载：串行化，避免并发重复载入撑爆内存
        pipe = loader()
        _CACHE[key] = pipe
        _CACHE.move_to_end(key)
        _HITS.setdefault(key, 0)
        # LRU 淘汰（保留最新）
        while len(_CACHE) > _MAX_PIPES:
            old_key, old_pipe = _CACHE.popitem(last=False)
            _HITS.pop(old_key, None)
            logger.info("[video_pipe_cache] 淘汰旧管线 %s（上限 %d）", old_key, _MAX_PIPES)
            del old_pipe  # 先断引用再回收（顺序反了 gc 收不掉，2026-10-24 教训）
            _release_vram()
        return pipe, "miss"


def evict(key: Tuple[str, str]) -> bool:
    """显式淘汰某个 key（如生成时 OOM，下次强制重载）。返回是否确有该缓存。"""
    with _lock:
        pipe = _CACHE.pop(key, None)
        _HITS.pop(key, None)
        if pipe is None:
            return False
        pipe = None  # 先断引用再回收，否则 gc 收不掉（weakref 测试锁死该语义）
        _release_vram()
        return True


def clear() -> int:
    """清空全部缓存，返回释放数量（换卡/卸载/测试隔离用）。"""
    with _lock:
        n = len(_CACHE)
        _CACHE.clear()  # 断 dict 引用（无其他持有者 ⇒ refcount 归零，gc 必收）
        _HITS.clear()
        _release_vram()  # gc → synchronize → empty_cache 收口
        return n


def status() -> Dict[str, Any]:
    """供 UI/排障回显：当前常驻了哪些视频管线、各自复用次数、上限。"""
    with _lock:
        entries: List[Dict[str, Any]] = [
            {"kind": k[0], "model_path": k[1], "hits": _HITS.get(k, 0)} for k in _CACHE.keys()
        ]
        return {"max_pipes": _MAX_PIPES, "cached": len(entries), "entries": entries}


def _release_vram() -> None:
    """统一回收真源 ⇒ `app.core.neural.inference_cache.release_vram_sequence()`
    （gc → synchronize → empty_cache，+ ipc_collect best-effort）。

    ★ 2026-10-24 实测教训：SD1.5 整卡常驻 → unload → 同进程再 load SDXL，
      显存碎片换页卡死 >22min。正确顺序 = 先 gc 掉引用、再 synchronize、
      最后 empty_cache。此前本文件把该序列拆成两半且都错位：
      `_dispose` 只调 empty_cache（引用未断时 = 空转）、`_gc_release` 只调
      gc.collect（缺 sync/empty_cache）——现收口为单一调用，勿再拆。
    调用方纪律不变：**先断全部引用，再调本函数**（weakref 测试锁死）。
    """
    try:
        from app.core.neural.inference_cache import release_vram_sequence

        release_vram_sequence()
    except Exception:  # stability-gate: allow-swallow（回收失败最坏是显存晚一步释放，不影响正确性）
        logger.debug("[video_pipe_cache] 显存回收序列失败", exc_info=True)


def available_ram_gb() -> Optional[float]:
    """跨平台可用内存（GB）；取不到返回 None。"""
    try:
        import psutil

        return psutil.virtual_memory().available / 1024**3
    except Exception:  # stability-gate: allow-swallow（psutil 未装是常态：项目不强制该依赖，下面 ctypes/proc 两条原生路径就是为它准备的降级链）
        pass
    try:
        if os.name == "nt":
            import ctypes

            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = _MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return st.ullAvailPhys / 1024**3
        else:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024 / 1024**3
    except (
        Exception
    ):  # stability-gate: allow-swallow（内存水位探测是 best-effort；取不到时调用方按保守处理）
        return None
    return None


def release_under_pressure(reason: str = "", floor_gb: Optional[float] = None) -> int:
    """内存吃紧时主动让位：全部淘汰并回收，返回释放条数。

    ★ 为什么必须有（2026-10-24 实测，我自己引入的代价）：常驻管线把 offload 权重留在
      CPU 内存，SVD 一条就占 ~6.8GB；而**图像引擎是另一个单例、不走本缓存**，两者叠加
      会把 15GB 级机器压到可用 <2GB ⇒ 实测 SDXL 稳态 22.12s → 25.16s（+13.7%）。
      所以「谁要加载大权重，先叫对方让位」，让常驻只在内存宽裕时生效。

    floor_gb：可用内存低于此才释放；None ⇒ 读 SHIGUANG_RESIDENT_FLOOR_GB，默认 2.3
      （≈15GB 机器的 15%）。**可用内存取不到时按释放处理**（宁可多 reload 一次，
      不可把内存压爆）。
    """
    if floor_gb is None:
        try:
            floor_gb = float(os.environ.get("SHIGUANG_RESIDENT_FLOOR_GB", "2.3"))
        except (TypeError, ValueError):
            floor_gb = 2.3
    avail = available_ram_gb()
    if avail is not None and avail > floor_gb:
        return 0
    with _lock:
        if not _CACHE:
            return 0
        n = len(_CACHE)
        _CACHE.clear()  # 先断 dict 引用
        _HITS.clear()
        _release_vram()  # 最后统一回收（gc → sync → empty_cache 收口）
    logger.info(
        "[video_pipe_cache] 内存压力让位：释放 %d 条（可用 %sGB ≤ 水位 %.1fGB）%s",
        n,
        ("%.2f" % avail) if avail is not None else "未知",
        floor_gb,
        ("· " + reason) if reason else "",
    )
    return n


def cached_keys() -> List[Tuple[str, str]]:
    with _lock:
        return list(_CACHE.keys())
