#!/usr/bin/env python3
"""
测试Python环境和基本库导入
"""

import sys
print(f"Python版本: {sys.version}")
print(f"Python路径: {sys.path}")

# 测试基本库导入
try:
    import os
    print("✓ os 导入成功")
except Exception as e:
    print(f"✗ os 导入失败: {e}")

try:
    import json
    print("✓ json 导入成功")
except Exception as e:
    print(f"✗ json 导入失败: {e}")

try:
    import requests
    print(f"✓ requests 导入成功 (版本: {requests.__version__})")
except Exception as e:
    print(f"✗ requests 导入失败: {e}")

try:
    import numpy
    print(f"✓ numpy 导入成功 (版本: {numpy.__version__})")
except Exception as e:
    print(f"✗ numpy 导入失败: {e}")

try:
    from PIL import Image
    print(f"✓ Pillow 导入成功")
except Exception as e:
    print(f"✗ Pillow 导入失败: {e}")

try:
    import PyQt6
    print(f"✓ PyQt6 导入成功 (版本: {PyQt6.__version__})")
except Exception as e:
    print(f"✗ PyQt6 导入失败: {e}")

try:
    import cv2
    print(f"✓ OpenCV 导入成功 (版本: {cv2.__version__})")
except Exception as e:
    print(f"✗ OpenCV 导入失败: {e}")

try:
    import torch
    print(f"✓ PyTorch 导入成功 (版本: {torch.__version__})")
except Exception as e:
    print(f"✗ PyTorch 导入失败: {e}")

print("\n环境测试完成")
