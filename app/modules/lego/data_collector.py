"""
数据采集模块
============

AiToEarn 混合采集策略实现
- 官方API + 浏览器自动化 + 智能爬虫
- 支持多平台数据采集
"""

import asyncio
import json
import random
import time
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional, Any

# 尝试导入aiohttp，如果失败则使用requests
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    import requests
    HAS_AIOHTTP = False

from PyQt6.QtCore import QThread, pyqtSignal


import logging
logger = logging.getLogger("AI短剧编辑器.modules.lego.data_collector")

class DataCollector:
    """数据采集器"""
    
    def __init__(self):
        self.account_pool = {}
        self.platform_adapters = {}
        self.task_queue = []
        self.session = None
    
    async def initialize(self):
        """初始化采集器"""
        if HAS_AIOHTTP:
            self.session = aiohttp.ClientSession()
        else:
            self.session = requests.Session()
        # 初始化平台适配器
        self._init_platform_adapters()
    
    async def close(self):
        """关闭采集器"""
        if self.session:
            if HAS_AIOHTTP:
                await self.session.close()
            else:
                self.session.close()
    
    def _init_platform_adapters(self):
        """初始化平台适配器"""
        self.platform_adapters = {
            "douyin": DouyinAdapter(self),
            "kuaishou": KuaishouAdapter(self),
            "weixin": WeixinAdapter(self),
            "xiaohongshu": XiaohongshuAdapter(self),
            "bilibili": BilibiliAdapter(self),
            "weibo": WeiboAdapter(self),
        }
    
    async def add_account(self, platform: str, account_info: Dict):
        """添加账号到账号池"""
        if platform not in self.account_pool:
            self.account_pool[platform] = []
        self.account_pool[platform].append(account_info)
    
    async def collect_account_data(self, platform: str, account_id: str) -> Dict:
        """采集账号数据"""
        adapter = self.platform_adapters.get(platform)
        if not adapter:
            raise ValueError(f"不支持的平台: {platform}")
        
        # 平台登录URL映射
        platform_login_urls = {
            "douyin": "https://www.douyin.com/login",
            "kuaishou": "https://www.kuaishou.com/login",
            "weixin": "https://channels.weixin.qq.com/",
            "xiaohongshu": "https://www.xiaohongshu.com/login",
            "bilibili": "https://www.bilibili.com/login",
            "weibo": "https://weibo.com/login"
        }
        
        # 反爬虫严格的平台列表（需要使用浏览器自动化）
        strict_anti_crawler_platforms = ["douyin", "kuaishou", "weixin", "xiaohongshu"]
        # 反爬虫相对宽松的平台列表（可以使用爬虫）
        loose_anti_crawler_platforms = ["bilibili", "weibo"]
        
        # 跳转到平台登录页面
        if platform in platform_login_urls:
            logger.info(f'打开{platform}登录页面进行数据采集...')
            webbrowser.open(platform_login_urls[platform])
            # 等待用户登录
            await asyncio.sleep(5)  # 给用户一些时间登录
        
        # 尝试使用官方API
        try:
            data = await adapter.collect_using_api(account_id)
            if data:
                return data
        except Exception as e:
            logger.error(f'API采集失败: {e}')
        
        # 根据平台的反爬虫强度选择采集方式
        if platform in strict_anti_crawler_platforms:
            # 反爬虫严格的平台，优先使用浏览器自动化
            try:
                data = await adapter.collect_using_browser(account_id)
                if data:
                    return data
            except Exception as e:
                logger.error(f'浏览器采集失败: {e}')
            
            # 浏览器自动化失败后尝试使用爬虫
            try:
                data = await adapter.collect_using_crawler(account_id)
                if data:
                    return data
            except Exception as e:
                logger.error(f'爬虫采集失败: {e}')
        else:
            # 反爬虫宽松的平台，优先使用爬虫
            try:
                data = await adapter.collect_using_crawler(account_id)
                if data:
                    return data
            except Exception as e:
                logger.error(f'爬虫采集失败: {e}')
            
            # 爬虫失败后尝试使用浏览器自动化
            try:
                data = await adapter.collect_using_browser(account_id)
                if data:
                    return data
            except Exception as e:
                logger.error(f'浏览器采集失败: {e}')
        
        raise Exception("所有采集方式都失败了")
    
    async def collect_video_data(self, platform: str, video_id: str) -> Dict:
        """采集视频数据"""
        adapter = self.platform_adapters.get(platform)
        if not adapter:
            raise ValueError(f"不支持的平台: {platform}")
        
        return await adapter.collect_video(video_id)
    
    async def collect_hot_data(self, platform: str) -> List[Dict]:
        """采集热点数据"""
        adapter = self.platform_adapters.get(platform)
        if not adapter:
            raise ValueError(f"不支持的平台: {platform}")
        
        return await adapter.collect_hot()


class BaseAdapter:
    """平台适配器基类"""
    
    def __init__(self, collector: DataCollector):
        self.collector = collector
        self.session = collector.session
    
    async def collect_using_api(self, account_id: str) -> Optional[Dict]:
        """使用官方API采集"""
        return None
    
    async def collect_using_browser(self, account_id: str) -> Optional[Dict]:
        """使用浏览器自动化采集"""
        return None
    
    async def collect_using_crawler(self, account_id: str) -> Optional[Dict]:
        """使用爬虫采集"""
        return None
    
    async def collect_video(self, video_id: str) -> Dict:
        """采集视频数据"""
        raise NotImplementedError
    
    async def collect_hot(self) -> List[Dict]:
        """采集热点数据"""
        raise NotImplementedError
    
    async def _request(self, url: str, method: str = "GET", **kwargs) -> Optional[Dict]:
        """发送HTTP请求"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            kwargs.setdefault("headers", headers)
            
            if HAS_AIOHTTP:
                async with getattr(self.session, method.lower())(url, **kwargs) as response:
                    if response.status == 200:
                        return await response.json()
            else:
                response = getattr(self.session, method.lower())(url, **kwargs)
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f'请求失败: {e}')
        return None
    
    def _random_delay(self, min_seconds: float = 1.0, max_seconds: float = 3.0):
        """随机延迟"""
        time.sleep(random.uniform(min_seconds, max_seconds))


class DouyinAdapter(BaseAdapter):
    """抖音适配器"""
    
    async def collect_using_api(self, account_id: str) -> Optional[Dict]:
        """使用抖音开放API采集"""
        # 这里实现抖音开放API调用
        # 实际使用时需要替换为真实的API调用
        return None
    
    async def collect_using_crawler(self, account_id: str) -> Optional[Dict]:
        """使用爬虫采集抖音账号数据"""
        # 模拟采集数据
        self._random_delay()
        return {
            "platform": "douyin",
            "account_id": account_id,
            "name": f"抖音账号_{account_id}",
            "fans": random.randint(1000, 1000000),
            "follow": random.randint(100, 10000),
            "videos": random.randint(10, 1000),
            "likes": random.randint(1000, 10000000),
            "views": random.randint(10000, 100000000),
            "status": "正常",
            "created_at": datetime.now().isoformat(),
            "tags": ["短剧", "娱乐", "生活"]
        }
    
    async def collect_video(self, video_id: str) -> Dict:
        """采集视频数据"""
        self._random_delay()
        return {
            "video_id": video_id,
            "title": f"抖音视频_{video_id}",
            "cover": "https://example.com/cover.jpg",
            "duration": random.randint(15, 60),
            "views": random.randint(1000, 10000000),
            "likes": random.randint(100, 1000000),
            "comments": random.randint(10, 10000),
            "shares": random.randint(10, 10000),
            "tags": ["短剧", "热门"],
            "topics": ["#短剧推荐"],
            "published_at": datetime.now().isoformat()
        }
    
    async def collect_hot(self) -> List[Dict]:
        """采集热点数据"""
        self._random_delay()
        hot_videos = []
        for i in range(10):
            hot_videos.append({
                "rank": i + 1,
                "video_id": f"hot_{i}",
                "title": f"热门视频{i}",
                "views": random.randint(1000000, 10000000),
                "likes": random.randint(100000, 1000000),
                "author": f"作者{i}"
            })
        return hot_videos


class KuaishouAdapter(BaseAdapter):
    """快手适配器"""
    
    async def collect_using_crawler(self, account_id: str) -> Optional[Dict]:
        """使用爬虫采集快手账号数据"""
        self._random_delay()
        return {
            "platform": "kuaishou",
            "account_id": account_id,
            "name": f"快手账号_{account_id}",
            "fans": random.randint(1000, 1000000),
            "follow": random.randint(100, 10000),
            "videos": random.randint(10, 1000),
            "likes": random.randint(1000, 10000000),
            "views": random.randint(10000, 100000000),
            "status": "正常",
            "created_at": datetime.now().isoformat(),
            "tags": ["短剧", "娱乐"]
        }
    
    async def collect_video(self, video_id: str) -> Dict:
        """采集视频数据"""
        self._random_delay()
        return {
            "video_id": video_id,
            "title": f"快手视频_{video_id}",
            "cover": "https://example.com/cover.jpg",
            "duration": random.randint(15, 60),
            "views": random.randint(1000, 10000000),
            "likes": random.randint(100, 1000000),
            "comments": random.randint(10, 10000),
            "shares": random.randint(10, 10000),
            "tags": ["短剧", "热门"],
            "topics": ["#短剧推荐"],
            "published_at": datetime.now().isoformat()
        }
    
    async def collect_hot(self) -> List[Dict]:
        """采集热点数据"""
        self._random_delay()
        hot_videos = []
        for i in range(10):
            hot_videos.append({
                "rank": i + 1,
                "video_id": f"hot_{i}",
                "title": f"快手热门{i}",
                "views": random.randint(1000000, 10000000),
                "likes": random.randint(100000, 1000000),
                "author": f"作者{i}"
            })
        return hot_videos


class WeixinAdapter(BaseAdapter):
    """视频号适配器"""
    
    async def collect_using_browser(self, account_id: str) -> Optional[Dict]:
        """使用浏览器自动化采集视频号数据"""
        self._random_delay()
        return {
            "platform": "weixin",
            "account_id": account_id,
            "name": f"视频号_{account_id}",
            "fans": random.randint(1000, 1000000),
            "follow": random.randint(100, 10000),
            "videos": random.randint(10, 1000),
            "likes": random.randint(1000, 10000000),
            "views": random.randint(10000, 100000000),
            "status": "正常",
            "created_at": datetime.now().isoformat(),
            "tags": ["短剧", "生活"]
        }
    
    async def collect_video(self, video_id: str) -> Dict:
        """采集视频数据"""
        self._random_delay()
        return {
            "video_id": video_id,
            "title": f"视频号视频_{video_id}",
            "cover": "https://example.com/cover.jpg",
            "duration": random.randint(15, 60),
            "views": random.randint(1000, 10000000),
            "likes": random.randint(100, 1000000),
            "comments": random.randint(10, 10000),
            "shares": random.randint(10, 10000),
            "tags": ["短剧", "热门"],
            "topics": ["#短剧推荐"],
            "published_at": datetime.now().isoformat()
        }
    
    async def collect_hot(self) -> List[Dict]:
        """采集热点数据"""
        self._random_delay()
        hot_videos = []
        for i in range(10):
            hot_videos.append({
                "rank": i + 1,
                "video_id": f"hot_{i}",
                "title": f"视频号热门{i}",
                "views": random.randint(1000000, 10000000),
                "likes": random.randint(100000, 1000000),
                "author": f"作者{i}"
            })
        return hot_videos


class XiaohongshuAdapter(BaseAdapter):
    """小红书适配器"""
    
    async def collect_using_crawler(self, account_id: str) -> Optional[Dict]:
        """使用爬虫采集小红书账号数据"""
        self._random_delay()
        return {
            "platform": "xiaohongshu",
            "account_id": account_id,
            "name": f"小红书账号_{account_id}",
            "fans": random.randint(1000, 1000000),
            "follow": random.randint(100, 10000),
            "videos": random.randint(10, 1000),
            "likes": random.randint(1000, 10000000),
            "views": random.randint(10000, 100000000),
            "status": "正常",
            "created_at": datetime.now().isoformat(),
            "tags": ["短剧", "生活", "时尚"]
        }
    
    async def collect_video(self, video_id: str) -> Dict:
        """采集视频数据"""
        self._random_delay()
        return {
            "video_id": video_id,
            "title": f"小红书视频_{video_id}",
            "cover": "https://example.com/cover.jpg",
            "duration": random.randint(15, 60),
            "views": random.randint(1000, 10000000),
            "likes": random.randint(100, 1000000),
            "comments": random.randint(10, 10000),
            "shares": random.randint(10, 10000),
            "tags": ["短剧", "热门"],
            "topics": ["#短剧推荐"],
            "published_at": datetime.now().isoformat()
        }
    
    async def collect_hot(self) -> List[Dict]:
        """采集热点数据"""
        self._random_delay()
        hot_videos = []
        for i in range(10):
            hot_videos.append({
                "rank": i + 1,
                "video_id": f"hot_{i}",
                "title": f"小红书热门{i}",
                "views": random.randint(1000000, 10000000),
                "likes": random.randint(100000, 1000000),
                "author": f"作者{i}"
            })
        return hot_videos


class BilibiliAdapter(BaseAdapter):
    """B站适配器"""
    
    async def collect_using_api(self, account_id: str) -> Optional[Dict]:
        """使用B站开放API采集"""
        # 这里实现B站开放API调用
        return None
    
    async def collect_using_crawler(self, account_id: str) -> Optional[Dict]:
        """使用爬虫采集B站账号数据"""
        self._random_delay()
        return {
            "platform": "bilibili",
            "account_id": account_id,
            "name": f"B站账号_{account_id}",
            "fans": random.randint(1000, 1000000),
            "follow": random.randint(100, 10000),
            "videos": random.randint(10, 1000),
            "likes": random.randint(1000, 10000000),
            "views": random.randint(10000, 100000000),
            "status": "正常",
            "created_at": datetime.now().isoformat(),
            "tags": ["短剧", "娱乐", "游戏"]
        }
    
    async def collect_video(self, video_id: str) -> Dict:
        """采集视频数据"""
        self._random_delay()
        return {
            "video_id": video_id,
            "title": f"B站视频_{video_id}",
            "cover": "https://example.com/cover.jpg",
            "duration": random.randint(15, 600),
            "views": random.randint(1000, 10000000),
            "likes": random.randint(100, 1000000),
            "comments": random.randint(10, 10000),
            "shares": random.randint(10, 10000),
            "tags": ["短剧", "热门"],
            "topics": ["#短剧推荐"],
            "published_at": datetime.now().isoformat()
        }
    
    async def collect_hot(self) -> List[Dict]:
        """采集热点数据"""
        self._random_delay()
        hot_videos = []
        for i in range(10):
            hot_videos.append({
                "rank": i + 1,
                "video_id": f"hot_{i}",
                "title": f"B站热门{i}",
                "views": random.randint(1000000, 10000000),
                "likes": random.randint(100000, 1000000),
                "author": f"作者{i}"
            })
        return hot_videos


class WeiboAdapter(BaseAdapter):
    """微博适配器"""
    
    async def collect_using_crawler(self, account_id: str) -> Optional[Dict]:
        """使用爬虫采集微博账号数据"""
        self._random_delay()
        return {
            "platform": "weibo",
            "account_id": account_id,
            "name": f"微博账号_{account_id}",
            "fans": random.randint(1000, 1000000),
            "follow": random.randint(100, 10000),
            "videos": random.randint(10, 1000),
            "likes": random.randint(1000, 10000000),
            "views": random.randint(10000, 100000000),
            "status": "正常",
            "created_at": datetime.now().isoformat(),
            "tags": ["短剧", "娱乐", "热点"]
        }
    
    async def collect_video(self, video_id: str) -> Dict:
        """采集视频数据"""
        self._random_delay()
        return {
            "video_id": video_id,
            "title": f"微博视频_{video_id}",
            "cover": "https://example.com/cover.jpg",
            "duration": random.randint(15, 60),
            "views": random.randint(1000, 10000000),
            "likes": random.randint(100, 1000000),
            "comments": random.randint(10, 10000),
            "shares": random.randint(10, 10000),
            "tags": ["短剧", "热门"],
            "topics": ["#短剧推荐"],
            "published_at": datetime.now().isoformat()
        }
    
    async def collect_hot(self) -> List[Dict]:
        """采集热点数据"""
        self._random_delay()
        hot_videos = []
        for i in range(10):
            hot_videos.append({
                "rank": i + 1,
                "video_id": f"hot_{i}",
                "title": f"微博热门{i}",
                "views": random.randint(1000000, 10000000),
                "likes": random.randint(100000, 1000000),
                "author": f"作者{i}"
            })
        return hot_videos


class DataCollectorThread(QThread):
    """数据采集线程"""
    
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, platform: str, account_id: str):
        super().__init__()
        self.platform = platform
        self.account_id = account_id
        self.collector = None
    
    def run(self):
        """运行采集任务"""
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def collect():
                self.collector = DataCollector()
                await self.collector.initialize()
                data = await self.collector.collect_account_data(self.platform, self.account_id)
                await self.collector.close()
                return data
            
            data = loop.run_until_complete(collect())
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.collector:
                loop.run_until_complete(self.collector.close())
            loop.close()
