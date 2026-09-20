"""C8: Qt6 启动验证 - 验证 C 系列改动不破坏现有功能"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import sys
import time
sys.path.insert(0, '.')

print("=" * 60)
print("C8: Qt6 启动 + C 系列验证")
print("=" * 60)

t0 = time.time()

# 1. 启动 Qt6
print(f"[1/5] 启动 QApplication...")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication(sys.argv)
print(f"  ✅ QApplication 启动成功 ({time.time()-t0:.2f}s)")

# 2. 验证核心模块
print(f"[2/5] 验证 3 大总线...")
t1 = time.time()
from modules.lego import EventBus, MasterClock, DataBus
eb = EventBus.get_instance()
mc = MasterClock.get_instance()
db = DataBus.get_instance()
print(f"  ✅ EventBus / MasterClock / DataBus ({time.time()-t1:.2f}s)")

# 3. 验证 SkillEngine
print(f"[3/5] 验证 SkillEngine...")
t2 = time.time()
from modules.lego import SkillEngine
se = SkillEngine.get_instance()
print(f"  ✅ SkillEngine 单例 ({time.time()-t2:.2f}s)")

# 4. 事件循环跑 1 秒
print(f"[4/4] 启动 Qt 事件循环 1 秒...")
t4 = time.time()
QTimer.singleShot(1000, app.quit)
app.exec()
print(f"  ✅ 事件循环正常退出 (实际 {time.time()-t4:.2f}s)")

print("=" * 60)
print(f"✅ C 系列验证全部通过! 总耗时 {time.time()-t0:.2f}s")
print("=" * 60)
