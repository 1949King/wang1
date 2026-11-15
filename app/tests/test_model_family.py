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
    assert {"svd", "wan"} <= names, "真机验证过的视频族必须在默认可选（wan=M5 验收）"
    assert not (names & {"ltx", "mochi", "hunyuan"}), "未验证族混进了默认可选"


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


# ── 权重探测必须与磁盘事实同源（2026-11-15 修）──────────────────────────────
# 修之前这里有两个静默失败，导致 `weights_present()` 全线失真：
#   ① `from ...diffsynth_image import is_downloaded` / `from ...video_gen import is_downloaded`
#      —— 真名是 **Engine.is_downloaded 静态方法**，模块级函数不存在 ⇒ ImportError 被吞 ⇒ 恒 False
#      ⇒ sd15 / sdxl / svd 明明在盘却被 resolve() 判「权重不在盘」。
#   ② `_probe_local_video` 的第二个条件 `bool(_guess_model_kind(kind))` 传的是**族名**，
#      族名自己命中自己的关键词 ⇒ 恒 True ⇒ 零权重的 cogvideox / ltx / mochi 被谎报「在盘」。
# 下面三条测的就是「别再退回去」。


def test_image_probe_agrees_with_engine_static_method():
    """图像族：能探测到 True 当且仅当引擎静态方法说已下载（不许恒 False）。"""
    from app.core.neural.diffsynth_image import IMAGE_MODELS, DiffsynthImageEngine

    checked = 0
    for fam, mid in (("sd15", "sd15-t2i"), ("sdxl", "sdxl-t2i")):
        assert mid in IMAGE_MODELS
        if not DiffsynthImageEngine.is_downloaded(mid):
            continue  # 本机没下就不比，避免换机器误红
        assert MF.weights_present(fam) is True, f"{fam} 权重在盘，探测却返回 False"
        checked += 1
    assert checked >= 0  # 只作可读性说明：0 也合法（无权重机器）


def test_svd_probe_agrees_with_engine_static_method():
    """SVD：探测结果必须等于 VideoGenEngine.is_downloaded（此前恒 False）。"""
    from app.core.neural.video_gen import VideoGenEngine

    if not VideoGenEngine.is_downloaded("svd-xt-i2v"):
        assert MF.weights_present("svd") is False
        return
    assert MF.weights_present("svd") is True, "SVD 权重在盘，探测却返回 False"


def test_local_video_probe_only_trusts_disk_scan():
    """③ 系各族：探测结果必须与「真实扫描到的 kind」逐一对齐。

    这条不依赖本机是否下载 —— 有目录就必须 True，没目录就必须 False。
    恒 True（旧 bug）和恒 False 都会在这里红。
    """
    from app.core.local_video_infer import _scan_local_models

    present = {m.kind for m in _scan_local_models()}
    for fam in ("wan", "cogvideox", "hunyuan", "ltx", "mochi", "minimax_h3"):
        assert MF.weights_present(fam) == (fam in present), (
            f"{fam}：探测={MF.weights_present(fam)} 但磁盘扫描={fam in present}"
        )


def test_probes_have_no_legacy_wrong_patterns():
    """源码级防回归：两种错误写法都不许再出现。

    改成 AST 断言而不是字符串匹配 —— 字符串会被**注释**命中（第一版就踩了：
    注释里写着「不要再写 import is_downloaded」，结果断言自己被自己的注释绊倒）。
    行为断言在「正好蒙对」的机器上还会假绿，而这两条错误的根因是写法本身：
      · 模块级 import 一个不存在的函数（真名是 Engine 静态方法）；
      · 拿**族名**去 `_guess_model_kind` 猜模型 id ⇒ 族名自己命中自己 ⇒ 恒 True。
    """
    import ast
    import inspect
    import textwrap

    def _tree(fn):
        return ast.parse(textwrap.dedent(inspect.getsource(fn)))

    def _imported(tree):
        out = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                out |= {a.name for a in n.names}
        return out

    def _touched(tree):
        """函数体里真正被引用的标识符（Name.id + Attribute.attr）。"""
        return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }

    img = _tree(MF._probe_image)
    svd = _tree(MF._probe_svd)
    vid = _tree(MF._probe_local_video)

    for name, tree in (("_probe_image", img), ("_probe_svd", svd)):
        assert "is_downloaded" not in _imported(tree), (
            f"{name}：is_downloaded 是 Engine 静态方法，不能用模块级 import（ImportError 会被吞）"
        )
    assert "DiffsynthImageEngine" in _touched(img), "图像探测必须落到引擎静态方法上"
    assert "VideoGenEngine" in _touched(svd), "SVD 探测必须落到引擎静态方法上"

    assert "_guess_model_kind" not in _touched(vid), "族名会被自己命中 ⇒ 探测恒 True"
    assert "_guess_model_kind" not in _imported(vid)
    assert "_scan_local_models" in _touched(vid), "只能认磁盘上真实扫描到的模型目录"


