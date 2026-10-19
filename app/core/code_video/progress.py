# -*- coding: utf-8 -*-
"""渲染进度回调（V4.46 画布节点 SSE 用）。

独立成模块：render_host 有 438 行体积基线，进度桥接不应继续堆进编排主体。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def emit_progress(
    cb: Optional[Callable[[Dict[str, Any]], None]],
    stage: str,
    percent: int,
    detail: str = "",
) -> None:
    """向调用方报告粗粒度进度；回调异常绝不影响渲染。"""
    if cb is None:
        return
    try:
        cb({"stage": stage, "percent": max(0, min(100, int(percent))), "detail": detail})
    except Exception:  # 进度回调是旁路，失败只记日志
        logger.debug("progress callback failed", exc_info=True)
