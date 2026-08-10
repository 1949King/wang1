# -*- coding: utf-8 -*-
"""启动 / 探测 infinite-canvas 前端（vendor 或外部 URL）。"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("AI短剧编辑器.canvas_runtime")

DEFAULT_PORT = 3000


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def vendor_canvas_dir() -> Path:
    return project_root() / "vendor" / "infinite-canvas"


def vendor_web_dir() -> Path:
    return vendor_canvas_dir() / "web"


def canvas_url(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}"


def port_open(host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class CanvasRuntime:
    """管理 infinite-canvas 的本机进程（npm run dev）。"""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self._proc: Optional[subprocess.Popen] = None

    @property
    def url(self) -> str:
        return canvas_url(self.port)

    def is_ready(self) -> bool:
        return port_open(port=self.port)

    def ensure_started(self, wait_seconds: float = 45.0) -> tuple[bool, str]:
        """若未监听则尝试启动 vendor/web 的 vite。返回 (ok, message)。"""
        if self.is_ready():
            return True, f"画布已在运行: {self.url}"

        web = vendor_web_dir()
        if not (web / "package.json").is_file():
            return False, (
                f"未找到 vendor/infinite-canvas（期望 {web}）。\n"
                "请运行: scripts/setup_infinite_canvas.ps1"
            )

        node_modules = web / "node_modules"
        if not node_modules.is_dir():
            return False, (
                "画布依赖未安装。请先运行:\n"
                "  scripts/setup_infinite_canvas.ps1\n"
                "或: cd vendor/infinite-canvas/web && npm install"
            )

        if self._proc and self._proc.poll() is None:
            # 正在启动
            pass
        else:
            npm = shutil_which("npm")
            if not npm:
                return False, "未找到 npm。请安装 Node.js 后重试。"
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self._proc = subprocess.Popen(
                    [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(self.port)],
                    cwd=str(web),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                logger.info("started infinite-canvas pid=%s", self._proc.pid)
            except Exception as e:
                return False, f"启动画布失败: {e}"

        deadline = time.time() + max(5.0, wait_seconds)
        while time.time() < deadline:
            if self.is_ready():
                return True, f"画布已启动: {self.url}"
            if self._proc and self._proc.poll() is not None:
                return False, "画布进程已退出，请检查 Node/npm 与 vendor 依赖"
            time.sleep(0.5)
        return False, f"等待画布超时（{self.url}）。可手动: cd vendor/infinite-canvas/web && npm run dev"

    def stop(self) -> None:
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
