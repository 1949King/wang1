# -*- coding: utf-8 -*-
"""启动 / 探测画布前端（自研 shiguang-canvas 或 vendor/infinite-canvas）。

⚠️ 本模块管的是**画布前端 HTTP 服务**（加载 React 画布页面），
不是 Agent 进程也不是后端适配层。

三模块对照：
- ``canvas_runtime.py``          → **本文件**：画布前端 HTTP 服务（Python HTTP / vite，端口 3010）
- ``canvas_agent_runtime.py``    → 外部 Node MCP agent（@basketikun/canvas-agent，端口 17371）
- ``project_agent_host.py``      → 自研画布 ↔ 剪辑 Agent 的 Python 适配层（SSE + chat）

引擎：环境变量 ``SHIGUANG_CANVAS_ENGINE`` = ``shiguang``（默认）| ``infinite``。
运行时可通过 ``set_active_canvas_engine()`` 动态切换（重启服务）。

优先顺序（快 → 慢）：
1. 端口已在听 → 直接用
2. 有 dist/ → 进程内 Python 静态服务（秒级）
3. 否则 vite preview / vite dev
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("AI短剧编辑器.canvas_runtime")

DEFAULT_PORT = 3000
STATIC_PORT = 3001
SHIGUANG_PORT = 3010
SHIGUANG_STATIC_PORT = 3011


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def active_canvas_engine() -> str:
    raw = (os.environ.get("SHIGUANG_CANVAS_ENGINE") or "shiguang").strip().lower()
    return raw if raw in ("shiguang", "infinite") else "shiguang"


def set_active_canvas_engine(engine: str) -> str:
    """运行时切换画布引擎（shiguang | infinite），返回生效引擎。

    会停止旧引擎服务并重置单例，下次 get_canvas_runtime() 按新引擎重建。
    供「AI 画布」顶栏切换下拉框调用。
    """
    global _runtime_singleton
    eng = (engine or "").strip().lower()
    if eng not in ("shiguang", "infinite"):
        eng = "shiguang"
    os.environ["SHIGUANG_CANVAS_ENGINE"] = eng
    if _runtime_singleton is not None:
        try:
            _runtime_singleton.stop()
        except Exception as e:
            logger.warning("stop old canvas runtime failed: %s", e)
        _runtime_singleton = None
    return eng


def vendor_canvas_dir() -> Path:
    if active_canvas_engine() == "infinite":
        return project_root() / "vendor" / "infinite-canvas"
    return project_root() / "vendor" / "shiguang-canvas"


def vendor_web_dir() -> Path:
    root = vendor_canvas_dir()
    if active_canvas_engine() == "infinite":
        return root / "web"
    return root


def vendor_dist_dir() -> Path:
    return vendor_web_dir() / "dist"


def canvas_url(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}"


def port_open(host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _SPAHandler(SimpleHTTPRequestHandler):
    """SPA：缺文件时回退 index.html；prompts/、models/ 可回退 public/ 目录（dist 未重建时仍能读离线资源）。"""

    def __init__(self, *args, directory: str = "", public_root: str = "", **kwargs):
        self.public_root = public_root
        super().__init__(*args, directory=directory, **kwargs)

    def translate_path(self, path: str) -> str:
        path = path.split("?", 1)[0].split("#", 1)[0]
        path = path.replace("\\", "/")
        tail = path.lstrip("/")
        local = os.path.join(self.directory, tail) if tail else self.directory
        if os.path.isfile(local):
            return local
        if self.public_root and (tail.startswith("prompts/") or tail.startswith("models/")):
            pub = os.path.join(self.public_root, tail)
            if os.path.isfile(pub):
                return pub
        return local

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        logger.debug("canvas-static %s - %s", self.address_string(), fmt % args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):  # noqa: N802
        # 去掉 query
        path = self.path.split("?", 1)[0]
        local = self.translate_path(path)
        if path != "/" and not os.path.isfile(local) and not os.path.isdir(local):
            self.path = "/index.html"
        return super().do_GET()


class CanvasRuntime:
    """管理画布本机服务（默认自研 shiguang-canvas）。"""

    def __init__(
        self,
        port: Optional[int] = None,
        static_port: Optional[int] = None,
    ):
        eng = active_canvas_engine()
        if port is None:
            port = SHIGUANG_PORT if eng == "shiguang" else DEFAULT_PORT
        if static_port is None:
            static_port = SHIGUANG_STATIC_PORT if eng == "shiguang" else STATIC_PORT
        self.engine = eng
        self.port = port
        self.static_port = static_port
        self._proc: Optional[subprocess.Popen] = None
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._mode: str = ""  # static | vite | external
        self._active_port: int = port

    @property
    def url(self) -> str:
        return canvas_url(self._active_port)

    def is_ready(self) -> bool:
        if port_open(port=self._active_port):
            return True
        # 外部可能已在 3000 起了 dev
        if self._active_port != self.port and port_open(port=self.port):
            self._active_port = self.port
            self._mode = "external"
            return True
        if port_open(port=self.port):
            self._active_port = self.port
            self._mode = "external"
            return True
        return False

    def _start_static_server(self) -> tuple[bool, str]:
        dist = vendor_dist_dir()
        if not (dist / "index.html").is_file():
            return False, "无 dist"
        if self._httpd is not None:
            self._active_port = self.static_port
            self._mode = "static"
            return True, f"画布静态服务已在运行: {self.url}"

        # 端口占用则换用已有服务
        if port_open(port=self.static_port):
            self._active_port = self.static_port
            self._mode = "static"
            return True, f"画布已在运行: {self.url}"

        try:
            public_root = str(vendor_canvas_dir() / "public")
            handler = partial(_SPAHandler, directory=str(dist), public_root=public_root)
            httpd = ThreadingHTTPServer(("127.0.0.1", self.static_port), handler)
            self._httpd = httpd
            self._http_thread = threading.Thread(
                target=httpd.serve_forever, name="CanvasStatic", daemon=True
            )
            self._http_thread.start()
            self._active_port = self.static_port
            self._mode = "static"
            logger.info("canvas static server on %s (dist=%s)", self.url, dist)
            return True, f"画布已启动（静态秒开）: {self.url}"
        except OSError as e:
            logger.warning("static server bind failed: %s", e)
            return False, str(e)
        except Exception as e:
            return False, str(e)

    def _start_vite(self, *, preview: bool) -> tuple[bool, str]:
        web = vendor_web_dir()
        npm = shutil_which("npm")
        npx = shutil_which("npx")
        if not npm and not npx:
            return False, "未找到 npm/npx。请安装 Node.js 后重试。"

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        # 直接调 vite，少一层 npm script 开销
        if npx:
            if preview and (vendor_dist_dir() / "index.html").is_file():
                cmd = [
                    npx, "--yes", "vite", "preview",
                    "--host", "127.0.0.1", "--port", str(self.port), "--strictPort",
                ]
            else:
                cmd = [
                    npx, "--yes", "vite",
                    "--host", "127.0.0.1", "--port", str(self.port), "--strictPort",
                ]
        else:
            script = "start" if preview else "dev"
            cmd = [npm, "run", script, "--", "--host", "127.0.0.1", "--port", str(self.port)]

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(web),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self._active_port = self.port
            self._mode = "vite"
            logger.info("started vite pid=%s preview=%s", self._proc.pid, preview)
            return True, "vite 已拉起"
        except Exception as e:
            return False, f"启动 vite 失败: {e}"

    def ensure_started(
        self,
        wait_seconds: float = 25.0,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> tuple[bool, str]:
        """若未监听则启动。优先 dist 静态服务。"""
        def progress(msg: str) -> None:
            if on_progress:
                try:
                    on_progress(msg)
                except Exception:
                    pass

        if self.is_ready():
            return True, f"画布已在运行: {self.url}"

        web = vendor_web_dir()
        eng = active_canvas_engine()
        if not (web / "package.json").is_file():
            if eng == "shiguang":
                return False, (
                    f"未找到自研画布（期望 {web}）。\n"
                    "请确认 vendor/shiguang-canvas 存在，并执行:\n"
                    "  cd vendor/shiguang-canvas && npm install && npm run build"
                )
            return False, (
                f"未找到 vendor/infinite-canvas（期望 {web}）。\n"
                "请运行: scripts/setup_infinite_canvas.ps1"
            )

        # 1) 静态 dist（最快）
        progress(f"正在秒开画布（引擎={eng}）…")
        ok, msg = self._start_static_server()
        if ok and self.is_ready():
            return True, msg

        # 2) 无 dist：提示并拉 vite（可随后后台 build）
        node_modules = web / "node_modules"
        if not node_modules.is_dir():
            hint = (
                "cd vendor/shiguang-canvas && npm install && npm run build"
                if eng == "shiguang"
                else "scripts/setup_infinite_canvas.ps1 或 cd vendor/infinite-canvas/web && npm install --legacy-peer-deps"
            )
            return False, f"画布依赖未安装。请先运行:\n  {hint}"

        progress("首次需启动 Vite（约 10–30 秒）…")
        if self._proc is None or self._proc.poll() is not None:
            ok, msg = self._start_vite(preview=False)
            if not ok:
                return False, msg

        deadline = time.time() + max(5.0, wait_seconds)
        last_tick = 0.0
        while time.time() < deadline:
            if self.is_ready():
                # 后台异步 build，下次走静态秒开
                self._kick_background_build()
                return True, f"画布已启动: {self.url}"
            if self._proc and self._proc.poll() is not None:
                return False, "画布进程已退出，请检查 Node/npm 与 vendor 依赖"
            now = time.time()
            if now - last_tick >= 2.0:
                left = int(deadline - now)
                progress(f"正在等待 Vite 就绪…（剩余约 {left}s）")
                last_tick = now
            time.sleep(0.25)
        build_hint = (
            "cd vendor/shiguang-canvas && npm run build"
            if active_canvas_engine() == "shiguang"
            else "cd vendor/infinite-canvas/web && npm run build"
        )
        return False, (
            f"等待画布超时（{self.url}）。\n"
            f"可手动: {build_hint}\n"
            "然后重新点「启动画布」走静态秒开。"
        )

    def _kick_background_build(self) -> None:
        """后台 build dist，下次启动秒开。"""
        dist = vendor_dist_dir() / "index.html"
        if dist.is_file():
            return
        web = vendor_web_dir()
        npm = shutil_which("npm")
        if not npm:
            return

        def _build():
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                logger.info("background vite build starting…")
                subprocess.run(
                    [npm, "run", "build"],
                    cwd=str(web),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=300,
                    creationflags=creationflags,
                )
                logger.info("background vite build done: %s", dist.is_file())
            except Exception as e:
                logger.warning("background build failed: %s", e)

        threading.Thread(target=_build, name="CanvasBuild", daemon=True).start()

    def warmup_async(
        self,
        on_done: Optional[Callable[[bool, str], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> None:
        """后台预热，不阻塞 UI。"""
        def _run():
            ok, msg = self.ensure_started(wait_seconds=45.0, on_progress=on_progress)
            if on_done:
                try:
                    on_done(ok, msg)
                except Exception:
                    pass

        threading.Thread(target=_run, name="CanvasWarmup", daemon=True).start()

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None
        self._http_thread = None
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None


def shutil_which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)


_runtime_singleton: Optional[CanvasRuntime] = None


def get_canvas_runtime() -> CanvasRuntime:
    global _runtime_singleton
    if _runtime_singleton is None:
        _runtime_singleton = CanvasRuntime()
    return _runtime_singleton
