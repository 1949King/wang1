# config.py
import os
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "data" / "video_monitor.db")
MONITOR_INTERVAL_MINUTES = 10  # 每10分钟采集一次

# 后端接口地址，可通过环境变量覆盖
BACKEND_PUSH_URL = os.environ.get(
    "BACKEND_PUSH_URL",
    "http://127.0.0.1:8000/api/data_sync"
)
WEBSOCKET_ENABLE = os.environ.get("WEBSOCKET_ENABLE", "true").lower() == "true"
