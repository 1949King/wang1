# -*- coding: utf-8 -*-
"""app/tests/test_idea_card.py — 选题立意卡回归（WS-D 第一刀）。

锁定纪律：往返无损 · 状态只收三值 · blocked 必须有人工合规备注 · 空标题 ·
不猜题材/受众 · 非法状态不被静默纠正。
"""

import pytest

from app.core.idea_card import (
    IDEA_CARD_STATUSES,
    IdeaCard,
    create_idea_card,
    from_dict,
    set_status,
    to_dict,
    validate_idea_card,
)


def _full_card(**overrides) -> IdeaCard:
    """一张字段齐全的立意卡；overrides 用来刻意制造缺失。"""
    payload = {
        "title": "长夜拾光",
        "logline": "一句话立意",
        "genre": "悬疑",
        "audience": "25-35 女性",
        "tone": "冷峻",
    }
    payload.update(overrides)
    return create_idea_card(**payload)


@pytest.mark.unit
class TestRoundTrip:
    def test_full_card_roundtrip_is_lossless(self):
        card = _full_card()
        card = set_status(card, "ready")
        card.compliance_notes.extend(["不含真实案件细节"])
        data = to_dict(card)
        restored = from_dict(data)
        assert restored == card
        assert restored.to_dict() == data
        assert validate_idea_card(card) == []

    def test_compliance_notes_do_not_share_list(self):
        card = _full_card()
        card.compliance_notes.append("原备注")
        data = card.to_dict()
        data["compliance_notes"].append("外部篡改")
        assert card.compliance_notes == ["原备注"]


@pytest.mark.unit
class TestDefaultsAreHonest:
    def test_create_does_not_guess_genre_audience(self):
        card = create_idea_card("标题", logline="立意")
        assert card.genre == ""
        assert card.audience == ""
        assert card.tone == ""
        assert card.compliance_notes == []
        assert card.status == "draft"
        errors = validate_idea_card(card)
        assert any("题材" in error for error in errors)
        assert any("受众" in error for error in errors)
        assert not any("compliance_notes" in error for error in errors)

    def test_status_values_are_exactly_three(self):
        assert IDEA_CARD_STATUSES == ("draft", "ready", "blocked")


@pytest.mark.unit
class TestEmptyFields:
    def test_empty_title_is_flagged(self):
        card = _full_card(title="")
        errors = validate_idea_card(card)
        assert any("标题" in error for error in errors)

    def test_blank_title_is_flagged(self):
        card = _full_card(title="   ")
        errors = validate_idea_card(card)
        assert any("标题" in error for error in errors)

    def test_empty_logline_is_flagged(self):
        card = _full_card(logline="")
        errors = validate_idea_card(card)
        assert any("logline" in error for error in errors)

    def test_from_dict_missing_fields_are_flagged(self):
        card = IdeaCard.from_dict({})
        assert card.title == "" and card.logline == ""
        assert card.status == "draft"
        errors = validate_idea_card(card)
        assert any("标题" in error for error in errors)
        assert any("logline" in error for error in errors)


@pytest.mark.unit
class TestStatus:
    def test_set_status_returns_new_card(self):
        card = _full_card()
        ready = set_status(card, "ready")
        assert ready is not card
        assert ready.status == "ready"
        assert card.status == "draft"
        assert ready.card_id == card.card_id

    @pytest.mark.parametrize("bad_status", ["approved", "DONE", "", "blocked "])
    def test_set_status_rejects_illegal_value(self, bad_status):
        with pytest.raises(ValueError, match="非法 status"):
            set_status(_full_card(), bad_status)

    def test_illegal_status_is_flagged_not_corrected(self):
        card = IdeaCard(title="标题", logline="立意", genre="悬疑", audience="大众",
                        status="approved")
        errors = validate_idea_card(card)
        assert any("非法" in error for error in errors)
        assert card.status == "approved"

    def test_from_dict_keeps_illegal_status_for_validation(self):
        card = from_dict({"title": "标题", "logline": "立意", "genre": "悬疑",
                          "audience": "大众", "status": "approved"})
        assert card.status == "approved"
        errors = validate_idea_card(card)
        assert any("非法" in error for error in errors)

    def test_set_status_non_card_raises(self):
        with pytest.raises(TypeError):
            set_status(None, "ready")


@pytest.mark.unit
class TestBlockedCompliance:
    def test_blocked_requires_compliance_notes(self):
        card = set_status(_full_card(), "blocked")
        errors = validate_idea_card(card)
        assert any("compliance_notes" in error for error in errors)

    def test_blocked_with_blank_notes_still_flagged(self):
        card = set_status(_full_card(), "blocked")
        card.compliance_notes.extend(["", "   "])
        errors = validate_idea_card(card)
        assert any("compliance_notes" in error for error in errors)

    def test_blocked_with_notes_passes(self):
        card = set_status(_full_card(), "blocked")
        card.compliance_notes.append("涉及医疗情节，需补专业顾问确认")
        assert validate_idea_card(card) == []

    def test_ready_does_not_require_compliance_notes(self):
        card = set_status(_full_card(), "ready")
        assert card.compliance_notes == []
        assert validate_idea_card(card) == []


@pytest.mark.unit
class TestValidationBoundary:
    def test_validate_non_idea_card_does_not_raise(self):
        errors = validate_idea_card(None)
        assert isinstance(errors, list)
        assert errors

    def test_validate_reports_all_problems_at_once(self):
        card = IdeaCard()
        errors = validate_idea_card(card)
        assert len(errors) >= 4
        assert any("标题" in error for error in errors)
        assert any("logline" in error for error in errors)
        assert any("题材" in error for error in errors)
        assert any("受众" in error for error in errors)
