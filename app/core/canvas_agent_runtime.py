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


def _canvas_agent_lockfile() -> Path:
    """上游 canvas-agent 会写 ~/.infinite-canvas/canvas-agent.json，EPERM 时可删。"""
    return Path.home() / ".infinite-canvas" / "canvas-agent.json"


def _try_clear_upstream_lockfile() -> Optional[str]:
    """尝试删除上游 canvas-agent 的锁文件，返回清理信息（失败返回 None）。"""
    lock = _canvas_agent_lockfile()
    if not lock.is_file():
        return None
    try:
        lock.unlink()
        logger.info("已清理上游 canvas-agent 锁文件: %s", lock)
        return f"已清理锁文件 {lock.name}"
    except Exception as e:
        logger.warning("清理锁文件失败（可忽略）: %s", e)
        return None


def _kill_stale_agent_processes() -> int:
    """杀掉所有残留的 @basketikun/canvas-agent node 进程。

    自研画布根本不依赖这个外部 Node agent（它只是 Codex/MCP 工具通道的备用），
    所以残留进程必须清干净，否则新起的 canvas-agent 会因为锁文件 EPERM 崩。
    返回杀掉的进程数。
    """
    import signal

    killed = 0
    try:
        from pathlib import Path as _P
    except Exception:
        return 0
    try:
        import psutil
    except Exception:
        psutil = None

    if psutil is not None:
        for proc in psutil.process_iter(["pid", "cmdline", "name"]):
            try:
                cmd = proc.info.get("cmdline") or []
                name = (proc.info.get("name") or "").lower()
                cmdline_str = " ".join(cmd).lower() if cmd else ""
                is_agent = (
                    "canvas-agent" in cmdline_str
                    or ("node" in name and "basketikun" in cmdline_str)
                )
                if is_agent:
                    proc.terminate()
                    killed += 1
                    logger.info("已终止残留 canvas-agent 进程 pid=%s", proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if killed:
            time.sleep(0.4)
            for proc in psutil.process_iter(["pid", "cmdline", "name"]):
                try:
                    cmd = proc.info.get("cmdline") or []
                    cmdline_str = " ".join(cmd).lower() if cmd else ""
                    if "canvas-agent" in cmdline_str:
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        return killed

    # fallback: 用 taskkill
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "node.exe", "/FI", "WINDOWTITLE eq canvas-agent*"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            killed = 1
    except Exception:
        logger.debug("忽略异常（原为 pass）: canvas_agent_runtime.py", exc_info=True)
    return killed


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

    def _start_raw_process(self, progress: Callable[[str], None]) -> subprocess.Popen:
        """拉起 canvas-agent 子进程（底层）。"""
        npx = _which("npx")
        if not npx:
            raise RuntimeError("未找到 npx。请安装 Node.js 后重试。")

        progress("正在启动 canvas-agent…")
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            return subprocess.Popen(
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
            raise RuntimeError(f"启动 canvas-agent 失败: {e}") from e

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
                    logger.debug("忽略异常（原为 pass）: canvas_agent_runtime.py", exc_info=True)

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
                    "请关闭旧 canvas-agent 后重试。",
                )

            return self._do_start(wait_seconds, progress)

    def _do_start(
        self,
        wait_seconds: float,
        progress: Callable[[str], None],
    ) -> Tuple[bool, str]:
        """实际拉起 + 等待 token。自动清理残留进程 + 锁文件，EPERM 时重试一次。"""
        # 1. 先杀所有残留的 canvas-agent node 进程（它会占锁文件/端口）
        killed = _kill_stale_agent_processes()
        if killed:
            logger.info("已清理 %d 个残留 canvas-agent 进程", killed)
            time.sleep(0.3)
        # 2. 再清锁文件（如果上次崩了留下）
        _try_clear_upstream_lockfile()

        try:
            self._proc = self._start_raw_process(progress)
        except RuntimeError as e:
            return False, str(e)

        url_found = ""
        token_found = ""
        deadline = time.time() + max(8.0, wait_seconds)
        last_tick = 0.0
        buf_lines: list[str] = []

        assert self._proc.stdout is not None
        while time.time() < deadline:
            if self._proc.poll() is not None and not self.is_listening():
                # 子进程退出了——读一下完整输出看是否 EPERM
                tail = "\n".join(buf_lines[-12:])
                remaining = self._proc.stdout.read() or ""
                if remaining:
                    tail = (tail + "\n" + remaining).strip()
                logger.warning("canvas-agent exited early: %s", tail[:300])
                # EPERM 自动清理 + 重试一次
                if "EPERM" in tail or "EACCES" in tail or "open'" in tail:
                    _kill_stale_agent_processes()
                    cleared = _try_clear_upstream_lockfile()
                    if cleared:
                        progress(f"检测到锁文件冲突，{cleared}，重试中…")
                        return self._do_start_no_retry(wait_seconds, progress)
                    # 重试也清不掉——放弃，返回友好提示
                    logger.warning("canvas-agent EPERM 锁文件无法清理，放弃重试")
                return (
                    False,
                    "canvas-agent 启动失败（可忽略）。\n"
                    "自研画布已内置 Agent，这个外部通道仅在需要 MCP 工具时才用。\n"
                    f"详情: {tail[:200]}",
                )

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
                        logger.debug("忽略异常（原为 pass）: canvas_agent_runtime.py", exc_info=True)
                    self._save_session()
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
                            logger.debug("忽略异常（原为 pass）: canvas_agent_runtime.py", exc_info=True)
                        self._save_session()
                        return True, f"Agent 已连接就绪: {self.url}"
            time.sleep(0.25)

        self._load_session()
        if self.is_listening() and self.token:
            return True, f"Agent 已在运行: {self.url}"
        if self.is_listening():
            return (
                False,
                "Agent 端口已开但未拿到 Connect token。\n"
                "可重启 canvas-agent 或清空 ~/.infinite-canvas/canvas-agent.json 后重试。",
            )
        return (
            False,
            "等待 canvas-agent 超时。\n"
            "可手动: npx -y @basketikun/canvas-agent\n"
            "或忽略：自研画布已内置 Agent，不需要这个外部通道。",
        )

    def _do_start_no_retry(
        self,
        wait_seconds: float,
        progress: Callable[[str], None],
    ) -> Tuple[bool, str]:
        """_do_start 的非重试分支（避免无限递归）。"""
        return self._do_start(wait_seconds, progress)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                logger.debug("忽略异常（原为 pass）: canvas_agent_runtime.py", exc_info=True)
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
                    logger.debug("忽略异常（原为 pass）: canvas_agent_runtime.py", exc_info=True)

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
