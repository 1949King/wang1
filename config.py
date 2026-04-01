# config.py
DB_PATH = "video_monitor.db"
MONITOR_INTERVAL_MINUTES = 10  # 每10分钟采集一次
BACKEND_PUSH_URL = "http://127.0.0.1:8000/api/data_sync"  # 你的后端接口
WEBSOCKET_ENABLE = True
