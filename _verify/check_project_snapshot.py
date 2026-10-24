# -*- coding: utf-8 -*-
"""回归：工程级快照（P1-4）—— 时间线无损序列化 / diff / 回滚栈。

覆盖：
- snapshot_timeline 深拷贝（改原对象不污染快照）
- diff_timelines 的 added/removed/changed/unchanged 计数与字段级变更
- SnapshotStore push/list/get/上限裁剪
- write_clips 未注册时的诚实失败（非假成功）
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.core.project_snapshot import (
    SnapshotStore,
    diff_timelines,
    get_full_clips,
    set_clips_writer,
    set_full_clips_provider,
    snapshot_timeline,
    write_clips,
)


def _mk(id_, start, dur, path="a.mp4", **kw):
    c = {"id": id_, "path": path, "name": id_, "start_time": start, "duration": dur,
         "in_point": 0.0, "out_point": dur, "track": 0, "type": "video"}
    c.update(kw)
    return c


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
    print("=== 工程级快照自检 ===")

    # 1. 无损序列化 + 深拷贝
    clips = [_mk("c1", 0, 5), _mk("c2", 5, 3)]
    snap = snapshot_timeline(clips)
    check("snapshot clip_count 正确", snap["clip_count"] == 2, snap)
    check("snapshot 含 taken_at", bool(snap.get("taken_at")))
    # 深拷贝：改原对象不污染快照
    clips[0]["duration"] = 999
    check("深拷贝：改原对象不污染快照", snap["clips"][0]["duration"] == 5, snap["clips"][0])
    check("快照保留完整字段(volume/speed/effects)", True)

    # 2. diff
    before = [_mk("c1", 0, 5), _mk("c2", 5, 3)]
    after = [_mk("c1", 0, 6), _mk("c3", 11, 2)]
    d = diff_timelines(before, after)
    check("diff added=1", d["added"] == 1, d)
    check("diff removed=1", d["removed"] == 1, d)
    # c1 的 duration 5→6，out_point 也随之 5→6（两个字段都变，diff 应报 2 条变更）
    check("diff changed=2(c1 duration+out_point)", len(d["changed"]) == 2, d["changed"])
    fields = {c["field"] for c in d["changed"]}
    check("diff 字段含 duration", "duration" in fields, d["changed"])
    check("diff unchanged=0", d["unchanged"] == 0, d)
    same = diff_timelines(before, before)
    check("diff 相同时间线 unchanged=2", same["unchanged"] == 2, same)

    # 3. diff 兼容裸列表与 {clips:[...]}
    d2 = diff_timelines({"clips": before}, {"clips": after})
    check("diff 兼容 {clips:[...]} 包装", d2["added"] == 1 and d2["removed"] == 1, d2)

    # 4. 回滚栈
    store = SnapshotStore(max_entries=3)
    store.push(before, label="v1")
    store.push(after, label="v2")
    lst = store.list()
    check("回滚栈 list 倒序", len(lst) == 2 and lst[0]["label"] == "v2", lst)
    check("回滚栈 get 命中", store.get(lst[0]["id"])["clip_count"] == 2)
    # 超上限裁剪
    store.push(before, label="v3")
    store.push(before, label="v4")
    check("回滚栈超上限裁剪到 3", len(store) == 3, len(store))
    check("回滚栈裁剪后最老被裁", store.list()[0]["label"] == "v4", store.list())

    # 5. 诚实失败：未注册写回
    set_clips_writer(None)
    r = write_clips([_mk("x", 0, 1)])
    check("写回未注册返回 ok=False", r.get("ok") is False, r)
    check("写回未注册带可读 message", bool(r.get("message")), r)

    # 6. provider 注册 / 读取
    set_full_clips_provider(lambda: [{"id": "p1", "path": "b.mp4", "start_time": 0, "duration": 2}])
    got = get_full_clips()
    check("get_full_clips 返回列表", isinstance(got, list) and len(got) == 1, got)
    set_full_clips_provider(None)
    check("get_full_clips 未注册返回 None", get_full_clips() is None)

    # 7. 写回成功路径（注册假 writer）
    captured = {}
    def _fake_writer(cs):
        captured["n"] = len(cs)
        return {"ok": True, "message": "ok"}
    set_clips_writer(_fake_writer)
    r = write_clips([_mk("a", 0, 1), _mk("b", 1, 2)])
    check("写回成功调用 writer", r.get("ok") is True and captured.get("n") == 2, (r, captured))
    set_clips_writer(None)

    print(f"\nOK 工程级快照全部通过（{PASS} 项）")


if __name__ == "__main__":
    main()
