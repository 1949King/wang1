# -*- coding: utf-8 -*-
"""入轨治理闸门守卫（刀3 / E2 · 2026-10-23）

治理缺口（设计文档 §7.4「无闸门」）：分数算出来了，但**没有任何地方因为
分数低而拒绝**——`aesthetic_gate.evaluate_gate` 完整却零生产调用方。

本刀把它接进入轨链路，但必须绕开三个陷阱（均为刀3 实测发现）：

  A. **误拦用户素材**：`evaluate_gate` 对无分数返回 `block(missing_scores)`；
     `_add_clip_to_timeline` 有 13 个调用方，含用户手动导入 ⇒ 若直接接，
     **用户导入的每个视频都会被拦**。故入轨语境必须「无分数 ⇒ 不判定」。
  B. **落点错位**：`_add_clip_to_timeline(file_path)` 只收路径、拿不到分数，
     在那里做闸门是空转（本项目明令反对「注册了但看不见」的空接线）。
     正确落点是 `agent_replace_timeline_clips(clips)`——收 clip dict 列表。
  C. **force 静默放行**：要放行必须留痕，不能假装判定通过了。

断言：
  ① 语境区分：无分数 ⇒ pass 且 `scored=False`、理由含「不判定」（绝不 block）
  ② 硬闸门：有分数且 D 级 ⇒ block，且带原因（不静默）
  ③ 复核区间：C 级 ⇒ review（进但标人工确认）
  ④ force 留痕：block + force ⇒ review + `forced=True` + `forced_by_caller`
  ⑤ 批量硬闸：任一 block ⇒ 整批 block；未评分素材如实报数（非 0 假装）
  ⑥ 接线在册：`agent_replace_timeline_clips` 有 `enforce_gate` 参数、
     闸门在 `clear()` **之前**、`enforce_gate=False` 时零判定
  ⑦ 辅助方法在 mixin（宿主受体积守卫，判定薄壳须外置）
  ⑧ 治理单一来源：闸门不得复制 evaluate_gate 的阈值/权重逻辑

用法（项目根执行）：python _verify/check_ingest_gate.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GATE_REL = "app/core/ingest_gate.py"
EDITOR_REL = "app/modules/lego/editor_module.py"
MIXIN_REL = "app/modules/lego/editor_ai_process_mixin.py"

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def _scored(score: float, grade: str = ""):
    return {"clip_id": "c", "weighted_score": score, "grade": grade,
            "dimensions": {"visual_quality": score, "narrative_highlight": score,
                           "copy_match": score, "bgm_match": score,
                           "shot_duration": score}}


# ── ① 语境区分：这是本刀最重要的断言 ─────────────────────────────────

def check_unscored_is_not_blocked() -> None:
    from app.core.ingest_gate import decide

    for item, label in (
        ({"clip_id": "u", "path": "/movies/mine.mp4"}, "用户导入（仅路径）"),
        ({"clip_id": "u", "dimensions": {}}, "空 dimensions"),
        ({"clip_id": "u", "weighted_score": "85"}, "字符串分数（不可判定）"),
        ({"clip_id": "u", "weighted_score": True}, "bool 分数（不可判定）"),
    ):
        out = decide(item)
        if out["decision"] == "block":
            _fail(f"① {label} 被拦（会误拦用户素材——本刀头号风险）")
        if out["decision"] != "pass":
            _fail(f"① {label} 未放行：{out['decision']}")
        if out["scored"] is not False:
            _fail(f"① {label} 被标记成「已评分」（把没测说成测了）")
        if "不判定" not in out["reason"]:
            _fail(f"① {label} 理由未说明「不判定」：{out['reason']!r}")


# ── ②③ 硬闸门与复核区间 ──────────────────────────────────────────────

def check_hard_gate() -> None:
    from app.core.ingest_gate import decide

    d = decide(_scored(45, "D"))
    if d["decision"] != "block":
        _fail(f"② D 级未被拦：{d['decision']}（闸门等于没有）")
    if not d.get("reasons"):
        _fail("② D 级拦截未带原因（静默丢弃）")
    if d.get("scored") is not True:
        _fail("② 有分数的素材未标记 scored=True")

    c = decide(_scored(65, "C"))
    if c["decision"] != "review":
        _fail(f"③ C 级应为 review，实测 {c['decision']}")

    a = decide(_scored(88, "A"))
    if a["decision"] != "pass":
        _fail(f"③ A 级应为 pass，实测 {a['decision']}")

    # 只给分数不给 grade 也必须能判
    bare = decide({"clip_id": "c", "weighted_score": 30})
    if bare["decision"] != "block":
        _fail("② 只给 weighted_score（无 grade）时未拦住低分")


# ── ④ force 留痕 ──────────────────────────────────────────────────────

def check_force_leaves_trace() -> None:
    from app.core.ingest_gate import decide

    out = decide(_scored(45, "D"), force=True)
    if out["decision"] == "pass":
        _fail("④ force 直接 PASS 了（应降为 review 要求人工确认）")
    if out["decision"] != "review":
        _fail(f"④ force 后应为 review，实测 {out['decision']}")
    if out.get("forced") is not True:
        _fail("④ force 未标记 forced=True（放行不可追溯）")
    if "forced_by_caller" not in (out.get("reasons") or []):
        _fail("④ force 未在 reasons 留痕")

    # force 不该把「没测」变成「测过」
    unscored_force = decide({"clip_id": "u"}, force=True)
    if unscored_force.get("scored") is not False:
        _fail("④ force 把未评分素材标记成已评分（事实被篡改）")


# ── ⑤ 批量硬闸 ────────────────────────────────────────────────────────

def check_batch_semantics() -> None:
    from app.core.ingest_gate import decide_batch

    mixed = decide_batch([_scored(88, "A"), _scored(45, "D")])
    if mixed["verdict"] != "block":
        _fail(f"⑤ 混入 D 级的批次未整批拒绝：{mixed['verdict']}")
    if len(mixed["blocked"]) != 1:
        _fail(f"⑤ 被拦条目数不对：{len(mixed['blocked'])}")

    review_only = decide_batch([_scored(88, "A"), _scored(65, "C")])
    if review_only["verdict"] != "review":
        _fail(f"⑤ 仅 C 级时不该 block：{review_only['verdict']}")

    all_unscored = decide_batch([{"id": "a"}, {"id": "b"}])
    if all_unscored["verdict"] != "pass":
        _fail("⑤ 全未评分批次被拦（误拦用户素材）")
    if all_unscored["unscored_count"] != 2:
        _fail(f"⑤ 未评分数未如实报：{all_unscored['unscored_count']}")

    if decide_batch([])["verdict"] != "pass":
        _fail("⑤ 空批次应为 pass")


# ── ⑥ 接线在册 ────────────────────────────────────────────────────────

def check_wiring() -> None:
    from app.modules.lego.editor_module import EditorModule

    fn = getattr(EditorModule, "agent_replace_timeline_clips", None)
    if fn is None:
        _fail("⑥ 找不到 agent_replace_timeline_clips")
        return
    params = inspect.signature(fn).parameters
    if "enforce_gate" not in params:
        _fail("⑥ 写入口未接受 enforce_gate（闸门未接入）")
    elif params["enforce_gate"].default is not True:
        _fail("⑥ enforce_gate 缺省不是 True（默认应受治理）")

    src = _read(EDITOR_REL)
    start = src.find("def agent_replace_timeline_clips")
    end = src.find("def agent_apply_storyboard_durations", start)
    body = src[start:end] if end > start else ""
    if "_gate_before_ingest" not in body:
        _fail("⑥ 写入口未调用闸门（空接线）")
    idx_gate = body.find("_gate_before_ingest")
    idx_clear = body.find("self._timeline_store.clear()")
    if idx_clear < 0:
        _fail("⑥ 找不到 clear()（结构变了？需同步本守卫）")
    elif idx_gate > idx_clear:
        _fail("⑥ 闸门在 clear() 之后（先清空再判定 = 时间线已被破坏才拒绝）")

    # 宿主受体积守卫：判定薄壳必须在 mixin。
    # 判据是「**定义**是否写进宿主」而不是「名字是否出现」——调用点必然
    # 出现该名字（本守卫首跑即因此误报）。
    if "def _gate_before_ingest" in src:
        _fail("⑥ 闸门实现写进了 editor_module（受体积守卫，须外置到 mixin）")
    mixin = _read(MIXIN_REL)
    if "def _gate_before_ingest" not in mixin:
        _fail("⑥ mixin 里找不到 _gate_before_ingest 实现")


# ── ⑦ 缺省不判定路径（enforce_gate=False 零行为变化）──────────────────

def check_disable_switch() -> None:
    mixin = _read(MIXIN_REL)
    start = mixin.find("def _gate_before_ingest")
    end = mixin.find("def ", start + 10)
    body = mixin[start:end] if end > start else mixin[start:]
    if "if not enforce:" not in body:
        _fail("⑦ 闸门缺 enforce 开关（既有调用方无法回到零判定）")
    if "return None" not in body:
        _fail("⑦ 闸门通过路径未返回 None（宿主无法区分「放行」与「拒绝」）")
    # 治理模块缺失时必须诚实降级而不是炸入轨
    if "except ImportError" not in body:
        _fail("⑦ 闸门无 ImportError 兜底（治理模块缺失会炸掉入轨链路）")


# ── ⑧ 治理单一来源 ────────────────────────────────────────────────────

def check_single_source() -> None:
    src = _read(GATE_REL)
    for token in ("min_weighted_score", "block_grades", "GRADE_THRESHOLDS",
                  "WEIGHTS = {"):
        if token in src:
            _fail(f"⑧ 闸门复制了评分阈值/权重 `{token}`（应委托 aesthetic_gate）")
    if "evaluate_gate" not in src:
        _fail("⑧ 闸门未委托 evaluate_gate（治理判定出现第二套实现）")


def main() -> int:
    check_unscored_is_not_blocked()
    check_hard_gate()
    check_force_leaves_trace()
    check_batch_semantics()
    check_wiring()
    check_disable_switch()
    check_single_source()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  入轨治理闸门：无分数不拦(防误拦用户素材)/D级硬拦/C级复核/force留痕/"
          "批量硬闸/接线在册(clear前)/开关可用/治理单一来源")
    return 0


if __name__ == "__main__":
    sys.exit(main())
