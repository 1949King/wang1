"""平台集成模块"""

import os
import json
import time
from datetime import datetime, timedelta
from modules.utils.logger import logger

class PlatformIntegrator:
    """平台集成器"""
    
    def __init__(self, credentials_path=None):
        """初始化平台集成器
        
        Args:
            credentials_path: 平台凭证配置文件路径
        """
        self.credentials_path = credentials_path or os.path.join(os.path.dirname(__file__), "..", "..", "config", "platform_credentials.json")
        self.credentials = self._load_credentials()
        self.platforms = {
            "douyin": self._get_douyin_client,
            "bilibili": self._get_bilibili_client,
            "youtube": self._get_youtube_client
        }
    
    def _load_credentials(self):
        """加载平台凭证"""
        if os.path.exists(self.credentials_path):
            try:
                with open(self.credentials_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载平台凭证失败: {e}")
                return {}
        return {}
    
    def _save_credentials(self):
        """保存平台凭证"""
        try:
            os.makedirs(os.path.dirname(self.credentials_path), exist_ok=True)
            with open(self.credentials_path, "w", encoding="utf-8") as f:
                json.dump(self.credentials, f, ensure_ascii=False, indent=2)
            logger.info(f"平台凭证保存成功: {self.credentials_path}")
            return True
        except Exception as e:
            logger.error(f"保存平台凭证失败: {e}")
            return False
    
    def _get_douyin_client(self):
        """获取抖音客户端"""
        # 这里应该实现抖音API客户端的初始化
        # 由于抖音API需要真实的App Key和App Secret，这里只是示例
        if "douyin" in self.credentials:
            logger.info("初始化抖音客户端")
            return {"platform": "douyin", "connected": True}
        return {"platform": "douyin", "connected": False}
    
    def _get_bilibili_client(self):
        """获取B站客户端"""
        # 这里应该实现B站API客户端的初始化
        if "bilibili" in self.credentials:
            logger.info("初始化B站客户端")
            return {"platform": "bilibili", "connected": True}
        return {"platform": "bilibili", "connected": False}
    
    def _get_youtube_client(self):
        """获取YouTube客户端"""
        # 这里应该实现YouTube API客户端的初始化
        if "youtube" in self.credentials:
            logger.info("初始化YouTube客户端")
            return {"platform": "youtube", "connected": True}
        return {"platform": "youtube", "connected": False}
    
    def get_platform_client(self, platform):
        """获取平台客户端
        
        Args:
            platform: 平台名称，支持 "douyin", "bilibili", "youtube"
        """
        if platform in self.platforms:
            return self.platforms[platform]()
        logger.error(f"不支持的平台: {platform}")
        return None
    
    def update_credentials(self, platform, credentials):
        """更新平台凭证
        
        Args:
            platform: 平台名称
            credentials: 凭证信息
        """
        self.credentials[platform] = credentials
        return self._save_credentials()
    
    def publish_to_platform(self, platform, video_path, title, description, tags=None, scheduled_time=None):
        """发布视频到平台
        
        Args:
            platform: 平台名称
            video_path: 视频路径
            title: 视频标题
            description: 视频描述
            tags: 视频标签
            scheduled_time: 定时发布时间
        """
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return False
        
        client = self.get_platform_client(platform)
        if not client or not client.get("connected"):
            logger.error(f"{platform} 客户端未连接")
            return False
        
        # 模拟发布过程
        logger.info(f"开始发布视频到 {platform}")
        logger.info(f"视频路径: {video_path}")
        logger.info(f"标题: {title}")
        logger.info(f"描述: {description}")
        logger.info(f"标签: {tags}")
        logger.info(f"定时发布: {scheduled_time}")
        
        # 模拟上传延迟
        time.sleep(2)
        
        if scheduled_time:
            logger.info(f"视频已安排在 {scheduled_time} 发布到 {platform}")
        else:
            logger.info(f"视频已成功发布到 {platform}")
        
        return True
    
    def publish_to_multiple_platforms(self, platforms, video_path, title, description, tags=None, scheduled_time=None):
        """发布视频到多个平台
        
        Args:
            platforms: 平台列表
            video_path: 视频路径
            title: 视频标题
            description: 视频描述
            tags: 视频标签
            scheduled_time: 定时发布时间
        """
        results = {}
        for platform in platforms:
            success = self.publish_to_platform(platform, video_path, title, description, tags, scheduled_time)
            results[platform] = success
        
        logger.info(f"多平台发布结果: {results}")
        return results
    
    def get_platform_specific_tags(self, platform, video_content=None):
        """获取平台特定标签
        
        Args:
            platform: 平台名称
            video_content: 视频内容描述
        """
        # 这里应该根据平台特性和视频内容生成推荐标签
        platform_tags = {
            "douyin": ["热门", "创意", "剧情", "搞笑", "短剧"],
            "bilibili": ["原创", "剧情", "短剧", "UP主", "影视剪辑"],
            "youtube": ["Short Drama", "Original", "Story", "Creative", "Entertainment"]
        }
        
        return platform_tags.get(platform, [])
    
    def get_platform_specific_description(self, platform, original_description):
        """获取平台特定描述
        
        Args:
            platform: 平台名称
            original_description: 原始描述
        """
        # 这里应该根据平台特性调整描述
        platform_prefixes = {
            "douyin": "#抖音短剧 #热门",
            "bilibili": "【原创短剧】",
            "youtube": "[Short Drama]"
        }
        
        prefix = platform_prefixes.get(platform, "")
        if prefix:
            return f"{prefix} {original_description}"
        return original_description
    
    def export_and_publish(self, video_path, output_format="mp4", platforms=None, title=None, description=None, tags=None, scheduled_time=None):
        """导出并发布视频
        
        Args:
            video_path: 视频路径
            output_format: 输出格式
            platforms: 目标平台列表
            title: 视频标题
            description: 视频描述
            tags: 视频标签
            scheduled_time: 定时发布时间
        """
        if not platforms:
            logger.error("未指定目标平台")
            return False
        
        # 这里可以添加视频格式转换逻辑
        # 现在直接使用原始视频
        
        results = {}
        for platform in platforms:
            # 获取平台特定的标签和描述
            platform_tags = tags or self.get_platform_specific_tags(platform)
            platform_description = description or self.get_platform_specific_description(platform, "")
            
            success = self.publish_to_platform(platform, video_path, title, platform_description, platform_tags, scheduled_time)
            results[platform] = success
        
        logger.info(f"导出并发布结果: {results}")
        return all(results.values())
    
    def get_supported_platforms(self):
        """获取支持的平台列表"""
        return list(self.platforms.keys())
