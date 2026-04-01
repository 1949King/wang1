import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any


class ProjectManager:
    """
    项目管理系统
    负责项目的创建、保存、加载、管理等功能
    """
    
    def __init__(self):
        """初始化项目管理器"""
        self.projects_dir = "projects"
        self.current_project = None
        self.autosave_interval = 60  # 自动保存间隔（秒）
        self.last_autosave_time = time.time()
        
        # 创建项目目录
        os.makedirs(self.projects_dir, exist_ok=True)
    
    def create_project(self, name: str, resolution: str = "1920x1080", fps: int = 30, **kwargs) -> Dict[str, Any]:
        """
        创建新项目
        
        Args:
            name: 项目名称
            resolution: 项目分辨率
            fps: 帧率
            **kwargs: 其他项目设置
            
        Returns:
            项目信息字典
        """
        project_id = f"{name}_{int(time.time())}"
        project_path = os.path.join(self.projects_dir, project_id)
        os.makedirs(project_path, exist_ok=True)
        
        # 项目信息
        project_info = {
            "id": project_id,
            "name": name,
            "created_at": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
            "settings": {
                "resolution": resolution,
                "fps": fps,
                "aspect_ratio": "16:9",
                **kwargs
            },
            "clips": [],
            "tracks": [],
            "effects": [],
            "transitions": [],
            "audio_tracks": [],
            "subtitles": [],
            "markers": []
        }
        
        # 保存项目文件
        project_file = os.path.join(project_path, "project.json")
        with open(project_file, "w", encoding="utf-8") as f:
            json.dump(project_info, f, ensure_ascii=False, indent=2)
        
        self.current_project = project_info
        return project_info
    
    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        加载项目
        
        Args:
            project_id: 项目ID
            
        Returns:
            项目信息字典，如果项目不存在则返回None
        """
        project_path = os.path.join(self.projects_dir, project_id)
        project_file = os.path.join(project_path, "project.json")
        
        if not os.path.exists(project_file):
            return None
        
        try:
            with open(project_file, "r", encoding="utf-8") as f:
                project_info = json.load(f)
            
            self.current_project = project_info
            return project_info
        except Exception as e:
            print(f"加载项目失败: {e}")
            return None
    
    def save_project(self, project_info: Optional[Dict[str, Any]] = None) -> bool:
        """
        保存项目
        
        Args:
            project_info: 项目信息字典，如果为None则保存当前项目
            
        Returns:
            是否保存成功
        """
        if project_info is None:
            project_info = self.current_project
        
        if not project_info:
            return False
        
        project_id = project_info.get("id")
        if not project_id:
            return False
        
        try:
            project_path = os.path.join(self.projects_dir, project_id)
            os.makedirs(project_path, exist_ok=True)
            
            # 更新最后修改时间
            project_info["last_modified"] = datetime.now().isoformat()
            
            project_file = os.path.join(project_path, "project.json")
            with open(project_file, "w", encoding="utf-8") as f:
                json.dump(project_info, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"保存项目失败: {e}")
            return False
    
    def autosave(self) -> bool:
        """
        自动保存项目
        
        Returns:
            是否保存成功
        """
        current_time = time.time()
        if current_time - self.last_autosave_time >= self.autosave_interval:
            success = self.save_project()
            if success:
                self.last_autosave_time = current_time
            return success
        return False
    
    def list_projects(self) -> List[Dict[str, Any]]:
        """
        列出所有项目
        
        Returns:
            项目列表
        """
        projects = []
        
        if not os.path.exists(self.projects_dir):
            return projects
        
        for project_id in os.listdir(self.projects_dir):
            project_path = os.path.join(self.projects_dir, project_id)
            if os.path.isdir(project_path):
                project_file = os.path.join(project_path, "project.json")
                if os.path.exists(project_file):
                    try:
                        with open(project_file, "r", encoding="utf-8") as f:
                            project_info = json.load(f)
                        projects.append(project_info)
                    except Exception as e:
                        print(f"读取项目信息失败: {e}")
        
        # 按最后修改时间排序
        projects.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
        return projects
    
    def delete_project(self, project_id: str) -> bool:
        """
        删除项目
        
        Args:
            project_id: 项目ID
            
        Returns:
            是否删除成功
        """
        import shutil
        
        project_path = os.path.join(self.projects_dir, project_id)
        if not os.path.exists(project_path):
            return False
        
        try:
            shutil.rmtree(project_path)
            if self.current_project and self.current_project.get("id") == project_id:
                self.current_project = None
            return True
        except Exception as e:
            print(f"删除项目失败: {e}")
            return False
    
    def export_project(self, project_id: str, output_path: str) -> bool:
        """
        导出项目
        
        Args:
            project_id: 项目ID
            output_path: 导出路径
            
        Returns:
            是否导出成功
        """
        import zipfile
        
        project_path = os.path.join(self.projects_dir, project_id)
        if not os.path.exists(project_path):
            return False
        
        try:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(project_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, project_path)
                        zipf.write(file_path, arcname)
            return True
        except Exception as e:
            print(f"导出项目失败: {e}")
            return False
    
    def import_project(self, zip_path: str) -> Optional[Dict[str, Any]]:
        """
        导入项目
        
        Args:
            zip_path: 项目压缩包路径
            
        Returns:
            导入的项目信息字典，如果导入失败则返回None
        """
        import zipfile
        import tempfile
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(zip_path, "r") as zipf:
                    zipf.extractall(temp_dir)
                
                # 查找项目文件
                project_file = None
                for root, dirs, files in os.walk(temp_dir):
                    if "project.json" in files:
                        project_file = os.path.join(root, "project.json")
                        break
                
                if not project_file:
                    return None
                
                # 读取项目信息
                with open(project_file, "r", encoding="utf-8") as f:
                    project_info = json.load(f)
                
                # 生成新的项目ID
                new_project_id = f"{project_info['name']}_{int(time.time())}"
                project_info["id"] = new_project_id
                project_info["created_at"] = datetime.now().isoformat()
                project_info["last_modified"] = datetime.now().isoformat()
                
                # 保存到项目目录
                new_project_path = os.path.join(self.projects_dir, new_project_id)
                os.makedirs(new_project_path, exist_ok=True)
                
                # 复制所有文件
                import shutil
                for root, dirs, files in os.walk(os.path.dirname(project_file)):
                    for file in files:
                        src_path = os.path.join(root, file)
                        rel_path = os.path.relpath(src_path, os.path.dirname(project_file))
                        dst_path = os.path.join(new_project_path, rel_path)
                        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                        shutil.copy2(src_path, dst_path)
                
                # 更新项目文件中的ID
                new_project_file = os.path.join(new_project_path, "project.json")
                with open(new_project_file, "w", encoding="utf-8") as f:
                    json.dump(project_info, f, ensure_ascii=False, indent=2)
                
                self.current_project = project_info
                return project_info
        except Exception as e:
            print(f"导入项目失败: {e}")
            return None


# 全局项目管理器实例
project_manager = ProjectManager()
