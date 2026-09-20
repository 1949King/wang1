#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 score_book（P0-2 评分回写闭环）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_score_book.py

对照任务清单验收标准：
  1. record 后落盘文件出现条目（含增益组合）
  2. 同风格第 2 次 best_combo 选出的负面词/增益 = 第 1 次高分组合
  3. retake 条目降权（下次不再优先）
  4. 不同 style_dna 互不污染
  5. score 归一（0~100 → 0~1）/ dim 维度聚合
  6. enhance_prompt 集成：guards 带 style_dna → 负面词换历史组合 + 增益词注入
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
    """加载 app/core/ai 下的模块（伪包方式，使相对导入可用且不 import app 包）。"""
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    modname = fname[:-3]
    full = f"{pkg}.{modname}"
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    sb = _load("score_book.py")

    tmpdir = tempfile.mkdtemp(prefix="sg_score_test_")
    store = os.path.join(tmpdir, "score_book.json")
    book = sb.ScoreBook(store_path=store)

    # ── 1. record 落盘 ──
    book.record("都市逆袭|冷色调",
                dims={"画面质量": 0.9, "构图": 0.8},
                gains=["8K", "无阴影"], negatives=["三通结构", "多余分支"],
                score=88)
    check("落盘文件存在", os.path.exists(store))
    with open(store, "r", encoding="utf-8") as f:
        raw = json.load(f)
    check("条目含增益组合",
          raw["entries"]["都市逆袭|冷色调"][0]["gains"] == ["8K", "无阴影"])
    check("score 0~100 归一为 0~1",
          abs(raw["entries"]["都市逆袭|冷色调"][0]["score"] - 0.88) < 1e-6)

    # ── 2. best_combo 选用高分组合 ──
    book.record("都市逆袭|冷色调",
                gains=["8K", "无阴影"], negatives=["三通结构", "多余分支"], score=90)
    book.record("都市逆袭|冷色调",
                gains=["胶片感"], negatives=["过曝"], score=0.55)
    combo = book.best_combo("都市逆袭|冷色调")
    check("返回历史高分组合", combo is not None)
    check("增益组合一致", combo["gains"] == ["8K", "无阴影"])
    check("负面词组合一致", combo["negatives"] == ["三通结构", "多余分支"])
    check("样本数累计", combo["samples"] == 2)
    check("未记录的风格 → None", book.best_combo("风格X") is None)

    # ── 3. retake 降权 ──
    book.record_retake("古装仙侠|暖色调",
                       gains=["电影感光"], negatives=["穿模"], score=0.95)
    book.record("古装仙侠|暖色调",
                gains=["水墨滤镜"], negatives=["过曝"], score=0.8)
    combo2 = book.best_combo("古装仙侠|暖色调")
    check("重拍组合被降权，次优组合胜出",
          combo2 is not None and combo2["gains"] == ["水墨滤镜"])
    check("retake_rate 可查", combo2["retake_rate"] == 0.0)

    # ── 4. 风格隔离 ──
    check("不同 style_dna 互不污染",
          book.best_combo("古装仙侠|暖色调")["gains"] != ["8K", "无阴影"])
    check("空 style_dna → None", book.best_combo("") is None)
    check("未记录风格 → None", book.best_combo("不存在的风格") is None)

    # ── 5. dim 维度聚合 ──
    book.record("维度测试",
                dims={"画面质量": 0.98}, gains=["高码率"], negatives=["糊"], score=0.6)
    by_dim = book.best_combo("维度测试", dim="画面质量")
    check("按维度聚合（画面质量 0.98 拉高组合）",
          by_dim is not None and by_dim["gains"] == ["高码率"]
          and by_dim["score"] > 0.9)

    # ── 6. stats ──
    st = book.stats()
    check("stats 汇总", st["total"] >= 5 and "都市逆袭|冷色调" in st["styles"])

    # ── 7. enhance_prompt 集成（guard_pipeline ⑤ 步）──
    gp = _load("guard_pipeline.py")
    # 把测试簿塞进 score_book 单例（enhance_prompt 走 get_score_book()）
    sb._book_instance = book
    try:
        out = gp.enhance_prompt("夜市追逐戏", guards={
            "style_dna": "都市逆袭|冷色调",
            "prop": {"prop_type": "sword", "grip": "two_hand", "hand": "both"},
        })
        check("增益词注进提示词", "8K" in out["prompt"] and "无阴影" in out["prompt"])
        check("负面词换成历史高分组合",
              "三通结构" in out["negative"] and "过曝" not in out["negative"])
        check("detail 记录评分簿来源",
              out["guards"].get("score_book", {}).get("samples") == 2)
        check("changed=True", out["changed"] is True)
        # 无 style_dna 的 guards：行为与旧版一致（不查簿）
        out2 = gp.enhance_prompt("x", guards={})
        check("无 style_dna 不查簿（负面词仍是全量）", len(out2["negative"]) > 0
              and "score_book" not in out2["guards"])
    finally:
        sb._book_instance = None

    # 清理
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    # ── 汇总 ──
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        for x in FAILS:
            print(f"  - {x}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
