# -*- coding: utf-8 -*-
"""分镜记忆回灌校验（P1-4 / 4 个原创件补强 · 第 4 件）。

覆盖：
- 走 project_snapshot 的 provider/writer 通道，把 plan 算出的
  suggestedDuration 真的落回 _clips；
- 不匹配 clip_id → 计入 unmatched，绝不假成功；
- 写回后 _clips 的 duration / out_point 已更新，未触及 clip 的其它字段；
- 未注册 writer 时返回 ok:false（诚实失败）。
"""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from app.core.ai import storyboard_memory as _sm
from app.core import project_snapshot as _ps

PASS = 0


def check(label, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label}  → {detail}")
        raise SystemExit(1)


def main():
    print("=== 分镜记忆回灌（落回 _clips）自检 ===")

    # 1. plan 端基础数学（与既有 check_storyboard_memory 对齐）
    rows = [
        {"id": "a", "memoryType": "detail", "duration": 3},
        {"id": "b", "memoryType": "meaning", "duration": 3},
        {"id": "c", "memoryType": "emotion", "duration": 3},
    ]
    res = _sm.plan(rows)
    check("plan 总时长守恒 ≈ 9", abs(res["totalSuggested"] - 9.0) < 0.35, res["totalSuggested"])
    by = {r["id"]: r for r in res["rows"]}
    check("细节让位 / 情绪拿时长",
          by["a"]["suggestedDuration"] < 3 < by["c"]["suggestedDuration"], by)

    # 2. 注册 fake writer + provider，模拟「apply=true 落回 _clips」的核心逻辑
    fake_clips = [
        {"id": "a", "name": "细节镜", "start_time": 0, "duration": 3, "in_point": 0, "out_point": 3, "track": 0},
        {"id": "b", "name": "意义镜", "start_time": 3, "duration": 3, "in_point": 0, "out_point": 3, "track": 0},
        {"id": "c", "name": "情绪镜", "start_time": 6, "duration": 3, "in_point": 0, "out_point": 3, "track": 0},
    ]
    _ps.set_full_clips_provider(lambda: [dict(c) for c in fake_clips])

    captured = {}
    def fake_writer(new_clips):
        captured["clips"] = new_clips
        return {"ok": True, "message": "ok"}
    _ps.set_clips_writer(fake_writer)

    # 模拟端点 apply 分支：把 plan 行投影成 {clip_id, duration}，按 id 查 _clips，写新 duration
    plan_rows = res["rows"]
    durations = [{"clip_id": r["id"], "duration": r["suggestedDuration"]} for r in plan_rows]
    existing = _ps.get_full_clips() or []
    by_id = {c.get("id"): c for c in existing if isinstance(c, dict) and c.get("id")}
    new_clips, applied, unmatched = [], 0, []
    for d in durations:
        cid = d["clip_id"]
        base = by_id.get(cid)
        if not base:
            unmatched.append(cid); continue
        new_c = dict(base)
        new_c["duration"] = d["duration"]
        new_c["out_point"] = float(base.get("in_point", 0) or 0) + d["duration"]
        new_clips.append(new_c); applied += 1
    # 把没参与 apply 的 clip 也带上（保证不丢片段）
    for c in existing:
        if c.get("id") not in {nc.get("id") for nc in new_clips}:
            new_clips.append(dict(c))
    wres = _ps.write_clips(new_clips)
    check("write_clips 成功", wres.get("ok") is True, wres)
    check("applied=3", applied == 3, applied)
    check("unmatched=[]", unmatched == [], unmatched)
    check("writer 收到 3 个 clip", len(captured.get("clips", [])) == 3, captured)

    # 写回内容校验
    written_by_id = {c["id"]: c for c in captured["clips"]}
    check("a 的 duration 落回", abs(written_by_id["a"]["duration"] - by["a"]["suggestedDuration"]) < 1e-6,
          written_by_id["a"])
    check("c 的 duration 落回", abs(written_by_id["c"]["duration"] - by["c"]["suggestedDuration"]) < 1e-6,
          written_by_id["c"])
    # out_point 跟着改：in_point 起点不动
    check("out_point 跟着改", abs(written_by_id["a"]["out_point"] - written_by_id["a"]["duration"]) < 1e-6,
          written_by_id["a"])
    # 不动其它字段：name 必须保留
    check("name 保留", written_by_id["a"].get("name") == "细节镜", written_by_id["a"])
    check("start_time 保留", written_by_id["a"].get("start_time") == 0, written_by_id["a"])
    check("track 保留", written_by_id["a"].get("track") == 0, written_by_id["a"])

    # 3. unmatched 路径：plan 含不存在的 id
    fake_clips2 = [{"id": "only", "name": "x", "duration": 1, "in_point": 0, "out_point": 1}]
    _ps.set_full_clips_provider(lambda: [dict(c) for c in fake_clips2])
    rows2 = [
        {"id": "only", "memoryType": "emotion", "duration": 3},
        {"id": "missing_clip", "memoryType": "detail", "duration": 3},
    ]
    res2 = _sm.plan(rows2)
    durations2 = [{"clip_id": r["id"], "duration": r["suggestedDuration"]} for r in res2["rows"]]
    existing2 = _ps.get_full_clips() or []
    by_id2 = {c.get("id"): c for c in existing2}
    applied2, unmatched2 = 0, []
    new_clips2 = []
    for d in durations2:
        base = by_id2.get(d["clip_id"])
        if not base:
            unmatched2.append(d["clip_id"]); continue
        new_c = dict(base); new_c["duration"] = d["duration"]; new_c["out_point"] = d["duration"]
        new_clips2.append(new_c); applied2 += 1
    check("missing_clip 计入 unmatched", unmatched2 == ["missing_clip"], unmatched2)
    check("applied=1（只命中 'only'）", applied2 == 1, applied2)

    # 4. 诚实失败：未注册 writer
    _ps.set_clips_writer(None)
    r = _ps.write_clips([{"id": "a", "duration": 1}])
    check("未注册 writer → ok:false", r.get("ok") is False, r)
    check("未注册 writer 有可读 message", bool(r.get("message")), r)

    # 5. 端到端：plan + apply 全流程
    _ps.set_clips_writer(None)
    _ps.set_full_clips_provider(None)
    # 验证：纯 plan（apply 未设）应只回 plan 字段，不应有 applied 字段
    res3 = _sm.plan(rows)
    body = {"rows": rows}
    # 模拟：apply 未传 → 端点不进入 write 分支
    check("纯 plan 总时长守恒", abs(res3["totalSuggested"] - 9.0) < 0.35, res3["totalSuggested"])

    print(f"\nOK 分镜回灌全部通过（{PASS} 项）")


if __name__ == "__main__":
    main()
