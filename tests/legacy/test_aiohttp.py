#!/usr/bin/env python3
"""
测试aiohttp是否安装成功
"""

try:
    import aiohttp
    print("✅ aiohttp安装成功！")
    print(f"aiohttp版本: {aiohttp.__version__}")
except ImportError:
    print("❌ aiohttp安装失败！")
