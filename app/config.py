import os

# API Keys
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")

# Paths
BGMS_PATH = "./bgms"
STICKERS_PATH = "./stickers"
OUTPUT_PATH = "./output"

# Processing
WHISPER_MODEL = "tiny"  # CPU友好版本
MAX_SCRIPT_LENGTH = 1000
DEVICE = "cpu"  # 本地电脑默认CPU
CPU_THREADS = os.cpu_count() or 4  # 使用CPU核心数