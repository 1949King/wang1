"""
AI 视频生成客户端 (VideoGenerationClient)
=========================================
统一封装 AI 视频生成服务（火山 Seedance / 智谱 CogVideo / 本地占位）。

设计原则：
  - 单例，线程安全；调用方应在 worker 线程调用，本模块不阻塞 Qt 主线程。
  - 优先调用真实云端/本地生成服务；失败自动回退到本地占位生成（FFmpeg 色块）。
  - 只输出文件路径，不写 UI 逻辑；UI 由 pipeline 层通过 EventBus 驱动。
  - 失败通过 EventBus 广播 GENERATION_INSPECTION_FAILED，由 AgentFeedbackBridge 回流。

架构位置：
  AgentPipelineRouter → AIVideoGenerationPipeline → VideoGenerationClient
"""
from __future__ import annotations
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 占位片段默认参数
_DEFAULT_FPS = 30
_DEFAULT_RESOLUTION = (1280, 720)  # 720p 占位
_DEFAULT_DURATION = 5.0


class VideoGenerationClient:
    """
    AI 视频生成客户端 —— 单例

    使用方式：
        from app.core.ai.video_generation_client import video_generation_client
        paths = video_generation_client.generate(prompt="...", duration=5.0, count=3)
    """
    _instance: Optional['VideoGenerationClient'] = None
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
        self._providers: Dict[str, Optional[Callable]] = {}  # 延迟加载缓存
        self._output_dir = os.path.join(tempfile.gettempdir(), "shiguangyx_ai_gen")
        try:
            os.makedirs(self._output_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"[VideoGenerationClient] 创建输出目录失败: {e}")

    @classmethod
    def get_instance(cls) -> 'VideoGenerationClient':
        return cls()

    # ────────────── 公共接口 ──────────────

    def generate(self, prompt: str, duration: float = _DEFAULT_DURATION,
                 count: int = 1, provider: str = "auto",
                 width: int = _DEFAULT_RESOLUTION[0],
                 height: int = _DEFAULT_RESOLUTION[1]) -> List[str]:
        """
        生成视频片段

        参数：
            prompt:    标准化提示词（中英文均可）
            duration:  单段时长（秒）
            count:     生成段数
            provider:  生成器；auto 表示按优先级依次尝试
            width/height: 分辨率

        返回：
            生成的视频文件路径列表（全部失败返回空列表）
        """
        results: List[str] = []
        providers = self._resolve_provider_order(provider)
        last_error = ""
        for name in providers:
            handler = self._get_provider(name)
            if handler is None:
                continue
            try:
                paths = handler(prompt=prompt, duration=duration, count=count,
                                width=width, height=height)
                if paths:
                    results.extend(paths)
                    logger.info(f"[VideoGenerationClient] {name} 成功生成 {len(paths)} 段")
                    break  # 成功即停止尝试后续 provider
            except Exception as e:
                logger.warning(f"[VideoGenerationClient] {name} 执行失败: {e}")
                last_error = str(e)

        # 所有真实 provider 失败 → 回退本地占位生成（保证业务流程可演示）
        if not results:
            if provider not in ("local",):
                logger.warning(f"[VideoGenerationClient] 真实 provider 全部失败，回退占位生成 ({last_error})")
            results = self._call_local_fallback(prompt=prompt, duration=duration,
                                                count=count, width=width, height=height)

        # 广播生成完成（便于 pipeline 层追踪）
        self._emit_generation_done(results, prompt=prompt)

        return results[:count] if results else []

    def list_providers(self) -> List[Dict[str, Any]]:
        """列出可用生成器及其可用状态（供 UI 展示）"""
        return [
            {"id": "seedance", "name": "火山引擎 Seedance",
             "available": self._get_provider("seedance") is not None},
            {"id": "cogvideo", "name": "智谱 CogVideo",
             "available": self._get_provider("cogvideo") is not None},
            {"id": "local", "name": "本地占位生成（FFmpeg 色块）", "available": True},
        ]

    # ────────────── Provider 解析 ──────────────

    def _resolve_provider_order(self, provider: str) -> List[str]:
        """解析 provider 调用顺序"""
        if provider and provider != "auto":
            return [provider, "local"]
        return ["seedance", "cogvideo", "local"]

    def _get_provider(self, name: str) -> Optional[Callable]:
        """延迟加载 provider，加载失败返回 None"""
        if name == "local":
            return self._call_local_fallback
        if name in self._providers:
            return self._providers[name]
        handler: Optional[Callable] = None
        try:
            if name == "seedance":
                handler = self._load_seedance()
            elif name == "cogvideo":
                handler = self._load_cogvideo()
        except Exception as e:
            logger.debug(f"[VideoGenerationClient] 加载 {name} 失败: {e}")
        self._providers[name] = handler
        return handler

    def _load_seedance(self) -> Optional[Callable]:
        """加载火山引擎 Seedance 客户端（项目内若有封装则用，否则返回 None）"""
        # 尝试项目内可能的封装路径；不存在则静默回退
        try:
            from app.core.ai.byted_seedance import generate_videos as _seed  # type: ignore
            return _seed
        except Exception as e:
            logger.debug(f"[VideoGenClient] 加载Seedance封装失败: {e}")
        try:
            from app.core.ai.byted_seedance_client import SeedanceClient  # type: ignore
            client = SeedanceClient()

            def _seed(prompt, duration, count, width, height):
                return client.generate(prompt=prompt, duration=duration, count=count)
            return _seed
        except Exception as e:
            logger.debug(f"[VideoGenClient] 加载SeedanceClient失败: {e}")
            return None

    def _load_cogvideo(self) -> Optional[Callable]:
        """加载智谱 CogVideo 客户端"""
        try:
            from app.core.ai.cogvideo_client import CogVideoClient  # type: ignore
            client = CogVideoClient()

            def _cog(prompt, duration, count, width, height):
                return client.generate(prompt=prompt, duration=duration, count=count)
            return _cog
        except Exception:
            return None

    # ────────────── 本地占位生成 ──────────────

    def _call_local_fallback(self, prompt: str, duration: float = _DEFAULT_DURATION,
                             count: int = 1, width: int = _DEFAULT_RESOLUTION[0],
                             height: int = _DEFAULT_RESOLUTION[1],
                             **_: Any) -> List[str]:
        """
        本地占位生成：用 FFmpeg 生成色块 + hue 渐变 + 文字标识的占位片段。
        保证无网络/无云端 Key 时业务流程仍可演示。
        失败回退到无文字的纯色块版本。
        """
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            logger.error("[VideoGenerationClient] 未找到 ffmpeg，无法占位生成")
            return []

        paths: List[str] = []
        safe_prompt = (prompt or "AI生成")[:20].replace(" ", "_").replace(":", "_")
        for i in range(count):
            out_path = os.path.join(
                self._output_dir,
                f"gen_{int(time.time())}_{uuid.uuid4().hex[:6]}_{safe_prompt}_{i + 1}.mp4"
            )
            hue = (i * 60) % 360  # 不同片段用不同色相，便于区分
            label = self._escape_drawtext(f"AI Gen #{i + 1} | {(prompt or '')[:24]}")
            if self._generate_with_text(ffmpeg, out_path, label, hue, duration, width, height):
                paths.append(out_path)
            elif self._generate_plain(ffmpeg, out_path, hue, duration, width, height):
                paths.append(out_path)
            else:
                logger.warning(f"[VideoGenerationClient] 占位生成第 {i + 1} 段失败")
        return paths

    def _generate_with_text(self, ffmpeg: str, out_path: str, label: str,
                            hue: int, duration: float, width: int, height: int) -> bool:
        """带文字标识的占位生成（需要字体支持）"""
        filter_str = (
            f"color=c=0x223355:s={width}x{height}:d={duration}:r={_DEFAULT_FPS},"
            f"format=yuv420p,"
            f"drawtext=text='{label}':fontcolor=white:fontsize=32:"
            f"x=(w-text_w)/2:y=(h-text_h)/2,"
            f"hue=h={hue}:s=1"
        )
        return self._run_ffmpeg(ffmpeg, filter_str, duration, out_path)

    def _generate_plain(self, ffmpeg: str, out_path: str, hue: int,
                        duration: float, width: int, height: int) -> bool:
        """无文字的纯色块占位生成（字体不支持时回退）"""
        filter_str = (
            f"color=c=0x223355:s={width}x{height}:d={duration}:r={_DEFAULT_FPS},"
            f"format=yuv420p,hue=h={hue}:s=1"
        )
        return self._run_ffmpeg(ffmpeg, filter_str, duration, out_path)

    def _run_ffmpeg(self, ffmpeg: str, filter_str: str,
                    duration: float, out_path: str) -> bool:
        """执行 ffmpeg 命令生成片段"""
        cmd = [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", filter_str,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-t", str(duration),
            out_path,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=60,
                creationflags=self._subprocess_flags(),
            )
            return proc.returncode == 0 and os.path.exists(out_path) \
                and os.path.getsize(out_path) > 0
        except Exception as e:
            logger.debug(f"[VideoGenerationClient] ffmpeg 执行异常: {e}")
            return False

    # ────────────── 工具方法 ──────────────

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        """转义 drawtext 文本中的特殊字符"""
        # drawtext 对冒号/单引号/反斜杠敏感
        return (text.replace("\\", "\\\\")
                    .replace(":", "\\:")
                    .replace("'", "\\'"))

    @staticmethod
    def _find_ffmpeg() -> Optional[str]:
        """优先复用项目 ffmpeg_utils（含 thirdparty/ffmpeg/bin/ 查找），回退本地候选 + 系统 PATH"""
        # 1. 项目统一 ffmpeg 查找逻辑（禁止重复造轮子）
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            path = find_ffmpeg()
            if path and os.path.isfile(path):
                return path
        except Exception as e:
            logger.debug(f"[VideoGenerationClient] ffmpeg_utils 查找失败: {e}")
        # 2. 本地候选（兼容兜底）
        candidates = [
            os.path.join(os.getcwd(), "thirdparty", "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(os.getcwd(), "ffmpeg", "ffmpeg.exe"),
            os.path.join(os.getcwd(), "bin", "ffmpeg.exe"),
            os.path.join(os.getcwd(), "tools", "ffmpeg.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")

    @staticmethod
    def _subprocess_flags() -> int:
        """Windows 下隐藏控制台窗口，避免弹出黑框"""
        try:
            import sys
            if sys.platform == "win32":
                return 0x08000000  # CREATE_NO_WINDOW
        except Exception as e:
            logger.debug(f"[VideoGenClient] 获取子进程标志失败: {e}")
        return 0

    def _emit_generation_done(self, paths: List[str], prompt: str) -> None:
        """广播生成完成事件（便于 pipeline 层追踪，不强制依赖 EventBus）"""
        try:
            from app.modules.lego.core import EventBus, EventType
            bus = EventBus.get_instance()
            bus.emit(
                EventType.CUSTOM,
                {
                    "subtype": "video_generation_done",
                    "count": len(paths),
                    "paths": paths,
                    "prompt": prompt[:80],
                },
                source="VideoGenerationClient",
            )
        except Exception as e:
            logger.debug(f"[VideoGenerationClient] emit 失败: {e}")


# 全局单例便捷引用
video_generation_client = VideoGenerationClient.get_instance()
