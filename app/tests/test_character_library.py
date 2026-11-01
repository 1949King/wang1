# -*- coding: utf-8 -*-
"""角色库桥接（2026-11-01）：复用既有 CharacterStore，不另建一套存储。

测试用 SHIGUANG_CHARACTER_STORE_PATH 指到临时文件 —— 既隔离真实角色库，
也证明"路径可覆盖"这条应急通道是通的（主库目录不可写时靠它）。
"""
from __future__ import annotations

import json

import pytest

import app.core.ai.character_library as CL


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    path = tmp_path / "characters.json"
    monkeypatch.setenv("SHIGUANG_CHARACTER_STORE_PATH", str(path))
    yield path
    monkeypatch.delenv("SHIGUANG_CHARACTER_STORE_PATH", raising=False)


def test_store_path_override(lib):
    assert CL.store_path() == str(lib)


def test_save_list_delete_roundtrip(lib):
    res = CL.save_character(name="林小满", card={"gender": "女生", "hair": "黑长直"})
    assert res["ok"] and res["id"]
    items = CL.list_characters()
    assert len(items) == 1
    assert items[0]["name"] == "林小满"
    assert items[0]["card"]["hair"] == "黑长直"
    assert items[0]["has_card"] is True

    assert CL.delete_character(res["id"])["ok"] is True
    assert CL.list_characters() == []


def test_update_keeps_id(lib):
    res = CL.save_character(name="A", card={"gender": "女生"})
    upd = CL.save_character(name="A2", card={"outfit": "汉服"}, char_id=res["id"])
    assert upd["ok"] and upd["id"] == res["id"]
    got = CL.get_character(res["id"])
    assert got["name"] == "A2" and got["card"]["outfit"] == "汉服"


def test_empty_name_rejected(lib):
    res = CL.save_character(name="   ", card={"gender": "女生"})
    assert res["ok"] is False and "角色名" in res["message"]


def test_update_missing_character_is_explicit(lib):
    res = CL.save_character(name="X", card={}, char_id="not-exist")
    assert res["ok"] is False and "不存在" in res["message"]


def test_card_whitelist_drops_unknown_keys(lib):
    res = CL.save_character(name="B", card={"gender": "女生", "垃圾字段": "x", "hair": "短发"})
    assert res["ok"]
    card = CL.get_character(res["id"])["card"]
    assert "垃圾字段" not in card
    assert card["hair"] == "短发"


def test_derive_card_from_basic_fields(lib):
    """没有 person_card 时，从 gender/age_range 推基础两项（appearance 不硬拆）。"""
    path = lib
    path.write_text(json.dumps([
        {"id": "c1", "name": "老角色", "gender": "女", "age_range": "青年",
         "appearance": "黑色长直发，米白衬衫"},
    ], ensure_ascii=False), encoding="utf-8")
    got = CL.get_character("c1")
    assert got["card"] == {"gender": "女生", "age": "青年"}
    assert got["has_card"] is False
    assert "黑色长直发" in (got["hint"] or "")
