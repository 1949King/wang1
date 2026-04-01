#!/bin/bash

cd "$(dirname "$0")"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 未找到。"
    exit 1
fi

echo "🔄 检查并安装依赖..."
pip3 install -r requirements.txt || pip3 install tkinter openai-whisper easyocr moviepy dashscope transformers torch mediapipe pillow yt-dlp gTTS pynvml

if [ ! -f "ui_main.py" ]; then
    echo "❌ 找不到 ui_main.py 文件。"
    exit 1
fi

echo "🚀 启动 AI 视频编辑器 UI..."
python3 ui_main.py