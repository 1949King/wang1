# -*- coding: utf-8 -*-
"""app/tests/test_script_doc.py — 长篇剧本结构模型回归（WS-D 第一刀）。

锁定纪律：往返无损 · 集号唯一且升序 · 缺 duration 进 errors · 空输入 · 不猜集数/钩子。
"""

import pytest

from app.core.script_doc import (
    Episode,
    ScriptDoc,
    add_episode,
    create_script_doc,
    from_dict,
    to_dict,
    validate_script_doc,
)


def _episode_payload(number: int, **overrides):
    """一集「填满」的合法内容；overrides 用来刻意制造缺失。"""
    payload = {
        "number": number,
        "title": f"第{number}集 标题",
        "synopsis": "剧情梗概",
        "beats": ["开场", "转折", "收尾"],
        "hook": "结尾悬念",
        "duration_target": 120.0,
    }
    payload.update(overrides)
    return payload


def _valid_doc() -> ScriptDoc:
    doc = create_script_doc("长夜拾光", logline="一句话梗概", genre="悬疑")
    doc = add_episode(doc, **_episode_payload(2))
    doc = add_episode(doc, **_episode_payload(1))
    return doc


@pytest.mark.unit
class TestRoundTrip:
    def test_create_and_roundtrip_is_lossless(self):
        doc = _valid_doc()
        assert doc.doc_id
        assert doc.created_at
        assert doc.version == 1
        assert [episode.number for episode in doc.episodes] == [1, 2]
        data = to_dict(doc)
        restored = from_dict(data)
        assert restored == doc
        assert restored.to_dict() == data
        assert validate_script_doc(doc) == []

    def test_beats_and_duration_survive_roundtrip(self):
        doc = create_script_doc("标题")
        doc = add_episode(doc, number=1, title="一", hook="钩子", beats=["a", "b"],
                          duration_target=119.5)
        restored = ScriptDoc.from_dict(doc.to_dict())
        assert restored.episodes[0].beats == ["a", "b"]
        assert restored.episodes[0].duration_target == 119.5

    def test_to_dict_does_not_share_beats_list(self):
        doc = create_script_doc("标题")
        doc = add_episode(doc, number=1, title="一", hook="钩子", beats=["a"],
                          duration_target=60.0)
        data = doc.to_dict()
        data["episodes"][0]["beats"].append("外部篡改")
        assert doc.episodes[0].beats == ["a"]


@pytest.mark.unit
class TestEpisodeOrdering:
    def test_add_episode_keeps_number_sorted(self):
        doc = create_script_doc("标题")
        for number in (3, 1, 2):
            doc = add_episode(doc, **_episode_payload(number))
        assert [episode.number for episode in doc.episodes] == [1, 2, 3]
        assert validate_script_doc(doc) == []

    def test_unsorted_construction_is_flagged(self):
        doc = ScriptDoc(
            title="标题",
            episodes=[
                Episode(number=2, title="二", hook="钩子", duration_target=60.0),
                Episode(number=1, title="一", hook="钩子", duration_target=60.0),
            ],
        )
        errors = validate_script_doc(doc)
        assert any("升序" in error for error in errors)


@pytest.mark.unit
class TestDuplicateNumber:
    def test_add_episode_rejects_duplicate(self):
        doc = create_script_doc("标题")
        doc = add_episode(doc, number=1, title="一", hook="钩子", duration_target=60.0)
        with pytest.raises(ValueError, match="已存在"):
            add_episode(doc, number=1, title="重复", hook="钩子", duration_target=60.0)

    def test_validate_catches_duplicate_numbers(self):
        doc = ScriptDoc(
            title="标题",
            episodes=[
                Episode(number=1, title="一", hook="钩子", duration_target=60.0),
                Episode(number=1, title="重复", hook="钩子", duration_target=60.0),
            ],
        )
        errors = validate_script_doc(doc)
        assert any("重复" in error for error in errors)


@pytest.mark.unit
class TestMissingFields:
    def test_missing_duration_is_not_guessed(self):
        doc = create_script_doc("标题")
        doc = add_episode(doc, number=1, title="第一集", hook="悬念")
        assert doc.episodes[0].duration_target == 0.0
        errors = validate_script_doc(doc)
        assert any("duration_target" in error for error in errors)

    def test_missing_episode_title_and_hook_are_flagged(self):
        doc = create_script_doc("标题")
        doc = add_episode(doc, number=1, duration_target=60.0)
        errors = validate_script_doc(doc)
        assert any("标题为空" in error for error in errors)
        assert any("hook" in error for error in errors)

    def test_non_numeric_duration_is_flagged(self):
        doc = ScriptDoc(
            title="标题",
            episodes=[Episode(number=1, title="一", hook="钩子", duration_target="60")],
        )
        errors = validate_script_doc(doc)
        assert any("duration_target" in error for error in errors)


@pytest.mark.unit
class TestEmptyAndBoundary:
    def test_empty_title_is_flagged(self):
        doc = create_script_doc("")
        assert doc.episodes == []
        errors = validate_script_doc(doc)
        assert any("标题" in error for error in errors)

    def test_blank_title_is_flagged(self):
        errors = validate_script_doc(create_script_doc("   "))
        assert any("标题" in error for error in errors)

    def test_empty_doc_is_legal_but_reports_hint(self):
        doc = create_script_doc("占位标题")
        assert doc.episodes == []
        assert ScriptDoc.from_dict(doc.to_dict()) == doc
        errors = validate_script_doc(doc)
        assert any("剧集为空" in error for error in errors)

    def test_non_positive_number_rejected(self):
        doc = create_script_doc("标题")
        for bad_number in (0, -3):
            with pytest.raises(ValueError):
                add_episode(doc, number=bad_number, title="一", hook="钩子",
                            duration_target=60.0)

    def test_non_positive_number_flagged_when_constructed_directly(self):
        doc = ScriptDoc(
            title="标题",
            episodes=[Episode(number=0, title="一", hook="钩子", duration_target=60.0)],
        )
        errors = validate_script_doc(doc)
        assert any("集号" in error for error in errors)

    def test_add_episode_rejects_string_beats(self):
        doc = create_script_doc("标题")
        with pytest.raises(ValueError, match="beats"):
            add_episode(doc, number=1, title="一", hook="钩子", beats="整段文本")

    def test_add_episode_returns_new_doc_without_mutating_original(self):
        doc = create_script_doc("标题")
        extended = add_episode(doc, number=1, title="一", hook="钩子", duration_target=60.0)
        assert doc.episodes == []
        assert extended is not doc
        assert extended.doc_id == doc.doc_id
        assert extended.episodes[0].number == 1

    def test_validate_non_scriptdoc_does_not_raise(self):
        errors = validate_script_doc(None)
        assert isinstance(errors, list)
        assert errors

    def test_from_dict_missing_fields_are_flagged_not_guessed(self):
        doc = ScriptDoc.from_dict({})
        assert doc.title == ""
        assert doc.episodes == []
        errors = validate_script_doc(doc)
        assert any("标题" in error for error in errors)
        assert any("剧集为空" in error for error in errors)
