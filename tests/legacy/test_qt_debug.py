#!/usr/bin/env python3
"""
带调试日志的测试脚本
"""

import os
import sys
import logging

logging.basicConfig(level=logging.DEBUG)

# 必须先创建 QApplication
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

test_video = os.path.join(os.path.dirname(__file__), "素材库", "test_video.mp4")

print("\n测试波形生成...")
from app.core.waveform_generator import waveform_generator
data = waveform_generator.generate(test_video, num_samples=100)
if data and data.peaks:
    print(f"波形生成成功: {len(data.peaks)} 采样点")
    print(f"峰值范围: {min(data.peaks):.6f} ~ {max(data.peaks):.6f}")
    print(f"前10个峰值: {data.peaks[:10]}")
else:
    print("波形生成失败")

print("\n测试完成!")
