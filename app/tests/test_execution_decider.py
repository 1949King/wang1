"""app/tests/test_execution_decider.py — L1 决策出口回归（2026-10-02）。

背景：核查发现**画布侧生成链完全不消费「异构动态协作引擎」的任何切片**
（对 12 个切片的引用数为 0），而 Agent 侧已接 11 个。
⇒ 两条链平行：Agent 侧「动态选路」，画布侧「静态查表」。

本模块（`ai/execution_decider.py`）是**收敛的第一步**：把选路收敛成单一出口，
行为与收敛前**逐键一致**，差别是多了决定性非空的 `reasons`。

纪律：本测试**不连云端、不加载模型**（只测决策逻辑与失败语义）。
"""
from app.core.ai.execution_decider import decide_execution


# ─────────────── 本地分支 ───────────────

def test_local_prefix_forces_local():
    """`local/` 前缀必须强制本地 —— 这是既有的语义约定，不得丢失。"""
    r = decide_execution(capability="video", channel_id="local/svd", model="svd-xt-i2v")
    assert r["ok"] is True
    assert r["channel_id"] == "local/svd"
    assert r["model"] == "svd-xt-i2v"


def test_local_respects_allow_local_false():
    """`allow_local=False` 时必须**诚实拒绝**，不得偷偷走本地。"""
    r = decide_execution(capability="video", channel_id="local/svd", allow_local=False)
    assert r["ok"] is False
    assert "本地执行被禁用" in r["message"]


def test_frames_recorded_in_reasons_for_local():
    """帧数要进 reasons（本地显存分级的输入，需可观测）。"""
    r = decide_execution(capability="video", channel_id="local/svd", frames=10)
    assert any("10" in x for x in r["reasons"])


# ─────────────── 云端分支：失败语义 ───────────────

def test_cloud_honest_failure_when_no_channel():
    """★ 铁律 R3：无可用渠道必须**诚实失败并给指引**，不得静默降级到本地。"""
    r = decide_execution(capability="video", quality="standard", motion="calm")
    assert r["ok"] is False
    assert r["message"], "失败必须带可读 message"
    assert any("渠道" in x for x in r["reasons"])


def test_cloud_respects_allow_cloud_false():
    r = decide_execution(capability="video", allow_cloud=False)
    assert r["ok"] is False
    assert "云端执行被禁用" in r["message"]


# ─────────────── ★ 铁律 A1：reasons 必须非空 ───────────────

def test_reasons_always_present():
    """★ 铁律 A1：选路必须可解释 —— 无论成功失败，`reasons` 都不得为空。

    没有它，线上「为什么走了这条渠道」无法排障（这正是引入本出口的主要目的之一）。
    """
    cases = [
        dict(capability="video", channel_id="local/svd"),
        dict(capability="video", channel_id="local/svd", allow_local=False),
        dict(capability="video"),
        dict(capability="video", allow_cloud=False),
    ]
    for kw in cases:
        r = decide_execution(**kw)
        assert r["reasons"], f"reasons 为空: {kw}"


# ─────────────── ★ 运动词汇归一（易静默出错的坑） ───────────────

def test_motion_vocabulary_normalized():
    """★ `video_gen` 用 calm/normal/lively，而 `translate_motion` 认 low/medium/high。

    传错会**静默退回 medium**（不报错、结果错）—— 正是「同一信息多处演化」的典型。
    本出口做单向归一，两套词汇都能用。

    验证方式：**直接查出口源码里的归一表**（走云端需要真渠道，测试里没有），
    确认 calm→low / lively→high 两个方向都映射正确，而不是靠 `or True` 蒙混。
    """
    import inspect

    from app.core.ai import execution_decider as ed

    src = inspect.getsource(ed.decide_execution)
    assert '"calm": "low"' in src, "缺少 calm→low 归一"
    assert '"lively": "high"' in src, "缺少 lively→high 归一"
    assert '"normal": "medium"' in src, "缺少 normal→medium 归一"

    # 并确认目标词汇确实是 translate_motion 认的那套（否则归一到不存在的值）
    from app.core.canvas_aigc import MOTION_PRESET
    for v in ("low", "medium", "high"):
        assert v in MOTION_PRESET, f"translate_motion 不认 {v}（归一目标无效）"
    assert MOTION_PRESET["low"] <= MOTION_PRESET["medium"] <= MOTION_PRESET["high"]


def test_unknown_motion_does_not_crash():
    """未知运动档不得抛错（诚实退化，不炸调用方）。"""
    r = decide_execution(capability="video", motion="__nonsense__")
    assert "reasons" in r          # 不抛即可


# ─────────────── 返回结构契约 ───────────────

def test_return_shape_contract():
    """返回结构必须含契约字段（调用方按此读取）。"""
    r = decide_execution(capability="video", channel_id="local/svd")
    for k in ("ok", "channel_id", "model", "params", "reasons", "degrade_level", "message"):
        assert k in r, k


def test_does_not_mutate_registry():
    """决策是**只读**的：多次调用结果一致（不得有副作用）。"""
    a = decide_execution(capability="video", channel_id="local/svd")
    b = decide_execution(capability="video", channel_id="local/svd")
    assert a["ok"] == b["ok"] and a["channel_id"] == b["channel_id"]


# ─────────────── P3：治理切片已接入（此前画布侧引用数为 0）───────────────

def test_governance_slices_are_consumed():
    """★ 出口必须**引用**三个治理切片 —— 这是 P3 的核心（此前画布侧对它们引用数为 0）。

    验证方式：查源码里确有对应 import（走通需要真渠道，测试环境不连云端）。
    """
    import inspect

    from app.core.ai import execution_decider as ed

    src = inspect.getsource(ed.decide_execution)
    assert "provider_caps" in src, "未消费 provider_caps（能力筛选）"
    assert "budget_pacer" in src, "未消费 budget_pacer（影子价格 λ）"
    assert "quality_prior" in src, "未消费 quality_prior（期望质量 q̂）"


def test_governance_failure_degrades_honestly():
    """★ 治理切片不可用时必须**降级但不阻断**（诚实降级，不是静默失败）。"""
    import inspect

    from app.core.ai import execution_decider as ed

    src = inspect.getsource(ed.decide_execution)
    assert "降级为静态渠道解析" in src, "缺降级说明（用户应能从 reasons 看出走了降级路径）"


def test_spec_uses_semantic_flags_not_capability():
    """★ `normalize_spec` 认的是**语义标志**（text_to_video/image_to_video/first_last_frame），

    不是 capability/quality —— 传错键会得到空 spec、能力筛选**静默空转**（本次踩过）。
    """
    import inspect

    from app.core.ai import execution_decider as ed
    from app.core.ai import provider_caps as pc

    src = inspect.getsource(ed.decide_execution)
    assert "text_to_video" in src and "image_to_video" in src
    # 确认这两个键确实是 normalize_spec 认的（否则断言无意义）
    normalized = pc.normalize_spec({"text_to_video": True})
    assert normalized.get("text_to_video") is True, "normalize_spec 不认 text_to_video？"


def test_governance_accessors_exist():
    """★ 治理单例的访问器名必须核对过（本次踩过 `budget_pacer` 是**类**不是实例）。"""
    from app.core.ai.budget_pacer import get_pacer
    from app.core.ai.quality_prior import get_store

    assert callable(get_pacer)
    assert callable(get_store)
    assert hasattr(get_pacer(), "get_lambda"), "BudgetPacer 缺 get_lambda()"
    assert hasattr(get_store(), "predict"), "QualityPriorStore 缺 predict()"


# ═══════════ 主选 / 备选 执行引擎（2026-10-02 用户裁定）═══════════

def test_primary_and_fallback_engine_declared():
    """主选 = DiffSynth（Apache-2.0），备选 = 自研 builtin。"""
    from app.core.ai import execution_decider as ed

    assert ed.PRIMARY_ENGINE == "diffsynth"
    assert ed.FALLBACK_ENGINE == "builtin"


def test_env_switch_forces_fallback(monkeypatch):
    """★ 开关 `SHIGUANG_EXEC_ENGINE=fallback` 必须能**强制走自研备选**。

    这就是「等自研在能力与架构上都起来后，再替换回来」的那个开关 ——
    一行配置即可切，不需要改代码。
    """
    from app.core.ai import execution_decider as ed

    monkeypatch.setenv("SHIGUANG_EXEC_ENGINE", "fallback")
    r = ed.resolve_execution_engine()
    assert r["engine"] == ed.FALLBACK_ENGINE
    assert r["is_fallback"] is True
    assert r["switch"] == "fallback"


def test_primary_selected_when_available(monkeypatch):
    """★ 主选引擎**可用时**必须选主选（不能因为默认就永远走备选）。"""
    from app.core.ai import execution_decider as ed

    monkeypatch.delenv("SHIGUANG_EXEC_ENGINE", raising=False)
    monkeypatch.setattr(ed, "_probe_importable", lambda names: "diffsynth_engine")
    r = ed.resolve_execution_engine()
    assert r["engine"] == ed.PRIMARY_ENGINE
    assert r["is_fallback"] is False


def test_primary_unavailable_degrades_to_fallback_honestly(monkeypatch):
    """★ 铁律 R9：主选**不可用**时必须退备选，**且原因可见**。

    若静默切换，就会出现「以为在用主选、其实一直在跑备选」而永远查不出来。
    """
    from app.core.ai import execution_decider as ed

    monkeypatch.delenv("SHIGUANG_EXEC_ENGINE", raising=False)
    monkeypatch.setattr(ed, "_probe_importable", lambda names: "")
    r = ed.resolve_execution_engine()
    assert r["engine"] == ed.FALLBACK_ENGINE
    assert r["is_fallback"] is True
    assert r["reason"], "退化必须给出原因"
    assert "未安装" in r["reason"] or "pip install" in r["reason"]


def test_engine_recorded_in_reasons_and_result(monkeypatch):
    """引擎选择必须**同时**出现在返回字段与 `reasons` 里（可观测）。"""
    from app.core.ai import execution_decider as ed

    monkeypatch.setattr(ed, "_probe_importable", lambda names: "")
    r = ed.decide_execution(capability="video", channel_id="local/svd")
    assert "engine" in r
    assert any("执行引擎" in x for x in r["reasons"]), "reasons 未记录引擎选择"


def test_probe_does_not_trigger_heavy_import():
    """★ 探测必须用 `find_spec`（**不触发重量级 import**）—— 保冷启动。

    本项目有冷启动纪律（MainWindow 曾从 8.24s 优化到 0.191s），
    在决策出口里 import torch/diffusers 会直接毁掉它。
    """
    import inspect

    from app.core.ai import execution_decider as ed

    src = inspect.getsource(ed._probe_importable)
    assert "find_spec" in src, "探测必须用 find_spec"
    assert "import torch" not in src and "import diffusers" not in src


# ═══════════ H1 硬件三档自适应（2026-10-10）：全云 / 主流 / 满血 ═══════════

def _fake_tier(mem_mb, name="FakeGPU"):
    """构造一个假的 GPUInfo 返回值，供 monkeypatch 桩替换 detect_gpu。"""
    from types import SimpleNamespace
    from app.core.gpu_acceleration import GPUType

    return SimpleNamespace(gpu_type=GPUType.NVIDIA, name=name, memory_mb=mem_mb)


class _FakeDetector:
    def __init__(self, info):
        self._info = info

    def detect_gpu(self, force_redetect=False):
        return self._info


def _patch_tier(monkeypatch, mem_mb, name="FakeGPU"):
    from app.core.ai import execution_decider as ed

    monkeypatch.setattr(ed, "_gpu_detector", _FakeDetector(_fake_tier(mem_mb, name)))


def test_tier_full_at_16g(monkeypatch):
    """≥16G ⇒ 满血档。"""
    from app.core.ai import execution_decider as ed

    _patch_tier(monkeypatch, 16384, "RTX 4080")
    hw = ed.detect_hardware_tier()
    assert hw["tier"] == "full"
    assert hw["memory_mb"] == 16384
    assert "满血档" in hw["reason"]


def test_tier_mainstream_at_8g(monkeypatch):
    """5G~15G ⇒ 主流档（本机 RTX 4060 8G 落在这档）。"""
    from app.core.ai import execution_decider as ed

    _patch_tier(monkeypatch, 8188, "RTX 4060 Laptop")
    hw = ed.detect_hardware_tier()
    assert hw["tier"] == "mainstream"
    assert "主流档" in hw["reason"]


def test_tier_cloud_at_4g_and_below(monkeypatch):
    """≤4G ⇒ 全云档；边界 4096 含、4097 起进主流。"""
    from app.core.ai import execution_decider as ed

    _patch_tier(monkeypatch, 4096)
    assert ed.detect_hardware_tier()["tier"] == "cloud"
    _patch_tier(monkeypatch, 2048)
    assert ed.detect_hardware_tier()["tier"] == "cloud"
    _patch_tier(monkeypatch, 4097)
    assert ed.detect_hardware_tier()["tier"] == "mainstream"


def test_tier_zero_memory_is_cloud_honestly(monkeypatch):
    """无独显（核显 memory_mb=0）⇒ 全云档 + 诚实标注（不编数字）。"""
    from app.core.ai import execution_decider as ed

    _patch_tier(monkeypatch, 0, "Intel Iris Xe")
    hw = ed.detect_hardware_tier()
    assert hw["tier"] == "cloud"
    assert hw["memory_mb"] == 0
    assert "未探测到独显显存" in hw["reason"]


def test_tier_probe_exception_degrades_honestly(monkeypatch):
    """★ 探测异常 ⇒ 全云档 + 诚实标注 + **绝不抛出**（R3）。"""
    from app.core.ai import execution_decider as ed

    class _Boom:
        def detect_gpu(self, force_redetect=False):
            raise RuntimeError("no nvidia-smi")

    monkeypatch.setattr(ed, "_gpu_detector", _Boom())
    hw = ed.detect_hardware_tier()  # 不得抛
    assert hw["tier"] == "cloud"
    assert "探测异常" in hw["reason"]


def test_decide_execution_records_tier_in_reasons(monkeypatch):
    """★ R9：档位必须写进 reasons —— 线上能回答「为什么这条链走这档」。"""
    from app.core.ai import execution_decider as ed

    _patch_tier(monkeypatch, 8188)
    r = ed.decide_execution(capability="video", channel_id="local/svd")
    assert r["hw_tier"] == "mainstream"
    assert any("硬件档位" in x for x in r["reasons"]), "reasons 未记录硬件档位"


def test_tier_does_not_change_explicit_routing(monkeypatch):
    """★ 档位**只留痕不改路**：全云档下 `local/` 前缀仍强制本地（显式语义优先）。"""
    from app.core.ai import execution_decider as ed

    _patch_tier(monkeypatch, 2048)  # 全云档
    r = ed.decide_execution(capability="video", channel_id="local/svd")
    assert r["ok"] is True and r["channel_id"] == "local/svd"
    assert r["hw_tier"] == "cloud"


def test_tier_probe_is_cached_not_per_call(monkeypatch):
    """档位探测走 GPUDetector 缓存（多次调用不得每次都起 nvidia-smi 子进程）。"""
    import inspect

    from app.core.ai import execution_decider as ed

    # detect_hardware_tier 自己不 new 检测器（用模块级单例），且委托 detect_gpu 的缓存
    src = inspect.getsource(ed.detect_hardware_tier)
    assert "GPUDetector()" not in src, "不得每次调用新建检测器（丢缓存、反复起子进程）"
    assert "_get_gpu_detector()" in src
