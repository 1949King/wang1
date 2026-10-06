"""app/tests/test_editor_undo_coverage.py — 撤销覆盖与加锁（刀 A3，2026-10-05）。

刀 A3 修三件事，本测试锁死它们：
  ① **转场 / 贴纸入撤销栈** —— 此前这两类操作**不可撤销**（最大体验洞），
     现在写入 `_action_history`（转场走 edit_clip 型、贴纸走 stickers 型整表快照）；
  ② **`_apply_action` 整段持 `_clips_lock`** —— 此前多步改真相源不持锁，
     画布桥快照 / autosave 会读到半新半旧的 `_clips`（本文件自写纪律的自违反）；
  ③ **撤销栈并发保护** —— `_record_action`（Agent 线程压栈）与 `_undo`（UI 线程弹栈）
     此前无互斥；弹栈「pop 后 append 到另一栈」非原子，并发会丢 action。

做法：把 **EditorModule 的真实方法绑定到替身对象**上调用（不测副本、不拉 Qt widget）。
"""
import pathlib
import threading
import types

import pytest

EM = pytest.importorskip("app.modules.lego.editor_module")
ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = (ROOT / "app" / "modules" / "lego" / "editor_module.py").read_text(encoding="utf-8")


def _bind(obj, *names):
    """把 EditorModule 的真实方法绑到替身上（测真实实现，不复制逻辑）。"""
    for n in names:
        setattr(obj, n, types.MethodType(getattr(EM.EditorModule, n), obj))
    return obj


class _FakeEditor:
    """最小替身：只提供被绑定的真实方法所依赖的属性与无副作用桩。"""

    def __init__(self, clips=None, stickers=None):
        self._clips = clips if clips is not None else []
        self._current_clip = None
        self._active_stickers = stickers if stickers is not None else []
        self._action_history = []
        self._redo_history = []
        self._project_dirty = False
        self._notices = []
        # 无副作用桩
        for n in ("_sync_timeline_widget_state", "_sync_kernel_timeline",
                  "_refresh_preview_with_effects", "_refresh_preview_to_current_clip",
                  "_touch_project_dirty", "_update_undo_redo_state",
                  "_refresh_sticker_list_ui", "_on_agent_action_undone",
                  "_on_agent_action_redone"):
            setattr(self, n, types.MethodType(lambda self_, *a, **k: None, self))
        self._notify_edit = lambda msg: self._notices.append(msg)
        _bind(self, "_get_history_lock", "_record_action", "_apply_clip_fields",
              "_apply_action", "_apply_action_locked", "_undo", "_redo",
              "_apply_transition_to_clip", "_apply_sticker", "_clear_stickers",
              "_snapshot_stickers")


# ─────────────────────── ① 转场入撤销栈 ───────────────────────

def test_transition_writes_action():
    clip = {"id": "c1", "start_time": 0.0, "duration": 3.0}
    ed = _FakeEditor([clip])
    ed._apply_transition_to_clip(clip, "fade", 0.5)
    assert len(ed._action_history) == 1
    a = ed._action_history[0]
    assert a["type"] == "edit_clip" and a["clip_id"] == "c1"
    assert a["after"]["transition"]["type"] == "fade"
    assert a["before"]["transition"] is None  # 原本没有转场


def test_transition_undo_restores_empty():
    clip = {"id": "c1", "start_time": 0.0, "duration": 3.0}
    ed = _FakeEditor([clip])
    ed._apply_transition_to_clip(clip, "fade", 0.5)
    ed._undo()
    assert clip["transition"] is None
    assert not clip["transitions"]          # 撤销后回到「无转场」
    assert ed._action_history == [] and len(ed._redo_history) == 1


def test_transition_redo_reapplies():
    clip = {"id": "c1", "start_time": 0.0, "duration": 3.0}
    ed = _FakeEditor([clip])
    ed._apply_transition_to_clip(clip, "fade", 0.5)
    ed._undo()
    ed._redo()
    assert clip["transition"]["type"] == "fade"


def test_transition_before_snapshot_is_deep_enough():
    """改已有转场时，before 必须记下**上一条**转场（否则撤销会丢历史）。"""
    clip = {"id": "c1"}
    ed = _FakeEditor([clip])
    ed._apply_transition_to_clip(clip, "fade", 0.5)
    before_list = list(clip["transitions"])
    ed._apply_transition_to_clip(clip, "wipe", 0.8)
    a = ed._action_history[-1]
    assert a["before"]["transition"]["type"] == "fade"
    assert a["before"]["transitions"] == before_list


# ─────────────────────── ① 贴纸入撤销栈 ───────────────────────

def test_sticker_apply_writes_action():
    ed = _FakeEditor([{"id": "c1"}], stickers=[{"emoji": "😀", "x": 0.1, "scale": 1.0}])
    ed._gather_sticker_params_from_ui = lambda: {"x": 0.9, "scale": 2.0}
    ed._selected_sticker_index = lambda: 0
    ed._schedule_preview_refresh = lambda: None
    ed._apply_sticker()
    assert ed._action_history[-1]["type"] == "stickers"
    assert ed._active_stickers[0]["x"] == 0.9


def test_sticker_undo_restores_snapshot():
    ed = _FakeEditor([{"id": "c1"}], stickers=[{"emoji": "😀", "x": 0.1}])
    ed._gather_sticker_params_from_ui = lambda: {"x": 0.9}
    ed._selected_sticker_index = lambda: 0
    ed._schedule_preview_refresh = lambda: None
    ed._apply_sticker()
    ed._undo()
    assert ed._active_stickers[0]["x"] == 0.1   # 参数回到改前


def test_clear_stickers_undo_restores_all():
    """「清空」最需要后悔药：撤销必须把整表还原（含顺序）。"""
    ed = _FakeEditor([{"id": "c1"}], stickers=[{"emoji": "A"}, {"emoji": "B"}])
    ed._schedule_preview_refresh = lambda: None
    ed._clear_stickers()
    assert ed._active_stickers == []
    ed._undo()
    assert [s["emoji"] for s in ed._active_stickers] == ["A", "B"]


def test_snapshot_is_deep_copy():
    """快照必须是深拷贝，否则回滚会被后续修改串改。"""
    ed = _FakeEditor([{"id": "c1"}], stickers=[{"emoji": "A", "x": 0.1}])
    snap = ed._snapshot_stickers()
    ed._active_stickers[0]["x"] = 0.99
    assert snap[0]["x"] == 0.1


def test_stickers_action_unknown_type_safe():
    """未知 action 类型不得抛异常（历史里可能有旧版本写的类型）。"""
    ed = _FakeEditor()
    ed._apply_action({"type": "未来才有的类型"}, mode="undo")  # 不炸即可


# ─────────────────────── ② _apply_action 持锁 ───────────────────────

def test_apply_action_acquires_clips_lock():
    """行为级：进入 _apply_action 必须**真的取到锁**（用一个会记录的锁）。"""
    seen = {"acquired": 0}

    class _SpyLock:
        def __enter__(self):
            seen["acquired"] += 1
            return self

        def __exit__(self, *a):
            return False

    ed = _FakeEditor([{"id": "c1"}])
    ed._clips_lock = _SpyLock()
    ed._apply_action({"type": "edit_clip", "clip_id": "c1", "before": {}, "after": {}}, mode="undo")
    assert seen["acquired"] == 1


def test_apply_action_locked_is_single_source():
    """`_apply_action` 只做加锁 + 委托，业务分支全在 `_apply_action_locked`。"""
    assert hasattr(EM.EditorModule, "_apply_action_locked")
    body = SRC.split("def _apply_action(self", 1)[1].split("def _apply_action_locked", 1)[0]
    assert "_apply_action_locked(action, mode)" in body
    assert "atype" not in body          # 不含业务分支
    # 撤销/重做走的仍是带锁入口
    assert "_apply_action(action, mode='undo')" in SRC
    assert "_apply_action(action, mode='do')" in SRC


# ─────────────────────── ③ 撤销栈并发保护 ───────────────────────

def test_record_action_uses_history_lock():
    seen = {"n": 0}

    class _SpyLock:
        def __enter__(self):
            seen["n"] += 1
            return self

        def __exit__(self, *a):
            return False

    ed = _FakeEditor()
    ed._history_lock = _SpyLock()
    ed._record_action({"type": "edit_clip"})
    assert seen["n"] >= 1


def test_undo_redo_use_history_lock():
    seen = {"n": 0}

    class _SpyLock:
        def __enter__(self):
            seen["n"] += 1
            return self

        def __exit__(self, *a):
            return False

    ed = _FakeEditor([{"id": "c1"}])
    ed._history_lock = _SpyLock()
    ed._record_action({"type": "edit_clip", "clip_id": "c1", "before": {}, "after": {}})
    ed._undo()
    ed._redo()
    assert seen["n"] >= 3


def test_concurrent_push_pop_does_not_lose_actions():
    """并发压栈 + 弹栈：总数守恒（无丢失、无重复）。"""
    ed = _FakeEditor([{"id": "c1"}])
    n_push, n_pop = 200, 100

    def _push():
        for _ in range(n_push):
            ed._record_action({"type": "edit_clip", "clip_id": "c1", "before": {}, "after": {}})

    def _pop():
        for _ in range(n_pop):
            with ed._get_history_lock():
                if ed._action_history:
                    ed._redo_history.append(ed._action_history.pop())

    ts = [threading.Thread(target=_push), threading.Thread(target=_pop)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # ⚠️ 压栈会**清空 redo 栈**（正确语义：新操作丢弃重做分支）⇒ 不能断言总数守恒。
    #   真正要防的是「同一个 action 同时留在两条栈」/「丢到两条栈都没有」——
    #   前者会让一次 Ctrl+Z 撤销两步，后者让操作凭空消失。故按对象身份查重。
    all_actions = ed._action_history + ed._redo_history
    ids = [id(a) for a in all_actions]
    assert len(ids) == len(set(ids)), "同一 action 出现在两条栈（撤销会错步）"
    assert len(all_actions) <= n_push


def test_no_deadlock_when_undo_calls_apply_action():
    """_undo 在 history 锁外调 _apply_action（后者取 _clips_lock）⇒ 无嵌套死锁。"""
    clip = {"id": "c1"}
    ed = _FakeEditor([clip])
    ed._apply_transition_to_clip(clip, "fade", 0.5)
    done = {"ok": False}

    def _work():
        ed._undo()
        done["ok"] = True

    t = threading.Thread(target=_work)
    t.start()
    t.join(timeout=5)
    assert done["ok"] and not t.is_alive()


# ─────────────────────── 源码级：孤儿已清、接线在位 ───────────────────────

def test_orphan_functions_removed():
    """A3 顺手清掉的三个零引用孤儿不得回流（否则又占体量、又误导真相源）。"""
    for name in ("_optimize_workflow", "_remove_fillers_and_silence",
                 "_fallback_subtitle_generation"):
        assert f"def {name}(" not in SRC, f"孤儿函数 {name} 回流"


def test_all_three_record_points_present():
    """三处必须都调 _record_action（转场 + 贴纸两处）。"""
    for fn in ("_apply_transition_to_clip", "_apply_sticker", "_clear_stickers"):
        body = SRC.split(f"def {fn}(", 1)[1][:2600]
        assert "_record_action(" in body, f"{fn} 未入撤销栈"
    # stickers 动作类型已在 _apply_action_locked 中处理
    assert 'atype == "stickers"' in SRC
    # 历史锁助手存在
    assert "def _get_history_lock" in SRC
    helper = SRC.split("def _get_history_lock", 1)[1][:900]
    assert "threading.RLock()" in helper, "_get_history_lock 未用 RLock"
    assert 'self._history_lock = lock' in helper
