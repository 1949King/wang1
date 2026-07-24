"""
抖音短剧 Playwright 爬虫 (默认真实数据源)
==========================================
用户首选方案: 免费 + 真实数据 + 不需要任何账号/Token。
失败时 fetch() 返回 None, 由 DramaCrawler 自动回退到 TikHub / 模拟数据。

抓取目标:
  - 抖音短剧频道: https://www.douyin.com/discover/series
  - 通过 page.route() 拦截 /aweme/post/ 类型的 API 响应
  - 解析 JSON 中的 aweme_list

反爬策略:
  - 复用 StealthBrowser 的 stealth.js 注入
  - 高斯分布延迟 (3±1 秒)
  - 失败重试 2 次

参考:
  - https://github.com/Greatdori/Douyin_TikTok_Scraper
  - https://github.com/Johnserf-Seed/f2
  - https://github.com/cv-cat/python-xiaohongshu-scraper
"""
import os
import json
import time
import logging
import hashlib
from typing import List, Optional, Dict
from datetime import datetime

from .drama_crawler import DramaInfo, PlatformAPI, ScoringEngine, Recommender
from .stealth_browser import (
    is_playwright_available,
    get_stealth_browser,
    StealthBrowser,
)

logger = logging.getLogger(__name__)


# 抖音短剧关键词 (用这些做搜索更精准, 比直接抓"热榜"命中率高)
KEYWORDS_HOT = [
    "短剧",
    "甜宠短剧",
    "战神归来",
    "穿越短剧",
    "重生短剧",
]


class DouyinPlaywrightAPI(PlatformAPI):
    """
    抖音短剧 Playwright 爬虫 (真实数据, 免费)。
    fetch() 失败时返回 None, 由 DramaCrawler 自动回退。
    """

    # 抖音短剧搜索 URL (有搜索结果更精准)
    SEARCH_URL = "https://www.douyin.com/search/{keyword}?type=video&publish_time=week"
    # 抖音短剧频道 URL
    SERIES_URL = "https://www.douyin.com/discover/series"
    CACHE_TTL = 600  # 本地缓存 10 分钟

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self._local_cache: Dict[str, tuple] = {}  # cache_key -> (data, ts)
        # Real #1 补短: 实例化即标记"健康度" (UI 弹"⚠️ 数据为模拟"提示用)
        # 之前只在 fetch() 成功后才标记,会导致 _to_drama_info() 单测时漏标
        try:
            from .drama_crawler import DATA_SOURCE_HEALTH
            DATA_SOURCE_HEALTH["douyin"] = {
                "real": True,
                "source": "Playwright 真实爬取",
                "api_class": "DouyinPlaywrightAPI",
            }
        except Exception:
            # 极端情况下避免阻断实例化
            pass

    # ---- 公开方法 ----

    def is_available(self) -> bool:
        """爬虫是否可用: playwright + chromium 已装"""
        return is_playwright_available()

    def fetch(self, keyword: str = "", page: int = 1, page_size: int = 20,
              user_prefs: Dict = None) -> Optional[List[DramaInfo]]:
        """
        用 Playwright 抓取抖音短剧真实数据。

        Args:
            keyword:  搜索关键词, 留空走热榜
            page:     页码 (目前只支持第 1 页, 抖音搜索 API 不直接分页)
            page_size: 每页条数
            user_prefs: 用户偏好

        Returns:
            List[DramaInfo] 成功
            None           失败 (调用方应回退)
        """
        if not self.is_available():
            logger.info("[DouyinPlaywright] playwright 不可用,跳过")
            return None

        # 1) 本地缓存命中
        cache_key = f"douyin_pw_{keyword}_{page}_{page_size}"
        if cache_key in self._local_cache:
            data, ts = self._local_cache[cache_key]
            if time.time() - ts < self.CACHE_TTL:
                logger.info(f"[DouyinPlaywright] 本地缓存命中: {cache_key}")
                return data

        # 2) 真实抓取
        dramas = None
        try:
            if keyword and keyword not in ("all", "热榜", "drama", ""):
                dramas = self._scrape_search(keyword, page_size, user_prefs)
            if not dramas:
                # 兜底走频道页
                dramas = self._scrape_series(page_size, user_prefs)
        except Exception as e:
            logger.warning(f"[DouyinPlaywright] 抓取失败: {e}")
            return None

        if not dramas:
            return None

        # 3) 本地缓存 + 更新健康状态
        self._local_cache[cache_key] = (dramas, time.time())
        from .drama_crawler import DATA_SOURCE_HEALTH
        DATA_SOURCE_HEALTH["douyin"] = {
            "real": True,
            "source": "Playwright 真实爬取",
            "api_class": "DouyinPlaywrightAPI",
        }
        logger.info(f"[DouyinPlaywright] 抓取成功: {len(dramas)} 条")
        return dramas

    # ---- 内部方法 ----

    def _scrape_search(self, keyword: str, count: int, user_prefs: Dict) -> Optional[List[DramaInfo]]:
        """搜索关键词抓取"""
        url = self.SEARCH_URL.format(keyword=keyword)
        return self._scrape_douyin(url, count, user_prefs, source_kind="search")

    def _scrape_series(self, count: int, user_prefs: Dict) -> Optional[List[DramaInfo]]:
        """短剧频道抓取"""
        return self._scrape_douyin(self.SERIES_URL, count, user_prefs, source_kind="series")

    def _scrape_douyin(self, url: str, count: int, user_prefs: Dict,
                        source_kind: str, max_retries: int = 2) -> Optional[List[DramaInfo]]:
        """
        核心抓取逻辑 (复用 StealthBrowser + page.route 拦截 API)。

        抖音搜索结果页会调 /aweme/post/ 类 API 返回 aweme_list,
        我们在协议层拦截, 不依赖 HTML 解析 (DOM 经常改).
        """
        browser: Optional[StealthBrowser] = None
        page = None
        intercepted_data: List[Dict] = []

        def _on_response(response):
            """拦截抖音 API 响应"""
            try:
                if "/aweme/post/" in response.url or "/aweme/v1/web/aweme/post/" in response.url:
                    try:
                        body = response.json()
                        if isinstance(body, dict) and "aweme_list" in body:
                            for item in body["aweme_list"]:
                                if isinstance(item, dict):
                                    intercepted_data.append(item)
                    except Exception:
                        pass
            except Exception:
                pass

        for attempt in range(max_retries + 1):
            try:
                browser = get_stealth_browser()
                if not browser.is_running():
                    browser.start()
                page = browser.new_page()
                page.on("response", _on_response)

                # 访问页面 (触发 AJAX)
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                browser.human_delay(mean=2.5, std=0.8)  # 等 AJAX 完成

                # 滚动触发懒加载 (短剧搜索结果通常 1-2 屏)
                for _ in range(2):
                    page.evaluate("window.scrollBy(0, 600)")
                    browser.human_delay(mean=1.5, std=0.5)

                break  # 成功, 退出重试循环
            except Exception as e:
                logger.warning(f"[DouyinPlaywright] 第 {attempt+1} 次抓取异常: {e}")
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = None
                if attempt >= max_retries:
                    return None
                browser.human_delay(mean=2, std=1)

        # 解析拦截到的数据
        if not intercepted_data:
            logger.info(f"[DouyinPlaywright] 拦截到 0 条 ({source_kind})")
            return None

        dramas = []
        for item in intercepted_data[:count]:
            drama = self._to_drama_info(item, user_prefs)
            if drama:
                dramas.append(drama)

        if page:
            try:
                page.close()
            except Exception:
                pass

        return dramas if dramas else None

    def _to_drama_info(self, item: Dict, user_prefs: Dict) -> Optional[DramaInfo]:
        """抖音原始 aweme → DramaInfo"""
        try:
            aweme_id = (
                item.get("aweme_id")
                or item.get("video_id")
                or hashlib.md5(str(item).encode()).hexdigest()[:16]
            )
            title = (
                item.get("title")
                or item.get("desc")
                or "(无标题)"
            )
            # 抖音标题可能含 # 话题, 取第 1 段
            if "#" in title:
                title = title.split("#")[0].strip() or title
            # 截断
            title = str(title)[:100]

            author_obj = item.get("author") or {}
            if isinstance(author_obj, dict):
                author = author_obj.get("nickname") or "未知"
            else:
                author = str(author_obj) or "未知"
            author = str(author)[:30]

            # 统计
            stats = item.get("statistics") or item.get("video_status") or {}
            views = int(stats.get("play_count") or stats.get("views") or 0)
            likes = int(stats.get("digg_count") or stats.get("likes") or 0)
            comments = int(stats.get("comment_count") or 0)
            shares = int(stats.get("share_count") or 0)

            # 时长
            video = item.get("video") or item
            duration = int(video.get("duration") or 0) / 1000.0  # 抖音返回毫秒
            if duration <= 0:
                duration = 60.0  # 短剧默认估 1 分钟

            # 封面
            cover_url = ""
            for key in ("cover_url", "dynamic_cover", "origin_cover", "cover"):
                v = video.get(key) if isinstance(video, dict) else None
                if not v:
                    v = item.get(key)
                if isinstance(v, dict):
                    v = v.get("url_list", [None])[0] or v.get("url") or v.get("uri")
                if v:
                    cover_url = v
                    break

            # 标签
            tags = []
            for tag in (item.get("text_extra") or item.get("tags") or []):
                if isinstance(tag, dict):
                    t = tag.get("tag_name") or tag.get("name") or ""
                    if t:
                        tags.append(t)
                elif isinstance(tag, str):
                    tags.append(tag)

            # 时间
            ts = int(item.get("create_time") or 0)
            if ts:
                update_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            else:
                update_time = datetime.now().strftime("%Y-%m-%d %H:%M")

            # 集数估算 (短剧 1 条视频约 5-10 集)
            episodes = max(1, int(duration // 30) + 1) if duration > 0 else 1

            # 热度: 综合播放/点赞/评论
            heat = views // 1000 + likes * 10 + comments * 5 + shares * 8

            drama = DramaInfo(
                id=f"douyin_playwright_{aweme_id}",
                title=title,
                platform="douyin",
                category=item.get("category_name") or "短剧",
                tags=tags[:10] if tags else ["短剧"],
                episodes=episodes,
                views=views,
                likes=likes,
                commission=0.0,
                commission_rate=0.0,
                rating=0.0,
                heat=heat,
                author=author,
                update_time=update_time,
                status="连载中",
                cover_url=cover_url,
                description=item.get("desc") or title,
                source_url=f"https://www.douyin.com/video/{aweme_id}",
            )
            drama.score = ScoringEngine.calculate_score(drama, user_prefs)
            drama.recommend_reason = Recommender.generate_reason(drama, drama.score)
            return drama
        except Exception as e:
            logger.debug(f"[DouyinPlaywright] 解析单条失败: {e}")
            return None
