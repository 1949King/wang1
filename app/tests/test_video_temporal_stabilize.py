"""app/tests/test_video_temporal_stabilize.py — 时序稳定器契约（T1 项一，2026-11-20）。

锁死 stabilize_frame_sequence 行为：
  - 静态区亮度抖动 ⇒ 稳定后帧间 MAD 下降。
  - 场景切变 ⇒ 不混合（无鬼影）。
  - 空目录 ⇒ False。
  - 单帧 ⇒ True（无需稳定）。
  - progress_callback 抛异常 ⇒ 不崩。
  - 诚实标注：时序稳定后滤波，非时序超分模型。
"""
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.core.video_temporal_stabilize import stabilize_frame_sequence


def _write_frames(frame_dir, frames):
    """把 numpy 帧列表写入目录（f_000001.png 起），Unicode 安全。"""
    os.makedirs(frame_dir, exist_ok=True)
    for i, frame in enumerate(frames, 1):
        ok, buf = cv2.imencode(".png", frame)
        if ok:
            buf.tofile(os.path.join(frame_dir, f"f_{i:06d}.png"))


def _read_frames(frame_dir):
    """读取目录内帧序列，Unicode 安全。"""
    files = sorted(f for f in os.listdir(frame_dir) if f.startswith("f_") and f.endswith(".png"))
    frames = []
    for f in files:
        data = np.fromfile(os.path.join(frame_dir, f), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is not None:
            frames.append(img)
    return frames


def _mad(frames):
    """相邻帧平均绝对差（MAD）。"""
    if len(frames) < 2:
        return 0.0
    diffs = [np.mean(cv2.absdiff(frames[i], frames[i + 1])) for i in range(len(frames) - 1)]
    return float(np.mean(diffs))


class TestTemporalStabilize:
    """stabilize_frame_sequence 契约。"""

    def test_brightness_jitter_reduced(self, tmp_path):
        """静态场景亮度抖动 ⇒ 稳定后帧间 MAD 下降。"""
        frame_dir = str(tmp_path / "frames")
        base = np.full((64, 64, 3), 128, dtype=np.uint8)
        # 模拟亮度抖动：±15
        frames = []
        for i in range(8):
            jitter = 15 if i % 2 == 0 else -15
            f = np.clip(base.astype(np.int16) + jitter, 0, 255).astype(np.uint8)
            frames.append(f)
        _write_frames(frame_dir, frames)
        mad_before = _mad(frames)

        ok = stabilize_frame_sequence(frame_dir)
        assert ok is True

        after = _read_frames(frame_dir)
        mad_after = _mad(after)
        assert mad_after < mad_before, f"MAD 应下降: {mad_before:.2f} → {mad_after:.2f}"

    def test_scene_cut_no_ghost(self, tmp_path):
        """场景切变（全黑→全白）⇒ 不混合，切变帧保持原样。"""
        frame_dir = str(tmp_path / "frames")
        black = np.zeros((64, 64, 3), dtype=np.uint8)
        white = np.full((64, 64, 3), 255, dtype=np.uint8)
        frames = [black, black, white, white]
        _write_frames(frame_dir, frames)

        ok = stabilize_frame_sequence(frame_dir)
        assert ok is True

        after = _read_frames(frame_dir)
        # 切变处（帧2→帧3）不应被混合：帧3 仍应接近全白
        assert np.mean(after[2]) > 200, "场景切变帧被混合产生鬼影"

    def test_empty_dir_returns_false(self, tmp_path):
        """空目录 ⇒ False。"""
        frame_dir = str(tmp_path / "empty")
        os.makedirs(frame_dir)
        assert stabilize_frame_sequence(frame_dir) is False

    def test_single_frame_returns_true(self, tmp_path):
        """单帧 ⇒ True（无需稳定）。"""
        frame_dir = str(tmp_path / "single")
        frame = np.full((32, 32, 3), 100, dtype=np.uint8)
        _write_frames(frame_dir, [frame])
        assert stabilize_frame_sequence(frame_dir) is True

    def test_progress_callback_exception_no_crash(self, tmp_path):
        """progress_callback 抛异常 ⇒ 不崩，仍返回 True。"""
        frame_dir = str(tmp_path / "frames")
        base = np.full((32, 32, 3), 128, dtype=np.uint8)
        frames = [base.copy() for _ in range(4)]
        _write_frames(frame_dir, frames)

        def _bad_callback(pct, msg):
            raise RuntimeError("callback exploded")

        ok = stabilize_frame_sequence(frame_dir, progress_callback=_bad_callback)
        assert ok is True

    def test_nonexistent_dir_returns_false(self):
        """目录不存在 ⇒ False，不抛。"""
        assert stabilize_frame_sequence("/nonexistent/dir") is False

    def test_strength_zero_minimal_change(self, tmp_path):
        """strength=0 ⇒ 几乎不改变帧（保守边界）。"""
        frame_dir = str(tmp_path / "frames")
        base = np.full((32, 32, 3), 128, dtype=np.uint8)
        frames = [np.clip(base.astype(np.int16) + (10 if i % 2 else -10), 0, 255).astype(np.uint8)
                  for i in range(6)]
        _write_frames(frame_dir, frames)
        mad_before = _mad(frames)

        ok = stabilize_frame_sequence(frame_dir, strength=0.0)
        assert ok is True
        after = _read_frames(frame_dir)
        mad_after = _mad(after)
        # strength=0 时变化极小（允许浮点误差）
        assert abs(mad_after - mad_before) < 2.0
