# -*- coding: utf-8 -*-
"""TimelineStore 乐观并发（revision / CAS）回归测试（刀1 · 2026-10-23）。

对照 FableCut 的治理模型：一个粗粒度 revision 管全部写冲突，
陈旧写入被拒绝而非静默覆盖（对应其 HTTP 409）。

本文件只测 store 层语义，不依赖 Qt / EditorModule：
    * `revision()` 初值 0；结构/字段写成功后单调 +1
    * **无真实改动不 bump**（未命中的 remove/set_fields、空 clear）
    * `base_revision` 不匹配 ⇒ `RevisionConflict` 且**一个字节都不写**
    * `base_revision=None` ⇒ 保持历史行为（不校验）
    * 非法类型 ⇒ TypeError（不猜）
    * 冲突对象带 expected/actual/op，供上层转 409
"""
import pytest

from app.core.timeline_store import RevisionConflict, TimelineStore


def _clip(cid, **kw):
    base = {"id": cid, "path": f"/tmp/{cid}.mp4", "start_time": 0.0,
            "in_point": 0.0, "duration": 1.0, "track": 0, "type": "video"}
    base.update(kw)
    return base


@pytest.fixture()
def store():
    return TimelineStore([])


# ── 基础语义 ──────────────────────────────────────────────────────────

def test_initial_revision_is_zero(store):
    assert store.revision() == 0


def test_add_bumps_revision(store):
    store.add(_clip("a"))
    assert store.revision() == 1
    store.add(_clip("b"))
    assert store.revision() == 2


def test_remove_hit_bumps_miss_does_not(store):
    store.add(_clip("a"))
    before = store.revision()
    assert store.remove_by_id("a") == 1
    assert store.revision() == before + 1
    # 未命中：没有真实改动，不该让别人的 revision 失效
    miss_before = store.revision()
    assert store.remove_by_id("nope") == 0
    assert store.revision() == miss_before


def test_replace_all_and_clear_bump(store):
    store.add(_clip("a"))
    store.replace_all([_clip("x"), _clip("y")])
    after_replace = store.revision()
    assert after_replace >= 2
    store.clear()
    assert store.revision() == after_replace + 1


def test_clear_on_empty_does_not_bump(store):
    assert store.revision() == 0
    store.clear()
    assert store.revision() == 0, "空列表再清 = 无改动，不应 bump"


def test_set_fields_hit_bumps_miss_does_not(store):
    store.add(_clip("a"))
    before = store.revision()
    assert store.set_fields("a", start_time=2.5) is True
    assert store.revision() == before + 1
    miss_before = store.revision()
    assert store.set_fields("nope", start_time=9.9) is False
    assert store.revision() == miss_before


def test_update_where_hit_bumps_miss_does_not(store):
    store.add(_clip("a", type="video"))
    store.add(_clip("b", type="audio"))
    before = store.revision()
    hit = store.update_where(lambda c: c.get("type") == "audio", volume=0.5)
    assert hit == 1
    assert store.revision() == before + 1
    miss_before = store.revision()
    assert store.update_where(lambda c: c.get("type") == "image", volume=0.1) == 0
    assert store.revision() == miss_before


# ── CAS：匹配通过 ─────────────────────────────────────────────────────

def test_cas_match_allows_write(store):
    store.add(_clip("a"))
    rev = store.revision()
    store.add(_clip("b"), base_revision=rev)
    assert store.revision() == rev + 1
    assert len(store.rows()) == 2


def test_cas_match_set_fields(store):
    store.add(_clip("a"))
    rev = store.revision()
    assert store.set_fields("a", start_time=3.0, base_revision=rev) is True
    assert store.revision() == rev + 1


def test_cas_match_replace_all_and_clear(store):
    store.add(_clip("a"))
    rev = store.revision()
    store.replace_all([_clip("z")], base_revision=rev)
    rev2 = store.revision()
    store.clear(base_revision=rev2)
    assert store.rows() == []


# ── CAS：陈旧写入被拒绝，且不写 ───────────────────────────────────────

def test_cas_stale_add_is_rejected_without_writing(store):
    store.add(_clip("a"))
    stale = store.revision() - 1  # 故意落后一版
    with pytest.raises(RevisionConflict) as exc:
        store.add(_clip("b"), base_revision=stale)
    conflict = exc.value
    assert conflict.expected == stale
    assert conflict.actual == store.revision()
    # 一个字节都不该写进去
    assert [c["id"] for c in store.rows()] == ["a"]
    assert conflict.op == "add"


def test_cas_stale_remove_does_not_delete(store):
    store.add(_clip("a"))
    stale = store.revision() - 1
    with pytest.raises(RevisionConflict):
        store.remove_by_id("a", base_revision=stale)
    assert [c["id"] for c in store.rows()] == ["a"], "冲突时不得删除"


def test_cas_stale_set_fields_does_not_change(store):
    store.add(_clip("a", start_time=0.0))
    stale = store.revision() - 1
    with pytest.raises(RevisionConflict):
        store.set_fields("a", start_time=99.0, base_revision=stale)
    assert store.find_by_id("a")["start_time"] == 0.0


def test_cas_stale_replace_all_keeps_original(store):
    store.add(_clip("a"))
    stale = store.revision() - 1
    with pytest.raises(RevisionConflict):
        store.replace_all([], base_revision=stale)
    assert len(store.rows()) == 1


def test_cas_stale_clear_does_not_clear(store):
    store.add(_clip("a"))
    stale = store.revision() - 1
    with pytest.raises(RevisionConflict):
        store.clear(base_revision=stale)
    assert len(store.rows()) == 1


def test_cas_stale_update_where_writes_nothing(store):
    store.add(_clip("a", volume=1.0))
    stale = store.revision() - 1
    with pytest.raises(RevisionConflict):
        store.update_where(lambda c: True, volume=0.0, base_revision=stale)
    assert store.find_by_id("a")["volume"] == 1.0


# ── 冲突信息可被上层转成 409 ─────────────────────────────────────────

def test_conflict_carries_actionable_fields(store):
    store.add(_clip("a"))
    store.add(_clip("b"))
    with pytest.raises(RevisionConflict) as exc:
        store.add(_clip("c"), base_revision=0)
    c = exc.value
    assert c.expected == 0 and c.actual == 2
    text = str(c)
    assert "revision=0" in text and "revision=2" in text
    assert "未执行" in text, "错误消息必须说明本次写入未执行（不静默）"


# ── 保守性：None 与企业既有行为 ───────────────────────────────────────

def test_none_base_revision_keeps_legacy_behavior(store):
    store.add(_clip("a"))          # 无 base_revision
    store.add(_clip("b"))          # 无 base_revision
    store.set_fields("a", start_time=5.0)
    store.remove_by_id("b")
    assert [c["id"] for c in store.rows()] == ["a"]
    assert store.revision() == 4   # add,add,set_fields,remove


def test_invalid_base_revision_type_raises_typeerror(store):
    store.add(_clip("a"))
    with pytest.raises(TypeError):
        store.add(_clip("b"), base_revision="1")
    with pytest.raises(TypeError):
        store.add(_clip("b"), base_revision=True)


# ── check_revision 公开校验（宿主写入口用） ──────────────────────────

def test_check_revision_public_api(store):
    store.add(_clip("a"))
    store.check_revision(store.revision())          # 匹配：不抛
    with pytest.raises(RevisionConflict):
        store.check_revision(0)
    store.check_revision(None)                      # None：不校验


# ── 同一性不变量未被破坏 ─────────────────────────────────────────────

def test_list_identity_preserved_across_bump(store):
    rows = store.rows()
    store.add(_clip("a"))
    store.replace_all([_clip("b")])
    store.clear()
    assert store.rows() is rows, "revision 改造不得换掉 live list 对象"
