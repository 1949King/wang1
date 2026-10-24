# -*- coding: utf-8 -*-
"""守卫：问题路由规则表（智能时间线 P1 / §6.9，2026-10-17）。

验证三件事：
  ① 纯函数行为：五维低分→类别→通道的规则表全路径（单类/混合/字幕细分/
     无血缘降级/信号不足兜底/置信度单调性/脏输入不抛）。
  ② 静态多处同步：路由输出的三通道模块必须真实存在（删通道文件即红）；
     run_all_checks 已登记本守卫；文档 §6.8.5/§6.9 已回写 ✅。
  ③ 反例自检：故意违规必须被抓（守卫自身不许是哑弹）。

【sys.path 绕过】同 check_clip_lineage：项目不变量 #10，
把 ``app/core`` 直接入 path，以顶层模块导入，完全不触碰 ``app`` 包。
"""
from __future__ import annotations

import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CORE = os.path.join(ROOT, "app", "core")
if CORE not in sys.path:
    sys.path.insert(0, CORE)

import problem_router as pr  # noqa: E402

PASS = []
FAIL = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("  %s %-58s %s" % ("✅" if ok else "❌", name, detail))


def _rev(**dims):
    """构造 review 入参（未列出的维度默认 80 高分，不干扰判据）。"""
    base = {"visual_quality": 80, "narrative_highlight": 80, "copy_match": 80,
            "bgm_match": 80, "shot_duration": 80}
    base.update(dims)
    return {"dimensions": base, "estimated_dims": [], "grade": "B"}


# ---------------------------------------------------------------------------
# ① 纯函数行为
# ---------------------------------------------------------------------------
print("=" * 74)
print("① 行为：五维标记 → segment_retake / video_edit / timeline_edit")
print("=" * 74)

# ①-1 单类路由
r = pr.route_problem(_rev(visual_quality=30), {"has_canvas_lineage": True})
check("画面崩坏+有血缘 ⇒ segment_retake",
      r["action"] == pr.ACTION_SEGMENT_RETAKE and r["steps"] == [r["action"]], str(r["action"]))
r = pr.route_problem(_rev(shot_duration=40))
check("时长低分 ⇒ timeline_edit（edit_commands）",
      r["action"] == pr.ACTION_TIMELINE_EDIT, str(r["action"]))
r = pr.route_problem(_rev(narrative_highlight=50, bgm_match=55))
check("节奏+音频双低（同属剪辑类）⇒ 仍 timeline_edit 不混",
      r["action"] == pr.ACTION_TIMELINE_EDIT and r["steps"] == [pr.ACTION_TIMELINE_EDIT],
      str(r["steps"]))

# ①-2 copy_match 细分：字幕错→时间线；画面不符/无标→指令编辑
r = pr.route_problem(_rev(copy_match=30), {"marks": ["subtitle_error"]})
check("文案低+subtitle_error ⇒ timeline_edit",
      r["action"] == pr.ACTION_TIMELINE_EDIT, str(r["action"]))
r = pr.route_problem(_rev(copy_match=30), {"marks": ["frame_mismatch"]})
check("文案低+frame_mismatch ⇒ video_edit",
      r["action"] == pr.ACTION_VIDEO_EDIT, str(r["action"]))
r = pr.route_problem(_rev(copy_match=30))
check("文案低+无细分标 ⇒ video_edit + notes 如实说明",
      r["action"] == pr.ACTION_VIDEO_EDIT and len(r["notes"]) == 1, str(r["notes"]))

# ①-3 无血缘降级：画面问题但没源节点可退回 → 指令编辑 + 标注
r = pr.route_problem(_rev(visual_quality=20), {"has_canvas_lineage": False})
check("画面低分+无血缘 ⇒ 降级 video_edit + notes",
      r["action"] == pr.ACTION_VIDEO_EDIT and any("血缘" in n for n in r["notes"]),
      str(r["notes"]))

# ①-4 混合问题：跨类 ⇒ mixed，steps 按 MIXED_ORDER（先时间线后重拍）
r = pr.route_problem(_rev(visual_quality=30, shot_duration=40),
                    {"has_canvas_lineage": True})
check("画面+时长混合 ⇒ mixed",
      r["action"] == pr.ACTION_MIXED, str(r["action"]))
check("mixed 序列：timeline_edit 在 segment_retake 之前（先便宜后贵）",
      r["steps"] == [pr.ACTION_TIMELINE_EDIT, pr.ACTION_SEGMENT_RETAKE], str(r["steps"]))

# ①-5 兜底：keep / manual
r = pr.route_problem(_rev())
check("全维 ≥60 ⇒ keep 且免确认",
      r["action"] == pr.ACTION_KEEP and r["needs_confirmation"] is False
      and r["confidence"] == 1.0, str(r["action"]))
r = pr.route_problem({"dimensions": {}, "estimated_dims": []})
check("空维度 ⇒ manual（诚实兜底不猜）",
      r["action"] == pr.ACTION_MANUAL and r["confidence"] == 0.0, str(r["action"]))

# ①-6 置信度：实测 > 估算；全估算封顶 0.5；降级/默认再扣 0.10
hi = pr.route_problem(_rev(visual_quality=10), {"has_canvas_lineage": True})
lo = pr.route_problem({"dimensions": dict(_rev()["dimensions"], visual_quality=10),
                       "estimated_dims": list(pr.DIM_CATEGORY)})
check("实测低分置信 > 全估算置信",
      hi["confidence"] > lo["confidence"],
      "%s vs %s" % (hi["confidence"], lo["confidence"]))
check("全估算置信封顶 0.5（不许冒充高置信）", lo["confidence"] <= 0.5,
      str(lo["confidence"]))
dflt = pr.route_problem(_rev(copy_match=30))  # 走默认细分 ⇒ 带 notes
check("带 notes（默认/降级）置信再降", dflt["confidence"] <= 0.9,
      str(dflt["confidence"]))

# ①-7 脏输入一律不抛（前端 JSON 直传的现实形态）
check("脏输入不抛：review=None / 非 dict / 值字符串 / 未知键",
      pr.route_problem(None)["action"] == pr.ACTION_MANUAL
      and pr.route_problem("x")["action"] == pr.ACTION_MANUAL
      and pr.route_problem({"dimensions": {"visual_quality": "abc"}})["action"]
      == pr.ACTION_MANUAL
      and pr.route_problem({"dimensions": {"bogus": 1, "visual_quality": 30}},
                           {"has_canvas_lineage": True})["low_dims"] == ["visual_quality"])
check("features 非 dict ⇒ 按无血缘处理不抛",
      pr.route_problem(_rev(visual_quality=30), "junk")["action"] == pr.ACTION_VIDEO_EDIT)

# ①-8 执行纪律：除 keep 外一律 needs_confirmation=True（「确认后执行」不变）
r = pr.route_problem(_rev(visual_quality=30, copy_match=20),
                     {"has_canvas_lineage": True})
check("任何返工路由都需人工确认", r["needs_confirmation"] is True, str(r["action"]))

# ---------------------------------------------------------------------------
# ② 静态多处同步
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("② 静态：三通道真实存在 + 守卫登记 + 文档回写")
print("=" * 74)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(p):
        return ""
    return io.open(p, encoding="utf-8", errors="replace").read()


check("路由输出通道对应的三模块文件真实存在",
      os.path.isfile(os.path.join(CORE, "segment_retake.py"))
      and os.path.isfile(os.path.join(CORE, "ai", "video_edit_client.py"))
      and os.path.isfile(os.path.join(CORE, "edit_commands.py")))
check("run_all_checks 已登记 ROUTER",
      "check_problem_routing.py" in _read("_verify/run_all_checks.py"))
check("文档已回写（§6.8.5/§6.9 提及 problem_router）",
      "problem_router" in _read("docs/现行技术文档.md"))
# Agent 消费接线（2026-10-17 后续刀）：能力目录行 + dispatcher 登记缺一不可（静默失效防线）
check("Agent 消费接线在册（pipeline.route_problem 目录行 + 注册）",
      "pipeline.route_problem" in _read("app/core/agent_capability_catalog.py")
      and 'dispatcher.register("pipeline.route_problem"'
      in _read("app/core/capability_handlers.py"))
check("维度键与 five_dimension_scorer 五维口径一致",
      set(pr.DIM_CATEGORY) == {"visual_quality", "narrative_highlight",
                               "copy_match", "bgm_match", "shot_duration"})

# ---------------------------------------------------------------------------
# ③ 反例自检（守卫不许是哑弹）
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("③ 反例自检")
print("=" * 74)
check("反例：未知维度 bogus=1 不被判低分（不猜路由）",
      "bogus" not in pr.low_dimensions({"dimensions": {"bogus": 1}}))
check("反例：70 估算基线不触低分线（不误伤素材）",
      pr.low_dimensions({"dimensions": {k: 70 for k in pr.DIM_CATEGORY}}) == [])
check("反例：低分线边界严格 <（60 恰不算低）",
      pr.low_dimensions({"dimensions": {"visual_quality": 60}}) == []
      and pr.low_dimensions({"dimensions": {"visual_quality": 59.9}}) == ["visual_quality"])
mixed = pr.route_problem(_rev(visual_quality=30, shot_duration=40),
                         {"has_canvas_lineage": True})
check("反例：mixed 序列若把重拍排前面即违规",
      mixed["steps"].index(pr.ACTION_TIMELINE_EDIT)
      < mixed["steps"].index(pr.ACTION_SEGMENT_RETAKE))

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
print()
print("=" * 74)
print("ROUTER 汇总：通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("   ❌ %s" % f)
print("=" * 74)
sys.exit(1 if FAIL else 0)
