"""注册表模块必须能 import，否则导航栏会缺项（AI 画布曾因 IndentationError 静默消失）。"""
from __future__ import annotations

import importlib
import py_compile
from pathlib import Path

import pytest

from app.modules.lego.module_registry import _MODULE_DEFINITIONS


LEGO_DIR = Path(__file__).resolve().parents[1] / "modules" / "lego"


def test_registry_python_files_compile():
    errors = []
    for defn in _MODULE_DEFINITIONS:
        rel = defn["import_module"].lstrip(".")
        path = LEGO_DIR / f"{rel}.py"
        if not path.is_file():
            errors.append(f"missing {path}")
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("defn", _MODULE_DEFINITIONS, ids=lambda d: d["id"])
def test_registry_class_importable(defn):
    mod = importlib.import_module(defn["import_module"], package="app.modules.lego")
    cls = getattr(mod, defn["import_class"], None)
    assert cls is not None, f"{defn['id']}: 缺少 {defn['import_class']}"
    assert defn["id"] != "characters" or getattr(cls, "module_name", "") == "AI 画布"
