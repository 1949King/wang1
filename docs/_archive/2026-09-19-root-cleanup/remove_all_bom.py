#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""查找并移除所有BOM字符"""

import os
import glob

def find_and_remove_bom(directory):
    """查找并移除目录中所有Python文件的BOM字符"""
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    
                    if content.startswith(b'\xef\xbb\xbf'):
                        print(f"Found BOM in: {file_path}")
                        with open(file_path, 'r', encoding='utf-8-sig') as f:
                            content = f.read()
                        
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        
                        print(f"Removed BOM from: {file_path}")
                except Exception as e:
                    print(f"Error processing {file_path}: {e}")

if __name__ == "__main__":
    directories = [
        "app/core",
        "app/modules/lego"
    ]
    
    for directory in directories:
        if os.path.exists(directory):
            print(f"\nChecking directory: {directory}")
            find_and_remove_bom(directory)