# -*- coding: utf-8 -*-
"""画布桥 · 团队协作端点（V4.49.1 · 2026-10-31）

| 端点 | 作用 |
|---|---|
| `GET  /host/team/status`   | 本机团队服务是否在跑 + 地址 + 统计 |
| `POST /host/team/start`    | 启动本机团队服务（0.0.0.0:18770） |
| `POST /host/team/stop`     | 停止 |
| `GET  /host/team/discover` | 局域网扫描（UDP，只能由后端做——浏览器发不了 UDP） |
| `POST /host/team/inbox-map`| 剪辑器 clip.path（本地绝对路径）→ 画布能 fetch 的 `/inbox_file/…` |
| `POST /host/team/materialize`| 团队附件 → 本机素材库（同事真要接着剪时间线时用） |
| `POST /host/team/poster`   | 本机视频抽一帧当封面（附件列表缩略图） |

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
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from app.core.canvas_route_registry import _route_get, _route_post

logger = logging.getLogger(__name__)

#: 进程级单例（一个画布进程只跑一个团队服务）
_SERVER: Optional[Any] = None

#: 只认团队附件地址：`…/team/projects/{id}/assets/{64位sha}[?token=…]`
#: **这是 SSRF 的闸门** —— 不加这条，本机会被当成任意内网 URL 的下载代理。
_MATERIALIZE_URL_RE = re.compile(
    r"^https?://[^/\s]+/team/projects/[^/?#]+/assets/([a-f0-9]{64})/?(?:\?[^\s]*)?$", re.I
)

#: 单文件下载上限（与 Hub 的 MAX_ASSET_BYTES 对齐）
_MATERIALIZE_MAX = 512 * 1024 * 1024

#: 抽帧只认画布自己的媒体路径：`/inbox_file/x.mp4`、`/editor_file/x.mp4`
#: （可带 `http://127.0.0.1:端口` 前缀）。**不接受绝对路径** —— 否则这个端点
#: 就成了「让 ffmpeg 读任意本机文件再回一张图」的探测工具。
_POSTER_URL_RE = re.compile(
    r"^(?:https?://127\.0\.0\.1(?::\d+)?)?/(inbox_file|editor_file)/([^/?#\\]+)$", re.I
)

#: 封面默认缩略宽度：列表里显示 44px 宽，320 已足够 retina，再大只是白占带宽
_POSTER_WIDTH = 320


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

    @_route_post("/host/team/materialize")
    def _p_host_team_materialize(self, parsed, raw: bytes, ctype: str) -> None:
        """把一个团队附件**下载到本机素材库**，返回本地路径。

        为什么需要：同事拉下来的时间线片段记的是团队 URL，剪辑器只认本地文件路径，
        不落地就永远只能「看」不能「接着剪」。

        ## 为什么一次只下一个

        `canvas_server` 的请求有 30 秒上限。局域网传 200MB 约 2~5 秒、放一批还行，
        但十来个片段叠起来必然超时，留下半个文件更难查。所以约定**前端串行逐个调**，
        单次只处理一个 URL，超时风险归零。

        ## SSRF 闸门

        只接受形如 `http://<host>/team/projects/<id>/assets/<64位sha>` 的地址，
        其余一律 400 —— 否则本机就成了「任意内网 URL 的下载代理」。
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
        url = str((body or {}).get("url") or "").strip()
        name = str((body or {}).get("name") or "").strip()
        m = _MATERIALIZE_URL_RE.match(url)
        if not m:
            self._json(400, {"ok": False, "code": "bad_url",
                             "message": "只接受团队附件地址（…/team/projects/{id}/assets/{sha}）"})
            return
        sha = m.group(1).lower()
        try:
            from app.core.canvas_bridge import canvas_inbox_dir

            inbox = canvas_inbox_dir()
        except Exception:
            logger.debug("[/host/team/materialize] 取 inbox 目录失败", exc_info=True)
            self._json(500, {"ok": False, "message": "取不到画布素材目录（canvas_inbox_dir）"})
            return
        os.makedirs(inbox, exist_ok=True)
        base = os.path.basename(name) or (sha[:12] + ".bin")
        # Windows 非法字符会直接让 open() 失败；`..` 之类也会把 basename 变成空或越级
        base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", base)[:120]
        if base in (".", "..", ""):
            base = sha[:12] + ".bin"
        # 加 sha 前缀：绝不覆盖用户素材库里已有的同名文件（成片.mp4 满天飞）
        dest = os.path.join(inbox, "team_%s_%s" % (sha[:8], base))
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            self._json(200, {"ok": True, "path": dest, "bytes": os.path.getsize(dest),
                             "cached": True})
            return
        tmp = dest + ".part"
        got = 0
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "shiguang-team/1"})
            with urllib.request.urlopen(req, timeout=20) as resp, open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > _MATERIALIZE_MAX:
                        raise ValueError("超过 %dMB 上限" % (_MATERIALIZE_MAX // 1048576))
                    f.write(chunk)
        except Exception as e:
            try:
                os.remove(tmp)
            except OSError:
                logger.debug("[/host/team/materialize] 清理半截文件失败 %s", tmp, exc_info=True)
            logger.warning("[/host/team/materialize] 下载失败 %s: %s", url, e)
            self._json(200, {"ok": False, "code": "download_failed",
                             "message": "下载失败：%s" % _friendly(e)})
            return
        if got <= 0:
            try:
                os.remove(tmp)
            except OSError:
                logger.debug("[/host/team/materialize] 清理空文件失败 %s", tmp, exc_info=True)
            self._json(200, {"ok": False, "code": "empty", "message": "对方返回了 0 字节"})
            return
        os.replace(tmp, dest)
        self._json(200, {"ok": True, "path": dest, "bytes": got})

    @_route_post("/host/team/poster")
    def _p_host_team_poster(self, parsed, raw: bytes, ctype: str) -> None:
        """给本机视频抽一帧当封面，回 `data_url`（JPEG base64）。

        ## 为什么必须是后端抽帧，不能让浏览器自己截

        实测（QT WebEngine，与画布同一内核）：

        | 探测 | 结果 |
        |---|---|
        | `canPlayType('video/mp4; codecs="avc1.42E01E"')` | `""`（不支持） |
        | `<video src="x.mp4">` | `error.code = 4`（SRC_NOT_SUPPORTED） |
        | `<video src="x.webm">` | 正常，`readyState = 4` |

        pip 装的 PyQt6-WebEngine **不带 H.264/AAC**，而本产品自己渲染的成片正是
        h264 ⇒ 浏览器里既放不出画面，`canvas.drawImage(video)` 也拿不到像素。
        所以「前端截首帧」这条路对 mp4 根本不存在，只能回到 ffmpeg。

        ## 边界

        · 只认 `/inbox_file/` 与 `/editor_file/`（见 `_POSTER_URL_RE`），绝不接受
          任意绝对路径；文件不存在如实回 `not_found`。
        · 抽帧给了 20 秒上限：画布桥的请求本身有 30 秒硬上限，超了连接已被对端放弃。
        · 抽不出来（无 ffmpeg / 编码怪 / 空文件）回 `ok=False` 并写明原因 ——
          封面是锦上添花，不能让它拦住上传，但也不能假装成功。
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
        src = str((body or {}).get("path") or "").strip()
        m = _POSTER_URL_RE.match(src)
        if not m:
            self._json(400, {"ok": False, "code": "bad_path",
                             "message": "只接受 /inbox_file/… 或 /editor_file/… 的路径"})
            return
        try:
            at = float((body or {}).get("at", 0.35))
        except (TypeError, ValueError):
            at = 0.35
        try:
            width = int((body or {}).get("width") or _POSTER_WIDTH)
        except (TypeError, ValueError):
            width = _POSTER_WIDTH
        # 夹到合理区间：太小看不清，太大 base64 撑爆 JSON 响应
        at = min(max(at, 0.0), 600.0)
        width = min(max(width, 96), 640)

        try:
            # 🔴 必须写成 `from app.core.canvas_bridge import …`（直接导子模块）：
            # 写成 `from app.core import canvas_bridge` 时，只要 `app.core` 上已经有
            # `canvas_bridge` 属性（真实模块被谁先 import 过），`_handle_fromlist`
            # 就直接取属性、**绕过 sys.modules** ⇒ 测试里替不掉，还静默用真目录。
            from app.core.canvas_bridge import _safe_filename, canvas_inbox_dir, canvas_outbox_dir

            sub, name = m.group(1).lower(), _safe_filename(m.group(2))
            base_dir = canvas_inbox_dir() if sub == "inbox_file" else canvas_outbox_dir()
            fpath = os.path.join(base_dir, name)
        except Exception as e:
            logger.debug("[/host/team/poster] 解析路径失败 %s", src, exc_info=True)
            self._json(200, {"ok": False, "code": "bad_path",
                             "message": "定位不到本机文件：%s" % _friendly(e)})
            return
        if not os.path.isfile(fpath):
            self._json(200, {"ok": False, "code": "not_found",
                             "message": "本机没有这个文件（%s）" % name})
            return
        try:
            from app.core.canvas_shot_vision import _grab_frame

            jpeg = _grab_frame(fpath, at, width=width, timeout=20)
        except Exception as e:
            logger.debug("[/host/team/poster] 抽帧异常 %s", fpath, exc_info=True)
            self._json(200, {"ok": False, "code": "frame_failed",
                             "message": "抽帧失败：%s" % _friendly(e)})
            return
        if not jpeg:
            self._json(200, {"ok": False, "code": "frame_failed",
                             "message": "抽不出帧（没装 ffmpeg 或视频编码无法解码）"})
            return
        import base64

        self._json(200, {"ok": True, "at": at, "width": width, "bytes": len(jpeg),
                         "data_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")})
