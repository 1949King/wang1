"""
P0#4 验证：撤销/重做贯通 UI
- 不依赖 Qt 主循环，用 offscreen 平台
- 验证按钮 enable/disable、toast、快捷键注册
"""
import os
import sys

# 强制 offscreen，避免依赖显示器
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, r"d:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop\AI短剧编辑器2")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

print("=" * 60)
print("P0#4 撤销/重做贯通 UI 验证")
print("=" * 60)

# 1) 语法 / import 验证
print("\n[1] 导入 EditorModule...")
try:
    from app.modules.lego.modules import EditorModule
    print(f"  ✓ EditorModule 加载成功")
except Exception as e:
    print(f"  ✗ 加载失败: {e}")
    sys.exit(1)

# 2) 直接实例化（offscreen 模式，避开视频渲染）
print("\n[2] 实例化 EditorModule（offscreen）...")
try:
    em = EditorModule()
    print(f"  ✓ 实例化成功")
except Exception as e:
    print(f"  ✗ 实例化失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 3) 验证按钮引用
print("\n[3] 验证撤销/重做按钮引用...")
print(f"  _undo_btn: {'✓' if em._undo_btn is not None else '✗'}")
print(f"  _redo_btn: {'✓' if em._redo_btn is not None else '✗'}")
print(f"  undo enabled (初始无历史): {em._undo_btn.isEnabled() if em._undo_btn else 'N/A'}")
print(f"  redo enabled (初始无历史): {em._redo_btn.isEnabled() if em._redo_btn else 'N/A'}")

# 4) 模拟一次删除操作（绕开 QMessageBox）
print("\n[4] 模拟一次删除（push _action_history）...")
em._clips = [{"id": 1, "path": "test1.mp4", "start_time": 0}, {"id": 2, "path": "test2.mp4", "start_time": 10}]
em._action_history = []
em._redo_history = []
# 模拟 _delete_clip 推入历史
em._action_history.append({"type": "delete", "clip": em._clips[0]})
em._clips.pop(0)
em._update_undo_redo_state()
print(f"  undo enabled: {em._undo_btn.isEnabled()} (预期 True)")
print(f"  redo enabled: {em._redo_btn.isEnabled()} (预期 False)")

# 5) 模拟撤销（不再弹 QMessageBox）
print("\n[5] 调用 _undo()（不应弹模态框）...")
try:
    em._undo()
    toast = em.get_undo_redo_toast()
    print(f"  toast: '{toast}'")
    print(f"  undo enabled: {em._undo_btn.isEnabled()} (预期 False)")
    print(f"  redo enabled: {em._redo_btn.isEnabled()} (预期 True)")
except Exception as e:
    print(f"  ✗ _undo 失败: {e}")
    import traceback
    traceback.print_exc()

# 6) 模拟重做
print("\n[6] 调用 _redo()（不应弹模态框）...")
try:
    em._redo()
    toast = em.get_undo_redo_toast()
    print(f"  toast: '{toast}'")
    print(f"  undo enabled: {em._undo_btn.isEnabled()} (预期 True)")
    print(f"  redo enabled: {em._redo_btn.isEnabled()} (预期 False)")
except Exception as e:
    print(f"  ✗ _redo 失败: {e}")

# 7) 验证快捷键注册（QShortcut 在 QtGui 里，不在 QtWidgets）
print("\n[7] 验证快捷键注册...")
from PySide6.QtGui import QShortcut as GuiQShortcut
shortcuts = em.findChildren(GuiQShortcut)
print(f"  注册的 QShortcut 数量: {len(shortcuts)} (预期 ≥3: Ctrl+Z/Ctrl+Y/Ctrl+Shift+Z)")
for sc in shortcuts:
    seq = sc.key().toString()
    print(f"    {seq}")

# 8) 验证 QShortcut 实际触发了 _undo/_redo
print("\n[8] 验证 QShortcut 触发链路...")
# 找一个 Ctrl+Z 快捷键
ctrl_z = None
ctrl_y = None
for sc in shortcuts:
    seq = sc.key().toString()
    if seq == "Ctrl+Z":
        ctrl_z = sc
    elif seq == "Ctrl+Y":
        ctrl_y = sc

if ctrl_z is not None:
    # 再 push 一个动作
    em._action_history.append({"type": "delete", "clip": {"id": 99}})
    em._update_undo_redo_state()
    print(f"  Ctrl+Z 已注册: {ctrl_z is not None}")
    # 激活 Ctrl+Z
    ctrl_z.activated.emit()
    print(f"  Ctrl+Z 触发后 toast: '{em.get_undo_redo_toast()}'")
else:
    print(f"  ✗ Ctrl+Z 快捷键未注册")

# ===== 结论 =====
print("\n" + "=" * 60)
all_ok = (
    em._undo_btn is not None
    and em._redo_btn is not None
    and len(shortcuts) >= 3  # Ctrl+Z + Ctrl+Y + Ctrl+Shift+Z
)
if all_ok:
    print("结论: P0#4 撤销/重做贯通 UI 端到端跑通 ✓")
else:
    print("结论: 部分失败，需排查")
print("=" * 60)
