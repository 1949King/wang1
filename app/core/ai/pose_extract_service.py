"""
姿态解析调度服务（模式 B · PoseExtractService）
================================================
以独立子进程运行 pose_worker.py：视频 → BlazePose 关键点 JSON 落 canvas inbox。

架构位置：canvas_server(/host/pose-extract) → PoseExtractService → pose_worker 子进程

设计约束（docs/_archive/knowledge/17-motion-ref-design.md §六）：
  - 姿态推理放独立子进程，推理完立即退出释放显存，不与 AI 画布视频生成抢显存；
  - 依赖缺失 / 打包环境 / 超时 / 视频损坏 → 诚实失败（返回明确 message），不假成功；
  - 单例模式，线程锁保护子进程互斥（同时只跑一个推理任务）。
"""
from __future__ import annotations

import json
import logging
import os
import string
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("AI短剧编辑器.pose_extract")

# 子进程默认参数
_DEFAULT_TIMEOUT = 180.0
_DEFAULT_MAX_FRAMES = 300


def _is_ascii(path: str) -> bool:
    """路径是否纯 ASCII（mediapipe C++ 层仅保证 ASCII 路径可靠打开）。"""
    return all(ord(ch) < 128 for ch in path)


def _find_free_drive() -> str:
    """从 Z 往前找一个未被占用的盘符（subst 桥接用）。"""
    for letter in reversed(string.ascii_uppercase):
        drive = f"{letter}:"
        if not os.path.exists(drive + os.sep):
            return drive
    return ""


class _SubstBridge:
    """中文项目路径 → subst 虚拟盘符桥接（上下文管理器）。

    背景：mediapipe C++ 层以 ANSI/UTF-8 打开模型文件，中文安装路径（如 D:\\拾光剪影）
    直接 FileNotFoundError（与 MLT 中文路径已知坑同源）；且部分卷禁用 8.3 短名，
    GetShortPathName 无效。subst 一个纯 ASCII 盘符指向解释器所在的第一级目录，
    从该盘符运行子进程，使 site-packages 全链路 ASCII。
    subst 失败时静默退化为原始路径（推理会诚实失败并透出原始错误）。
    """

    def __init__(self):
        self._drive = ""
        self._target = ""

    def __enter__(self) -> "_SubstBridge":
        exe = sys.executable
        if sys.platform == "win32" and exe and not _is_ascii(exe):
            drive_part, rest = os.path.splitdrive(os.path.abspath(exe))
            segments = [s for s in rest.split(os.sep) if s]
            if drive_part and segments:
                target = drive_part + os.sep + segments[0]
                drive = _find_free_drive()
                if drive:
                    try:
                        result = subprocess.run(
                            ["subst", drive, target],
                            capture_output=True, text=True, timeout=10,
                            creationflags=PoseExtractService._no_window_flags(),
                        )
                        if result.returncode == 0 and os.path.isdir(drive + os.sep):
                            self._drive = drive
                            self._target = target
                            logger.debug("[pose-extract] subst 桥接: %s -> %s", drive, target)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        logger.debug("[pose-extract] subst 失败，退化为原始路径: %s", exc)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._drive:
            try:
                subprocess.run(
                    ["subst", self._drive, "/d"],
                    capture_output=True, timeout=10,
                    creationflags=PoseExtractService._no_window_flags(),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("[pose-extract] subst 卸载失败（盘符 %s 可能残留）: %s", self._drive, exc)
            self._drive = ""
            self._target = ""
        return False

    def remap(self, path: str) -> str:
        """把桥接目标目录之下的绝对路径改写为虚拟盘符形式；其余原样返回。"""
        if not self._drive or not path:
            return path
        ab = os.path.abspath(path)
        target = self._target.rstrip(os.sep) + os.sep
        if ab.startswith(target):
            return self._drive + os.sep + ab[len(target):]
        return path


def _find_worker_script() -> str:
    """定位 pose_worker.py：源码环境随模块同目录；打包环境查 sys._MEIPASS。"""
    candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "pose_worker.py")]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(os.path.join(meipass, "app", "core", "ai", "pose_worker.py"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


class PoseExtractService:
    """模式 B 姿态解析调度器（单例）。

    使用方式：
        from app.core.ai.pose_extract_service import pose_extract_service
        result = pose_extract_service.extract("D:/xxx/video.mp4")
    """

    _instance: Optional["PoseExtractService"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._backend_cache: Optional[Dict[str, Any]] = None
        # 子进程互斥锁：同一时刻只允许一个姿态推理任务占用 GPU
        self._run_lock = threading.Lock()

    # ═══════════════════════════════════════════════════════════
    # 公共接口
    # ═══════════════════════════════════════════════════════════

    def check_backend(self, force: bool = False) -> Dict[str, Any]:
        """探测姿态推理后端（子进程 import 检查）；结果缓存避免重复拉起进程。

        返回 {ok, backend, cv2, mediapipe, message, frozen}。
        """
        if self._backend_cache is not None and not force:
            return dict(self._backend_cache)

        worker = _find_worker_script()
        if not worker:
            result = {
                "ok": False, "backend": "", "cv2": False, "mediapipe": False,
                "frozen": bool(getattr(sys, "frozen", False)),
                "message": "pose_worker.py 未找到（安装不完整）",
            }
        elif getattr(sys, "frozen", False):
            # 打包环境：sys.executable 是应用 exe，无法直接执行 Python 脚本
            result = {
                "ok": False, "backend": "", "cv2": False, "mediapipe": False,
                "frozen": True,
                "message": "发布版内嵌环境暂不支持姿态解析；请在开发环境（安装 mediapipe 的 Python）运行",
            }
        else:
            with _SubstBridge() as bridge:
                result = self._run_worker(
                    [bridge.remap(sys.executable), worker, "--check"],
                    timeout=30.0,
                    purpose="backend-check",
                )
            if not isinstance(result, dict):
                result = {
                    "ok": False, "backend": "", "cv2": False, "mediapipe": False,
                    "frozen": False, "message": str(result),
                }
            result.setdefault("frozen", False)
        self._backend_cache = result
        return dict(result)

    def extract(
        self,
        video_path: str,
        *,
        sample_step: int = 1,
        max_frames: int = _DEFAULT_MAX_FRAMES,
        model_complexity: int = 1,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """调度子进程提取关键点；结果 JSON 落 canvas inbox 并返回可下载 URL。

        返回 {ok, frame_count, duration, fps, json_url, json_path, message}。
        """
        base = {
            "ok": False, "frame_count": 0, "duration": 0.0, "fps": 0.0,
            "json_url": "", "json_path": "", "message": "",
        }

        # 1) 视频本地路径校验（外链 URL / 不存在均诚实失败）
        if not video_path or not os.path.isfile(video_path):
            base["message"] = f"视频文件不存在或不可访问: {video_path or '(空)'}"
            return base

        # 2) 后端探测（打包环境 / 依赖缺失提前失败，给出指引）
        backend = self.check_backend()
        if not backend.get("ok"):
            base["message"] = self._install_hint(backend)
            return base

        worker = _find_worker_script()
        out_path = self._make_output_path(video_path)

        # 3) 子进程推理（互斥：同时刻仅一个任务占用 GPU；中文路径经 subst 桥接转 ASCII）
        with self._run_lock:
            with _SubstBridge() as bridge:
                summary = self._run_worker(
                    [
                        bridge.remap(sys.executable), worker,
                        "--video", video_path,
                        "--out", out_path,
                        "--sample-step", str(max(1, int(sample_step))),
                        "--max-frames", str(max(1, int(max_frames))),
                        "--model-complexity", str(int(model_complexity)),
                    ],
                    timeout=timeout,
                    purpose="extract",
                )

        # 4) 结果校验：worker stdout 摘要 + 落盘 JSON 双重确认
        if isinstance(summary, dict) and summary.get("ok") and os.path.isfile(out_path):
            base.update({
                "ok": True,
                "frame_count": int(summary.get("frame_count") or 0),
                "duration": float(summary.get("duration") or 0.0),
                "fps": float(summary.get("fps") or 0.0),
                "json_path": out_path,
                "json_url": self._inbox_url(os.path.basename(out_path)),
                "message": f"已解析 {summary.get('frame_count')} 帧关键点（{summary.get('duration', 0)}s）",
            })
            logger.info("[pose-extract] 完成: %s → %s", video_path, out_path)
            return base

        # 诚实失败：转发 worker 的错误说明
        detail = summary.get("message") if isinstance(summary, dict) else str(summary)
        base["message"] = f"姿态解析失败: {detail or '子进程异常退出'}"
        logger.warning("[pose-extract] 失败: %s → %s", video_path, base["message"])
        return base

    # ═══════════════════════════════════════════════════════════
    # 私有工具
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _no_window_flags() -> int:
        """Windows 下隐藏子进程控制台窗口（与 comfy_provider 同约定）。"""
        if sys.platform == "win32":
            return 0x08000000  # CREATE_NO_WINDOW
        return 0

    @staticmethod
    def _run_worker(cmd: list, timeout: float, purpose: str) -> Any:
        """拉起子进程并等待；成功解析 stdout 单行 JSON，失败返回 {message} 字符串化结果。"""
        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=PoseExtractService._no_window_flags(),
            )
        except subprocess.TimeoutExpired:
            logger.warning("[pose-extract] 子进程超时（%.0fs）: %s", timeout, purpose)
            return {"message": f"推理超时（{timeout:.0f}s），请缩短视频或降低采样密度"}
        except OSError as exc:
            logger.warning("[pose-extract] 子进程启动失败: %s", exc)
            return {"message": f"子进程启动失败: {exc}"}

        elapsed = time.monotonic() - started

        # 解析 stdout 最后一行 JSON（worker 单行输出约定；--check 失败时详情也在 stdout）
        stdout_json = None
        for line in reversed((proc.stdout or "").strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        stdout_json = parsed
                        break
                except json.JSONDecodeError:
                    continue

        if stdout_json is not None:
            # worker 已给出结构化结论（含 --check 的依赖缺失详情）
            if proc.returncode == 0 or "ok" in stdout_json:
                return stdout_json

        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "").strip().splitlines()
            detail = stderr_tail[-1] if stderr_tail else f"退出码 {proc.returncode}"
            logger.warning("[pose-extract] %s 失败（%.1fs）: %s", purpose, elapsed, detail)
            return {"message": detail}

        logger.warning("[pose-extract] %s 无有效 stdout JSON（%.1fs）", purpose, elapsed)
        return {"message": "子进程未返回有效结果"}

    @staticmethod
    def _make_output_path(video_path: str) -> str:
        """结果 JSON 落 canvas inbox（与参考视频同目录，URL 规则复用 /inbox_file/）。"""
        from app.core.canvas_aigc import _canvas_inbox_dir

        inbox = _canvas_inbox_dir()
        os.makedirs(inbox, exist_ok=True)
        stem = os.path.splitext(os.path.basename(video_path))[0][:40] or "video"
        return os.path.join(inbox, f"{int(time.time())}_{stem}_pose.json")

    @staticmethod
    def _inbox_url(filename: str) -> str:
        """拼接可下载的 inbox 文件 URL（端口复用 canvas_bridge.DEFAULT_PORT）。"""
        from app.core.canvas_bridge import DEFAULT_PORT

        return f"http://127.0.0.1:{DEFAULT_PORT}/inbox_file/{filename}"

    @staticmethod
    def _install_hint(backend: Dict[str, Any]) -> str:
        """依赖缺失时的安装指引（含 frozen 环境的诚实说明）。"""
        if backend.get("frozen"):
            return str(backend.get("message") or "发布版暂不支持姿态解析")
        return (
            "姿态解析后端未就绪：请在当前 Python 环境安装依赖 "
            "pip install mediapipe opencv-python（详见 app/requirements-optional.txt）"
        )


# 全局单例便捷引用
pose_extract_service = PoseExtractService()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.stdout.write(
        json.dumps(pose_extract_service.check_backend(force=True), ensure_ascii=False, indent=2) + "\n"
    )
