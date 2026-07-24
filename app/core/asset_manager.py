import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

from .asset_repository import AssetRepository
from .project_repository import ProjectRepository
from .metadata_extractor import MetadataExtractor
from .preview_generator import PreviewGenerator
from .cache_manager_refactor import CacheManager
from .file_operator import FileOperator


class AssetManager:
    """
    素材管理系统
    负责素材的导入、组织、预览、管理等功能
    """

    def __init__(self):
        """初始化素材管理器"""
        self.assets_dir = "assets"
        self.cache_dir = os.path.join(self.assets_dir, "cache")

        FileOperator.ensure_dir(self.assets_dir)

        self.asset_repository = AssetRepository(self.assets_dir)
        self.project_repository = ProjectRepository(self.assets_dir)
        self.metadata_extractor = MetadataExtractor()
        self.preview_generator = PreviewGenerator(self.cache_dir)
        self.cache_manager = CacheManager(self.cache_dir)
        self.file_operator = FileOperator()

    def import_asset(self, file_path: str, category: str = "videos", tags: List[str] = None) -> Dict[str, Any]:
        """导入素材"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        asset_id = f"{category}_{int(time.time())}_{os.path.basename(file_path)}"
        asset_id = asset_id.replace(" ", "_")

        category_dir = os.path.join(self.assets_dir, category)
        FileOperator.ensure_dir(category_dir)

        asset_name = os.path.basename(file_path)
        asset_path = os.path.join(category_dir, asset_name)

        if os.path.exists(asset_path):
            base_name, ext = os.path.splitext(asset_name)
            asset_name = f"{base_name}_{int(time.time())}{ext}"
            asset_path = os.path.join(category_dir, asset_name)

        self.file_operator.copy_file(file_path, asset_path)

        asset_info = {
            "id": asset_id,
            "name": os.path.splitext(asset_name)[0],
            "path": asset_path,
            "category": category,
            "tags": tags or [],
            "imported_at": datetime.now().isoformat(),
            "file_size": self.file_operator.get_file_size(asset_path),
            "file_extension": os.path.splitext(file_path)[1],
            "metadata": self.metadata_extractor.extract_metadata(asset_path)
        }

        self.asset_repository.save_asset(category, asset_id, asset_info)

        preview_path = self.preview_generator.generate_preview(asset_path, asset_id)
        if preview_path:
            asset_info["preview_path"] = preview_path
            self.asset_repository.save_asset(category, asset_id, asset_info)

        return asset_info

    def import_folder(self, folder_path: str, category: str = "videos", tags: List[str] = None) -> List[Dict[str, Any]]:
        """导入整个文件夹的素材"""
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise FileNotFoundError(f"文件夹不存在: {folder_path}")

        imported_assets = []
        supported_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.mp3', '.wav', '.flac', '.jpg', '.jpeg', '.png', '.gif', '.srt', '.ass', '.vtt']

        for root, _, files in os.walk(folder_path):
            for file_name in files:
                ext = os.path.splitext(file_name)[1].lower()
                if ext in supported_extensions:
                    file_path = os.path.join(root, file_name)
                    try:
                        asset_info = self.import_asset(file_path, category, tags)
                        imported_assets.append(asset_info)
                    except Exception as e:
                        print(f"导入文件失败 {file_path}: {e}")

        return imported_assets

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """获取素材信息"""
        return self.asset_repository.get_asset(asset_id)

    def list_assets(self, category: str = None, tags: List[str] = None) -> List[Dict[str, Any]]:
        """列出素材"""
        return self.asset_repository.list_assets(category, tags)

    def update_asset(self, asset_id: str, **kwargs) -> bool:
        """更新素材信息"""
        return self.asset_repository.update_asset(asset_id, kwargs)

    def delete_asset(self, asset_id: str) -> bool:
        """删除素材"""
        asset_info = self.get_asset(asset_id)
        if not asset_info:
            return False

        self.file_operator.delete_file(asset_info["path"])

        preview_path = asset_info.get("preview_path")
        if preview_path:
            self.file_operator.delete_file(preview_path)

        return self.asset_repository.delete_asset(asset_info["category"], asset_id)

    def search_assets(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索素材"""
        return self.asset_repository.search_assets(keyword)

    def organize_assets(self, category: str, sort_by: str = "imported_at") -> List[Dict[str, Any]]:
        """组织素材"""
        assets = self.asset_repository.get_by_category(category)
        if not assets:
            return []

        sorted_assets = list(assets.values())
        if sort_by in ["name", "imported_at", "file_size"]:
            sorted_assets.sort(key=lambda x: x.get(sort_by, ""), reverse=True)

        return sorted_assets

    def get_asset_categories(self) -> List[str]:
        """获取素材类别列表"""
        return self.asset_repository.get_categories()

    def get_asset_tags(self, category: str = None) -> List[str]:
        """获取素材标签列表"""
        return self.asset_repository.get_tags(category)

    def generate_preview(self, asset_id: str) -> Optional[str]:
        """生成素材预览"""
        asset_info = self.get_asset(asset_id)
        if not asset_info:
            return None

        preview_path = self.preview_generator.generate_preview(asset_info["path"], asset_id)
        if preview_path:
            asset_info["preview_path"] = preview_path
            self.asset_repository.save_asset(asset_info["category"], asset_id, asset_info)

        return preview_path

    def analyze_asset(self, asset_id: str) -> Dict[str, Any]:
        """深度分析素材"""
        asset_info = self.get_asset(asset_id)
        if not asset_info:
            return {"error": "素材不存在"}

        analysis = {
            "asset_id": asset_id,
            "basic_info": asset_info,
            "technical_info": self.metadata_extractor.analyze_asset(asset_info["path"])["technical_info"]
        }

        return analysis

    def clean_cache(self) -> bool:
        """清理缓存"""
        return self.cache_manager.clean_cache()

    def create_project(self, project_name: str, description: str = "") -> Dict[str, Any]:
        """创建项目"""
        return self.project_repository.create_project(project_name, description)

    def add_asset_to_project(self, project_id: str, asset_id: str) -> bool:
        """将素材添加到项目"""
        if not self.get_asset(asset_id):
            return False
        return self.project_repository.add_asset_to_project(project_id, asset_id)

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """获取项目信息"""
        return self.project_repository.get_project(project_id)

    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有项目"""
        return self.project_repository.list_projects()

    def backup_project(self, project_id: str) -> Optional[str]:
        """备份项目"""
        return self.project_repository.backup_project(project_id)

    def restore_project(self, project_id: str, version_id: str) -> bool:
        """恢复项目到指定版本"""
        return self.project_repository.restore_project(project_id, version_id)


asset_manager = AssetManager()


def import_asset(file_path: str, category: str = "videos", tags: List[str] = None) -> Dict[str, Any]:
    """兼容模块级调用，转发到全局 AssetManager 单例导入素材。"""
    return asset_manager.import_asset(file_path, category, tags)


def get_asset(asset_id: str) -> Optional[Dict[str, Any]]:
    """兼容模块级调用，转发到全局 AssetManager 单例获取素材。"""
    return asset_manager.get_asset(asset_id)
