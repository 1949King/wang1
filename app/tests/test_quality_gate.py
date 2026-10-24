# -*- coding: utf-8 -*-
"""质量总闸：默认/归一化/持久化/显式优先。"""
from __future__ import annotations

import json

import app.core.ai.quality_gate as QG


def _reset(tmp_path, monkeypatch):
    p = tmp_path / "qg.json"
    monkeypatch.setenv("SHIGUANG_QUALITY_GATE", str(p))
    monkeypatch.setattr(QG, "_GATE", None)
    return p


def test_default_is_standard(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    assert QG.get_gate().get() == "standard"
    assert QG.get_quality("") == "standard"


def test_set_persists_and_reloads(tmp_path, monkeypatch):
    p = _reset(tmp_path, monkeypatch)
    assert QG.get_gate().set("cinema") is True
    assert json.loads(p.read_text(encoding="utf-8"))["quality"] == "cinema"
    monkeypatch.setattr(QG, "_GATE", None)
    assert QG.get_gate().get() == "cinema"


def test_invalid_rejected_and_explicit_wins(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    assert QG.get_gate().set("ultra") is False
    assert QG.get_gate().get() == "standard"
    # 显式合法值优先于总闸
    assert QG.get_quality("draft") == "draft"
    # 显式非法值 ⇒ 回落总闸
    assert QG.get_quality("nonsense") == "standard"
