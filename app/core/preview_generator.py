import os
import subprocess
from typing import Optional


import logging
logger = logging.getLogger("AI短剧编辑器.core.preview_generator")

class PreviewGenerator:
    """预览生成器"""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir

    def generate_preview(self, asset_path: str, asset_id: str) -> Optional[str]:
        """生成素材预览"""
        preview_path = os.path.join(self.cache_dir, f"{asset_id}_preview.jpg")

        try:
            cmd = [
                "ffmpeg", "-i", asset_path, "-ss", "00:00:01",
                "-vframes", "1", "-q:v", "2", preview_path
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return preview_path
        except subprocess.TimeoutExpired:
            logger.info(f'生成预览超时: {asset_path}')
        except Exception as e:
            logger.error(f'生成预览失败: {e}')

        return None

    def generate_thumbnail(
        self, asset_path: str, asset_id: str, timestamp: str = "00:00:01"
    ) -> Optional[str]:
        """生成缩略图"""
        thumbnail_path = os.path.join(self.cache_dir, f"{asset_id}_thumb.jpg")

        try:
            cmd = [
                "ffmpeg", "-i", asset_path, "-ss", timestamp,
                "-vframes", "1", "-q:v", "5", "-s", "320x240", thumbnail_path
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return thumbnail_path
        except subprocess.TimeoutExpired:
            logger.info(f'生成缩略图超时: {asset_path}')
        except Exception as e:
            logger.error(f'生成缩略图失败: {e}')

        return None

    def get_preview_path(self, asset_id: str) -> str:
        """获取预览文件路径"""
        return os.path.join(self.cache_dir, f"{asset_id}_preview.jpg")

    def preview_exists(self, asset_id: str) -> bool:
        """检查预览文件是否存在"""
        preview_path = self.get_preview_path(asset_id)
        return os.path.exists(preview_path)
