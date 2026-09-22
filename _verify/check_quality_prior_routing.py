#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.37.4 质量先验库 + 收益函数选路（规格书 §11/§14/§39 切片）—— 自包含。

跑法: python _verify/check_quality_prior_routing.py

验收要点：
  A. EMA 数学正确（均值/方差递推、样本夹紧、冷启动）
  B. inherit 冷启动不确定度（继承均值、方差×4）
  C. 持久化原子写 + 重载
  D. 收益函数选路：priors 覆盖 tier 排序；缺先验中性 0.5；无 priors 向后兼容
  E. 端到端：假 provider 成败 → 先验回写（local 不记录）
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types

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
    # 沙箱 wmic 黑名单（项目不变量 #10）：import app 链会触发 config_manager 的
    # wmic 并挂死。注入空 app 假包，让 video_generation_client 里
    # `from app.core.canvas_gen_jobs import ...` 等导入**快速 ImportError**
    # （这些导入都有 try 兜底），而不是执行 app/__init__.py。
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
    tmpdir = tempfile.mkdtemp(prefix="sg_qp_test_")
    qp = _load("quality_prior.py")
    pc = _load("provider_caps.py")

    # ════════════ A. EMA 数学 ════════════
    store = qp.QualityPriorStore(store_path=os.path.join(tmpdir, "a.json"))
    store.record("seedance", 1.0)
    p = store.predict("seedance")
    check("首样本：均值=样本", p and abs(p["mean"] - 1.0) < 1e-9)
    check("首样本：冷启动方差 0.25", p and abs(p["var"] - 0.25) < 1e-9)
    store.record("seedance", 0.0)
    p = store.predict("seedance")
    # delta=-1 → mean=1+0.3*(-1)=0.7；var=0.7*(0.25+0.3*1)=0.385
    check("EMA 均值递推 1.0→0.0 → 0.7", p and abs(p["mean"] - 0.7) < 1e-9)
    check("EMA 方差递推 → 0.385", p and abs(p["var"] - 0.385) < 1e-9)
    check("样本计数 n=2", p and p["n"] == 2.0)
    store.record("seedance", 9.9)  # 越界样本
    p = store.predict("seedance")
    check("样本夹紧到 [0,1]", p and 0.0 <= p["mean"] <= 1.0)
    check("未知 provider predict=None", store.predict("nope") is None)
    check("mean_of 无数据用中性 0.5", abs(store.mean_of("nope") - 0.5) < 1e-9)
    store.record("", 1.0)  # 空 provider 不崩
    check("空 provider 记录不崩（no-op）", store.predict("") is None)

    # ════════════ B. inherit 冷启动不确定度（规格 §39） ════════════
    store2 = qp.QualityPriorStore(store_path=os.path.join(tmpdir, "b.json"))
    store2.record("dashscope", 0.9, kind="wan2.2")
    store2.inherit("dashscope", "wan2.2", "wan2.5")
    p_new = store2.predict("dashscope", kind="wan2.5")
    p_old = store2.predict("dashscope", kind="wan2.2")
    check("继承：均值照搬", p_new and abs(p_new["mean"] - p_old["mean"]) < 1e-9)
    check("继承：方差 ×4（≥0.25）", p_new and abs(p_new["var"] - 1.0) < 1e-9)
    check("继承：n 归零（新桶未观测）", p_new and p_new["n"] == 0.0)
    store2.inherit("dashscope", "wan2.2", "wan2.5")  # 已存在不覆盖
    check("继承不覆盖已有桶", store2.predict("dashscope", kind="wan2.5")["var"] == 1.0)

    # ════════════ C. 持久化 ════════════
    path_c = os.path.join(tmpdir, "c.json")
    store3 = qp.QualityPriorStore(store_path=path_c)
    store3.record("cogvideo", 0.8)
    check("原子写落盘", os.path.exists(path_c))
    store4 = qp.QualityPriorStore(store_path=path_c)
    p = store4.predict("cogvideo")
    check("重载读取先验", p and abs(p["mean"] - 0.8) < 1e-9)
    # 损坏文件容错
    with open(path_c, "w", encoding="utf-8") as f:
        f.write("{broken json")
    store5 = qp.QualityPriorStore(store_path=path_c)
    check("损坏文件按空库启动", store5.predict("cogvideo") is None)

    # ════════════ D. 收益函数选路 ════════════
    check("λ_c 常量存在", abs(pc._LAMBDA_PRICE - 0.2) < 1e-9)
    # D1：无 priors → 旧行为（tier 降序 + 声明顺序）
    order = pc.resolve_order("auto")
    check("无 priors 向后兼容（dashscope 首位）", order[0] == "dashscope")
    # D2：priors 覆盖 tier/声明顺序
    order = pc.resolve_order("auto", priors={"seedance": 0.9, "dashscope": 0.1})
    # utility: seedance=0.9-0.2*1.0=0.7；dashscope=0.1-0.2*1.5=-0.2；cogvideo=0.5-0.2*0.8=0.34
    check("priors 排序：seedance 反超 dashscope", order[0] == "seedance")
    check("priors 排序：缺先验的 cogvideo 用中性 0.5 居中",
          order == ["seedance", "cogvideo", "dashscope", "local"])
    check("local 仍永远兜底", order[-1] == "local")
    # D3：显式 provider 路径不受 priors 影响
    order = pc.resolve_order("seedance", priors={"dashscope": 1.0})
    check("显式 provider 不受 priors 影响", order == ["seedance", "local"])
    # D4：quote() 不传 priors → 行为不变
    q = pc.quote("auto", count=1)
    check("quote 不传 priors → 仍报 dashscope", q["provider"] == "dashscope")

    # ════════════ E. 端到端：假 provider 成败 → 先验回写 ════════════
    vgc = _load("video_generation_client.py")
    # 注入隔离先验库（不碰真 data/quality_prior.json）
    iso = qp.QualityPriorStore(store_path=os.path.join(tmpdir, "e.json"))
    qp._STORE = iso
    client = vgc.VideoGenerationClient()

    def _fail(prompt, duration, count, width, height):
        raise RuntimeError("模拟云端失败")

    def _ok(prompt, duration, count, width, height):
        return [os.path.join(tmpdir, "fake_1.mp4")]

    client._providers = {"dashscope": None, "seedance": _fail, "cogvideo": _ok}
    paths = client.generate(prompt="测试", duration=3.0, count=1)
    check("端到端出片（cogvideo 假成功）", paths == [os.path.join(tmpdir, "fake_1.mp4")])
    p_seed = iso.predict("seedance")
    p_cog = iso.predict("cogvideo")
    check("失败渠道先验 mean=0.0", p_seed and abs(p_seed["mean"]) < 1e-9)
    check("成功渠道先验 mean=1.0", p_cog and abs(p_cog["mean"] - 1.0) < 1e-9)
    check("dashscope handler=None 不产生先验记录", iso.predict("dashscope") is None)
    # local 占位不记录（强造全失败走兜底——真跑 ffmpeg 太慢，直接验 _record_prior 的 local 门）
    client._record_prior("local", True)
    check("local 占位不写先验", iso.predict("local") is None)
    qp._STORE = None  # 还原单例

    print(f"\n{'ALL PASS' if not FAILS else 'FAILED'} ({TOTAL} checks)")
    for f in FAILS:
        print(f"  - {f}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
