"""误触阈值 / 负载区间计算 — 无 GUI。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestClipHeavyAndSpans(unittest.TestCase):
    def test_clip_looks_heavy(self):
        from app.modules.lego.editor_timeline_tools import (
            clip_looks_heavy,
            compute_load_spans,
            CLIP_DRAG_THRESHOLD_PX,
        )
        self.assertGreaterEqual(CLIP_DRAG_THRESHOLD_PX, 4)
        self.assertFalse(clip_looks_heavy({"type": "video", "speed": 1}))
        self.assertTrue(clip_looks_heavy({"type": "video", "lut": "a.cube"}))
        self.assertTrue(clip_looks_heavy({"type": "video", "speed": 1.5}))
        self.assertFalse(clip_looks_heavy({"type": "audio", "effects": {}}))
        spans = compute_load_spans([
            {"type": "video", "start_time": 1, "duration": 2, "transition": "dissolve"},
            {"type": "video", "start_time": 10, "duration": 1},
        ])
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0], (1.0, 3.0))


if __name__ == "__main__":
    unittest.main()
