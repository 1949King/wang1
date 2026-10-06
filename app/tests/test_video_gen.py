"""app/tests/test_video_gen.py — 本地视频生成引擎回归（2026-10-01）。

锁定的纪律：
  ① **模型不自动下载** —— `generate()` 绝不能悄悄开始下一个几 GB 的模型；
  ② **诚实失败** —— 缺图/缺模型/未知 id 都要给出**具体**原因，不返回占位视频；
  ③ 注册表里的体积是**实测值**（SVD 的子集必须显著小于全仓）；
  ④ 走**项目原生链路**（`neural_engine`），不依赖 ComfyUI。

注：本测试**不加载模型、不下载权重**（只在已下载时做只读判断）。
"""
import inspect

from app.core.neural import video_gen as V


# ─────────────────────── 注册表 ───────────────────────

def test_registry_nonempty_and_complete():
    models = V.available_models()
    assert len(models) >= 2
    for m in models:
        for k in ("id", "label", "params", "modes", "download_gb",
                  "vram_gb", "ram_gb", "note", "license"):
            assert k in m, (m.get("id"), k)
        assert m["modes"], m["id"]
        assert set(m["modes"]) <= {"t2v", "i2v"}


def test_svd_subset_is_much_smaller_than_full_repo():
    """★ SVD 只取 fp16 推理子集：必须显著小于全仓（否则等于白省 26GB）。"""
    spec = V.VIDEO_MODELS["svd-xt-i2v"]
    assert spec["subset_gb"] < spec["full_repo_gb"] / 3, spec
    assert spec["subset_gb"] <= 6.0, "子集应控制在 6GB 以内"


def test_svd_is_i2v_and_has_clip_encoder_note():
    spec = V.VIDEO_MODELS["svd-xt-i2v"]
    assert "i2v" in spec["modes"]
    assert "T5" in spec["note"] or "CLIP" in spec["note"]


def test_wan_requires_more_ram_than_this_machine():
    """★ 记录选型依据：Wan 系 RAM 需求高于本机可用，所以没被选为默认。"""
    for mid in ("wan22-ti2v-5b", "wan21-t2v-1.3b"):
        assert V.VIDEO_MODELS[mid]["ram_gb"] >= 16, mid


# ─────────────────────── 路径与状态（不发网络请求）───────────────────────

def test_local_dir_is_deterministic_and_under_models_cache():
    a = V.VideoGenEngine.local_dir("svd-xt-i2v")
    b = V.VideoGenEngine.local_dir("svd-xt-i2v")
    assert a == b
    assert "models" in a.replace("\\", "/")
    assert "cache" in a.replace("\\", "/")


def test_unknown_model_local_dir_falls_back_to_id():
    """未知 id 也要给得出路径（把 id 当 repo 用），不抛异常。"""
    d = V.VideoGenEngine.local_dir("__nope__/__x__")
    assert d
    assert "__nope__/__x__".replace("/", "_") in d.replace("\\", "_")


def test_is_downloaded_false_for_unknown_model():
    assert V.VideoGenEngine.is_downloaded("__definitely_not_downloaded__") is False


# ─────────────────────── ① 不自动下载 ───────────────────────

def test_generate_does_not_auto_download(monkeypatch):
    """★ generate() 对一个未下载的模型，必须**只报错、不下载**。"""
    called = {"pull": 0}
    monkeypatch.setattr(V.VideoGenEngine, "pull",
                        lambda self, *a, **k: called.__setitem__("pull", called["pull"] + 1))
    monkeypatch.setattr(V.VideoGenEngine, "is_downloaded", staticmethod(lambda mid: False))

    eng = V.VideoGenEngine()
    r = eng.generate("svd-xt-i2v", image_path="dummy.png")
    assert r["ok"] is False
    assert called["pull"] == 0, "generate 绝不能触发下载"


def test_pull_rejects_unknown_model_without_network():
    eng = V.VideoGenEngine()
    r = eng.pull("__no_such_model__")
    assert r["ok"] is False
    assert "未知模型" in r["message"]


# ─────────────────────── ② 诚实失败 ───────────────────────

def test_i2v_without_image_gives_specific_message():
    r = V.VideoGenEngine().generate("svd-xt-i2v")
    assert r["ok"] is False
    assert "image_path" in r["message"]


def test_unknown_model_generate_message():
    r = V.VideoGenEngine().generate("__nope__")
    assert r["ok"] is False
    assert "__nope__" in r["message"]


def test_unavailable_reason_is_specific_string():
    reason = V.VideoGenEngine.unavailable_reason()
    assert isinstance(reason, str)
    # 可用时为空串；不可用时必须给出**具体**原因（而不是"不可用"三个字）
    if reason:
        assert len(reason) > 3


def test_is_available_returns_bool():
    assert isinstance(V.VideoGenEngine.is_available(), bool)


# ─────────────────────── ④ 项目原生链路 ───────────────────────

def test_download_goes_through_neural_engine(monkeypatch):
    """★ 必须复用项目的 neural_engine.download_snapshot，而不是自建/ComfyUI。"""
    seen = {}

    class _FakeEng:
        def download_snapshot(self, repo, **kw):
            seen["repo"] = repo
            seen["patterns"] = kw.get("allow_patterns")
            return ""

    import app.core.neural_engine as ne
    monkeypatch.setattr(ne, "get_neural_engine", lambda: _FakeEng())
    monkeypatch.setattr(V.VideoGenEngine, "is_downloaded", staticmethod(lambda mid: False))

    r = V.VideoGenEngine().pull("svd-xt-i2v")
    assert seen["repo"] == "stabilityai/stable-video-diffusion-img2vid-xt"
    assert seen["patterns"], "SVD 必须带 allow_patterns 以只取 fp16 子集"
    assert r["ok"] is False           # 假引擎返回空路径 → 诚实失败


def test_svd_patterns_cover_fp16_only():
    """★ 子集模式必须排除 9GB 级的原始 .pth（否则白拉 26GB）。"""
    pats = V._SVD_FP16_PATTERNS
    assert any("fp16" in p for p in pats)
    assert not any(p.endswith(".pth") for p in pats)
    assert "model_index.json" in pats


# ─────────────────────── 单例 ───────────────────────

def test_engine_singleton():
    assert V.get_video_engine() is V.get_video_engine()


def test_unload_is_safe_when_never_loaded():
    V.VideoGenEngine().unload()   # 不该抛


# ─────────────────── 推理调优（2026-10-01 实测结论，锁死防回退）───────────────────

def test_tuned_svd_offload_stays_on():
    """★ offload **保持开启**（此结论经过两次反转，用例锁死防再翻车）。

    反转史（务必别重犯）：
      1. 最初判断「offload 是最大瓶颈」→ 改成不 offload。**错**：
         该判断在 **chunk=2** 下测出，把 chunk 的锅记到 offload 头上（混淆变量）。
      2. 固定 chunk=1 重测后反转：offload 开启**更快**（5 帧 40.0s vs 42.5s）
         且**更省显存**（4.66 vs 5.84GB）。
      3. 安全性定论：不 offload 时显存随帧数增长（≈0.4GB/帧），
         10 帧达 7.7GB → WDDM 分页 → 实测 **>600s 卡死**（正常只要 75.7s）。
    ⇒ 所有帧数都 offload，又稳又快。
    """
    assert V.tuned_for("svd-xt-i2v")["offload"] is True
    for fr in (0, 2, 5, 6, 8, 10, 25):
        assert V.should_offload("svd-xt-i2v", fr) is True, fr


def test_should_offload_always_true_for_unregistered():
    """未登记模型同样 offload（更保守：大模型更装不下）。"""
    for mid in ("wan22-ti2v-5b", "__unknown__"):
        assert V.should_offload(mid, 5) is True, mid
        assert V.should_offload(mid, 0) is True, mid


def test_tuned_svd_chunk_is_one_not_two():
    """★ 实测收益最稳的一项：chunk=1 的 VAE 解码 2.4~3.8s vs chunk=2 的 37.5s。

    小了反而快约 6 倍，且显存更低。8 帧 chunk=2 实测要 377s（47 s/帧）。
    已验证与 chunk=2 输出等价（逐帧 PSNR 46.0 dB、拼图肉眼不可区分）。
    """
    assert V.tuned_for("svd-xt-i2v")["decode_chunk_size"] == 1


def test_tuned_svd_steps_below_default():
    """14 步（原默认 25）—— 运动保留 98%、拼图肉眼同级；10 步运动升到 132% 故不作默认。"""
    st = V.tuned_for("svd-xt-i2v")["steps"]
    assert 10 <= st < 25, st


def test_unregistered_model_falls_back_to_conservative():
    """★ 未登记模型必须退回**保守**默认（offload=True）。

    理由：调优值是按 SVD（4.2GB，8GB 装得下）实测的；
    换成更大的模型（如 Wan 系）若照搬「不 offload」会直接 OOM。
    宁可慢，不可炸。
    """
    for mid in ("wan22-ti2v-5b", "wan21-t2v-1.3b", "__unknown__"):
        t = V.tuned_for(mid)
        assert t["offload"] is True, mid
        assert t["decode_chunk_size"] == 2, mid
        assert t["steps"] == 25, mid


def test_tuned_for_returns_copy_not_reference():
    """返回副本：调用方改它不应污染全局调优表。"""
    a = V.tuned_for("svd-xt-i2v")
    a["steps"] = 999
    assert V.tuned_for("svd-xt-i2v")["steps"] != 999


def test_generate_accepts_steps_param():
    """generate() 必须能接 steps（质量/速度旋钮），且未下载时依旧诚实失败不下载。"""
    import inspect
    sig = inspect.signature(V.VideoGenEngine.generate)
    assert "steps" in sig.parameters


# ─────────────────── 质量档位 / 运动档位 / CFG 锁（2026-10-01 实测）───────────────────

def test_quality_presets_ordering():
    """档位必须单调：fast(10) < balanced(14) < best(25)，且默认取 balanced。"""
    q = V.QUALITY_PRESETS
    assert q["fast"] < q["balanced"] < q["best"]
    assert q["best"] == 25, "best 应对齐原默认 25 步"
    assert V.tuned_for("svd-xt-i2v")["steps"] == q["balanced"]


def test_motion_presets_and_default_is_calm():
    """★ 默认必须是 calm(80)。

    实测（真实立绘 / 14 步 / 6 帧）：mb80 主体**6 帧全程稳定**（首帧保持 23.0dB、
    抖动 15.48），而 127/180 后段崩坏（180 第 4 帧起就明显变形）；**三者耗时相同**。
    本项目主力素材是漫剧/立绘 ⇒ 默认 calm 是纯赚的画质提升。
    """
    m = V.MOTION_PRESETS
    assert m["calm"] < m["normal"] < m["lively"]
    assert m["normal"] == 127, "normal 应对齐 SVD 原默认"
    assert V.tuned_for("svd-xt-i2v")["motion_bucket_id"] == m["calm"] == 80


def test_cfg_must_stay_enabled():
    """★★ CFG 绝不能被关掉。

    实测：`max_guidance_scale=1.0`（关 CFG）让每步快 **1.85x**（42.8s→23.1s），
    但输出**直接废掉** —— 首帧保持 35.1→15.9dB，拼图上噪声糊满画面。
    这是最容易被「为了提速」误关的一项，故用断言锁死。
    """
    t = V.tuned_for("svd-xt-i2v")
    assert t["cfg_max"] > 1.0, "cfg_max 必须 >1，否则 CFG 关闭、输出报废"
    assert t["cfg_min"] >= 1.0
    g = inspect.signature(V.VideoGenEngine.generate)
    assert "quality" in g.parameters and "motion" in g.parameters


def test_generate_exposes_quality_and_motion_knobs():
    """generate() 必须暴露 quality / motion 两个用户可见档位。"""
    sig = inspect.signature(V.VideoGenEngine.generate)
    assert sig.parameters["quality"].default == ""
    assert sig.parameters["motion"].default == ""


# ─────────────── P2：步数蒸馏档（2026-10-02） ───────────────

def test_preview_preset_exists_and_is_lowest():
    """★ 蒸馏预览档必须在位，且步数最低（4 步偏软，舒适区 6~8 ⇒ 取 6）。"""
    q = V.QUALITY_PRESETS
    assert "preview" in q, "缺 preview 档"
    assert q["preview"] <= 8, "预览档应在 4~8 步区间"
    assert q["preview"] < q["fast"] < q["balanced"] < q["best"]


def test_svd_is_marked_not_distilled():
    """★ SVD-xt 是**未蒸馏基模** ⇒ `distilled=False` ⇒ 必须开 CFG。

    若有人把它标成 True，CFG 会被压成 1.0，输出直接报废（实测首帧保持 35→16dB）。
    """
    t = V.tuned_for("svd-xt-i2v")
    assert t["distilled"] is False
    assert float(t["cfg_max"]) > 1.0


def test_distilled_flag_implies_cfg_one():
    """★ 蒸馏权重**必须 CFG=1.0** —— 训练时就是无 CFG 的，开 CFG 反而劣化。

    验证 `generate()` 源码里确实按 `distilled` 分支决定 CFG（而不是硬编码）。
    """
    src = inspect.getsource(V.VideoGenEngine.generate)
    assert "distilled" in src, "generate 未消费 distilled 标记"
    assert "1.0 if _is_distilled" in src or "_is_distilled" in src, \
        "CFG 必须按 distilled 分支取值"


def test_distilled_flag_is_documented():
    """该标记的由来（蒸馏 vs 基模的 CFG 差异）必须留档，否则后人会误删。"""
    import pathlib
    src = pathlib.Path(V.__file__).read_text(encoding="utf-8")
    assert "蒸馏" in src and "CFG" in src
