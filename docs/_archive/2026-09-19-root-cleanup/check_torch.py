#!/usr/bin/env python3
"""
检查Torch库的加载情况
"""

import sys

try:
    import torch
    print(f"Torch版本: {torch.__version__}")
    print(f"Torch CUDA可用: {torch.cuda.is_available()}")
except Exception as e:
    print(f"加载Torch失败: {e}")
    import traceback
    traceback.print_exc()

print("脚本执行完成")
