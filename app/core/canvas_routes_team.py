# -*- coding: utf-8 -*-
"""画布桥 · 团队协作端点（V4.49.1 · 2026-10-31）

| 端点 | 作用 |
|---|---|
| `GET  /host/team/status`   | 本机团队服务是否在跑 + 地址 + 统计 |
| `POST /host/team/start`    | 启动本机团队服务（0.0.0.0:18770） |
| `POST /host/team/stop`     | 停止 |
| `GET  /host/team/discover` | 局域网扫描（UDP，只能由后端做——浏览器发不了 UDP） |
| `POST /host/team/inbox-map`| 剪辑器 clip.path（本地绝对路径）→ 画布能 fetch 的 `/inbox_file/…` |

## 为什么这些端点必须走 canvas_server（127.0.0.1）

它们是**本机管理面**：只有本机能启停团队服务、只有本机能发 UDP 广播。
同事端只访问 team_server 的文档端点，永远看不到这四个。

## 为什么单开 mixin

`canvas_routes_post.py` / `canvas_routes_get.py` 都已接近 2,000 行规模守卫上限，
按 dub/roughcut/digital_human/execution 的先例例外开。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from app.core.canvas_route_registry import _route_get, _route_post

logger = logging.getLogger(__name__)

#: 进程级单例（一个画布进程只跑一个团队服务）
_SERVER: Optional[Any] = None


def _cs():
    from app.core import canvas_server

    return canvas_server


def _friendly(exc: BaseException) -> str:
    """把套接字类异常翻成人话；翻译层坏掉时退回原始文本（绝不因此吞掉错误）。"""
    try:
        from app.core.team_discovery import friendly_socket_error

        return friendly_socket_error(exc)
    except Exception:  # stability-gate: allow-swallow（翻译失败不该让错误响应本身 500）
        return str(exc)


def _status_payload() -> Dict[str, Any]:
    srv = _SERVER
    # 单例存在 ≠ 正在跑：stop() 后 _httpd 会被置空，这里必须一起判
    if srv is None or getattr(srv, "_httpd", None) is None:
        return {"ok": True, "running": False, "address": "", "lan_ip": "", "port": 0,
                "stats": {}, "hint": "点「启动团队服务」后，同事才能连这台机器"}
    try:
        stats = srv.hub.stats()
    except Exception:  # stability-gate: allow-swallow（统计失败不该让状态接口 500）
        logger.debug("[team] 读取统计失败", exc_info=True)
        stats = {}
    return {"ok": True, "running": True, "address": "http://%s:%d" % (srv.lan_ip(), srv.port),
            "lan_ip": srv.lan_ip(), "port": int(srv.port), "name": srv.name,
            "root": srv.hub.root, "stats": stats}


class CanvasTeamRoutesMixin:
    """团队协作端点集合（由 `_BridgeHandler` 继承）。"""

    @_route_get("/host/team/status")
    def _g_host_team_status(self, parsed) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        self._json(200, _status_payload())

    @_route_post("/host/team/start")
    def _p_host_team_start(self, parsed, raw: bytes, ctype: str) -> None:
        global _SERVER
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        try:
            if _SERVER is None:
                import os

                from app.core.team_server import DEFAULT_PORT, TeamServer

                root = str(body.get("root") or os.path.join("data", "team"))
                _SERVER = TeamServer(
                    root=root,
                    host=str(body.get("host") or "0.0.0.0"),
                    port=int(body.get("port") or DEFAULT_PORT),
                    name=str(body.get("name") or "拾光剪影团队"),
                )
            info = _SERVER.start()
            self._json(200, {"ok": True, **info, **_status_payload()})
        except Exception as e:
            logger.exception("[/host/team/start] 失败")
            self._json(500, {"ok": False, "message": f"团队服务启动失败：{_friendly(e)}"})

    @_route_post("/host/team/stop")
    def _p_host_team_stop(self, parsed, raw: bytes, ctype: str) -> None:
        global _SERVER
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            if _SERVER is not None:
                _SERVER.stop()
                _SERVER = None   # 不清单例的话，状态接口会一直报 running=True
        except Exception:
            logger.exception("[/host/team/stop] 失败")
        self._json(200, {"ok": True, **_status_payload()})

    @_route_get("/host/team/discover")
    def _g_host_team_discover(self, parsed) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core.team_discovery import scan

            found = scan(timeout=2.0)
            self._json(200, {"ok": True, "servers": found})
        except Exception as e:
            logger.exception("[/host/team/discover] 失败")
            self._json(500, {"ok": False, "message": f"局域网扫描失败：{_friendly(e)}",
                             "servers": []})

    @_route_post("/host/team/inbox-map")
    def _p_host_team_inbox_map(self, parsed, raw: bytes, ctype: str) -> None:
        """把剪辑器 `clip.path`（本地绝对路径）翻成画布能 fetch 的 `/inbox_file/…`。

        ## 为什么只做「路径换算」而不是「后端代传」

        时间线里的片段用绝对路径引用素材（`D:\\…\\inbox\\成片.mp4`），画布 JS
        **无权 fetch 本地文件**，所以前端没法自己上传。看起来该由后端代读上传，
        但 `canvas_server` 的请求有 **30 秒上限** —— 一条 200MB 成片必然超时，
        留下半个文件。所以这里只回一张映射表（毫秒级），字节交给前端走
        `/inbox_file/` 直传（同源、流式、无超时）。

        不在 inbox 目录内的路径（用户从别处拖进来的视频）**如实列进 `outside`**，
        由界面提示「这几条要手工挪进素材库」——绝不假装同步成功。
        """
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        paths = body.get("paths") if isinstance(body, dict) else None
        if not isinstance(paths, list):
            self._json(400, {"ok": False, "message": "paths 必须是数组"})
            return
        try:
            from app.core.canvas_bridge import canvas_inbox_dir

            inbox = os.path.normcase(os.path.abspath(canvas_inbox_dir()))
        except Exception:
            logger.debug("[/host/team/inbox-map] 取 inbox 目录失败", exc_info=True)
            self._json(500, {"ok": False, "message": "取不到画布素材目录（canvas_inbox_dir）"})
            return
        mapping: Dict[str, str] = {}
        outside: list = []
        for p in paths[:500]:
            raw_path = str(p or "").strip()
            if not raw_path:
                continue
            try:
                abs_path = os.path.normcase(os.path.abspath(raw_path))
            except Exception:
                outside.append(raw_path)
                continue
            # 同一目录才算；用 commonpath 而非 startswith，避免 `inbox2` 冒充 `inbox`
            try:
                inside = os.path.commonpath([abs_path, inbox]) == inbox
            except ValueError:      # 不同盘符：Windows 上 commonpath 会抛
                inside = False
            if not inside or not os.path.isfile(abs_path):
                outside.append(raw_path)
                continue
            name = os.path.basename(abs_path)
            from urllib.parse import quote

            mapping[raw_path] = "/inbox_file/" + quote(name)
        self._json(200, {"ok": True, "map": mapping, "outside": outside})
