"""
导出渲染器
==========
集成统一渲染管理器，支持多格式/多平台导出
"""
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("AI短剧编辑器.export_render")

class ExportRenderer:
    """导出渲染器 — 对接统一 RenderManager"""

    def __init__(self):
        self._initialized = False
        self._rm = None

    def initialize(self) -> bool:
        try:
            from app.core.render_manager import get_render_manager
            self._rm = get_render_manager()
            self._initialized = True
            logger.info("导出渲染器已初始化")
            return True
        except Exception as e:
            logger.error(f"导出渲染器初始化失败: {e}")
            return False

    def export_video(self, input_path: str, output_path: str,
                     platform: str = "通用HD", **kwargs) -> bool:
        """导出视频

        Args:
            input_path: 输入视频路径
            output_path: 输出路径
            platform: 平台预设 (抖音/快手/B站/小红书/视频号/通用HD)
            **kwargs: 覆盖参数 (width, height, fps, bitrate, codec 等)

        Returns:
            是否导出成功
        """
        if not self._initialized:
            self.initialize()
        if not self._rm:
            logger.error("渲染管理器不可用")
            return False

        try:
            result = self._rm.render(input_path, output_path, platform=platform)
            if result.success:
                logger.info(f"导出成功: {output_path} ({result.processing_time:.1f}s, {result.output_size/1024/1024:.1f}MB)")
            else:
                logger.error(f"导出失败: {result.error_message}")
            return result.success
        except Exception as e:
            logger.error(f"导出异常: {e}")
            return False

    def export_audio(self, input_path: str, output_path: str,
                     format: str = "mp3") -> bool:
        """提取音频"""
        if not self._initialized:
            self.initialize()
        if not self._rm:
            return False
        try:
            from app.core.render_manager import FFmpegTool
            success, err = FFmpegTool.run(
                ["-i", input_path, "-vn", "-acodec", "libmp3lame" if format == "mp3" else "aac",
                 "-y", output_path]
            )
            return success
        except Exception as e:
            logger.error(f"音频提取失败: {e}")
            return False

    def shutdown(self):
        self._initialized = False
        self._rm = None
