# -*- coding: utf-8 -*-
"""启动 / 探测画布前端（自研 shiguang-canvas 或 Tauri 桌面壳）。

⚠️ 本模块管的是**画布前端 HTTP 服务**（加载 React 画布页面），
不是 Agent 进程也不是后端适配层。

三模块对照：
- ``canvas_runtime.py``          → **本文件**：画布前端 HTTP 服务（Python HTTP / vite，端口 3010），
                                   或 Tauri 桌面进程拉起（engine=tauri）
- ``canvas_agent_runtime.py``    → 外部 Node MCP agent（@basketikun/canvas-agent，端口 17371）
- ``project_agent_host.py``      → 自研画布 ↔ 剪辑 Agent 的 Python 适配层（SSE + chat）

画布引擎选择（环境变量 ``SHIGUANG_CANVAS_ENGINE``）：
- ``shiguang``（默认）：自研 shiguang-canvas，WebEngine 嵌入式（保留旧路径）
- ``tauri``            ：AI-Canvas-tauri 独立桌面进程，Qt 主程序不嵌入 WebEngine

优先顺序（快 → 慢）：
1. 端口已在听 → 直接用（Tauri 模式下端口探活仅作健康检查）
2. engine=tauri → 拉起 Tauri 进程（注入 SHIGUANG_BRIDGE_TOKEN / SHIGUANG_BRIDGE_URL）
3. 有 dist/ → 进程内 Python 静态服务（秒级）
4. 否则 vite preview / vite dev
"""
from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("AI短剧编辑器.canvas_runtime")

DEFAULT_PORT = 3000
STATIC_PORT = 3001
SHIGUANG_PORT = 3010
SHIGUANG_STATIC_PORT = 3011

# Tauri 桌面壳相关常量（engine=tauri 时使用）
TAURI_VITE_PORT = 1420  # Tauri 开发期 vite dev 端口，与 tauri.conf.json.devUrl 一致
TAURI_BRIDGE_URL_DEFAULT = "http://127.0.0.1:18765"


def _resource_root() -> Path:
    """资源根目录：开发环境为项目根；PyInstaller 打包后为 _MEIPASS 解压目录。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def project_root() -> Path:
    return _resource_root()


def active_canvas_engine() -> str:
    """返回当前画布引擎：shiguang（默认 WebEngine 嵌入）或 tauri（独立桌面进程）。

    由环境变量 ``SHIGUANG_CANVAS_ENGINE`` 控制，默认 shiguang。
    """
    eng = (os.environ.get("SHIGUANG_CANVAS_ENGINE") or "shiguang").strip().lower()
    # 兼容历史取值，统一收敛为 shiguang / tauri 两类
    if eng in ("tauri", "aic", "ai-canvas"):
        return "tauri"
    return "shiguang"


def set_active_canvas_engine(engine: str) -> str:
    """切换画布引擎：shiguang（WebEngine 嵌入）或 tauri（独立桌面进程）。

    会停止旧引擎服务并重置单例，下次 get_canvas_runtime() 按新引擎重建。
    保留旧路径作为 fallback，不破坏现有调用方。
    """
    global _runtime_singleton
    eng = "tauri" if engine in ("tauri", "aic", "ai-canvas") else "shiguang"
    os.environ["SHIGUANG_CANVAS_ENGINE"] = eng
    if _runtime_singleton is not None:
        try:
            _runtime_singleton.stop()
        except Exception as e:
            logger.warning("stop old canvas runtime failed: %s", e)
        _runtime_singleton = None
    return eng


def vendor_canvas_dir() -> Path:
    return project_root() / "vendor" / "shiguang-canvas"


def vendor_web_dir() -> Path:
    return vendor_canvas_dir()


def vendor_dist_dir() -> Path:
    return vendor_web_dir() / "dist"


_ENTRY_SRC_RE = re.compile(r"""<script[^>]+\bsrc\s*=\s*["']([^"']+)["']""", re.I)


def dist_integrity_problem(dist: Optional[Path] = None) -> Optional[str]:
    """校验 dist 产物完整性，返回问题描述（``None`` = 完整）。

    🔴 只检查 ``index.html`` 存在是不够的（2026-10-25 实测翻车）：
    运行期 dist 被重建/搬走后，``index.html`` 可能是旧的、``assets/*.js`` 已换名，
    此时静态服务照样「启动成功」，但页面一加载所有 chunk 全 404 ⇒ 白屏、
    ``Failed to fetch dynamically imported module``、App 崩溃后画布进程退出。
    这里额外校验 index.html 里引用的本地入口脚本真实存在。
    """
    d = Path(dist) if dist is not None else vendor_dist_dir()
    index = d / "index.html"
    if not index.is_file():
        return f"{index} 不存在"
    try:
        html = index.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"{index} 无法读取: {e}"
    for src in _ENTRY_SRC_RE.findall(html):
        if src.startswith(("http://", "https://", "//", "data:")):
            continue  # 外链（如 inject.js 由 bridge 服务提供）不校验
        rel = src[2:] if src.startswith("./") else src.lstrip("/")
        rel = rel.split("?", 1)[0].split("#", 1)[0]
        if not rel:
            continue
        if not (d / rel).is_file():
            return f"index.html 引用的入口脚本缺失: {rel}"
    return None


def vendor_tauri_dir() -> Path:
    """AI-Canvas-tauri 项目根目录（engine=tauri 时使用）。"""
    return project_root() / "vendor" / "AI-Canvas-tauri"


def vendor_tauri_src_dir() -> Path:
    """AI-Canvas-tauri 前端 src 目录。"""
    return vendor_tauri_dir() / "src"


def vendor_tauri_src_tauri_dir() -> Path:
    """AI-Canvas-tauri Rust 后端 src-tauri 目录。"""
    return vendor_tauri_dir() / "src-tauri"


def _tauri_binary_path() -> Optional[Path]:
    """定位 Tauri 应用可执行文件：优先环境变量 SHIGUANG_TAURI_BIN，
    其次开发期 cargo dev 构建产物，最后打包期 _MEIPASS 同级目录。"""
    # 1) 环境变量显式指定（最高优先级）
    env_bin = os.environ.get("SHIGUANG_TAURI_BIN")
    if env_bin:
        p = Path(env_bin)
        if p.is_file():
            return p
    # 2) PyInstaller 打包后：_MEIPASS 同级 AI-Canvas.exe
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "AI-Canvas.exe"
        if candidate.is_file():
            return candidate
    # 3) 开发期：未构建二进制，返回 None（由 _start_tauri_process 走 cargo run / tauri dev）
    return None


def _tauri_dev_command() -> list[str]:
    """开发期拉起 Tauri 应用：优先 npm run tauri dev，
    回退 cargo run（需 src-tauri 已构建过）"""
    tauri_dir = vendor_tauri_dir()
    npm = shutil_which("npm")
    if npm and (tauri_dir / "package.json").is_file():
        return [npm, "run", "tauri", "dev"]
    # 回退 cargo（要求用户已装 Rust 工具链）
    cargo = shutil_which("cargo")
    if cargo:
        return [cargo, "run", "--manifest-path",
                str(tauri_dir / "src-tauri" / "Cargo.toml")]
    return []


def canvas_url(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}"


def port_open(host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_probe(url: str, timeout: float = 1.5) -> bool:
    """无代理 GET 探测，验证 URL 真的返回画布页面。

    仅用 ``port_open`` 做 TCP 探活会误判「半死监听」——进程 socket 还在 LISTEN
    却不 accept（backlog 满后 RST / 502），导致新实例复用死监听而白屏。
    这里走系统代理绕过（``ProxyHandler({})``）再校验响应体含画布挂载点，
    避开本机代理软件对 localhost 的干扰。
    """
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={"User-Agent": "shiguang-probe"})
        with opener.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = resp.read(4096).decode("utf-8", "replace")
            return 'id="root"' in body or "拾光导演台" in body
    except Exception:
        return False


class _SPAHandler(SimpleHTTPRequestHandler):
    """SPA：页面路由回退 index.html；静态资源缺失必须真 404。

    🔴 定案 2026-10-25：**带扩展名的资源路径不做 SPA 兜底**。
    之前所有缺失路径一律改写成 ``/index.html``，于是前端拿到 **200 + HTML**：
    ``import('./ImageStudio-xxx.js')`` 报 ``Unexpected token '<'``、CSS 被当样式表
    解析失败、GLB 解析成乱码——真实原因（dist 产物缺失/不一致）被完全掩盖，
    表现为「插件坏了」「模型加载失败」等一堆假故障。
    现在资源缺失返回 404 + text/plain 说明，产物问题一眼可见。
    """

    # 代表「真实文件」的扩展名：缺失 = 产物缺失，只能 404，不能兜底成 HTML
    _ASSET_SUFFIXES = (
        ".js", ".mjs", ".cjs", ".css", ".json", ".map", ".wasm",
        ".glb", ".gltf", ".bin", ".hdr", ".exr", ".ktx2", ".drc",
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".bmp",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp4", ".webm", ".mp3", ".wav", ".ogg",
        ".txt", ".xml", ".csv",
    )

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
        # index.html 必须每次校验；模型/提示词静态资源可长缓存，加速二次进 3D
        path = (self.path or "").split("?", 1)[0]
        if path.endswith(".html") or path == "/" or path.endswith("/"):
            self.send_header("Cache-Control", "no-cache")
        elif "/models/" in path or path.endswith(".glb") or path.endswith(".gltf"):
            # 带 ?v= 查询串换模型；无查询串时也不用 immutable，避免换文件后 WebView 死守旧 GLB
            self.send_header("Cache-Control", "public, max-age=86400")
        elif path.startswith("/prompts/") or "/prompts/" in path:
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        super().end_headers()

    def _is_asset_path(self, path: str) -> bool:
        return path.lower().endswith(self._ASSET_SUFFIXES)

    def _send_plain(self, code: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except OSError:
                logger.debug("canvas-static write failed", exc_info=True)

    def do_GET(self):  # noqa: N802
        # 去掉 query
        path = self.path.split("?", 1)[0]
        local = self.translate_path(path)
        if path != "/" and not os.path.isfile(local) and not os.path.isdir(local):
            if self._is_asset_path(path):
                # 资源缺失：真 404，禁止返回 HTML（否则前端报 Unexpected token '<'）
                # favicon 是浏览器自动请求的、不属于构建产物，降为 debug 免刷告警
                if path.endswith("/favicon.ico"):
                    logger.debug("canvas favicon missing: %s", path)
                else:
                    logger.warning("canvas asset missing: %s (dist=%s)", path, self.directory)
                self._send_plain(
                    404,
                    f"canvas asset missing: {path}\n"
                    "画布静态产物与当前页面不一致（dist 可能被移动、重建或清理过）。\n"
                    "修复：cd vendor/shiguang-canvas && npm run build，然后刷新画布。\n",
                )
                return
            if not os.path.isfile(os.path.join(self.directory, "index.html")):
                # 连 index.html 都没有 = dist 被整个移走
                logger.error("canvas dist missing: %s", self.directory)
                self._send_plain(
                    503,
                    "画布构建产物缺失（dist/index.html 不存在）。\n"
                    "修复：cd vendor/shiguang-canvas && npm run build，然后重新点「启动画布」。\n",
                )
                return
            self.path = "/index.html"
        return super().do_GET()


class CanvasRuntime:
    """管理画布本机服务。

    引擎选择：
    - ``shiguang``（默认）：自研 shiguang-canvas，Python ThreadingHTTPServer 静态服务
                          或 vite dev，由 Qt WebEngine 嵌入加载
    - ``tauri``            ：AI-Canvas-tauri 独立桌面进程，Qt 主程序不嵌入 WebEngine

    Tauri 模式下 token 通过环境变量 ``SHIGUANG_BRIDGE_TOKEN`` 传给子进程，
    URL 通过 ``SHIGUANG_BRIDGE_URL`` 传给子进程（默认 http://127.0.0.1:18765）。
    """

    def __init__(
        self,
        port: Optional[int] = None,
        static_port: Optional[int] = None,
    ):
        eng = active_canvas_engine()
        if port is None:
            # tauri 模式端口切换为 Tauri dev 端口；其余模式保持 shiguang 默认
            port = TAURI_VITE_PORT if eng == "tauri" else SHIGUANG_PORT
        if static_port is None:
            static_port = SHIGUANG_STATIC_PORT
        self.engine = eng
        self.port = port
        self.static_port = static_port
        self._proc: Optional[subprocess.Popen] = None
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._mode: str = ""  # static | vite | external | tauri-binary | tauri-dev
        self._dist_problem: Optional[str] = None  # dist 完整性问题的最近一次原因
        self._active_port: int = port
        # bridge token / URL：engine=tauri 时通过环境变量注入子进程；
        # engine=shiguang 时不使用，保持原 inject.js 注入路径
        self._bridge_token: str = ""
        self._bridge_url: str = TAURI_BRIDGE_URL_DEFAULT

    def set_bridge_credentials(self, token: str, url: str = TAURI_BRIDGE_URL_DEFAULT) -> None:
        """注入 Python 后端 session token 和 URL，engine=tauri 时用于子进程环境变量。

        engine=shiguang 模式下此方法不影响原 inject.js 注入流程，仅记录以备切换。
        """
        self._bridge_token = token or ""
        self._bridge_url = url or TAURI_BRIDGE_URL_DEFAULT

    @property
    def url(self) -> str:
        return canvas_url(self._active_port)

    def is_ready(self) -> bool:
        # engine=tauri 模式：进程存活即视为就绪，端口探活仅作辅助
        # （Tauri 应用是桌面 GUI，不强制监听本机端口）
        if self.engine == "tauri":
            if self._proc and self._proc.poll() is None:
                return True
            # 进程未存活但端口探活通过（外部已起 Tauri 应用）
            if port_open(port=TAURI_VITE_PORT):
                self._active_port = TAURI_VITE_PORT
                self._mode = "external"
                return True
            return False
        # 自己起的 static 服务：dist 可能在运行期被重建/搬走（产物换代）。
        # 只探 HTTP 会误判「就绪」——index.html 还在但 assets 已换名，页面必白屏，
        # 且 App 里动态 import 失败会把整个画布炸掉（2026-10-25 实证）。
        if self._httpd is not None:
            problem = dist_integrity_problem()
            if problem is not None:
                self._dist_problem = problem
                logger.warning("canvas static 服务仍在，但 dist 已损坏: %s", problem)
                return False
        if self._port_serves_canvas(self._active_port):
            return True
        # 外部可能已在 3000 起了 dev
        if self._active_port != self.port and self._port_serves_canvas(self.port):
            self._active_port = self.port
            self._mode = "external"
            return True
        if self._port_serves_canvas(self.port):
            self._active_port = self.port
            self._mode = "external"
            return True
        return False

    def _port_serves_canvas(self, port: int) -> bool:
        """端口在听且 HTTP 健康（真返回画布页面）。仅 TCP 探活会误判半死监听。"""
        if not port_open(port=port):
            return False
        return http_probe(f"http://127.0.0.1:{port}/")

    def _start_tauri_process(self) -> tuple[bool, str]:
        """拉起 AI-Canvas-tauri 应用进程（engine=tauri 专用）。

        优先使用已构建的可执行二进制（SHIGUANG_TAURI_BIN 环境变量或 _MEIPASS 同级）；
        回退到 npm run tauri dev / cargo run 开发模式。

        通过环境变量 SHIGUANG_BRIDGE_TOKEN / SHIGUANG_BRIDGE_URL 注入 Python 后端凭据，
        Tauri 应用前端通过 Rust command get_bridge_token/get_bridge_url 读取。
        """
        # 已有进程在跑，直接复用
        if self._proc and self._proc.poll() is None:
            self._mode = "tauri-binary" if self._mode.startswith("tauri") else self._mode
            return True, f"Tauri 应用已在运行（pid={self._proc.pid}）"

        # 构造子进程环境变量（继承当前进程 + 注入 bridge 凭据）
        env = os.environ.copy()
        if self._bridge_token:
            env["SHIGUANG_BRIDGE_TOKEN"] = self._bridge_token
        if self._bridge_url:
            env["SHIGUANG_BRIDGE_URL"] = self._bridge_url

        creationflags = 0
        if sys.platform == "win32":
            # Windows 下独立窗口，不阻塞 Qt 主控制台
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        # 1) 优先调用已构建二进制
        binary = _tauri_binary_path()
        if binary is not None:
            try:
                self._proc = subprocess.Popen(
                    [str(binary)],
                    cwd=str(vendor_tauri_dir()),
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                self._mode = "tauri-binary"
                logger.info("tauri binary started pid=%s bin=%s", self._proc.pid, binary)
                return True, f"Tauri 应用已启动（pid={self._proc.pid}）"
            except OSError as e:
                logger.warning("tauri binary start failed: %s", e)
            except Exception as e:
                return False, f"启动 Tauri 二进制失败: {e}"

        # 2) 开发期：npm run tauri dev 或 cargo run
        cmd = _tauri_dev_command()
        if not cmd:
            return False, (
                "未找到 Tauri 应用可执行文件，也未找到 npm/cargo。"
                "请先构建：cd vendor/AI-Canvas-tauri && npm run tauri build，"
                "或安装 Node.js / Rust 工具链。"
            )

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(vendor_tauri_dir()),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self._mode = "tauri-dev"
            logger.info("tauri dev started pid=%s cmd=%s", self._proc.pid, cmd)
            return True, f"Tauri 应用正在启动（pid={self._proc.pid}，开发模式）"
        except OSError as e:
            return False, f"启动 Tauri 开发模式失败: {e}"
        except Exception as e:
            return False, f"启动 Tauri 开发模式异常: {e}"

    def _stop_static(self) -> None:
        """只停静态服务（不动 vite 子进程）。

        ``shutdown()`` 之后必须 ``server_close()`` 才真正释放监听端口，
        否则 DIST 换代后重建会撞「端口被占用」。
        """
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
        except Exception:
            logger.debug("static shutdown failed", exc_info=True)
        try:
            self._httpd.server_close()
        except Exception:
            logger.debug("static server_close failed", exc_info=True)
        self._httpd = None
        self._http_thread = None

    def _start_static_server(self) -> tuple[bool, str]:
        dist = vendor_dist_dir()
        self._dist_problem = dist_integrity_problem(dist)
        if self._dist_problem is not None:
            # dist 坏了而旧静态服务还在跑：必须关掉。否则它一直对着已失效的目录
            # 服务（页面能返回、chunk 全 404），且端口被占，无法重建（2026-10-25）。
            if self._httpd is not None:
                logger.warning("dist 已损坏，关闭旧静态服务以便重建: %s", self._dist_problem)
                self._stop_static()
            return False, f"无 dist（{self._dist_problem}）"
        if self._httpd is not None:
            self._active_port = self.static_port
            self._mode = "static"
            return True, f"画布静态服务已在运行: {self.url}"

        # 端口占用则换用已有服务——但仅当 HTTP 健康；半死监听不复用（否则白屏）
        if port_open(port=self.static_port):
            if http_probe(f"http://127.0.0.1:{self.static_port}/"):
                self._active_port = self.static_port
                self._mode = "static"
                return True, f"画布已在运行: {self.url}"
            logger.warning(
                "static port %s occupied but not serving canvas (半死监听，不复用)",
                self.static_port,
            )

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
            return False, (
                f"画布端口 {self.static_port} 被占用但服务不健康。\n"
                f"可能有残留的旧编辑器进程占着端口，请关闭后重试，或点「刷新」。\n"
                f"（{e}）"
            )
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
        """若未监听则启动。

        engine=tauri：拉起 Tauri 桌面进程（不嵌入 WebEngine）。
        engine=shiguang：优先 dist 静态服务 → vite dev，由 Qt WebEngine 加载。
        """
        def progress(msg: str) -> None:
            if on_progress:
                try:
                    on_progress(msg)
                except Exception:
                    pass

        # §12-P2 启动打点：boot 分段计时起点（进程起 → 静态服务/vite → 就绪）
        _t_boot = time.monotonic()
        if self.is_ready():
            logger.info("canvas boot timing: already running (%.2fs)",
                        time.monotonic() - _t_boot)
            return True, f"画布已在运行: {self.url}"

        eng = active_canvas_engine()

        # ── engine=tauri：拉起 AI-Canvas-tauri 桌面进程 ──
        if eng == "tauri":
            tauri_dir = vendor_tauri_dir()
            if not (tauri_dir / "package.json").is_file() and _tauri_binary_path() is None:
                return False, (
                    f"未找到 Tauri 应用（期望 {tauri_dir}）。"
                    "请确认 vendor/AI-Canvas-tauri 存在，"
                    "并执行 cd vendor/AI-Canvas-tauri && npm install && npm run tauri build"
                )
            progress("正在启动 Tauri 桌面应用…")
            ok, msg = self._start_tauri_process()
            if not ok:
                return False, msg
            # Tauri 应用是桌面 GUI，启动后立即返回成功（不像 vite 需要等端口探活）
            return True, msg

        # ── engine=shiguang：原 WebEngine + 静态/vite 路径（不动） ──
        web = vendor_web_dir()

        # 1) 静态 dist（最快）。发布包只携带 dist/public，没有源码 package.json；
        #    因而必须先尝试完整静态产物，不能用源码包清单提前拦截冻结版。
        progress(f"正在秒开画布（引擎={eng}）…")
        ok, msg = self._start_static_server()
        if ok and self.is_ready():
            logger.info("canvas boot timing: static ready %.2fs",
                        time.monotonic() - _t_boot)
            return True, msg

        # 2) 无可用 dist 时才需要源码包与 vite。
        if not (web / "package.json").is_file():
            return False, (
                f"未找到自研画布（期望 {web}）。\n"
                "请确认 vendor/shiguang-canvas 存在，并执行:\n"
                "  cd vendor/shiguang-canvas && npm install && npm run build"
            )

        # 无 dist：提示并拉 vite（可随后后台 build）
        #    把 dist 缺失的具体原因带进报错：只说「画布进程已退出」会把
        #    「产物被搬走」误诊成「Node/npm 装坏了」（2026-10-25 实际翻车）。
        dist_note = f"\n（dist 状态：{self._dist_problem}）" if self._dist_problem else ""
        node_modules = web / "node_modules"
        if not node_modules.is_dir():
            hint = "cd vendor/shiguang-canvas && npm install && npm run build"
            return False, f"画布依赖未安装。请先运行:\n  {hint}{dist_note}"

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
                logger.info("canvas boot timing: vite ready %.2fs",
                            time.monotonic() - _t_boot)
                self._kick_background_build()
                return True, f"画布已启动: {self.url}"
            if self._proc and self._proc.poll() is not None:
                return False, (
                    "画布进程已退出，请检查 Node/npm 与 vendor 依赖"
                    f"{dist_note}"
                )
            now = time.time()
            if now - last_tick >= 2.0:
                left = int(deadline - now)
                progress(f"正在等待 Vite 就绪…（剩余约 {left}s）")
                last_tick = now
            time.sleep(0.25)
        build_hint = "cd vendor/shiguang-canvas && npm run build"
        return False, (
            f"等待画布超时（{self.url}）。\n"
            f"可手动: {build_hint}\n"
            "然后重新点「启动画布」走静态秒开。"
        )

    def _kick_background_build(self) -> None:
        """后台 build dist，下次启动秒开。

        触发条件用 ``dist_integrity_problem`` 而非「index.html 是否存在」：
        入口脚本缺失时 index.html 仍在，单看它会永远跳过重建 ⇒ dist 一直坏着。
        """
        if dist_integrity_problem() is None:
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
                problem = dist_integrity_problem()
                logger.info(
                    "background vite build done: %s",
                    "ok" if problem is None else f"still broken - {problem}",
                )
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

    def mark_tauri_closed(self) -> None:
        """Tauri 桌面窗口关闭时由 /host/tauri-closing 调用，清理进程引用。

        仅在 engine=tauri 模式下生效；不主动 kill 子进程（用户已关闭窗口），
        仅清空 self._proc 让下次 ensure_started 重新拉起。
        """
        if getattr(self, "engine", "") != "tauri":
            return
        try:
            if self._proc is not None:
                # 已退出进程 poll() 返回码；仍在运行的话不强制 kill（用户主动关闭）
                if self._proc.poll() is not None:
                    self._proc = None
                    self._mode = ""
                    logger.info("tauri process closed and reference cleared")
        except Exception as exc:
            logger.debug("mark_tauri_closed exception: %s", exc)

    def stop(self) -> None:
        self._stop_static()
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
