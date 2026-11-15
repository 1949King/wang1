# -*- coding: utf-8 -*-
"""`model_sources` 的诚实性守卫。

这张表的唯一用途是「点一下就跳过去」。所以它的错法只有两种：
① 链接格式不对（点开 404）；② 明明没有开放权重却硬编一个链接。

这里不测网络（CI 不该依赖外网），只测**形状与覆盖**。
可达性由 `VERIFIED_AT` 那次逐个 probe 保证（魔搭走 `/api/v1/models/<repo>` → 200，
GitHub 走 `https://github.com/<owner>/<name>` → 200）。
"""
from __future__ import annotations

from app.core.neural import model_sources as MS


def test_verified_date_recorded() -> None:
    assert MS.VERIFIED_AT, "链接必须记录核实日期，否则成了传说"
    assert MS.VERIFIED_AT.count("-") == 2


def test_url_templates_are_https() -> None:
    assert MS.MODELSCOPE_MODEL_URL.startswith("https://")
    assert MS.GITHUB_REPO_URL.startswith("https://")


def test_known_models_get_both_sources() -> None:
    """四族主力模型：魔搭 + GitHub 都要有。"""
    for mid, fam in (
        ("sd15-t2i", "sd15"),
        ("sdxl-t2i", "sdxl"),
        ("svd-xt-i2v", "svd"),
        ("wan21-t2v-1.3b", "wan"),
        ("wan22-ti2v-5b", "wan"),
    ):
        ss = MS.sources_for(mid, fam)
        names = [s["name"] for s in ss]
        assert "魔搭 ModelScope" in names, (mid, names)
        assert "GitHub" in names, (mid, names)
        for s in ss:
            assert s["url"].startswith("https://"), s
            host = s["url"][8:].split("/")[0]
            assert host in ("www.modelscope.cn", "github.com"), host


def test_wan_branches_point_to_their_own_repo() -> None:
    """2.1 和 2.2 是两个仓，别都指到 2.1。"""
    u21 = MS.sources_for("wan21-t2v-1.3b", "wan")[1]["url"]
    u22 = MS.sources_for("wan22-ti2v-5b", "wan")[1]["url"]
    assert u21.endswith("Wan2.1") and u22.endswith("Wan2.2")


def test_minimax_has_no_source_at_all() -> None:
    """闭源无权重 ⇒ 空列表。**不许**退化成「去搜索页找」这种假链接。"""
    assert MS.sources_for("", "minimax_h3") == []


def test_download_dir_repo_matches_registry() -> None:
    """魔搭链接里的 repo 必须来自注册表，不能是另写一份。"""
    from app.core.neural import video_gen as VG

    spec = VG.VIDEO_MODELS["wan21-t2v-1.3b"]
    url = MS.sources_for("wan21-t2v-1.3b", "wan")[0]["url"]
    assert url == MS.MODELSCOPE_MODEL_URL % spec["repo"]


def test_attach_sources_handles_family_rows() -> None:
    """`local_models_view` 的族行 id 形如 `cogvideox（族）`，也要能查出链接。"""
    rows = [{"id": "cogvideox（族）", "family": "cogvideox"}]
    MS.attach_sources(rows)
    assert rows[0]["sources"], "族行必须能查到代表仓库"
    assert "modelscope" in rows[0]["sources"][0]["url"]


def test_attach_sources_never_raises() -> None:
    rows = [{"id": "", "family": ""}]
    MS.attach_sources(rows)
    assert rows[0]["sources"] == []


def test_community_notes_mention_ollama_and_comfyui() -> None:
    """这两个边界必须出现在用户看得到的说明里 —— 否则按钮会暗示错东西。"""
    t = MS.community_notes()
    assert "Ollama" in t and "ComfyUI" in t
    assert "拉不了" in t or "不" in t
