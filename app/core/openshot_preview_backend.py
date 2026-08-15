"""OpenShot Preview Backend — 通过子进程 bridge 提供视频帧解码。

与 PreviewManager 的 OpenCV+QLabel 后端并行存在，通过 backend 切换开关启用。
bridge 进程（MSYS2 Python 3.14 + libopenshot）长驻，二进制 JSON line 协议通信。
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtGui import QImage
from PyQt6.QtCore import QObject, pyqtSignal

try:
    from loguru import logger
except ImportError:
    import logging as logger


_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent.parent  # .../app/core -> app -> project root
BRIDGE_PYTHON = r"C:/msys64/ucrt64/bin/python.exe"
BRIDGE_SCRIPT = str(_PROJECT_ROOT / "scripts" / "openshot_bridge.py")
REQUEST_TIMEOUT_SEC = 10
BRIDGE_PING_INTERVAL = 30


class OpenShotPreviewBackend(QObject):
    """通过 OpenShot FFmpegReader bridge 解码视频帧。

    长驻子进程 + 二进制 JSON line 协议。崩溃自动重启，超时回退 None。
    """

    frame_decoded = pyqtSignal(int, int, int, str)  # frame_num, w, h, jpg_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._video_info: Dict[str, Any] = {}
        self._open = False
        self._bridge_python = BRIDGE_PYTHON
        self._bridge_script = BRIDGE_SCRIPT

    @classmethod
    def is_available(cls) -> bool:
        """检查 bridge 运行时是否可用（不真正启动进程）。"""
        return os.path.isfile(BRIDGE_PYTHON) and os.path.isfile(BRIDGE_SCRIPT)

    # ---- 进程管理 ----

    def _ensure_proc(self):
        """确保 bridge 进程存活，否则重启。"""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True
            if not self.is_available():
                logger.warning("[OpenShotBackend] bridge runtime 不可用")
                return False
            try:
                self._proc = subprocess.Popen(
                    [self._bridge_python, self._bridge_script],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                hello = self._read_response()
                if hello and hello.get("hello"):
                    logger.info(f"[OpenShotBackend] bridge 启动 OK, pid={self._proc.pid}, "
                                f"openshot={hello.get('openshot_version')}")
                    return True
                logger.error(f"[OpenShotBackend] bridge hello 失败: {hello}")
                self._kill()
                return False
            except Exception as e:
                logger.error(f"[OpenShotBackend] 启动 bridge 失败: {e}")
                self._proc = None
                return False

    def _kill(self):
        with self._lock:
            if self._proc is not None:
                try:
                    if self._proc.poll() is None:
                        self._proc.stdin.write(b'{"cmd":"quit"}\n')
                        self._proc.stdin.flush()
                        try:
                            self._proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            self._proc.kill()
                            self._proc.wait(timeout=1)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None
        self._open = False
        self._video_info = {}

    # ---- 协议通信 ----

    def _send(self, msg: dict) -> Optional[dict]:
        """发一个 JSON line 命令，读一个响应。失败返回 None。"""
        if not self._ensure_proc():
            return None
        try:
            line = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
            return self._read_response()
        except Exception as e:
            logger.error(f"[OpenShotBackend] send failed: {e}")
            self._kill()
            return None

    def _read_response(self) -> Optional[dict]:
        """读一行 JSON 响应，带超时。"""
        if self._proc is None:
            return None
        start = time.monotonic()
        buf = bytearray()
        while time.monotonic() - start < REQUEST_TIMEOUT_SEC:
            try:
                ch = self._proc.stdout.read(1)
            except Exception:
                return None
            if not ch:
                if self._proc.poll() is not None:
                    logger.error(f"[OpenShotBackend] bridge died, rc={self._proc.returncode}")
                    return None
                continue
            if ch == b"\n":
                break
            buf += ch
        else:
            logger.error("[OpenShotBackend] read timeout")
            return None
        try:
            return json.loads(buf.decode("utf-8"))
        except Exception as e:
            logger.error(f"[OpenShotBackend] JSON decode failed: {e}, raw={buf[:80]!r}")
            return None

    # ---- 公共 API ----

    def open_video(self, path: str) -> bool:
        if not self._ensure_proc():
            return False
        resp = self._send({"cmd": "open", "path": path})
        if resp and resp.get("ok"):
            self._open = True
            self._video_info = resp.get("info", {})
            logger.info(f"[OpenShotBackend] opened {path}, info={self._video_info}")
            return True
        logger.error(f"[OpenShotBackend] open failed: {resp}")
        self._open = False
        self._video_info = {}
        return False

    def close_video(self):
        if self._open:
            self._send({"cmd": "close"})
        self._open = False
        self._video_info = {}

    def get_video_info(self) -> dict:
        return dict(self._video_info)

    def read_frame(self, frame_num: int, scale: float = 1.0,
                   fmt: str = "JPEG", quality: int = 85) -> Optional[QImage]:
        """解码指定帧，返回 QImage。失败返回 None。"""
        if not self._open:
            return None
        resp = self._send({
            "cmd": "read_frame",
            "frame_num": int(frame_num),
            "scale": float(scale),
            "fmt": fmt,
            "quality": quality,
        })
        if not resp or not resp.get("ok"):
            if resp:
                logger.warning(f"[OpenShotBackend] read_frame failed: {resp.get('error')}")
            return None
        fpath = resp.get("path")
        if not fpath or not os.path.isfile(fpath):
            return None
        img = QImage(fpath)
        if img.isNull():
            logger.warning(f"[OpenShotBackend] QImage load failed: {fpath}")
            return None
        return img

    def ping(self) -> bool:
        resp = self._send({"cmd": "ping"})
        return bool(resp and resp.get("ok"))

    def shutdown(self):
        self._kill()
