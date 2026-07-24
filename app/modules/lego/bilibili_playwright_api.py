"""
B 站短剧 Playwright 爬虫 (完全免费)
=====================================
B 站反爬较温和, Playwright + stealth.js 即可稳定抓取。
不需 Token / 不需登录 / 不需付费。

抓取目标:
  - B 站短剧频道: https://www.bilibili.com/v/popular/serial
  - 短剧搜索: https://search.bilibili.com/all?keyword=短剧
  - page.route() 拦截 /x/web-interface/ 类型的 API

反爬策略:
  - 复用 StealthBrowser stealth.js 注入
  - 抖音用 3s 高斯延迟, B 站放宽到 2s
  - 失败重试 2 次
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


# B 站短剧搜索关键词
KEYWORDS = ["短剧", "微短剧", "短剧合集", "甜宠短剧", "重生短剧"]


class BilibiliPlaywrightAPI(PlatformAPI):
    """
    B 站短剧 Playwright 爬虫 (免费真实数据)。
    """

    SEARCH_URL = "https://search.bilibili.com/all?keyword={keyword}"
    POPULAR_URL = "https://www.bilibili.com/v/popular/serial"
    CACHE_TTL = 600

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self._local_cache: Dict[str, tuple] = {}
        # Real #1 补短: 实例化即标记"健康度" (UI 弹"⚠️ 数据为模拟"提示用)
        # 之前只在 fetch() 成功后才标记,会导致 _to_drama_info() 单测时漏标
        try:
            from .drama_crawler import DATA_SOURCE_HEALTH
            DATA_SOURCE_HEALTH["bilibili"] = {
                "real": True,
                "source": "Playwright 真实爬取",
                "api_class": "BilibiliPlaywrightAPI",
            }
        except Exception:
            # 极端情况下避免阻断实例化
            pass

    # ---- 公开方法 ----

    def is_available(self) -> bool:
        return is_playwright_available()

    def fetch(self, keyword: str = "", page: int = 1, page_size: int = 20,
              user_prefs: Dict = None) -> Optional[List[DramaInfo]]:
        if not self.is_available():
            return None

        # 本地缓存
        cache_key = f"bilibili_pw_{keyword}_{page}_{page_size}"
        if cache_key in self._local_cache:
            data, ts = self._local_cache[cache_key]
            if time.time() - ts < self.CACHE_TTL:
                return data

        dramas = None
        try:
            if keyword and keyword not in ("all", "热榜", "drama", ""):
                dramas = self._scrape_search(keyword, page_size, user_prefs)
            if not dramas:
                dramas = self._scrape_popular(page_size, user_prefs)
        except Exception as e:
            logger.warning(f"[BilibiliPlaywright] 抓取失败: {e}")
            return None

        if not dramas:
            return None

        self._local_cache[cache_key] = (dramas, time.time())
        from .drama_crawler import DATA_SOURCE_HEALTH
        DATA_SOURCE_HEALTH["bilibili"] = {
            "real": True,
            "source": "Playwright 真实爬取",
            "api_class": "BilibiliPlaywrightAPI",
        }
        logger.info(f"[BilibiliPlaywright] 抓取成功: {len(dramas)} 条")
        return dramas

    # ---- 内部方法 ----

    def _scrape_search(self, keyword: str, count: int, user_prefs: Dict) -> Optional[List[DramaInfo]]:
        url = self.SEARCH_URL.format(keyword=keyword)
        return self._scrape_bilibili(url, count, user_prefs, source_kind="search")

    def _scrape_popular(self, count: int, user_prefs: Dict) -> Optional[List[DramaInfo]]:
        return self._scrape_bilibili(self.POPULAR_URL, count, user_prefs, source_kind="popular")

    def _scrape_bilibili(self, url: str, count: int, user_prefs: Dict,
                          source_kind: str, max_retries: int = 2) -> Optional[List[DramaInfo]]:
        """核心抓取 - 拦截 /x/web-interface/search/ 等 API"""
        browser: Optional[StealthBrowser] = None
        page = None
        intercepted_data: List[Dict] = []

        def _on_response(response):
            try:
                url_str = response.url
                # B 站搜索 API / 推荐 API
                if ("/x/web-interface/search/all/v2" in url_str
                        or "/x/web-interface/popular" in url_str
                        or "/api/bilibili.com/x/web-interface/" in url_str):
                    try:
                        body = response.json()
                        data = body.get("data") or body.get("result") or {}
                        if isinstance(data, dict):
                            # 搜索结果
                            result = data.get("result") or []
                            if isinstance(result, list):
                                for item in result:
                                    if isinstance(item, dict):
                                        intercepted_data.append(item)
                            # 热门结果
                            items = data.get("list") or []
                            if isinstance(items, list):
                                for item in items:
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

                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                browser.human_delay(mean=2.0, std=0.5)

                # B 站搜索结果是无限滚动, 多滚 2 屏
                for _ in range(2):
                    page.evaluate("window.scrollBy(0, 800)")
                    browser.human_delay(mean=1.0, std=0.3)

                break
            except Exception as e:
                logger.warning(f"[BilibiliPlaywright] 第 {attempt+1} 次抓取异常: {e}")
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = None
                if attempt >= max_retries:
                    return None
                browser.human_delay(mean=1.5, std=0.5)

        if not intercepted_data:
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
        """B 站原始 → DramaInfo"""
        try:
            # B 站搜索结果 data_type 多种: video / bangumi / live...
            data_type = item.get("data_type") or item.get("type") or "video"
            if data_type not in ("video", "bangumi", "media_bangumi"):
                # 非视频类型跳过
                if "title" in item and "play" in str(item.get("play", "")):
                    pass
                else:
                    return None

            bvid = (
                item.get("bvid")
                or item.get("id")
                or hashlib.md5(str(item).encode()).hexdigest()[:16]
            )
            title = item.get("title") or item.get("name") or "(无标题)"
            # B 站标题含 <em> 标签, 清洗
            title = title.replace("<em class=\"keyword\">", "").replace("</em>", "")
            title = str(title)[:100]

            author = item.get("author") or item.get("up_name") or item.get("name") or "未知"
            if isinstance(author, dict):
                author = author.get("name") or "未知"
            author = str(author)[:30]

            # 统计
            views = int(item.get("play") or item.get("view") or item.get("stat", {}).get("view") or 0)
            likes = int(item.get("like") or item.get("stat", {}).get("like") or 0)
            danmu = int(item.get("danmaku") or item.get("stat", {}).get("danmaku") or 0)

            # 时长
            duration_str = str(item.get("duration") or "0:0")
            duration = self._parse_bili_duration(duration_str)

            # 封面
            cover_url = (
                item.get("pic")
                or item.get("cover")
                or (item.get("cover_url") if isinstance(item.get("cover_url"), str) else "")
            )
            if isinstance(cover_url, list) and cover_url:
                cover_url = cover_url[0]

            # 标签
            tags = []
            tag_str = item.get("tag") or item.get("tags")
            if isinstance(tag_str, str):
                tags = [t.strip() for t in tag_str.split(",") if t.strip()][:10]
            elif isinstance(tag_str, list):
                tags = [str(t)[:20] for t in tag_str[:10]]

            # 时间
            ts = int(item.get("pubdate") or item.get("ctime") or 0)
            if ts:
                update_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            else:
                update_time = datetime.now().strftime("%Y-%m-%d %H:%M")

            # 集数估算
            episodes = max(1, int(duration // 60) + 1) if duration > 0 else 1

            # 热度
            heat = views // 1000 + likes * 10 + danmu * 3

            drama = DramaInfo(
                id=f"bilibili_playwright_{bvid}",
                title=title,
                platform="bilibili",
                category="短剧" if "短剧" in title or "短剧" in str(tags) else item.get("typename") or "其他",
                tags=tags if tags else ["短剧"],
                episodes=episodes,
                views=views,
                likes=likes,
                commission=0.0,
                commission_rate=0.0,
                rating=float(item.get("rating") or 0) or 0.0,
                heat=heat,
                author=author,
                update_time=update_time,
                status="连载中",
                cover_url=cover_url if isinstance(cover_url, str) else "",
                description=item.get("description") or title,
                source_url=f"https://www.bilibili.com/video/{bvid}" if str(bvid).startswith("BV") else f"https://search.bilibili.com/all?keyword={keyword}",
            )
            drama.score = ScoringEngine.calculate_score(drama, user_prefs)
            drama.recommend_reason = Recommender.generate_reason(drama, drama.score)
            return drama
        except Exception as e:
            logger.debug(f"[BilibiliPlaywright] 解析单条失败: {e}")
            return None

    @staticmethod
    def _parse_bili_duration(d: str) -> float:
        """B 站时长 '12:34' / '1:23:45' → 秒"""
        try:
            parts = d.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            return 60.0
        except Exception:
            return 60.0
