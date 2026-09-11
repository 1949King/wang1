# -*- coding: utf-8 -*-
"""短剧筛选爬虫接口壳。功能已卸，不爬、不造假榜单。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

UNLOADED_MSG = "插件功能已卸，仅保留接口"

DATA_SOURCE_HEALTH: Dict[str, Dict[str, Any]] = {
    "douyin": {"real": False, "source": UNLOADED_MSG, "api_class": None},
    "kuaishou": {"real": False, "source": UNLOADED_MSG, "api_class": None},
    "bilibili": {"real": False, "source": UNLOADED_MSG, "api_class": None},
}

DATA_SOURCE_HELP = UNLOADED_MSG


def get_data_source_health() -> Dict[str, Dict]:
    return DATA_SOURCE_HEALTH.copy()


@dataclass
class DramaInfo:
    """短剧条目（接口保留，供 workflow / 回流签名使用）。"""
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


class ScoringEngine:
    CATEGORY_BOOST: Dict[str, float] = {}
    PLATFORM_BOOST: Dict[str, float] = {}

    @classmethod
    def calculate_score(cls, drama: DramaInfo, user_prefs: Dict = None) -> float:
        return 0.0


class KeywordMatcher:
    @classmethod
    def match(cls, *args, **kwargs) -> float:
        return 0.0


class HeatPredictor:
    @classmethod
    def predict(cls, *args, **kwargs) -> Dict[str, Any]:
        return {"success": False, "error": UNLOADED_MSG}


class Recommender:
    @classmethod
    def generate_reason(cls, drama: DramaInfo, score: float) -> str:
        return UNLOADED_MSG


class PlatformAPI:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def fetch(self, keyword: str = "", page: int = 1, page_size: int = 20, **kwargs) -> List[DramaInfo]:
        return []

    def is_available(self) -> bool:
        return False


class DouyinAPI(PlatformAPI):
    pass


class KuaishouAPI(PlatformAPI):
    pass


class BilibiliAPI(PlatformAPI):
    pass


class DramaCrawler:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_inited", False):
            return
        self._inited = True
        self._cache: Dict[str, Any] = {}
        self._user_preferences: Dict[str, Any] = {}
        self._favorites: List[str] = []
        self._view_history: List[str] = []
        self._last_fetch_errors: List[str] = [UNLOADED_MSG]
        self._last_data_source: List[Any] = []

    def get_platforms(self) -> Dict[str, Dict]:
        return {}

    def get_categories(self) -> Dict[str, str]:
        return {}

    def get_total_drama_count(self) -> int:
        return 0

    def set_user_preferences(self, prefs: Dict):
        self._user_preferences = dict(prefs or {})

    def add_to_history(self, drama_id: str):
        return None

    def add_to_favorites(self, drama_id: str):
        return None

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
        min_views: int = 0,
    ) -> List[DramaInfo]:
        if callback:
            callback([])
        return []

    def fetch_dramas_async(self, *args, **kwargs) -> List[DramaInfo]:
        return []

    def download_drama(self, drama_info: Any) -> Dict[str, Any]:
        title = getattr(drama_info, "title", "") or ""
        return {
            "success": False,
            "error": UNLOADED_MSG,
            "video_path": "",
            "title": title,
        }

    def get_recommendations(self, count: int = 10) -> List[DramaInfo]:
        return []

    def get_hot_dramas(self, platform: str = "all", count: int = 10) -> List[DramaInfo]:
        return []

    def get_high_commission(self, min_commission: float = 20000, count: int = 10) -> List[DramaInfo]:
        return []

    def predict_heat(self, drama_id: str) -> Dict[str, Any]:
        return {"success": False, "error": UNLOADED_MSG}

    def get_platform_stats(self, platform: str) -> Dict[str, Any]:
        return {}

    def get_all_platform_stats(self) -> List[Dict[str, Any]]:
        return []

    def get_real_time_stats(self) -> Dict[str, Any]:
        return {}

    def search_drama(self, drama_id: str) -> Optional[DramaInfo]:
        return None

    def get_drama_episodes(self, drama_id: str) -> List[Dict]:
        return []

    def clear_cache(self):
        self._cache.clear()

    def get_last_errors(self) -> List[str]:
        return list(self._last_fetch_errors)

    def get_data_freshness(self) -> Dict:
        return {
            "has_static": False,
            "is_pure_fallback": False,
            "sources": [],
            "unloaded": True,
            "message": UNLOADED_MSG,
        }

    def add_to_history_persisted(self, drama_id: str, max_len: int = 100):
        return None

    def add_to_favorites_persisted(self, drama_id: str):
        return None

    def remove_from_favorites_persisted(self, drama_id: str):
        return None

    def load_persisted_prefs(self):
        return None


drama_crawler = DramaCrawler()
