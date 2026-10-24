# -*- coding: utf-8 -*-
"""局部重绘（抽卡闭环 P4，方案 §四 P4 验收行）

核心验收：**人为构造局部崩图 → 走 inpaint 而非重抽；原满意区域像素不变**。
"像素不变"用 np.array_equal 钉死（不是"看起来差不多"）。

覆盖：
- plan_repair：好图 → needs_repair=False（且不发请求）；局部崩图 → 定位到坏块
- build_mask：坏区为白、其余为黑
- composite：**坏区外像素 bit-exact 等于原图**；坏区取新图；尺寸不一致先 resize
- repair_image：无坏区不发请求；注入式 inpaint 被调用（证明走的是 inpaint 不是重抽）；
  结果只在坏区变化；inpaint 失败 → ok=False 且**不伪造图**
"""
from __future__ import annotations

import base64

import numpy as np
import pytest

import app.core.ai.inpaint_retry as ir

cv2 = pytest.importorskip("cv2", reason="蒙版/合成需要 cv2")


def _natural(w=256, h=256, seed=11):
    """真实感纹理：渐变底 + 随机色块 + **逐像素噪声**。

    噪声是必需的——纯渐变的某些格子会因"过于均匀"被判成坏区
    （首版夹具就因此让"好图无需修复"用例假失败）。真实照片每个格子都有纹理，
    夹具必须同等地有。
    """
    r = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = np.linspace(40, 210, w, dtype=np.uint8)[None, :]
    img[:, :, 1] = np.linspace(30, 170, h, dtype=np.uint8)[:, None]
    img[:, :, 2] = 100
    for _ in range(12):
        x0, y0 = int(r.integers(0, w - 40)), int(r.integers(0, h - 40))
        img[y0:y0 + 32, x0:x0 + 32] = r.integers(0, 255, 3)
    noise = r.normal(0, 22, img.shape)
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def _url(img):
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _broken(img, box):
    """在 box 处贴一块死黑（模拟局部崩图）。"""
    out = img.copy()
    x, y, w, h = box
    out[y:y + h, x:x + w] = 0
    return out


def _decode(url):
    payload = url.split(",", 1)[1]
    return cv2.imdecode(np.frombuffer(base64.b64decode(payload), dtype=np.uint8),
                        cv2.IMREAD_COLOR)


# ── plan_repair ─────────────────────────────────────────────────────────────


def test_good_image_needs_no_repair():
    plan = ir.plan_repair(_natural())
    assert plan["needs_repair"] is False
    assert plan["boxes"] == []


def test_broken_corner_is_located():
    img = _natural()
    bad = _broken(img, (0, 0, 64, 64))          # 左上角崩
    plan = ir.plan_repair(bad, grid=4)
    assert plan["needs_repair"] is True
    assert plan["count"] >= 1
    # 至少有一个坏格落在左上区域
    assert any(b["box"][0] < 64 and b["box"][1] < 64 for b in plan["boxes"])


def test_garbage_image_has_no_boxes_not_crash():
    assert ir.plan_repair(b"not an image")["needs_repair"] is False


def test_low_contrast_textured_region_is_not_flagged():
    """设计洞察钉死：**低对比但有层次**的区域（天空/墙面）不算坏区。

    格级检测若沿用整图的 std 判据，会把真实照片里大片低对比区判成坏区 ⇒
    白花钱去"修"没坏的地方。故格级用「死区」判据（极端像素 + 单色支配）。
    """
    r = np.random.default_rng(5)
    img = np.full((256, 256, 3), 128, dtype=np.uint8)
    # 右半边：低对比但带纹理（模拟天空/墙面）——std 低，但色阶层次完整
    sky = 120 + r.normal(0, 6, (256, 128, 3))
    img[:, 128:] = np.clip(sky, 0, 255).astype(np.uint8)
    # 左半边：给足纹理，避免整体被判低分
    img[:, :128] = np.clip(120 + r.normal(0, 25, (256, 128, 3)), 0, 255).astype(np.uint8)
    plan = ir.plan_repair(img, grid=4)
    right_boxes = [b for b in plan["boxes"] if b["box"][0] >= 128]
    assert right_boxes == [], f"低对比纹理区被误判为坏区: {right_boxes}"


# ── build_mask ──────────────────────────────────────────────────────────────


def test_mask_is_white_in_box_black_elsewhere():
    img = _natural()
    boxes = [{"box": (64, 64, 64, 64)}]
    m = _decode(ir.build_mask(img, boxes, pad=0))
    mask = cv2.cvtColor(m, cv2.COLOR_BGR2GRAY)
    assert int(mask[64:128, 64:128].min()) == 255   # 坏区全白
    assert int(mask[0:32, 0:32].max()) == 0         # 远处全黑
    assert int(mask[192:256, 192:256].max()) == 0
    # 尺寸与原图一致
    assert mask.shape == (256, 256)


def test_mask_pad_expands_repair_area():
    img = _natural()
    m0 = cv2.cvtColor(_decode(ir.build_mask(img, [{"box": (100, 100, 40, 40)}], pad=0)),
                      cv2.COLOR_BGR2GRAY)
    m8 = cv2.cvtColor(_decode(ir.build_mask(img, [{"box": (100, 100, 40, 40)}], pad=8)),
                      cv2.COLOR_BGR2GRAY)
    assert m8.sum() > m0.sum()   # 外扩后白区更大


# ── composite（P4 硬承诺：坏区外像素不变） ─────────────────────────────────


def test_composite_keeps_pixels_outside_boxes_bitexact():
    src = _natural()
    dst = np.full_like(src, 255)          # 重绘图：整张纯白（最坏情况）
    boxes = [{"box": (64, 128, 64, 64)}]
    out = _decode(ir.composite(src, dst, boxes, pad=0))
    h = out.shape[0]
    inside = np.zeros((h, out.shape[1]), dtype=bool)
    inside[128:192, 64:128] = True
    # 坏区内 = 纯白（来自重绘图）
    assert np.all(out[128:192, 64:128] == 255)
    # 坏区外 = 与原图逐字节相同（不是"接近"）
    assert np.array_equal(out[~inside], src[~inside])
    # 反证：不做合成的"直接采用重绘图"会整张变白
    assert not np.array_equal(dst, src)


def test_composite_resizes_mismatched_inpaint_output():
    src = _natural(256, 256)
    dst = np.full((128, 128, 3), 200, dtype=np.uint8)   # 端点返回了不同分辨率
    boxes = [{"box": (64, 64, 64, 64)}]
    out = _decode(ir.composite(src, dst, boxes, pad=0))
    assert out.shape[:2] == (256, 256)                  # 已 resize 回原尺寸
    inside = np.zeros((256, 256), dtype=bool)
    inside[64:128, 64:128] = True
    assert np.array_equal(out[~inside], src[~inside])


def test_composite_raises_on_undecodable_input():
    with pytest.raises(ValueError):
        ir.composite(b"not an image", b"nope", [])


# ── repair_image 编排（走 inpaint 而非重抽） ────────────────────────────────


def test_no_repair_means_no_request_at_all():
    calls = []

    def _spy(**kw):
        calls.append(kw)
        return {"ok": True, "image_data_url": ""}

    res = ir.repair_image(_natural(), prompt="p", inpaint_fn=_spy)
    assert res["ok"] is True and res["repaired"] is False
    assert calls == []        # 无坏区 ⇒ 一次请求都不发（省钱）


def test_repair_uses_inpaint_and_keeps_other_pixels():
    """核心验收：坏区走 inpaint；结果只在坏区变化（原满意区域像素不变）。"""
    img = _natural()
    bad = _broken(img, (0, 0, 64, 64))
    calls = []

    def _fake_inpaint(**kw):
        calls.append(kw)
        assert kw["mask"].startswith("data:image/png;base64,")   # 蒙版已备好
        # 端点返回整张纯红（模拟"整图被洗"的最坏情况）
        red = np.zeros_like(img)
        red[:, :, 2] = 255
        return {"ok": True, "image_data_url": _url(red), "channel_id": "ch1"}

    res = ir.repair_image(bad, prompt="修左上角", inpaint_fn=_fake_inpaint)
    assert res["ok"] is True and res["repaired"] is True
    assert res["used"] == "inpaint"          # 走的是 inpaint，不是整张重抽
    assert len(calls) == 1
    out = _decode(res["image_data_url"])
    # 坏区（含 pad 外扩）确实被换成了重绘内容（红色 BGR: (0,0,255) → 红通道高）
    assert int(out[8:56, 8:56, 2].mean()) > 200
    # 坏区之外与原图逐字节一致 —— "原满意区域像素不变" 的硬承诺
    # 用**返回的坏区并集**（而非测试自拟假设）构造掩码，避免假设与实际检测不符
    box = np.zeros((img.shape[0], img.shape[1]), dtype=bool)
    for b in res["boxes"]:
        x, y, bw, bh = b["box"]
        pad = ir.DEFAULT_PAD
        box[max(0, y - pad):y + bh + pad, max(0, x - pad):x + bw + pad] = True
    assert box.any()
    assert np.array_equal(out[~box], bad[~box])
    assert res["before_score"] is not None and res["after_score"] is not None


def test_inpaint_failure_is_honest_not_faked():
    bad = _broken(_natural(), (0, 0, 64, 64))

    def _fail(**kw):
        return {"ok": False, "message": "渠道不支持 edits"}

    res = ir.repair_image(bad, prompt="p", inpaint_fn=_fail)
    assert res["ok"] is False
    assert "image_data_url" not in res        # 不伪造图
    assert "渠道不支持" in res["message"]


def test_inpaint_exception_is_contained():
    bad = _broken(_natural(), (0, 0, 64, 64))

    def _boom(**kw):
        raise RuntimeError("网络炸了")

    res = ir.repair_image(bad, prompt="p", inpaint_fn=_boom)
    assert res["ok"] is False
    assert "网络炸了" in res["message"]
