# -*- coding: utf-8 -*-
"""模型仓库 + 懒加载 + 显存水位守卫（2026-10-09）。

解决什么问题（背景）
====================
ComfyUI 能"适配这么多模型"的原因，不是它内置了所有模型，而是：
  · 模型都躺在磁盘上，**用哪个拉哪个**（懒加载）；
  · **用完释放**，一次只占用当前任务需要的显存；
  · 有显存管理（--lowvram 等），保证 8GB 卡也能跑大模型。
本项目之前把 T1–T3 的模型（funasr/CosyVoice2/MuseTalk）当成"都要常驻"，其实
**任何时刻只跑一个重模型**，8GB 绰绰有余 —— 缺的正是这套"按需进出 + 水位守卫"。

本模块做什么
============
· **注册表**：每个本地模型声明「峰值显存 + 懒加载函数 + 释放函数」；
· **acquire()**：加载前查剩余显存，够就加载并缓存；不够就 **LRU 驱逐**最久未用的模型腾空间；
  仍不够 ⇒ **诚实失败**（返回原因：建议排队或降级 CPU），**绝不 OOM 崩溃、绝不假装加载成功**；
· **release() / evict()**：显式释放，把显存还给其它任务。

⚠️ 关于"同时跑多个工作流"的物理真相
==================================
8GB 显存是**硬上限**：两个各需 6GB 的模型**同时**加载必然 OOM。
ComfyUI 也不是真并行，而是**串行队列**（任务排队，一个跑完释放再跑下一个）。
所以正确姿势不是"同时并发"，而是**排队串行 + 水位守卫 + 按需进出**。
本模块是这套姿势的"地基"，上层的任务队列/编排再往上叠。

诚实边界（本模块的红线）
========================
· 显存探测失败（无 CUDA / 无 pynvml）时**如实报告**，不编一个"够用"的假数字；
· 驱逐后仍不够 ⇒ 失败并说明，不悄悄把模型塞进 CPU 冒充加载成功。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 安全系数：预留 15% 显存余量（其余应用/缓存/碎片）
_SAFETY_FACTOR = 1.15


@dataclass
class ModelSpec:
    """一个本地模型的声明。"""
    model_id: str
    vram_mb: int                                   # 峰值显存预估（MB）
    loader: Callable[[], Any]                      # 懒加载函数（真正 import + 载入模型）
    release: Optional[Callable[[Any], None]] = None  # 释放函数（可选，None 则置空缓存引用）

    def __hash__(self) -> int:
        return hash(self.model_id)


@dataclass
class AcquireResult:
    """acquire 的结果（诚实标记）。"""
    ok: bool
    model: Any = None
    cached: bool = False        # 是否命中缓存（未重新加载）
    evicted: List[str] = field(default_factory=list)  # 本次为腾空间驱逐的模型
    reason: str = ""            # 失败原因


class ModelRegistry:
    """模型仓库：懒加载 + LRU 驱逐 + 显存水位守卫。"""

    def __init__(self, free_vram_mb: Optional[Callable[[], int]] = None):
        self._specs: Dict[str, ModelSpec] = {}
        self._cache: Dict[str, Any] = {}       # model_id -> 已加载模型
        self._last_used: Dict[str, float] = {}  # model_id -> 最近使用时间戳（LRU）
        self._lock = threading.RLock()
        self._free_vram = free_vram_mb or _free_vram_mb
        self._tick = 0

    # ── 注册 ─────────────────────────────────────────────────────

    def register(self, spec: ModelSpec) -> None:
        with self._lock:
            self._specs[spec.model_id] = spec

    def is_registered(self, model_id: str) -> bool:
        with self._lock:
            return model_id in self._specs

    def spec(self, model_id: str) -> Optional[ModelSpec]:
        with self._lock:
            return self._specs.get(model_id)

    # ── 显存探测（诚实）──────────────────────────────────────────

    def free_vram_mb(self) -> Optional[int]:
        """当前空闲显存（MB）；探测失败返回 None（不编数字）。"""
        try:
            return self._free_vram()
        except Exception as e:
            logger.debug("[model_registry] 显存探测失败: %s", e)
            return None

    # ── 加载 / 释放（LRU + 水位守卫）──────────────────────────────

    def acquire(self, model_id: str) -> AcquireResult:
        """按需加载模型（含 LRU 驱逐 + 水位守卫，诚实失败）。"""
        with self._lock:
            spec = self._specs.get(model_id)
            if spec is None:
                return AcquireResult(ok=False, reason=f"未注册的模型：{model_id}")

            self._tick += 1
            self._last_used[model_id] = self._tick
            if model_id in self._cache:
                return AcquireResult(ok=True, model=self._cache[model_id], cached=True)

            need = int(spec.vram_mb * _SAFETY_FACTOR)
            free = self.free_vram_mb()

            if free is None:
                # 探测不到显存 ⇒ 只能诚实失败，不赌
                return AcquireResult(ok=False, reason="无法探测显存（无 CUDA/驱动），无法保证能加载")

            evicted: List[str] = []
            while free < need:
                victim = self._lru_victim(exclude=model_id)
                if victim is None:
                    break
                self._evict_locked(victim)
                evicted.append(victim)
                free = self.free_vram_mb() or 0

            if free < need:
                return AcquireResult(
                    ok=False,
                    reason=(f"显存不足：需要约 {need}MB（含安全余量），"
                            f"当前空闲 {free}MB；已驱逐 {evicted or '无'}。"
                            f"建议排队等待或降级 CPU"),
                    evicted=evicted)

            try:
                model = spec.loader()
            except Exception as e:
                logger.warning("[model_registry] 加载模型 %s 失败: %s", model_id, e)
                return AcquireResult(ok=False, reason=f"加载失败：{e}", evicted=evicted)

            self._cache[model_id] = model
            return AcquireResult(ok=True, model=model, cached=False, evicted=evicted)

    def release(self, model_id: str) -> bool:
        """显式释放一个模型（有 release 回调就调它，否则置空缓存引用）。"""
        with self._lock:
            return self._evict_locked(model_id)

    def loaded_models(self) -> List[str]:
        with self._lock:
            return list(self._cache.keys())

    # ── 内部 ─────────────────────────────────────────────────────

    def _lru_victim(self, exclude: str) -> Optional[str]:
        """找最久未用的已加载模型（排除正在 acquire 的那个）。"""
        best, best_tick = None, None
        for mid, tick in self._last_used.items():
            if mid == exclude or mid not in self._cache:
                continue
            if best_tick is None or tick < best_tick:
                best, best_tick = mid, tick
        return best

    def _evict_locked(self, model_id: str) -> bool:
        if model_id not in self._cache:
            return False
        spec = self._specs.get(model_id)
        model = self._cache.pop(model_id, None)
        self._last_used.pop(model_id, None)
        if spec and spec.release and model is not None:
            try:
                spec.release(model)
            except Exception as e:
                logger.debug("[model_registry] 释放 %s 失败（已置空引用）: %s", model_id, e)
        logger.info("[model_registry] 已释放模型显存：%s", model_id)
        return True


def _free_vram_mb() -> int:
    """默认显存探测：torch.cuda.mem_get_info；无 CUDA 则抛异常（调用方转 None）。"""
    import torch  # 延迟导入：无 torch 时不阻断模块 import

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用")
    free, _total = torch.cuda.mem_get_info()
    return int(free // (1024 * 1024))
