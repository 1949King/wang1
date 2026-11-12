# -*- coding: utf-8 -*-
"""免责声明"已同意"的**服务端**记录（2026-11-12）。

## 为什么不能只靠 localStorage

用户实测：**每次启动都弹免责声明**。QtWebEngine 的 localStorage 在部分环境
（临时 profile / 存储被清 / 无痕式配置）不会持久化，setItem 也不报错——
于是"同意过"等于没记住，合规页面每次弹一次，体验极差。

所以改成**双写**：前端仍写 localStorage（快），同时写这个服务端标记（稳）。
读取时**以服务端为准**（它跨 profile、跨重启都在）。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger("AI短剧编辑器.compliance_accept")


def _root() -> str:
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def state_path() -> str:
    return os.path.join(_root(), "data", "compliance_acceptance.json")


def read_state() -> Dict[str, Any]:
    """返回 accepted/version/at；缺失或坏文件一律按"未同意"处理（合规优先）。"""
    p = state_path()
    try:
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and raw.get("accepted"):
                return {"accepted": True,
                        "version": str(raw.get("version") or ""),
                        "at": str(raw.get("at") or "")}
    except Exception:  # stability-gate: allow-swallow（读不到就当未同意，交给前端再弹）
        logger.warning("[compliance] 记录读取失败，按未同意处理", exc_info=True)
    return {"accepted": False, "version": "", "at": ""}


def write_state(version: str, at: str) -> bool:
    p = state_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"accepted": True, "version": str(version or ""), "at": str(at or "")},
                      f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception:  # stability-gate: allow-swallow（写失败由前端回落 localStorage，不阻断）
        logger.warning("[compliance] 记录写入失败", exc_info=True)
        return False