"""统一配置中心"""
import os

# ============================================================
# API Keys
# ============================================================
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")

# ============================================================
# 路径配置
# ============================================================
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(APP_DIR)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "短剧AI剪辑输出")
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "output")
THIRDPARTY_DIR = os.path.join(PROJECT_ROOT, "thirdparty")
FFMPEG_DIR = os.path.join(THIRDPARTY_DIR, "ffmpeg", "bin")

# ============================================================
# 渲染默认值
# ============================================================
DEFAULT_CODEC = "libx264"
DEFAULT_PRESET = "medium"
DEFAULT_CRF = 23
DEFAULT_BITRATE = "5M"
DEFAULT_FPS = 30
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080

# 确保目录存在
for _d in [OUTPUT_DIR, OUTPUT_PATH]:
    os.makedirs(_d, exist_ok=True)
