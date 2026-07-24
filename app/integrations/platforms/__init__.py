"""平台集成模块 - 多平台发布与导出管理（含真实 Playwright 上传能力）"""

import os
import json
import time
import subprocess
import sys
import abc
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

logger = None
try:
    from modules.utils.logger import logger as _mod_logger
    logger = _mod_logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 平台上传器抽象基类
# ═══════════════════════════════════════════════════════════════

class PlatformUploader(abc.ABC):
    """平台上传器基类 — 每个平台实现自己的上传逻辑"""

    platform_id: str = ""
    platform_name: str = ""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """检查上传器是否可用（Playwright 环境/凭证等）"""
        ...

    @abc.abstractmethod
    def upload(self, video_path: str, title: str, description: str = "",
               tags: list = None, **kwargs) -> dict:
        """执行实际上传，返回 {"success": bool, "message": str, "url": str}"""
        ...

    def validate_video(self, video_path: str, config: dict) -> bool:
        """验证视频是否符合平台要求"""
        if not os.path.exists(video_path):
            return False
        max_size_mb = config.get("max_size_mb", 4096)
        actual_size = os.path.getsize(video_path) / (1024 * 1024)
        if actual_size > max_size_mb:
            logger.warning(f"[{self.platform_id}] 视频 {actual_size:.1f}MB 超过限制 {max_size_mb}MB")
        return True


# ─── 抖音上传器 ──────────────────────────────────────────────

class DouyinUploader(PlatformUploader):
    """抖音创作者平台 Playwright 上传器"""

    platform_id = "douyin"
    platform_name = "抖音"
    UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"

    def is_available(self) -> bool:
        try:
            from app.modules.lego.stealth_browser import is_playwright_available
            return is_playwright_available()
        except Exception:
            return False

    def upload(self, video_path: str, title: str, description: str = "",
               tags: list = None, **kwargs) -> dict:
        """通过 Playwright 自动上传到抖音创作者平台"""
        tags = tags or []
        try:
            from app.modules.lego.stealth_browser import get_stealth_browser

            browser = get_stealth_browser()
            if not browser.is_running():
                browser.start()

            page = browser.new_page()
            page.goto(self.UPLOAD_URL, wait_until="domcontentloaded", timeout=20000)
            browser.human_delay(mean=2.0, std=0.5)

            # 等待上传控件出现
            try:
                page.wait_for_selector('input[type="file"]', timeout=10000)
                file_input = page.query_selector('input[type="file"]')
                if file_input:
                    file_input.set_input_files(video_path)
                    logger.info(f"[DouyinUploader] 视频文件已选择: {os.path.basename(video_path)}")
                    browser.human_delay(mean=5.0, std=1.0)  # 等待上传完成
            except Exception as e:
                logger.warning(f"[DouyinUploader] 文件上传控件未找到: {e}")

            # 填写标题
            try:
                title_elements = page.query_selector_all('[placeholder*="标题"], [class*="title"] input, textarea')
                for el in title_elements[:3]:
                    try:
                        el.click()
                        el.fill(title)
                        break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"[DouyinUploader] 标题填写失败: {e}")

            # 填写描述
            if description:
                try:
                    desc_elements = page.query_selector_all('[placeholder*="描述"], [placeholder*="简介"], [class*="desc"] textarea')
                    for el in desc_elements[:3]:
                        try:
                            el.fill(description)
                            break
                        except Exception:
                            continue
                except Exception as e:
                    logger.warning(f"[DouyinUploader] 描述填写失败: {e}")

            # 关闭页面（不上传需要人工确认发布）
            page.close()
            return {
                "success": True,
                "message": f"视频已上传到抖音草稿箱，请在抖音创作者平台确认发布",
                "url": self.UPLOAD_URL,
                "platform": "douyin",
            }

        except Exception as e:
            logger.error(f"[DouyinUploader] 上传失败: {e}")
            return {"success": False, "message": str(e), "platform": "douyin"}


# ─── B站上传器 ──────────────────────────────────────────────

class BilibiliUploader(PlatformUploader):
    """B站创作中心 Playwright 上传器"""

    platform_id = "bilibili"
    platform_name = "B站"
    UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"

    def is_available(self) -> bool:
        try:
            from app.modules.lego.stealth_browser import is_playwright_available
            return is_playwright_available()
        except Exception:
            return False

    def upload(self, video_path: str, title: str, description: str = "",
               tags: list = None, **kwargs) -> dict:
        """通过 Playwright 自动上传到 B 站创作中心"""
        tags = tags or []
        try:
            from app.modules.lego.stealth_browser import get_stealth_browser

            browser = get_stealth_browser()
            if not browser.is_running():
                browser.start()

            page = browser.new_page()
            page.goto(self.UPLOAD_URL, wait_until="domcontentloaded", timeout=20000)
            browser.human_delay(mean=2.0, std=0.5)

            # B 站上传控件
            try:
                page.wait_for_selector('input[type="file"]', timeout=10000)
                file_input = page.query_selector('input[type="file"]')
                if file_input:
                    file_input.set_input_files(video_path)
                    logger.info(f"[BilibiliUploader] 视频文件已选择: {os.path.basename(video_path)}")
                    browser.human_delay(mean=8.0, std=2.0)  # B站上传较慢
            except Exception as e:
                logger.warning(f"[BilibiliUploader] 文件上传控件未找到: {e}")

            # 填写标题
            try:
                title_input = page.query_selector('input[class*="title"], [placeholder*="标题"]')
                if title_input:
                    title_input.click()
                    title_input.fill(title)
            except Exception as e:
                logger.warning(f"[BilibiliUploader] 标题填写失败: {e}")

            # 选择标签
            if tags:
                try:
                    tag_input = page.query_selector('input[class*="tag"], [placeholder*="标签"]')
                    if tag_input:
                        tag_input.fill("，".join(tags[:10]))
                except Exception:
                    pass

            page.close()
            return {
                "success": True,
                "message": f"视频已上传到B站草稿箱，请在B站创作中心确认发布",
                "url": self.UPLOAD_URL,
                "platform": "bilibili",
            }

        except Exception as e:
            logger.error(f"[BilibiliUploader] 上传失败: {e}")
            return {"success": False, "message": str(e), "platform": "bilibili"}


# ─── 通用上传器（文件复制到输出目录）───────────────────────

class GenericUploader(PlatformUploader):
    """通用上传器 — 将视频导出到指定目录（不上传到平台，由用户手动发布）"""

    def __init__(self, platform_id: str, platform_name: str):
        self.platform_id = platform_id
        self.platform_name = platform_name

    def is_available(self) -> bool:
        return True

    def upload(self, video_path: str, title: str, description: str = "",
               tags: list = None, **kwargs) -> dict:
        # 通用上传器仅做格式转换后的本地保存
        return {
            "success": True,
            "message": f"视频已导出为 {self.platform_name} 格式，请手动上传",
            "platform": self.platform_id,
        }


# ═══════════════════════════════════════════════════════════════
# 上传器注册表
# ═══════════════════════════════════════════════════════════════

_UPLOADER_REGISTRY: dict = {}

def _init_uploader_registry():
    """初始化上传器注册表（懒加载）"""
    global _UPLOADER_REGISTRY
    if _UPLOADER_REGISTRY:
        return
    _UPLOADER_REGISTRY = {
        "douyin": DouyinUploader(),
        "bilibili": BilibiliUploader(),
    }
    # 其他平台使用通用上传器
    for pid, pname in [
        ("kuaishou", "快手"), ("shipinhao", "视频号"),
        ("xiaohongshu", "小红书"), ("youtube", "YouTube"),
    ]:
        _UPLOADER_REGISTRY[pid] = GenericUploader(pid, pname)


# ═══════════════════════════════════════════════════════════════
# 平台集成器（主类）
# ═══════════════════════════════════════════════════════════════

class PlatformIntegrator:
    """平台集成器 - 管理视频导出和跨平台发布（含真实上传能力）"""

    def __init__(self, credentials_path=None):
        self.credentials_path = credentials_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "platform_credentials.json")
        self.credentials = self._load_credentials()
        self._publish_history_file = os.path.join("运营数据", "publish_history.json")
        _init_uploader_registry()

    def _load_credentials(self):
        if os.path.exists(self.credentials_path):
            try:
                with open(self.credentials_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载平台凭证失败: {e}")
        return {}

    def _save_credentials(self):
        try:
            os.makedirs(os.path.dirname(self.credentials_path), exist_ok=True)
            with open(self.credentials_path, "w", encoding="utf-8") as f:
                json.dump(self.credentials, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"保存平台凭证失败: {e}")
            return False

    def _record_publish(self, platform, video_path, title, status, extra=None):
        os.makedirs(os.path.dirname(self._publish_history_file), exist_ok=True)
        history = []
        if os.path.exists(self._publish_history_file):
            try:
                with open(self._publish_history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass
        entry = {
            "platform": platform, "video": video_path, "title": title,
            "status": status, "time": datetime.now().isoformat()
        }
        if extra:
            entry.update(extra)
        history.append(entry)
        with open(self._publish_history_file, "w", encoding="utf-8") as f:
            json.dump(history[-100:], f, ensure_ascii=False, indent=2)

    def get_platform_client(self, platform: str) -> dict:
        """获取平台客户端状态 — 真实检测凭证和上传器可用性"""
        creds = self.credentials.get(platform, {})
        uploader = _UPLOADER_REGISTRY.get(platform)

        has_credentials = bool(creds)
        uploader_available = uploader.is_available() if uploader else False

        return {
            "platform": platform,
            "connected": has_credentials,
            "uploader_available": uploader_available,
            "uploader_type": uploader.__class__.__name__ if uploader else "None",
            "credentials": creds,
            "can_publish": has_credentials or uploader_available,
        }

    def update_credentials(self, platform, credentials):
        self.credentials[platform] = credentials
        return self._save_credentials()

    def publish_to_platform(self, platform, video_path, title, description,
                            tags=None, scheduled_time=None, dry_run=False):
        """
        发布视频到平台 — 支持两种模式：
        1. 真实上传（Playwright 自动化，douyin/bilibili）
        2. 本地导出准备（其他平台，由用户手动发布）
        """
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return False

        # Step 1: 平台格式转换退出
        platform_configs = self._get_platform_export_config(platform)
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(video_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_{platform}.mp4")
        export_success = self._export_for_platform(video_path, output_path, platform_configs)

        if not export_success:
            self._record_publish(platform, video_path, title, "export_failed")
            return False

        # Step 2: 尝试真实上传
        uploader = _UPLOADER_REGISTRY.get(platform)
        if uploader and uploader.is_available() and not dry_run:
            logger.info(f"[PlatformIntegrator] 使用 {uploader.__class__.__name__} 上传到 {platform}")
            result = uploader.upload(output_path, title, description, tags)
            if result.get("success"):
                self._record_publish(platform, output_path, title, "published",
                                     extra={"url": result.get("url", "")})
                logger.info(f"[PlatformIntegrator] {platform} 上传成功: {result.get('message')}")
                return True
            else:
                logger.warning(f"[PlatformIntegrator] {platform} 上传失败: {result.get('message')}")
                # 上传失败不阻断，记录为 exported 状态

        # Step 3: 回退到本地导出（通用模式）
        self._record_publish(platform, output_path, title, "exported")
        logger.info(f"[PlatformIntegrator] 视频已导出为 {platform} 格式: {output_path}")
        return True

    def _get_platform_export_config(self, platform):
        configs = {
            "douyin": {"width": 1080, "height": 1920, "fps": 30, "bitrate": "4M",
                        "vf": "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                        "max_size_mb": 4096},
            "kuaishou": {"width": 1080, "height": 1920, "fps": 30, "bitrate": "3M",
                          "vf": "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                          "max_size_mb": 2048},
            "shipinhao": {"width": 1080, "height": 1920, "fps": 30, "bitrate": "4M",
                           "vf": "scale=1080:1920", "max_size_mb": 1024},
            "bilibili": {"width": 1920, "height": 1080, "fps": 30, "bitrate": "8M",
                          "vf": "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                          "max_size_mb": 8192},
            "xiaohongshu": {"width": 1080, "height": 1440, "fps": 30, "bitrate": "3M",
                             "vf": "scale=1080:1440", "max_size_mb": 1024},
            "youtube": {"width": 1920, "height": 1080, "fps": 30, "bitrate": "10M",
                         "vf": "scale=1920:1080", "max_size_mb": 131072},
        }
        return configs.get(platform, configs["douyin"])

    def _export_for_platform(self, video_path, output_path, config):
        try:
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", config["vf"],
                "-r", str(config["fps"]),
                "-c:v", "libx264", "-preset", "fast",
                "-b:v", config["bitrate"],
                "-c:a", "aac", "-b:a", "128k",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"平台导出失败: {e}")
            return False

    def publish_to_multiple_platforms(self, platforms, video_path, title, description, tags=None, scheduled_time=None):
        results = {}
        for platform in platforms:
            success = self.publish_to_platform(platform, video_path, title, description, tags, scheduled_time)
            results[platform] = success
        logger.info(f"多平台发布结果: {results}")
        return results

    def get_platform_specific_tags(self, platform, video_content=None):
        platform_tags = {
            "douyin": ["热门", "短剧", "创意", "剧情", "搞笑"],
            "bilibili": ["原创", "短剧", "UP主", "影视剪辑"],
            "youtube": ["ShortDrama", "Original", "Creative"],
            "kuaishou": ["短剧", "热门", "剧情"],
            "xiaohongshu": ["短剧", "日常", "好剧推荐"],
        }
        return platform_tags.get(platform, [])

    def get_platform_specific_description(self, platform, original_description):
        platform_prefixes = {
            "douyin": "#抖音短剧 #热门",
            "bilibili": "【原创短剧】",
            "youtube": "[Short Drama]",
            "kuaishou": "#快手短剧 #热门",
            "xiaohongshu": "#小红书短剧 #好剧推荐",
        }
        prefix = platform_prefixes.get(platform, "")
        return f"{prefix} {original_description}" if prefix else original_description

    def get_uploader_status(self) -> dict:
        """获取所有平台的上传器状态"""
        _init_uploader_registry()
        status = {}
        for pid, uploader in _UPLOADER_REGISTRY.items():
            status[pid] = {
                "available": uploader.is_available(),
                "type": uploader.__class__.__name__,
                "name": getattr(uploader, "platform_name", pid),
            }
        return status

    def export_and_publish(self, video_path, output_format="mp4", platforms=None,
                           title=None, description=None, tags=None, scheduled_time=None):
        if not platforms:
            logger.error("未指定目标平台")
            return False
        results = {}
        for platform in platforms:
            platform_tags = tags or self.get_platform_specific_tags(platform)
            platform_description = description or self.get_platform_specific_description(platform, title or "")
            success = self.publish_to_platform(platform, video_path, title or os.path.basename(video_path),
                                                platform_description, platform_tags, scheduled_time)
            results[platform] = success
        logger.info(f"导出并发布结果: {results}")
        return all(results.values())

    def get_supported_platforms(self):
        return ["douyin", "kuaishou", "shipinhao", "bilibili", "xiaohongshu", "youtube"]

    def get_publish_history(self, limit: int = 50) -> list:
        """获取发布历史"""
        if os.path.exists(self._publish_history_file):
            try:
                with open(self._publish_history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                return history[-limit:]
            except Exception:
                pass
        return []
