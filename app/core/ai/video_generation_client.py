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

# P1-3 取消异常：任务线程内逐段检查抛出；伪包/独立加载时无任务底座，
# 空元组 except 子句永不匹配（等价于没有这个 except），普通调用零影响。
try:
    from app.core.canvas_gen_jobs import GenCancelled as _GenCancelled
except Exception:  # noqa: BLE001 - 独立加载场景（_verify 伪包）不可能出现取消
    _GenCancelled = ()  # type: ignore[assignment]


def _raise_if_cancelled() -> None:
    """gen-jobs 任务线程内已取消 → 抛 GenCancelled；普通调用（无令牌）零影响。

    ⚠️ 调用点不要包进 catch-all try（会把取消控制流吞成普通失败）。
    """
    try:
        from .pipeline_jobs import raise_if_cancelled as _ric
    except Exception:  # noqa: BLE001 - 伪包加载：无任务底座
        return
    _ric()


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
                 height: int = _DEFAULT_RESOLUTION[1],
                 spec: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        生成视频片段

        参数：
            prompt:    标准化提示词（中英文均可）
            duration:  单段时长（秒）
            count:     生成段数
            provider:  生成器；auto 表示按能力声明 + 优先级依次尝试
            width/height: 分辨率
            spec:      本次请求的**能力需求**（如 first_last_frame=True /
                       image_to_video=True / resolution="1080p"）；未提的字段不参与筛选

        返回：
            生成的视频文件路径列表（全部失败返回空列表）
        """
        _raise_if_cancelled()  # P1-3：入口即响应取消（排队期被取消的任务不再起跑）
        results: List[str] = []
        providers = self._resolve_provider_order(provider, spec=spec,
                                                 duration=duration,
                                                 width=width, height=height)
        # 额度池重排（P0-1）：有健康账号的 provider 优先；无账号配置时透传
        pool = None
        try:
            from .provider_pool import get_pool

            pool = get_pool()
            providers = pool.reorder_providers(providers)
        except Exception:
            logger.debug("[VideoGenerationClient] 额度池不可用，跳过重排", exc_info=True)
        last_error = ""
        for name in providers:
            _raise_if_cancelled()  # P1-3：provider 尝试之间响应取消
            handler = self._get_provider(name)
            if handler is None:
                continue
            try:
                paths = handler(prompt=prompt, duration=duration, count=count,
                                width=width, height=height)
                if paths:
                    results.extend(paths)
                    if pool is not None:
                        pool.report_success(name, segments=len(paths))
                    logger.info(f"[VideoGenerationClient] {name} 成功生成 {len(paths)} 段")
                    break  # 成功即停止尝试后续 provider
                if pool is not None and name != "local":
                    pool.report_failure(name, error="返回空结果")
            except _GenCancelled:
                raise  # 取消是控制流，不记 provider 失败（P1-3）
            except Exception as e:
                logger.warning(f"[VideoGenerationClient] {name} 执行失败: {e}")
                last_error = str(e)
                if pool is not None and name != "local":
                    pool.report_failure(name, error=str(e))

        # 所有真实 provider 失败 → 回退本地占位生成（保证业务流程可演示）
        if not results:
            _raise_if_cancelled()  # P1-3：占位生成前响应取消（不白跑 ffmpeg）
            if provider not in ("local",):
                logger.warning(f"[VideoGenerationClient] 真实 provider 全部失败，回退占位生成 ({last_error})")
            results = self._call_local_fallback(prompt=prompt, duration=duration,
                                                count=count, width=width, height=height)

        # 广播生成完成（便于 pipeline 层追踪）
        self._emit_generation_done(results, prompt=prompt)

        return results[:count] if results else []

    def list_providers(self) -> List[Dict[str, Any]]:
        """列出可用生成器及其可用状态 + 能力/单价/健康摘要（供 UI 展示）"""
        try:
            from .provider_caps import get_caps
        except Exception:
            get_caps = None  # type: ignore[assignment]
        pool = None
        try:
            from .provider_pool import get_pool

            pool = get_pool()
        except Exception:
            logger.debug("[VideoGenerationClient] 额度池不可用，健康信息缺省", exc_info=True)
        rows: List[Dict[str, Any]] = []
        for pid, name in (
            ("seedance", "火山引擎 Seedance"),
            ("cogvideo", "智谱 CogVideo"),
            ("local", "本地占位生成（FFmpeg 色块）"),
        ):
            row: Dict[str, Any] = {
                "id": pid, "name": name,
                "available": self._get_provider(pid) is not None,
            }
            if get_caps is not None:
                caps = get_caps(pid)
                if caps:
                    row["caps"] = {
                        k: caps.get(k)
                        for k in ("text_to_video", "image_to_video",
                                  "first_last_frame", "lip_sync",
                                  "max_duration", "resolutions", "quality_tier")
                    }
                    row["price_per_clip"] = float(caps.get("price_per_clip") or 0.0)
            if pool is not None:
                try:
                    row["health"] = pool.health(pid)
                except Exception:
                    logger.debug("[VideoGenerationClient] %s 健康查询失败", pid, exc_info=True)
            rows.append(row)
        return rows

    # ────────────── 报价（P1-1）──────────────

    def quote(self, provider: str = "auto", *, count: int = 1,
              duration: float = 0.0, width: int = 0, height: int = 0,
              spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """**生成前报价**：沿真实路由链预估本次生成花费 + 谁接单 + 配额健康。

        与 ``generate()`` 同一套决策（能力筛选 → 池内重排 → handler 可用性），
        但**只读预演**：不生成、不记账、不消耗配额。
        候选链里「客户端封装加载不出」的渠道会被跳过（与 generate 循环一致）。

        Returns（池可用时）::
            {"ok", "provider", "account_id", "tier", "price_per_clip", "count",
             "cost_estimate", "currency", "quota_remaining", "cloud_available",
             "dead_providers", "reason", "note"}
        池不可用时退化为声明表估算（provider/cost_estimate/count/note）。
        """
        merged: Dict[str, Any] = {}
        try:
            from .provider_caps import normalize_spec

            merged = normalize_spec(spec, duration=duration, width=width, height=height)
        except Exception:
            logger.debug("[VideoGenerationClient] spec 规范化失败，按空 spec 报价", exc_info=True)

        # ① 池视角报价（含账号/配额/死号跳过）
        try:
            from .provider_pool import get_pool

            q = get_pool().quote(provider, count=count, spec=merged or None)
        except Exception:
            logger.debug("[VideoGenerationClient] 池报价不可用，退化为声明估算", exc_info=True)
            q = {}

        # ② 校验「池认为的首选」handler 是否真的加载得出（与 generate 循环一致）
        chosen = str(q.get("provider") or "")
        if chosen and chosen != "local" and self._get_provider(chosen) is None:
            # 池不可用时 chosen 为空 → 走 ③ 的声明链兜底；
            # 池可用但首选封装缺失 → 沿池的重排链找下一个 handler 可用的
            fallback = self._resolve_provider_order(provider, spec=spec,
                                                    duration=duration,
                                                    width=width, height=height)
            chosen = next((p for p in fallback
                           if p != "local" and self._get_provider(p) is not None), "local")
            if chosen != q.get("provider"):
                q = dict(q)
                q["provider"] = chosen
                q["cloud_available"] = chosen != "local"
                q["account_id"] = ""
                q["quota_remaining"] = 0
                if chosen == "local":
                    q["cost_estimate"] = 0.0
                    q["price_per_clip"] = 0.0
                    q["reason"] = "云端客户端封装不可用，将回退本地占位"

        if q:
            return q

        # ③ 池完全不可用：声明表估算 + handler 可用性修正
        try:
            from .provider_caps import quote as caps_quote

            q = dict(caps_quote(provider, count=count, spec=merged or None))
            if q.get("provider") != "local" and \
                    self._get_provider(str(q.get("provider"))) is None:
                q["provider"] = "local"
                q["cost_estimate"] = 0.0
                q["price_per_clip"] = 0.0
            return q
        except Exception:
            return {"ok": True, "provider": "local", "count": max(1, int(count or 1)),
                    "cost_estimate": 0.0, "currency": "CNY",
                    "note": "报价模块不可用，按本地占位（免费）报"}

    # ────────────── Provider 解析 ──────────────

    def _resolve_provider_order(self, provider: str,
                                spec: Optional[Dict[str, Any]] = None,
                                duration: float = 0.0,
                                width: int = 0, height: int = 0) -> List[str]:
        """解析 provider 调用顺序。

        V4.35.0 起走**能力声明路由**（provider_caps.resolve_order）：
        按本次请求 spec 筛掉不支持的 provider，再按 quality_tier 排序，
        local 永远兜底。声明模块不可用时**诚实降级**回旧的名字顺序。
        """
        try:
            from .provider_caps import normalize_spec, resolve_order

            # 合并：显式 spec 优先，未提的字段由 generate() 的 duration/分辨率补上
            merged = normalize_spec(spec, duration=duration, width=width, height=height)
            return resolve_order(provider, spec=merged)
        except Exception:
            logger.debug("[VideoGenerationClient] 能力路由不可用，回退名字顺序", exc_info=True)
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
            _raise_if_cancelled()  # P1-3：占位段与段之间响应取消
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
