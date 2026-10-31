# -*- coding: utf-8 -*-
"""团队协作服务端（Team Hub HTTP）—— **独立进程 / 独立端口**，只同步文档。

## 与 canvas_server 的边界（不要合并！）

| | canvas_server | team_server（本文件） |
|---|---|---|
| 监听 | `127.0.0.1:18765` | `0.0.0.0:18770`（可配） |
| 能力 | 跑 GPU 推理、读写本机文件、起子进程 | **只有文档 CRUD + 交接** |
| 暴露到局域网 | ❌ 绝对不行 | ✅ 本来就是给同事连的 |

所以团队模式**不会**打开 canvas 的局域网入口；同事只能同步画布文档，
其余能力仍只在本机。

## 鉴权

`POST /team/join` 换取令牌（响应里只出现一次），之后所有请求带
`Authorization: Bearer <token>`。令牌在库里只存 sha256。

## CORS

画布页面来自 `http://127.0.0.1:18765`，而团队服务是另一个端口 ⇒ 跨域。
这里放开 `Access-Control-Allow-Origin: *`：服务本身是**内网 + 令牌鉴权**，
放开来源的收益（少配一次白名单，IP 变了也能用）大于风险；**但令牌校验不能省**。

## 启动

```
python -m app.core.team_server --host 0.0.0.0 --port 18770 --root data/team
```
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from app.core.team_discovery import Beacon
from app.core.team_hub import ConflictError, Hub, LockedError, TeamError

logger = logging.getLogger(__name__)

DEFAULT_PORT = 18770
#: 单请求体上限（与 Hub 的 bundle 上限对齐，另留 5MB 给 JSON 包装）
MAX_BODY = 105 * 1024 * 1024
SERVER_NAME = "shiguang-team-hub"
SERVER_VERSION = "1"


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class _TeamHandler(BaseHTTPRequestHandler):
    server_version = "ShiguangTeam/" + SERVER_VERSION
    hub: Hub = None  # type: ignore[assignment]
    beacon_name: str = "拾光剪影团队"

    # ── 基础响应 ────────────────────────────────────────
    def _send(self, status: int, payload: Any) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status: int, code: str, message: str = "", **extra: Any) -> None:
        self._send(status, {"ok": False, "code": code, "message": message or code, **extra})

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("[team] " + fmt, *args)

    # ── 读取请求 ────────────────────────────────────────
    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise TeamError("too_large", "请求体过大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise TeamError("bad_json", "请求体不是合法 JSON：%s" % e) from e
        if not isinstance(data, dict):
            raise TeamError("bad_json", "请求体必须是对象")
        return data

    def _token(self) -> str:
        auth = str(self.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return str(parse_qs(urlparse(self.path).query).get("token", [""])[0] or "")

    def _member(self) -> Dict[str, Any]:
        m = self.hub.auth(self._token())
        if not m:
            raise TeamError("unauthorized", "令牌无效或缺失（先 POST /team/join）")
        return m

    # ── 路由 ────────────────────────────────────────────
    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        try:
            self._route_get(urlparse(self.path).path.rstrip("/") or "/")
        except TeamError as e:
            self._err(self._status_of(e), e.code, e.message)
        except Exception:
            logger.exception("[team] GET 失败")
            self._err(500, "internal", "服务端异常")

    def do_POST(self) -> None:
        try:
            self._route_post(urlparse(self.path).path.rstrip("/") or "/")
        except TeamError as e:
            extra: Dict[str, Any] = {}
            if isinstance(e, ConflictError):
                extra = {"current_rev": e.current_rev, "author": e.author}
            elif isinstance(e, LockedError):
                extra = {"holder": e.holder, "expires_at": e.expires_at}
            self._err(self._status_of(e), e.code, e.message, **extra)
        except Exception:
            logger.exception("[team] POST 失败")
            self._err(500, "internal", "服务端异常")

    @staticmethod
    def _status_of(e: TeamError) -> int:
        return {
            "unauthorized": 401,
            "forbidden": 403,
            "not_found": 404,
            "conflict": 409,
            "locked": 423,
            "too_large": 413,
        }.get(e.code, 400)

    def _route_get(self, path: str) -> None:
        hub = self.hub
        if path in ("/team/ping", "/ping"):
            self._send(200, {"ok": True, "service": SERVER_NAME, "name": self.beacon_name,
                             "version": SERVER_VERSION})
            return
        if path in ("/team/info", "/team"):
            self._send(200, {"ok": True, "service": SERVER_NAME, "name": self.beacon_name,
                             "version": SERVER_VERSION, **hub.stats()})
            return
        if path == "/team/members":
            self._member()
            self._send(200, {"ok": True, "members": hub.members()})
            return
        if path == "/team/projects":
            self._member()
            self._send(200, {"ok": True, "projects": hub.list_projects()})
            return
        if path == "/team/inbox":
            me = self._member()
            self._send(200, {"ok": True, "items": hub.inbox(me["id"])})
            return
        parts = path.split("/")
        # /team/projects/{id}
        if len(parts) == 4 and parts[1] == "team" and parts[2] == "projects":
            self._member()
            rev = int(parse_qs(urlparse(self.path).query).get("rev", ["0"])[0] or 0)
            self._send(200, {"ok": True, **hub.get_bundle(parts[3], rev)})
            return
        # /team/projects/{id}/versions
        if len(parts) == 5 and parts[4] == "versions":
            self._member()
            self._send(200, {"ok": True, "versions": hub.versions(parts[3])})
            return
        raise TeamError("not_found", "未知端点：%s" % path)

    def _route_post(self, path: str) -> None:
        hub = self.hub
        if path == "/team/join":
            data = self._body()
            info = hub.register_member(str(data.get("name") or ""), str(data.get("role") or "editor"))
            self._send(200, {"ok": True, **info})
            return
        if path == "/team/projects":
            me = self._member()
            data = self._body()
            res = hub.create_project(str(data.get("name") or ""), me["id"], data.get("bundle") or {})
            self._send(200, {"ok": True, **res})
            return
        parts = path.split("/")
        if len(parts) == 5 and parts[1] == "team" and parts[2] == "projects":
            me = self._member()
            pid, action = parts[3], parts[4]
            data = self._body()
            if action == "push":
                res = hub.push(pid, me["id"], data.get("bundle") or {},
                               int(data.get("base_rev") or 0), str(data.get("message") or ""))
            elif action == "claim":
                res = hub.claim(pid, me["id"], int(data.get("ttl") or 600))
            elif action == "release":
                res = hub.release(pid, me["id"])
            elif action == "handoff":
                res = hub.handoff(pid, me["id"], str(data.get("to") or ""),
                                  str(data.get("message") or ""))
            else:
                raise TeamError("not_found", "未知动作：%s" % action)
            self._send(200, {"ok": True, **res})
            return
        # /team/inbox/{hid}/ack
        if len(parts) == 5 and parts[1] == "team" and parts[2] == "inbox" and parts[4] == "ack":
            me = self._member()
            res = hub.ack_handoff(parts[3], me["id"])
            self._send(200, {"ok": True, **res})
            return
        raise TeamError("not_found", "未知端点：%s" % path)


class TeamServer:
    """可启停的团队服务（供 Qt6 设置页/CLI 调用）。"""

    def __init__(self, root: str, host: str = "0.0.0.0", port: int = DEFAULT_PORT,
                 name: str = "拾光剪影团队") -> None:
        self.hub = Hub(root)
        self.host = host
        self.port = port
        self.name = name
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._beacon: Optional[Beacon] = None

    def start(self) -> Dict[str, Any]:
        if self._httpd is not None:
            return {"ok": True, "host": self.host, "port": self.port, "already": True}
        handler = type("_BoundTeamHandler", (_TeamHandler,), {"hub": self.hub, "beacon_name": self.name})
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._httpd.daemon_threads = True
        # port=0 时由内核分配：把实际端口写回来，测试/设置页要显示它
        self.port = int(getattr(self._httpd, "server_port", self.port) or self.port)
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="TeamHub", daemon=True)
        self._thread.start()
        # 局域网自动发现：服务端一起广播，同事那边「扫描」即可看到
        self._beacon = Beacon(self.name, self.port, self.lan_ip())
        self._beacon.start()
        logger.info("[team] 服务已启动 http://%s:%d（本机 %s）",
                    self.host, self.port, self.lan_ip())
        return {"ok": True, "host": self.host, "port": self.port, "lan_ip": self.lan_ip(),
                "discovery": True, "address": "http://%s:%d" % (self.lan_ip(), self.port)}

    def stop(self) -> None:
        if self._beacon is not None:
            self._beacon.stop()
            self._beacon = None
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    @staticmethod
    def lan_ip() -> str:
        """本机在局域网里的地址（不发包，只让内核选路）。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                return str(s.getsockname()[0])
            finally:
                s.close()
        except Exception:  # stability-gate: allow-swallow（离线时退回本机地址，不影响启动）
            return "127.0.0.1"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="拾光剪影 · 团队协作服务端")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--root", default=os.path.join("data", "team"))
    ap.add_argument("--name", default="拾光剪影团队")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    srv = TeamServer(args.root, args.host, args.port, args.name)
    info = srv.start()
    logger.info("团队服务已启动：%s", json.dumps(info, ensure_ascii=False))
    logger.info("同事在局域网里填这个地址：%s", info.get("address"))
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，正在停止…")
        srv.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
