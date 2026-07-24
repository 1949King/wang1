import os
import threading
from typing import Dict, List, Optional, Any

from .base_repository import BaseRepository


class AssetRepository(BaseRepository):
    """素材数据持久化"""

    def __init__(self, assets_dir: str):
        self.assets_dir = assets_dir
        db_path = os.path.join(assets_dir, "assets.json")
        super().__init__(db_path)

    def get_by_category(self, category: str) -> Dict[str, Any]:
        """根据类别获取素材"""
        return self._data.get(category, {})

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取素材"""
        for category_assets in self._data.values():
            if asset_id in category_assets:
                return category_assets[asset_id]
        return None

    def save_asset(self, category: str, asset_id: str, asset_data: Dict[str, Any]) -> bool:
        """保存素材"""
        with self._lock:
            if category not in self._data:
                self._data[category] = {}
            self._data[category][asset_id] = asset_data
            return self._save_data()

    def delete_asset(self, category: str, asset_id: str) -> bool:
        """删除素材"""
        with self._lock:
            if category in self._data and asset_id in self._data[category]:
                del self._data[category][asset_id]
                return self._save_data()
        return False

    def update_asset(self, asset_id: str, updates: Dict[str, Any]) -> bool:
        """更新素材"""
        with self._lock:
            for category, assets in self._data.items():
                if asset_id in assets:
                    assets[asset_id].update(updates)
                    return self._save_data()
        return False

    def list_assets(self, category: Optional[str] = None, tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """列出素材"""
        assets = []
        categories = [category] if category else self._data.keys()

        for cat in categories:
            if cat in self._data:
                for asset_info in self._data[cat].values():
                    if tags:
                        if any(tag in asset_info.get("tags", []) for tag in tags):
                            assets.append(asset_info)
                    else:
                        assets.append(asset_info)

        assets.sort(key=lambda x: x.get("imported_at", ""), reverse=True)
        return assets

    def search_assets(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索素材"""
        results = []
        keyword = keyword.lower()

        for category, assets in self._data.items():
            for asset_info in assets.values():
                if (
                    keyword in asset_info.get("name", "").lower() or
                    keyword in asset_info.get("path", "").lower() or
                    any(keyword in tag.lower() for tag in asset_info.get("tags", []))
                ):
                    results.append(asset_info)

        return results

    def get_categories(self) -> List[str]:
        """获取所有类别"""
        return list(self._data.keys())

    def get_tags(self, category: Optional[str] = None) -> List[str]:
        """获取所有标签"""
        tags = set()
        categories = [category] if category else self._data.keys()

        for cat in categories:
            if cat in self._data:
                for asset_info in self._data[cat].values():
                    tags.update(asset_info.get("tags", []))

        return list(tags)
