#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 guard_base（四个守护的共享基座）—— 自包含，不依赖 pytest / Qt。

跑法: python _verify/check_guard_base.py

覆盖基座全部导出函数，重点是**边界/脏数据**（基座被四个模块共用，一个 bug 影响四处）：
  1. normalize_text（list 归一 / 去空白 / None / 嵌套）
  2. normalize_traits（空值不收录 / 非 dict）
  3. stable_fingerprint（稳定 / 内容变则变 / 长度参数 / 空）
  4. diff_traits（定位 / 前后指纹 / reason / 空输入）
  5. to_float（非法 / NaN / None）
  6. extract_json_array（markdown 包裹 / 非数组 / 脏元素 / 空）
  7. merge_unique（去重保序 / 空值跳过）
"""

from __future__ import annotations

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []
TOTAL = 0


def check(desc: str, cond: bool) -> None:
    global TOTAL
    TOTAL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILS.append(desc)


def _load(name: str, *parts: str):
    """加载 app/core/ai 下的模块（伪包方式，使相对导入可用且不 import app 包）。"""
    import types
    ai_dir = os.path.join(ROOT, "app", "core", "ai")
    pkg = "_sg_ai_pkg"
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [ai_dir]
        sys.modules[pkg] = p
    fname = parts[-1]
    modname = fname[:-3] if fname.endswith(".py") else fname
    full = f"{pkg}.{modname}"
    spec = importlib.util.spec_from_file_location(full, os.path.join(ai_dir, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    gb = _load("_guard_base", "app", "core", "ai", "guard_base.py")

    # ── 1. normalize_text ──
    check("list 归一为逗号串", gb.normalize_text(["a", "b"]) == "a,b")
    check("去所有空白", gb.normalize_text("  x y ") == "xy")
    check("None → 空", gb.normalize_text(None) == "")
    check("数字转串", gb.normalize_text(12) == "12")
    check("嵌套 list", gb.normalize_text(["a", ["b", "c"]]) == "a,b,c")
    check("list 中空值跳过", gb.normalize_text(["a", "", None, "b"]) == "a,b")

    # ── 2. normalize_traits ──
    t = gb.normalize_traits({"name": "林晚", "gender": "女", "x": ""}, ("name", "gender", "x", "y"))
    check("只收敛非空字段", t == {"name": "林晚", "gender": "女"})
    check("非 dict → {}", gb.normalize_traits(None, ("a",)) == {})
    check("空 dict → {}", gb.normalize_traits({}, ("a",)) == {})

    # ── 3. stable_fingerprint ──
    f1 = gb.stable_fingerprint({"a": "1", "b": "2"})
    f2 = gb.stable_fingerprint({"b": "2", "a": "1"})   # 键序无关
    check("同内容指纹稳定（键序无关）", f1 == f2 and len(f1) == 12)
    check("改内容指纹变", gb.stable_fingerprint({"a": "1", "b": "3"}) != f1)
    check("长度参数生效", len(gb.stable_fingerprint({"a": "1"}, length=8)) == 8)
    check("空指纹为空", gb.stable_fingerprint({}) == "" and gb.stable_fingerprint(None) == "")

    # ── 4. diff_traits ──
    d0 = gb.diff_traits({"a": "1"}, {"a": "1"})
    check("无差异 → ok", d0["ok"] is True and d0["drifted"] == [])
    d1 = gb.diff_traits({"a": "1", "b": "2"}, {"a": "9", "b": "2"})
    check("定位漂移项", d1["drifted"] == ["a"])
    check("detail 有前后值", d1["detail"]["a"] == {"before": "1", "after": "9"})
    check("前后指纹不同", d1["fingerprint_before"] != d1["fingerprint_after"])
    check("reason 非空", bool(d1["reason"]))
    check("新增键算漂移", gb.diff_traits({"a": "1"}, {"a": "1", "b": "2"})["drifted"] == ["b"])
    check("空输入不崩", gb.diff_traits(None, None)["ok"] is True)

    # ── 5. to_float ──
    check("正常转换", gb.to_float("1.5") == 1.5)
    check("非法 → 0", gb.to_float("abc") == 0.0)
    check("None → 0", gb.to_float(None) == 0.0)
    check("NaN → 0", gb.to_float(float("nan")) == 0.0)
    check("负值保留", gb.to_float("-2") == -2.0)

    # ── 6. extract_json_array ──
    rows = gb.extract_json_array('[{"a": 1}, {"b": 2}]')
    check("解析纯数组", len(rows) == 2)
    check("容忍 markdown 包裹", len(gb.extract_json_array('```json\n[{"a":1}]\n```')) == 1)
    check("容忍前后废话", len(gb.extract_json_array('好的，结果如下：[{"a":1}] 完毕')) == 1)
    check("非数组 → []", gb.extract_json_array('{"a": 1}') == [])
    check("脏元素被过滤", gb.extract_json_array('[{"a":1}, 5, "x"]') == [{"a": 1}])
    check("空 → []", gb.extract_json_array("") == [] and gb.extract_json_array(None) == [])
    check("非 JSON → []", gb.extract_json_array("完全不是 JSON") == [])

    # ── 7. merge_unique ──
    check("去重保序", gb.merge_unique(["b", "a", "b", "c", "a"]) == ["b", "a", "c"])
    check("跳过空值", gb.merge_unique(["a", "", None, "  ", "b"]) == ["a", "b"])
    check("空输入 → []", gb.merge_unique(None) == [] and gb.merge_unique([]) == [])

    # ── 汇总 ──
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} / {TOTAL}")
        for x in FAILS:
            print(f"  - {x}")
        return 1
    print(f"ALL PASS ({TOTAL} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
