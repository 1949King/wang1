#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 V4.38.2 AI 辅助人工抽检子系统（规格书第十四篇 §70-76 切片⑨）—— 自包含。

跑法: python _verify/check_sampling_review.py

验收要点：
  A. 自适应抽样：确定性（同单元同决定）；残差/分歧放大提高 P；
     新版本/新题材强制必检；24h 重复签名过滤
  B. 规则预审：缺失文件/Schema 缺字段→高；体积/时长异常→中；
     灰区机器分→uncertain 上交；表单字段齐全
  C. 红线：submit_ai_score 永不写先验（注入计数 writer 断言 0 次）；
     待复核清单高风险优先
  D. 人工标签：唯一写先验通道；非法标签拒绝；残差 EMA 更新
  E. 漂移：残差均值>0.30 → 冻结+告警；冻结中 is_frozen；人工解冻重置基线
  F. 指标：召回/精确/减负率口径正确
  G. 端到端闭环：人工标签经 writer 写进隔离先验库 quality 桶
"""
from __future__ import annotations

import importlib.util
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
    tmpdir = tempfile.mkdtemp(prefix="sg_sr_test_")
    sr = _load("sampling_review.py")

    # ════════════ A. 自适应分层抽样（§71.1） ════════════
    rv = sr.SamplingReview(store_path=os.path.join(tmpdir, "a.json"))
    d1 = rv.should_sample("unit-001", "video")
    d2 = rv.should_sample("unit-001", "video")
    check("A1 确定性：同单元同决定", d1["sample"] == d2["sample"])
    check("A2 基础概率 = 2%", abs(d1["p"] - 0.02) < 1e-9)
    d3 = rv.should_sample("unit-002", "video", residual=1.0, divergence=1.0)
    check("A3 残差+分歧放大（0.02×7=0.14）", abs(d3["p"] - 0.14) < 1e-9)
    check("A4 放大理由可读", any("残差放大" in r for r in d3["reasons"]))
    d4 = rv.should_sample("unit-003", "video", new_version=True)
    check("A5 新模型版本强制必检", d4["sample"] is True and d4["p"] == 1.0)
    d5 = rv.should_sample("unit-004", "video", new_genre=True)
    check("A6 新题材强制必检", d5["sample"] is True)
    d6 = rv.should_sample("unit-005", "video", prompt_sig="sig_x")
    d7 = rv.should_sample("unit-006", "video", prompt_sig="sig_x")
    check("A7 24h 重复签名被过滤", (not d6["sample"] or True)
          and d7["sample"] is False
          and any("重复样本" in r for r in d7["reasons"]))

    # ════════════ B. 规则预审（§71.2） ════════════
    v1 = rv.prescreen({"unit_id": "b1", "kind": "video",
                       "path": os.path.join(tmpdir, "no_such.mp4"),
                       "machine_score": 0.8})
    check("B1 文件缺失 → 高风险", v1["risk"] == "高")
    v2 = rv.prescreen({"unit_id": "b2", "kind": "text",
                       "fields": {"台词": "你好"},
                       "required_fields": ["台词", "场景"],
                       "machine_score": 0.8})
    check("B2 Schema 缺字段 → 高风险", v2["risk"] == "高"
          and any("场景" in d for d in v2["defects"]))
    big = os.path.join(tmpdir, "big.bin")
    with open(big, "wb") as f:
        f.write(b"x" * 32768)   # >10KB，不触发视频体积异常规则
    v3 = rv.prescreen({"unit_id": "b3", "kind": "video", "path": big,
                       "machine_score": 0.8, "duration": 3.0,
                       "expected_duration": 5.0})
    check("B3 时长偏差>20% → 中风险", v3["risk"] == "中")
    v4 = rv.prescreen({"unit_id": "b4", "kind": "video", "path": big,
                       "machine_score": 0.5})
    check("B4 灰区机器分 → uncertain 上交", v4["uncertain"] is True)
    v5 = rv.prescreen({"unit_id": "b5", "kind": "video", "path": big,
                       "machine_score": 0.9, "mode": "D",
                       "model_version": "wan2.2", "provider": "dashscope"})
    need = {"machine_score", "divergence", "mode", "model_version",
            "provider", "risk", "suggested", "created_at"}
    check("B5 预填表单字段齐全（§71.3）", need.issubset(set(v5["form"].keys())))
    check("B6 健康单元 → 低风险+建议合格",
          v5["risk"] == "低" and v5["form"]["suggested"] == "合格")

    # ════════════ C. 红线：AI 打分永不写先验 ════════════
    calls = []
    rv2 = sr.SamplingReview(store_path=os.path.join(tmpdir, "c.json"),
                            prior_writer=lambda p, y: calls.append((p, y)))
    rv2.submit_ai_score({"unit_id": "c1", "kind": "video",
                         "path": os.path.join(tmpdir, "none.mp4"),
                         "machine_score": 0.9})
    rv2.submit_ai_score({"unit_id": "c2", "kind": "video", "path": big,
                         "machine_score": 0.9})
    check("C1 submit_ai_score 不写先验（writer 0 次）", len(calls) == 0)
    pend = rv2.pending_reviews()
    check("C2 高风险排最前", pend[0]["unit_id"] == "c1"
          and pend[0]["risk"] == "高")

    # ════════════ D. 人工真值（唯一写先验通道） ════════════
    r_bad = rv2.submit_human_label("c1", "随便")
    check("D1 非法标签拒绝", r_bad["ok"] is False)
    r_ok = rv2.submit_human_label("c1", "不合格", provider="dashscope")
    check("D2 人工标签接受", r_ok["ok"] is True and r_ok["y"] == 0.0)
    check("D3 人工标签写先验（writer 1 次）", len(calls) == 1
          and calls[0] == ("dashscope", 0.0))
    check("D4 残差 = |0−0.9| = 0.9", abs(r_ok["residual"] - 0.9) < 1e-9)
    check("D5 出池后不在待复核清单",
          all(f["unit_id"] != "c1" for f in rv2.pending_reviews()))

    # ════════════ E. 漂移冻结 + 人工解冻（§29/§71.4/§72） ════════════
    rv3 = sr.SamplingReview(store_path=os.path.join(tmpdir, "e.json"))
    for i in range(6):  # 残差恒 0.9 → 均值迅速 >0.30
        rv3.submit_human_label(f"e{i}", "不合格", ai_score=0.9)
    ds = rv3.drift_status()
    check("E1 残差均值 >0.30", ds["residual_mean"] > 0.30)
    check("E2 闭环冻结", ds["frozen"] is True and rv3.is_frozen())
    check("E3 冻结告警已记录",
          any(a["kind"] == "freeze" for a in ds["alerts"]))
    uf = rv3.unfreeze(operator="测试员")
    check("E4 人工解冻", uf["was_frozen"] is True
          and rv3.is_frozen() is False)
    check("E5 解冻后残差基线重置", rv3.drift_status()["residual_n"] == 0)
    # 样本不足不误冻结
    rv4 = sr.SamplingReview(store_path=os.path.join(tmpdir, "e2.json"))
    rv4.submit_human_label("x1", "不合格", ai_score=0.9)
    check("E6 样本不足 5 不冻结", rv4.is_frozen() is False)

    # ════════════ F. 指标（§74） ════════════
    rv5 = sr.SamplingReview(store_path=os.path.join(tmpdir, "f.json"))
    # 4 个高风险（AI 标）全判不合格（TP=4）；1 个低风险判不合格（FN=1）
    for i in range(4):
        rv5.submit_ai_score({"unit_id": f"f{i}", "kind": "video",
                             "path": os.path.join(tmpdir, "none.mp4"),
                             "machine_score": 0.8})
        rv5.submit_human_label(f"f{i}", "不合格")
    rv5.submit_ai_score({"unit_id": "f9", "kind": "video", "path": big,
                         "machine_score": 0.9})
    rv5.submit_human_label("f9", "不合格")
    m = rv5.metrics()
    check("F1 召回率 = TP/(TP+FN) = 4/5 = 0.8", abs(m["recall"] - 0.8) < 1e-9)
    check("F2 精确率 = TP/AI标高 = 4/4 = 1.0", abs(m["precision"] - 1.0) < 1e-9)
    check("F3 计数齐全", m["counts"]["tp"] == 4 and m["counts"]["fn"] == 1)

    # ════════════ G. 端到端：人工标签写进隔离先验库 ════════════
    qp = _load("quality_prior.py")
    store = qp.QualityPriorStore(store_path=os.path.join(tmpdir, "g.json"))
    rv6 = sr.SamplingReview(
        store_path=os.path.join(tmpdir, "g2.json"),
        prior_writer=lambda p, y: store.record_outcome(p, ok=True,
                                                       quality=y,
                                                       kind="quality"))
    rv6.submit_human_label("g1", "合格", provider="dashscope")
    q = store.route_mean("dashscope")
    check("G1 人工合格标签 → quality 桶均值 > 中性 0.5", q > 0.5)
    rv6.submit_human_label("g2", "不合格", provider="seedance")
    check("G2 人工不合格标签 → 均值 < 0.5",
          store.route_mean("seedance") < 0.5)

    print(f"\n{'=' * 50}\n抽检子系统检查：{TOTAL - len(FAILS)}/{TOTAL} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK AI 辅助人工抽检子系统全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
