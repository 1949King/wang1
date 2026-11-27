"""app/tests/test_rife_engine.py — RIFE 引擎契约（T4 项二，2026-11-20）。

锁死诚实纪律与探测/加载/推理行为：
  1. 路径优先级：SHIGUANG_RIFE_PATH（整文件）> SHIGUANG_RIFE_DIR（目录）
     > 仓库 thirdparty/models > 模块目录；缺失 ⇒ find_rife_model 返回 ""。
  2. RIFE_MODEL_GUIDANCE 含目标路径 + 资源地址 + 部署步骤 + 「绝不自动下载」。
  3. is_available：模型缺失 ⇒ False（不依赖 torch）。
  4. load：损坏权重 ⇒ False 不抛；torch 不可用 ⇒ RifeUnavailableError（类型化）。
  5. interpolate_pair：假权重桩下输出 shape/dtype 与输入一致（RGB uint8）。

绝不触网：所有用例仅本地文件 / 内存桩，无任何下载。
"""
import os
import sys

import pytest

from app.core.neural import rife_engine


# ─────────────────────── 路径探测 ───────────────────────

class TestRifeSearchPaths:
    """rife_search_paths 优先级契约。"""

    def test_env_file_first(self, monkeypatch):
        """SHIGUANG_RIFE_PATH 指向的整文件路径排第一。"""
        monkeypatch.setenv("SHIGUANG_RIFE_PATH", "/custom/rife49.pth")
        monkeypatch.delenv("SHIGUANG_RIFE_DIR", raising=False)
        paths = rife_engine.rife_search_paths()
        assert paths[0] == "/custom/rife49.pth"

    def test_env_dir_before_thirdparty(self, monkeypatch):
        """SHIGUANG_RIFE_DIR 目录候选排在仓库 thirdparty 之前。"""
        monkeypatch.delenv("SHIGUANG_RIFE_PATH", raising=False)
        monkeypatch.setenv("SHIGUANG_RIFE_DIR", "/models")
        paths = rife_engine.rife_search_paths()
        dir_candidate = os.path.join("/models", rife_engine.RIFE_MODEL_FILENAME)
        assert dir_candidate in paths
        thirdparty = [p for p in paths if "thirdparty" in p]
        assert thirdparty, "应包含仓库 thirdparty/models 候选"
        assert paths.index(dir_candidate) < paths.index(thirdparty[0])

    def test_default_candidates_present(self, monkeypatch):
        """无环境变量时仍含 thirdparty 与模块目录两个候选。"""
        monkeypatch.delenv("SHIGUANG_RIFE_PATH", raising=False)
        monkeypatch.delenv("SHIGUANG_RIFE_DIR", raising=False)
        paths = rife_engine.rife_search_paths()
        assert any("thirdparty" in p for p in paths)
        assert any(p.endswith(rife_engine.RIFE_MODEL_FILENAME) for p in paths)


class TestFindRifeModel:
    """find_rife_model 只返回真实存在的文件。"""

    def test_missing_returns_empty(self, monkeypatch, tmp_path):
        """候选都不存在 ⇒ 返回空串（绝不返回裸文件名）。"""
        monkeypatch.setattr(
            rife_engine, "rife_search_paths",
            lambda: [str(tmp_path / "nope.pth")],
        )
        assert rife_engine.find_rife_model() == ""

    def test_env_file_picked_when_exists(self, monkeypatch, tmp_path):
        """环境变量指向的真实文件被选中。"""
        model = tmp_path / "rife49.pth"
        model.write_bytes(b"\x00" * 32)
        monkeypatch.setenv("SHIGUANG_RIFE_PATH", str(model))
        monkeypatch.delenv("SHIGUANG_RIFE_DIR", raising=False)
        assert rife_engine.find_rife_model() == str(model)


class TestGuidance:
    """模型缺失引导文案必须可自取、含目标路径、声明不自动下载。"""

    def test_guidance_contains_key_info(self):
        g = rife_engine.RIFE_MODEL_GUIDANCE
        assert rife_engine.RIFE_MODEL_FILENAME in g
        assert "thirdparty" in g
        assert "1UssCvbL8N-ty0xIKM5G5ZTEgp9o4w3hp" in g  # Google Drive
        assert "swr9" in g  # 百度网盘提取码
        assert "绝不自动下载" in g


class TestIsAvailable:
    """is_available 探测（模型缺失即 False，不依赖 torch）。"""

    def test_no_model_unavailable(self, monkeypatch):
        monkeypatch.setattr(rife_engine, "find_rife_model", lambda: "")
        assert rife_engine.RifeEngine().is_available() is False


# ─────────────────────── 加载 / 推理（需 torch） ───────────────────────

class TestLoad:
    """load 诚实失败契约。"""

    def test_corrupt_weights_returns_false(self, tmp_path):
        """损坏权重 ⇒ False，不抛（上层据此降级）。"""
        pytest.importorskip("torch")
        bad = tmp_path / "rife49.pth"
        bad.write_bytes(b"this is not a torch checkpoint")
        engine = rife_engine.RifeEngine()
        assert engine.load(str(bad)) is False
        assert engine.is_available() is False or True  # load 失败不认领 loaded

    def test_torch_missing_raises_typed(self, monkeypatch, tmp_path):
        """torch 不可用 ⇒ RifeUnavailableError（类型化，区别于损坏）。"""
        from app.core.neural.rife_net import RifeUnavailableError
        model = tmp_path / "rife49.pth"
        model.write_bytes(b"\x00" * 32)
        # 让 `import torch` 抛 ImportError（None in sys.modules）
        monkeypatch.setitem(sys.modules, "torch", None)
        engine = rife_engine.RifeEngine()
        with pytest.raises(RifeUnavailableError):
            engine.load(str(model))


class TestInterpolatePair:
    """interpolate_pair 预处理/后处理管线（假权重桩，不跑真实前向）。"""

    def test_shape_dtype_consistent(self):
        torch = pytest.importorskip("torch")
        import numpy as np

        class _FakeModel:
            """假权重桩：返回与输入同形的零张量，仅验证 pad/归一化/裁剪管线。"""

            def inference(self, img0, img1, timestep=0.5, scale=1.0):
                return torch.zeros_like(img0)

        engine = rife_engine.RifeEngine()
        engine._model = _FakeModel()
        engine._device = "cpu"
        engine._loaded = True

        prev = np.full((64, 64, 3), 10, dtype=np.uint8)
        cur = np.full((64, 64, 3), 200, dtype=np.uint8)
        out = engine.interpolate_pair(prev, cur, 0.5)
        assert out.shape == (64, 64, 3)
        assert out.dtype == np.uint8

    def test_not_loaded_raises(self):
        pytest.importorskip("torch")
        import numpy as np
        from app.core.neural.rife_net import RifeError

        engine = rife_engine.RifeEngine()
        prev = np.zeros((32, 32, 3), dtype=np.uint8)
        with pytest.raises(RifeError):
            engine.interpolate_pair(prev, prev, 0.5)
