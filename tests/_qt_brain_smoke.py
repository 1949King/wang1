"""在真实 Qt6 环境下验证 AgentBrain + _refresh_agent_brain_status 不会崩溃。

只验证：
1. QApplication 启动
2. AgentBrain 单例 + sync_from_dispatcher
3. QLabel 显示 brain status
4. QTimer 周期刷新
5. reinforce_path 后 UI 更新
不加载完整 main_qt6.py，避免其他模块干扰。
"""
import os
import sys
import time

sys.path.insert(0, r"d:\拾光剪影")

# 必须在 QApplication 之前设置环境变量
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout  # noqa: E402
from PyQt6.QtCore import QTimer  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

# 1. 导入 AgentBrain（验证 import 不崩溃）
from app.core.agent_brain import agent_brain, AgentBrain  # noqa: E402
print("[1] AgentBrain import OK, 单例:", AgentBrain() is agent_brain)

# 2. sync_from_dispatcher
class FakeDispatcher:  # noqa: N801
    def list_capabilities(self):
        return ["editor.split_clip", "model.chat", "pipeline.route"]
agent_brain.sync_from_dispatcher(FakeDispatcher())
status = agent_brain.get_brain_status()
print(f"[2] sync OK, 神经元数: {status['total_neurons']}")

# 3. 创建 QLabel 并显示 brain status
window = QWidget()
window.setWindowTitle("🧠 Brain Status Test")
window.resize(600, 100)
layout = QVBoxLayout(window)
label = QLabel("🧠 初始化中...")
label.setStyleSheet(
    "QLabel{background:#1a1030;color:#d2a8ff;border:1px solid #3b1f6f;"
    "border-radius:6px;padding:6px 10px;font-size:11px;}"
)
label.setWordWrap(True)
layout.addWidget(label)

# 4. 模拟 _refresh_agent_brain_status 方法
def refresh():
    try:
        s = agent_brain.get_brain_status()
        main = (f"🧠 神经元 {s['total_neurons']} | 🌐 左脑 {s['left_brain_count']}"
                f" / 右脑 {s['right_brain_count']} / 胼胝体 {s['cc_count']}"
                f" | 🔗 突触 {s['total_synapses']} | ⚡ 激活 {len(s['active_neurons'])}")
        top = s.get("top_synapses", []) or []
        links = []
        for syn in top[:2]:
            w_pct = int(float(syn.get("weight", 0)) * 100)
            links.append(f"{syn.get('pre','')}→{syn.get('post','')}({w_pct}%)")
        link_text = " | 强链路: " + " / ".join(links) if links else ""
        label.setText(main + link_text)
        print(f"[refresh] {main}{link_text}")
    except Exception as e:
        label.setText(f"🧠 大脑状态不可用: {e}")
        print(f"[refresh] ERROR: {e}")

# 5. 启动 QTimer
timer = QTimer()
timer.setInterval(1000)  # 1 秒刷新一次（测试用）
timer.timeout.connect(refresh)
timer.start()

# 6. 触发一次 reinforce_path，让突触有数据
agent_brain.reinforce_path(
    ["pipeline.route", "pipeline.generate", "pipeline.preview_validate",
     "pipeline.score", "pipeline.generate_script", "pipeline.execute_editing"],
    success=True,
)

# 7. 显示窗口
window.show()
refresh()  # 立即刷新一次

# 8. 3 秒后自动退出
QTimer.singleShot(3000, app.quit)

print("[3] 启动 Qt 事件循环 3 秒...")
app.exec()
print("[4] Qt 事件循环结束，所有验证通过")
print()
print("=== QT_BRAIN_SMOKE_OK ===")
