"""
代理媒体 (Proxy Media) 模块 - 补短 P0#1
=========================================
解决 4K/高码率素材在时间轴上拖动卡顿的问题：
  - 源视频 → 540p + 低码率的 H.264 代理文件
  - UI / 预览 / 缩略图统一走代理
  - 导出时切回原始高质量源

对齐 Shotcut / OpenShot 标配能力：
  - Shotcut: Settings → Proxy → Use Proxy
  - OpenShot: Profile → Proxy

架构（最小侵入）：
  app/core/proxy_media.py
    ├── ProxyConfig           # 代理参数（分辨率/码率/编码）
    ├── ProxyMediaManager     # 代理生成 + 缓存 + 异步任务
    └── get_proxy_manager()   # 全局单例

  与现有模块关系：
    - LocalAssetManager: 调 should_generate_proxy() 判断是否需要代理
    - PreviewManager:    调 get_proxy_path() 拿到低分辨率路径
    - cpp_engine:        复用 C++ 视频引擎做转码（如果可用），否则回退 ffmpeg
"""
import os
import hashlib
import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List, Callable

logger = logging.getLogger("AI短剧编辑器.proxy_media")

# 默认代理缓存根目录
_DEFAULT_PROXY_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "proxies")
)


class ProxyStrategy(Enum):
    """代理策略"""
    DISABLED = "disabled"            # 关闭代理
    AUTO = "auto"                    # 自动（按分辨率/码率阈值）
    ALWAYS = "always"                # 总是生成


@dataclass
class ProxyConfig:
    """代理生成参数（对齐 Shotcut 默认值；漫剧竖屏按长边限制，不强制 16:9 pad）"""
    target_width: int = 960          # 长边上限（横/竖均适用）
    target_height: int = 960
    video_bitrate: str = "1500k"     # 视频码率
    audio_bitrate: str = "128k"      # 音频码率
    codec: str = "libx264"
    preset: str = "ultrafast"        # 编码速度优先（代理是临时文件）
    fps: int = 0                     # 0=跟随源帧率
    audio_sample_rate: int = 44100
    # 自动策略阈值：源超过此规格才生成代理
    auto_width_threshold: int = 1280
    auto_height_threshold: int = 720
    auto_bitrate_threshold_kbps: int = 4000


# 异步任务状态
_TASK_STATUS_PENDING = "pending"
_TASK_STATUS_RUNNING = "running"
_TASK_STATUS_DONE = "done"
_TASK_STATUS_FAILED = "failed"


class ProxyMediaManager:
    """
    代理媒体管理器

    功能：
      1. 智能判定：源是否需要代理（按策略 + 阈值）
      2. 异步生成：后台 QThread/threading 跑 ffmpeg 转码
      3. 缓存管理：同源 hash 复用代理；LRU 清理
      4. 状态查询：UI 知道代理生成中 / 完成 / 失败
    """

    def __init__(self,
                 cache_dir: str = _DEFAULT_PROXY_DIR,
                 strategy: ProxyStrategy = ProxyStrategy.AUTO,
                 config: Optional[ProxyConfig] = None):
        self.cache_dir = cache_dir
        self.strategy = strategy
        self.config = config or ProxyConfig()
        os.makedirs(self.cache_dir, exist_ok=True)

        # 任务表：source_path -> {status, proxy_path, error, progress, started_at}
        self._tasks: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self.enabled = strategy != ProxyStrategy.DISABLED

    def set_cache_dir(self, cache_dir: str) -> None:
        """迁移代理缓存根目录（设置页可选 NVMe）。"""
        if not cache_dir:
            return
        path = os.path.normpath(os.path.abspath(cache_dir))
        os.makedirs(path, exist_ok=True)
        with self._lock:
            self.cache_dir = path
        logger.info("[proxy] 缓存目录: %s", path)

    def set_strategy(self, strategy: ProxyStrategy) -> None:
        self.strategy = strategy
        self.enabled = strategy != ProxyStrategy.DISABLED

    def resolve_for_preview(self, source_path: str) -> str:
        """预览用路径：已有代理则返回代理，否则返回源。"""
        if not source_path or not self.enabled:
            return source_path
        if self.has_proxy(source_path):
            return self.get_proxy_path(source_path)
        return source_path

    # ---------- 判定 ----------

    def should_generate_proxy(self,
                              source_path: str,
                              width: int = 0,
                              height: int = 0,
                              bitrate_kbps: int = 0) -> bool:
        """
        判断是否需要为该源生成代理。

        Args:
            source_path: 源视频路径
            width/height: 源分辨率（0 表示未知，需自行探测）
            bitrate_kbps: 源码率（kbps，0 表示未知）

        Returns:
            True 表示需要生成代理
        """
        if self.strategy == ProxyStrategy.DISABLED:
            return False
        if self.strategy == ProxyStrategy.ALWAYS:
            return True
        # AUTO 模式：超过阈值才生成
        if width <= 0 or height <= 0:
            # 未知规格时保守生成（让剪辑更顺）
            return True
        if (width > self.config.auto_width_threshold or
                height > self.config.auto_height_threshold):
            return True
        if bitrate_kbps > self.config.auto_bitrate_threshold_kbps:
            return True
        return False

    # ---------- 路径与缓存 ----------

    def get_proxy_path(self, source_path: str) -> str:
        """
        获取源对应的代理文件路径（不一定已生成）。

        命名规则：{md5(source_path + mtime).hex[:16]}.mp4
        - 用 mtime 让源被修改后代理失效
        - 用 md5 避免路径特殊字符
        """
        try:
            mtime = os.path.getmtime(source_path)
        except OSError:
            mtime = 0
        key = f"{os.path.abspath(source_path)}|{mtime}".encode("utf-8")
        name = hashlib.md5(key).hexdigest()[:16]
        return os.path.join(self.cache_dir, f"{name}.mp4")

    def has_proxy(self, source_path: str) -> bool:
        """代理文件是否已存在"""
        path = self.get_proxy_path(source_path)
        return os.path.isfile(path) and os.path.getsize(path) > 0

    # ---------- 状态查询 ----------

    def get_status(self, source_path: str) -> Dict:
        """
        查询源当前的代理状态。
        Returns: {status, proxy_path, error, progress, started_at}
        """
        with self._lock:
            return dict(self._tasks.get(os.path.abspath(source_path), {
                "status": _TASK_STATUS_DONE if self.has_proxy(source_path) else _TASK_STATUS_PENDING,
                "proxy_path": self.get_proxy_path(source_path) if self.has_proxy(source_path) else "",
                "error": "",
                "progress": 1.0 if self.has_proxy(source_path) else 0.0,
                "started_at": 0.0,
            }))

    # ---------- 生成 ----------

    def generate_sync(self, source_path: str,
                      on_progress: Optional[Callable[[float], None]] = None) -> bool:
        """
        同步生成代理（阻塞当前线程）。
        适用于小文件 / 测试 / 用户手动触发。
        """
        if not os.path.isfile(source_path):
            logger.error(f"源文件不存在: {source_path}")
            return False
        if self.has_proxy(source_path):
            return True

        proxy_path = self.get_proxy_path(source_path)
        cmd = self._build_ffmpeg_cmd(source_path, proxy_path)

        key = os.path.abspath(source_path)
        with self._lock:
            self._tasks[key] = {
                "status": _TASK_STATUS_RUNNING,
                "proxy_path": proxy_path,
                "error": "",
                "progress": 0.0,
                "started_at": time.time(),
            }

        logger.info(f"[proxy] 开始生成: {os.path.basename(source_path)} -> {proxy_path}")
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Windows 默认 gbk 读 ffmpeg 日志易 UnicodeDecodeError；用字节再解码
                creationflags=creationflags,
            )
            err_chunks: List[bytes] = []
            if proc.stderr is not None:
                for raw in proc.stderr:
                    err_chunks.append(raw)
                    if on_progress and b"time=" in raw:
                        on_progress(0.5)
            rc = proc.wait()
            if rc == 0 and os.path.isfile(proxy_path) and os.path.getsize(proxy_path) > 0:
                with self._lock:
                    self._tasks[key]["status"] = _TASK_STATUS_DONE
                    self._tasks[key]["progress"] = 1.0
                logger.info(f"[proxy] 生成成功: {proxy_path} ({os.path.getsize(proxy_path)} bytes)")
                return True
            err = b"".join(err_chunks).decode("utf-8", errors="replace")
            with self._lock:
                self._tasks[key]["status"] = _TASK_STATUS_FAILED
                self._tasks[key]["error"] = (err or "")[-300:]
            logger.error(f"[proxy] 生成失败: {source_path}, rc={rc}")
            return False
        except Exception as e:
            with self._lock:
                self._tasks[key]["status"] = _TASK_STATUS_FAILED
                self._tasks[key]["error"] = str(e)
            logger.error(f"[proxy] 异常: {e}")
            return False

    def generate_async(self, source_path: str,
                       on_done: Optional[Callable[[bool, str], None]] = None) -> threading.Thread:
        """异步生成代理（开新线程，不阻塞 UI）"""
        def _worker():
            ok = self.generate_sync(source_path)
            if on_done:
                try:
                    on_done(ok, self.get_proxy_path(source_path))
                except Exception as e:
                    logger.debug(f"[ProxyMedia] 代理生成回调失败: {e}")
        t = threading.Thread(target=_worker, daemon=True, name=f"proxy-{os.path.basename(source_path)}")
        t.start()
        return t

    # ---------- 内部 ----------

    def _find_ffmpeg(self) -> str:
        """优先项目内 ffmpeg，否则 PATH。"""
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            p = find_ffmpeg()
            if p:
                return str(p)
        except Exception:
            logger.debug("定位项目内 ffmpeg 失败，回退 PATH", exc_info=True)
        return "ffmpeg"

    def _build_ffmpeg_cmd(self, source_path: str, proxy_path: str) -> List[str]:
        """构造 ffmpeg 转码命令：长边限制，保持片源宽高比（漫剧 9:16 友好）。"""
        cfg = self.config
        long_edge = max(int(cfg.target_width or 960), int(cfg.target_height or 960))
        # 长边压到 long_edge，短边按比例（-2 保证偶数边）
        vf = (
            f"scale='if(gt(iw,ih),min({long_edge},iw),-2)'"
            f":'if(gt(ih,iw),min({long_edge},ih),-2)'"
        )
        cmd = [
            self._find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", source_path,
        ]
        if int(cfg.fps or 0) > 0:
            cmd += ["-r", str(int(cfg.fps))]
        cmd += [
            "-vf", vf,
            "-c:v", cfg.codec,
            "-preset", cfg.preset,
            "-b:v", cfg.video_bitrate,
            "-c:a", "aac",
            "-b:a", cfg.audio_bitrate,
            "-ar", str(cfg.audio_sample_rate),
            "-movflags", "+faststart",
            proxy_path,
        ]
        return cmd

    def clear_idle_cache(self, max_age_days: float = 14.0) -> int:
        """删除闲置超过 max_age_days 的代理文件。"""
        import time as _time
        cutoff = _time.time() - max(1.0, float(max_age_days)) * 86400.0
        deleted = 0
        for item in self.list_cached():
            if float(item.get("mtime", 0) or 0) >= cutoff:
                continue
            try:
                os.remove(item["path"])
                deleted += 1
            except OSError as e:
                logger.debug("[ProxyMedia] 清理闲置代理失败: %s", e)
        return deleted

    # ---------- 缓存管理 ----------

    def list_cached(self) -> List[Dict]:
        """列出所有缓存的代理文件"""
        result = []
        if not os.path.isdir(self.cache_dir):
            return result
        for name in os.listdir(self.cache_dir):
            if not name.endswith(".mp4"):
                continue
            full = os.path.join(self.cache_dir, name)
            try:
                stat = os.stat(full)
                result.append({
                    "name": name,
                    "path": full,
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                })
            except OSError:
                continue
        return result

    def get_cache_size_mb(self) -> float:
        """缓存总大小（MB）"""
        total = sum(item["size_bytes"] for item in self.list_cached())
        return total / (1024 * 1024)

    def clear_cache(self) -> int:
        """清空所有代理缓存。返回删除的文件数。"""
        count = 0
        for item in self.list_cached():
            try:
                os.remove(item["path"])
                count += 1
            except OSError as e:
                logger.debug(f"[ProxyMedia] 删除缓存文件失败: {e}")
        return count

    def clear_cache_lru(self, keep_mb: float = 1024.0) -> int:
        """
        按 LRU 清理缓存，直到总大小 <= keep_mb。
        返回删除的文件数。
        """
        items = sorted(self.list_cached(), key=lambda x: x["mtime"])  # 老的在前
        total_mb = self.get_cache_size_mb()
        deleted = 0
        for item in items:
            if total_mb <= keep_mb:
                break
            try:
                os.remove(item["path"])
                total_mb -= item["size_bytes"] / (1024 * 1024)
                deleted += 1
            except OSError as e:
                logger.debug(f"[ProxyMedia] LRU清理缓存失败: {e}")
        return deleted


# ---- 全局单例 ----

_manager_instance: Optional[ProxyMediaManager] = None
_manager_lock = threading.Lock()


def get_proxy_manager(strategy: ProxyStrategy = ProxyStrategy.AUTO,
                      config: Optional[ProxyConfig] = None) -> ProxyMediaManager:
    """获取全局代理管理器（线程安全单例）"""
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = ProxyMediaManager(strategy=strategy, config=config)
        return _manager_instance


def reset_proxy_manager():
    """重置单例（测试用）"""
    global _manager_instance
    with _manager_lock:
        _manager_instance = None
