"""剪辑模块性能优化轻测：预览同档不清缓存、代理路径解析、导出守卫。"""
from __future__ import annotations

import ast
import inspect
import os
import sys
import tempfile
import unittest

# 临时目录钉到项目内 .workbuddy/tmp（2026-09-28）：沙箱拦截系统 Temp 写入 ⇒
# tempfile.gettempdir() 回退到 cwd（项目根），直接单跑本脚本会把临时目录漏进仓库根。
# 规范入口 run_all_checks 已用 TMPDIR 传递；此处覆盖「直接单跑」路径。
try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if "__file__" in globals() else os.getcwd(),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestPreviewQualityNoop(unittest.TestCase):
    def test_same_quality_early_return_in_source(self):
        # 避免拉起 PreviewManager 的重依赖；断言同档 early-return 仍在源码中
        path = os.path.join(ROOT, "app", "core", "preview_manager.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("同档位不整表清空", src)
        self.assertIn('if q == getattr(self, "preview_quality", None):', src)


class TestFilmstripPrefersProxy(unittest.TestCase):
    def test_resolve_prefers_proxy_file(self):
        from app.modules.lego.editor_preview_ux import resolve_preview_media_path

        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "a.mp4")
            proxy = os.path.join(td, "p.mp4")
            with open(src, "wb") as f:
                f.write(b"1")
            with open(proxy, "wb") as f:
                f.write(b"2")
            clip = {"path": src, "proxy_path": proxy}
            self.assertEqual(
                resolve_preview_media_path(clip),
                os.path.normpath(proxy),
            )


class TestExportProxyGuard(unittest.TestCase):
    def test_is_proxy_path(self):
        from app.modules.lego.editor_preview_ux import is_proxy_path

        self.assertTrue(is_proxy_path(r"D:\app\cache\proxies\abc.mp4"))
        self.assertFalse(is_proxy_path(r"D:\footage\shot.mp4"))

    def test_export_skips_proxy_path_branch(self):
        path = os.path.join(ROOT, "app", "modules", "lego", "editor_export.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("is_proxy_path", src)
        self.assertIn("导出禁止误用代理文件", src)


class TestTimelineWorkerLifecycle(unittest.TestCase):
    def test_interaction_wake_and_remove_sleep(self):
        path = os.path.join(ROOT, "app", "modules", "lego", "timeline_widget.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("def set_clip_interaction_active", src)
        self.assertIn("_wake_visible_clip_media()", src)
        self.assertIn("sleep_media_workers", src)
        self.assertIn("_scaled_thumb_cache", src)
        self.assertIn("def _resolve_clip_media_path", src)


class TestMediaWorkerGate(unittest.TestCase):
    def test_limits_concurrency_and_drains_queue(self):
        import importlib
        # 独立导入模块级门（不依赖 PyQt 组件实例化）
        tw_mod = importlib.import_module("app.modules.lego.timeline_widget")
        Gate = tw_mod._MediaWorkerGate

        gate = Gate(max_concurrent=2)
        started = []

        class Owner:
            pass

        owners = [Owner() for _ in range(4)]
        for i, o in enumerate(owners):
            gate.request(o, lambda i=i: started.append(i))

        self.assertEqual(started, [0, 1])  # 前两个立即启动，其余排队
        gate.release()  # 释放一个名额，队列里第 3 个应启动
        self.assertEqual(started, [0, 1, 2])
        gate.release()
        self.assertEqual(started, [0, 1, 2, 3])

    def test_cancel_owner_drops_queued(self):
        import importlib
        tw_mod = importlib.import_module("app.modules.lego.timeline_widget")
        Gate = tw_mod._MediaWorkerGate

        gate = Gate(max_concurrent=1)
        started = []

        class Owner:
            pass

        o1, o2 = Owner(), Owner()
        gate.request(o1, lambda: started.append("o1"))
        gate.request(o2, lambda: started.append("o2"))
        gate.cancel_owner(o2)
        gate.release()
        self.assertEqual(started, ["o1"])  # o2 已撤销，释放名额后队列为空


class TestGridBackgroundDirtyRectClipping(unittest.TestCase):
    """长时间线滚动/框选时，网格线只按脏区算，不整表循环。"""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_narrow_dirty_rect_draws_fewer_lines_than_full_width(self):
        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QPixmap, QPainter
        from app.modules.lego.timeline_widget import TrackViewport

        PPS = 400.0  # 高缩放 → sec_per_grid=0.5
        TOTAL_DUR = 600.0  # 10 分钟工程
        W = int(TOTAL_DUR * PPS)  # 逻辑总宽度（真实控件按此展开，非物理画布尺寸）

        class MockParent:
            _left_margin = 0
            _total_duration = TOTAL_DUR

            def px_per_sec(self):
                return PPS

        viewport = TrackViewport()
        # 画布尺寸与逻辑宽度 W 无关，只是给 QPainter 一个有效设备
        pix = QPixmap(64, 64)
        painter = QPainter(pix)
        calls = {"n": 0}
        orig_draw_line = painter.drawLine

        def counting_draw_line(*args, **kwargs):
            calls["n"] += 1
            return orig_draw_line(*args, **kwargs)

        painter.drawLine = counting_draw_line
        try:
            full_rect = QRect(0, 0, W, 60)
            viewport._paint_grid_background(painter, MockParent(), W, 60, full_rect)
            full_count = calls["n"]

            calls["n"] = 0
            narrow_rect = QRect(W // 2, 0, 100, 60)  # 仅 100px 宽的脏区
            viewport._paint_grid_background(painter, MockParent(), W, 60, narrow_rect)
            narrow_count = calls["n"]
        finally:
            painter.end()

        self.assertGreater(full_count, 500)  # 未裁剪时（整表 10 分钟 @0.5s 间隔）线数应该很多
        self.assertLess(narrow_count, 20)     # 裁剪后只画脏区附近几条
        self.assertLess(narrow_count, full_count)


class TestPlayheadMovedNoRebaseDuringPlayback(unittest.TestCase):
    """播放中 playhead_moved 回抛不应重新 rebase 墙钟锚点（否则约每 100ms 抖一次）。"""

    def test_playing_skips_rebase_not_playing_still_scrubs(self):
        from app.modules.lego.editor_module import EditorModule

        class MockSelf:
            def __init__(self, playing):
                self._timeline_playing = playing
                self.rebase_calls = []
                self.scrub_begun = False
                self._scrub_preview_pending = None
                self._scrub_preview_coalesce = 0
                self._scrub_preview_timer = None

            def _update_time_display(self):
                pass

            def _rebasing_playback_clock(self, t):
                self.rebase_calls.append(t)

            def _begin_preview_scrub(self):
                self.scrub_begun = True

            def _flush_scrub_preview(self):
                pass

        playing_self = MockSelf(playing=True)
        EditorModule._on_timeline_playhead_moved(playing_self, 12.5)
        self.assertEqual(playing_self.rebase_calls, [])
        self.assertFalse(playing_self.scrub_begun)

        idle_self = MockSelf(playing=False)
        EditorModule._on_timeline_playhead_moved(idle_self, 12.5)
        self.assertTrue(idle_self.scrub_begun)


class TestAgentPromptWhitelistAligned(unittest.TestCase):
    """剪辑 Agent 提示词里宣传的 action 必须都在真实白名单里，否则模型一提就被拒。"""

    @staticmethod
    def _extract_advertised_actions(src: str) -> set:
        start = src.find("可用 action:")
        assert start >= 0, "未找到剪辑 Agent 提示词里的 action 列表"
        end = src.find("。", start)
        assert end > start
        # 源码里是多段相邻字符串字面量拼接（跨行 + 引号），先去掉引号/换行再按逗号切
        raw = src[start:end].replace('"', " ").replace("\n", " ")
        actions_part = raw.split("可用 action:", 1)[1]
        return {a.strip() for a in actions_part.split(",") if a.strip()}

    def test_prompt_actions_subset_of_allowed_actions(self):
        from app.modules.lego.ai_agent_panel import _AGENT_ALLOWED_ACTIONS

        path = os.path.join(ROOT, "app", "modules", "lego", "editor_module.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        advertised = self._extract_advertised_actions(src)
        advertised -= {"answer", "info"}  # 内建，不需要在白名单里
        unknown = advertised - set(_AGENT_ALLOWED_ACTIONS)
        self.assertEqual(
            unknown, set(),
            f"提示词宣传了白名单里没有的 action: {unknown}（模型一提就会被拒）",
        )

    def test_add_clip_move_clip_not_advertised(self):
        path = os.path.join(ROOT, "app", "modules", "lego", "editor_module.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        advertised = self._extract_advertised_actions(src)
        # 未实现的 action：曾写进提示词却不在白名单/执行分支里，模型一提必被拒
        self.assertNotIn("add_clip", advertised)
        self.assertNotIn("move_clip", advertised)


if __name__ == "__main__":
    unittest.main()
