"""
平台适配模块 (PlatformAdapter)
==========================
支持抖音、快手、小红书等平台的导出格式和模板
"""

import json
import os
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class PlatformConfig:
    """平台配置"""
    name: str
    display_name: str
    description: str
    video_formats: List[str]
    aspect_ratios: List[str]
    max_duration: int
    max_size: int
    recommended_resolutions: List[str]
    watermark_position: Optional[str] = None
    template_paths: List[str] = field(default_factory=list)


class PlatformAdapter:
    """平台适配器"""
    
    _instance: Optional['PlatformAdapter'] = None
    
    PLATFORMS = {
        "douyin": PlatformConfig(
            name="douyin",
            display_name="抖音",
            description="抖音短视频平台",
            video_formats=["mp4"],
            aspect_ratios=["9:16", "16:9", "1:1"],
            max_duration=60,
            max_size=50 * 1024 * 1024,  # 50MB
            recommended_resolutions=["1080x1920", "1920x1080", "1080x1080"],
            watermark_position="bottom-right"
        ),
        "kuaishou": PlatformConfig(
            name="kuaishou",
            display_name="快手",
            description="快手短视频平台",
            video_formats=["mp4"],
            aspect_ratios=["9:16", "16:9", "1:1"],
            max_duration=60,
            max_size=50 * 1024 * 1024,  # 50MB
            recommended_resolutions=["1080x1920", "1920x1080", "1080x1080"],
            watermark_position="bottom-right"
        ),
        "xiaohongshu": PlatformConfig(
            name="xiaohongshu",
            display_name="小红书",
            description="小红书内容平台",
            video_formats=["mp4"],
            aspect_ratios=["9:16", "1:1"],
            max_duration=180,  # 3分钟
            max_size=100 * 1024 * 1024,  # 100MB
            recommended_resolutions=["1080x1920", "1080x1080"],
            watermark_position="top-right"
        ),
        "weibo": PlatformConfig(
            name="weibo",
            display_name="微博",
            description="微博社交平台",
            video_formats=["mp4"],
            aspect_ratios=["16:9", "9:16", "1:1"],
            max_duration=180,  # 3分钟
            max_size=50 * 1024 * 1024,  # 50MB
            recommended_resolutions=["1920x1080", "1080x1920", "1080x1080"],
            watermark_position="bottom-right"
        ),
        "tiktok": PlatformConfig(
            name="tiktok",
            display_name="TikTok",
            description="国际版抖音",
            video_formats=["mp4"],
            aspect_ratios=["9:16", "16:9", "1:1"],
            max_duration=60,
            max_size=75 * 1024 * 1024,  # 75MB
            recommended_resolutions=["1080x1920", "1920x1080", "1080x1080"],
            watermark_position="bottom-right"
        )
    }
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._templates: Dict[str, List[Dict]] = {}
        self._load_templates()
    
    def _load_templates(self):
        """加载平台模板"""
        template_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "platform_templates"
        )
        
        if not os.path.exists(template_dir):
            os.makedirs(template_dir, exist_ok=True)
            # 创建默认模板
            self._create_default_templates(template_dir)
        
        for platform in self.PLATFORMS:
            platform_dir = os.path.join(template_dir, platform)
            if os.path.exists(platform_dir):
                templates = []
                for file in os.listdir(platform_dir):
                    if file.endswith(".json"):
                        try:
                            with open(os.path.join(platform_dir, file), 'r', encoding='utf-8') as f:
                                template = json.load(f)
                                templates.append(template)
                        except Exception as e:
                            logger.error(f"加载模板失败: {e}")
                self._templates[platform] = templates
    
    def _create_default_templates(self, template_dir):
        """创建默认模板"""
        default_templates = {
            "douyin": [
                {
                    "name": "抖音热门模板",
                    "description": "适合抖音平台的热门风格",
                    "aspect_ratio": "9:16",
                    "resolution": "1080x1920",
                    "duration": 15,
                    "effects": ["fade_in", "fade_out"],
                    "music": "popular"
                },
                {
                    "name": "抖音故事模板",
                    "description": "适合讲述故事的模板",
                    "aspect_ratio": "9:16",
                    "resolution": "1080x1920",
                    "duration": 30,
                    "effects": ["transition_slide", "text_animation"],
                    "music": "emotional"
                }
            ],
            "kuaishou": [
                {
                    "name": "快手潮流模板",
                    "description": "适合快手平台的潮流风格",
                    "aspect_ratio": "9:16",
                    "resolution": "1080x1920",
                    "duration": 15,
                    "effects": ["glitch", "vhs"],
                    "music": "trendy"
                }
            ],
            "xiaohongshu": [
                {
                    "name": "小红书种草模板",
                    "description": "适合小红书种草内容",
                    "aspect_ratio": "1:1",
                    "resolution": "1080x1080",
                    "duration": 60,
                    "effects": ["soft_light", "text_overlay"],
                    "music": "relaxing"
                }
            ]
        }
        
        for platform, templates in default_templates.items():
            platform_dir = os.path.join(template_dir, platform)
            os.makedirs(platform_dir, exist_ok=True)
            for i, template in enumerate(templates):
                template_path = os.path.join(platform_dir, f"template_{i+1}.json")
                with open(template_path, 'w', encoding='utf-8') as f:
                    json.dump(template, f, ensure_ascii=False, indent=2)
    
    def get_platforms(self) -> List[Dict[str, Any]]:
        """获取所有支持的平台"""
        platforms = []
        for name, config in self.PLATFORMS.items():
            platforms.append({
                "name": name,
                "display_name": config.display_name,
                "description": config.description,
                "aspect_ratios": config.aspect_ratios,
                "recommended_resolutions": config.recommended_resolutions
            })
        return platforms
    
    def get_platform_config(self, platform: str) -> Optional[PlatformConfig]:
        """获取平台配置"""
        return self.PLATFORMS.get(platform)
    
    def get_platform_templates(self, platform: str) -> List[Dict]:
        """获取平台模板"""
        return self._templates.get(platform, [])
    
    def validate_video(self, platform: str, video_path: str) -> Dict[str, Any]:
        """验证视频是否符合平台要求"""
        config = self.get_platform_config(platform)
        if not config:
            return {"valid": False, "message": "平台不支持"}
        
        try:
            import cv2
            import os
            
            # 检查文件大小
            file_size = os.path.getsize(video_path)
            if file_size > config.max_size:
                return {"valid": False, "message": f"视频大小超过平台限制 ({config.max_size // (1024 * 1024)}MB)"}
            
            # 检查视频信息
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return {"valid": False, "message": "无法打开视频文件"}
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps
            
            if duration > config.max_duration:
                return {"valid": False, "message": f"视频时长超过平台限制 ({config.max_duration}秒)"}
            
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            # 检查分辨率
            resolution = f"{width}x{height}"
            if resolution not in config.recommended_resolutions:
                return {"valid": True, "message": f"视频分辨率不在推荐列表中，建议使用: {', '.join(config.recommended_resolutions)}"}
            
            cap.release()
            return {"valid": True, "message": "视频符合平台要求"}
            
        except ImportError:
            return {"valid": True, "message": "无法验证视频，缺少必要模块"}
        except Exception as e:
            logger.error(f"验证视频失败: {e}")
            return {"valid": False, "message": f"验证失败: {str(e)}"}
    
    def get_export_settings(self, platform: str) -> Dict[str, Any]:
        """获取平台导出设置"""
        config = self.get_platform_config(platform)
        if not config:
            return {}
        
        return {
            "format": config.video_formats[0],
            "codec": "h264",
            "bitrate": "5M",
            "fps": 30,
            "resolution": config.recommended_resolutions[0],
            "max_duration": config.max_duration,
            "max_size": config.max_size
        }
    
    def generate_platform_metadata(self, platform: str, video_info: Dict[str, Any]) -> Dict[str, Any]:
        """生成平台元数据"""
        metadata = {
            "platform": platform,
            "title": video_info.get("title", ""),
            "description": video_info.get("description", ""),
            "tags": video_info.get("tags", []),
            "category": video_info.get("category", ""),
            "cover_frame": video_info.get("cover_frame", 0)
        }
        
        # 平台特定元数据
        if platform == "douyin":
            metadata["douyin_specific"] = {
                "hashtags": video_info.get("hashtags", []),
                "at_users": video_info.get("at_users", [])
            }
        elif platform == "xiaohongshu":
            metadata["xiaohongshu_specific"] = {
                "topics": video_info.get("topics", []),
                "collection": video_info.get("collection", "")
            }
        
        return metadata


platform_adapter = PlatformAdapter()
