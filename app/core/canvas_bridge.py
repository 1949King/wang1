# -*- coding: utf-8 -*-
"""infinite-canvas ↔ 拾光剪影 本地桥。

职责：
- 接收画布导出的图片/视频（HTTP multipart 或本地路径）
- 落盘到 ~/.video_editor_cache/canvas_inbox/
- 可选写入角色库资产（CharacterStore）
- EventBus 推送到剪辑时间线（MATERIAL_TO_TIMELINE）
- 可选开启线性补帧标记（非神经网络）

不嵌入 React 内核；画布仍跑在 localhost WebView。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("AI短剧编辑器.canvas_bridge")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765


def canvas_inbox_dir() -> str:
    root = os.path.join(os.path.expanduser("~"), ".video_editor_cache", "canvas_inbox")
    os.makedirs(root, exist_ok=True)
    return root


def canvas_characters_media_dir(char_id: str = "default") -> str:
    root = os.path.join(
        os.path.expanduser("~"), ".video_editor_cache", "characters", "media", char_id
    )
    os.makedirs(root, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "asset.bin").replace("..", "_")
    keep = "".join(c for c in base if c.isalnum() or c in "._- ()[]")
    return keep or f"asset_{uuid.uuid4().hex[:8]}.bin"


def ingest_local_file(
    src_path: str,
    *,
    title: str = "",
    character_id: str = "",
    character_name: str = "",
    send_to_editor: bool = True,
    enable_interpolation: bool = False,
    source: str = "infinite_canvas",
) -> Dict[str, Any]:
    """复制本地文件到 inbox，可选入轨 / 挂角色资产。"""
    inbox = os.path.abspath(canvas_inbox_dir())
    path = os.path.abspath(src_path)
    if not os.path.isfile(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    ext = os.path.splitext(path)[1].lower()
    dest_name = os.path.basename(path)
    if os.path.dirname(path) == inbox:
        dest = path
    else:
        dest_name = f"{int(time.time())}_{_safe_filename(os.path.basename(path))}"
        dest = os.path.join(inbox, dest_name)
        try:
            shutil.copy2(path, dest)
        except Exception as e:
            return {"success": False, "message": f"复制失败: {e}"}

    asset = {
        "id": f"canvas_{uuid.uuid4().hex[:12]}",
        "path": dest,
        "title": title or os.path.basename(path),
        "ext": ext,
        "kind": "video" if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v") else "image",
        "character_id": character_id or "",
        "character_name": character_name or "",
        "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "enable_interpolation": bool(enable_interpolation),
    }

    if character_id:
        try:
            media_dir = canvas_characters_media_dir(character_id)
            linked = os.path.join(media_dir, dest_name)
            if not os.path.isfile(linked):
                shutil.copy2(dest, linked)
            asset["character_media_path"] = linked
            _append_character_asset(character_id, asset)
        except Exception as e:
            logger.warning("挂角色资产失败: %s", e)

    result: Dict[str, Any] = {
        "success": True,
        "message": f"已入库: {os.path.basename(dest)}",
        "asset": asset,
        "file_path": dest,
    }

    if send_to_editor:
        send_res = emit_canvas_to_editor(
            dest,
            title=asset["title"],
            source=source,
            enable_interpolation=enable_interpolation,
            kind=asset["kind"],
        )
        result["editor"] = send_res
        if not send_res.get("success"):
            result["message"] = send_res.get("message") or result["message"]
            result["success"] = bool(send_res.get("success"))

    return result


def _append_character_asset(character_id: str, asset: Dict[str, Any]) -> None:
    try:
        from app.modules.lego.character_management_module import CharacterStore
    except ImportError:
        from modules.lego.character_management_module import CharacterStore  # type: ignore

    store = CharacterStore()
    char = store.get(character_id)
    if not char:
        return
    assets = list(char.get("generated_assets") or [])
    assets.append(
        {
            "id": asset.get("id"),
            "path": asset.get("character_media_path") or asset.get("path"),
            "kind": asset.get("kind"),
            "title": asset.get("title"),
            "created_at": asset.get("created_at"),
            "source": asset.get("source"),
        }
    )
    # 保留最近 50 条
    store.update(character_id, {"generated_assets": assets[-50:]})


def _image_to_still_video(image_path: str, duration_sec: float = 3.0) -> Optional[str]:
    """把静图转成短视频，便于入时间线。失败返回 None。"""
    ext = os.path.splitext(image_path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        return None
    out = os.path.join(
        canvas_inbox_dir(),
        f"{int(time.time())}_{_safe_filename(os.path.splitext(os.path.basename(image_path))[0])}.still.mp4",
    )
    ffmpeg = "ffmpeg"
    try:
        import shutil

        found = shutil.which("ffmpeg")
        if found:
            ffmpeg = found
    except Exception:
        pass
    cmd = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        image_path,
        "-t",
        str(max(0.5, float(duration_sec))),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        out,
    ]
    try:
        import subprocess
        import sys

        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=flags)
        if r.returncode == 0 and os.path.isfile(out):
            return out
        logger.warning("静图转视频失败: %s", (r.stderr or b"")[:200])
    except Exception as e:
        logger.warning("静图转视频异常: %s", e)
    return None


def emit_canvas_to_editor(
    file_path: str,
    *,
    title: str = "",
    source: str = "infinite_canvas",
    enable_interpolation: bool = False,
    kind: str = "",
) -> Dict[str, Any]:
    """推送到剪辑模块（与 drama_send_to_editor 同通道）。"""
    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    resolved_kind = kind
    if not resolved_kind:
        ext = os.path.splitext(path)[1].lower()
        resolved_kind = (
            "video"
            if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
            else "image"
        )

    timeline_path = path
    if resolved_kind == "image":
        still = _image_to_still_video(path)
        if still:
            timeline_path = still
            resolved_kind = "video"
        else:
            return {
                "success": False,
                "message": "图片入轨需要 ffmpeg 转成短视频，未找到可用 ffmpeg",
                "file_path": path,
            }

    try:
        from app.modules.lego.core import EventBus, EventType
    except ImportError:
        from modules.lego.core import EventBus, EventType  # type: ignore

    bus = EventBus.get_instance()
    bus.emit(
        EventType.MODULE_ACTIVATED,
        {
            "target": "editor",
            "hint": f"画布素材已发送到剪辑：{title or os.path.basename(path)}",
            "source": source,
        },
        source=source,
    )
    bus.emit(
        EventType.MATERIAL_TO_TIMELINE,
        {
            "file_path": timeline_path,
            "title": title,
            "source": source,
            "kind": resolved_kind,
            "enable_interpolation": bool(enable_interpolation),
            "original_path": path,
        },
        source=source,
    )
    return {
        "success": True,
        "message": f"已发送到剪辑：{os.path.basename(timeline_path)}",
        "file_path": timeline_path,
        "enable_interpolation": bool(enable_interpolation),
    }


class _BridgeHandler(BaseHTTPRequestHandler):
    server_version = "ShiguangCanvasBridge/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        logger.debug("bridge %s - %s", self.address_string(), fmt % args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Shiguang-Token",
        )

    def _json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/health"):
            self._json(
                200,
                {
                    "ok": True,
                    "service": "shiguang-canvas-bridge",
                    "inbox": canvas_inbox_dir(),
                    "port": getattr(self.server, "bridge_port", DEFAULT_PORT),
                },
            )
            return
        if parsed.path == "/inject.js":
            js = _INJECT_JS.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(js)))
            self._cors()
            self.end_headers()
            self.wfile.write(js)
            return
        self._json(404, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        ctype = (self.headers.get("Content-Type") or "").lower()

        if parsed.path == "/ingest":
            self._handle_ingest(raw, ctype, parse_qs(parsed.query))
            return
        if parsed.path == "/ingest_path":
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"success": False, "message": "invalid json"})
                return
            path = str(data.get("path") or "")
            res = ingest_local_file(
                path,
                title=str(data.get("title") or ""),
                character_id=str(data.get("character_id") or ""),
                character_name=str(data.get("character_name") or ""),
                send_to_editor=bool(data.get("send_to_editor", True)),
                enable_interpolation=bool(data.get("enable_interpolation", False)),
                source=str(data.get("source") or "infinite_canvas"),
            )
            self._json(200 if res.get("success") else 400, res)
            return
        self._json(404, {"ok": False, "message": "not found"})

    def _handle_ingest(self, raw: bytes, ctype: str, qs: Dict[str, List[str]]) -> None:
        title = (qs.get("title") or [""])[0]
        character_id = (qs.get("character_id") or [""])[0]
        character_name = (qs.get("character_name") or [""])[0]
        send_to_editor = (qs.get("send_to_editor") or ["1"])[0] not in ("0", "false", "False")
        enable_interpolation = (qs.get("enable_interpolation") or ["0"])[0] in (
            "1",
            "true",
            "True",
        )
        filename = (qs.get("filename") or ["upload.bin"])[0]

        if "multipart/form-data" in ctype:
            # 极简 multipart：找 filename= 与空行后的二进制（够用；复杂表单走 /ingest_path）
            try:
                boundary = None
                for part in ctype.split(";"):
                    part = part.strip()
                    if part.startswith("boundary="):
                        boundary = part.split("=", 1)[1].strip().strip('"')
                if not boundary:
                    self._json(400, {"success": False, "message": "no boundary"})
                    return
                marker = ("--" + boundary).encode("utf-8")
                chunks = raw.split(marker)
                file_bytes = None
                for ch in chunks:
                    if b"filename=" not in ch:
                        continue
                    # header / body
                    sep = ch.find(b"\r\n\r\n")
                    if sep < 0:
                        continue
                    header = ch[:sep].decode("utf-8", errors="ignore")
                    body = ch[sep + 4 :]
                    if body.endswith(b"\r\n"):
                        body = body[:-2]
                    if body.endswith(b"--"):
                        body = body[:-2]
                    if body.endswith(b"\r\n"):
                        body = body[:-2]
                    for line in header.split("\r\n"):
                        if "filename=" in line:
                            import re

                            m = re.search(r'filename="([^"]+)"', line)
                            if m:
                                filename = m.group(1)
                    file_bytes = body
                    break
                if file_bytes is None:
                    self._json(400, {"success": False, "message": "no file part"})
                    return
                dest = os.path.join(canvas_inbox_dir(), f"{int(time.time())}_{_safe_filename(filename)}")
                with open(dest, "wb") as f:
                    f.write(file_bytes)
                res = ingest_local_file(
                    dest,
                    title=title or filename,
                    character_id=character_id,
                    character_name=character_name,
                    send_to_editor=send_to_editor,
                    enable_interpolation=enable_interpolation,
                )
                # 已在 inbox，ingest 会再 copy 一份同内容 —— 可接受；若 dest 已在 inbox 则直接用
                self._json(200 if res.get("success") else 400, res)
                return
            except Exception as e:
                self._json(500, {"success": False, "message": str(e)})
                return

        # raw body + filename query
        if not raw:
            self._json(400, {"success": False, "message": "empty body"})
            return
        dest = os.path.join(canvas_inbox_dir(), f"{int(time.time())}_{_safe_filename(filename)}")
        try:
            with open(dest, "wb") as f:
                f.write(raw)
        except Exception as e:
            self._json(500, {"success": False, "message": str(e)})
            return
        res = ingest_local_file(
            dest,
            title=title or filename,
            character_id=character_id,
            character_name=character_name,
            send_to_editor=send_to_editor,
            enable_interpolation=enable_interpolation,
        )
        self._json(200 if res.get("success") else 400, res)


_INJECT_JS = r"""
(function () {
  if (window.__SHIGUANG_BRIDGE_INJECTED__) return;
  window.__SHIGUANG_BRIDGE_INJECTED__ = true;
  var BRIDGE = "http://127.0.0.1:18765";
  var panel = document.createElement("div");
  panel.id = "shiguang-bridge-panel";
  panel.style.cssText = [
    "position:fixed", "right:16px", "bottom:16px", "z-index:2147483647",
    "background:#111827", "color:#e5e7eb", "border:1px solid #374151",
    "border-radius:12px", "padding:12px", "width:260px",
    "font:13px/1.4 system-ui,sans-serif", "box-shadow:0 8px 24px rgba(0,0,0,.4)"
  ].join(";");
  panel.innerHTML = [
    "<div style='font-weight:700;margin-bottom:8px'>拾光剪影</div>",
    "<div style='opacity:.8;margin-bottom:8px;font-size:12px'>把画布生成的图/视频发送到剪辑时间线</div>",
    "<label style='display:flex;gap:6px;align-items:center;margin-bottom:8px;font-size:12px'>",
    "<input id='sg-interp' type='checkbox'/> 入轨后开线性补帧</label>",
    "<input id='sg-file' type='file' accept='image/*,video/*' style='width:100%;margin-bottom:8px'/>",
    "<button id='sg-send' style='width:100%;padding:8px;border:0;border-radius:8px;",
    "background:#2563eb;color:#fff;font-weight:600;cursor:pointer'>发送到剪辑</button>",
    "<div id='sg-status' style='margin-top:8px;font-size:11px;opacity:.85'></div>"
  ].join("");
  document.documentElement.appendChild(panel);
  function setStatus(t) {
    var el = document.getElementById("sg-status");
    if (el) el.textContent = t || "";
  }
  document.getElementById("sg-send").onclick = async function () {
    var input = document.getElementById("sg-file");
    var file = input && input.files && input.files[0];
    if (!file) { setStatus("请先选择图片或视频文件"); return; }
    var interp = !!(document.getElementById("sg-interp") || {}).checked;
    setStatus("上传中…");
    try {
      var q = new URLSearchParams({
        filename: file.name,
        title: file.name,
        send_to_editor: "1",
        enable_interpolation: interp ? "1" : "0"
      });
      var res = await fetch(BRIDGE + "/ingest?" + q.toString(), {
        method: "POST",
        body: file,
        headers: { "Content-Type": file.type || "application/octet-stream" }
      });
      var data = await res.json();
      setStatus(data.message || (data.success ? "已发送" : "失败"));
    } catch (e) {
      setStatus("桥接失败: " + e);
    }
  };
})();
"""


class CanvasBridgeServer:
    """后台线程 HTTP 桥。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), _BridgeHandler)
            self._httpd.bridge_port = self.port  # type: ignore[attr-defined]
            self._thread = threading.Thread(
                target=self._httpd.serve_forever, name="CanvasBridge", daemon=True
            )
            self._thread.start()
            logger.info("canvas bridge listening on %s", self.base_url)
            return True
        except OSError as e:
            # 端口占用：假定已有桥在跑
            logger.warning("canvas bridge bind failed (%s), assume already running", e)
            return True
        except Exception as e:
            logger.error("canvas bridge start failed: %s", e)
            return False

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None
        self._thread = None


_bridge_singleton: Optional[CanvasBridgeServer] = None


def get_canvas_bridge() -> CanvasBridgeServer:
    global _bridge_singleton
    if _bridge_singleton is None:
        _bridge_singleton = CanvasBridgeServer()
    return _bridge_singleton
