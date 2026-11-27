# -*- coding: utf-8 -*-
"""app/tests/test_inpainting_local_first.py — T3 LaMa 本地优先（2026-11-20）。

用户红线：模型权重**绝不自动下载、不随包**，只给「自取 + guidance」。
旧 inpainting.load() 走 eng.download_model(LAMA_ONNX) 会静默从 HF 拉权重，
且 onnx-community/lama_dilated 仓已不存在（T0 许可核实）⇒ 本测试锁死新契约：
  ① AST：inpainting 模块内零 download_model 调用；
  ② 权重在盘 ⇒ 本地文件优先，认领 lama_inpaint；
  ③ 权重缺失 ⇒ 诚实返 False + guidance（绝不自动下载）；
  ④ 加载失败 ⇒ 不认领（与 A-6「回退冒充 AI」同纪律）；
  ⑤ tool_weights 的 lama 条目 probe/guidance 收拢到 inpainting 单一真源。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

from app.core.neural import inpainting as ip


def _fake_onnx_engine(load_ok: bool = True):
    """桩神经引擎：ONNX 后端可用；download_model 若被调用直接判失败（红线）。"""
    from app.core.neural_engine import InferenceBackend

    class _E:
        is_available = True
        backend = InferenceBackend.ONNX

        def download_model(self, *a, **k):
            raise AssertionError("红线：LaMa 绝不自动下载权重")

        def load_onnx_model(self, path, name):
            return load_ok

    return _E()


# ─────────────────────── ① 结构性红线：零自动下载 ───────────────────────

def test_no_download_model_call_ast():
    """AST 断言：模块内不存在任何 download_model 调用（不靠自觉，靠结构）。"""
    tree = ast.parse(Path(ip.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                assert fn.attr != "download_model", "inpainting 仍有自动下载调用"
            elif isinstance(fn, ast.Name):
                assert fn.id != "download_model", "inpainting 仍有自动下载调用"


# ─────────────────────── ② 探测：env 优先 / 缺返空 ───────────────────────

def test_find_lama_env_first_and_missing(monkeypatch, tmp_path):
    f = tmp_path / "lama_dilated.onnx"
    f.write_bytes(b"fake")
    monkeypatch.setenv("SHIGUANG_LAMA_PATH", str(f))
    assert ip.find_lama_onnx() == str(f)
    monkeypatch.setenv("SHIGUANG_LAMA_PATH", str(tmp_path / "nope.onnx"))
    assert ip.find_lama_onnx() == ""
    for p in ip.lama_search_paths():
        assert os.path.isabs(p), p


# ─────────────────────── ③ 在盘 ⇒ 认领；缺失 ⇒ 诚实 False ───────────────────────

def test_load_claims_lama_when_local_file_exists(monkeypatch, tmp_path):
    f = tmp_path / "lama_dilated.onnx"
    f.write_bytes(b"fake")
    monkeypatch.setenv("SHIGUANG_LAMA_PATH", str(f))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", _fake_onnx_engine)
    eng = ip.InpaintingEngine()
    assert eng.load() is True
    assert eng._loaded is True


def test_load_missing_returns_false_and_guidance(monkeypatch, tmp_path):
    monkeypatch.setenv("SHIGUANG_LAMA_PATH", str(tmp_path / "nope.onnx"))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", _fake_onnx_engine)
    eng = ip.InpaintingEngine()
    assert eng.load() is False
    assert eng._loaded is False
    assert "绝不自动下载" in ip.LAMA_GUIDANCE
    assert "lama_dilated.onnx" in ip.LAMA_GUIDANCE
    assert "https://huggingface.co/Carve/LaMa-ONNX" in ip.LAMA_GUIDANCE


def test_load_failure_does_not_claim_lama(monkeypatch, tmp_path):
    """权重在盘但加载失败 ⇒ 不认领（防 Telea 冒充 AI）。"""
    f = tmp_path / "lama_dilated.onnx"
    f.write_bytes(b"corrupt")
    monkeypatch.setenv("SHIGUANG_LAMA_PATH", str(f))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine",
                        lambda: _fake_onnx_engine(load_ok=False))
    eng = ip.InpaintingEngine()
    assert eng.load() is False
    assert eng._loaded is False


# ─────────────────────── ⑤ 单一真源：tool_weights 收拢到 inpainting ───────────────────────

def test_tool_weights_lama_uses_inpainting_single_source():
    from app.core.neural import tool_weights as tw

    spec = tw.TOOL_WEIGHTS["lama_dilated"]
    assert spec["probe"] is ip.find_lama_onnx
    assert spec["guidance"] is ip.LAMA_GUIDANCE
