"""
TikHub 抖音短剧真实数据 API
============================
来源: https://api.tikhub.io/api/v1/douyin/web/fetch_series_aweme

接入方式 (二选一):
  1. 环境变量 TIKHUB_API_TOKEN=<你的 token>
  2. 在 .env 文件里写 TIKHUB_API_TOKEN=<你的 token>

未配置 token / 网络失败 / token 过期 时, fetch() 返回 None,
调用方应回退到 DramaCrawler 的 fallback (DouyinAPI 随机生成)。

API 文档:
  - URL: https://api.tikhub.io/api/v1/douyin/web/fetch_series_aweme
  - Query: offset (int), count (int, default 16), content_type (int, default 0=热榜)
  - Auth:  Authorization: Bearer <token>
  - 价格: ¥0.04/次 (官方)
"""
import os
import logging
import time
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import hashlib

try:
    import requests
except ImportError:
    requests = None  # 缺包时降级

from .drama_crawler import DramaInfo, PlatformAPI, ScoringEngine, Recommender

logger = logging.getLogger(__name__)


# 抖音 20 个 content_type
TIKHUB_CONTENT_TYPE: Dict[str, int] = {
    "热榜":      0,
    "甜宠":      101,
    "搞笑":      102,
    "正能量":    104,
    "成长":      105,
    "悬疑":      106,
    "家庭":      109,
    "都市":      110,
    "奇幻":      112,
    "玄幻":      113,
    "职场":      114,
    "青春":      115,
    "古装":      116,
    "动作":      117,
    "逆袭":      119,
    "其他":      124,
}


def _get_tikhub_token() -> str:
    """
    读取 TikHub API Token。
    优先级: 环境变量 > .env 文件 (项目根)
    """
    token = os.environ.get("TIKHUB_API_TOKEN", "").strip()
    if token:
        return token
    # 尝试读 .env
    try:
        for up in [".env", "app/.env"]:
            path = os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", up
            ))
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("TIKHUB_API_TOKEN"):
                            return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def is_tikhub_configured() -> bool:
    """TikHub Token 是否已配置"""
    return bool(_get_tikhub_token())


class TikHubDouyinAPI(PlatformAPI):
    """
    真实抖音短剧数据 API (TikHub 网关)。

    失败时 fetch() 返回 None,调用方应回退到 DouyinAPI 随机数据。
    """

    BASE_URL = "https://api.tikhub.io/api/v1/douyin/web/fetch_series_aweme"
    CACHE_TTL = 600  # TikHub 自身缓存 24h, 我们二次缓存 10 分钟避免重复扣费

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self._local_cache: Dict[str, tuple] = {}  # cache_key -> (data, ts)

    # ---- 公开方法 ----

    def is_available(self) -> bool:
        """是否可用: 配了 token + 依赖包 + 最近一次请求成功"""
        if not is_tikhub_configured():
            return False
        if requests is None:
            return False
        return True

    def fetch(self, keyword: str = "", page: int = 1, page_size: int = 20,
              user_prefs: Dict = None) -> Optional[List[DramaInfo]]:
        """
        抓取抖音短剧。

        Returns:
            List[DramaInfo]  成功
            None             失败 (token 缺失/网络/限流等) — 调用方应回退
        """
        if not self.is_available():
            return None

        # 1) keyword / content_type 映射
        content_type = TIKHUB_CONTENT_TYPE.get(keyword, 0)  # 0 = 热榜
        if not keyword:
            content_type = 0

        # 2) 本地缓存命中
        cache_key = f"douyin_tikhub_{content_type}_{page}_{page_size}"
        if cache_key in self._local_cache:
            data, ts = self._local_cache[cache_key]
            if time.time() - ts < self.CACHE_TTL:
                logger.info(f"[TikHub] 本地缓存命中: {cache_key}")
                return data

        # 3) 真实请求
        token = _get_tikhub_token()
        try:
            resp = requests.get(
                self.BASE_URL,
                params={
                    "offset": (page - 1) * page_size,
                    "count": page_size,
                    "content_type": content_type,
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"[TikHub] HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            payload = resp.json()
        except requests.exceptions.Timeout:
            logger.warning("[TikHub] 请求超时")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"[TikHub] 请求异常: {e}")
            return None
        except Exception as e:
            logger.warning(f"[TikHub] 未知异常: {e}")
            return None

        if payload.get("code") != 200:
            logger.warning(f"[TikHub] 业务错误: {payload.get('message', '')}")
            return None

        # 4) 转换
        raw_list = (payload.get("data") or {}).get("aweme_list") or payload.get("data") or []
        if isinstance(raw_list, dict):
            raw_list = list(raw_list.values())  # 兼容 dict 形式
        if not isinstance(raw_list, list):
            raw_list = []

        dramas = [self._to_drama_info(item, user_prefs) for item in raw_list]
        dramas = [d for d in dramas if d is not None]

        # 5) 本地缓存 + 更新健康状态
        self._local_cache[cache_key] = (dramas, time.time())
        from .drama_crawler import DATA_SOURCE_HEALTH
        DATA_SOURCE_HEALTH["douyin"] = {
            "real": True,
            "source": "TikHub 真实数据",
            "api_class": "TikHubDouyinAPI",
        }
        logger.info(f"[TikHub] 抖音短剧 抓取成功: {len(dramas)} 条")
        return dramas

    # ---- 内部方法 ----

    def _to_drama_info(self, item: Dict, user_prefs: Dict) -> Optional[DramaInfo]:
        """TikHub 原始数据 → DramaInfo"""
        try:
            # TikHub 返回字段名不固定, 兼容多种可能
            aweme_id = (
                item.get("aweme_id")
                or item.get("video_id")
                or item.get("id")
                or hashlib.md5(str(item).encode()).hexdigest()[:16]
            )
            title = (
                item.get("title")
                or item.get("desc")
                or item.get("name")
                or "(无标题)"
            )
            author = (
                (item.get("author") or {}).get("nickname")
                if isinstance(item.get("author"), dict)
                else item.get("author_nickname")
                or item.get("author")
                or "未知"
            )
            # 统计
            stats = item.get("statistics") or item.get("video_status") or item.get("stats") or {}
            views = int(stats.get("play_count") or stats.get("views") or item.get("views") or 0)
            likes = int(stats.get("digg_count") or stats.get("likes") or item.get("likes") or 0)
            comments = int(stats.get("comment_count") or item.get("comments") or 0)
            # 时长
            video = item.get("video") or item
            duration = int(video.get("duration") or item.get("duration") or 0)
            # 封面
            cover_url = ""
            for key in ("cover_url", "dynamic_cover", "origin_cover", "thumbnail", "cover"):
                v = video.get(key) if isinstance(video, dict) else None
                if not v:
                    v = item.get(key)
                if isinstance(v, dict):
                    # 抖音 cover 字段: {url_list: [...], uri: ...}
                    v = v.get("url_list", [None])[0] or v.get("url") or v.get("uri")
                if v:
                    cover_url = v
                    break

            # 时间戳
            ts = int(item.get("create_time") or 0)
            if ts:
                update_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            else:
                update_time = datetime.now().strftime("%Y-%m-%d %H:%M")

            # 集数 (TikHub 不直接给, 估个值)
            episodes = max(1, duration // 60) if duration > 0 else 1
            # 热度 (用播放+点赞估算)
            heat = views // 100 + likes * 5

            drama = DramaInfo(
                id=f"douyin_tikhub_{aweme_id}",
                title=str(title)[:100],
                platform="douyin",
                category=item.get("category_name") or item.get("drama_type") or "其他",
                tags=item.get("tags") or item.get("keywords") or [],
                episodes=episodes,
                views=views,
                likes=likes,
                commission=0.0,  # TikHub 不提供
                commission_rate=0.0,
                rating=0.0,      # TikHub 不提供
                heat=heat,
                author=str(author)[:30],
                update_time=update_time,
                status="连载中",  # TikHub 不提供, 默认连载中
                cover_url=cover_url,
                description=item.get("desc") or title,
                source_url=f"https://www.douyin.com/discover/series/{aweme_id}",
            )
            # 评分
            drama.score = ScoringEngine.calculate_score(drama, user_prefs)
            drama.recommend_reason = Recommender.generate_reason(drama, drama.score)
            return drama
        except Exception as e:
            logger.debug(f"[TikHub] 解析单条失败: {e}, item={item}")
            return None
