#!/usr/bin/env python3
# 测试 PyQt5 安装路径

import os
import PyQt5

print('PyQt5 安装路径:', os.path.dirname(PyQt5.__file__))

# 检查 Qt 平台插件目录
qt_dir = os.path.join(os.path.dirname(PyQt5.__file__), 'Qt5', 'plugins', 'platforms')
print('Qt 平台插件目录:', qt_dir)
print('目录是否存在:', os.path.exists(qt_dir))

# 列出目录内容
if os.path.exists(qt_dir):
    print('目录内容:', os.listdir(qt_dir))
else:
    print('目录不存在')
