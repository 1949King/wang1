"""app/tests/test_diffsynth_image.py — DiffSynth 图像引擎（主选通道）回归（2026-10-02）。

锁定的纪律：
  ① **不自动下载** —— generate() 对未下载模型只报错、不拉取；
  ② **诚实失败** —— 未知 id / 缺 prompt / 缺模型都给具体原因，不返回占位图；
  ③ **探测零重导入** —— is_available / unavailable_reason 只做 find_spec，
     绝不真 import diffsynth_engine（2026-10-01/10-02 两次组合场景硬崩血泪）；
  ④ **moviepy shim 前置** —— load() 必须走 diffsynth_compat.import_diffsynth_engine()；
  ⑤ **下载走 ModelScope**（diffsynth 模型原生渠道），落盘项目缓存目录。

注：本测试**不真 import diffsynth_engine、不下载权重**。
"""
import inspect
import pathlib

from app.core.neural import diffsynth_image as D


# ─────────────────────── 注册表 ───────────────────────

def test_registry_nonempty_and_complete():
    models = D.available_models()
    assert len(models) >= 1
    for m in models:
        for k in ("id", "label", "params", "modes", "download_gb",
                      "vram_gb", "ram_gb", "native_size", "note", "license"):
            assert k in m, (m.get("id"), k)
        assert m["modes"]
        assert set(m["modes"]) <= {"t2i", "i2i"}


def test_sd15_is_first_landing_with_measured_size():
    """★ 首个落地 = SD1.5：体积是 ModelScope API 实测（3.97GB 一体化），
    且体积必须适合本机（< 8GB，区别于 Wan 视频的 16GB+10.58GB T5 硬墙）。"""
    spec = D.IMAGE_MODELS["sd15-t2i"]
    assert spec["size_gb"] == 3.97, "体积漂移（应锁定 ModelScope 实测值）"
    assert spec["size_gb"] < 8.0
    assert spec["ms_file"].endswith(".safetensors")
    # 无巨型 T5 是它能落地的根本原因（对比 Wan 的 umt5-xxl 10.58GB）—— 注册表必须留痕
    assert "CLIP" in spec["note"] or "T5" in spec["note"]


def test_sd15_native_size_is_512_not_pipeline_default():
    """SD 管道 __call__ 默认 1024（那是给 SDXL 的）；SD1.5 原生 512，必须显式登记。"""
    assert D.IMAGE_MODELS["sd15-t2i"]["native_size"] == 512


# ─────────────────────── 路径与状态 ───────────────────────

def test_local_paths_deterministic_and_under_cache():
    a = D.DiffsynthImageEngine.local_file("sd15-t2i")
    b = D.DiffsynthImageEngine.local_file("sd15-t2i")
    assert a == b
    norm = a.replace("\\", "/")
    assert "models" in norm and "cache" in norm
    assert norm.endswith(".safetensors")


def test_is_downloaded_false_when_absent():
    assert D.DiffsynthImageEngine.is_downloaded("__definitely_not__") is False


# ─────────────────────── ① 不自动下载 ───────────────────────

def test_generate_does_not_auto_download(monkeypatch):
    called = {"pull": 0}
    monkeypatch.setattr(D.DiffsynthImageEngine, "pull",
                        lambda self, *a, **k: called.__setitem__("pull", called["pull"] + 1))
    monkeypatch.setattr(D.DiffsynthImageEngine, "is_downloaded", staticmethod(lambda mid: False))
    monkeypatch.setattr(D.DiffsynthImageEngine, "is_available", staticmethod(lambda: True))
    eng = D.DiffsynthImageEngine()
    r = eng.generate("sd15-t2i", prompt="a cat")
    assert r["ok"] is False
    assert called["pull"] == 0, "generate 绝不能触发下载"


# ─────────────────────── ② 诚实失败 ───────────────────────

def test_unknown_model_message():
    r = D.DiffsynthImageEngine().generate("__nope__", prompt="x")
    assert r["ok"] is False and "__nope__" in r["message"]


def test_t2i_requires_prompt_or_image():
    r = D.DiffsynthImageEngine().generate("sd15-t2i")
    assert r["ok"] is False and "prompt" in r["message"]


def test_missing_input_image_message():
    r = D.DiffsynthImageEngine().generate("sd15-t2i", image_path="no_such.png")
    assert r["ok"] is False and "不存在" in r["message"]


def test_unavailable_reason_specific():
    reason = D.DiffsynthImageEngine.unavailable_reason()
    assert isinstance(reason, str)
    if reason:
        assert len(reason) > 3


def test_pull_rejects_unknown_without_network():
    r = D.DiffsynthImageEngine().pull("__no_such__")
    assert r["ok"] is False and "未知模型" in r["message"]


# ─────────────────────── ③ 探测零重导入（AST 锁）───────────────────────

def test_probe_functions_no_real_import():
    """★ is_available / unavailable_reason 函数体内不得真 import diffsynth_engine。"""
    import ast
    src = pathlib.Path(D.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in ("is_available", "unavailable_reason"):
            body = ast.dump(fn)
            assert "find_spec" in body, fn.name
            assert "ImportFrom" not in body or "diffsynth_engine" not in body.replace(
                "diffsynth_compat", ""), fn.name


# ─────────────────────── ④ moviepy shim 前置（AST 锁）───────────────────────

def test_load_goes_through_compat_entry():
    """★ load() 必须经 diffsynth_compat.import_diffsynth_engine()（裸 import 必炸）。"""
    src = inspect.getsource(D.DiffsynthImageEngine.load)
    assert "import_diffsynth_engine" in src
    assert "diffsynth_compat" in src


# ─────────────────────── ⑤ 下载通道与契约形状 ───────────────────────

def test_pull_uses_modelscope_snapshot():
    src = inspect.getsource(D.DiffsynthImageEngine.pull)
    assert "snapshot_download" in src and "modelscope" in src


def test_generate_returns_video_gen_aligned_shape():
    """generate 的返回键必须与 video_gen 对齐（image_* 对应 video_*），
    否则调用方要写两套解析 —— 那正是本项目一直在避免的「两条并行实现」反模式。"""
    src = inspect.getsource(D.DiffsynthImageEngine.generate)
    for key in ('"image_path"', '"image_url"', '"steps"', '"seconds_elapsed"', '"message"'):
        assert key in src, key


def test_engine_singleton():
    assert D.get_image_engine() is D.get_image_engine()


def test_unload_safe_when_never_loaded():
    D.DiffsynthImageEngine().unload()   # 不该抛
