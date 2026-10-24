# -*- coding: utf-8 -*-
"""引擎遥测（Engine Telemetry）—— EPLB 的对应物：按**实测延迟与失败率**选栈，而不是写死优先级。

为什么需要（用户 2026-10-24 指令，对应「DeepSeek EPLB 按负载动态分配」）：
  · 现状：`code_video/diffsynth` 优先写死在代码里；实测 SDXL 首图 diffsynth 需 415s、
    diffusers 仅 35s ⇒ 写死优先级会把一次「首图卡死 7 分钟」的事故稳定复现给用户。
  · 目标：按 (设备指纹, 引擎, 模型架构) 记「首图耗时 / 稳态耗时 / 失败率」，
    决策器据此选栈；新设备没有证据时退回保守默认（不瞎猜）。

与既有证据库同款纪律（照 quality_prior / budget_pacer）：
  · 纯 stdlib、包 try、异常不外抛、原子写；测试用 `SHIGUANG_ENGINE_TELEMETRY_PATH` 隔离。
  · EMA 平滑（alpha=0.3），只累计真实执行结果；**不记录估算值**。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("AI短剧编辑器.core.ai.engine_telemetry")

_ALPHA = 0.3
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_DEFAULT = os.path.join(_APP_ROOT, "data", "engine_telemetry.json")

_lock = threading.RLock()


def _path() -> str:
    return os.environ.get("SHIGUANG_ENGINE_TELEMETRY_PATH") or _DEFAULT


def _device_id() -> str:
    """设备指纹（换卡/换机后证据不复用，避免拿旧卡数据误导新卡）。"""
    try:
        from app.core.neural.device_profile import probe

        return str(probe(use_cache=True).get("device_id") or "unknown")
    except Exception:
        return "unknown"


def _key(engine: str, model_arch: str, device_id: str) -> str:
    return "%s|%s|%s" % (device_id, engine, model_arch or "-")


def _load() -> Dict[str, Any]:
    try:
        p = _path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        logger.debug("[engine_telemetry] 读取失败（从空库起步）", exc_info=True)
    return {}


def _save(data: Dict[str, Any]) -> None:
    try:
        p = _path()
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        logger.debug("[engine_telemetry] 落盘失败（不阻断）", exc_info=True)


def record(*, engine: str, model_arch: str, ok: bool,
           first_ms: float = 0.0, steady_ms: float = 0.0,
           device_id: Optional[str] = None) -> None:
    """记一次真实执行。首图/稳态耗时只在该次确实测到时传（不传=不更新）。"""
    if not engine:
        return
    with _lock:
        data = _load()
        k = _key(engine, model_arch, device_id or _device_id())
        rec = dict(data.get(k) or {"n": 0, "ok": 0, "first_ms": None,
                                   "steady_ms": None, "last_ts": 0.0})
        rec["n"] = int(rec.get("n") or 0) + 1
        if ok:
            rec["ok"] = int(rec.get("ok") or 0) + 1
        for field, val in (("first_ms", first_ms), ("steady_ms", steady_ms)):
            v = float(val or 0.0)
            if v <= 0:
                continue
            prev = rec.get(field)
            rec[field] = round(v, 1) if prev is None else round(
                _ALPHA * v + (1 - _ALPHA) * float(prev), 1)
        rec["last_ts"] = time.time()
        data[k] = rec
        _save(data)


def score(*, engine: str, model_arch: str,
          device_id: Optional[str] = None) -> Dict[str, Any]:
    """读出该引擎在该架构上的证据；无证据返回 n=0（调用方不当成 0 秒）。"""
    with _lock:
        data = _load()
        rec = data.get(_key(engine, model_arch, device_id or _device_id())) or {}
    n = int(rec.get("n") or 0)
    ok = int(rec.get("ok") or 0)
    return {
        "engine": engine, "model_arch": model_arch, "n": n,
        "fail_rate": round(1.0 - (ok / n), 3) if n else 0.0,
        "first_ms": rec.get("first_ms"), "steady_ms": rec.get("steady_ms"),
        "last_ts": rec.get("last_ts") or 0.0,
    }


def recommend(*, candidates: Sequence[str], model_arch: str,
              min_samples: int = 3,
              device_id: Optional[str] = None) -> Tuple[Optional[str], List[str]]:
    """在候选后端里按证据挑一个；证据不足返回 (None, reasons)，由调用方用默认偏好。

    打分口径（越小越好）：
      失败率优先（>20% 直接淘汰）→ 首图耗时（用户第一眼体感）→ 稳态耗时。
    """
    reasons: List[str] = []
    scored: List[Tuple[float, str, Dict[str, Any]]] = []
    for eng in candidates:
        s = score(engine=eng, model_arch=model_arch, device_id=device_id)
        if s["n"] < min_samples:
            reasons.append("%s：证据不足（n=%d < %d）" % (eng, s["n"], min_samples))
            continue
        if s["fail_rate"] > 0.2:
            reasons.append("%s：失败率 %.0f%% 过高，淘汰" % (eng, s["fail_rate"] * 100))
            continue
        first = float(s["first_ms"] or 0.0)
        steady = float(s["steady_ms"] or 0.0)
        cost = s["fail_rate"] * 10000.0 + first + 0.2 * steady
        reasons.append("%s：n=%d 失败 %.0f%% 首图 %.1fs 稳态 %.2fs"
                       % (eng, s["n"], s["fail_rate"] * 100,
                          first / 1000.0, steady / 1000.0))
        scored.append((cost, eng, s))
    if not scored:
        return None, reasons or ["无候选"]
    scored.sort(key=lambda x: x[0])
    return scored[0][1], reasons


def snapshot() -> Dict[str, Any]:
    """全量证据（供 UI/排障）。"""
    with _lock:
        data = _load()
    return {"path": _path(), "device_id": _device_id(), "records": data}
