# -*- coding: utf-8 -*-
"""生成品代理评分（生成抽卡闭环 P0b，方案 §3.2）

核心断言：
- **is_proxy 恒为 True**（项目红线：AI 打分禁当真值）——每条返回路径都查
- 纯黑/单色图 → 崩图闸门压分（总分 ≤0.3）
- 清晰自然图 > 高斯模糊图（拉普拉斯方差区分度）
- 尺寸不符 → size 子分扣减；无期望 → 不罚
- 耗时/重试 → 成本子分扣减
- 垃圾输入 → 中性 0.5 + decode_error，绝不抛出
"""
from __future__ import annotations

import base64

import numpy as np
import pytest

import app.core.ai.gen_critic as gc

cv2 = pytest.importorskip("cv2", reason="gen_critic 解码 data URL 需要 cv2")

rng = np.random.default_rng(42)


def _natural_image(w=512, h=288, seed=7):
    """有结构的自然感测试图：渐变底 + 随机色块 + 边缘（保证 std/熵/清晰度都在线）。"""
    r = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = np.linspace(30, 200, w, dtype=np.uint8)[None, :]
    img[:, :, 1] = np.linspace(20, 160, h, dtype=np.uint8)[:, None]
    img[:, :, 2] = 80
    for _ in range(12):  # 随机锐边矩形色块 → 拉普拉斯方差高
        x0, y0 = int(r.integers(0, w - 60)), int(r.integers(0, h - 60))
        img[y0:y0 + 50, x0:x0 + 50] = r.integers(0, 255, 3)
    return img


def _to_data_url(img):
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


# ── 红线：is_proxy 恒真 ─────────────────────────────────────────────────────


def test_is_proxy_always_true_on_all_paths():
    img = _natural_image()
    for res in (
        gc.score_image(img),
        gc.score_image(_to_data_url(img)),
        gc.score_image("不是图像".encode("utf-8")),
        gc.score_image("data:image/png;base64,%%%"),
        gc.score_image(None),
        gc.score_image(np.zeros((0, 0), dtype=np.uint8)),
    ):
        assert res["is_proxy"] is True
        assert 0.0 <= res["score"] <= 1.0


# ── 崩图闸门 ────────────────────────────────────────────────────────────────


def test_pure_black_image_capped_by_broken_gate():
    black = np.zeros((288, 512, 3), dtype=np.uint8)
    res = gc.score_image(black)
    assert res["score"] <= 0.3
    assert res["detail"]["broken_gate_applied"] is True
    assert res["detail"]["non_broken"] < 0.2


def test_near_monochrome_scores_low():
    flat = np.full((288, 512, 3), 127, dtype=np.uint8)
    res = gc.score_image(flat)
    assert res["score"] <= 0.3


def test_natural_image_not_gated():
    res = gc.score_image(_natural_image())
    assert res["detail"]["broken_gate_applied"] is False
    assert res["detail"]["non_broken"] > 0.5
    assert res["score"] > 0.5


# ── 清晰度 ──────────────────────────────────────────────────────────────────


def test_blurry_scores_lower_than_sharp():
    img = _natural_image()
    sharp_res = gc.score_image(img)
    blur_res = gc.score_image(cv2.GaussianBlur(img, (15, 15), 0))
    assert blur_res["detail"]["lap_var"] < sharp_res["detail"]["lap_var"]
    assert blur_res["detail"]["sharpness"] < sharp_res["detail"]["sharpness"]


# ── 尺寸达标 ────────────────────────────────────────────────────────────────


def test_size_match_and_mismatch():
    img = _natural_image(w=512, h=288)
    assert gc.score_image(img, expected_size="512x288")["detail"]["size"] == 1.0
    res = gc.score_image(img, expected_size="1024x576")  # 比例对、分辨率不对
    assert res["detail"]["size"] == 0.7
    res2 = gc.score_image(img, expected_size="512x512")  # 比例也不对
    assert res2["detail"]["size"] == 0.3
    # 无期望 → 不罚
    assert gc.score_image(img)["detail"]["size"] == 1.0


# ── 成本信号 ────────────────────────────────────────────────────────────────


def test_cost_penalty_for_slow_and_retried():
    img = _natural_image()
    fast = gc.score_image(img, elapsed_ms=8000)["detail"]["cost"]
    slow = gc.score_image(img, elapsed_ms=120000)["detail"]["cost"]
    retried = gc.score_image(img, elapsed_ms=8000, retried=True)["detail"]["cost"]
    assert fast == 1.0
    assert slow < fast
    assert retried < fast
    assert gc.score_image(img)["detail"]["cost"] == 1.0  # 无数据中立


# ── 解码路径 ────────────────────────────────────────────────────────────────


def test_data_url_and_bytes_decode(tmp_path):
    img = _natural_image()
    ok, buf = cv2.imencode(".png", img)
    assert ok
    res_url = gc.score_image(_to_data_url(img))
    res_bytes = gc.score_image(buf.tobytes())
    # 文件路径解码：cv2.imwrite 在中文路径（D:\拾光剪影）下同样失败，
    # 用 Python 写字节（镜像真实调用方的落盘方式），score_image 内部走
    # open()+imdecode 必须能吃 Unicode 路径
    p = tmp_path / "t.png"
    p.write_bytes(buf.tobytes())
    res_path = gc.score_image(str(p))
    for r in (res_url, res_bytes, res_path):
        assert "decode_error" not in r["detail"]
        assert r["score"] > 0.5


def test_garbage_returns_neutral_and_never_raises():
    for garbage in (b"not an image", "data:image/png;base64,!!!", None,
                    "", np.zeros((0, 0), dtype=np.uint8), 12345):
        res = gc.score_image(garbage)
        assert res["score"] == 0.5
        assert "decode_error" in res["detail"]
        assert res["is_proxy"] is True
