# -*- coding: utf-8 -*-
"""核心模块可导入性守卫（2026-10-06，同类事故第 3 次后加）。

**为什么要有它**
================
`app/version.py` 被 `app/__init__.py` 导入 ⇒ **它语法一坏，全仓 import 全崩**。
实测踩过 3 次同一个坑：往中文长字符串里塞**直引号**（`"..."` 套 `"..."`）导致
`SyntaxError: Perhaps you forgot a comma?`：
  · V4.40.33（LUT 轮）：`version.py` 字符串里的引号
  · V4.40.36（守卫轮）：守卫 docstring 里的直引号
  · V4.40.40（桌宠轮）：`version.py` 描述里的 `"不许随机动"`
后两次的**代价被放大**：不是"这条检查失败"，而是**所有 import app 的检查集体报错**
（PINYIN / GENLEDGER / LUTBAKE / VIDEOGEN 一起红），排查时极易误判成"环境坏了"。

**本守卫做两件事**（都是一行 AST + 一次 import，秒级）：
  ① `ast.parse` 校验核心文件语法（**先于**任何 import，报错定位更直白）；
  ② 真 import 一次 `app.version` 并断言 `__version__` / `VERSION_INFO` 可用
     （语法之外还挡住"漏写字段"）。

**给未来的自己**：写中文长字符串时，内层引号一律用「」『』，**不要**用直引号；
写完 `version.py` **必须**立刻跑一次 `python -c "import app.version"`。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 被广泛 import 的"地基"文件：坏了会连带一大片
CORE_FILES = [
    os.path.join("app", "version.py"),
    os.path.join("app", "__init__.py"),
]

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def check_syntax() -> None:
    for rel in CORE_FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            _fail(f"① 文件缺失：{rel}")
            continue
        try:
            # ⚠️ 用 utf-8-sig 读：本项目 app/__init__.py 带 BOM，
            #   真实 import 会正确处理 BOM，ast.parse 若用 utf-8 会误报 U+FEFF。
            ast.parse(open(p, encoding="utf-8-sig").read(), filename=rel)
        except SyntaxError as e:
            _fail(f"① {rel} 语法错误（第 {e.lineno} 行）：{e.msg}"
                  f" —— 提示：中文长串里的直引号要改成「」")


def check_importable() -> None:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        from app.version import VERSION_INFO, __version__
    except Exception as e:
        _fail(f"② import app.version 失败：{type(e).__name__}: {e}")
        return
    if not isinstance(__version__, str) or not __version__.strip():
        _fail("② __version__ 不是非空字符串")
    if not isinstance(VERSION_INFO, dict) or "major" not in VERSION_INFO:
        _fail("② VERSION_INFO 缺 major（版本元信息结构被改）")


def main() -> int:
    print("=" * 62)
    print("核心模块可导入性守卫")
    print("=" * 62)
    for fn in (check_syntax, check_importable):
        try:
            fn()
        except Exception as e:
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")
    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK 核心文件语法与导入均正常（版本号可读）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
