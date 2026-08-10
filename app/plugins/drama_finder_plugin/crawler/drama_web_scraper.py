"""
短剧Web抓取器 - 从公开短剧热榜网站抓取真实数据
==================================================
作为 DramaCrawler 的补充数据源，当 Playwright/TikHub API 不可用时使用。

策略:
  1. 优先使用 Playwright 真实爬取 (douyin_playwright_api / bilibili_playwright_api)
  2. 其次使用本模块的 HTTP 抓取 (公开数据聚合站点)
  3. 最后回退到 drama_data.json 静态缓存

设计参考: Toonflow / Huobao Drama 的数据聚合策略
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# ── 公开短剧数据聚合源 ──
# 这些是公开的短剧热榜API/页面，用于兜底数据采集
_HOT_DRAMA_SOURCES = [
    {
        "name": "短剧热榜-聚合",
        "url": "https://api.example.com/drama/hot",  # 占位，实际部署时替换
        "parser": "json",
        "enabled": False,  # 默认禁用，需用户配置真实API
    },
]

# 内置短剧标题池 (用于网络不可用时的最基础兜底)
_BUILTIN_TITLES = [
    "我在八零年代当后妈", "闪婚后成了大佬的心尖宠", "重生之都市修仙",
    "王妃她不装了", "总裁的替身前妻", "穿越古代当赘婿",
    "我成了反派的白月光", "真千金她美强飒", "女总裁的全能兵王",
    "一不小心捡到了总裁", "神医狂妃", "豪门千金不好惹",
    "重生九零辣媳当家", "我的AI恋人", "逃婚后我成了富豪",
    "被读心后我成了团宠", "末世重生囤货女王", "将军在上我在下",
    "离婚后我成了首富", "穿成虐文女主后我摆烂了",
]


class DramaWebScraper:
    """从公开网络源抓取短剧数据"""

    def __init__(self, cache_dir: str = None):
        # 缓存落在 app/data（与迁入插件前一致）；勿用 crawler/ 相对两级（会指到 plugins/data）
        if cache_dir:
            self._cache_dir = cache_dir
        else:
            app_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..")
            )
            self._cache_dir = os.path.join(app_root, "data")
        self._cache_file = os.path.join(self._cache_dir, "drama_data.json")
        self._cache_ttl = 3600  # 1小时缓存
        self._sources = _HOT_DRAMA_SOURCES
        self._last_fetch_time: Dict[str, float] = {}

    def fetch_hot_list(self, platform: str = "all", limit: int = 50) -> List[Dict]:
        """获取短剧热榜列表

        Args:
            platform: 平台筛选 (douyin/kuaishou/bilibili/all)
            limit: 最大返回条数

        Returns:
            短剧数据列表
        """
        dramas = []

        # 策略1: 尝试从配置的API源抓取
        for source in self._sources:
            if source.get("enabled"):
                try:
                    fetched = self._fetch_from_api(source, platform, limit)
                    if fetched:
                        dramas.extend(fetched)
                        self._last_fetch_time[source["name"]] = time.time()
                        logger.info(
                            f"[DramaWebScraper] 从 {source['name']} 获取 {len(fetched)} 条数据"
                        )
                except Exception as e:
                    logger.debug(f"[DramaWebScraper] {source['name']} 抓取失败: {e}")

        # 策略2: 从本地缓存文件加载
        if not dramas:
            dramas = self._load_from_cache(platform, limit)
            if dramas:
                logger.info(
                    f"[DramaWebScraper] 从缓存加载 {len(dramas)} 条数据"
                )

        # 策略3: 使用内置标题池生成最小数据集
        if not dramas:
            dramas = self._generate_default(platform, limit)
            logger.info(
                f"[DramaWebScraper] 使用内置数据生成 {len(dramas)} 条"
            )

        return dramas[:limit]

    def _fetch_from_api(self, source: Dict, platform: str, limit: int) -> List[Dict]:
        """从API源抓取数据"""
        url = source["url"]
        if platform != "all":
            url = f"{url}?platform={platform}&limit={limit}"

        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })

        try:
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return self._parse_response(data, source.get("parser", "json"))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            logger.debug(f"[DramaWebScraper] API请求失败: {e}")
            return []
        except Exception as e:
            logger.warning(f"[DramaWebScraper] 未知错误: {e}")
            return []

    def _parse_response(self, data, parser_type: str) -> List[Dict]:
        """解析API响应为标准格式"""
        if parser_type == "json":
            items = data if isinstance(data, list) else data.get("data", data.get("list", []))
            result = []
            for item in items:
                result.append({
                    "title": str(item.get("title", item.get("name", ""))),
                    "platform": str(item.get("platform", "unknown")),
                    "category": str(item.get("category", item.get("genre", "其他"))),
                    "episodes": int(item.get("episodes", item.get("total_episodes", 100))),
                    "views": str(item.get("views", item.get("play_count", "未知"))),
                    "commission": str(item.get("commission", "—")),
                    "heat": int(item.get("heat", item.get("score", item.get("hot", 50)))),
                    "type": "drama",
                    "weight": float(item.get("weight", 0.5)),
                    "source": "api",
                })
            return result
        return []

    def _load_from_cache(self, platform: str, limit: int) -> List[Dict]:
        """从本地JSON缓存加载"""
        if not os.path.exists(self._cache_file):
            return []

        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)

            # 检查缓存时效
            last_updated = cache.get("last_updated", "")
            if last_updated:
                try:
                    cache_time = datetime.fromisoformat(last_updated)
                    if datetime.now() - cache_time > timedelta(seconds=self._cache_ttl * 24):
                        logger.debug("[DramaWebScraper] 缓存已过期但仍使用")
                except ValueError as e:
                    logger.debug(f"[DramaWebScraper] 缓存时间戳解析失败: {e}")

            dramas = cache.get("dramas", [])
            if platform != "all":
                dramas = [d for d in dramas if d.get("platform") == platform]
            out = []
            for d in dramas[:limit]:
                item = dict(d)
                item.setdefault("source", "cache")
                out.append(item)
            return out
        except (json.JSONDecodeError, IOError) as e:
            logger.debug(f"[DramaWebScraper] 缓存读取失败: {e}")
            return []

    def _generate_default(self, platform: str, limit: int) -> List[Dict]:
        """生成默认数据集 (内置标题池)"""
        import random
        random.seed(42)  # 确定性随机，保证每次相同输入产生相同结果

        platforms_list = ["douyin", "kuaishou", "bilibili"]
        categories = ["甜宠", "逆袭", "古装", "都市", "年代", "科幻", "异能", "穿书", "豪门", "修仙"]
        result = []

        for i, title in enumerate(_BUILTIN_TITLES):
            if platform != "all" and platforms_list[i % len(platforms_list)] != platform:
                continue
            result.append({
                "title": title,
                "platform": platforms_list[i % len(platforms_list)],
                "category": categories[i % len(categories)],
                "episodes": random.randint(40, 120),
                "views": f"{random.randint(500, 5000)}万",
                "commission": f"¥{random.randint(1, 15)}.{random.randint(1, 9)}万",
                "heat": random.randint(10, 95),
                "type": "drama",
                "weight": round(random.uniform(0.1, 0.95), 2),
                "source": "builtin",
            })
            if len(result) >= limit:
                break

        return result

    def refresh_cache(self, dramas: List[Dict]):
        """更新本地缓存"""
        try:
            cache_data = {
                "version": "auto",
                "last_updated": datetime.now().isoformat(),
                "description": "DramaWebScraper 自动缓存",
                "source": "web_scraper",
                "total": len(dramas),
                "dramas": dramas,
            }
            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[DramaWebScraper] 缓存已刷新: {len(dramas)} 条")
        except IOError as e:
            logger.warning(f"[DramaWebScraper] 缓存写入失败: {e}")

    def get_source_health(self) -> Dict[str, bool]:
        """检查各数据源健康状态"""
        health = {}
        for source in self._sources:
            name = source["name"]
            last = self._last_fetch_time.get(name, 0)
            health[name] = (time.time() - last) < self._cache_ttl
        health["cache"] = os.path.exists(self._cache_file)
        health["builtin"] = True  # 内置数据始终可用
        return health


# 模块级单例
drama_web_scraper = DramaWebScraper()
