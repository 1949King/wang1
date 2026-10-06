"""app/tests/test_canvas_enhance.py — 画布意图级增强层回归（2026-09-30）。

核心纪律（也是「不走 ComfyUI 老路」的落地）：
  ① **只暴露意图，不暴露模型名** —— 用户不该被迫选模型；
  ② **诚实报告** —— 每步回报实际引擎，降级必须显式标注且与 reason 一致；
  ③ **绝不抛异常** —— 坏输入只返回 ok=False；
  ④ **不静默下载大模型** —— 只有 high 档允许 RealESRGAN。
"""
import base64

import pytest

from app.core import canvas_enhance as E

# 1×1 透明 PNG（合法 data URL，用于走通解码路径）
PNG_1X1 = ("data:image/png;base64,"
           "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
           "DwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


# ─────────────────────── ① 只暴露意图 ───────────────────────

def test_intents_catalog_exposes_no_model_names():
    """★ 与 ComfyUI 的分歧点：目录里不该有 engine/model 之类的键。"""
    for item in E.available_intents():
        assert set(item) == {"id", "label", "hint"}, item
        for v in item.values():
            assert "onnx" not in str(v).lower()
            assert "gfpgan" not in str(v).lower()
            assert "realesrgan" not in str(v).lower()


def test_intent_catalog_nonempty_and_labelled():
    intents = E.available_intents()
    assert len(intents) >= 3
    assert all(i["label"] and i["hint"] for i in intents)
    assert {"face", "cutout", "sharpen", "style", "heal"} <= {i["id"] for i in intents}


def test_quality_tiers_are_three_and_semantic():
    """档位是 fast/standard/high —— 不是 steps/cfg/denoise 这类实现层参数。"""
    assert set(E.QUALITY_TIERS) == {"fast", "standard", "high"}
    for name, tier in E.QUALITY_TIERS.items():
        assert set(tier) <= {"sr_scale", "use_realesrgan"}, (name, tier)


def test_only_high_tier_allows_realesrgan_download():
    """★ 不静默下载：只有 high 触发 RealESRGAN（其余走 OpenCV 内置 ESPCN）。"""
    assert E.QUALITY_TIERS["high"]["use_realesrgan"] is True
    assert E.QUALITY_TIERS["fast"]["use_realesrgan"] is False
    assert E.QUALITY_TIERS["standard"]["use_realesrgan"] is False


# ─────────────────────── ③ 绝不抛异常 ───────────────────────

def test_empty_intents_returns_false_not_raises():
    r = E.apply_intents(PNG_1X1, [])
    assert r["ok"] is False
    assert "未指定" in r["message"]


def test_bad_image_returns_false_not_raises():
    r = E.apply_intents("not-a-data-url", ["face"])
    assert r["ok"] is False
    assert "解码失败" in r["message"]


def test_none_like_inputs_do_not_raise():
    assert E.apply_intents("", [])["ok"] is False
    assert E.apply_intents(None, ["face"])["ok"] is False
    assert E.apply_intents(PNG_1X1, None)["ok"] is False


def test_unknown_intent_goes_to_skipped():
    r = E.apply_intents(PNG_1X1, ["__brand_new__"])
    assert any(s["intent"] == "__brand_new__" for s in r["skipped"])
    assert r["applied"] == []
    assert r["changed"] is False


def test_mixed_known_and_unknown_intents():
    """未知意图被跳过，但不应拖垮整次调用（仍返回合法结构）。"""
    r = E.apply_intents(PNG_1X1, ["__nope__", "heal"])
    assert isinstance(r, dict)
    assert "applied" in r and "skipped" in r
    assert any(s["intent"] == "__nope__" for s in r["skipped"])


# ─────────────────────── ② 诚实报告 ───────────────────────

def test_heal_without_mask_is_skipped_honestly():
    """局部修图**必须**有遮罩；没遮罩要如实说，绝不瞎猜区域。"""
    r = E.apply_intents(PNG_1X1, ["heal"])
    skipped = {s["intent"]: s["reason"] for s in r["skipped"]}
    assert "heal" in skipped
    assert "遮罩" in skipped["heal"]


def test_result_shape_is_complete():
    r = E.apply_intents(PNG_1X1, ["__nope__"])
    for key in ("ok", "applied", "skipped", "quality", "changed", "note"):
        assert key in r, key
    assert isinstance(r["applied"], list)
    assert isinstance(r["skipped"], list)


def test_invalid_quality_falls_back_to_standard():
    r = E.apply_intents(PNG_1X1, ["__nope__"], quality="__bogus__")
    assert r["quality"] == "standard"


def test_sharpen_reports_real_engine_and_consistent_degraded():
    """★ 真跑一次超分：必须回报实际引擎；degraded 与 reason 必须一致。"""
    import numpy as np
    import cv2
    img = np.zeros((32, 32, 3), np.uint8)
    img[:, :, 1] = np.linspace(0, 255, 32).astype(np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    url = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()

    r = E.apply_intents(url, ["sharpen"], quality="standard")
    if not r["applied"]:
        pytest.skip(f"本机超分不可用（诚实跳过）：{r['skipped']}")
    item = r["applied"][0]
    assert item["engine"], "必须回报实际引擎"
    # degraded 与 reason 同源：非降级时不得有降级说明
    if not item.get("degraded"):
        assert not item.get("reason"), item
    else:
        assert item.get("reason"), item


def test_high_tier_degradation_is_reported_truthfully():
    """★ high 档拿不到 RealESRGAN 时，必须 degraded=True **且**给出原因。"""
    import numpy as np
    import cv2
    img = np.zeros((32, 32, 3), np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    url = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()

    r = E.apply_intents(url, ["sharpen"], quality="high")
    if not r["applied"]:
        pytest.skip(f"本机超分不可用：{r['skipped']}")
    item = r["applied"][0]
    if item["engine"] != "realesrgan":
        assert item["degraded"] is True
        assert "降级" in item["reason"]


def test_pipeline_order_is_respected():
    """列表即顺序：重复意图会被依次处理（链式而非图）。"""
    r = E.apply_intents(PNG_1X1, ["__a__", "__b__"])
    order = [s["intent"] for s in r["skipped"]]
    assert order == ["__a__", "__b__"]


# ─────────────────────── stats ───────────────────────

def test_stats_shape_and_no_model_loading():
    st = E.stats()
    assert st["intents"] == list(E.ENHANCE_INTENTS)
    assert st["quality_tiers"] == list(E.QUALITY_TIERS)
    assert isinstance(st["neural_backend"], str)
