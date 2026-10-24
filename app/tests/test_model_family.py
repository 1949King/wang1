# -*- coding: utf-8 -*-
"""模型族注册表（统一引擎 M1 协议层）测试。

锁死四件事：
1. resolve 的诚实失败：未登记族 / 权重不在盘 / 能力不匹配 ⇒ ok=False + 可读原因，
   绝不静默换族（svd 漏登记误杀视频路径的教训反着用：这次让"查无"成为显式结论）。
2. SVD 唯一归属 = video_gen（④ diffsynth 通道），local_video_infer 只作 fallback ——
   这是消灭双轨漂移的协议级承诺。
3. unverified 族不得进默认可选列表（include_unverified=False 必须滤掉）。
4. native_fps 与 V4.46.11/12 的实测纪律一致（svd=7、wan=16、ltx=25、minimax=24）。
探测均为惰性 import 轻模块（diffsynth_image/video_gen/local_video_infer 顶层无重依赖，
已逐一核实），不触发 torch/diffusers 真加载。
"""

import app.core.neural.model_family as MF


def test_registry_shape():
    fams = {s.family for s in MF.FAMILIES}
    assert {
        "sd15",
        "sdxl",
        "svd",
        "wan",
        "cogvideox",
        "hunyuan",
        "ltx",
        "mochi",
        "minimax_h3",
    } <= fams
    # 每个族的能力合法、后端 id 全在已知集合
    known = {
        MF.BACKEND_DIFFSYNTH_IMAGE,
        MF.BACKEND_DIFFUSERS_IMAGE,
        MF.BACKEND_VIDEO_GEN,
        MF.BACKEND_LOCAL_VIDEO,
    }
    for s in MF.FAMILIES:
        assert s.capability in (MF.CAP_IMAGE, MF.CAP_VIDEO, MF.CAP_AUDIO, MF.CAP_MUSIC, MF.CAP_LLM)
        assert set(s.backends) <= known, s.family
        assert s.verification in (MF.VERIFIED, MF.UNVERIFIED, MF.BLOCKED)


def test_svd_single_home():
    """协议级承诺：svd 首选后端 = video_gen（④），③ 只是 fallback。"""
    s = MF.spec_of("svd")
    assert s.backends[0] == MF.BACKEND_VIDEO_GEN
    assert s.native_fps == 7, "SVD 训练 fps=7（V4.46.11 实测），编码帧率不得再写死"
    assert s.tuned_ref.startswith("video_gen.TUNED"), "参数唯一真源指针必须指向 TUNED"


def test_native_fps_matches_measured_discipline():
    """各族 fps 取自其 num_frames 系数（V4.46.12 守卫同源，双保险）。"""
    expect = {
        "svd": 7,
        "wan": 16,
        "cogvideox": 16,
        "hunyuan": 16,
        "ltx": 25,
        "mochi": 16,
        "minimax_h3": 24,
    }
    for fam, fps in expect.items():
        assert MF.spec_of(fam).native_fps == fps, fam


def test_resolve_unknown_family_is_honest():
    r = MF.resolve("totally-new-model")
    assert r["ok"] is False
    assert any("未登记" in x for x in r["reasons"]), (
        "新模型未登记 ⇒ 必须指向'先登记'这条路（合一协议的意义）"
    )


def test_resolve_capability_mismatch_rejected():
    r = MF.resolve("sd15", capability_hint=MF.CAP_VIDEO)
    assert r["ok"] is False
    assert any("能力不匹配" in x for x in r["reasons"])


def test_resolve_image_family_prefers_diffsynth():
    r = MF.resolve("sd15")
    # 权重在盘（本机实测 sd15 已下载）⇒ ok；查无环境也不许崩，只许诚实 False
    if r["ok"]:
        assert r["backend"] == MF.BACKEND_DIFFSYNTH_IMAGE
        assert r["verification"] == MF.VERIFIED
    else:
        assert any("权重" in x or "后端" in x for x in r["reasons"])


def test_weights_probe_no_crash_on_absent():
    """未下权重的族：探测必须安全返回 False（不许抛）。"""
    for fam in ("wan", "ltx", "mochi", "minimax_h3", "hunyuan", "cogvideox"):
        assert MF.weights_present(fam) in (True, False)


def test_unverified_excluded_from_default_list():
    default = MF.families(capability=MF.CAP_VIDEO, include_unverified=False)
    names = {s.family for s in default}
    assert "svd" in names, "唯一验证过的视频族必须在默认可选里"
    assert not (names & {"wan", "ltx", "mochi"}), "未验证族混进了默认可选"


def test_status_shape():
    st = MF.status()
    assert st["total"] == len(MF.FAMILIES)
    assert st["verified"] + st["unverified"] <= st["total"]
    row = next(r for r in st["families"] if r["family"] == "sd15")
    assert set(row) >= {"family", "verification", "weights", "backends", "native_fps"}


def test_backend_health_detects_typo():
    """守卫自检思路：后端 id 拼错必须被 resolve 抓到（防 svd 漏登记类回归）。"""
    ok, why = MF._backend_available("not_a_real_backend")
    assert ok is False and "未知后端" in why


# ── ⑤ M2 接线：族→引擎优先级映射 + planner 消费注册表 ──────────────────
def test_preferred_engines_mapping():
    """引擎归属是核实过的事实：两条 SVD 实现 import 的都是 diffusers（video_gen.py:419）。"""
    assert MF.preferred_engines("svd") == ["diffusers"]
    assert MF.preferred_engines("sd15") == ["diffsynth", "diffusers"]
    assert MF.preferred_engines("sdxl") == ["diffsynth", "diffusers"]
    assert MF.preferred_engines("wan") == ["diffusers"]
    assert MF.preferred_engines("no-such-family") == []


def test_planner_default_order_comes_from_registry(monkeypatch, tmp_path):
    """无遥测证据时，planner 的保守默认序必须读模型族注册表（M2 收编）。

    svd 族 ⇒ engine=diffusers 且 is_fallback=False（diffusers 就是它的主选，
    旧逻辑写死「!= diffsynth 即备选」会把正确的视频选择误标成降级）。
    """
    import json

    monkeypatch.setenv(
        "SHIGUANG_DEVICE_PROFILE",
        json.dumps(
            {
                "vendor": "nvidia",
                "arch": "sm89",
                "name": "Fake Ada",
                "vram_gb": 8.0,
                "device_id": "nvidia:sm89:8.0gb",
                "capabilities": {},
                "libs": {"diffusers": True, "diffsynth_engine": True},
            }
        ),
    )
    monkeypatch.setenv("SHIGUANG_ENGINE_TELEMETRY_PATH", str(tmp_path / "tel.json"))
    from app.core.ai import execution_planner as EP

    r = EP._engine_probe("video")
    assert r["available"] is True, r.get("reason")
    assert r["engine"] == "diffusers", "SVD 必须路由到真实承接它的 diffusers 栈"
    assert r["is_fallback"] is False, "diffusers 是 svd 族的主选，不该标「退到备选」"
    assert "模型族注册表" in (r.get("reason") or ""), "默认序来源必须可见（R9）"

    # 图像族回归对照：sd15/sdxl 主选仍是 diffsynth（与改动前一致）
    r2 = EP._engine_probe("image")
    assert r2["engine"] == "diffsynth"
    assert r2["is_fallback"] is False
