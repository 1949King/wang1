"""应用配置设置"""

import os
import platform

class Config:
    """应用配置类"""
    
    # 应用数据目录
    if platform.system() == "Windows":
        APP_DATA_DIR = os.path.join(os.environ.get("APPDATA", ""), "AI短剧编辑器")
    elif platform.system() == "Darwin":  # macOS
        APP_DATA_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "AI短剧编辑器")
    else:  # Linux
        APP_DATA_DIR = os.path.join(os.path.expanduser("~"), ".ai_short_drama_editor")
    
    # 插件目录
    PLUGINS_DIR = os.path.join(APP_DATA_DIR, "plugins")
    
    # 缓存目录
    CACHE_DIR = os.path.join(APP_DATA_DIR, "cache")
    
    # 日志目录
    LOGS_DIR = os.path.join(APP_DATA_DIR, "logs")
    
    # 临时文件目录
    TEMP_DIR = os.path.join(APP_DATA_DIR, "temp")
    
    # 确保所有目录存在
    @classmethod
    def ensure_directories(cls):
        """确保所有必要的目录存在"""
        directories = [
            cls.APP_DATA_DIR,
            cls.PLUGINS_DIR,
            cls.CACHE_DIR,
            cls.LOGS_DIR,
            cls.TEMP_DIR
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)

# 初始化配置
Config.ensure_directories()
