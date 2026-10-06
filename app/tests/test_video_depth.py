"""app/tests/test_video_depth.py — 深度提取的**诚实性**回归（2026-10-06）。

这个模块的红线只有一条，但它最重要：**深度必须来自真正的深度模型**。
模型缺失时**只能如实失败**，绝不许"退回灰度/边缘/模糊"来冒充深度
（那是本项目明令禁止的「回退冒充 AI」）。本测试把这条线钉死：

  ① 没模型 ⇒ `available()` 如实报告 + 给获取方式；
  ② 没模型 ⇒ `estimate_depth_bgr()` 返回 **None**（不是灰度图）；图像/视频提取返回 `ok=False`；
  ③ **源码级锁**：本模块**不得**出现 `COLOR_BGR2GRAY` 之类"把灰度当深度"的写法；
  ④ 归一化判据：全平输入 → 全 0（不制造假对比度）。
"""
import io
import os

import pytest

from app.core import video_depth as vd

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "core", "video_depth.py")


def _no_model(monkeypatch):
    monkeypatch.setattr(vd, "find_model", lambda: "")


# ─────────────────────── ① 如实报告 ───────────────────────

def test_available_reports_missing_model_honestly(monkeypatch):
    _no_model(monkeypatch)
    av = vd.available()
    assert av["ok"] is False and av["available"] is False
    assert "深度模型" in av["reason"]
    # 必须给出**获取方式**，否则用户只能干瞪眼
    assert "hf-mirror.com" in av["hint"]
    # 必须明确声明不会拿灰度冒充
    assert "冒充" in av["hint"] or "不会" in av["hint"]


def test_available_reports_model_when_present():
    av = vd.available()
    if not av.get("available"):
        pytest.skip("本机未放置深度模型（属预期：诚实失败路径已由上面的用例覆盖）")
    assert av["model"].endswith(".onnx")
    assert av["size_mb"] > 1


# ─────────────────────── ② 没模型就绝不产出假深度 ───────────────────────

def test_no_model_returns_none_not_grayscale(monkeypatch):
    import numpy as np
    _no_model(monkeypatch)
    img = np.full((32, 32, 3), 120, dtype=np.uint8)
    assert vd.estimate_depth_bgr(img) is None, "没模型却返回了图像 ⇒ 疑似灰度冒充"


def test_extract_image_fails_honestly(monkeypatch, tmp_path):
    _no_model(monkeypatch)
    r = vd.extract_depth_image("whatever.png", str(tmp_path / "o.png"))
    assert r["ok"] is False and r.get("available") is False
    assert not (tmp_path / "o.png").exists(), "失败却留下了产物"


def test_extract_video_fails_honestly(monkeypatch, tmp_path):
    _no_model(monkeypatch)
    r = vd.extract_depth_video("whatever.mp4", str(tmp_path / "o.mp4"))
    assert r["ok"] is False and r.get("available") is False
    assert not (tmp_path / "o.mp4").exists(), "失败却留下了产物"


# ─────────────────────── ③ 源码级诚实锁 ───────────────────────

def test_source_forbids_gray_fallback():
    src = io.open(SRC, encoding="utf-8").read()
    for bad in ("COLOR_BGR2GRAY", "convert_to_grayscale"):
        assert bad not in src, f"模块里出现 {bad} ⇒ 有把灰度当深度的嫌疑（红线）"
    # 必须真的走 onnxruntime 推理
    assert "onnxruntime" in src
    assert "InferenceSession" in src


# ─────────────────────── ④ 归一化判据 ───────────────────────

def test_to_gray_u8_maps_range():
    import numpy as np
    d = np.array([[0.0, 1.0], [0.5, 2.0]], dtype="float32")
    g = vd.to_gray_u8(d)
    assert g.dtype == np.uint8
    assert int(g.min()) == 0 and int(g.max()) == 255


def test_to_gray_u8_flat_input_is_zero_not_fake_contrast():
    import numpy as np
    g = vd.to_gray_u8(np.full((4, 4), 3.14, dtype="float32"))
    assert int(g.max()) == 0, "全平输入不该被造出假对比度"


# ─────────────────────── ⑤ 真模型在位时：形状与"非平凡" ───────────────────────

def test_real_inference_shape_and_nontrivial():
    """模型在位时真跑一次：形状对齐 + 输出不是常量（**不验证语义** —— 语义需真实参考片）。"""
    if not vd.available().get("available"):
        pytest.skip("本机未放置深度模型")
    import numpy as np
    img = np.zeros((96, 128, 3), dtype=np.uint8)
    img[:, :] = 200
    img[30:90, 20:100] = 60
    d = vd.estimate_depth_bgr(img)
    assert d is not None
    assert d.shape == (96, 128)
    g = vd.to_gray_u8(d)
    assert int(g.max()) - int(g.min()) > 10, "输出近似常量 ⇒ 可疑"
