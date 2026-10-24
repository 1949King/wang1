"""app/tests/test_local_video_infer.py — 既有本地视频推理模块的收敛回归（2026-10-02）。

背景：项目里曾有**两套本地视频生成**并存 ——
  · `app/core/local_video_infer.py`（6 族，已接线，但**不认 SVD、不扫项目模型目录**）
  · `app/core/neural/video_gen.py`（认 SVD、会下载，但**未接线**）
本轮把 SVD 支持**并入既有模块**（收敛方向），本文件锁住这几条。

纪律：本测试**不加载模型、不下载权重、不跑推理**（纯静态与扫描逻辑）。
"""
import os

from app.core import local_video_infer as L


# ─────────────── SVD 已并入既有模块 ───────────────

def test_svd_registered_in_all_three_tables():
    """三张表必须一致登记 svd —— 少一张就会「认得但跑不了」。"""
    assert "svd" in L.MODEL_KEYWORD_MAP
    assert "svd" in L.PIPELINE_CLASS_MAP
    assert "svd" in L._INFER_FUNC_MAP
    assert L.PIPELINE_CLASS_MAP["svd"] == "StableVideoDiffusionPipeline"


def test_svd_keyword_recognition():
    """★ 关键：项目里 SVD 的实际目录名是 `stabilityai_stable-video-diffusion-img2vid-xt`。

    收敛前 `_guess_model_kind` 认不出它 ⇒ 明明下载了却「找不到模型」。
    """
    assert L._guess_model_kind("svd-xt-i2v") == "svd"
    assert L._guess_model_kind("svd") == "svd"
    assert L._guess_model_kind(
        "stabilityai_stable-video-diffusion-img2vid-xt") == "svd"
    assert L._guess_model_kind("models--stabilityai--stable-video-diffusion-img2vid-xt") == "svd"


def test_other_families_not_broken():
    """并入 SVD 时不能踩到别的族（本次改 `_INFER_FUNC_MAP` 时一度漏掉 minimax_h3）。"""
    for k in ("wan", "cogvideox", "hunyuan", "ltx", "mochi", "minimax_h3", "svd"):
        assert k in L._INFER_FUNC_MAP, k
        assert k in L.MODEL_KEYWORD_MAP, k
        assert k in L.PIPELINE_CLASS_MAP, k


def test_svd_declared_as_i2v():
    """★ SVD 是**图生视频**：不需要 prompt，但必须有输入图。

    这条语义差异必须显式声明，否则会被当成 t2v 族处理
    （入口曾硬性要求 prompt 非空 ⇒ SVD 永远进不来）。
    """
    assert "svd" in L.I2V_KINDS


# ─────────────── 扫描目录已含项目自己的下载位 ───────────────

def test_scan_covers_project_model_cache():
    """★ 必须扫 `app/models/cache` —— 那是 `neural_engine.download_snapshot()` 的落盘位。

    收敛前不扫这里 ⇒ **项目自己下载的模型，本模块永远看不到**。
    """
    joined = "|".join(L.LOCAL_MODELS_DIR_CANDIDATES).replace("\\", "/")
    assert "models/cache" in joined
    assert "models/video" in joined


# ─────────────── ★ 空壳目录过滤（易复发的坑） ───────────────

def test_has_weights_rejects_empty_shell(tmp_path):
    """只有 repo 元数据（如 HF 的 `refs/main`）的空壳目录必须被判为「无权重」。

    实测踩到：本机同时存在
      · `~/.cache/huggingface/hub/models--stabilityai--...`（**1KB 空壳**）
      · `app/models/cache/stabilityai_...`（**4.2GB 真权重**）
    而调用方取 `matches[0].path` ⇒ 不过滤就会选到空壳，
    「明明下载了却加载失败」，且报错指向模型不存在，**极难排查**。
    """
    shell = tmp_path / "models--x--y"
    (shell / "refs").mkdir(parents=True)
    (shell / "refs" / "main").write_text("deadbeef")
    assert L._has_weights(str(shell)) is False


def test_has_weights_rejects_tiny_safetensors(tmp_path):
    """0 字节 / 极小的 safetensors 占位不算有权重（HF blob 索引会留这种）。"""
    d = tmp_path / "m"
    d.mkdir()
    (d / "model.safetensors").write_bytes(b"")
    assert L._has_weights(str(d)) is False


def test_has_weights_accepts_real_weights(tmp_path):
    """真正有 MB 级权重文件的目录应被判为有权重。"""
    d = tmp_path / "m"
    d.mkdir()
    (d / "model.safetensors").write_bytes(b"\0" * (2 * 1024 * 1024))
    assert L._has_weights(str(d)) is True


def test_has_weights_handles_missing_dir():
    assert L._has_weights("__definitely_not_a_dir__") is False


# ─────────────── 入口不再硬性要求 prompt（i2v 放行） ───────────────

def test_entry_allows_empty_prompt_when_image_given():
    """★ 有图时允许空 prompt —— 否则 SVD 永远进不来。

    用 AST/源码断言而非实跑（实跑要加载模型）：
    入口里那句判断必须带 `reference_image or first_frame` 的放行条件。
    """
    import inspect
    src = inspect.getsource(L.generate_video_local)
    assert "reference_image or first_frame" in src, \
        "入口的空 prompt 判断必须对 i2v（有图）放行"


def test_svd_infer_requires_image_and_honest_failure():
    """SVD 推理函数在**无图**时必须诚实报错（不静默、不退回文生视频）。"""
    import inspect
    src = inspect.getsource(L._infer_svd)
    assert "图生视频" in src and "reference_image" in src
    assert "decode_chunk_size=1" in src, "实测关键项：chunk=1"
    assert "max_guidance_scale" in src, "CFG 必须显式给"
    assert "motion_bucket_id" in src, "实测画质项：motion_bucket_id"
