# -*- coding: utf-8 -*-
"""asset_hub 资产中间表示回归（刀2 · 2026-10-23）。

D2 验收口径：「同一角色跨镜复用有唯一来源」——本文件把它落成可执行断言：
    * 同一 path+source **派生同一个 asset_id**（幂等，不随机）
    * 血缘过 `normalize_generation` **六键白名单**，不扩容、不猜
    * 缺 path ⇒ asset_id 为空 ⇒ 拒绝落账（不造无主记录）
    * 落账委托 `gen_task_registry`，失败如实 False（不谎报）
    * `lineage_coverage` 空样本 ⇒ coverage=None（不把「没测」说成 0）
"""
import pytest

from app.core.asset_hub import (
    ASSET_KINDS,
    AssetRef,
    asset_ref_from_ingest,
    derive_asset_id,
    is_asset_ref,
    lineage_coverage,
    lineage_of_clip,
    normalize_kind,
    remember_ingest,
)
from app.core.glue.schema import GENERATION_KEYS


# ── 身份确定性 ────────────────────────────────────────────────────────

def test_same_path_and_source_derives_same_id():
    a = derive_asset_id("D:/media/out.mp4", source="stage3d_pose_video")
    b = derive_asset_id("D:/media/out.mp4", source="stage3d_pose_video")
    assert a == b and a.startswith("ast_")


def test_id_is_stable_across_case_and_slashes():
    assert derive_asset_id("D:\\Media\\Out.MP4", source="s") == derive_asset_id(
        "d:/media/out.mp4", source="s")


def test_different_source_gives_different_id():
    assert derive_asset_id("D:/a.mp4", source="x") != derive_asset_id("D:/a.mp4", source="y")


def test_empty_path_yields_empty_id():
    assert derive_asset_id("") == ""
    assert derive_asset_id("   ") == ""


def test_id_is_not_random_hash():
    """内置 hash() 带进程随机盐；跨进程不稳定 ⇒ 必须用哈希摘要。"""
    first = derive_asset_id("D:/a.mp4", source="s")
    import importlib
    import app.core.asset_hub as hub
    importlib.reload(hub)
    assert hub.derive_asset_id("D:/a.mp4", source="s") == first


# ── 载荷归一 ──────────────────────────────────────────────────────────

def test_ingest_payload_normalized():
    ref = asset_ref_from_ingest({
        "path": "D:/media/a.mp4",
        "title": "镜头 1",
        "source": "stage3d_pose_video",
        "kind": "video",
        "duration_sec": 3.2,
        "generation": {"prompt": "p", "seed": 42, "model": "m"},
    }, now=1234.0)
    assert ref.asset_id.startswith("ast_")
    assert ref.path == "D:/media/a.mp4"
    assert ref.kind == "video"
    assert ref.title == "镜头 1"
    assert ref.source == "stage3d_pose_video"
    assert ref.lineage["prompt"] == "p" and ref.lineage["seed"] == 42
    assert ref.created_at == 1234.0


def test_lineage_respects_six_key_whitelist():
    """白名单外的键必须被丢弃（六键不扩容铁律）。"""
    ref = asset_ref_from_ingest({
        "path": "D:/a.mp4",
        "generation": {"prompt": "p", "channel": "local", "reference": "r",
                       "secret_extra": "nope", "duration": 9},
    })
    assert "secret_extra" not in ref.lineage
    assert "duration" not in ref.lineage
    assert set(ref.lineage) <= set(GENERATION_KEYS)
    # channel / reference 是六键内的，应当保留（这正是前端丢的两键）
    assert ref.lineage.get("channel") == "local"
    assert ref.lineage.get("reference") == "r"


def test_malformed_generation_does_not_raise():
    ref = asset_ref_from_ingest({"path": "D:/a.mp4", "generation": "not-a-dict"})
    assert ref.lineage == {}


def test_missing_fields_stay_missing():
    ref = asset_ref_from_ingest({"path": "D:/a.mp4"})
    assert ref.title == ""
    assert ref.master_id == ""
    assert ref.lineage == {}
    assert ref.version == 1


def test_invalid_payload_returns_empty_ref():
    assert asset_ref_from_ingest(None).asset_id == ""
    assert asset_ref_from_ingest("junk").asset_id == ""


def test_kind_normalized_or_unknown():
    assert normalize_kind("VIDEO") == "video"
    assert normalize_kind("movie") == "video"
    assert normalize_kind("图片") == "unknown"
    assert normalize_kind(None) == "unknown"
    assert normalize_kind("hologram") == "unknown"
    assert set(ASSET_KINDS) >= {"image", "video", "audio"}


def test_explicit_asset_id_wins():
    ref = asset_ref_from_ingest({"path": "D:/a.mp4", "asset_id": "ast_given"})
    assert ref.asset_id == "ast_given"


def test_version_positive_only():
    assert asset_ref_from_ingest({"path": "a", "version": 3}).version == 3
    assert asset_ref_from_ingest({"path": "a", "version": 0}).version == 1
    assert asset_ref_from_ingest({"path": "a", "version": -2}).version == 1
    assert asset_ref_from_ingest({"path": "a", "version": True}).version == 1


# ── 落账：不造假 ──────────────────────────────────────────────────────

def test_remember_rejects_ownerless_record():
    assert remember_ingest(AssetRef(asset_id="", path="D:/a.mp4")) is False
    assert remember_ingest(AssetRef(asset_id="ast_x", path="")) is False
    assert remember_ingest("not-a-ref") is False


def test_remember_calls_record_asset():
    calls = {}

    class FakeStore:
        def record_asset(self, asset_id, *, path, kind="", canvas_node_id=""):
            calls.update(asset_id=asset_id, path=path, kind=kind)
            return {"asset_id": asset_id}

    ref = asset_ref_from_ingest({"path": "D:/a.mp4", "kind": "video"})
    assert remember_ingest(ref, store=FakeStore()) is True
    assert calls["asset_id"] == ref.asset_id
    assert calls["path"] == "D:/a.mp4"
    assert calls["kind"] == "video"


def test_remember_reports_failure_honestly():
    class Boom:
        def record_asset(self, *a, **k):
            raise RuntimeError("disk full")

    class ReturnsNone:
        def record_asset(self, *a, **k):
            return None

    ref = asset_ref_from_ingest({"path": "D:/a.mp4"})
    assert remember_ingest(ref, store=Boom()) is False
    assert remember_ingest(ref, store=ReturnsNone()) is False
    assert remember_ingest(ref, store=object()) is False


# ── 血缘查询：查不到就是空槽 ──────────────────────────────────────────

def test_lineage_of_clip_delegates():
    class FakeStore:
        def resolve_lineage(self, clip):
            return {"clip_id": clip.get("id"), "asset": {"asset_id": "a1"},
                    "task": None, "canvas_node_id": "n1"}

    out = lineage_of_clip({"id": "c1", "asset_id": "a1"}, store=FakeStore())
    assert out["clip_id"] == "c1"
    assert out["asset"] == {"asset_id": "a1"}
    assert out["task"] is None, "查不到的任务槽必须是 None，不能猜"


def test_lineage_of_clip_never_raises():
    class Boom:
        def resolve_lineage(self, clip):
            raise RuntimeError("bad")

    out = lineage_of_clip({"id": "c1"}, store=Boom())
    assert out["asset"] is None and out["task"] is None
    assert lineage_of_clip("junk", store=object())["asset"] is None


# ── 覆盖率：不把「没测」说成 0 ────────────────────────────────────────

def test_coverage_empty_sample_is_none_not_zero():
    out = lineage_coverage([])
    assert out["total"] == 0
    assert out["coverage"] is None, "空样本的覆盖率必须是 None（没说测过）"


def test_coverage_counts_six_keys():
    full = asset_ref_from_ingest({"path": "a", "generation": {
        "prompt": "p", "seed": 1, "model": "m",
        "channel": "c", "character_id": "ch", "reference": "r"}})
    half = asset_ref_from_ingest({"path": "b", "generation": {"prompt": "p", "seed": 1}})
    out = lineage_coverage([full, half])
    assert out["total"] == 2 and out["complete"] == 1
    assert out["coverage"] == 0.5
    assert out["per_key"]["prompt"] == 2
    assert out["per_key"]["channel"] == 1


def test_coverage_ignores_empty_refs():
    out = lineage_coverage([AssetRef(asset_id="", path="")])
    assert out["total"] == 0 and out["coverage"] is None


# ── 序列化 ────────────────────────────────────────────────────────────

def test_roundtrip():
    ref = asset_ref_from_ingest({"path": "D:/a.mp4", "kind": "video",
                                 "generation": {"prompt": "p", "seed": 7}}, now=5.0)
    data = ref.to_dict()
    assert AssetRef.from_dict(data).to_dict() == data


def test_from_dict_malformed_is_safe():
    assert AssetRef.from_dict(None).asset_id == ""
    assert AssetRef.from_dict("junk").path == ""
    assert AssetRef.from_dict({"lineage": "bad"}).lineage == {}


def test_lineage_keys_sorted():
    ref = asset_ref_from_ingest({"path": "a", "generation": {"seed": 1, "prompt": "p"}})
    assert ref.lineage_keys() == ["prompt", "seed"]


def test_is_asset_ref():
    assert is_asset_ref(AssetRef(asset_id="x", path="y")) is True
    assert is_asset_ref({"asset_id": "x"}) is False
