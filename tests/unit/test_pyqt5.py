#!/usr/bin/env python3
# 测试 PySide6 安装路径

import os
import PySide6

print('PySide6 安装路径:', os.path.dirname(PySide6.__file__))

# 检查 Qt 平台插件目录
qt_dir = os.path.join(os.path.dirname(PySide6.__file__), 'plugins', 'platforms')
print('Qt 平台插件目录:', qt_dir)
print('目录是否存在:', os.path.exists(qt_dir))

# 列出目录内容
if os.path.exists(qt_dir):
    print('目录内容:', os.listdir(qt_dir))
else:
    print('目录不存在')
