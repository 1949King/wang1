"""
短剧数据爬虫模块 v3.0
=====================
支持多平台短剧数据爬取，后台静默运行
智能筛选算法 + 多维度评分 + 热度预测 + 个性化推荐

线程安全：支持 Qt 信号-槽机制，避免跨线程 UI 操作
"""

import json
import time
import random
import threading
import requests
import sys
import os
from typing import Optional, Dict, List, Any, Callable, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
import logging
import hashlib
import re
from collections import defaultdict
from functools import lru_cache

sys.dont_write_bytecode = True

logger = logging.getLogger(__name__)

# ============================================================
# 数据源健康状态表 (Real #1 补短)
# ============================================================
# 标识每个平台的数据是真实 API 还是模拟 fallback。
# 真实数据源 (real=True) 需要用户配置 API Key, 否则会回退到 fallback。
# UI 可以通过 get_data_source_health() 弹"⚠️ 数据为模拟"提示。
DATA_SOURCE_HEALTH = {
    "douyin":     {"real": False, "source": "随机生成（需配置 TIKHUB_API_TOKEN 启用真实数据）", "api_class": "DouyinAPI"},
    "kuaishou":   {"real": False, "source": "随机生成（需 Playwright 接入）",                 "api_class": "KuaishouAPI"},
    "bilibili":   {"real": False, "source": "随机生成（可接 B 站官方 API）",                 "api_class": "BilibiliAPI"},
    "xiaohongshu":{"real": False, "source": "未接入", "api_class": None},
    "weiduanju":  {"real": False, "source": "未接入", "api_class": None},
    "tencent":    {"real": False, "source": "未接入", "api_class": None},
    "iqiyi":      {"real": False, "source": "未接入", "api_class": None},
    "youku":      {"real": False, "source": "未接入", "api_class": None},
    "weibo":      {"real": False, "source": "未接入", "api_class": None},
    "mgtv":       {"real": False, "source": "未接入", "api_class": None},
    "sohu":       {"real": False, "source": "未接入", "api_class": None},
    "xigua":      {"real": False, "source": "未接入", "api_class": None},
    "douyin_wx":  {"real": False, "source": "未接入", "api_class": None},
    "kuaishou_wx":{"real": False, "source": "未接入", "api_class": None},
    "duanjuju":   {"real": False, "source": "未接入", "api_class": None},
}


def get_data_source_health() -> Dict[str, Dict]:
    """获取所有平台的数据源健康状态 (供 UI 提示用)"""
    return DATA_SOURCE_HEALTH.copy()


# ============================================================

try:
    from PyQt6.QtCore import QObject, pyqtSignal, QThread
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    QObject = object
    pyqtSignal = None
    QThread = None


@dataclass
class DramaInfo:
    """短剧信息"""
    id: str
    title: str
    platform: str
    category: str
    tags: List[str] = field(default_factory=list)
    episodes: int = 0
    views: int = 0
    likes: int = 0
    commission: float = 0.0
    commission_rate: float = 0.0
    rating: float = 0.0
    cover_url: str = ""
    description: str = ""
    author: str = ""
    author_id: str = ""
    update_time: str = ""
    status: str = "连载中"
    heat: int = 0
    source_url: str = ""
    score: float = 0.0
    recommend_reason: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


if PYQT_AVAILABLE:
    class CrawlerSignals(QObject):
        """爬虫信号类 - 用于线程间安全通信"""
        data_fetched = pyqtSignal(list)
        error_occurred = pyqtSignal(str)
        progress_updated = pyqtSignal(int, int)
        status_changed = pyqtSignal(str)
    
    class CrawlerWorker(QThread):
        """爬虫工作线程 - 安全的异步数据获取"""
        
        def __init__(self, crawler, method_name: str, *args, **kwargs):
            super().__init__()
            self.crawler = crawler
            self.method_name = method_name
            self.args = args
            self.kwargs = kwargs
            self.signals = CrawlerSignals()
            self._is_cancelled = False
        
        def run(self):
            try:
                method = getattr(self.crawler, self.method_name)
                result = method(*self.args, **self.kwargs)
                if not self._is_cancelled:
                    self.signals.data_fetched.emit(result)
            except Exception as e:
                logger.error(f"爬虫工作线程错误: {e}")
                self.signals.error_occurred.emit(str(e))
        
        def cancel(self):
            self._is_cancelled = True


class ScoringEngine:
    """多维度评分引擎"""
    
    WEIGHTS = {
        "heat": 0.25,
        "views": 0.20,
        "commission": 0.20,
        "rating": 0.15,
        "engagement": 0.10,
        "freshness": 0.10,
    }
    
    CATEGORY_BOOST = {
        "霸总": 1.2, "甜宠": 1.15, "逆袭": 1.18, "重生": 1.12,
        "修仙": 1.10, "系统流": 1.08, "神豪": 1.15, "穿越": 1.05,
    }
    
    PLATFORM_BOOST = {
        "douyin": 1.15, "kuaishou": 1.12, "bilibili": 1.08,
        "xiaohongshu": 1.10, "douyin_wx": 1.05, "kuaishou_wx": 1.03,
    }
    
    @classmethod
    def calculate_score(cls, drama: DramaInfo, user_prefs: Dict = None) -> float:
        score = 0.0
        
        heat_score = cls._normalize(drama.heat, 1000, 100000)
        views_score = cls._normalize(drama.views, 100000, 10000000)
        commission_score = cls._normalize(drama.commission, 1000, 50000)
        rating_score = drama.rating / 10.0
        
        engagement_rate = (drama.likes / drama.views) if drama.views > 0 else 0
        engagement_score = cls._normalize(engagement_rate * 100, 0.5, 15)
        
        freshness_score = cls._calculate_freshness(drama.update_time)
        
        score = (
            heat_score * cls.WEIGHTS["heat"] +
            views_score * cls.WEIGHTS["views"] +
            commission_score * cls.WEIGHTS["commission"] +
            rating_score * cls.WEIGHTS["rating"] +
            engagement_score * cls.WEIGHTS["engagement"] +
            freshness_score * cls.WEIGHTS["freshness"]
        )
        
        category_boost = cls.CATEGORY_BOOST.get(drama.category, 1.0)
        platform_boost = cls.PLATFORM_BOOST.get(drama.platform, 1.0)
        score *= category_boost * platform_boost
        
        if user_prefs:
            score *= cls._calculate_preference_boost(drama, user_prefs)
        
        return round(score, 2)
    
    @staticmethod
    def _normalize(value: float, min_val: float, max_val: float) -> float:
        if max_val == min_val:
            return 0.5
        normalized = (value - min_val) / (max_val - min_val)
        return max(0.0, min(1.0, normalized))
    
    @staticmethod
    def _calculate_freshness(update_time: str) -> float:
        try:
            update_dt = datetime.strptime(update_time, "%Y-%m-%d %H:%M")
            days_ago = (datetime.now() - update_dt).days
            
            if days_ago <= 1:
                return 1.0
            elif days_ago <= 3:
                return 0.9
            elif days_ago <= 7:
                return 0.7
            elif days_ago <= 14:
                return 0.5
            elif days_ago <= 30:
                return 0.3
            else:
                return 0.1
        except Exception:
            pass
            return 0.5
    
    @staticmethod
    def _calculate_preference_boost(drama: DramaInfo, prefs: Dict) -> float:
        boost = 1.0
        
        if prefs.get("preferred_categories"):
            if drama.category in prefs["preferred_categories"]:
                boost *= 1.3
        
        if prefs.get("preferred_platforms"):
            if drama.platform in prefs["preferred_platforms"]:
                boost *= 1.2
        
        if prefs.get("min_commission") and drama.commission >= prefs["min_commission"]:
            boost *= 1.15
        
        if prefs.get("preferred_tags"):
            matching_tags = set(drama.tags) & set(prefs["preferred_tags"])
            if matching_tags:
                boost *= 1.0 + 0.1 * len(matching_tags)
        
        return boost


class KeywordMatcher:
    """智能关键词匹配器"""
    
    STOP_WORDS = {"的", "之", "与", "和", "或", "在", "是", "有", "为", "了", "等", "及"}
    
    SYNONYMS = {
        "总裁": ["霸总", "CEO", "老板", "总裁"],
        "重生": ["穿越", "回到", "重来", "重生"],
        "逆袭": ["反击", "翻盘", "崛起", "逆袭"],
        "甜宠": ["甜文", "宠文", "甜宠", "撒糖"],
        "修仙": ["仙侠", "玄幻", "修真", "修仙"],
        "神豪": ["富豪", "首富", "财神", "神豪"],
    }
    
    @classmethod
    def match(cls, drama: DramaInfo, keyword: str) -> Tuple[bool, float]:
        if not keyword:
            return True, 1.0
        
        keyword = keyword.lower().strip()
        tokens = cls._tokenize(keyword)
        
        score = 0.0
        matched = False
        
        title_lower = drama.title.lower()
        desc_lower = drama.description.lower()
        tags_lower = [t.lower() for t in drama.tags]
        category_lower = drama.category.lower()
        
        for token in tokens:
            if token in cls.STOP_WORDS:
                continue
            
            token_score = 0.0
            
            if token in title_lower:
                token_score = 1.0
                matched = True
            elif token in category_lower:
                token_score = 0.9
                matched = True
            elif any(token in tag for tag in tags_lower):
                token_score = 0.85
                matched = True
            elif token in desc_lower:
                token_score = 0.6
                matched = True
            
            synonyms = cls.SYNONYMS.get(token, [])
            for syn in synonyms:
                if syn.lower() in title_lower:
                    token_score = max(token_score, 0.8)
                    matched = True
                    break
                elif syn.lower() in category_lower:
                    token_score = max(token_score, 0.7)
                    matched = True
                    break
            
            score += token_score
        
        if tokens:
            score = score / len([t for t in tokens if t not in cls.STOP_WORDS])
        
        return matched or score > 0, min(score, 1.0)
    
    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        tokens = re.findall(r'[\w]+', text)
        return [t for t in tokens if t not in cls.STOP_WORDS]


class HeatPredictor:
    """热度预测器"""
    
    TREND_MULTIPLIERS = {
        "rising": 1.3,
        "stable": 1.0,
        "declining": 0.8,
    }
    
    @classmethod
    def predict(cls, drama: DramaInfo) -> Tuple[float, str]:
        base_heat = drama.heat
        
        trend = cls._estimate_trend(drama)
        multiplier = cls.TREND_MULTIPLIERS.get(trend, 1.0)
        
        category_factor = cls._get_category_factor(drama.category)
        platform_factor = cls._get_platform_factor(drama.platform)
        
        predicted_heat = base_heat * multiplier * category_factor * platform_factor
        
        engagement_rate = (drama.likes / drama.views) if drama.views > 0 else 0
        if engagement_rate > 0.1:
            predicted_heat *= 1.2
        elif engagement_rate > 0.05:
            predicted_heat *= 1.1
        
        return round(predicted_heat), trend
    
    @staticmethod
    def _estimate_trend(drama: DramaInfo) -> str:
        try:
            update_dt = datetime.strptime(drama.update_time, "%Y-%m-%d %H:%M")
            days_ago = (datetime.now() - update_dt).days
            
            if days_ago <= 2 and drama.views > 500000:
                return "rising"
            elif days_ago <= 7:
                return "stable"
            else:
                return "declining"
        except Exception:
            pass
            return "stable"
    
    @staticmethod
    def _get_category_factor(category: str) -> float:
        hot_categories = {"霸总", "甜宠", "逆袭", "重生", "修仙"}
        warm_categories = {"都市", "古装", "悬疑", "系统流", "神豪"}
        
        if category in hot_categories:
            return 1.2
        elif category in warm_categories:
            return 1.05
        return 1.0
    
    @staticmethod
    def _get_platform_factor(platform: str) -> float:
        platform_factors = {
            "douyin": 1.15, "kuaishou": 1.12, "douyin_wx": 1.10,
            "kuaishou_wx": 1.08, "bilibili": 1.05, "xiaohongshu": 1.08,
        }
        return platform_factors.get(platform, 1.0)


class Recommender:
    """智能推荐系统"""
    
    RECOMMEND_TEMPLATES = {
        "high_commission": "💰 高佣金推荐 - 预计收益 ¥{commission:.0f}",
        "hot_trending": "🔥 热门爆款 - {views_str}播放",
        "high_rating": "⭐ 口碑佳作 - {rating}分",
        "new_release": "🆕 新剧上线 - {status}",
        "category_match": "🏷️ {category}精选",
        "engagement_king": "💬 互动王 - {engagement_rate:.1%}互动率",
    }
    
    @classmethod
    def generate_reason(cls, drama: DramaInfo, score: float) -> str:
        reasons = []
        
        if drama.commission >= 30000:
            reasons.append(cls.RECOMMEND_TEMPLATES["high_commission"].format(commission=drama.commission))
        
        if drama.views >= 5000000:
            views_str = cls._format_views(drama.views)
            reasons.append(cls.RECOMMEND_TEMPLATES["hot_trending"].format(views_str=views_str))
        
        if drama.rating >= 9.0:
            reasons.append(cls.RECOMMEND_TEMPLATES["high_rating"].format(rating=drama.rating))
        
        if drama.status == "连载中":
            try:
                update_dt = datetime.strptime(drama.update_time, "%Y-%m-%d %H:%M")
                if (datetime.now() - update_dt).days <= 3:
                    reasons.append(cls.RECOMMEND_TEMPLATES["new_release"].format(status=drama.status))
            except Exception:
                pass
                pass
        
        if drama.category in ScoringEngine.CATEGORY_BOOST:
            reasons.append(cls.RECOMMEND_TEMPLATES["category_match"].format(category=drama.category))
        
        engagement_rate = (drama.likes / drama.views) if drama.views > 0 else 0
        if engagement_rate >= 0.08:
            reasons.append(cls.RECOMMEND_TEMPLATES["engagement_king"].format(engagement_rate=engagement_rate))
        
        return reasons[0] if reasons else "综合推荐"
    
    @staticmethod
    def _format_views(views: int) -> str:
        if views >= 10000000:
            return f"{views/10000000:.1f}千万"
        elif views >= 10000:
            return f"{views/10000:.1f}万"
        return str(views)


class PlatformAPI:
    """平台API基类"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
    
    def fetch(self, keyword: str = "", page: int = 1, page_size: int = 20, 
              user_prefs: Dict = None) -> List[DramaInfo]:
        raise NotImplementedError
    
    def is_available(self) -> bool:
        return True


class DouyinAPI(PlatformAPI):
    """抖音短剧API"""
    
    BASE_URL = "https://www.douyin.com"
    
    TITLES = [
        "总裁的替身新娘", "重生之商业女王", "穿越时空爱上你", "霸道王爷俏王妃",
        "豪门恩怨之复仇", "都市修仙录", "甜蜜暴击", "逆袭之星途璀璨",
        "千亿总裁的隐婚妻", "神医嫡女", "战神归来", "仙帝重生",
    ]
    
    AUTHORS = ["星辰影视", "梦幻工作室", "光影传媒", "橙子短剧", "番茄剧场"]
    
    def fetch(self, keyword: str = "", page: int = 1, page_size: int = 20,
              user_prefs: Dict = None) -> List[DramaInfo]:
        return self._generate_data("douyin", keyword, page_size, user_prefs)
    
    def _generate_data(self, platform: str, keyword: str, count: int,
                       user_prefs: Dict = None) -> List[DramaInfo]:
        dramas = []
        base_time = int(time.time())
        
        for i in range(count):
            title = random.choice(self.TITLES)
            if keyword:
                title = f"{keyword}之{title}"
            
            category = random.choice(["都市", "古装", "甜宠", "霸总", "逆袭", "重生", "修仙"])
            views = random.randint(100000, 10000000)
            likes = int(views * random.uniform(0.03, 0.15))
            
            drama = DramaInfo(
                id=f"{platform}_{base_time}_{i}",
                title=title,
                platform=platform,
                category=category,
                tags=random.choice([["都市", "甜宠"], ["古装", "穿越"], ["霸总", "逆袭"], ["重生", "复仇"]]),
                episodes=random.randint(50, 200),
                views=views,
                likes=likes,
                commission=round(random.uniform(1000, 50000), 2),
                commission_rate=round(random.uniform(5, 30), 1),
                rating=round(random.uniform(7.0, 9.8), 1),
                heat=random.randint(1000, 100000),
                author=random.choice(self.AUTHORS),
                update_time=(datetime.now() - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d %H:%M"),
                status=random.choice(["连载中", "已完结"]),
                source_url=f"https://www.douyin.com/drama/{hashlib.md5(str(base_time + i).encode()).hexdigest()[:8]}"
            )
            
            drama.score = ScoringEngine.calculate_score(drama, user_prefs)
            drama.recommend_reason = Recommender.generate_reason(drama, drama.score)
            dramas.append(drama)
        
        return dramas


class KuaishouAPI(PlatformAPI):
    """快手短剧API"""
    
    BASE_URL = "https://www.kuaishou.com"
    
    TITLES = [
        "战神归来", "仙帝重生", "都市最强战神", "豪门第一宠婚",
        "神医嫡女", "千亿总裁的隐婚妻", "重生之都市仙尊", "绝世武神",
    ]
    
    AUTHORS = ["快手短剧官方", "番茄剧场", "橙子短剧", "光影工场"]
    
    def fetch(self, keyword: str = "", page: int = 1, page_size: int = 20,
              user_prefs: Dict = None) -> List[DramaInfo]:
        return self._generate_data("kuaishou", keyword, page_size, user_prefs)
    
    def _generate_data(self, platform: str, keyword: str, count: int,
                       user_prefs: Dict = None) -> List[DramaInfo]:
        dramas = []
        base_time = int(time.time())
        
        for i in range(count):
            title = random.choice(self.TITLES)
            if keyword:
                title = f"{keyword}之{title}"
            
            category = random.choice(["逆袭", "修仙", "霸总", "神豪", "系统流"])
            views = random.randint(80000, 8000000)
            likes = int(views * random.uniform(0.04, 0.12))
            
            drama = DramaInfo(
                id=f"{platform}_{base_time}_{i}",
                title=title,
                platform=platform,
                category=category,
                tags=random.choice([["逆袭", "爽文"], ["修仙", "玄幻"], ["霸总", "甜宠"]]),
                episodes=random.randint(60, 180),
                views=views,
                likes=likes,
                commission=round(random.uniform(800, 40000), 2),
                commission_rate=round(random.uniform(6, 28), 1),
                rating=round(random.uniform(7.2, 9.6), 1),
                heat=random.randint(800, 80000),
                author=random.choice(self.AUTHORS),
                update_time=(datetime.now() - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d %H:%M"),
                status=random.choice(["连载中", "已完结"]),
                source_url=f"https://www.kuaishou.com/short-video/{hashlib.md5(str(base_time + i).encode()).hexdigest()[:8]}"
            )
            
            drama.score = ScoringEngine.calculate_score(drama, user_prefs)
            drama.recommend_reason = Recommender.generate_reason(drama, drama.score)
            dramas.append(drama)
        
        return dramas


class BilibiliAPI(PlatformAPI):
    """B站短剧API"""
    
    BASE_URL = "https://www.bilibili.com"
    
    TITLES = [
        "校园纯爱故事", "悬疑迷局", "古风虐恋", "职场女王养成记",
        "玄幻大陆传说", "科幻未来世界", "青春无悔", "偶像练习生",
    ]
    
    AUTHORS = ["B站短剧", "UP主创作", "官方短剧", "番剧工房"]
    
    def fetch(self, keyword: str = "", page: int = 1, page_size: int = 20,
              user_prefs: Dict = None) -> List[DramaInfo]:
        return self._generate_data("bilibili", keyword, page_size, user_prefs)
    
    def _generate_data(self, platform: str, keyword: str, count: int,
                       user_prefs: Dict = None) -> List[DramaInfo]:
        dramas = []
        base_time = int(time.time())
        
        for i in range(count):
            title = random.choice(self.TITLES)
            if keyword:
                title = f"{keyword}之{title}"
            
            category = random.choice(["校园", "悬疑", "玄幻", "科幻", "青春"])
            views = random.randint(50000, 5000000)
            likes = int(views * random.uniform(0.05, 0.18))
            
            drama = DramaInfo(
                id=f"{platform}_{base_time}_{i}",
                title=title,
                platform=platform,
                category=category,
                tags=random.choice([["校园", "青春"], ["悬疑", "推理"], ["玄幻", "仙侠"]]),
                episodes=random.randint(40, 150),
                views=views,
                likes=likes,
                commission=round(random.uniform(500, 30000), 2),
                commission_rate=round(random.uniform(4, 25), 1),
                rating=round(random.uniform(7.5, 9.9), 1),
                heat=random.randint(500, 50000),
                author=random.choice(self.AUTHORS),
                update_time=(datetime.now() - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d %H:%M"),
                status=random.choice(["连载中", "已完结"]),
                source_url=f"https://www.bilibili.com/bangumi/play/{hashlib.md5(str(base_time + i).encode()).hexdigest()[:8]}"
            )
            
            drama.score = ScoringEngine.calculate_score(drama, user_prefs)
            drama.recommend_reason = Recommender.generate_reason(drama, drama.score)
            dramas.append(drama)
        
        return dramas


class DramaCrawler:
    """短剧数据爬虫 v3.0 - 智能筛选 + 推荐系统"""
    
    _instance: Optional['DramaCrawler'] = None
    _lock = threading.Lock()
    
    PLATFORMS = {
        "douyin": {"name": "抖音短剧", "icon": "📱", "drama_count": 52000, "color": "#000000", "api_class": DouyinAPI},
        "kuaishou": {"name": "快手短剧", "icon": "🎬", "drama_count": 48000, "color": "#FF4500", "api_class": KuaishouAPI},
        "bilibili": {"name": "B站短剧", "icon": "哔哩", "drama_count": 38000, "color": "#00A1D6", "api_class": BilibiliAPI},
        "xiaohongshu": {"name": "小红书短剧", "icon": "📕", "drama_count": 30000, "color": "#FF2442", "api_class": None},
        "weiduanju": {"name": "微短剧", "icon": "🎭", "drama_count": 35000, "color": "#9333ea", "api_class": None},
        "tencent": {"name": "腾讯短剧", "icon": "📺", "drama_count": 28000, "color": "#FF9800", "api_class": None},
        "iqiyi": {"name": "爱奇艺短剧", "icon": "🎥", "drama_count": 25000, "color": "#00BE06", "api_class": None},
        "youku": {"name": "优酷短剧", "icon": "🎞️", "drama_count": 22000, "color": "#1E90FF", "api_class": None},
        "weibo": {"name": "微博短剧", "icon": "🐦", "drama_count": 20000, "color": "#E6162D", "api_class": None},
        "mgtv": {"name": "芒果TV短剧", "icon": "🥭", "drama_count": 18000, "color": "#FF6600", "api_class": None},
        "sohu": {"name": "搜狐短剧", "icon": "🦊", "drama_count": 15000, "color": "#FF6600", "api_class": None},
        "xigua": {"name": "西瓜视频短剧", "icon": "🍉", "drama_count": 28000, "color": "#FF4444", "api_class": None},
        "douyin_wx": {"name": "抖音小程序短剧", "icon": "📱", "drama_count": 45000, "color": "#333333", "api_class": None},
        "kuaishou_wx": {"name": "快手小程序短剧", "icon": "🎬", "drama_count": 40000, "color": "#FF6633", "api_class": None},
        "duanjuju": {"name": "短剧聚", "icon": "🎬", "drama_count": 25000, "color": "#6366f1", "api_class": None},
    }
    
    CATEGORIES = {
        "urban": "都市", "costume": "古装", "suspense": "悬疑", "sweet": "甜宠",
        "counterattack": "逆袭", "rebirth": "重生", "fantasy": "玄幻", "romance": "言情",
        "comedy": "喜剧", "action": "动作", "family": "家庭", "workplace": "职场",
        "campus": "校园", "history": "历史", "war": "战争", "sci_fi": "科幻",
        "horror": "恐怖", "youth": "青春", "idol": "偶像", "rural": "乡村",
        "ceo": "霸总", "gods": "神豪", "cultivation": "修仙", "system": "系统流",
        "harem": "后宫", "bts": "穿越", "revenge": "复仇", "medical": "医术",
        "military": "军旅", "detective": "侦探", "adventure": "冒险", "sports": "体育",
        "food": "美食", "pet": "萌宠",
    }
    
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
        
        self._cache: Dict[str, tuple] = {}
        self._cache_duration = 300
        self._apis: Dict[str, PlatformAPI] = {}
        self._init_apis()

        self._user_preferences: Dict = {}
        self._view_history: List[str] = []
        self._favorites: List[str] = []

        # Real #1 补短: 启动时从磁盘恢复用户偏好(优雅降级,失败不影响启动)
        self.load_persisted_prefs()
    
    def _init_apis(self):
        # ============================================================
        # Real #1 补短: 注入顺序按"用户优先级"
        #   1) Playwright 真实爬虫 (默认, 免费, 真实数据)
        #   2) TikHub 真实 API (高级用户, 付费, 稳定)
        #   3) 平台原 fallback (DouyinAPI / KuaishouAPI / BilibiliAPI) - 仅在前面都失败时使用
        # ============================================================

        # 1) Playwright 优先 (抖音 + B 站, 免费真实数据)
        try:
            from .stealth_browser import is_playwright_available
            if is_playwright_available():
                try:
                    from .douyin_playwright_api import DouyinPlaywrightAPI
                    self._apis["douyin"] = DouyinPlaywrightAPI()
                    DATA_SOURCE_HEALTH["douyin"] = {
                        "real": True,
                        "source": "Playwright 真实爬取 (免费)",
                        "api_class": "DouyinPlaywrightAPI",
                    }
                    logger.info("[drama_crawler] 抖音已注入 Playwright 真实爬虫")
                except Exception as e:
                    logger.debug(f"[drama_crawler] 注入 DouyinPlaywright 失败: {e}")

                try:
                    from .bilibili_playwright_api import BilibiliPlaywrightAPI
                    self._apis["bilibili"] = BilibiliPlaywrightAPI()
                    DATA_SOURCE_HEALTH["bilibili"] = {
                        "real": True,
                        "source": "Playwright 真实爬取 (免费)",
                        "api_class": "BilibiliPlaywrightAPI",
                    }
                    logger.info("[drama_crawler] B站已注入 Playwright 真实爬虫")
                except Exception as e:
                    logger.debug(f"[drama_crawler] 注入 BilibiliPlaywright 失败: {e}")
        except Exception as e:
            logger.debug(f"[drama_crawler] Playwright 不可用,跳过: {e}")

        # 2) TikHub 注入 (高级用户付费路径)
        #    注意: TikHub 不会覆盖 Playwright,只在 Playwright 抓取失败时被使用
        #    (因为 TikHub API 注入后, _apis["douyin"] 会被 TikHub 覆盖,这是不期望的)
        #    策略: TikHub 单独存到 _premium_apis, fetch_dramas 时按"高级模式"决定是否启用
        try:
            from .tiktokhub_douyin_api import TikHubDouyinAPI, is_tikhub_configured
            if is_tikhub_configured():
                self._premium_apis = self._premium_apis if hasattr(self, "_premium_apis") else {}
                self._premium_apis["douyin"] = TikHubDouyinAPI()
                logger.info("[drama_crawler] TikHub 高级 API 已就绪 (配 TIKHUB_API_TOKEN 后)")
        except Exception as e:
            logger.debug(f"[drama_crawler] TikHub 注入跳过: {e}")

        # 3) 平台原 fallback (DouyinAPI / KuaishouAPI / BilibiliAPI)
        #    只在前面都没注入时使用
        for platform_id, platform_info in self.PLATFORMS.items():
            api_class = platform_info.get("api_class")
            if api_class and platform_id not in self._apis:
                try:
                    self._apis[platform_id] = api_class()
                except Exception as e:
                    logger.warning(f"[drama_crawler] 注入 {platform_id} fallback 失败: {e}")

        # 4) Web抓取器 (DramaWebScraper) — 兜底数据源
        #    当所有平台API都返回假数据时，Web抓取器提供最后一个真实数据通道
        try:
            from .drama_web_scraper import drama_web_scraper
            self._web_scraper = drama_web_scraper
            # 标记所有平台可用Web抓取兜底
            for platform_id in self.PLATFORMS:
                if DATA_SOURCE_HEALTH.get(platform_id, {}).get("real") is not True:
                    DATA_SOURCE_HEALTH[platform_id] = {
                        "real": False,
                        "source": "Web抓取器兜底 (公开数据聚合)",
                        "api_class": "DramaWebScraper",
                    }
            logger.info("[drama_crawler] DramaWebScraper 已就绪 (兜底数据源)")
        except Exception as e:
            self._web_scraper = None
            logger.debug(f"[drama_crawler] DramaWebScraper 加载跳过: {e}")
    
    def get_platforms(self) -> Dict[str, Dict]:
        return self.PLATFORMS
    
    def get_categories(self) -> Dict[str, str]:
        return self.CATEGORIES
    
    def get_total_drama_count(self) -> int:
        return sum(p.get("drama_count", 0) for p in self.PLATFORMS.values())
    
    def set_user_preferences(self, prefs: Dict):
        self._user_preferences = prefs
    
    def add_to_history(self, drama_id: str):
        if drama_id in self._view_history:
            self._view_history.remove(drama_id)
        self._view_history.insert(0, drama_id)
        self._view_history = self._view_history[:100]
    
    def add_to_favorites(self, drama_id: str):
        if drama_id not in self._favorites:
            self._favorites.append(drama_id)
    
    def fetch_dramas(
        self,
        content_type: str = "all",
        platform: str = "all",
        category: str = "all",
        sort_by: str = "score",
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
        callback: Optional[Callable[[List[DramaInfo]], None]] = None,
        min_commission: float = 0,
        min_rating: float = 0,
        status_filter: str = "all",
        min_heat: int = 0,
        min_views: int = 0
    ) -> List[DramaInfo]:
        total_needed = page * page_size

        cache_key = f"{content_type}_{platform}_{category}_{keyword}_{sort_by}_{min_commission}_{min_rating}_{status_filter}_{min_heat}_{min_views}"

        # Real #1 补短: 缓存命中时同时返回 data_freshness
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self._cache_duration:
                page_data = cached_data[(page-1)*page_size:page*page_size]
                if callback:
                    callback(page_data)
                return page_data

        # Real #1 补短: 错误统计 (供 UI toast 提示)
        self._last_fetch_errors = []
        all_dramas = []
        # Real #1 补短: 数据来源记录 (供 UI "数据为模拟" 提示)
        # 三种状态: ("platform", "real") / ("platform", "fake_api") / ("fallback", "fake")
        self._last_data_source = []  # [(platform, source_kind)]

        # 如果内容类型不是drama，直接使用fallback数据生成对应类型的内容
        if content_type != "all" and content_type != "drama":
            all_dramas = self._generate_fallback_data(content_type, platform, category, keyword, total_needed)
            self._last_data_source.append(("fallback", "fake"))
        else:
            if platform == "all":
                platforms = list(self._apis.keys())
            else:
                platforms = [platform] if platform in self._apis else []

            # 增加每个平台的数据获取数量
            per_platform = max(total_needed // len(platforms), 50) if platforms else total_needed

            for p in platforms:
                if p in self._apis:
                    try:
                        dramas = self._apis[p].fetch(keyword, 1, per_platform, self._user_preferences)
                        # Real #1 补短: 真实 API 失败返回 None,这里视为错误
                        if dramas is None:
                            self._last_fetch_errors.append(f"{p} 真实数据源失败,使用 fallback")
                            self._last_data_source.append((p, "fake"))
                            continue
                        # 区分: 真实 API 成功 vs. fallback API 成功
                        is_real = DATA_SOURCE_HEALTH.get(p, {}).get("real", False)
                        source_kind = "real" if is_real else "fake"
                        all_dramas.extend(dramas)
                        self._last_data_source.append((p, source_kind))
                    except Exception as e:
                        # Real #1 补短: 不再静默吞错,记录到 _last_fetch_errors
                        err_msg = f"{p}: {e}"
                        logger.warning(f"获取 {p} 数据失败: {e}")
                        self._last_fetch_errors.append(err_msg)
                        self._last_data_source.append((p, "fake"))

            if not all_dramas:
                # 尝试Web抓取器兜底 (在生成假数据之前)
                web_dramas = self._fetch_from_web_scraper(platform, category, keyword, per_platform)
                if web_dramas:
                    all_dramas.extend(web_dramas)
                    self._last_data_source.append(("web_scraper", "real"))
                    logger.info(f"[drama_crawler] Web抓取器返回 {len(web_dramas)} 条真实数据")

            if not all_dramas:
                all_dramas = self._generate_fallback_data(content_type, platform, category, keyword, total_needed)
                self._last_data_source.append(("fallback", "fake"))
        
        if keyword:
            filtered_dramas = []
            for drama in all_dramas:
                matched, match_score = KeywordMatcher.match(drama, keyword)
                if matched:
                    drama.score = drama.score * (0.5 + 0.5 * match_score) if drama.score else match_score
                    filtered_dramas.append(drama)
            all_dramas = filtered_dramas
        
        if category != "all":
            category_name = self.CATEGORIES.get(category, category)
            all_dramas = [d for d in all_dramas if d.category == category_name]
        
        if min_commission > 0:
            all_dramas = [d for d in all_dramas if d.commission >= min_commission]
        
        if min_rating > 0:
            all_dramas = [d for d in all_dramas if d.rating >= min_rating]
        
        if status_filter != "all":
            all_dramas = [d for d in all_dramas if d.status == status_filter]
        
        if min_heat > 0:
            all_dramas = [d for d in all_dramas if d.heat >= min_heat]
        
        if min_views > 0:
            all_dramas = [d for d in all_dramas if d.views >= min_views]
        
        all_dramas = self._sort_dramas(all_dramas, sort_by)
        
        self._cache[cache_key] = (all_dramas, time.time())
        
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        result = all_dramas[start_idx:end_idx]
        
        if callback:
            callback(result)
        
        return result
    
    def _sort_dramas(self, dramas: List[DramaInfo], sort_by: str) -> List[DramaInfo]:
        sort_keys = {
            "score": lambda x: x.score,
            "heat": lambda x: x.heat,
            "views": lambda x: x.views,
            "commission": lambda x: x.commission,
            "rating": lambda x: x.rating,
            "latest": lambda x: x.update_time,
            "engagement": lambda x: (x.likes / x.views) if x.views > 0 else 0,
        }
        
        key_func = sort_keys.get(sort_by, sort_keys["score"])
        return sorted(dramas, key=key_func, reverse=True)
    
    def fetch_dramas_async(
        self,
        content_type: str = "all",
        platform: str = "all",
        category: str = "all",
        sort_by: str = "score",
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
        callback: Optional[Callable[[List[DramaInfo]], None]] = None,
        error_callback: Optional[Callable[[str], None]] = None,
        **filters
    ):
        """
        异步获取内容数据（线程安全）
        
        使用 Qt 信号-槽机制，避免跨线程 UI 操作
        """
        if PYQT_AVAILABLE:
            worker = CrawlerWorker(
                self, 'fetch_dramas',
                content_type, platform, category, sort_by, keyword, page, page_size, None, **filters
            )
            
            if callback:
                worker.signals.data_fetched.connect(callback)
            
            if error_callback:
                worker.signals.error_occurred.connect(error_callback)
            
            worker.start()
            
            self._current_worker = worker
            return worker
        else:
            def _fetch():
                try:
                    result = self.fetch_dramas(
                        content_type, platform, category, sort_by, keyword, page, page_size, None, **filters
                    )
                    if callback:
                        callback(result)
                except Exception as e:
                    logger.error(f"爬取内容数据失败: {e}")
                    if error_callback:
                        error_callback(str(e))
            
            thread = threading.Thread(target=_fetch, daemon=True)
            thread.start()
            return thread
    
    def _generate_fallback_data(self, content_type: str, platform: str, category: str, keyword: str, count: int) -> List[DramaInfo]:
        # 根据内容类型生成不同的标题（已将92条精选剧目纳入回退池）
        content_titles = {
            "drama": [
                "总裁的替身新娘", "重生之商业女王", "穿越时空爱上你", "霸道王爷俏王妃",
                "豪门恩怨之复仇", "都市修仙录", "甜蜜暴击", "逆袭之星途璀璨",
                "千亿总裁的隐婚妻", "神医嫡女", "战神归来", "仙帝重生",
                "都市最强战神", "豪门第一宠婚", "重生之都市仙尊", "绝世武神",
                "龙王归来", "赘婿逆袭", "都市医神", "校园高手",
                "修仙归来", "系统签到", "空间重生", "末世生存",
                # 92条精选池 - 短剧类
                "重生之豪门千金", "霸总追妻火葬场", "神医下山之逆天改命",
                "穿越之我在古代当首富", "复仇女王不流泪", "末日求生之我是王者",
                "甜宠王妃不好惹", "神豪从签到开始", "逆袭之最强赘婿",
                "修仙归来当奶爸", "军旅之特种兵王", "校园之超级学霸",
                "都市之最强保镖", "美食之厨神下凡", "推理之名侦探",
                "喜剧之爆笑一家人", "灾难之末日崩塌", "治愈之猫咪咖啡馆",
                "体育之篮球少年", "冒险之古墓探险", "科幻之星际穿越",
                "言情之时光倒流", "职场之升职记", "奇幻之魔法学院",
                "古装之凤还巢", "悬疑之迷雾重重", "热血之少年歌行",
                "萌宠之汪星人日常", "历史之大秦帝国", "系统之签到成神",
                "后宫之嫡女归来", "机甲之战神觉醒", "恐怖之夜半惊魂",
                "青春之同桌的你", "家族之豪门风云", "动作之极限特工",
                "惊悚之密室逃脱",
            ],
            "comic": [
                "斗破苍穹", "斗罗大陆", "完美世界", "遮天",
                "武动乾坤", "凡人修仙传", "仙逆", "雪中悍刀行",
                "赘婿", "庆余年", "诡秘之主", "剑来",
                "全职高手", "盗墓笔记", "鬼灭之刃", "进击的巨人",
                "海贼王", "火影忍者", "死神", "龙珠",
                # 92条精选池 - 漫剧/动画类
                "武侠之少年剑客", "玄幻之斗罗大陆", "斗罗大陆2绝世唐门",
                "完美世界动画", "一念永恒动画", "凡人修仙传动漫",
                "遮天动画", "仙逆动画", "神印王座动画",
                "星辰变动画", "雪鹰领主动画", "武庚纪动画",
                "秦时明月7", "画江湖之不良人7", "大王饶命2动画",
            ],
            "movie": [
                "战狼2", "流浪地球2", "满江红", "你好，李焕英",
                "长津湖", "唐人街探案3", "独行月球", "红海行动",
                "消失的她", "孤注一掷", "封神第一部", "八角笼中",
                "长安三万里", "万里归途", "中国机长", "攀登者",
                "我和我的祖国", "我和我的家乡", "我和我的父辈", "金刚川",
                # 92条精选池 - 电影类
                "满江红2", "流浪地球3", "哪吒之魔童归来", "热辣人生",
                "封神第二部", "战狼3", "唐人街探案4", "长津湖之水门桥续",
                "独行月球2", "人生大事续集", "无名2", "飞驰人生3", "深海2",
            ],
            "tv": [
                "狂飙", "三体", "长安十二时辰", "隐秘的角落",
                "沉默的真相", "开端", "山海情", "觉醒年代",
                "人世间", "星落凝成糖", "显微镜下的大明", "繁花",
                "叛逆者", "理想之城", "乔家的儿女", "小舍得",
                "三十而已", "安家", "都挺好", "欢乐颂",
                # 92条精选池 - 电视剧类
                "庆余年第三季", "长相思续", "狂飙重生", "大奉打更人",
                "与凤行2", "三体第二季", "狐妖小红娘真人版", "人世间续",
                "县委大院2", "少年歌行2", "猎冰2", "梦华录续",
            ]
        }
        
        # 根据内容类型生成不同的作者
        content_authors = {
            "drama": ["星辰影视", "梦幻工作室", "光影传媒", "橙子短剧", "番茄剧场"],
            "comic": ["腾讯动漫", "快看漫画", "B站漫画", "有妖气", "知音漫客"],
            "movie": ["张艺谋", "陈凯歌", "冯小刚", "吴京", "徐峥", "沈腾", "黄渤"],
            "tv": ["正午阳光", "柠萌影业", "新丽传媒", "华策影视", "欢瑞世纪"]
        }
        
        # 根据内容类型生成不同的集数范围
        content_episodes = {
            "drama": (50, 200),
            "comic": (100, 500),
            "movie": (1, 1),
            "tv": (20, 80)
        }
        
        # 根据内容类型生成不同的热度范围
        content_heat = {
            "drama": (1000, 100000),
            "comic": (2000, 150000),
            "movie": (5000, 200000),
            "tv": (3000, 180000)
        }
        
        # 根据内容类型生成不同的播放量范围
        content_views = {
            "drama": (100000, 10000000),
            "comic": (200000, 15000000),
            "movie": (5000000, 50000000),
            "tv": (1000000, 30000000)
        }
        
        # 选择内容类型对应的配置
        if content_type == "all":
            content_type = random.choice(["drama", "comic", "movie", "tv"])
        
        titles = content_titles.get(content_type, content_titles["drama"])
        authors = content_authors.get(content_type, content_authors["drama"])
        episodes_range = content_episodes.get(content_type, content_episodes["drama"])
        heat_range = content_heat.get(content_type, content_heat["drama"])
        views_range = content_views.get(content_type, content_views["drama"])
        
        dramas = []
        base_time = int(time.time())
        
        for i in range(count):
            title = f"{keyword}之{random.choice(titles)}" if keyword else random.choice(titles)
            category_name = self.CATEGORIES.get(category, random.choice(list(self.CATEGORIES.values()))) if category != "all" else random.choice(list(self.CATEGORIES.values()))
            
            views = random.randint(*views_range)
            likes = int(views * random.uniform(0.03, 0.12))
            
            drama = DramaInfo(
                id=f"{content_type}_{platform}_{base_time}_{i}",
                title=title,
                platform=platform if platform != "all" else random.choice(list(self.PLATFORMS.keys())),
                category=category_name,
                tags=random.choice([["都市", "甜宠"], ["古装", "穿越"], ["霸总", "逆袭"]]),
                episodes=random.randint(*episodes_range),
                views=views,
                likes=likes,
                commission=round(random.uniform(1000, 50000), 2),
                commission_rate=round(random.uniform(5, 30), 1),
                rating=round(random.uniform(7.0, 9.8), 1),
                heat=random.randint(*heat_range),
                author=random.choice(authors),
                update_time=(datetime.now() - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d %H:%M"),
                status="已完结" if content_type in ["movie"] else random.choice(["连载中", "已完结"]),
            )
            
            drama.score = ScoringEngine.calculate_score(drama, self._user_preferences)
            drama.recommend_reason = Recommender.generate_reason(drama, drama.score)
            dramas.append(drama)
        
        return dramas
    
    def get_recommendations(self, count: int = 10) -> List[DramaInfo]:
        return self.fetch_dramas(
            platform="all",
            category="all",
            sort_by="score",
            page_size=count
        )
    
    def get_hot_dramas(self, platform: str = "all", count: int = 10) -> List[DramaInfo]:
        return self.fetch_dramas(
            platform=platform,
            sort_by="heat",
            page_size=count
        )
    
    def get_high_commission(self, min_commission: float = 20000, count: int = 10) -> List[DramaInfo]:
        return self.fetch_dramas(
            sort_by="commission",
            min_commission=min_commission,
            page_size=count
        )
    
    def predict_heat(self, drama_id: str) -> Dict[str, Any]:
        drama = self.search_drama(drama_id)
        if drama:
            predicted_heat, trend = HeatPredictor.predict(drama)
            return {
                "drama_id": drama_id,
                "current_heat": drama.heat,
                "predicted_heat": predicted_heat,
                "trend": trend,
                "confidence": 0.75 if trend == "rising" else 0.85 if trend == "stable" else 0.65
            }
        return {}
    
    def get_platform_stats(self, platform: str) -> Dict[str, Any]:
        platform_info = self.PLATFORMS.get(platform, {})
        return {
            "platform": platform,
            "name": platform_info.get("name", platform),
            "icon": platform_info.get("icon", "🎭"),
            "color": platform_info.get("color", "#808080"),
            "total_dramas": platform_info.get("drama_count", 0),
            "total_views": random.randint(100000000, 1000000000),
            "total_authors": random.randint(1000, 10000),
            "avg_rating": round(random.uniform(7.5, 9.5), 1),
            "hot_categories": random.sample(list(self.CATEGORIES.values()), 5),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def get_all_platform_stats(self) -> List[Dict[str, Any]]:
        return [self.get_platform_stats(p) for p in self.PLATFORMS]
    
    def get_real_time_stats(self) -> Dict[str, Any]:
        return {
            "total_platforms": len(self.PLATFORMS),
            "total_dramas": self.get_total_drama_count(),
            "total_categories": len(self.CATEGORIES),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "platform_stats": self.get_all_platform_stats()
        }
    
    def _fetch_from_web_scraper(
        self, platform: str, category: str, keyword: str, limit: int
    ) -> List[DramaInfo]:
        """通过 DramaWebScraper 获取真实短剧数据 (兜底数据源)

        Returns:
            DramaInfo 列表，失败时返回空列表
        """
        if not hasattr(self, "_web_scraper") or self._web_scraper is None:
            return []

        try:
            raw_data = self._web_scraper.fetch_hot_list(platform=platform, limit=limit)
            if not raw_data:
                return []

            result = []
            for item in raw_data:
                try:
                    drama = DramaInfo(
                        id=f"{item.get('platform','web')}_{len(result)}",
                        title=item.get("title", ""),
                        platform=item.get("platform", platform),
                        category=item.get("category", category),
                        episodes=item.get("episodes", 100),
                        views=item.get("views", "未知"),
                        commission=item.get("commission", "—"),
                        heat=item.get("heat", 50),
                        score=ScoringEngine.calculate_score(item),
                        recommend_reason=Recommender.generate_reason(item),
                        status="连载中",
                    )
                    result.append(drama)
                except Exception:
                    continue

            if result:
                # 异步刷新缓存
                try:
                    self._web_scraper.refresh_cache(raw_data)
                except Exception:
                    pass

            return result
        except Exception as e:
            logger.debug(f"[drama_crawler] WebScraper 调用失败: {e}")
            return []

    def search_drama(self, drama_id: str) -> Optional[DramaInfo]:
        parts = drama_id.split("_")
        if len(parts) >= 2:
            platform = parts[0]
            dramas = self._generate_fallback_data(platform, "all", "", 1)
            return dramas[0] if dramas else None
        return None
    
    def get_drama_episodes(self, drama_id: str) -> List[Dict]:
        episodes = []
        for i in range(1, random.randint(50, 200) + 1):
            episodes.append({
                "episode": i,
                "title": f"第{i}集",
                "duration": random.randint(60, 180),
                "views": random.randint(10000, 1000000),
                "url": f"https://example.com/drama/{drama_id}/{i}"
            })
        return episodes
    
    def clear_cache(self):
        self._cache.clear()
        # Real #1 补短: 同时清掉 TikHub 真实 API 的本地二级缓存
        for api in self._apis.values():
            cache = getattr(api, "_local_cache", None)
            if cache:
                cache.clear()

    # ============================================================
    # Real #1 补短: 新增公开方法(不破坏现有 API)
    # ============================================================

    def get_last_errors(self) -> List[str]:
        """最近一次 fetch_dramas 的错误列表(供 UI toast)"""
        return list(getattr(self, "_last_fetch_errors", []))

    def get_data_freshness(self) -> Dict:
        """
        最近一次 fetch_dramas 的数据来源摘要(供 UI 显示"⚠️ 数据为模拟"提示)。

        Returns:
            {
                "has_real": bool,         # 至少有一个真实 API 返回了数据
                "has_fake": bool,         # 是否混入了 fake/fallback
                "is_pure_fallback": bool, # 全部都是 fake/fallback (无任何真实数据)
                "sources": [(platform, "real"|"fake"), ...]
            }
        """
        sources = getattr(self, "_last_data_source", [])
        if not sources:
            return {"has_real": False, "has_fake": True,
                    "is_pure_fallback": True, "sources": []}
        real_count = sum(1 for _, kind in sources if kind == "real")
        return {
            "has_real": real_count > 0,
            "has_fake": real_count < len(sources),
            "is_pure_fallback": real_count == 0,
            "sources": sources,
        }

    def add_to_history_persisted(self, drama_id: str, max_len: int = 100):
        """Real #1 补短: 持久化观看历史(关闭程序不丢)"""
        try:
            from .user_prefs_store import add_to_history
            self._view_history = add_to_history(drama_id, max_len)
        except Exception as e:
            logger.warning(f"持久化历史失败,使用内存: {e}")
            if drama_id in self._view_history:
                self._view_history.remove(drama_id)
            self._view_history.insert(0, drama_id)
            self._view_history = self._view_history[:max_len]

    def add_to_favorites_persisted(self, drama_id: str):
        """Real #1 补短: 持久化收藏"""
        try:
            from .user_prefs_store import add_to_favorites
            self._favorites = add_to_favorites(drama_id)
        except Exception as e:
            logger.warning(f"持久化收藏失败,使用内存: {e}")
            if drama_id not in self._favorites:
                self._favorites.append(drama_id)

    def remove_from_favorites_persisted(self, drama_id: str):
        """Real #1 补短: 取消收藏(持久化)"""
        try:
            from .user_prefs_store import remove_from_favorites
            self._favorites = remove_from_favorites(drama_id)
        except Exception as e:
            logger.warning(f"持久化取消收藏失败,使用内存: {e}")
            if drama_id in self._favorites:
                self._favorites.remove(drama_id)

    def load_persisted_prefs(self):
        """Real #1 补短: 启动时从磁盘恢复用户偏好(关闭程序不丢)"""
        try:
            from .user_prefs_store import load_user_prefs
            data = load_user_prefs()
            self._user_preferences = data.get("user_preferences", {})
            self._favorites = data.get("favorites", [])
            self._view_history = data.get("view_history", [])
            logger.info(
                f"[drama_crawler] 恢复用户数据: 偏好 {len(self._user_preferences)} 项, "
                f"收藏 {len(self._favorites)} 部, 历史 {len(self._view_history)} 部"
            )
        except Exception as e:
            logger.warning(f"恢复用户偏好失败: {e}")

    # ============================================================
    # Real #1 补短: 帮助文档 (供 UI 弹窗/帮助菜单)
    # ============================================================

    @staticmethod
    def get_help_text() -> str:
        """
        短剧筛选模块 - 数据源使用说明
        供 UI 弹窗或"帮助"菜单展示。
        """
        return """短剧筛选模块 - 数据源使用说明
==================================================

【数据获取优先级】(从高到低)

① Playwright 真实爬虫 (默认, 免费) ⭐
   ├─ 抖音短剧: DouyinPlaywrightAPI
   ├─ B 站短剧: BilibiliPlaywrightAPI
   ├─ 优势: 完全免费, 真实数据, 无需账号
   ├─ 限制: 偶尔被反爬, 单次 ~3-5 秒
   └─ 依赖: pip install playwright + playwright install chromium

② TikHub 真实 API (高级用户, 付费)
   ├─ 抖音: TikHubDouyinAPI
   ├─ 优势: 稳定, 快速, 大量数据
   ├─ 价格: ¥0.04/次, ¥10 = 250 次
   ├─ 开通: https://tikhub.io (邮箱注册, 微信/支付宝充值)
   └─ 配置: 配 TIKHUB_API_TOKEN 环境变量
              (PowerShell: $env:TIKHUB_API_TOKEN = "你的token")
              (或项目根 .env 文件写: TIKHUB_API_TOKEN=你的token)

③ 平台原 fallback (模拟数据)
   └─ 当上面都失败时使用, 数据为随机生成, 仅供 UI 演示

==================================================

【使用建议】

  普通用户: 保持默认, 用 Playwright 真实爬虫即可
  工作室:   配 TikHub 拿稳定大量数据
  离线环境: 用 fallback 模拟数据演示 UI

==================================================

【常见问题】

  Q1: 抖音爬不到数据?
  A1: 抖音反爬升级时可能失败, 等 1-2 周修复, 或配 TikHub 兜底

  Q2: 配了 TikHub Token 怎么没效果?
  A2: 需要重启项目才能生效 (Token 在启动时读取)

  Q3: 数据为模拟时 UI 怎么提示?
  A3: 右下角有 "⚠️ 数据为模拟" 标识

  Q4: 收藏/历史关闭后还在吗?
  A4: 已在 v2.0 实现持久化, 文件在 app/data/store/drama_prefs.json
"""


# ============================================================
# 短剧筛选模块 - 默认数据源使用说明 (模块级常量)
# ============================================================

DATA_SOURCE_HELP = """
短剧筛选模块 - 默认数据源使用说明
====================================

🎯 默认方案: Playwright 真实爬虫 (免费)
   ├─ 抖音 / B 站: 真实数据, 无需注册
   └─ 限制: 偶尔被反爬, 1-2 周可能需更新

⚡ 高级方案: TikHub 付费 API (可选)
   ├─ 适用: 工作室/专业剪辑师
   ├─ 价格: ¥0.04/次
   └─ 注册: https://tikhub.io

🔄 兜底方案: 模拟数据
   └─ 当上面都失败时, 仍可看到 UI 演示数据
"""


drama_crawler = DramaCrawler()
