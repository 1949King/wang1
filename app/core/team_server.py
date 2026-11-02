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

**附件字节流是例外**：`<video src="…">` / `<img src="…">` 带不了请求头，所以
`GET /team/projects/{id}/assets/{sha}` 额外接受 `?token=` 查询参数 —— 代价是令牌
会出现在 URL 里（浏览器历史 / 服务日志可见）。这是内网 + 一次性令牌 + 只读字节流
的权衡，不适用密码类凭据；真要收紧就得上签名 URL（带过期时间），本轮不做。

## 附件（2026-11-02）

bundle 是 JSON，塞不下视频：base64 会让 100MB 上限在 200 张图内撞线，而本地路径
（`/inbox_file/x.mp4`）到同事机上就是 404。所以**大文件走独立端点**，边收边写盘
（512MB 视频不进内存），bundle 里只留 `mediaIndex` 映射。

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
import hashlib
import json
import logging
import os
import re
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from app.core.team_discovery import Beacon
from app.core.team_hub import (ConflictError, Hub, LockedError, MAX_ASSET_BYTES,
                               TeamError)

logger = logging.getLogger(__name__)

DEFAULT_PORT = 18770
#: 单请求体上限（与 Hub 的 bundle 上限对齐，另留 5MB 给 JSON 包装）
MAX_BODY = 105 * 1024 * 1024
#: 附件请求体上限（Hub 会再校验一遍，这里拦是为了**不白收 512MB 再报错**）
MAX_ASSET_BODY = MAX_ASSET_BYTES + (1 << 20)
#: 流式落盘的读块大小（64KB：8GB 机器上 512MB 也不会一次进内存）
_CHUNK = 64 * 1024
SERVER_NAME = "shiguang-team-hub"
SERVER_VERSION = "2"
#: 允许从附件名里挑 `kind` 的取值
_ASSET_KINDS = frozenset(["image", "video", "audio", "text", "file"])


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class _TeamHandler(BaseHTTPRequestHandler):
    server_version = "ShiguangTeam/" + SERVER_VERSION
    hub: Hub = None  # type: ignore[assignment]
    beacon_name: str = "拾光剪影团队"

    # ── 基础响应 ────────────────────────────────────────
    def _send(self, status: int, payload: Any, extra: Optional[Dict[str, str]] = None) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: str, mime: str, name: str = "") -> None:
        """字节流响应，支持 `Range`（浏览器 `<video>` 要能拖进度条才不卡）。"""
        size = os.path.getsize(path)
        start, end = 0, size - 1
        status = 200
        rng = str(self.headers.get("Range") or "").strip()
        if rng.startswith("bytes="):
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:                       # bytes=-N ⇒ 末尾 N 字节
                    start = max(0, size - int(m.group(2) or 0))
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length")
        if name:
            # 中文名要 percent-encode，裸 UTF-8 进 header 会让某些客户端解析失败
            from urllib.parse import quote
            self.send_header("Content-Disposition",
                             "inline; filename*=UTF-8''%s" % quote(name))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(_CHUNK, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return              # 客户端拖动进度条会主动断开，属正常
                left -= len(chunk)

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

    def _tmp_dir(self) -> str:
        """临时落点必须在 hub.root 底下 —— 跨盘 `os.replace` 会抛 EXDEV。"""
        d = os.path.join(self.hub.root, "tmp")
        os.makedirs(d, exist_ok=True)
        return d

    def _raw_to_tmp(self, limit: int) -> Tuple[str, str, int]:
        """请求体**流式**写进临时文件，返回 (tmp 路径, sha256, 字节数)。

        为什么不能 `self.rfile.read(length)`：512MB 成片一次性进内存，在 8GB 机器上
        会直接触发换页、把整个服务拖死；而且中途断开时已经收的字节全白读。
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise TeamError("bad_asset", "附件内容为空（0 字节不登记）")
        if length > limit:
            # 在**读之前**就拒：否则等于白收几百兆再报错
            raise TeamError("too_large", "附件过大（%.0fMB > %dMB），成片请先压缩或走网盘"
                            % (length / 1048576.0, limit // 1048576))
        fd, tmp = tempfile.mkstemp(prefix="asset_", suffix=".part", dir=self._tmp_dir())
        digest = hashlib.sha256()
        got = 0
        try:
            with os.fdopen(fd, "wb") as f:
                while got < length:
                    chunk = self.rfile.read(min(_CHUNK, length - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    digest.update(chunk)
                    got += len(chunk)
        except BaseException:
            self._drop(tmp)
            raise
        if got != length:
            self._drop(tmp)
            raise TeamError("bad_asset", "上传中断（收到 %d / %d 字节），请重试一次"
                            % (got, length))
        return tmp, digest.hexdigest(), got

    @staticmethod
    def _drop(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            logger.debug("[team] 临时文件清理失败 %s", path, exc_info=True)

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
    def _assets_route(self, method: str) -> bool:
        """附件端点（二进制，不在 JSON 路由表里）。**返回 True = 已处理**。

        | 方法 | 路径 | 作用 |
        |---|---|---|
        | GET    | `/team/projects/{id}/assets` | 列出附件元信息 |
        | GET    | `/team/projects/{id}/assets/{sha}` | 取字节流（支持 Range） |
        | POST   | `/team/projects/{id}/assets?name=&kind=` | 上传（body = 原始字节） |
        | DELETE | `/team/projects/{id}/assets/{sha}` | 删登记（无引用才删字节） |

        单独判断而**不并进 `_route_post` 的 `len(parts)==5` 分支**：那个分支会把
        `assets` 当成 action 去解 JSON，二进制请求会被当坏 JSON 拒掉。
        """
        parts = urlparse(self.path).path.rstrip("/").split("/")
        if (len(parts) not in (5, 6) or parts[1] != "team" or parts[2] != "projects"
                or parts[4] != "assets"):
            return False
        pid = parts[3]
        sha = unquote(parts[5]) if len(parts) == 6 else ""
        if method == "GET":
            self._member()
            if not sha:
                self._send(200, {"ok": True, "assets": self.hub.list_assets(pid)})
            else:
                path, row = self.hub.asset_path_of(pid, sha)
                self._send_file(path, str(row["mime"]), str(row["name"]))
            return True
        if method == "POST":
            me = self._member()
            if sha:
                raise TeamError("not_found", "上传请用 /assets（URL 末尾不带 sha）")
            query = parse_qs(urlparse(self.path).query)
            name = unquote(str((query.get("name") or [""])[0]))
            kind = str((query.get("kind") or ["file"])[0] or "file")
            # 归属提示（「镜 03」）与封面 sha：都是可选，缺了就不记 —— 别编默认值
            owner = unquote(str((query.get("owner") or [""])[0]))
            poster = str((query.get("poster") or [""])[0] or "")
            if poster and not re.fullmatch(r"[a-f0-9]{64}", poster, re.I):
                poster = ""          # 形不合法就当没给，不能把乱字符串写进库里
            tmp, digest, size = self._raw_to_tmp(MAX_ASSET_BODY)
            res = self.hub.commit_asset_file(pid, me["id"], name, tmp, digest, size,
                                             kind if kind in _ASSET_KINDS else "file",
                                             str(self.headers.get("Content-Type") or ""),
                                             owner=owner, poster=poster)
            self._send(200, {"ok": True, **res})
            return True
        if method == "DELETE":
            self._member()
            if not sha:
                raise TeamError("not_found", "要删哪个附件？URL 末尾要带 sha256")
            self._send(200, {"ok": True, **self.hub.delete_asset(pid, sha)})
            return True
        return False

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        try:
            if self._assets_route("GET"):
                return
            self._route_get(urlparse(self.path).path.rstrip("/") or "/")
        except TeamError as e:
            self._err(self._status_of(e), e.code, e.message)
        except Exception:
            logger.exception("[team] GET 失败")
            self._err(500, "internal", "服务端异常")

    def do_DELETE(self) -> None:
        try:
            if self._assets_route("DELETE"):
                return
            raise TeamError("not_found", "未知端点：%s" % urlparse(self.path).path)
        except TeamError as e:
            self._err(self._status_of(e), e.code, e.message)
        except Exception:
            logger.exception("[team] DELETE 失败")
            self._err(500, "internal", "服务端异常")

    def do_POST(self) -> None:
        try:
            if self._assets_route("POST"):
                return
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
        # /team/projects/{id}/diff?from=&to=
        if len(parts) == 5 and parts[4] == "diff":
            self._member()
            q = parse_qs(urlparse(self.path).query)

            def _rev(name: str) -> int:
                try:
                    return int((q.get(name) or ["0"])[0] or 0)
                except (TypeError, ValueError):
                    # 参数写坏了按「不指定」处理（自动取最近两版），别回 500 让人猜
                    return 0

            self._send(200, {"ok": True, **hub.diff(parts[3], _rev("from"), _rev("to"))})
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
