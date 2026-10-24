# -*- coding: utf-8 -*-
"""V4.39.9 基础调色 LUT 化 — 像素级平价 + 性能基准

方案：测试内自带「旧浮点链」参照实现（改动前的原始数学，逐行镜像），
与 preview_manager 新 LUT 实现在同一随机帧上对比：
  - 点操作链（亮度/对比度/曝光/gamma/高光/阴影/色温）：max|Δ| ≤ 2 LSB
    （LUT 中间量化的固有上限，视觉不可区分）
  - 锐化（整帧单次 filter2D 替代逐通道循环）：必须**逐位一致**
  - 无特效时输出必须与输入完全一致（恒等）
  - 1080p 基准：新实现必须快于旧实现（方向性断言，防抖动不设硬倍率）

已知差异（有意为之，不计入偏差）：
  * 旧链在饱和度等操作产生**负值中间值**后，gamma 幂运算得 NaN，
    astype(uint8) 落 0 —— 是潜在的生产 bug（负值像素变黑）。
    LUT 链在入口处 clip，输出有定义的 0 值。对照时对旧链 NaN 像素打掩码。
  * color_params 会被 _normalize_effects 拍平到顶层，旧 CPU 路径的
    `cp.get('temperature')` 实际读不到（全 app 无第二处读取，属未接线死参数）。
    LUT-C 忠实保留该路径的原（死）行为；色温数学经绕过归一化单测验证。
"""
from __future__ import annotations

import time

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.core.preview_manager import (
    EffectsWorkerThread,
    PreviewManager,
    _pointwise_lut,
    _vignette_mask,
)

RNG = np.random.default_rng(42)


def _frame(h=64, w=96):
    return RNG.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _normalize(effects: dict) -> dict:
    """与 PreviewManager._normalize_effects 同款拍平（便于参照）。"""
    out = {}
    for k, v in effects.items():
        if k == "color_params" and isinstance(v, dict):
            out.update(v)
        else:
            out[k] = v
    return out


# ── 旧实现参照（改动前数学，逐行镜像；仅保留被 LUT 化的区段） ──


def _old_apply_effects_stages(frame: np.ndarray, effects: dict):
    """EffectsWorkerThread._apply_effects 的旧浮点链（亮度→对比度→饱和→曝光
    →gamma→高光→阴影→锐化）。返回 (final_float32, gamma阶段输出)，
    供 NaN 掩码与「128 阈值间断带」掩码使用。"""
    result = frame.astype(np.float32)
    brightness = effects.get("brightness", 0)
    if brightness != 0:
        result = result + brightness
    contrast = effects.get("contrast", 1.0)
    if contrast != 1.0:
        mean = result.mean()
        result = (result - mean) * contrast + mean
    saturation = effects.get("saturation", 1.0)
    if saturation != 1.0 and result.shape[2] >= 3:
        gray = result[:, :, :3].mean(axis=2, keepdims=True)
        result[:, :, :3] = gray + (result[:, :, :3] - gray) * saturation
    exposure = effects.get("exposure", 0)
    if exposure != 0:
        result = result * (2.0 ** exposure)
    gamma = effects.get("gamma", 1.0)
    if gamma != 1.0:
        with np.errstate(invalid="ignore"):
            result = 255.0 * ((result / 255.0) ** (1.0 / gamma))
    gamma_out = result.copy()
    highlights = effects.get("highlights", 0)
    if highlights != 0 and result.shape[2] >= 3:
        mask = result[:, :, :3] > 128
        result[:, :, :3][mask] = result[:, :, :3][mask] + highlights
    shadows = effects.get("shadows", 0)
    if shadows != 0 and result.shape[2] >= 3:
        mask = result[:, :, :3] <= 128
        result[:, :, :3][mask] = result[:, :, :3][mask] + shadows
    sharpen = effects.get("sharpen", 0)
    if sharpen != 0:
        kernel = np.array(
            [[-1, -1, -1], [-1, 9 + sharpen, -1], [-1, -1, -1]], dtype=np.float32
        ) / (1.0 + abs(sharpen) * 0.1)
        for c in range(min(3, result.shape[2])):
            result[:, :, c] = cv2.filter2D(result[:, :, c].astype(np.uint8), -1, kernel)
    return result, gamma_out


def _old_apply_effects_float(frame: np.ndarray, effects: dict) -> np.ndarray:
    return _old_apply_effects_stages(frame, effects)[0]


def _old_apply_effects(frame: np.ndarray, effects: dict) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.clip(_old_apply_effects_float(frame, effects), 0, 255).astype(np.uint8)


def _old_sync_grading_float(frame: np.ndarray, effects: dict) -> np.ndarray:
    """PreviewManager._apply_effects_sync 的旧点操作链（先经归一化拍平，
    含亮度换算规则、gamma 前先 clip）。返回 float32 以便检测 NaN。"""
    effects = _normalize(effects)
    result = frame.astype(np.float32)
    brightness = effects.get("brightness", 0)
    if brightness != 0:
        b = float(brightness)
        if abs(b) > 1.5:
            b = b / 100.0 * 80.0
        else:
            b = b * 80.0
        result = result + b
    contrast = effects.get("contrast", 1.0)
    if contrast != 1.0:
        mean = result.mean()
        result = (result - mean) * float(contrast) + mean
    saturation = effects.get("saturation", 1.0)
    if saturation != 1.0 and result.shape[2] >= 3:
        gray = result[:, :, :3].mean(axis=2, keepdims=True)
        result[:, :, :3] = gray + (result[:, :, :3] - gray) * float(saturation)
    exposure = effects.get("exposure", 0)
    if exposure != 0:
        result = result * (2.0 ** exposure)
    gamma = effects.get("gamma", 1.0)
    if gamma != 1.0:
        with np.errstate(invalid="ignore"):
            result = 255.0 * ((np.clip(result, 0, 255) / 255.0) ** (1.0 / float(gamma)))
    return result


# ── EffectsWorkerThread._apply_effects 平价 ──


def test_worker_lut_point_ops_parity():
    worker = EffectsWorkerThread()
    frame = _frame()
    fx = {
        "brightness": 12, "contrast": 1.22, "saturation": 1.31,
        "exposure": 0.4, "gamma": 1.15, "highlights": 14, "shadows": -9,
    }
    new = worker._apply_effects(frame.copy(), fx)
    old_f, gamma_out = _old_apply_effects_stages(frame.copy(), fx)
    with np.errstate(invalid="ignore"):
        old = np.clip(old_f, 0, 255).astype(np.uint8)
    diff = np.abs(new.astype(np.int16) - old.astype(np.int16))
    # 掩码①：旧链 NaN 像素（负值中间值 → gamma NaN → 落 0 垃圾，LUT 链修为有定义值）
    nan_mask = ~np.isfinite(gamma_out)
    # 掩码②：高光/阴影 128 阈值间断带 —— 该判定本身在旧链就是不连续的
    # （输入差 0.1 输出跳 |hl|+|sh|），LUT 入口 ±0.5 量化在带内可翻转分支，属固有
    band = np.abs(gamma_out - 128) <= 1.5
    ok = ~nan_mask & ~band
    assert diff[ok].max() <= 2, (
        f"LUT 链与旧浮点链偏差超阈: max={diff[ok].max()}")
    print(f"\n旧链 NaN 垃圾像素 {int(nan_mask.sum())} 个（LUT 链已修复）；"
          f"间断带像素 {int(band.sum())} 个（{float(band.mean())*100:.2f}%，分支翻转属固有）")


def test_worker_sharpen_bit_exact():
    worker = EffectsWorkerThread()
    frame = _frame()
    fx = {"sharpen": 2.0}
    new = worker._apply_effects(frame.copy(), fx)
    old = _old_apply_effects(frame.copy(), fx)
    assert np.array_equal(new, old), "整帧 filter2D 必须与逐通道循环逐位一致"


def test_worker_identity_when_no_effects():
    worker = EffectsWorkerThread()
    frame = _frame()
    out = worker._apply_effects(frame.copy(), {})
    assert np.array_equal(out, frame)


def test_worker_negative_and_combo_params_parity():
    """负值/组合参数（对比度<1、负曝光、阴影提亮、高光压暗）也须平。"""
    worker = EffectsWorkerThread()
    frame = _frame()
    fx = {
        "brightness": -18, "contrast": 0.85, "exposure": -0.6,
        "gamma": 0.9, "highlights": -25, "shadows": 20,
    }
    new = worker._apply_effects(frame.copy(), fx)
    old_f = _old_apply_effects_float(frame.copy(), fx)
    nan_mask = ~np.isfinite(old_f)
    with np.errstate(invalid="ignore"):
        old = np.clip(old_f, 0, 255).astype(np.uint8)
    diff = np.abs(new.astype(np.int16) - old.astype(np.int16))
    assert diff[~nan_mask].max() <= 2, (
        f"负值组合偏差超阈: max={diff[~nan_mask].max()}")


def test_worker_saturation_overdrive_no_nan_garbage():
    """饱和度过激（中间值出负）时：旧链出 NaN→0 垃圾，LUT 链必须有定义。

    该用例记录 LUT 化顺带修复的潜在生产 bug：负值像素在旧链变黑。
    """
    worker = EffectsWorkerThread()
    # 构造必然产生负值的帧：高对比通道差异 + 饱和度 2.0
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    frame[:, :, 0] = 255  # 纯红
    fx = {"saturation": 2.0, "gamma": 1.2}
    new = worker._apply_effects(frame.copy(), fx)
    old_f = _old_apply_effects_float(frame.copy(), fx)
    assert (~np.isfinite(old_f)).any(), "前提：旧链在该输入下确实产生 NaN"
    # LUT 链输出必须是有限合法值，且负值通道被 clip 到 0（而非旧链的 NaN 垃圾）
    assert np.isfinite(new.astype(np.float32)).all()
    assert (new[:, :, 1] == 0).all() and (new[:, :, 2] == 0).all()


# ── PreviewManager._apply_effects_sync 平价 ──


def test_sync_lut_point_ops_parity():
    pm = PreviewManager()
    frame = _frame()
    fx = {
        "brightness": 0.35, "contrast": 1.18, "saturation": 0.82,
        "exposure": 0.5, "gamma": 0.92,
    }
    new = pm._apply_effects_sync(frame.copy(), fx)
    old_f = _old_sync_grading_float(frame.copy(), fx)
    nan_mask = ~np.isfinite(old_f)
    with np.errstate(invalid="ignore"):
        old = np.clip(old_f, 0, 255).astype(np.uint8)
    diff = np.abs(new.astype(np.int16) - old.astype(np.int16))
    assert diff[~nan_mask].max() <= 2, (
        f"sync LUT 链偏差超阈: max={diff[~nan_mask].max()}")


def test_sync_brightness_scaling_rule_parity():
    """亮度换算规则分两支（|b|>1.5 与 <=1.5），都要平。"""
    pm = PreviewManager()
    frame = _frame()
    for bval in (0.8, 30.0):  # 两支各一
        fx = {"brightness": bval}
        new = pm._apply_effects_sync(frame.copy(), fx)
        old_f = _old_sync_grading_float(frame.copy(), fx)
        with np.errstate(invalid="ignore"):
            old = np.clip(old_f, 0, 255).astype(np.uint8)
        diff = np.abs(new.astype(np.int16) - old.astype(np.int16))
        assert diff.max() <= 2, f"亮度 {bval} 偏差超阈: max={diff.max()}"


def test_sync_temperature_lut_math(monkeypatch):
    """色温 LUT-C 的数学对照（绕过归一化拍平，直接驱动 cp 路径）。

    注：生产上 color_params 被拍平后 `cp.get('temperature')` 读不到
    （全 app 无第二处读取，未接线死参数），本用例仅验证 LUT-C 数学
    与原切片加法一致，不代表该参数已在产品链路生效。
    """
    pm = PreviewManager()
    monkeypatch.setattr(PreviewManager, "_normalize_effects", lambda self, e: e or {})
    frame = _frame()
    for t in (-60, 0, 75):
        fx = {"color_params": {"temperature": t}}
        new = pm._apply_effects_sync(frame.copy(), fx)
        # 旧数学：R+shift / B-shift（float，末端 clip）
        old = frame.astype(np.float32)
        if t:
            shift = float(t) / 100.0 * 40.0
            old[:, :, 0] = old[:, :, 0] + shift
            old[:, :, 2] = old[:, :, 2] - shift
        old = np.clip(old, 0, 255).astype(np.uint8)
        diff = np.abs(new.astype(np.int16) - old.astype(np.int16))
        assert diff.max() <= 2, f"色温 {t} LUT 数学偏差超阈: max={diff.max()}"


def test_sync_sharpen_bit_exact():
    pm = PreviewManager()
    frame = _frame()
    fx = {"sharpen": 1.5}
    new = pm._apply_effects_sync(frame.copy(), fx)
    # 旧逐通道参照（kernel 与本路径 float(sharpen) 版一致）
    result = frame.astype(np.float32)
    kernel = np.array(
        [[-1, -1, -1], [-1, 9 + 1.5, -1], [-1, -1, -1]], dtype=np.float32
    ) / (1.0 + abs(float(1.5)) * 0.1)
    for c in range(3):
        result[:, :, c] = cv2.filter2D(result[:, :, c].astype(np.uint8), -1, kernel)
    old = np.clip(result, 0, 255).astype(np.uint8)
    assert np.array_equal(new, old), "sync 整帧 filter2D 必须与逐通道循环逐位一致"


def test_sync_identity_when_no_effects():
    pm = PreviewManager()
    frame = _frame()
    out = pm._apply_effects_sync(frame.copy(), {})
    assert np.array_equal(out, frame)


# ── LUT 工具函数 ──


def test_pointwise_lut_identity():
    table = _pointwise_lut([])
    assert np.array_equal(table, np.arange(256, dtype=np.uint8))


def test_pointwise_lut_no_intermediate_clipping():
    """中间步骤不截断：x*2 再 /2 应近似恒等（而非 clip 到 255）。"""
    table = _pointwise_lut([lambda x: x * 2.0, lambda x: x / 2.0])
    assert np.array_equal(table, np.arange(256, dtype=np.uint8))


def test_vignette_mask_cache_and_values():
    h, w, v = 48, 64, 0.5
    m1 = _vignette_mask(h, w, v)
    m2 = _vignette_mask(h, w, v)
    assert m1 is m2, "同 key 必须命中缓存（同一对象）"
    # 与旧公式逐位一致
    yy, xx = np.ogrid[:h, :w]
    cx, cy = w / 2, h / 2
    dist = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    old = np.clip(1.0 - dist * v, 0.2, 1.0)
    assert np.array_equal(m1, old)


# ── 1080p 性能基准（方向性断言） ──


def test_1080p_lut_faster_than_float_chain():
    worker = EffectsWorkerThread()
    frame = _frame(1080, 1920)
    fx = {
        "brightness": 10, "contrast": 1.2, "saturation": 1.25,
        "exposure": 0.3, "gamma": 1.1, "highlights": 12, "shadows": -8,
        "sharpen": 1.0, "vignette": 0.35,
    }
    # 预热（建表/缓存路径）
    worker._apply_effects(frame.copy(), fx)
    _old_apply_effects(frame.copy(), fx)

    n = 5
    t0 = time.perf_counter()
    for _ in range(n):
        worker._apply_effects(frame.copy(), fx)
    t_new = (time.perf_counter() - t0) / n

    # 旧参照补 vignette（与新版同口径对比）
    def old_full(f):
        r = _old_apply_effects(f, fx).astype(np.float32)
        h, w = r.shape[:2]
        yy, xx = np.ogrid[:h, :w]
        cx, cy = w / 2, h / 2
        dist = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
        mask = np.clip(1.0 - dist * fx["vignette"], 0.2, 1.0)
        return np.clip(r * mask[:, :, np.newaxis], 0, 255).astype(np.uint8)

    old_full(frame.copy())
    t0 = time.perf_counter()
    for _ in range(n):
        old_full(frame.copy())
    t_old = (time.perf_counter() - t0) / n

    print(f"\n1080p 单帧调色：新 LUT {t_new*1000:.1f}ms vs 旧浮点链 {t_old*1000:.1f}ms"
          f"（{t_old/max(t_new, 1e-9):.2f}x）")
    assert t_new < t_old, "LUT 化后单帧耗时必须低于旧浮点链"
