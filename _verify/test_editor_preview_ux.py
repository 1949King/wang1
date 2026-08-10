"""P0：预览档位 / 代理路径 / 工具栏指令调度 — 轻量单测（无 GUI）。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestPreviewUx(unittest.TestCase):
    def test_normalize_quality(self):
        from app.modules.lego.editor_preview_ux import (
            normalize_preview_quality,
            quality_label,
            quality_combo_items,
        )
        self.assertEqual(normalize_preview_quality("1/4"), "low")
        self.assertEqual(normalize_preview_quality("1/2"), "medium")
        self.assertEqual(normalize_preview_quality("100%"), "high")
        self.assertEqual(normalize_preview_quality("bogus"), "medium")
        self.assertEqual(quality_label("low"), "1/4")
        items = quality_combo_items()
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0][1], "low")

    def test_resolve_preview_prefers_proxy(self):
        from app.modules.lego.editor_preview_ux import (
            resolve_preview_media_path,
            attach_proxy_path,
        )
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src.mp4")
            proxy = os.path.join(td, "proxy.mp4")
            with open(src, "wb") as f:
                f.write(b"x")
            with open(proxy, "wb") as f:
                f.write(b"y")
            clip = {"path": src}
            self.assertEqual(resolve_preview_media_path(clip), src)
            self.assertTrue(attach_proxy_path(clip, proxy))
            self.assertEqual(resolve_preview_media_path(clip), os.path.normpath(proxy))
            self.assertEqual(
                resolve_preview_media_path(clip, prefer_proxy=False),
                os.path.normpath(src),
            )
            # 导出真相源不变
            self.assertEqual(clip["path"], src)


class TestUxCommands(unittest.TestCase):
    def test_dispatch_known_and_unknown(self):
        from app.modules.lego.editor_ux_commands import dispatch_editor_action

        class Fake:
            def __init__(self):
                self.calls = []
                self._snap_enabled = True

            def _cut_clip(self):
                self.calls.append("cut")

            def _on_snap_toggled(self, enabled):
                self._snap_enabled = enabled
                self.calls.append(("snap", enabled))

            def set_user_preview_quality(self, q):
                self.calls.append(("pq", q))

        ed = Fake()
        r = dispatch_editor_action(ed, "cut")
        self.assertTrue(r["ok"])
        self.assertIn("cut", ed.calls)

        r2 = dispatch_editor_action(ed, "toggle_snap")
        self.assertTrue(r2["ok"])
        self.assertEqual(ed._snap_enabled, False)

        r3 = dispatch_editor_action(ed, "set_preview_quality", quality="low")
        self.assertTrue(r3["ok"])
        self.assertIn(("pq", "low"), ed.calls)

        r4 = dispatch_editor_action(ed, "no_such_action")
        self.assertFalse(r4["ok"])


class TestProxyMediaScale(unittest.TestCase):
    def test_build_cmd_preserves_aspect_no_pad(self):
        from app.core.proxy_media import ProxyMediaManager, reset_proxy_manager

        reset_proxy_manager()
        mgr = ProxyMediaManager(cache_dir=tempfile.mkdtemp())
        cmd = mgr._build_ffmpeg_cmd("in.mp4", "out.mp4")
        self.assertIn("-vf", cmd)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("scale=", vf)
        self.assertNotIn("pad=", vf)
        # 默认跟随源帧率，不强制 -r
        self.assertNotIn("-r", cmd)


if __name__ == "__main__":
    unittest.main()
