# -*- coding: utf-8 -*-
"""app/tests/test_super_resolution_local_first.py — T2 超分本地优先（2026-11-20）。

用户红线：模型权重**绝不自动下载、不随包**，只给「自取 + guidance」。
旧 load() 走 eng.download_model(REALESRGAN_ONNX) 会静默从 HF 拉几百 MB，
且 onnx-community 仓已不存在（T0 许可核实）⇒ 本测试锁死新契约：
  ① AST：super_resolution 模块内零 download_model 调用；
  ② 权重在盘 ⇒ 本地文件优先，认领 realesrgan；
  ③ 权重缺失 ⇒ 诚实返 False + guidance（绝不自动下载）；
  ④ 加载失败 ⇒ 不认领（与 A-6「回退冒充 AI」同纪律）；
  ⑤ canvas_enhance hint 改自取文案（不再承诺「首次可能需下载」）。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

from app.core.neural import super_resolution as sr


def _fake_onnx_engine(load_ok: bool = True):
    """桩神经引擎：ONNX 后端可用；download_model 若被调用直接判失败（红线）。"""
    from app.core.neural_engine import InferenceBackend

    class _E:
        is_available = True
        backend = InferenceBackend.ONNX

        def download_model(self, *a, **k):
            raise AssertionError("红线：超分绝不自动下载权重")

        def load_onnx_model(self, path, name):
            return load_ok

    return _E()


# ─────────────────────── ① 结构性红线：零自动下载 ───────────────────────

def test_no_download_model_call_ast():
    """AST 断言：模块内不存在任何 download_model 调用（不靠自觉，靠结构）。"""
    tree = ast.parse(Path(sr.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                assert fn.attr != "download_model", "super_resolution 仍有自动下载调用"
            elif isinstance(fn, ast.Name):
                assert fn.id != "download_model", "super_resolution 仍有自动下载调用"


# ─────────────────────── ② 探测：env 优先 / 缺返空 ───────────────────────

def test_find_realesrgan_env_first_and_missing(monkeypatch, tmp_path):
    f = tmp_path / "realesrgan_x4plus.onnx"
    f.write_bytes(b"fake")
    monkeypatch.setenv("SHIGUANG_REALESRGAN_PATH", str(f))
    assert sr.find_realesrgan_onnx() == str(f)
    monkeypatch.setenv("SHIGUANG_REALESRGAN_PATH", str(tmp_path / "nope.onnx"))
    assert sr.find_realesrgan_onnx() == ""
    for p in sr.realesrgan_search_paths():
        assert os.path.isabs(p), p


# ─────────────────────── ③ 在盘 ⇒ 认领；缺失 ⇒ 诚实 False ───────────────────────

def test_load_claims_realesrgan_when_local_file_exists(monkeypatch, tmp_path):
    f = tmp_path / "realesrgan_x4plus.onnx"
    f.write_bytes(b"fake")
    monkeypatch.setenv("SHIGUANG_REALESRGAN_PATH", str(f))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", _fake_onnx_engine)
    eng = sr.SuperResolutionEngine()
    assert eng.load(scale=4, use_realesrgan=True) is True
    assert eng._model_name == "realesrgan"


def test_load_missing_returns_false_and_guidance(monkeypatch, tmp_path):
    monkeypatch.setenv("SHIGUANG_REALESRGAN_PATH", str(tmp_path / "nope.onnx"))
    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", _fake_onnx_engine)
    eng = sr.SuperResolutionEngine()
    assert eng.load(scale=2, use_realesrgan=True) is False
    assert eng._model_name == ""
    assert "绝不自动下载" in sr.REALESRGAN_GUIDANCE
    assert "realesrgan_x4plus.onnx" in sr.REALESRGAN_GUIDANCE
    assert "https://huggingface.co/qualcomm/Real-ESRGAN-x4plus" in sr.REALESRGAN_GUIDANCE


def test_load_failure_does_not_claim_realesrgan(monkeypatch, tmp_path):
    """权重在盘但加载失败 ⇒ 不认领 realesrgan（防双三次冒充 AI）。"""
    f = tmp_path / "realesrgan_x4plus.onnx"
    f.write_bytes(b"corrupt")
    monkeypatch.setenv("SHIGUANG_REALESRGAN_PATH", str(f))
    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine",
                        lambda: _fake_onnx_engine(load_ok=False))
    eng = sr.SuperResolutionEngine()
    assert eng.load(scale=2, use_realesrgan=True) is False
    assert eng._model_name != "realesrgan"


# ─────────────────────── ⑤ 用户可见文案：自取而非下载 ───────────────────────

def test_sharpen_hint_promises_self_fetch_not_download():
    from app.core import canvas_enhance as ce

    hint = ce.ENHANCE_INTENTS["sharpen"]["hint"]
    assert "自取" in hint
    assert "首次可能需下载" not in hint
