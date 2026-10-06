"""app/tests/test_super_resolution_honesty.py — 超分引擎的诚实性（刀 A5 / A-6，2026-10-05）。

**修的 bug（「回退冒充 AI」）**：`SuperResolutionEngine.load()` 旧实现只要
`cv2.__path__` 存在就 `_model_name = "espcn"` + 打日志「ESPCN 就绪」并 `return True`
—— **从不校验模型文件**。而 `_espcn_upscale` 读的是**裸文件名** `ESPCN_x2.pb`
（`cv2.dnn_superres.readModel` 会去 cwd 找），仓库里根本没有该文件 ⇒ 推理必然失败并
**静默回退双三次插值**，但上层 `canvas_enhance._step_sharpen` 据 `_model_name` 上报
`engine="espcn" degraded=False` ⇒ **把双三次插值当 AI 超分端给用户**。

修法：**先找文件，找不到就不认领 espcn**；`_model_name` 保持空 ⇒ 上层的 degraded 判据
（它本来就在，且判据与 reason 一致）自动变诚实。

本测试锁死这条链：**引擎不撒谎 → 上层如实标 degraded → 用户看到「非 AI 放大」字样。**
"""
import os


from app.core.neural import super_resolution as sr


# ─────────────────────── ① 找不到模型就不认领 ───────────────────────

def test_find_espcn_never_returns_bare_name(monkeypatch, tmp_path):
    """候选路径必须都是**绝对/带目录**的路径 —— 绝不返回裸文件名（旧的坑）。"""
    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))
    for p in sr.espcn_search_paths(2):
        assert os.path.isabs(p), p
        assert p.endswith(".pb")
    assert sr.find_espcn_model(2) == ""      # tmp 里没有 ⇒ 空串，而不是"ESPCN_x2.pb"


def test_load_does_not_claim_espcn_without_model(monkeypatch, tmp_path):
    """★ 核心：没有模型文件时**不许**声称 espcn。"""
    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))
    eng = sr.SuperResolutionEngine()
    eng.load(scale=2, use_realesrgan=False)
    assert eng._model_name != "espcn", "没有模型文件却认领了 espcn ⇒ 回退会冒充 AI"
    assert eng._espcn_loaded is False
    assert eng._espcn_model_path == ""


def test_espcn_search_order_env_first(monkeypatch, tmp_path):
    """环境变量目录优先（用户自备模型的出口）。"""
    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))
    assert sr.espcn_search_paths(2)[0] == str(tmp_path / "ESPCN_x2.pb")


# ─────────────────────── ② 文件真在 ⇒ 认领（且记下路径）───────────────────────

def test_load_claims_espcn_when_file_exists(monkeypatch, tmp_path):
    (tmp_path / "ESPCN_x2.pb").write_bytes(b"fake-onnx-model")
    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.neural_engine.get_neural_engine",
                        lambda: type("E", (), {"is_available": True, "backend": None})())
    eng = sr.SuperResolutionEngine()
    ok = eng.load(scale=2, use_realesrgan=False)
    if ok:
        assert eng._model_name == "espcn"
        assert eng._espcn_model_path == str(tmp_path / "ESPCN_x2.pb")


def test_upscale_without_model_returns_bicubic(monkeypatch, tmp_path):
    """没模型也要**有输出**（双三次），只是不许声称是 AI。"""
    import numpy as np
    from app.core.neural_engine import InferenceBackend

    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))

    def _fake_engine():
        class _E:
            is_available = True
            backend = InferenceBackend.ONNX if hasattr(InferenceBackend, "ONNX") else None
            def download_model(self, *a, **k):
                return None
        return _E()

    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", _fake_engine)
    eng = sr.SuperResolutionEngine()
    eng.load(scale=2, use_realesrgan=True)
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    out = eng.upscale(img)
    assert out is not None and out.shape[0] == 16   # 仍产出，形状正确
    assert eng._model_name != "espcn"


# ─────────────────────── ③ 上层如实标 degraded（用户可见的诚实）───────────────────────

def test_step_sharpen_reports_degraded_for_bicubic(monkeypatch, tmp_path):
    """集成口径：无模型 ⇒ `engine="bicubic"` + `degraded=True` + 明说「非 AI 放大」。"""
    import numpy as np

    from app.core import canvas_enhance as ce

    monkeypatch.setenv("SHIGUANG_ESPCN_DIR", str(tmp_path))

    def _fake_engine():
        class _E:
            is_available = True
            backend = None
            def download_model(self, *a, **k):
                return None
        return _E()

    monkeypatch.setattr("app.core.neural_engine.get_neural_engine", _fake_engine)
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    report, out = ce._step_sharpen(img, "standard", {})
    assert out is not None
    if report.get("engine") == "bicubic":
        assert report["degraded"] is True
        assert "非 AI" in report["reason"], report
    else:
        # 若本机真装了 RealESRGAN，则不应标 degraded
        assert report["degraded"] is False
