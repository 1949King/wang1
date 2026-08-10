"""
tests/conftest.py
=================
tests/ 目录的 pytest 共享配置。
继承根目录 conftest.py 的 fixtures（qt_app/temp_dir/bus 等）。

职责：
  1. 将项目根 + app/ 加入 sys.path，兼容两种导入风格：
     - from app.modules.lego.xxx import ...  （需项目根）
     - from core.xxx import ...              （需 app/）
  2. 不重复定义根 conftest.py 已有的 fixtures
"""
import os
import sys
from pathlib import Path

# 项目根 = tests/ 的父目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_APP_ROOT = _PROJECT_ROOT / "app"

for p in [_PROJECT_ROOT, _APP_ROOT]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
