"""
JKL 渐进变速 Shuttle
====================
对标 CapCut / Premiere 的专业变速 shuttle。
- J 键（后退）：-1× → -2× → -4× → -8×（连击递增；按住保持档位）
- K 键（暂停）：立即 0×（tap 暂停，不触发连击加速）
- L 键（前进）：1× → 2× → 4× → 8×（连击递增；按住保持档位）
- 松键后 300ms 渐变回 0×（不硬切）
- 非播放状态下按 J/L 会自动开始播放
- 空格/C/文本框焦点不受影响

接入方式（零侵入宿主）：
    from app.modules.lego.playback_shuttle import PlaybackShuttle
    self._shuttle = PlaybackShuttle(self)
    self._shuttle.install()
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Set, Tuple

from PySide6.QtCore import QObject, QTimer, QEvent, Signal, Qt

import logging

logger = logging.getLogger(__name__)


# Shuttle 可用的速率档位（从 -8× 到 +8×，步进 1×/2×/4×/8×）
_SHUTTLE_SPEEDS: Tuple[float, ...] = (0.0, -1.0, 1.0, -2.0, 2.0, -4.0, 4.0, -8.0, 8.0)
# 连击判断窗口（ms）— 在此窗口内连续按同一方向键视为加速
_COOLDOWN_MS = 320
# 松键渐变时间（ms）
_DECEL_MS = 300
# 拦截的键集合
_JKL_KEYS = {Qt.Key.Key_J, Qt.Key.Key_K, Qt.Key.Key_L}


def _is_text_input_widget(widget: object) -> bool:
    """焦点在可编辑文本控件上时不接管 JKL。"""
    if widget is None:
        return False
    try:
        from PySide6.QtWidgets import (
            QComboBox,
            QDoubleSpinBox,
            QLineEdit,
            QPlainTextEdit,
            QSpinBox,
            QTextEdit,
        )
    except Exception:
        return False
    if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox)):
        return True
    if isinstance(widget, QComboBox) and widget.isEditable():
        return True
    return False


class PlaybackShuttle(QObject):
    """
    JKL 变速 shuttle — 独立模块，不碰播放主时钟冻结区。
    通过覆盖宿主的 `_playback_rate` 方法 + 应用级 event filter 接管 JKL 键。
    """

    rate_changed = Signal(float)
    finished = Signal()

    def __init__(self, host: object):
        parent = host if isinstance(host, QObject) else None
        super().__init__(parent)
        self._host = host
        self._speed_idx = 0
        self._last_j_ts = 0.0
        self._last_l_ts = 0.0
        self._enabled = False
        self._held_keys: Set[int] = set()
        self._decel_timer = QTimer(self)
        self._decel_timer.setInterval(16)
        self._decel_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._decel_timer.timeout.connect(self._step_decel)
        self._decel_start_rate = 0.0
        self._decel_elapsed_ms = 0.0
        self._temp_multiplier = 0.0
        self._original_rate_getter: Optional[Callable[[], float]] = None
        self._original_start: Optional[Callable] = None
        self._original_stop: Optional[Callable] = None
        self._app = None
        self._suppress_external_reset = False
        self._installed = False

    # ── 对外安装接口 ──────────────────────────────────────────────

    def install(self) -> None:
        """覆盖宿主 _playback_rate + 安装应用级 event filter 拦截 JKL 键。"""
        if self._installed:
            return
        host = self._host
        if hasattr(host, "_playback_rate"):
            self._original_rate_getter = host._playback_rate

            def _patched_rate() -> float:
                base = 1.0
                if self._original_rate_getter is not None:
                    try:
                        base = float(self._original_rate_getter())
                    except Exception:
                        base = 1.0
                if not self.is_active:
                    return base
                shuttle_rate = self._shuttle_multiplier()
                if shuttle_rate == 0.0:
                    return 0.0
                return base * shuttle_rate

            host._playback_rate = _patched_rate

        if hasattr(host, "_stop_timeline_playback"):
            self._original_stop = host._stop_timeline_playback

            def _patched_stop(*args, **kwargs):
                if not self._suppress_external_reset:
                    self._reset_idle(notify=False)
                return self._original_stop(*args, **kwargs)

            host._stop_timeline_playback = _patched_stop

        if hasattr(host, "_start_timeline_playback"):
            self._original_start = host._start_timeline_playback

            def _patched_start(*args, **kwargs):
                if not self._suppress_external_reset:
                    self._reset_idle(notify=False)
                return self._original_start(*args, **kwargs)

            host._start_timeline_playback = _patched_start

        try:
            from PySide6.QtWidgets import QApplication

            self._app = QApplication.instance()
            if self._app is not None:
                self._app.installEventFilter(self)
        except Exception:
            self._app = None

        self._installed = True

    def uninstall(self) -> None:
        """恢复宿主原始方法 + 移除 event filter。"""
        host = self._host
        if self._original_rate_getter is not None and hasattr(host, "_playback_rate"):
            host._playback_rate = self._original_rate_getter
        if self._original_stop is not None and hasattr(host, "_stop_timeline_playback"):
            host._stop_timeline_playback = self._original_stop
        if self._original_start is not None and hasattr(host, "_start_timeline_playback"):
            host._start_timeline_playback = self._original_start
        if self._app is not None:
            try:
                self._app.removeEventFilter(self)
            except Exception:
                logger.debug("忽略异常（原为 pass）: playback_shuttle.py", exc_info=True)
            self._app = None
        self.stop()
        self._installed = False

    # ── EventFilter 拦截 JKL ─────────────────────────────────────

    def eventFilter(self, obj: object, event) -> bool:  # noqa: ARG002
        if not self._installed:
            return False
        et = event.type()
        if et not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if not self._focus_belongs_to_host():
            return False
        try:
            from PySide6.QtWidgets import QApplication

            fw = QApplication.focusWidget()
        except Exception:
            fw = None
        if _is_text_input_widget(fw):
            return False
        if et == QEvent.Type.KeyPress:
            return self._handle_key_press(event)
        if et == QEvent.Type.KeyRelease:
            return self._handle_key_release(event)
        return False

    def _focus_belongs_to_host(self) -> bool:
        host = self._host
        try:
            from PySide6.QtWidgets import QApplication, QWidget
        except Exception:
            return True
        fw = QApplication.focusWidget()
        if fw is None:
            return isinstance(host, QWidget) and host.isVisible()
        if fw is host:
            return True
        p = fw
        while p is not None:
            if p is host:
                return True
            try:
                p = p.parentWidget()
            except Exception:
                break
        return False

    def _handle_key_press(self, event) -> bool:
        key = event.key()
        if key not in _JKL_KEYS:
            return False
        mods = event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
            | Qt.KeyboardModifier.ShiftModifier
        )
        if mods:
            return False
        if getattr(event, "isAutoRepeat", lambda: False)():
            return True
        self._held_keys.add(key)
        if key == Qt.Key.Key_J:
            self.press_j()
        elif key == Qt.Key.Key_L:
            self.press_l()
        elif key == Qt.Key.Key_K:
            self.press_k()
        event.accept()
        return True

    def _handle_key_release(self, event) -> bool:
        key = event.key()
        if key not in _JKL_KEYS:
            return False
        if getattr(event, "isAutoRepeat", lambda: False)():
            return True
        self._held_keys.discard(key)
        if key == Qt.Key.Key_K:
            event.accept()
            return True
        if not self._held_keys and self._enabled:
            self.release()
        event.accept()
        return True

    # ── 按键入口 ──────────────────────────────────────────────────

    def press_j(self) -> None:
        self._accelerate(-1)

    def press_l(self) -> None:
        self._accelerate(+1)

    def press_k(self) -> None:
        self.stop()

    def release(self) -> None:
        if self._speed_idx == 0:
            return
        cur = _SHUTTLE_SPEEDS[self._speed_idx]
        self._decel_start_rate = cur
        self._decel_elapsed_ms = 0.0
        self._temp_multiplier = cur
        self._decel_timer.start()
        self._speed_idx = 0
        self._enabled = False

    def stop(self) -> None:
        self._decel_timer.stop()
        self._speed_idx = 0
        self._enabled = False
        self._temp_multiplier = 0.0
        self._held_keys.clear()
        self._last_j_ts = 0.0
        self._last_l_ts = 0.0
        self.rate_changed.emit(0.0)
        self._sync_host_pause()

    def _reset_idle(self, notify: bool = False) -> None:
        self._decel_timer.stop()
        self._speed_idx = 0
        self._enabled = False
        self._temp_multiplier = 0.0
        self._held_keys.clear()
        self._last_j_ts = 0.0
        self._last_l_ts = 0.0
        if notify:
            self.rate_changed.emit(0.0)

    # ── 内部逻辑 ──────────────────────────────────────────────────

    def _accelerate(self, direction: int) -> None:
        self._decel_timer.stop()
        now = time.time() * 1000.0
        if direction < 0:
            cooldown_ok = (now - self._last_j_ts) <= _COOLDOWN_MS
            self._last_j_ts = now
        else:
            cooldown_ok = (now - self._last_l_ts) <= _COOLDOWN_MS
            self._last_l_ts = now

        cur_speed = _SHUTTLE_SPEEDS[self._speed_idx]
        cur_dir = -1 if cur_speed < 0 else (1 if cur_speed > 0 else 0)

        if cur_dir == direction and cooldown_ok:
            abs_cur = abs(cur_speed)
            abs_next = abs_cur * 2 if abs_cur < 8.0 else abs_cur
            self._speed_idx = _SHUTTLE_SPEEDS.index(direction * abs_next)
        else:
            self._speed_idx = _SHUTTLE_SPEEDS.index(direction * 1.0)

        self._enabled = True
        self._sync_host_playback()
        self.rate_changed.emit(_SHUTTLE_SPEEDS[self._speed_idx])

    def _step_decel(self) -> None:
        self._decel_elapsed_ms += 16.0
        t = min(1.0, self._decel_elapsed_ms / _DECEL_MS)
        self._temp_multiplier = self._decel_start_rate * (1.0 - t)
        self.rate_changed.emit(self._temp_multiplier)
        if t >= 1.0:
            self._decel_timer.stop()
            self._temp_multiplier = 0.0
            self.finished.emit()
            self._sync_host_pause()

    def _shuttle_multiplier(self) -> float:
        if self._decel_timer.isActive():
            return float(self._temp_multiplier)
        if self._enabled:
            return _SHUTTLE_SPEEDS[self._speed_idx]
        return 1.0

    # ── 宿主同步 ──────────────────────────────────────────────────

    def _sync_host_playback(self) -> None:
        host = self._host
        rate = _SHUTTLE_SPEEDS[self._speed_idx]
        self._suppress_external_reset = True
        try:
            if hasattr(host, "_start_timeline_playback"):
                if not getattr(host, "_timeline_playing", False):
                    host._start_timeline_playback()
        finally:
            self._suppress_external_reset = False
        if hasattr(host, "_media_player") and host._media_player is not None:
            try:
                host._media_player.setPlaybackRate(max(0.05, abs(rate)))
            except Exception:
                logger.debug("忽略异常（原为 pass）: playback_shuttle.py", exc_info=True)
        if hasattr(host, "_rebasing_playback_clock"):
            try:
                host._rebasing_playback_clock(
                    float(getattr(host, "_playhead_position", 0) or 0)
                )
            except Exception:
                logger.debug("忽略异常（原为 pass）: playback_shuttle.py", exc_info=True)

    def _sync_host_pause(self) -> None:
        host = self._host
        self._suppress_external_reset = True
        try:
            if hasattr(host, "_stop_timeline_playback"):
                host._stop_timeline_playback()
        finally:
            self._suppress_external_reset = False
        if hasattr(host, "_media_player") and host._media_player is not None:
            try:
                host._media_player.setPlaybackRate(1.0)
            except Exception:
                logger.debug("忽略异常（原为 pass）: playback_shuttle.py", exc_info=True)

    # ── 状态查询 ──────────────────────────────────────────────────

    @property
    def current_speed(self) -> float:
        if self._decel_timer.isActive():
            return float(self._temp_multiplier)
        return _SHUTTLE_SPEEDS[self._speed_idx]

    @property
    def is_active(self) -> bool:
        return self._enabled or self._decel_timer.isActive()
