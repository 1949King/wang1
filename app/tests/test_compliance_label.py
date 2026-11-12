# -*- coding: utf-8 -*-
"""G1 · AI 生成标识：角标 + 元数据（2026-11-12）。"""
from __future__ import annotations

import json
import os

import pytest

import app.core.compliance_label as CL


def test_defaults_enabled_by_design():
    cfg = CL.load_config(path=os.path.join(os.getcwd(), "__no_such_cfg__.json"))
    assert cfg["enabled"] is True            # 合规项默认开启
    assert cfg["text"]
    assert cfg["position"] in ("top-left", "top-right", "bottom-left", "bottom-right")


def test_save_and_load_override(tmp_path):
    p = tmp_path / "c.json"
    CL.save_config({"text": "AI 合成", "position": "top-left", "metadata": {"record_no": "备-001"}}, str(p))
    cfg = CL.load_config(str(p))
    assert cfg["text"] == "AI 合成"
    assert cfg["position"] == "top-left"
    assert cfg["metadata"]["record_no"] == "备-001"
    assert cfg["metadata"]["ai_generated"] == "true"      # 默认元数据保留


def test_bad_config_falls_back(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    cfg = CL.load_config(str(p))
    assert cfg["enabled"] is True and cfg["text"]


def test_position_xy_corners():
    w, h, m = 1080, 1920, 0.03
    tw, th = 200, 40
    x, y = CL.position_xy(w, h, "top-left", m, tw, th)
    assert (x, y) == (int(1080 * 0.03), int(1080 * 0.03))
    x, y = CL.position_xy(w, h, "bottom-right", m, tw, th)
    assert x == w - tw - int(1080 * 0.03)
    assert y == h - th - int(1080 * 0.03)
    assert CL.position_xy(w, h, "garbage", m, tw, th) == CL.position_xy(w, h, "bottom-right", m, tw, th)


def test_metadata_args_contains_required_keys():
    args = CL.metadata_args({"text": "本片含 AI 生成内容", "metadata": {"comment": "c", "ai_generated": "true",
                                                                  "record_no": "R1", "credits": "张三"}})
    joined = " ".join(args)
    assert "ai_generated=true" in joined
    assert "record_no=R1" in joined
    assert "credits=张三" in joined
    assert args.count("-metadata") == 6


def test_build_overlay_png_size_matches_video():
    pytest.importorskip("PIL")
    out = CL.build_overlay_png("本片含 AI 生成内容", 640, 360, "bottom-right", 0.5, 0.03, 0.035)
    assert out and os.path.isfile(out)
    from PIL import Image

    with Image.open(out) as im:
        assert im.size == (640, 360)
        assert im.mode == "RGBA"
    os.remove(out)


def test_apply_returns_reason_when_disabled(tmp_path):
    v = tmp_path / "a.mp4"
    v.write_bytes(b"x" * 2048)
    res = CL.apply_ai_label_inplace(str(v), {"enabled": False})
    assert res["applied"] is False and "未启用" in res["reason"]


def test_apply_returns_reason_when_ffmpeg_missing(tmp_path, monkeypatch):
    v = tmp_path / "a.mp4"
    v.write_bytes(b"x" * 2048)
    monkeypatch.setattr(CL, "find_ffmpeg", lambda: "")
    res = CL.apply_ai_label_inplace(str(v), {"enabled": True})
    assert res["applied"] is False and "ffmpeg" in res["reason"]
