# -*- coding: utf-8 -*-
"""守卫：语义轨道原型（§6.9-P3 · 质量分/高光落 clip 元数据，2026-10-17）。

验证三件事：
  ① 盖章契约：pipeline 打分结果按 clip_id / source_clip_id 别名盖章到
     clip["semantic"]["quality"]；无匹配如实跳过；估算维度如实透传（§8 诚实红线）。
  ② 高光规则：narrative_highlight ≥ A 级线自动判定；人工/Agent 显式标记
     优先，后续盖章不回改 highlight（quality 仍正常刷新）。
  ③ 静态接线在册：能力目录 2 行、editor skills 循环注册 2 行、薄壳 handler、
     pipeline.score 盖章调用、本守卫已登记 run_all_checks（防静默断线）。

纯 dict 操作模块，不触碰 UI；FakeEditor 鸭子类型即可。
"""
from __future__ import annotations

import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.core.clip_semantic import (  # noqa: E402
    HIGHLIGHT_THRESHOLD,
    SEMANTIC_KEY,
    get_semantic,
    mark_highlight,
    read_semantic,
    stamp_scored_results,
)

PASS = []
FAIL = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("  %s %-58s %s" % ("✅" if ok else "❌", name, detail))


def _result(clip_id, nh=50.0, total=70.0, grade="C", est=None, drop=False):
    """ScoreResult.to_dict 形状的最小构造。"""
    return {
        "clip_id": clip_id,
        "dimensions": {"visual_quality": 60.0, "narrative_highlight": nh,
                       "copy_match": 70.0, "bgm_match": 70.0, "shot_duration": 70.0},
        "weighted_score": total, "grade": grade, "should_drop": drop,
        "suggestions": [], "estimated_dims": list(est or []),
        "is_fully_estimated": len(est or []) >= 5, "metrics": {}, "measured_dims": [],
    }


# ---------------------------------------------------------------------------
# ① 盖章契约
# ---------------------------------------------------------------------------
print("=" * 74)
print("① 盖章：按 id/别名匹配、字段完整、无匹配如实跳过")
print("=" * 74)

clips = [{"id": "c1", "path": "a.mp4"}, {"id": "c2", "source_clip_id": "gen_x", "path": "b.mp4"}]
n = stamp_scored_results(clips, [_result("c1", nh=85.0, total=82.0, grade="A"),
                                 _result("gen_x", est=["visual_quality"]),
                                 _result("nope")])
check("stamp 返回盖章数=2（无匹配条目如实跳过）", n == 2, f"got {n}")
q1 = get_semantic(clips[0]).get("quality") or {}
check("quality 字段完整（score/grade/dimensions/scored_at/source）",
      q1.get("weighted_score") == 82.0 and q1.get("grade") == "A"
      and "dimensions" in q1 and q1.get("scored_at")
      and q1.get("source") == "five_dimension_scorer")
q2 = get_semantic(clips[1]).get("quality") or {}
check("source_clip_id 别名命中盖章", q2.get("estimated_dims") == ["visual_quality"])
check("estimated_dims 如实透传（不隐瞒估算）", q1.get("estimated_dims") == [])
check("is_fully_estimated 如实透传", q2.get("is_fully_estimated") is False)
n0 = stamp_scored_results([], [_result("c1")])
check("空片段列表盖章数=0（不造片段）", n0 == 0)
_tmp = [{"id": "t1"}]
check("非 dict 结果条目跳过不崩溃",
      stamp_scored_results(_tmp, ["bad", None, _result("t1")]) == 1)
check("get_semantic 非 dict 输入返回空", get_semantic(None) == {} and get_semantic("x") == {})

# ---------------------------------------------------------------------------
# ② 高光规则：自动判定 + 人工优先
# ---------------------------------------------------------------------------
print("=" * 74)
print("② 高光：A 级线自动判定 / 人工标记优先不被盖章回改")
print("=" * 74)

hl1 = get_semantic(clips[0]).get("highlight") or {}
check("narrative_highlight≥80 自动判高光", hl1.get("value") is True and hl1.get("auto") is True)
hl2 = get_semantic(clips[1]).get("highlight") or {}
check("narrative_highlight<80 自动判非高光", hl2.get("value") is False)
check("自动高光记录 dim_score/threshold 依据",
      hl1.get("dim_score") == 85.0 and hl1.get("threshold") == HIGHLIGHT_THRESHOLD)

ok = mark_highlight(clips, "c1", True, marked_by="manual", note="用户圈定")
check("人工标记成功返回 True", ok is True)
hl_m = get_semantic(clips[0])["highlight"]
check("人工标记 auto=False 且带 note", hl_m.get("auto") is False and hl_m.get("note") == "用户圈定")
# 再次盖章（低分）：highlight 不回改，quality 正常刷新
stamp_scored_results(clips, [_result("c1", nh=10.0, total=55.0, grade="D", drop=True)])
check("盖章不回改人工高光（value 保持 True）",
      get_semantic(clips[0])["highlight"].get("value") is True)
check("盖章仍刷新 quality（低分如实落）",
      get_semantic(clips[0])["quality"].get("weighted_score") == 55.0
      and get_semantic(clips[0])["quality"].get("should_drop") is True)
check("Agent 标记同样不被盖章覆盖",
      mark_highlight(clips, "c2", True, marked_by="agent")
      and stamp_scored_results(clips, [_result("gen_x", nh=5.0)]) == 1
      and get_semantic(clips[1])["highlight"].get("value") is True)
check("mark_highlight 未找到片段返回 False",
      mark_highlight(clips, "ghost", True) is False)

# ---------------------------------------------------------------------------
# ③ 查询：found 区分「没标」与「没找到」
# ---------------------------------------------------------------------------
print("=" * 74)
print("③ read_semantic：列表/单查/未打分/不存在 四类语义")
print("=" * 74)

clips3 = [{"id": "s1"}, {"id": "s2", "semantic": {"quality": {"grade": "B"}}}]
items = read_semantic(clips3)
check("不带 clip_id 只列有语义块的片段", len(items) == 1 and items[0]["clip_id"] == "s2")
one = read_semantic(clips3, "s2")
check("指定已打分片段 found=True 且带 grade 摘要",
      one[0]["found"] is True and one[0]["grade"] == "B")
none = read_semantic(clips3, "s1")
check("指定未打分数片段 found=False（区分没标/没找到）",
      len(none) == 1 and none[0]["found"] is False)
ghost = read_semantic(clips3, "zzz")
check("指定不存在片段返回空列表", ghost == [])
alias = read_semantic([{"id": "new1", "source_clip_id": "gen9",
                        "semantic": {"highlight": {"value": True}}}], "gen9")
check("别名可查询到重生成后的片段", len(alias) == 1 and alias[0]["highlight"] is True)

# ---------------------------------------------------------------------------
# ④ 静态接线在册
# ---------------------------------------------------------------------------
print("=" * 74)
print("④ 静态接线：目录/注册/薄壳/score 盖章/守卫登记")
print("=" * 74)


def _read(rel):
    with io.open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


_cat = _read("app/core/agent_capability_catalog.py")
check("能力目录含 editor.get_clip_semantic", '"editor.get_clip_semantic", "editor", "read"' in _cat)
check("能力目录含 editor.mark_clip_highlight", '"editor.mark_clip_highlight", "editor", "canvas_write"' in _cat)
_ch = _read("app/core/capability_handlers.py")
check("循环注册表含 get_clip_semantic 行", '"editor.get_clip_semantic", "get_clip_semantic"' in _ch)
check("循环注册表含 mark_clip_highlight 行", '"editor.mark_clip_highlight", "mark_clip_highlight"' in _ch)
check("pipeline.score 已接语义盖章调用", "stamp_scored_results(_cl" in _ch)
from app.core.capability_handlers_editor_skills import EditorSkillHandlers  # noqa: E402
check("薄壳 handler 两方法在册",
      hasattr(EditorSkillHandlers, "get_clip_semantic")
      and hasattr(EditorSkillHandlers, "mark_clip_highlight"))
from app.core.five_dimension_scorer import FiveDimensionScorer  # noqa: E402
check("高光阈值对齐 A 级线（80）",
      HIGHLIGHT_THRESHOLD == float(FiveDimensionScorer.GRADE_THRESHOLDS["A"]))
_rac = _read("_verify/run_all_checks.py")
check("本守卫已登记 run_all_checks（SEMMETA）", "SEMMETA" in _rac and "check_clip_semantic.py" in _rac)

# ---------------------------------------------------------------------------
print("=" * 74)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败项：", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
