import logging
import os
import datetime

# 配置日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 配置日志文件
log_file = os.path.join(LOG_DIR, f"ai_video_editor_{datetime.datetime.now().strftime('%Y%m%d')}.log")

# 创建日志记录器
logger = logging.getLogger("AIEditor")
logger.setLevel(logging.DEBUG)

# 创建文件处理器
file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 配置日志格式
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# 添加处理器到记录器
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 测试日志
logger.info("日志系统初始化完成")