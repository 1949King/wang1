"""
TOP 0级剪辑引擎依赖安装脚本
=============================
安装AI剧情理解引擎和专业剪辑引擎所需的依赖
"""

import subprocess
import sys
import os


def install_package(package, extra_index=None):
    """安装单个包"""
    cmd = [sys.executable, "-m", "pip", "install", package]
    if extra_index:
        cmd.extend(["--extra-index-url", extra_index])
    
    print(f"📦 安装 {package}...")
    try:
        subprocess.check_call(cmd)
        print(f"   ✅ {package} 安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"   ❌ {package} 安装失败: {e}")
        return False


def install_top0_dependencies():
    """安装TOP 0级引擎的所有依赖"""
    print("=" * 70)
    print("🚀 安装TOP 0级剪辑引擎依赖")
    print("=" * 70)
    print()
    
    # 核心依赖
    core_deps = [
        "openai-whisper",           # 语音识别
        "ollama",                   # 本地LLM
        "opencv-python",            # 视觉分析
        "numpy",                    # 数值计算
        "pillow",                   # 图像处理
    ]
    
    # 可选依赖（用于高级功能）
    optional_deps = [
        "torch",                    # PyTorch（用于深度学习模型）
        "torchvision",              # 视觉模型
        "transformers",             # Hugging Face模型
    ]
    
    print("📋 核心依赖:")
    core_success = []
    core_failed = []
    
    for dep in core_deps:
        if install_package(dep):
            core_success.append(dep)
        else:
            core_failed.append(dep)
    
    print()
    print("📋 可选依赖:")
    optional_success = []
    optional_failed = []
    
    for dep in optional_deps:
        if install_package(dep):
            optional_success.append(dep)
        else:
            optional_failed.append(dep)
    
    print()
    print("=" * 70)
    print("📊 安装结果:")
    print(f"   核心依赖: {len(core_success)}/{len(core_deps)} 成功")
    if core_failed:
        print(f"   失败: {', '.join(core_failed)}")
    
    print(f"   可选依赖: {len(optional_success)}/{len(optional_deps)} 成功")
    if optional_failed:
        print(f"   失败: {', '.join(optional_failed)}")
    
    print()
    
    # 检查Ollama
    print("🔍 检查Ollama...")
    try:
        import ollama
        # 测试连接
        ollama.list()
        print("   ✅ Ollama已安装并运行")
    except Exception as e:
        print(f"   ⚠️ Ollama未安装或未运行: {e}")
        print("   请访问 https://ollama.com 下载安装Ollama")
        print("   安装后运行: ollama pull qwen2.5")
    
    print()
    
    # 检查FFmpeg
    print("🔍 检查FFmpeg...")
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        print("   ✅ FFmpeg已安装")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("   ⚠️ FFmpeg未安装")
        print("   请访问 https://ffmpeg.org/download.html 下载安装FFmpeg")
        print("   并将FFmpeg添加到系统PATH")
    
    print()
    print("=" * 70)
    
    if len(core_success) == len(core_deps):
        print("✅ 所有核心依赖安装成功！")
        print("   TOP 0级剪辑引擎已准备就绪")
    else:
        print("⚠️ 部分依赖安装失败")
        print("   请检查错误信息并手动安装失败的包")
    
    print()
    print("📝 下一步:")
    print("   1. 确保Ollama已安装并运行")
    print("   2. 下载模型: ollama pull qwen2.5")
    print("   3. 启动AI短剧编辑器")
    print("   4. 在剪辑模块中使用'AI智能剪辑'功能")
    print("=" * 70)


if __name__ == "__main__":
    install_top0_dependencies()
