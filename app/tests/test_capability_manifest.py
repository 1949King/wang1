# -*- coding: utf-8 -*-
"""能力清单 × 引擎注册表契约测试（P0 · 2026-10-28）。

守的是什么（这套字段最大的风险不是「填错」，是「填得像真的」）
==============================================================
5 个能力字段（quant / offload_tiers / step_cache / verified / loop_owner）是
「引擎自主可控」唯一机器可读的证词。它们一旦可以随手填，`capability_manifest`
的 K5 覆盖率就变成自欺 —— 报 3/4 而实际 0/4，比不报更糟。

所以本文件锁的不是「代码能跑」，是**声明与事实的一致性**：
  ① 66 条登记全部带 5 字段，值域合法；
  ② `offload_tiers` 只许填 `memory_policy` 已实现的档（预告档永不得声明）；
  ③ `quant` 只许填 `quant_descriptor` 准入得了的方案；
  ④ 声称 `loop_owner=shiguang + verified` ⇒ 必须真有 `kernel/loop.py`（不许空头支票）；
  ⑤ K5 覆盖率口径固定，且**内核没写就该是 0/4**（诚实比好看重要）；
  ⑥ 本模块零 torch、零重依赖（画布 HTTP 线程与门禁都要能直接调）。
"""
from __future__ import annotations

import inspect

import pytest

from app.core import engine_registry as ER
from app.core.neural import capability_manifest as CM
from app.core.neural import memory_policy as MP


# ─────────────────── ① 5 字段齐全且值域合法 ───────────────────


def test_all_registrations_expose_five_capability_fields():
    rows = CM.registrations()
    assert len(rows) == len(ER.ENGINES) >= 60
    for r in rows:
        for k in ("quant", "offload_tiers", "step_cache", "verified", "loop_owner"):
            assert k in r, "%s 缺能力字段 %s" % (r["id"], k)


def test_loop_owner_value_domain():
    for r in CM.registrations():
        assert r["loop_owner"] in ("shiguang", "upstream"), r["id"]


def test_verified_three_state_domain():
    from app.core.neural.model_family import BLOCKED, UNVERIFIED, VERIFIED

    for r in CM.registrations():
        assert r["verified"] in (VERIFIED, UNVERIFIED, BLOCKED), r["id"]


def test_defaults_are_honest_not_optimistic():
    """默认值必须是「不声明」，不能是「支持」。

    这条守的是最容易犯的错：给新引擎留 `verified="verified"` 这种好意默认值，
    结果没人补证据，全库都"已验证"。默认只能是 unverified / upstream / 空。
    """
    e = ER.EngineSpec(id="x", family="inference", capability="image",
                      module="app/core/neural/memory_policy.py", role="library-only")
    assert e.verified == "unverified"
    assert e.loop_owner == "upstream"
    assert e.quant == ""
    assert e.offload_tiers == ()
    assert e.step_cache is False


# ─────────────────── ② offload_tiers ⊆ 已实现档 ───────────────────


def test_offload_tiers_are_subset_of_active_modes():
    """双向守卫：登记里写的档名必须真的在 `memory_policy.ACTIVE_MODES` 里。

    （与 `test_memory_policy.test_ladder_matches_memory_policy` 同一手法：
    两处各写一份档名表必然漂移，用测试把两边钉在一起。）
    """
    planned = set(getattr(MP, "PLANNED_MODES", ()))
    active = set(MP.ACTIVE_MODES)
    for r in CM.registrations():
        for t in r["offload_tiers"]:
            assert t in active, "%s 声明了未实现档 %s" % (r["id"], t)
            assert t not in planned, "%s 声明了预告档 %s" % (r["id"], t)


def test_honest_tier_declarations_match_code():
    """按源码事实核准三个推理引擎的档位声明（声明必须与实现同源）。"""
    by_id = {r["id"]: r for r in CM.registrations()}

    # diffusers_image.load() 有 four-way 分支（573/579/583 + 584 直上卡）
    assert set(by_id["image.diffusers"]["offload_tiers"]) == set(MP.ACTIVE_MODES)

    # video_gen 只有 model / sequential 两个分支（506/509）；
    # whole_gpu 是实测危险路径（10 帧 WDDM 分页 >600s），故不声明
    assert by_id["video.svd"]["offload_tiers"] == (
        MP.MODE_MODEL_OFFLOAD, MP.MODE_SEQUENTIAL_OFFLOAD)
    assert MP.MODE_WHOLE_GPU not in by_id["video.svd"]["offload_tiers"]

    # local_video_infer 全库只有 enable_model_cpu_offload
    assert by_id["video.local_video_infer"]["offload_tiers"] == (
        MP.MODE_MODEL_OFFLOAD,)

    # diffsynth 用自有 cpu_offload，不走 policy 档位 ⇒ 不准瞎声明
    assert by_id["image.diffsynth"]["offload_tiers"] == ()


# ─────────────────── ③ quant 准入 ───────────────────


def test_declared_quant_is_admissible():
    for r in CM.registrations():
        if not r["quant"]:
            continue
        assert r["quant_admissible"], "%s: %s 不可准入（%s）" % (
            r["id"], r["quant"], r["quant_why"])


def test_rejected_scheme_would_be_caught(monkeypatch):
    """反例：有人把被否决的 int8wo_v2 填进登记，契约必须报红。"""
    from app.core.neural import quant_descriptor as QD

    orig = QD.is_admissible
    monkeypatch.setattr(QD, "is_admissible",
                        lambda s, **k: (False, "已实测否决") if s == "int8wo_v2" else orig(s, **k))
    orig_rows = CM.registrations
    monkeypatch.setattr(CM, "registrations", lambda: [
        dict(r, quant="int8wo_v2", quant_admissible=False, quant_why="已实测否决")
        if r["id"] == "image.diffusers" else r
        for r in orig_rows()
    ])
    bad = CM.violations()
    assert any("int8wo_v2" in b and "不可准入" in b for b in bad), bad


def test_main_path_inference_engines_must_declare_quant():
    """主路径推理引擎必须显式声明 quant；library-only 豁免（不许代它编数据）。"""
    for r in CM.registrations():
        must = r["capability"] in ("image", "video") and \
            r["role"] not in ("library-only", "retired", "disabled")
        if must:
            assert r["quant"], "%s 是主路径推理引擎却未声明 quant" % r["id"]


# ─────────────────── ④ 「声明即承诺」 ───────────────────


def test_shiguang_claim_requires_kernel_module(monkeypatch):
    """说循环归自己 ⇒ 必须有 kernel/loop.py，否则报红。

    2026-10-28 P2：内核**已经存在**，所以这条规则不能再靠"文件真的不存在"来触发。
    改成把 `_module_exists` 打桩成 False —— 守的是**规则本身**，
    而不是"此刻盘上恰好没有那个文件"。前者长期有效，后者只会到期失效。
    """
    assert ER._module_exists("app/core/neural/kernel/loop.py"), \
        "内核应当已存在（P2 已交付）；若这里为假，说明 loop.py 被删了"
    monkeypatch.setattr(ER, "_module_exists", lambda rel: False)
    orig = CM.registrations
    monkeypatch.setattr(CM, "registrations", lambda: [
        dict(r, loop_owner="shiguang", verified="verified")
        if r["id"] == "image.diffusers" else r for r in orig()
    ])
    bad = CM.violations()
    assert any("kernel/loop.py 不存在" in b for b in bad), bad


def test_library_only_cannot_be_verified():
    """无入口的能力不算可用 —— library-only 不许标 verified。"""
    orig = CM.registrations
    try:
        CM.registrations = lambda: [
            dict(r, verified="verified") if r["role"] == "library-only" else r
            for r in orig()
        ]
        bad = CM.violations()
        assert any("library-only" in b for b in bad), bad
    finally:
        CM.registrations = orig


def test_duplicate_registration_is_flagged(monkeypatch):
    orig = CM.registrations
    monkeypatch.setattr(CM, "registrations", lambda: orig() + [orig()[0]])
    bad = CM.violations()
    assert any("重复登记" in b for b in bad), bad


# ─────────────────── ⑤ K5 覆盖率口径 ───────────────────


def test_coverage_is_honest_two_of_four_after_p2():
    """P2 落地 sd15/sdxl ⇒ K5 = 2/4（此前是 0/4，这条断言按设计"到期升级"）。

    为什么它会随阶段变化：K5 分子是「loop_owner=shiguang 且 verified」，
    P2 之前内核不存在，任何非零都是撒谎；P2 之后两族真的四门验收通过，
    还停在 0/4 就变成"明明做了却报没做"—— 两种偏差一样有害。

    剩下 2 族（svd / wan）必须仍在 pending 里：视频内核是 P3 的事，
    这里不许因为图像通了就顺手把它们算进来。
    """
    cov = CM.coverage()
    assert cov["target"] == list(CM.TARGET_FAMILIES)
    assert cov["ratio"] == "2/4"
    assert sorted(cov["owned"]) == ["sd15", "sdxl"]
    assert sorted(p["family"] for p in cov["pending"]) == ["svd", "wan"]


def test_coverage_counts_only_shiguang_and_verified(monkeypatch):
    """分子要求两个条件**同时**成立：只满足一个不算。

    两个方向都要造，否则只证了一半：
      · loop 不在自己手里（loop_owner=upstream）⇒ 不算；
      · 循环归自己但未验收（verified=unverified）⇒ 也不算。
    """
    orig = CM.registrations

    def _rows(**patch):
        rows = orig()
        return [dict(r, **patch.get(r["id"], {})) for r in rows]

    # 方向一：把 loop_owner 退回 upstream
    monkeypatch.setattr(CM, "registrations", lambda: _rows(
        **{"image.diffusers": {"loop_owner": "upstream"}}))
    assert CM.coverage()["owned"] == []

    # 方向二：loop_owner 保持 shiguang，但把 verified 降级
    monkeypatch.setattr(CM, "registrations", lambda: _rows(
        **{"image.diffusers": {"verified": "unverified"}}))
    assert CM.coverage()["owned"] == []

    # 反证：两条件都成立时必须算进来（否则前两条断言可能是"恒为空"的假绿）
    monkeypatch.setattr(CM, "registrations", lambda: _rows(
        **{"image.diffusers": {"loop_owner": "shiguang", "verified": "verified"}}))
    assert sorted(CM.coverage()["owned"]) == ["sd15", "sdxl"]


def test_target_families_exist_in_model_family():
    """K5 分母不许自说自话：目标族必须在 model_family 里有登记。"""
    from app.core.neural import model_family as MF

    for fam in CM.TARGET_FAMILIES:
        assert MF.spec_of(fam) is not None, fam


def test_every_target_family_has_a_carrier_engine():
    ids = {r["id"] for r in CM.registrations()}
    for fam, eid in CM.FAMILY_ENGINE.items():
        assert fam in CM.TARGET_FAMILIES
        assert eid in ids, "%s 的承载引擎 %s 未登记" % (fam, eid)


# ─────────────────── ⑥ 依赖纪律 ───────────────────


def test_manifest_is_torch_free():
    """画布 HTTP 线程与门禁脚本都会直接 import 它 ⇒ 顶层不许有 torch。"""
    src = inspect.getsource(CM)
    head = src.split('"""', 2)[-1]          # 去掉模块 docstring，只看代码
    assert "import torch" not in head
    assert "from torch" not in head


def test_manifest_does_not_leak_private_registry_internals():
    """清单只读字段，不许把 registry 私有函数当 API 用（除显式标注的 _module_exists）。"""
    src = inspect.getsource(CM)
    assert "ER.health" in src            # 明确复用的公开判定
    assert "ER.ENGINES" in src or "_registry()" in src


def test_describe_is_human_readable_and_reports_k5():
    """P2 之后 K5 是 2/4（sd15/sdxl 已接管循环），违约仍必须 0 条。"""
    text = CM.describe()
    assert "K5 覆盖率 2/4" in text
    assert "违约 0 条" in text


def test_manifest_shape_is_stable():
    m = CM.manifest()
    for k in ("engines_n", "by_verified", "by_loop_owner", "coverage",
              "two_legs", "violations", "engines"):
        assert k in m
    # P2 之后 sd15/sdxl 确实两腿并存（pipe 默认 + kernel 接管），声明位必须如实列出；
    # 视频族仍只有一腿，漏进来就是预告而不是事实。
    assert sorted(leg["family"] for leg in m["two_legs"]) == ["sd15", "sdxl"]


def test_registry_entry_points_delegate():
    """registry 只做入口，判定逻辑只有一份（在 capability_manifest）。"""
    assert ER.capabilities()["engines_n"] == len(ER.ENGINES)
    assert isinstance(ER.contract_violations(), list)


@pytest.mark.parametrize("eid", ["image.diffusers", "video.svd",
                                 "video.local_video_infer", "image.diffsynth"])
def test_key_engines_step_cache_and_owner(eid):
    rec = {r["id"]: r for r in CM.registrations()}[eid]
    # P2：图像族的循环已由 kernel/loop.py 接管（SHIGUANG_KERNEL=on 生效）；
    # 视频族仍在 pipe/第三方 __call__ 里，不许跟着改。
    expect = "shiguang" if eid == "image.diffusers" else "upstream"
    assert rec["loop_owner"] == expect, "loop_owner 与内核落地情况不符"
    assert rec["step_cache"] is (eid == "image.diffusers")
