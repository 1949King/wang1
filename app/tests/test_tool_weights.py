# -*- coding: utf-8 -*-
"""工具权重登记（T1 下载中心）：探测诚实 / 绝不自动下载 / 视图与检查器集成。

红线（用户拍板）：模型权重**绝不自动下载、不随包**，只给「自取 + guidance」。
本测试用 AST 断言 tool_weights 模块内没有任何下载调用与网络库导入。
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from app.core import video_depth
from app.core.neural import tool_weights as TW

_EXPECTED_IDS = (
    "rife49", "espcn_x2", "espcn_x3", "espcn_x4",
    "realesrgan_x4plus", "lama_dilated", "depth_anything_v2_small",
    "wan22_lightning_lora",
)


def test_registry_complete_and_guidance_honest() -> None:
    """8 项工具权重齐全；每项 guidance 非空且含文件名（用户照着能放对）。"""
    assert tuple(TW.TOOL_WEIGHTS) == _EXPECTED_IDS
    for tid, spec in TW.TOOL_WEIGHTS.items():
        assert set(spec) >= {
            "label", "filename", "probe", "place", "guidance", "sources", "license",
        }, tid
        assert callable(spec["probe"]), tid
        assert spec["guidance"] and spec["filename"] in spec["guidance"], tid
        assert spec["place"], tid
        # T0 许可门禁（2026-11-20）已实抓 LICENSE 核实全部 8 项
        assert spec["license"] in ("MIT", "Apache-2.0", "BSD-3-Clause"), tid


def test_missing_probe_yields_not_downloaded(monkeypatch) -> None:
    """探测不到 ⇒ downloaded=False / dir 空 / 体积 None（不装可用）。"""
    for tid in _EXPECTED_IDS:
        spec = dict(TW.TOOL_WEIGHTS[tid])
        spec["probe"] = lambda: ""
        monkeypatch.setitem(TW.TOOL_WEIGHTS, tid, spec)
    rows = {r["id"]: r for r in TW.tool_rows()}
    for tid in _EXPECTED_IDS:
        assert rows[tid]["downloaded"] is False, tid
        assert rows[tid]["dir"] == "", tid
        assert rows[tid]["size_gb"] is None, tid


def test_present_probe_yields_downloaded_with_dir(monkeypatch, tmp_path) -> None:
    """权重真在盘 ⇒ downloaded=True，dir 给实际路径，体积如实。"""
    f = tmp_path / "rife49.pth"
    f.write_bytes(b"x" * 2048)
    spec = dict(TW.TOOL_WEIGHTS["rife49"])
    spec["probe"] = lambda: str(f)
    monkeypatch.setitem(TW.TOOL_WEIGHTS, "rife49", spec)
    row = next(r for r in TW.tool_rows() if r["id"] == "rife49")
    assert row["downloaded"] is True
    assert row["dir"] == str(f)
    assert row["size_gb"] is not None


def test_sources_honest_no_fabrication() -> None:
    """T0 已核许可 ⇒ 每项都给真实 https 资源地址；RIFE 与 guidance 同源、depth 用现有地址。"""
    from app.core.neural import rife_engine

    for tid, spec in TW.TOOL_WEIGHTS.items():
        assert spec["sources"], "%s 许可已核应给资源地址" % tid
        for s in spec["sources"]:
            assert s["url"].startswith("https://"), s
            assert s["name"] and s["note"], s
    rife_srcs = TW.TOOL_WEIGHTS["rife49"]["sources"]
    assert len(rife_srcs) == 2
    for s in rife_srcs:
        assert s["url"] in rife_engine.RIFE_MODEL_GUIDANCE, "链接必须与 guidance 同源"
    depth_srcs = TW.TOOL_WEIGHTS["depth_anything_v2_small"]["sources"]
    assert depth_srcs and depth_srcs[0]["url"] == video_depth.MODEL_URL
    assert "TF-ESPCN" in TW.TOOL_WEIGHTS["espcn_x2"]["sources"][0]["url"]
    assert "Wan2.2-Lightning" in TW.TOOL_WEIGHTS["wan22_lightning_lora"]["sources"][0]["url"]


def test_no_download_code_in_tool_weights() -> None:
    """AST 断言：本模块零下载调用、零网络库导入（红线是结构性的，不靠自觉）。"""
    tree = ast.parse(Path(TW.__file__).read_text(encoding="utf-8"))
    banned = {"urllib", "requests", "modelscope", "huggingface_hub", "httpx"}
    banned_calls = {"download", "download_model", "snapshot_download", "urlopen", "pull"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned, a.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned, node.module
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                assert fn.attr not in banned_calls, fn.attr
            elif isinstance(fn, ast.Name):
                assert fn.id not in banned_calls, fn.id


def test_view_includes_tool_rows_without_touching_families() -> None:
    """视图集成：工具行在、生成模型族行不受影响、工具行自带 sources。"""
    from app.core.neural import local_models_view as LV

    rows = LV.list_local_models()
    tool = [r for r in rows if r["capability"] == "tool"]
    assert {r["id"] for r in tool} == set(_EXPECTED_IDS)
    ids = {r["id"] for r in rows}
    assert {"sd15-t2i", "sdxl-t2i", "svd-xt-i2v"} <= ids
    for r in tool:
        assert r["family"] == "tool"
        assert r["verification"] == ""
        assert isinstance(r.get("sources"), list)


def _load_check_models():
    """scripts/check_models.py 不在包内，按路径加载（__main__ 守卫不会触发）。"""
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "check_models_t1", root / "scripts" / "check_models.py")
    cm = importlib.util.module_from_spec(spec)
    sys.modules["check_models_t1"] = cm
    spec.loader.exec_module(cm)
    return cm


def test_check_models_collect_and_missing_render(monkeypatch) -> None:
    """collect 含工具行（可过滤）；--missing 渲染「工具权重自取」段与 guidance。"""
    for tid in _EXPECTED_IDS:
        spec = dict(TW.TOOL_WEIGHTS[tid])
        spec["probe"] = lambda: ""
        monkeypatch.setitem(TW.TOOL_WEIGHTS, tid, spec)
    cm = _load_check_models()
    _status, rows, cat = cm.collect(None, show_all=True)
    tool = [r for r in rows if r["capability"] == "tool"]
    assert {r["family"] for r in tool} == set(_EXPECTED_IDS)
    for r in tool:
        assert r["weights"] is False and r["pullable"] is False
    only_tool = cm.collect(["tool"], show_all=True)[1]
    assert only_tool and all(r["capability"] == "tool" for r in only_tool)
    no_tool = cm.collect(["video"], show_all=True)[1]
    assert all(r["capability"] != "tool" for r in no_tool)
    text = cm.render_missing(cat, cm._hw(), rows)
    assert "工具权重" in text and "绝不自动下载" in text
    assert "rife49.pth" in text and "SHIGUANG_REALESRGAN_PATH" in text


def test_check_models_pull_refuses_tool_weights(capsys) -> None:
    """--pull 命中工具 id ⇒ 拒绝（rc=1）+ 自取指引，绝不触发下载。"""
    cm = _load_check_models()
    rc = cm.do_pull("rife49", yes=True)
    assert rc == 1
    err = capsys.readouterr().err
    assert "绝不自动下载" in err and "rife49.pth" in err


def test_panel_tool_row_pull_guard_offscreen(monkeypatch) -> None:
    """Qt 面板：工具行禁「下载选中」（不起线程）；无链接行给自取指引文案。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["tool-weights-test"])
    spec = dict(TW.TOOL_WEIGHTS["realesrgan_x4plus"])
    spec["probe"] = lambda: ""
    monkeypatch.setitem(TW.TOOL_WEIGHTS, "realesrgan_x4plus", spec)
    from app.modules.lego.local_models_panel import LocalModelsPanel

    p = LocalModelsPanel()
    idx = next(i for i, r in enumerate(p._rows) if r["id"] == "realesrgan_x4plus")
    p._table.selectRow(idx)
    # 工具行有已核链接 ⇒ 正常长出社区按钮；但「下载选中」必须被拦（不起线程）
    assert p._src_box.count() >= 1
    p._pull_selected()
    assert p._btn_pull.isEnabled(), "工具行不许启动下载线程"
    assert "check_models" in p._summary.text() and "自取" in p._summary.text()
    # 无链接的工具行（模拟未来未核项）⇒ 给自取指引文案，不留旧按钮
    spec2 = dict(TW.TOOL_WEIGHTS["lama_dilated"])
    spec2["probe"] = lambda: ""
    spec2["sources"] = []
    monkeypatch.setitem(TW.TOOL_WEIGHTS, "lama_dilated", spec2)
    p.refresh()
    idx2 = next(i for i, r in enumerate(p._rows) if r["id"] == "lama_dilated")
    p._table.selectRow(idx2)
    assert p._src_box.count() == 0
    assert "check_models" in p._src_label.text()
    del app
