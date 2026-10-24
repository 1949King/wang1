@echo off
echo 🚀 开始安装 AI 视频剪辑软件 (本地版)...

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python 3 未安装，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 创建虚拟环境
echo 🔧 创建虚拟环境...
python -m venv venv

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 安装依赖
echo 📦 安装 Python 依赖...
pip install --upgrade pip
pip install -r requirements.txt

REM 创建必要目录
echo 📁 创建必要目录...
if not exist bgms mkdir bgms
if not exist stickers mkdir stickers
if not exist output mkdir output
if not exist logs mkdir logs

REM 检查 .env 文件
if not exist .env (
    echo 📝 创建 .env 文件...
    echo DASHSCOPE_API_KEY=your_dashscope_key > .env
    echo ANTHROPIC_API_KEY=your_claude_key >> .env
    echo ZHIPUAI_API_KEY=your_zhipu_key >> .env
    echo ⚠️ 请编辑 .env 文件填入你的 API Keys
)

echo 🎉 安装完成！
echo 💡 启动命令: call venv\Scripts\activate.bat && python app\web_interface.py
echo 🌐 访问地址: http://127.0.0.1:7860
pause