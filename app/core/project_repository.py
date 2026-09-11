import os
import time
import json
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

from .base_repository import BaseRepository


import logging
logger = logging.getLogger("AI短剧编辑器.core.project_repository")

class ProjectRepository(BaseRepository):
    """项目数据持久化"""

    def __init__(self, assets_dir: str):
        self.assets_dir = assets_dir
        db_path = os.path.join(assets_dir, "projects.json")
        super().__init__(db_path)

    def create_project(self, project_name: str, description: str = "") -> Dict[str, Any]:
        """创建项目"""
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
            self._data[project_id] = project_info
            self._save_data()

        return project_info

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """获取项目信息"""
        return self._data.get(project_id)

    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有项目"""
        return list(self._data.values())

    def add_asset_to_project(self, project_id: str, asset_id: str) -> bool:
        """将素材添加到项目"""
        with self._lock:
            if project_id in self._data:
                project = self._data[project_id]
                if asset_id not in project["assets"]:
                    project["assets"].append(asset_id)
                    project["updated_at"] = datetime.now().isoformat()
                    return self._save_data()
        return False

    def backup_project(self, project_id: str) -> Optional[str]:
        """备份项目"""
        project = self.get_project(project_id)
        if not project:
            return None

        backup_dir = os.path.join(self.assets_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        backup_path = os.path.join(backup_dir, f"{project_id}_{int(time.time())}.json")

        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(project, f, ensure_ascii=False, indent=2)

            with self._lock:
                version_info = {
                    "version_id": f"v{len(project.get('versions', [])) + 1}",
                    "backup_path": backup_path,
                    "created_at": datetime.now().isoformat(),
                    "description": "自动备份"
                }
                if "versions" not in project:
                    project["versions"] = []
                project["versions"].append(version_info)
                return self._save_data() and backup_path
        except Exception as e:
            logger.error(f'备份项目失败: {e}')
            return None

    def restore_project(self, project_id: str, version_id: str) -> bool:
        """恢复项目到指定版本"""
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
                            self._data[project_id] = restored_project
                            self._data[project_id]["updated_at"] = datetime.now().isoformat()
                            return self._save_data()
                    except Exception as e:
                        logger.error(f'恢复项目失败: {e}')
        return False

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> bool:
        """更新项目信息"""
        with self._lock:
            if project_id in self._data:
                self._data[project_id].update(updates)
                self._data[project_id]["updated_at"] = datetime.now().isoformat()
                return self._save_data()
        return False
