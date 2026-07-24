import os
import shutil
from typing import List, Optional


class FileOperator:
    """文件操作器"""

    @staticmethod
    def copy_file(source_path: str, target_path: str) -> bool:
        """复制文件"""
        try:
            shutil.copy2(source_path, target_path)
            return True
        except Exception as e:
            print(f"复制文件失败: {e}")
            return False

    @staticmethod
    def delete_file(file_path: str) -> bool:
        """删除文件"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except Exception as e:
            print(f"删除文件失败: {e}")
            return False

    @staticmethod
    def ensure_dir(dir_path: str):
        """确保目录存在"""
        os.makedirs(dir_path, exist_ok=True)

    @staticmethod
    def move_file(source_path: str, target_path: str) -> bool:
        """移动文件"""
        try:
            shutil.move(source_path, target_path)
            return True
        except Exception as e:
            print(f"移动文件失败: {e}")
            return False

    @staticmethod
    def get_file_size(file_path: str) -> int:
        """获取文件大小"""
        try:
            return os.path.getsize(file_path)
        except Exception as e:
            print(f"获取文件大小失败: {e}")
            return 0

    @staticmethod
    def file_exists(file_path: str) -> bool:
        """检查文件是否存在"""
        return os.path.exists(file_path) and os.path.isfile(file_path)

    @staticmethod
    def dir_exists(dir_path: str) -> bool:
        """检查目录是否存在"""
        return os.path.exists(dir_path) and os.path.isdir(dir_path)

    @staticmethod
    def list_files(dir_path: str, extensions: Optional[List[str]] = None) -> List[str]:
        """列出目录下的文件"""
        files = []
        try:
            for file_name in os.listdir(dir_path):
                file_path = os.path.join(dir_path, file_name)
                if os.path.isfile(file_path):
                    if extensions:
                        ext = os.path.splitext(file_name)[1].lower()
                        if ext in extensions:
                            files.append(file_path)
                    else:
                        files.append(file_path)
        except Exception as e:
            print(f"列出文件失败: {e}")
        return files

    @staticmethod
    def get_extension(file_path: str) -> str:
        """获取文件扩展名"""
        return os.path.splitext(file_path)[1].lower()

    @staticmethod
    def get_basename(file_path: str) -> str:
        """获取文件名（不含扩展名）"""
        return os.path.splitext(os.path.basename(file_path))[0]
