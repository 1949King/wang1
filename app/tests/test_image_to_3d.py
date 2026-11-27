# -*- coding: utf-8 -*-
"""app/tests/test_image_to_3d.py — T5 图片转3D 深度重建 GLB 网格路（2026-11-20）。

契约（方案 T5 节）：
  · parse_image_to_3d_request 纯函数：图源必填，fov 钳制 [30,120]，max_side 钳制 [128,512]；
  · 合成平面 + 桩深度 → GLB 存在 / 顶点数 / 包围盒有限（trimesh 真读回）；
  · 深度不连续剔除：阶跃深度 → 面数 < 满网格（MoGePointMapToMesh 原理）；
  · 深度模型缺失 → ok:false + guidance（绝不触网、不冒充）；
  · trimesh 缺失 → 诚实失败；外链图源 → 诚实失败（本地重建需本地文件）。
本测试不加载真模型：video_depth.available / estimate_depth_bgr 全部打桩。
"""
from __future__ import annotations

import base64
import os
import sys

import numpy as np
import pytest

from app.core import image_to_3d as i3d
from app.core import video_depth


class _Report:
    """StageReporter 桩（stage/progress/note 三出口）。"""

    def __init__(self):
        self.stages = []
        self.notes = []

    def stage(self, name, label=None):
        self.stages.append(name)

    def progress(self, pct):
        pass

    def note(self, text):
        self.notes.append(text)


def _synth_bgr(h=48, w=64):
    """合成 BGR 图（水平渐变，非全黑）。"""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    img[:, :, 1] = 128
    img[:, :, 2] = np.linspace(255, 0, w, dtype=np.uint8)[None, :]
    return img


def _patch_depth(monkeypatch, depth):
    """桩掉深度模型探测与推理（不触网、不加载 ONNX）。"""
    monkeypatch.setattr(
        video_depth, "available",
        lambda: {"ok": True, "available": True, "model": "stub.onnx", "path": "stub.onnx"},
    )
    monkeypatch.setattr(video_depth, "estimate_depth_bgr", lambda img: depth)


def _patch_inbox(monkeypatch, tmp_path):
    """GLB 落盘指向临时目录，避免污染真实收件箱。"""
    from app.core import canvas_bridge
    monkeypatch.setattr(canvas_bridge, "canvas_inbox_dir", lambda: str(tmp_path))


def _src_req(monkeypatch, tmp_path, img):
    """合成图写真 PNG 入临时 inbox，返回指向它的合法请求（图源真实可解析）。"""
    cv2 = pytest.importorskip("cv2")
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(os.path.join(str(tmp_path), "src.png"))
    _patch_inbox(monkeypatch, tmp_path)
    return i3d.parse_image_to_3d_request({"image": "/inbox_file/src.png"})


# ─────────────────────── parse 纯函数 ───────────────────────

def test_parse_requires_image():
    res = i3d.parse_image_to_3d_request({})
    assert res["ok"] is False
    assert res.get("error")


def test_parse_invalid_body():
    assert i3d.parse_image_to_3d_request(None)["ok"] is False
    assert i3d.parse_image_to_3d_request("x")["ok"] is False


def test_parse_fov_clamp():
    assert i3d.parse_image_to_3d_request({"image": "a.png", "fov": 5})["fov"] == 30
    assert i3d.parse_image_to_3d_request({"image": "a.png", "fov": 200})["fov"] == 120
    assert i3d.parse_image_to_3d_request({"image": "a.png"})["fov"] == 60


def test_parse_max_side_clamp():
    assert i3d.parse_image_to_3d_request({"image": "a.png", "max_side": 10})["max_side"] == 128
    assert i3d.parse_image_to_3d_request({"image": "a.png", "max_side": 9999})["max_side"] == 512
    assert i3d.parse_image_to_3d_request({"image": "a.png"})["max_side"] == 320


def test_parse_accepts_aliases():
    for key in ("image", "image_url", "imageUrl", "image_path", "imagePath"):
        res = i3d.parse_image_to_3d_request({key: "a.png"})
        assert res["ok"] is True
        assert res["image"] == "a.png"


# ─────────────────────── 成功路径（合成平面）───────────────────────

def test_flat_plane_glb(monkeypatch, tmp_path):
    pytest.importorskip("cv2")
    trimesh = pytest.importorskip("trimesh")
    img = _synth_bgr()
    _patch_depth(monkeypatch, np.full(img.shape[:2], 0.5, dtype=np.float32))
    req = _src_req(monkeypatch, tmp_path, img)
    res = i3d.run_image_to_3d(req, _Report())
    assert res["ok"] is True, res
    assert res["model_url"].startswith("/inbox_file/")
    assert res["model_url"].endswith(".glb")
    assert os.path.isfile(res["model_path"])
    assert os.path.getsize(res["model_path"]) > 0
    # 顶点数 = 网格点数（48×64，未降采样）；面数 = 满网格三角化
    assert res["vertices"] == 48 * 64
    assert res["faces"] == 2 * 63 * 47
    assert "2.5D" in res["note"]
    # trimesh 真读回：包围盒有限（GLB 含场景图 ⇒ force="mesh" 取单网格）
    mesh = trimesh.load(res["model_path"], file_type="glb", force="mesh")
    bounds = np.asarray(mesh.bounds)
    assert np.all(np.isfinite(bounds))
    assert len(mesh.vertices) == 48 * 64


def test_discontinuity_culls_faces(monkeypatch, tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("trimesh")
    img = _synth_bgr()
    depth = np.zeros(img.shape[:2], dtype=np.float32)
    depth[:, 32:] = 1.0   # 垂直阶跃：跨列三角面应被剔除
    _patch_depth(monkeypatch, depth)
    req = _src_req(monkeypatch, tmp_path, img)
    res = i3d.run_image_to_3d(req, _Report())
    assert res["ok"] is True, res
    full = 2 * 63 * 47
    assert res["faces"] < full
    assert res["culled"] > 0
    assert res["faces"] + res["culled"] == full


def test_data_url_source(monkeypatch, tmp_path):
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("trimesh")
    img = _synth_bgr()
    ok, buf = cv2.imencode(".png", img)
    assert ok
    data_url = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
    _patch_depth(monkeypatch, np.full(img.shape[:2], 0.5, dtype=np.float32))
    _patch_inbox(monkeypatch, tmp_path)
    req = i3d.parse_image_to_3d_request({"image": data_url})
    res = i3d.run_image_to_3d(req, _Report())
    assert res["ok"] is True, res


def test_inbox_file_source(monkeypatch, tmp_path):
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("trimesh")
    img = _synth_bgr()
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(os.path.join(str(tmp_path), "src.png"))
    _patch_depth(monkeypatch, np.full(img.shape[:2], 0.5, dtype=np.float32))
    _patch_inbox(monkeypatch, tmp_path)
    req = i3d.parse_image_to_3d_request({"image": "/inbox_file/src.png"})
    res = i3d.run_image_to_3d(req, _Report())
    assert res["ok"] is True, res


# ─────────────────────── 诚实失败路径 ───────────────────────

def test_model_missing_guidance(monkeypatch, tmp_path):
    pytest.importorskip("cv2")
    monkeypatch.setattr(
        video_depth, "available",
        lambda: {"ok": False, "available": False,
                 "reason": "未找到深度模型（.onnx）", "hint": "请下载 Depth-Anything-V2-Small …"},
    )
    called = []
    monkeypatch.setattr(video_depth, "estimate_depth_bgr",
                        lambda img: called.append(1) or None)
    _patch_inbox(monkeypatch, tmp_path)
    req = i3d.parse_image_to_3d_request({"image": "unused.png"})
    res = i3d.run_image_to_3d(req, _Report())
    assert res["ok"] is False
    assert res.get("guidance")
    assert not called   # 模型缺失绝不推理


def test_depth_none_honest(monkeypatch, tmp_path):
    pytest.importorskip("cv2")
    _patch_depth(monkeypatch, None)
    req = _src_req(monkeypatch, tmp_path, _synth_bgr())
    res = i3d.run_image_to_3d(req, _Report())
    assert res["ok"] is False
    assert "深度推理失败" in res.get("error", "")


def test_trimesh_missing_honest(monkeypatch, tmp_path):
    pytest.importorskip("cv2")
    img = _synth_bgr()
    _patch_depth(monkeypatch, np.full(img.shape[:2], 0.5, dtype=np.float32))
    req = _src_req(monkeypatch, tmp_path, img)
    monkeypatch.setitem(sys.modules, "trimesh", None)   # import trimesh ⇒ ImportError
    res = i3d.run_image_to_3d(req, _Report())
    assert res["ok"] is False
    assert "trimesh" in res.get("error", "")


def test_external_url_honest_failure(monkeypatch, tmp_path):
    _patch_inbox(monkeypatch, tmp_path)
    req = i3d.parse_image_to_3d_request({"image": "https://example.com/a.png"})
    res = i3d.run_image_to_3d(req, _Report())
    assert res["ok"] is False
    assert res.get("error")
