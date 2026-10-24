# -*- coding: utf-8 -*-
"""JKL shuttle 逻辑冒烟（无需完整 EditorModule GUI）。"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


class MockHost:
    def __init__(self):
        self._timeline_playing = False
        self._playhead_position = 0.0
        self._media_player = None
        self.start_count = 0
        self.stop_count = 0

    def _playback_rate(self) -> float:
        return 1.0

    def _start_timeline_playback(self):
        self._timeline_playing = True
        self.start_count += 1

    def _stop_timeline_playback(self):
        self._timeline_playing = False
        self.stop_count += 1

    def _rebasing_playback_clock(self, t: float):
        self._playhead_position = float(t)


def main():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    from app.modules.lego.playback_shuttle import PlaybackShuttle, _is_text_input_widget
    from PyQt6.QtWidgets import QLineEdit, QWidget

    errors = []

    # 文本框判定
    le = QLineEdit()
    if not _is_text_input_widget(le):
        errors.append("_is_text_input_widget should detect QLineEdit")
    plain = QWidget()
    if _is_text_input_widget(plain):
        errors.append("_is_text_input_widget should ignore plain QWidget")

    host = MockHost()
    shuttle = PlaybackShuttle(host)
    shuttle.install()
    rate = host._playback_rate

    # 空闲时不影响正常倍速
    if rate() != 1.0:
        errors.append(f"idle rate expected 1.0, got {rate()}")

    # L → 1×，连击 L → 2×
    shuttle.press_l()
    if not host._timeline_playing:
        errors.append("press_l should start timeline playback")
    if rate() != 1.0:
        errors.append(f"first L expected 1.0, got {rate()}")
    shuttle.press_l()
    if rate() != 2.0:
        errors.append(f"double L expected 2.0, got {rate()}")

    # K 暂停
    shuttle.press_k()
    if host._timeline_playing:
        errors.append("K should pause timeline")
    if shuttle.is_active:
        errors.append("K should reset shuttle active state")

    # J 后退档 + 连击加速
    shuttle.press_j()
    if rate() != -1.0:
        errors.append(f"first J expected -1.0, got {rate()}")
    time.sleep(0.05)
    shuttle.press_j()
    shuttle.press_j()
    if rate() != -4.0:
        errors.append(f"triple J expected -4.0, got {rate()}")

    shuttle.stop()

    # 外部 start（如空格）应重置 shuttle 状态
    shuttle.press_l()
    if not shuttle.is_active:
        errors.append("press_l should activate shuttle")
    host._start_timeline_playback()
    if shuttle.is_active:
        errors.append("external start should reset shuttle to idle")

    shuttle.uninstall()
    if host._playback_rate is rate:
        errors.append("uninstall should restore original _playback_rate")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("PASS playback shuttle smoke")
    sys.exit(0)


if __name__ == "__main__":
    main()
