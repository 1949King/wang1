#!/bin/bash

echo "🚀 开始安装 AI 视频剪辑软件 (本地版)..."

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 未安装，请先安装 Python 3.8+"
    exit 1
fi

# 检查 pip
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip 未安装，请先安装 pip"
    exit 1
fi

# 创建虚拟环境
echo "🔧 创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate

# 安装依赖
echo "📦 安装 Python 依赖..."
pip3 install --upgrade pip
pip3 install -r requirements.txt

# 创建必要目录
echo "📁 创建必要目录..."
mkdir -p bgms stickers output logs

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "📝 创建 .env 文件..."
    cat > .env << EOF
DASHSCOPE_API_KEY=your_dashscope_key
ANTHROPIC_API_KEY=your_claude_key
ZHIPUAI_API_KEY=your_zhipu_key
EOF
    echo "⚠️ 请编辑 .env 文件填入你的 API Keys"
fi

echo "🎉 安装完成！"
echo "💡 启动命令: source venv/bin/activate && python3 app/web_interface.py"
echo "🌐 访问地址: http://127.0.0.1:7860"