# -*- coding: utf-8 -*-
"""全局质量总闸（2026-10-25）—— 与 compute_bias 并列的用户级旋钮。

为什么需要
==========
算力滑块（compute_bias）只决定「本地还是云端」；但同一个引擎也有快/高质量档
（draft/standard/fine/cinema → 引擎 fast/high/final）。此前质量档只能由节点自身的
qualityTier 决定，没有「全局默认」。本模块补一个**总闸**：请求没写 quality 时由它兜底。

口径
====
· 档位：draft / standard / fine / cinema（与画布/引擎既有档位同名）；
· 非法值 ⇒ 回落 standard（并告警），绝不猜成 cinema；
· 持久化 data/quality_gate.json（可用环境变量 SHIGUANG_QUALITY_GATE 覆盖路径，便于测试）；
· 纯 stdlib，线程安全（读写锁），失败不阻断主链路。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict

logger = logging.getLogger("AI短剧编辑器.core.ai.quality_gate")

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_STORE = os.path.join(_APP_ROOT, "data", "quality_gate.json")

VALID = ("draft", "standard", "fine", "cinema")
DEFAULT = "standard"


def _path() -> str:
    return os.environ.get("SHIGUANG_QUALITY_GATE", "").strip() or _DEFAULT_STORE


def normalize(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in VALID else DEFAULT


class QualityGate:
    """进程级质量总闸。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._value = DEFAULT
        self._load()

    def _load(self) -> None:
        p = _path()
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                self._value = normalize((data or {}).get("quality"))
        except Exception:
            logger.debug("[quality_gate] 读取失败，按默认 %s", DEFAULT, exc_info=True)
            self._value = DEFAULT

    def get(self) -> str:
        with self._lock:
            return self._value

    def set(self, value: Any) -> bool:
        v = str(value or "").strip().lower()
        if v not in VALID:
            return False
        with self._lock:
            self._value = v
            p = _path()
            try:
                os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({"quality": v}, f, ensure_ascii=False)
            except Exception:
                logger.debug("[quality_gate] 持久化失败（不阻断）", exc_info=True)
        return True

    def status(self) -> Dict[str, Any]:
        return {"quality": self.get(), "valid": list(VALID), "default": DEFAULT}


_GATE: QualityGate | None = None
_GATE_LOCK = threading.Lock()


def get_gate() -> QualityGate:
    global _GATE
    with _GATE_LOCK:
        if _GATE is None:
            _GATE = QualityGate()
        return _GATE


def get_quality(value: Any = "") -> str:
    """优先用调用方显式值；空/非法时用总闸。"""
    v = str(value or "").strip().lower()
    if v in VALID:
        return v
    return get_gate().get()
