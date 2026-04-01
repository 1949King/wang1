# Olive Video Editor 集成模块
import os
import subprocess
import json
from datetime import datetime

class OliveVideoEditor:
    """
    Olive Video Editor 集成类
    提供完整的视频剪辑功能，替代原有的视频处理模块
    """
    
    def __init__(self):
        """
        初始化Olive Video Editor集成
        """
        self.executable = "olive-editor.exe"  # Olive可执行文件路径
        self.project_dir = os.path.join("短剧AI剪辑输出", "olive_projects")
        self.export_dir = "短剧AI剪辑输出"
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(self.export_dir, exist_ok=True)
        
        # 检查Olive是否安装
        self.is_available = self._check_olive_availability()
    
    def _check_olive_availability(self):
        """
        检查Olive Video Editor是否可用
        """
        try:
            # 尝试运行Olive命令行检查
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            # 如果Olive不可用，使用内置的Python实现
            return False
    
    def create_project(self, project_name):
        """
        创建Olive项目
        """
        project_path = os.path.join(self.project_dir, f"{project_name}.ove")
        
        # 创建项目文件结构
        project_data = {
            "name": project_name,
            "created": datetime.now().isoformat(),
            "media": [],
            "sequences": []
        }
        
        # 写入项目文件
        with open(project_path, 'w', encoding='utf-8') as f:
            json.dump(project_data, f, ensure_ascii=False, indent=2)
        
        return project_path
    
    def import_media(self, project_path, media_files):
        """
        导入媒体文件到Olive项目
        """
        try:
            # 读取现有项目数据
            with open(project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            # 添加媒体文件
            for media_file in media_files:
                if media_file not in project_data['media']:
                    project_data['media'].append(media_file)
            
            # 保存更新后的项目
            with open(project_path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"导入媒体文件失败: {e}")
            return False
    
    def edit_video(self, project_path, edit_params):
        """
        编辑视频
        """
        try:
            # 读取项目数据
            with open(project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            # 添加编辑序列
            sequence = {
                "name": "Main Sequence",
                "params": edit_params,
                "clips": []
            }
            
            # 生成剪辑方案
            if project_data['media']:
                for media_file in project_data['media']:
                    clip = {
                        "media": media_file,
                        "start": 0,
                        "duration": edit_params.get('target_duration', 30),
                        "speed": edit_params.get('speed', 1.0)
                    }
                    sequence['clips'].append(clip)
            
            project_data['sequences'].append(sequence)
            
            # 保存更新后的项目
            with open(project_path, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"编辑视频失败: {e}")
            return False
    
    def export_video(self, project_path, output_path, export_settings):
        """
        导出视频
        """
        try:
            # 读取项目数据
            with open(project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            # 如果Olive可用，使用Olive导出
            if self.is_available:
                # 构建Olive导出命令
                cmd = [
                    self.executable,
                    "--export",
                    project_path,
                    "--output",
                    output_path,
                    "--settings",
                    json.dumps(export_settings)
                ]
                
                # 执行导出命令
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True
                )
                
                return result.returncode == 0
            else:
                # 使用内置的FFmpeg实现
                return self._export_with_ffmpeg(project_data, output_path, export_settings)
        except Exception as e:
            print(f"导出视频失败: {e}")
            return False
    
    def _export_with_ffmpeg(self, project_data, output_path, export_settings):
        """
        使用FFmpeg导出视频
        """
        try:
            import subprocess
            
            # 构建FFmpeg命令
            cmd = [
                "ffmpeg",
                "-i", project_data['media'][0]  # 使用第一个媒体文件
            ]
            
            # 添加编码设置
            cmd.extend([
                "-c:v", export_settings.get('encoder', 'libx264'),
                "-b:v", export_settings.get('bitrate', '5M'),
                "-s", export_settings.get('resolution', '1920x1080'),
                "-c:a", "aac",
                "-b:a", "128k",
                "-y",
                output_path
            ])
            
            # 执行FFmpeg命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            return result.returncode == 0
        except Exception as e:
            print(f"FFmpeg导出失败: {e}")
            return False
    
    def get_project_info(self, project_path):
        """
        获取项目信息
        """
        try:
            with open(project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            return project_data
        except Exception as e:
            print(f"获取项目信息失败: {e}")
            return None
    
    def list_projects(self):
        """
        列出所有项目
        """
        projects = []
        try:
            for file in os.listdir(self.project_dir):
                if file.endswith('.ove'):
                    project_path = os.path.join(self.project_dir, file)
                    info = self.get_project_info(project_path)
                    if info:
                        projects.append({
                            'name': info['name'],
                            'path': project_path,
                            'created': info['created']
                        })
        except Exception as e:
            print(f"列出项目失败: {e}")
        return projects

# 创建全局Olive实例
olive_editor = OliveVideoEditor()