#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""移除文件BOM字符"""

import sys

def remove_bom(file_path):
    """移除文件的BOM字符"""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"已移除BOM: {file_path}")

if __name__ == "__main__":
    files = [
        "app/core/editor_scheduler.py",
        "app/modules/lego/video_editor/__init__.py"
    ]
    
    for file_path in files:
        try:
            remove_bom(file_path)
        except Exception as e:
            print(f"处理 {file_path} 时出错: {e}")