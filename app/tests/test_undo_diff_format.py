"""app/tests/test_undo_diff_format.py — 撤销栈走 DSL diff（OTIO 真相源迁移·刀6）。

刀6 把撤销 action 内嵌快照从「活体引用/浅拷」升级为「深拷 + 中央盖章（schema=diff-v1）」，
并让 split 还原改走 ``store.set_fields``（按 id 定位，不依赖快照对象身份）。本测试锁死：

  ① **浅拷污染回归** —— split/复制粘贴的快照与活体共享嵌套 effects/keyframes 时，
     后续对任一侧的原地突变会串改撤销快照（代码审查实证缺陷，刀6 用 deepcopy 根治）；
  ② **split 双格式** —— 新格式（带 ``original_clip_id``）走 store 字段写还原；
     旧格式（edit_commands/粗剪仍产出）走原路径**永久兼容**；
  ③ **成员判据** —— 读侧「是否已在真相源」由 dict 全等比较统一换成按 id 的
     ``find_by_id``（深拷快照下全等比较既慢又错）；
  ④ **schema 中央盖章** —— ``_record_action`` 统一盖 ``diff-v1``，不覆盖显式声明。

做法沿用 test_editor_undo_coverage.py：把 **EditorModule 的真实方法绑定到替身对象**
上调用（不测副本、不拉 Qt widget）。
"""
import types

import pytest

EM = pytest.importorskip("app.modules.lego.editor_module")
from app.core.timeline_store import TimelineStore  # noqa: E402


def _bind(obj, *names):
    """把 EditorModule 的真实方法绑到替身上（测真实实现，不复制逻辑）。"""
    for n in names:
        setattr(obj, n, types.MethodType(getattr(EM.EditorModule, n), obj))
    return obj


class _FakeTW:
    """时间线控件最小替身：add_clip 返回 None（不建 widget），其余走空。"""

    def add_clip(self, clip, track):
        return None

    def remove_clip_widget_by_id(self, clip_id):
        return None


class _FakeEditor:
    """最小替身：只提供被绑定的真实方法所依赖的属性与无副作用桩。"""

    def __init__(self, clips=None):
        self._clips = clips if clips is not None else []
        # store adopt 同一 list 对象（与宿主 EditorModule.__init__ 接线一致）
        self._timeline_store = TimelineStore(self._clips)
        self._current_clip = None
        self._active_stickers = []
        self._action_history = []
        self._redo_history = []
        self._project_dirty = False
        self._notices = []
        self._clip_widgets = []
        self._clip_id_to_widget = {}
        self._timeline_widget = _FakeTW()
        for n in ("_sync_timeline_widget_state", "_sync_kernel_timeline",
                  "_refresh_preview_with_effects", "_refresh_preview_to_current_clip",
                  "_touch_project_dirty", "_update_undo_redo_state",
                  "_refresh_sticker_list_ui"):
            setattr(self, n, types.MethodType(lambda self_, *a, **k: None, self))
        self._notify_edit = lambda msg: self._notices.append(msg)
        _bind(self, "_get_history_lock", "_record_action", "_apply_clip_fields",
              "_apply_action", "_apply_action_locked", "_undo", "_redo",
              "_timeline_add_clip_widget", "_timeline_remove_clip_widget",
              "_perform_split_clip", "_copy_clip_data_to_timeline")


def _clip_with_nested(**over):
    """带嵌套可变字段的片段（浅拷污染回归的靶子）。"""
    clip = {
        "id": "c1", "name": "A", "path": "a.mp4", "track": 0,
        "start_time": 0.0, "duration": 4.0, "in_point": 0.0, "out_point": 4.0,
        "effects": {"blur": {"radius": 2}},
        "keyframes": [{"prop": "opacity", "value": 1.0}],
        "transitions": [],
    }
    clip.update(over)
    return clip


# ─────────────── ④ schema 中央盖章 ───────────────

def test_schema_stamped_on_record():
    """_record_action 必须盖 diff-v1 章；显式声明的 schema 不得被覆盖。"""
    ed = _FakeEditor()
    ed._record_action({"type": "edit_clip", "clip_id": "c1"})
    assert ed._action_history[0].get("schema") == "diff-v1"
    ed._record_action({"type": "edit_clip", "clip_id": "c1", "schema": "legacy"})
    assert ed._action_history[1]["schema"] == "legacy"


# ─────────────── ① 浅拷污染回归（split / 复制粘贴） ───────────────

def test_split_snapshot_deepcopy_no_contamination():
    """split 出的新片与原件不得共享嵌套 effects/keyframes（浅拷会串改撤销快照）。"""
    clip = _clip_with_nested()
    ed = _FakeEditor([clip])
    action = ed._perform_split_clip(clip, 2.0)
    assert action is not None
    new_clip = action["new_clip"]
    # 新格式：action 必须带 original_clip_id（读侧按 id 还原的键）
    assert action["original_clip_id"] == "c1"
    # 对快照侧新片的嵌套字段做原地突变 ⇒ 活体原件必须不受影响
    new_clip["effects"]["blur"]["radius"] = 99
    new_clip["keyframes"].append({"prop": "scale", "value": 2.0})
    assert clip["effects"]["blur"]["radius"] == 2
    assert len(clip["keyframes"]) == 1


def test_paste_snapshot_deepcopy():
    """复制粘贴出的片段与源片不得共享嵌套可变字段。"""
    clip = _clip_with_nested()
    ed = _FakeEditor([clip])
    ed._copy_clip_data_to_timeline(clip, offset=1.0)
    action = ed._action_history[-1]
    assert action["type"] == "paste"
    pasted = action["new_clip"]
    pasted["effects"]["blur"]["radius"] = 77
    pasted["keyframes"].append({"prop": "x", "value": 1.0})
    assert clip["effects"]["blur"]["radius"] == 2
    assert len(clip["keyframes"]) == 1


# ─────────────── ② 新格式：快照即新活体 + 按 id 还原 ───────────────

def test_split_new_clip_is_live_identity():
    """action["new_clip"] 必须就是真相源里的活体行（对象同一性保留）。"""
    clip = _clip_with_nested()
    ed = _FakeEditor([clip])
    action = ed._perform_split_clip(clip, 2.0)
    assert ed._timeline_store.find_by_id(action["new_clip"]["id"]) is action["new_clip"]
    assert ed._timeline_store.find_by_id("c1") is clip


def test_split_triple_undo_redo():
    """新格式 split 三连：undo 还原原件时长/出点并移除新片，redo 再切，undo 再还原。"""
    clip = _clip_with_nested()
    ed = _FakeEditor([clip])
    action = ed._perform_split_clip(clip, 2.0)
    ed._record_action(action)
    new_id = action["new_clip"]["id"]
    assert clip["duration"] == 2.0 and clip["out_point"] == 2.0

    ed._undo()
    assert clip["duration"] == 4.0 and clip["out_point"] == 4.0
    assert ed._timeline_store.find_by_id(new_id) is None

    ed._redo()
    assert clip["duration"] == 2.0 and clip["out_point"] == 2.0
    assert ed._timeline_store.find_by_id(new_id) is action["new_clip"]

    ed._undo()
    assert clip["duration"] == 4.0 and clip["out_point"] == 4.0
    assert len(ed._timeline_store.rows()) == 1


# ─────────────── ② 旧格式永久兼容（edit_commands/粗剪产物） ───────────────

def test_old_format_split_undo_redo():
    """无 original_clip_id 的旧 split action：走原路径整段还原，不得报错。"""
    clip = _clip_with_nested()
    ed = _FakeEditor([clip])
    # 手工模拟旧格式：split 已生效（原件被截短），action 不带 original_clip_id
    new_clip = dict(clip)
    new_clip.update({"id": "c1_split_1", "start_time": 2.0, "duration": 2.0,
                     "in_point": 2.0, "out_point": 4.0})
    clip["duration"] = 2.0
    clip["out_point"] = 2.0
    ed._timeline_store.add(new_clip)
    ed._record_action({
        "type": "split", "original_clip": clip, "new_clip": new_clip,
        "original_duration": 4.0, "original_out_point": 4.0,
    })
    ed._undo()
    assert clip["duration"] == 4.0 and clip["out_point"] == 4.0
    assert ed._timeline_store.find_by_id("c1_split_1") is None
    ed._redo()
    assert clip["duration"] == 2.0 and clip["out_point"] == 2.0
    assert ed._timeline_store.find_by_id("c1_split_1") is new_clip


def test_rough_cut_compound_rollback():
    """粗剪式 compound（旧格式 split + edit_clip 混装）一条撤销整包回滚。"""
    clip = _clip_with_nested()
    ed = _FakeEditor([clip])
    new_clip = dict(clip)
    new_clip.update({"id": "c1_split_1", "start_time": 2.0, "duration": 2.0,
                     "in_point": 2.0, "out_point": 4.0})
    clip["duration"] = 2.0
    clip["out_point"] = 2.0
    ed._timeline_store.add(new_clip)
    steps = [
        {"type": "split", "original_clip": clip, "new_clip": new_clip,
         "original_duration": 4.0, "original_out_point": 4.0},
        {"type": "edit_clip", "clip_id": "c1",
         "before": {"volume": 0.4}, "after": {"volume": 1.0}},
    ]
    clip["volume"] = 1.0
    ed._record_action({"type": "compound", "steps": steps, "label": "rough_cut"})
    ed._undo()
    assert clip["duration"] == 4.0 and clip["out_point"] == 4.0
    assert clip["volume"] == 0.4
    assert ed._timeline_store.find_by_id("c1_split_1") is None
    ed._redo()
    assert clip["duration"] == 2.0 and clip["volume"] == 1.0
    assert ed._timeline_store.find_by_id("c1_split_1") is new_clip


# ─────────────── ③ 成员判据 find_by_id（禁 dict 全等比较） ───────────────

def test_membership_uses_find_by_id():
    """undo delete：真相源已有同 id 行（内容已被后续编辑改动）时不得重复插入。"""
    live = {"id": "a", "duration": 5.0}          # 快照之后又被改过的活体行
    snapshot = {"id": "a", "duration": 3.0}      # 撤销栈里的深拷快照（内容不等）
    ed = _FakeEditor([live])
    ed._apply_action({"type": "delete", "clip": snapshot, "ripple_shifts": []},
                     mode="undo")
    assert len(ed._clips) == 1                   # 按 id 判成员：已在场 ⇒ 不再 add
    assert ed._clips[0] is live

    # 正常场景：真相源无该 id ⇒ 快照回灌为活体
    ed2 = _FakeEditor([])
    ed2._apply_action({"type": "delete", "clip": snapshot, "ripple_shifts": []},
                      mode="undo")
    assert len(ed2._clips) == 1 and ed2._clips[0] is snapshot
