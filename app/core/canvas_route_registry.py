# -*- coding: utf-8 -*-
"""画布桥路由注册表（从 canvas_server.py 抽出，2026-09-27 整改 A4 批次 0）

为什么单独成模块
----------------
路由表原本定义在 `canvas_server.py` 里。把端点 handler 按域拆到独立 mixin
模块后，那些 mixin 需要 `@_route_get` / `@_route_post` 装饰器——若它们从
`canvas_server` 导入，就会形成「canvas_server → mixin → canvas_server」的
循环导入。把路由表下沉到本模块（零依赖），两边都从这里导入，循环即解。

历史与纪律（原样保留自 canvas_server.py）
----------------------------------------
请求进来先查表，未命中才回落老的 if 链（老链行为完全不变）。
这样加端点不用再往千行链里塞，老链后续可逐条迁出。

⚠️ 曾经的教训：端点被追加到文件末尾 → 落进上一个函数体内、且在 `return`
   之后 → 语法合法、静态检查全绿、但永远走不到（`/host/plugins/install`
   就是这样死的）。`_verify/check_canvas_routes.py` 现在会用 AST 检测这类
   不可达路由。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_ROUTES_GET: Dict[str, str] = {}
_ROUTES_POST: Dict[str, str] = {}


def _route_get(path: str):
    """把一个 handler 方法注册为 GET 路由。"""

    def _deco(fn):
        if path in _ROUTES_GET:
            raise ValueError(f"GET 路由重复注册: {path}")
        _ROUTES_GET[path] = fn.__name__
        return fn

    return _deco


def _route_post(path: str):
    """把一个 handler 方法注册为 POST 路由。"""

    def _deco(fn):
        if path in _ROUTES_POST:
            raise ValueError(f"POST 路由重复注册: {path}")
        _ROUTES_POST[path] = fn.__name__
        return fn

    return _deco


def dispatch_table(handler: Any, table: Dict[str, str], path: str, **kw) -> bool:
    """路由表分发：命中则执行并返回 True，未命中返回 False（交给老 if 链）。

    统一在这里兜异常，路由表里的 handler 不用各自写 try/except 大网。
    """
    name = table.get(path)
    if not name:
        return False
    fn = getattr(handler, name, None)
    if fn is None:
        logger.error("路由表指向了不存在的方法: %s -> %s", path, name)
        return False
    try:
        fn(**kw)
    except Exception as exc:  # 桥接层统一兜底，避免连接崩掉
        logger.exception("[%s] 路由处理失败", path)
        try:
            handler._json(500, {"ok": False, "message": str(exc)})
        except Exception:
            logger.debug("写 500 响应失败", exc_info=True)
    return True
