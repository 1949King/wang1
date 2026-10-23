# -*- coding: utf-8 -*-
"""混合算力偏好（B）—— 把「0=纯本地 … 100=纯云端」滑块翻译成路由裁定偏好。

来源：用户指令「本地部署模型 + 云端 API 混合运算」+「异构动态协作引擎为什么切换后没起作用」。

诊断（2026-10-23 实测，写进代码免得后人再查）：
  · 本机 SD 类执行引擎**健康且非降级**：`resolve_execution_engine()` 返回
    `engine=diffsynth, is_fallback=False`；SD1.5/SDXL/SVD 权重均在 app/models/cache。
  · 真正缺的不是引擎，是**「自动混合」这一档从未接进决策出口**：画布只能手动
    选「本机」渠道或某云端渠道，`decide_execution()` 里没有「按用户算力偏好 +
    目标函数(质量/成本/延迟/预算)自动裁本地 vs 云端」的入口。

本模块只做「偏好」这一层，**不做执行**（R4 职责边界）：
  bias(0-100) → mode ∈ {local, engine, cloud}
  · local   (0–24) ：倾向本地引擎；本地不可用才退云端（R9 可见降级）。
  · engine  (25–74)：交给既有治理排序（provider_caps 的 V = q̂ − λ·price + 六模式
                     收益打分）——这才是规格书意义上的「动态混合」，默认档。
  · cloud   (75–100)：倾向云端；云端不可用才回退本地（本地恒为兜底锚点）。

纪律（与 budget_pacer / quality_prior 同款）：
  · 纯 stdlib（json/os/logging），**不 import torch/diffusers 等重依赖**，
    以便在画布 HTTP 线程内也能安全惰性调用。
  · 一切异常绝不抛出：读失败按默认 50（engine）启动，写失败静默返回 False。
  · 原子写（tmp + os.replace），避免半写文件被下次读成损坏。
  · 测试隔离：环境变量 `COMPUTE_BIAS_STORE_PATH` 覆盖路径（别写进正式 data/）。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict

logger = logging.getLogger("AI短剧编辑器.core.ai.compute_bias")

# 三档边界（写死，别在别处再算一遍——单一真源）
MODE_LOCAL = "local"
MODE_ENGINE = "engine"
MODE_CLOUD = "cloud"

_LOCAL_MAX = 24          # bias ≤ 24 ⇒ 倾向本地
_CLOUD_MIN = 75          # bias ≥ 75 ⇒ 倾向云端
_DEFAULT_BIAS = 50       # 默认 engine（动态混合）

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))  # app/core/ai → app → 仓库根
_DEFAULT_STORE = os.path.join(_APP_ROOT, "data", "compute_bias.json")

_lock = threading.RLock()


def _resolve_store() -> str:
    """账本路径：环境变量 > 默认（data/compute_bias.json）。测试据此隔离。"""
    return os.environ.get("COMPUTE_BIAS_STORE_PATH") or _DEFAULT_STORE


def bias_mode(bias: int) -> str:
    """纯函数：0-100 的算力偏好 → local/engine/cloud。越界先夹到界内。"""
    try:
        v = int(bias)
    except (TypeError, ValueError):
        return MODE_ENGINE
    v = max(0, min(100, v))
    if v <= _LOCAL_MAX:
        return MODE_LOCAL
    if v >= _CLOUD_MIN:
        return MODE_CLOUD
    return MODE_ENGINE


class ComputeBias:
    """进程级算力偏好读写（持久化到 data/compute_bias.json）。"""

    def __init__(self, store_path: str = "") -> None:
        self._path = store_path or _resolve_store()
        self._bias = _DEFAULT_BIAS
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "bias" in data:
                    self._bias = max(0, min(100, int(data["bias"])))
        except Exception:
            logger.debug("[compute_bias] 加载失败，按默认 engine(50) 启动", exc_info=True)

    def get(self) -> int:
        with _lock:
            self._ensure_loaded()
            return self._bias

    def mode(self) -> str:
        return bias_mode(self.get())

    def set(self, bias: int) -> bool:
        try:
            v = max(0, min(100, int(bias)))
        except (TypeError, ValueError):
            return False
        with _lock:
            self._ensure_loaded()
            self._bias = v
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"bias": v}, f, ensure_ascii=False)
                os.replace(tmp, self._path)
                return True
            except Exception:
                logger.debug("[compute_bias] 持久化失败（不阻断主链路）", exc_info=True)
                return False

    def status(self) -> Dict[str, Any]:
        """供 UI/能力回显：当前档位与三档边界。"""
        b = self.get()
        return {"bias": b, "mode": bias_mode(b),
                "local_max": _LOCAL_MAX, "cloud_min": _CLOUD_MIN,
                "store_path": self._path}


_instance: Any = None


def get_bias() -> ComputeBias:
    """进程级单例（默认 data/compute_bias.json，缺省 engine=50）。"""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ComputeBias()
    return _instance
