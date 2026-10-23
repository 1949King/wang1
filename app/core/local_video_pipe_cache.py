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
from typing import Any, Callable, Dict, List, Tuple

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
            _dispose(old_pipe)
        return pipe, "miss"


def evict(key: Tuple[str, str]) -> bool:
    """显式淘汰某个 key（如生成时 OOM，下次强制重载）。返回是否确有该缓存。"""
    with _lock:
        pipe = _CACHE.pop(key, None)
        _HITS.pop(key, None)
        if pipe is None:
            return False
        _dispose(pipe)
        return True


def clear() -> int:
    """清空全部缓存，返回释放数量（换卡/卸载/测试隔离用）。"""
    with _lock:
        n = len(_CACHE)
        for pipe in _CACHE.values():
            _dispose(pipe)
        _CACHE.clear()
        _HITS.clear()
        return n


def status() -> Dict[str, Any]:
    """供 UI/排障回显：当前常驻了哪些视频管线、各自复用次数、上限。"""
    with _lock:
        entries: List[Dict[str, Any]] = [
            {"kind": k[0], "model_path": k[1], "hits": _HITS.get(k, 0)}
            for k in _CACHE.keys()
        ]
        return {"max_pipes": _MAX_PIPES, "cached": len(entries), "entries": entries}


def _dispose(pipe: Any) -> None:
    """尽力释放一个 pipeline 占用的显存（best-effort，失败不外抛）。"""
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # stability-gate: allow-swallow（torch 未装/CUDA 不可用时无缓存可清；释放是 best-effort，失败无后果）
        pass
    try:
        import gc

        del pipe
        gc.collect()
    except Exception:  # stability-gate: allow-swallow（gc 回收是尽力而为，失败不影响正确性）
        pass


def cached_keys() -> List[Tuple[str, str]]:
    with _lock:
        return list(_CACHE.keys())
