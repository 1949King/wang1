"""P1：ESC 取消拖拽还原 / autosave 防抖 / 波纹开关 — 无 GUI 轻测。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestCancelEditDragLogic(unittest.TestCase):
    def test_restore_fields_from_before(self):
        """模拟 cancel_edit_drag 的数据还原（不构造 Qt 控件）。"""
        before = {
            "id": "c1",
            "start_time": 1.0,
            "duration": 2.0,
            "in_point": 0.5,
            "out_point": 2.5,
            "track": 0,
        }
        clip = {
            "id": "c1",
            "start_time": 5.0,
            "duration": 1.0,
            "in_point": 1.0,
            "out_point": 2.0,
            "track": 1,
        }
        for k in ("start_time", "duration", "in_point", "out_point", "track"):
            clip[k] = before[k]
        self.assertEqual(clip["start_time"], 1.0)
        self.assertEqual(clip["track"], 0)
        self.assertEqual(clip["duration"], 2.0)


class TestUxRippleToggle(unittest.TestCase):
    def test_toggle_ripple_dispatch(self):
        from app.modules.lego.editor_ux_commands import dispatch_editor_action

        class Fake:
            def __init__(self):
                self._ripple_delete_enabled = True
                self.msgs = []

            def _on_ripple_delete_toggled(self, enabled):
                self._ripple_delete_enabled = enabled
                self.msgs.append(enabled)

        ed = Fake()
        r = dispatch_editor_action(ed, "toggle_ripple")
        self.assertTrue(r["ok"])
        self.assertFalse(ed._ripple_delete_enabled)


class TestTouchDirtyContract(unittest.TestCase):
    def test_touch_sets_flag_without_recursion(self):
        """确保 _touch_project_dirty 写 _project_dirty 而非自调用。"""
        import ast
        from pathlib import Path

        src = Path(ROOT, "app/modules/lego/editor_module.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "_touch_project_dirty":
                        found = item
                        break
        self.assertIsNotNone(found)
        text = ast.get_source_segment(src, found) or ""
        self.assertIn("self._project_dirty = True", text)
        # 函数体内不应再调用自己（防抖递归）
        calls = [
            n for n in ast.walk(found)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_touch_project_dirty"
        ]
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
