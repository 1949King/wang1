"""app/tests/test_rife_video_job.py — 补帧任务体行为契约（T4 项二，2026-11-20）。

run_interpolate 的诚实降级与失败路径（全部本地桩，绝不触网）：
  1. 模型缺失 ⇒ ok:false + guidance（不降级冒充、不下载）。
  2. 外链视频（path=""）⇒ ok:false 诚实失败。
  3. RIFE 加载失败 ⇒ 降级光流，engine="flow" degraded=True，仍产出成片。
  4. RIFE 加载成功 ⇒ engine="rife" degraded=False，frames_added=(N-1)(m-1)。

帧 helper / mux / inbox 均以 monkeypatch 桩替，避免真实 ffmpeg 依赖。
"""
import os

import pytest

pytest.importorskip("torch")
cv2 = pytest.importorskip("cv2")
import numpy as np

from app.core.video_interpolate_job import parse_interpolate_request, run_interpolate


class _Reporter:
    """StageReporter 桩：记录阶段/进度/附注。"""

    def __init__(self):
        self.stages = []
        self.progresses = []
        self.notes = []

    def stage(self, name, label=None):
        self.stages.append(name)

    def progress(self, pct):
        self.progresses.append(pct)

    def note(self, text):
        self.notes.append(text)


def _write_frame(path, value):
    """写一张 32x32 纯色 BGR 帧（Unicode 安全）。"""
    img = np.full((32, 32, 3), value, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(path)


def _req(src, multiplier=2):
    return parse_interpolate_request({"video_path": str(src), "multiplier": multiplier})


class TestModelMissing:
    """模型缺失：诚实报错 + 引导，不触网。"""

    def test_returns_guidance(self, monkeypatch, tmp_path):
        src = tmp_path / "a.mp4"
        src.write_bytes(b"\x00" * 64)
        monkeypatch.setattr(
            "app.core.canvas_aigc._normalize_reference_video",
            lambda v, **kw: {"ok": True, "url": "x", "path": str(src)},
        )
        monkeypatch.setattr("app.core.neural.rife_engine.find_rife_model", lambda: "")
        res = run_interpolate(_req(src), _Reporter())
        assert res["ok"] is False
        assert res.get("guidance")
        assert "rife49.pth" in res["guidance"]


class TestExternalLink:
    """外链视频（本地无文件）诚实失败。"""

    def test_external_path_empty_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.core.canvas_aigc._normalize_reference_video",
            lambda v, **kw: {"ok": True, "url": "http://external/v.mp4", "path": ""},
        )
        res = run_interpolate(_req(tmp_path / "a.mp4"), _Reporter())
        assert res["ok"] is False
        assert res.get("error")


class TestDegradation:
    """RIFE 加载失败 ⇒ 降级光流仍产出成片。"""

    def _patch_pipeline(self, monkeypatch, tmp_path, load_ok):
        src = tmp_path / "a.mp4"
        src.write_bytes(b"\x00" * 64)
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        monkeypatch.setattr(
            "app.core.canvas_aigc._normalize_reference_video",
            lambda v, **kw: {"ok": True, "url": "x", "path": str(src)},
        )
        monkeypatch.setattr("app.core.neural.rife_engine.find_rife_model", lambda: "/fake/rife49.pth")
        monkeypatch.setattr("app.core.canvas_bridge.canvas_inbox_dir", lambda: str(inbox))
        monkeypatch.setattr("app.core.ffmpeg_utils.get_ffmpeg", lambda: "/fake/ffmpeg")
        monkeypatch.setattr("app.core.ffmpeg_utils.mux_source_audio", lambda *a, **kw: False)
        monkeypatch.setattr("app.core.generation_postprocess._read_video_fps", lambda p: 24.0)

        def _fake_extract(ffmpeg, video_path, out_dir):
            _write_frame(os.path.join(out_dir, "f_000001.png"), 10)
            _write_frame(os.path.join(out_dir, "f_000002.png"), 200)
            return 2

        def _fake_encode(ffmpeg, frame_dir, out_path, fps):
            with open(out_path, "wb") as f:
                f.write(b"\x00" * 128)
            return True

        monkeypatch.setattr("app.core.generation_postprocess._extract_frames", _fake_extract)
        monkeypatch.setattr("app.core.generation_postprocess._encode_frames", _fake_encode)
        monkeypatch.setattr("app.core.neural.rife_engine.RifeEngine.load", lambda self, p="": load_ok)
        return src, inbox

    def test_load_fail_degrades_to_flow(self, monkeypatch, tmp_path):
        src, inbox = self._patch_pipeline(monkeypatch, tmp_path, load_ok=False)
        res = run_interpolate(_req(src, 2), _Reporter())
        assert res["ok"] is True
        assert res["engine"] == "flow"
        assert res["degraded"] is True
        assert res["frames_added"] == 1  # (2-1)*(2-1)
        assert res["fps"] == 48.0
        assert os.path.isfile(res["video_path"])

    def test_load_ok_uses_rife(self, monkeypatch, tmp_path):
        src, inbox = self._patch_pipeline(monkeypatch, tmp_path, load_ok=True)
        # 桩替推理：返回与输入同形的 RGB uint8（不跑真实前向）
        monkeypatch.setattr(
            "app.core.neural.rife_engine.RifeEngine.interpolate_pair",
            lambda self, a, b, t=0.5: np.full_like(a, 128),
        )
        res = run_interpolate(_req(src, 3), _Reporter())
        assert res["ok"] is True
        assert res["engine"] == "rife"
        assert res["degraded"] is False
        assert res["frames_added"] == 2  # (2-1)*(3-1)
        assert res["fps"] == 72.0
