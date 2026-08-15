# -*- coding: utf-8 -*-
"""拉起 / 探测外部 Node canvas-agent（:17371，@basketikun/canvas-agent）。

⚠️ 本模块管的是**外部 Node MCP 子进程**（供 Codex/MCP agent 调画布工具），
不是自研 shiguang-canvas 的后端适配层。
自研画布 Agent 请看 ``project_agent_host.py``；画布前端 HTTP 服务请看 ``canvas_runtime.py``。

三模块对照：
- ``canvas_runtime.py``          → 画布前端 HTTP 服务（Python HTTP / vite，端口 3010）
- ``canvas_agent_runtime.py``    → **本文件**：外部 Node MCP agent（端口 17371）
- ``project_agent_host.py``      → 自研画布 ↔ 剪辑 Agent 的 Python 适配层（SSE + chat）

解析 stdout 中的 Local URL / Connect token，落盘会话，供 WebView 自动连接。
仍被「连接 Agent」按钮（character_management_module）使用，保留以兼容旧路径。
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.canvas_agent_runtime")

DEFAULT_PORT = 17371
URL_RE = re.compile(r"Local\s+URL:\s*(https?://\S+)", re.I)
TOKEN_RE = re.compile(r"Connect\s+token:\s*(\S+)", re.I)


def session_path() -> Path:
    root = Path.home() / ".video_editor_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root / "canvas_agent_session.json"


def port_open(host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)


class CanvasAgentRuntime:
    """管理 @basketikun/canvas-agent 子进程。"""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.token = ""
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._load_session()

    def _load_session(self) -> None:
        path = session_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.url = str(data.get("url") or self.url).rstrip("/")
            self.token = str(data.get("token") or "")
            if data.get("port"):
                self.port = int(data["port"])
        except Exception as e:
            logger.debug("load agent session failed: %s", e)

    def _save_session(self) -> None:
        try:
            session_path().write_text(
                json.dumps(
                    {
                        "url": self.url,
                        "token": self.token,
                        "port": self.port,
                        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("save agent session failed: %s", e)

    def is_listening(self) -> bool:
        return port_open(port=self.port)

    def ensure_started(
        self,
        wait_seconds: float = 45.0,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str]:
        def progress(msg: str) -> None:
            if on_progress:
                try:
                    on_progress(msg)
                except Exception:
                    pass

        with self._lock:
            if self.is_listening() and self.token:
                return True, f"Agent 已在运行: {self.url}"

            if self.is_listening() and not self.token:
                # 端口在听但本进程无 token：尝试用落盘会话
                self._load_session()
                if self.token:
                    return True, f"Agent 已在运行（复用会话）: {self.url}"
                return (
                    False,
                    "检测到 :17371 已占用，但无 Connect token。\n"
                    "请关闭旧 canvas-agent，或清空 ~/.infinite-canvas/canvas-agent.json 后重试。",
                )

            npx = _which("npx")
            if not npx:
                return False, "未找到 npx。请安装 Node.js 后重试。"

            progress("正在启动 canvas-agent…")
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            try:
                self._proc = subprocess.Popen(
                    [npx, "-y", "@basketikun/canvas-agent"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=creationflags,
                    env={**os.environ, "PYTHONUTF8": "1"},
                )
            except Exception as e:
                return False, f"启动 canvas-agent 失败: {e}"

            url_found = ""
            token_found = ""
            deadline = time.time() + max(8.0, wait_seconds)
            last_tick = 0.0
            buf_lines: list[str] = []

            assert self._proc.stdout is not None
            while time.time() < deadline:
                if self._proc.poll() is not None and not self.is_listening():
                    tail = "\n".join(buf_lines[-12:])
                    return False, f"canvas-agent 已退出。\n{tail}"

                line = self._proc.stdout.readline()
                if line:
                    buf_lines.append(line.rstrip())
                    if len(buf_lines) > 80:
                        buf_lines = buf_lines[-40:]
                    m_url = URL_RE.search(line)
                    if m_url:
                        url_found = m_url.group(1).rstrip("/").rstrip()
                    m_tok = TOKEN_RE.search(line)
                    if m_tok:
                        token_found = m_tok.group(1).strip()
                    if url_found and token_found:
                        self.url = url_found
                        self.token = token_found
                        try:
                            from urllib.parse import urlparse

                            p = urlparse(url_found)
                            if p.port:
                                self.port = int(p.port)
                        except Exception:
                            pass
                        self._save_session()
                        # 再等端口就绪
                        for _ in range(40):
                            if self.is_listening():
                                break
                            time.sleep(0.15)
                        logger.info("canvas-agent ready url=%s", self.url)
                        return True, f"Agent 已连接就绪: {self.url}"

                now = time.time()
                if now - last_tick >= 2.0:
                    left = int(deadline - now)
                    progress(f"等待 canvas-agent 输出 token…（剩余约 {left}s）")
                    last_tick = now
                if not line:
                    time.sleep(0.05)

            # 超时前再读几行（Windows pipe 可能缓冲）
            progress("仍在等待 token，继续探测…")
            for _ in range(20):
                if self._proc and self._proc.stdout:
                    try:
                        line = self._proc.stdout.readline()
                    except Exception:
                        line = ""
                    if line:
                        mu = URL_RE.search(line)
                        mt = TOKEN_RE.search(line)
                        if mu:
                            url_found = mu.group(1).rstrip("/").rstrip()
                        if mt:
                            token_found = mt.group(1).strip()
                        if url_found and token_found:
                            self.url = url_found
                            self.token = token_found
                            try:
                                from urllib.parse import urlparse

                                p = urlparse(url_found)
                                if p.port:
                                    self.port = int(p.port)
                            except Exception:
                                pass
                            self._save_session()
                            return True, f"Agent 已连接就绪: {self.url}"
                time.sleep(0.25)

            # 超时：若已听端口且有落盘 token
            self._load_session()
            if self.is_listening() and self.token:
                return True, f"Agent 已在运行: {self.url}"
            if self.is_listening():
                return (
                    False,
                    "Agent 端口已开但未拿到 Connect token。\n"
                    "请点「连接 Agent」重试，或删除 ~/.infinite-canvas/canvas-agent.json 后重启。",
                )
            return (
                False,
                "等待 canvas-agent 超时。\n"
                "可手动: npx -y @basketikun/canvas-agent\n"
                "若 Origin 冲突，删除 ~/.infinite-canvas/canvas-agent.json 后重试。",
            )

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None

    def warmup_async(
        self,
        on_done: Optional[Callable[[bool, str], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> None:
        """后台预热 Agent，不阻塞 UI。"""

        def _run():
            ok, msg = self.ensure_started(wait_seconds=75.0, on_progress=on_progress)
            if on_done:
                try:
                    on_done(ok, msg)
                except Exception:
                    pass

        threading.Thread(target=_run, name="CanvasAgentWarmup", daemon=True).start()

    def credentials(self) -> Tuple[str, str]:
        """返回 (url, token)，必要时从会话文件刷新。"""
        if not self.token:
            self._load_session()
        return self.url, self.token


_agent_singleton: Optional[CanvasAgentRuntime] = None


def get_canvas_agent_runtime() -> CanvasAgentRuntime:
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = CanvasAgentRuntime()
    return _agent_singleton
