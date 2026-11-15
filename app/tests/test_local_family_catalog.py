# -*- coding: utf-8 -*-
"""`local_family_catalog` 的诚实性守卫。

这张表的用途是回答「这个模型怎么拉」，所以它的错法只有一种：**填了不存在的东西**。
下面的断言全部针对这一点 —— 不测网络（CI 不该连 ModelScope），只测自洽。

真正的仓库存在性由 `measured_at` 那次实测保证（2026-11-15 逐个 probe 返回 200），
仓库失效时会先在 `--missing` 的下载环节炸出来。
"""
from __future__ import annotations

import pytest

from app.core.local_video_infer import MODEL_KEYWORD_MAP
from app.core.neural import local_family_catalog as LFC


def test_every_kind_is_recognisable_by_scanner():
    """kind 必须是扫描器认得的族名，否则下载完了也扫不出来。"""
    for mid, spec in LFC.LOCAL_FAMILY_MODELS.items():
        assert spec["kind"] in MODEL_KEYWORD_MAP, f"{mid}: kind={spec['kind']} 不在关键词表里"


def test_download_dir_name_matches_keyword():
    """落盘目录名 = repo 去斜杠 ⇒ 必须命中族关键词，这是刻意的对齐。

    `neural_engine.repo_local_dir()` 把 `owner/name` 换成 `owner_name`，
    而 `_scan_local_models()` 靠目录名小写匹配关键词。
    """
    for mid, spec in LFC.LOCAL_FAMILY_MODELS.items():
        repo = spec.get("repo") or ""
        if not repo:
            continue
        dirname = repo.replace("/", "_").lower()
        kws = MODEL_KEYWORD_MAP[spec["kind"]]
        assert any(kw in dirname for kw in kws), (
            f"{mid}: 落盘目录 {dirname} 不含 {spec['kind']} 的关键词 {kws} ⇒ 下载后扫不到"
        )


def test_pullable_entries_look_complete():
    for mid, spec in LFC.LOCAL_FAMILY_MODELS.items():
        if not spec.get("pull"):
            continue
        assert spec.get("repo"), f"{mid}: pull=True 但没有 repo"
        assert spec.get("subset_gb", 0) > 0, f"{mid}: pull=True 但 subset_gb 为 0"
        assert spec.get("full_repo_gb", 0) >= spec["subset_gb"], f"{mid}: 整仓比子集还小"


def test_non_pullable_entries_must_say_why():
    """不可下载必须给原因。「拉不了」三个字不算原因。"""
    for mid, spec in LFC.LOCAL_FAMILY_MODELS.items():
        if spec.get("pull"):
            continue
        why = (spec.get("no_pull_reason") or "").strip()
        assert len(why) >= 20, f"{mid}: 不可下载但没给出像样的原因（{why!r}）"


def test_ram_estimate_covers_weights():
    """内存估算至少要装得下权重本身 —— 比权重还小的估算一定是笔误。"""
    for mid, spec in LFC.LOCAL_FAMILY_MODELS.items():
        size = spec.get("subset_gb") or 0
        if size <= 0:
            continue
        assert spec.get("ram_gb", 0) >= size, f"{mid}: ram_gb={spec.get('ram_gb')} < 权重 {size}GB"


def test_pullable_ids_matches_flag():
    ids = set(LFC.pullable_ids())
    for mid, spec in LFC.LOCAL_FAMILY_MODELS.items():
        assert (mid in ids) == bool(spec.get("pull") and spec.get("repo")), mid


def test_measured_at_is_recorded():
    assert LFC.CATALOG_MEASURED_AT, "必须记录体积的实测日期，否则数字就成了传说"
    assert "modelscope" in LFC.CATALOG_MEASURED_FROM.lower()


def test_public_list_marks_estimates():
    rows = LFC.public_list()
    assert len(rows) == len(LFC.LOCAL_FAMILY_MODELS)
    for r in rows:
        assert r["ram_gb_estimated"] is True, f"{r['id']}: 估算值必须打标"
        assert r["measured_at"] == LFC.CATALOG_MEASURED_AT


def test_download_rejects_unknown_and_unpullable():
    r = LFC.download("no-such-model")
    assert r["ok"] is False and "未知" in r["message"]
    r = LFC.download("minimax-h3")
    assert r["ok"] is False and "404" in r["message"]


@pytest.mark.parametrize("mid", ["hunyuan-video", "minimax-h3"])
def test_known_impossible_ids_are_not_pullable(mid):
    """这两条是「不是没适配，是客观不存在/格式不符」，别哪天被人顺手打开。"""
    assert mid in LFC.LOCAL_FAMILY_MODELS
    assert LFC.LOCAL_FAMILY_MODELS[mid]["pull"] is False
