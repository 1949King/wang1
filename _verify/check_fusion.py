#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.38.0 置信度融合器（三分）+ D 双路执行体（规格书 §42/§10 切片⑦）—— 自包含。

跑法: python _verify/check_fusion.py

验收要点：
  A. 文本融合：锁域不可翻越 / 逐字段评分择优 / 命名空间优先级 / only 规则 / 溯源
  B. 视频融合计划：同槽择优 / keyframe_ok=False 降权 0.7 / 差<0.05 让 prefer /
     时序升序 / 溯源含候选
  C. 音频混音计划：角色增益 / 峰值×增益>target 压回 / 总线>1 等比压缩 / 溯源
  D. 端到端 D：双路成功 → executed="D" + 溯源非空 + 分歧入库 + 花费记账(隔离)
  E. 云端失败退化：executed="C→L"（诚实不冒充 D）+ 本地段仍交付
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types

# 临时目录钉到项目内 .workbuddy/tmp（2026-09-28）：沙箱拦截系统 Temp 写入 ⇒
# tempfile.gettempdir() 回退到 cwd（项目根），直接单跑本脚本会把临时目录漏进仓库根。
# 规范入口 run_all_checks 已用 TMPDIR 传递；此处覆盖「直接单跑」路径。
try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if "__file__" in globals() else os.getcwd(),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load(fname: str):
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    for fake in ("app", "app.core"):
        if fake not in sys.modules:
            m = types.ModuleType(fake)
            m.__path__ = []
            sys.modules[fake] = m
    modname = fname[:-3]
    full = f"{pkg}.{modname}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="sg_fusion_test_")
    fu = _load("fusion.py")

    # ════════════ A. 文本：字段锁域 + 命名空间仲裁 ════════════
    merged, prov = fu.fuse_text(
        local_fields={"角色": "阿珍", "台词": "旧台词"},
        cloud_fields={"角色": "阿珍(错)", "台词": "新台词", "场景": "雨夜"},
        locks={"角色": "local"})
    check("A1 锁域字段只取锁定的来源", merged["角色"] == "阿珍")
    check("A2 锁域规则记入溯源", prov["fields"]["角色"]["rule"] == "lock")
    check("A3 未锁字段按优先级取 cloud", merged["台词"] == "新台词")
    check("A4 单边字段规则 = only", prov["fields"]["场景"]["rule"] == "only")
    merged2, prov2 = fu.fuse_text(
        local_fields={"台词": "本地版"}, cloud_fields={"台词": "云端版"},
        field_scores={"台词": {"local": 0.9, "cloud": 0.4}})
    check("A5 给了逐字段分就按分择优（优先于命名空间）", merged2["台词"] == "本地版")
    check("A6 评分规则记入溯源", prov2["fields"]["台词"]["rule"] == "score")
    check("A7 provenance 含 medium/mode/fused_at",
          prov["medium"] == "text" and prov["mode"] == "D" and "fused_at" in prov)

    # ════════════ B. 视频：关键帧择优 + 时序拼接 ════════════
    plan, provv = fu.plan_video_fusion([
        {"slot": 1, "source": "cloud", "path": "c1.mp4", "quality": 0.9,
         "duration": 5.0, "keyframe_ok": True},
        {"slot": 1, "source": "local", "path": "l1.mp4", "quality": 0.3,
         "duration": 5.0, "keyframe_ok": True},
        {"slot": 0, "source": "local", "path": "l0.mp4", "quality": 0.6,
         "duration": 5.0, "keyframe_ok": True},
        {"slot": 0, "source": "cloud", "path": "c0.mp4", "quality": 0.62,
         "duration": 5.0, "keyframe_ok": True},
        {"slot": 2, "source": "cloud", "path": "c2.mp4", "quality": 0.9,
         "duration": 5.0, "keyframe_ok": False},   # 帧坏：0.9×0.7=0.63
        {"slot": 2, "source": "local", "path": "l2.mp4", "quality": 0.65,
         "duration": 5.0, "keyframe_ok": True},
    ])
    check("B1 时序升序", [p["slot"] for p in plan] == [0, 1, 2])
    check("B2 质量悬殊选高分（cloud 0.9>0.3）", plan[1]["source"] == "cloud")
    check("B3 差<0.05 让给 prefer=cloud（0.62 vs 0.6）", plan[0]["source"] == "cloud")
    check("B4 关键帧崩坏降权后被反超（0.63<0.65 → local）",
          plan[2]["source"] == "local")
    seg0 = [s for s in provv["segments"] if s["slot"] == 2][0]
    check("B5 溯源含候选清单", len(seg0["candidates"]) == 2)
    check("B6 空输入不抛", fu.plan_video_fusion([])[0] == [])

    # ════════════ C. 音频：轨道分离混音 + 响度对齐 ════════════
    plana, prova = fu.plan_audio_mix([
        {"path": "v.wav", "role": "voice", "peak": 0.8, "source": "cloud"},
        {"path": "m.wav", "role": "music", "peak": 1.0, "source": "local"},
    ], target_peak=0.9)
    gains = {t["role"]: t["gain"] for t in plana}
    check("C1 角色增益比保持（voice:music = 1.0:0.5 = 2:1）",
          abs(gains["voice"] / gains["music"] - 2.0) < 1e-2)
    check("C2 总线>1 触发等比压缩（0.8+0.5=1.3）", prova["bus_scale"] < 1.0)
    tv = [t for t in prova["tracks"] if t["role"] == "voice"][0]
    check("C3 溯源含 pre_bus_gain（压总线前的角色增益 1.0）",
          abs(tv.get("pre_bus_gain", 0) - 1.0) < 1e-3)
    planb, provb = fu.plan_audio_mix([
        {"path": "v.wav", "role": "voice", "peak": 0.95, "source": "cloud"},
    ], target_peak=0.9)
    gb = planb[0]["gain"]
    check("C4 单轨峰值×增益>target 压回（0.9/0.95）",
          abs(gb - 0.9 / 0.95) < 1e-3)
    check("C5 溯源含 target_peak/tracks",
          provb["target_peak"] == 0.9 and len(provb["tracks"]) == 1)
    check("C6 空输入不抛", fu.plan_audio_mix([])[0] == [])

    # ════════════ D. 端到端：D 双路融合 ════════════
    bp = _load("budget_pacer.py")
    dpm = _load("divergence_probe.py")
    qp2 = _load("quality_prior.py")
    gpm = _load("global_price.py")
    vgc = _load("video_generation_client.py")
    # 隔离真实数据（同 QPRIOR/DEGRAD 做法）——路由排序依赖先验库，
    # 不隔离会被真实库里的历史失败记录带偏
    bp._PACER = bp.BudgetPacer(budget=100.0,
                               store_path=os.path.join(tmpdir, "pacer.json"))
    dpm._PROBE = dpm.DivergenceProbe(store_path=os.path.join(tmpdir, "probe.json"))
    qp2._STORE = qp2.QualityPriorStore(
        store_path=os.path.join(tmpdir, "qp.json"))
    gpm._GLOBAL = gpm.GlobalPriceController(
        store_path=os.path.join(tmpdir, "gp.json"))
    client = vgc.VideoGenerationClient.get_instance()
    cloud_file = os.path.join(tmpdir, "cloud_seg.bin")
    with open(cloud_file, "wb") as f:
        f.write(b"fake-cloud-video-bytes" * 64)

    def _fake_cloud(**_kw):
        return [cloud_file]

    # 路由收益排序的第一名随先验/λ 浮动——三个真实渠道**都**注入假实现，
    # 不管谁排第一双路都能拿到「云端」
    saved = {}
    for name in ("dashscope", "seedance", "cogvideo"):
        saved[name] = client._providers.get(name, "missing")
        client._providers[name] = _fake_cloud
    client._tls.last_fusion = None
    try:
        out = client.generate(prompt="D 双路端到端", duration=1.0, count=1,
                              provider="auto", width=320, height=240, mode="D")
    finally:
        for name, orig in saved.items():
            if orig == "missing":
                client._providers.pop(name, None)
            else:
                client._providers[name] = orig
    check("D1 双路有交付", len(out) == 1)
    check("D2 实际执行模式 = D", client.last_execution_mode() == "D")
    check("D3 融合溯源非空且 medium=video",
          client.last_fusion().get("medium") == "video")
    check("D4 云端质量分高 → 选云端段", out[0] == cloud_file)
    check("D5 分歧实测入库", dpm._PROBE.summary()["stats"].get("video", {})
          .get("n", 0) >= 1)
    used = client.last_used_provider()
    pcm = _load("provider_caps.py")
    price = float((pcm.PROVIDER_CAPS.get(used) or {}).get("price_per_clip") or 0)
    check("D6 花费记账（1 段 × 实际渠道单价）",
          abs(bp._PACER.status()["spent"] - price) < 1e-9)

    # ════════════ E. 云端失败：退化本地单路（诚实不冒充 D） ════════════
    def _boom(**_kw):
        raise RuntimeError("模拟云端 503")

    for name in ("dashscope", "seedance", "cogvideo"):
        client._providers[name] = _boom
    try:
        out2 = client.generate(prompt="D 退化端到端", duration=1.0, count=1,
                               provider="auto", width=320, height=240, mode="D")
    finally:
        for name, orig in saved.items():
            if orig == "missing":
                client._providers.pop(name, None)
            else:
                client._providers[name] = orig
    check("E1 云端挂仍有本地交付", len(out2) == 1)
    check("E2 实际模式 = C→L（诚实退化）", client.last_execution_mode() == "C→L")
    check("E3 降级标记 L6", client.last_degradation().get("level") == 6)

    print(f"\n{'=' * 50}\n融合器 + D 双路检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK 置信度融合器（三分）+ D 双路执行体全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
