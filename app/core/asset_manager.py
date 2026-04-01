import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import shutil
import subprocess
import threading


class AssetManager:
    """
    素材管理系统
    负责素材的导入、组织、预览、管理等功能
    """
    
    def __init__(self):
        """初始化素材管理器"""
        self.assets_dir = "assets"
        self.cache_dir = os.path.join(self.assets_dir, "cache")
        self.assets_db = os.path.join(self.assets_dir, "assets.json")
        self.projects_db = os.path.join(self.assets_dir, "projects.json")
        self.assets = {}
        self.projects = {}
        self._lock = threading.Lock()
        
        # 创建目录
        os.makedirs(self.assets_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # 加载素材数据库
        self._load_assets()
        # 加载项目数据库
        self._load_projects()
    
    def _load_assets(self):
        """加载素材数据库"""
        if os.path.exists(self.assets_db):
            try:
                with open(self.assets_db, "r", encoding="utf-8") as f:
                    self.assets = json.load(f)
            except Exception as e:
                print(f"加载素材数据库失败: {e}")
                self.assets = {}
    
    def _save_assets(self):
        """保存素材数据库"""
        try:
            with open(self.assets_db, "w", encoding="utf-8") as f:
                json.dump(self.assets, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存素材数据库失败: {e}")
            return False
    
    def _load_projects(self):
        """加载项目数据库"""
        if os.path.exists(self.projects_db):
            try:
                with open(self.projects_db, "r", encoding="utf-8") as f:
                    self.projects = json.load(f)
            except Exception as e:
                print(f"加载项目数据库失败: {e}")
                self.projects = {}
    
    def _save_projects(self):
        """保存项目数据库"""
        try:
            with open(self.projects_db, "w", encoding="utf-8") as f:
                json.dump(self.projects, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存项目数据库失败: {e}")
            return False
    
    def import_folder(self, folder_path: str, category: str = "videos", tags: List[str] = None) -> List[Dict[str, Any]]:
        """
        导入整个文件夹的素材
        
        Args:
            folder_path: 文件夹路径
            category: 素材类别
            tags: 素材标签
            
        Returns:
            导入的素材信息列表
        """
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise FileNotFoundError(f"文件夹不存在: {folder_path}")
        
        imported_assets = []
        supported_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.mp3', '.wav', '.flac', '.jpg', '.jpeg', '.png', '.gif', '.srt', '.ass', '.vtt']
        
        with self._lock:
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
    
    def analyze_asset(self, asset_id: str) -> Dict[str, Any]:
        """
        深度分析素材
        
        Args:
            asset_id: 素材ID
            
        Returns:
            分析结果
        """
        asset_info = self.get_asset(asset_id)
        if not asset_info:
            return {"error": "素材不存在"}
        
        analysis = {
            "asset_id": asset_id,
            "basic_info": asset_info,
            "technical_info": {}
        }
        
        # 分析视频/音频文件
        if asset_info.get("file_extension") in ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.mp3', '.wav', '.flac']:
            try:
                cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", asset_info["path"]]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    ffprobe_data = json.loads(result.stdout)
                    analysis["technical_info"]["ffprobe"] = ffprobe_data
                    
                    # 提取关键信息
                    if "streams" in ffprobe_data:
                        for stream in ffprobe_data["streams"]:
                            if stream.get("codec_type") == "video":
                                analysis["technical_info"]["video"] = {
                                    "codec": stream.get("codec_name"),
                                    "resolution": f"{stream.get('width')}x{stream.get('height')}",
                                    "frame_rate": stream.get("r_frame_rate"),
                                    "bit_rate": stream.get("bit_rate")
                                }
                            elif stream.get("codec_type") == "audio":
                                analysis["technical_info"]["audio"] = {
                                    "codec": stream.get("codec_name"),
                                    "sample_rate": stream.get("sample_rate"),
                                    "channels": stream.get("channels"),
                                    "bit_rate": stream.get("bit_rate")
                                }
            except Exception as e:
                print(f"分析素材失败: {e}")
        
        return analysis
    
    def create_project(self, project_name: str, description: str = "") -> Dict[str, Any]:
        """
        创建项目
        
        Args:
            project_name: 项目名称
            description: 项目描述
            
        Returns:
            项目信息
        """
        project_id = f"project_{int(time.time())}"
        project_info = {
            "id": project_id,
            "name": project_name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "assets": [],
            "versions": []
        }
        
        with self._lock:
            self.projects[project_id] = project_info
            self._save_projects()
        
        return project_info
    
    def add_asset_to_project(self, project_id: str, asset_id: str) -> bool:
        """
        将素材添加到项目
        
        Args:
            project_id: 项目ID
            asset_id: 素材ID
            
        Returns:
            是否添加成功
        """
        with self._lock:
            if project_id in self.projects and self.get_asset(asset_id):
                if asset_id not in self.projects[project_id]["assets"]:
                    self.projects[project_id]["assets"].append(asset_id)
                    self.projects[project_id]["updated_at"] = datetime.now().isoformat()
                    return self._save_projects()
        return False
    
    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        获取项目信息
        
        Args:
            project_id: 项目ID
            
        Returns:
            项目信息
        """
        return self.projects.get(project_id)
    
    def list_projects(self) -> List[Dict[str, Any]]:
        """
        列出所有项目
        
        Returns:
            项目列表
        """
        return list(self.projects.values())
    
    def backup_project(self, project_id: str) -> Optional[str]:
        """
        备份项目
        
        Args:
            project_id: 项目ID
            
        Returns:
            备份文件路径
        """
        project = self.get_project(project_id)
        if not project:
            return None
        
        backup_dir = os.path.join(self.assets_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_path = os.path.join(backup_dir, f"{project_id}_{int(time.time())}.json")
        
        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(project, f, ensure_ascii=False, indent=2)
            
            # 添加版本记录
            with self._lock:
                version_info = {
                    "version_id": f"v{len(project.get('versions', [])) + 1}",
                    "backup_path": backup_path,
                    "created_at": datetime.now().isoformat(),
                    "description": f"自动备份"
                }
                if "versions" not in project:
                    project["versions"] = []
                project["versions"].append(version_info)
                self._save_projects()
            
            return backup_path
        except Exception as e:
            print(f"备份项目失败: {e}")
            return None
    
    def restore_project(self, project_id: str, version_id: str) -> bool:
        """
        恢复项目到指定版本
        
        Args:
            project_id: 项目ID
            version_id: 版本ID
            
        Returns:
            是否恢复成功
        """
        project = self.get_project(project_id)
        if not project:
            return False
        
        for version in project.get("versions", []):
            if version["version_id"] == version_id:
                backup_path = version["backup_path"]
                if os.path.exists(backup_path):
                    try:
                        with open(backup_path, "r", encoding="utf-8") as f:
                            restored_project = json.load(f)
                        
                        with self._lock:
                            self.projects[project_id] = restored_project
                            self.projects[project_id]["updated_at"] = datetime.now().isoformat()
                            return self._save_projects()
                    except Exception as e:
                        print(f"恢复项目失败: {e}")
        return False
    
    def clean_cache(self) -> bool:
        """
        清理缓存
        
        Returns:
            是否清理成功
        """
        try:
            for file in os.listdir(self.cache_dir):
                file_path = os.path.join(self.cache_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            return True
        except Exception as e:
            print(f"清理缓存失败: {e}")
            return False
    
    def import_asset(self, file_path: str, category: str = "videos", tags: List[str] = None) -> Dict[str, Any]:
        """
        导入素材
        
        Args:
            file_path: 素材文件路径
            category: 素材类别 (videos, audio, images, etc.)
            tags: 素材标签
            
        Returns:
            素材信息字典
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 生成素材ID
        asset_id = f"{category}_{int(time.time())}_{os.path.basename(file_path)}"
        asset_id = asset_id.replace(" ", "_")
        
        # 素材类别目录
        category_dir = os.path.join(self.assets_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        
        # 复制文件到素材目录
        asset_name = os.path.basename(file_path)
        asset_path = os.path.join(category_dir, asset_name)
        
        # 如果文件已存在，添加时间戳
        if os.path.exists(asset_path):
            base_name, ext = os.path.splitext(asset_name)
            asset_name = f"{base_name}_{int(time.time())}{ext}"
            asset_path = os.path.join(category_dir, asset_name)
        
        # 复制文件
        import shutil
        shutil.copy2(file_path, asset_path)
        
        # 获取素材信息
        asset_info = {
            "id": asset_id,
            "name": os.path.splitext(asset_name)[0],
            "path": asset_path,
            "category": category,
            "tags": tags or [],
            "imported_at": datetime.now().isoformat(),
            "file_size": os.path.getsize(asset_path),
            "file_extension": os.path.splitext(file_path)[1],
            "metadata": self._extract_metadata(asset_path)
        }
        
        # 添加到素材数据库
        if category not in self.assets:
            self.assets[category] = {}
        self.assets[category][asset_id] = asset_info
        
        # 保存数据库
        self._save_assets()
        
        # 生成预览
        self.generate_preview(asset_id)
        
        return asset_info
    
    def _extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        提取素材元数据
        
        Args:
            file_path: 素材文件路径
            
        Returns:
            元数据字典
        """
        metadata = {}
        
        # 尝试使用 ffprobe 提取视频/音频元数据
        try:
            import subprocess
            import json
            
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                ffprobe_data = json.loads(result.stdout)
                metadata["ffprobe"] = ffprobe_data
        except Exception as e:
            print(f"提取元数据失败: {e}")
        
        return metadata
    
    def generate_preview(self, asset_id: str) -> Optional[str]:
        """
        生成素材预览
        
        Args:
            asset_id: 素材ID
            
        Returns:
            预览文件路径，如果生成失败则返回None
        """
        # 查找素材
        asset_info = self.get_asset(asset_id)
        if not asset_info:
            return None
        
        # 预览文件路径
        preview_path = os.path.join(self.cache_dir, f"{asset_id}_preview.jpg")
        
        # 生成预览
        try:
            import subprocess
            
            # 使用 ffmpeg 生成视频预览
            cmd = ["ffmpeg", "-i", asset_info["path"], "-ss", "00:00:01", "-vframes", "1", "-q:v", "2", preview_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                asset_info["preview_path"] = preview_path
                self._save_assets()
                return preview_path
        except Exception as e:
            print(f"生成预览失败: {e}")
        
        return None
    
    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """
        获取素材信息
        
        Args:
            asset_id: 素材ID
            
        Returns:
            素材信息字典，如果素材不存在则返回None
        """
        for category, assets in self.assets.items():
            if asset_id in assets:
                return assets[asset_id]
        return None
    
    def list_assets(self, category: str = None, tags: List[str] = None) -> List[Dict[str, Any]]:
        """
        列出素材
        
        Args:
            category: 素材类别，如果为None则列出所有类别
            tags: 标签过滤，如果为None则不过滤
            
        Returns:
            素材列表
        """
        assets = []
        
        categories = [category] if category else self.assets.keys()
        
        for cat in categories:
            if cat in self.assets:
                for asset_info in self.assets[cat].values():
                    # 标签过滤
                    if tags:
                        if any(tag in asset_info.get("tags", []) for tag in tags):
                            assets.append(asset_info)
                    else:
                        assets.append(asset_info)
        
        # 按导入时间排序
        assets.sort(key=lambda x: x.get("imported_at", ""), reverse=True)
        return assets
    
    def update_asset(self, asset_id: str, **kwargs) -> bool:
        """
        更新素材信息
        
        Args:
            asset_id: 素材ID
            **kwargs: 要更新的字段
            
        Returns:
            是否更新成功
        """
        for category, assets in self.assets.items():
            if asset_id in assets:
                assets[asset_id].update(kwargs)
                return self._save_assets()
        return False
    
    def delete_asset(self, asset_id: str) -> bool:
        """
        删除素材
        
        Args:
            asset_id: 素材ID
            
        Returns:
            是否删除成功
        """
        for category, assets in self.assets.items():
            if asset_id in assets:
                asset_info = assets[asset_id]
                
                # 删除文件
                if os.path.exists(asset_info["path"]):
                    try:
                        os.remove(asset_info["path"])
                    except Exception as e:
                        print(f"删除素材文件失败: {e}")
                
                # 删除预览
                preview_path = asset_info.get("preview_path")
                if preview_path and os.path.exists(preview_path):
                    try:
                        os.remove(preview_path)
                    except Exception as e:
                        print(f"删除预览文件失败: {e}")
                
                # 从数据库中删除
                del assets[asset_id]
                return self._save_assets()
        return False
    
    def search_assets(self, keyword: str) -> List[Dict[str, Any]]:
        """
        搜索素材
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            匹配的素材列表
        """
        results = []
        keyword = keyword.lower()
        
        for category, assets in self.assets.items():
            for asset_info in assets.values():
                if (
                    keyword in asset_info.get("name", "").lower() or
                    keyword in asset_info.get("path", "").lower() or
                    any(keyword in tag.lower() for tag in asset_info.get("tags", []))
                ):
                    results.append(asset_info)
        
        return results
    
    def organize_assets(self, category: str, sort_by: str = "imported_at") -> List[Dict[str, Any]]:
        """
        组织素材
        
        Args:
            category: 素材类别
            sort_by: 排序字段
            
        Returns:
            组织后的素材列表
        """
        if category not in self.assets:
            return []
        
        assets = list(self.assets[category].values())
        
        # 排序
        if sort_by in ["name", "imported_at", "file_size"]:
            assets.sort(key=lambda x: x.get(sort_by, ""), reverse=True)
        
        return assets
    
    def get_asset_categories(self) -> List[str]:
        """
        获取素材类别列表
        
        Returns:
            类别列表
        """
        return list(self.assets.keys())
    
    def get_asset_tags(self, category: str = None) -> List[str]:
        """
        获取素材标签列表
        
        Args:
            category: 素材类别，如果为None则获取所有类别
            
        Returns:
            标签列表
        """
        tags = set()
        
        categories = [category] if category else self.assets.keys()
        
        for cat in categories:
            if cat in self.assets:
                for asset_info in self.assets[cat].values():
                    tags.update(asset_info.get("tags", []))
        
        return list(tags)


# 全局素材管理器实例
asset_manager = AssetManager()

# 模块级别的便捷函数，方便直接调用
def import_asset(file_path: str, category: str = "videos", tags: list = None):
    """
    便捷函数：导入素材
    
    Args:
        file_path: 素材文件路径
        category: 素材类别
        tags: 素材标签
    
    Returns:
        素材信息字典
    """
    return asset_manager.import_asset(file_path, category, tags)



