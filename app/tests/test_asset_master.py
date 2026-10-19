# -*- coding: utf-8 -*-
"""AssetMaster 母版模型测试（2026-10-20）。"""
from app.core.asset_master import (
    AssetMaster,
    add_variant,
    clear_stale,
    create_master,
    deep_merge,
    resolve_variant,
    update_canonical,
    validate_master,
)


def test_deep_merge_nested_without_mutation():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    override = {"nested": {"y": 3}, "b": 2}
    merged = deep_merge(base, override)
    assert merged == {"a": 1, "nested": {"x": 1, "y": 3}, "b": 2}
    assert base["nested"]["y"] == 2  # 不改入参


def test_create_validate_and_variant_resolution():
    master = create_master("character", "林夏", {
        "gender": "female",
        "appearance": {"hair": "long", "color": "black"},
        "voice": "warm",
    })
    assert validate_master(master) == []
    variant = add_variant(master, overrides={"appearance": {"color": "brown"}},
                          media=["a.png"], seed=42, model="sd")
    resolved, errors = resolve_variant(master, variant.variant_id)
    assert errors == []
    assert resolved["appearance"] == {"hair": "long", "color": "brown"}
    assert resolved["voice"] == "warm"
    assert resolved["_master_id"] == master.master_id
    assert resolved["_kind"] == "character"


def test_unknown_variant_returns_error():
    master = create_master("scene", "天台")
    resolved, errors = resolve_variant(master, "nope")
    assert resolved is None
    assert any("未找到变体" in e for e in errors)


def test_invalid_master_fields():
    master = AssetMaster(master_id="", kind="unknown", name="")
    errors = validate_master(master)
    assert any("master_id" in e for e in errors)
    assert any("kind" in e for e in errors)
    assert any("name" in e for e in errors)


def test_update_canonical_marks_variants_stale_and_clears():
    master = create_master("prop", "玉佩", {"material": "jade"})
    v1 = add_variant(master, variant_id="v1")
    v2 = add_variant(master, variant_id="v2")
    marked = update_canonical(master, {"material": "white jade"})
    assert {v.variant_id for v in marked} == {"v1", "v2"}
    assert v1.stale_reason and v2.stale_reason
    resolved, _ = resolve_variant(master, "v1")
    assert resolved["material"] == "white jade"
    assert "母版 v2 更新" in resolved["_stale_reason"]
    assert clear_stale(master, "v1") is True
    assert v1.stale_reason == ""
    assert clear_stale(master, "nope") is False


def test_roundtrip_to_from_dict():
    master = create_master("style", "赛博霓虹", {"palette": {"neon": ["#f0f", "#0ff"]}})
    add_variant(master, overrides={"palette": {"neon": ["#f0f"]}}, seed=7, model="m")
    data = master.to_dict()
    restored = AssetMaster.from_dict(data)
    assert restored.to_dict() == data
    assert restored.variants[0].seed == 7
