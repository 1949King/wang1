# -*- coding: utf-8 -*-
"""首启免责提示守卫（2026-10-06）。

这个提示是**告知义务**的一部分（配置用机器指纹派生密钥加密；指纹变化 ⇒ 旧密文解不开、
设备绑定失效）。所以守卫的重点不是"代码好看"，而是**告知不能悄悄消失或被软化**：

  ① **入口必须调用它** —— 写在 `main_qt6._init_modules()` 里（没有它 = 用户永远看不到）。
  ② **免责要点必须在正文里** —— 「指纹 / 加密 / 解不开 / 设备绑定 /
     **与作者本人及本项目无关** / 备份」逐条断言。删掉任何一条，告知就不成立。
  ③ **文本升版机制在位**（`NOTICE_VERSION`）—— 否则改了条款老用户不会重看。
  ④ **不引入新的主题盲区**：弹窗不得用 `setStyleSheet` 内联样式
     （项目不变量 #8：每个内联样式控件都得在 `set_theme()` 里补刷新；这是启动期一次性告知，
     用 QMessageBox 走既有主题即可）。

零依赖：只读源码。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join("app", "core", "first_run_notice.py")
DIALOG = os.path.join("app", "modules", "lego", "notice_dialog.py")
ENTRY = os.path.join("app", "main_qt6.py")

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        _fail(f"文件缺失：{rel}")
        return ""
    return open(p, encoding="utf-8").read()


def check_entry_wires_notice() -> None:
    src = _read(ENTRY)
    if "show_first_run_notice" not in src:
        _fail("① main_qt6 未调用首启提示 ⇒ 用户永远看不到告知")
    if "notice_dialog" not in src:
        _fail("① main_qt6 未引用 notice_dialog")


def check_disclaimer_clauses() -> None:
    """② 告知要点逐条在位（缺一条 = 告知不成立）。"""
    core = _read(CORE)
    for clause in ("指纹", "加密", "解不开", "设备绑定", "与作者本人及本项目无关", "备份"):
        if clause not in core:
            _fail(f"② 首启提示缺少要点「{clause}」（免责告知不成立）")


def check_versioned() -> None:
    core = _read(CORE)
    if "NOTICE_VERSION" not in core or "_NOTICE_VERSION = " in core:
        _fail("③ 缺 NOTICE_VERSION（改条款后老用户不会重看）")
    if "acknowledged_version" not in core:
        _fail("③ 未按版本记录已确认状态")


def check_fail_open() -> None:
    """②b 状态不可读时必须『显示』（宁可多提示，不可漏告知）。"""
    core = _read(CORE)
    body = core.split("def should_show", 1)[-1].split("\ndef ", 1)[0]
    if "return ack < int(version)" not in body:
        _fail("②b should_show 的判据被改（必须『已确认版本 < 当前版本 ⇒ 显示』）")


def _strip_explanation(code: str) -> str:
    """剥掉 docstring 与注释再判断。

    ★ 2026-10-06 又踩一次：`check_no_inline_style` 因**docstring 里提到了** `setStyleSheet`
    而误报。凡「查某个禁用写法」的守卫都可能撞上这个 —— 解释文字里出现禁用词是正常的，
    **误报会逼着大家不敢解释**，比漏报更糟（同 route 守卫里 `/host/xxx` 在注释中的假阳性）。
    """
    import re as _re
    code = _re.sub(r'"""[\s\S]*?"""', "", code)
    code = _re.sub(r"^\s*#.*$", "", code, flags=_re.M)
    return code


def check_no_inline_style() -> None:
    """④ 不新增内联样式（避免主题盲区，见不变量 #8）。"""
    src = _read(DIALOG)
    code = _strip_explanation(src)
    if "setStyleSheet" in code:
        _fail("④ 弹窗用了 setStyleSheet（内联样式是主题盲区；启动期告知用 QMessageBox 即可）")
    if "QMessageBox" not in code:
        _fail("④ 弹窗未用 QMessageBox（自绘控件会引入新的主题维护点）")


def main() -> int:
    print("=" * 62)
    print("首启免责提示守卫")
    print("=" * 62)
    for fn in (check_entry_wires_notice, check_disclaimer_clauses, check_versioned,
               check_fail_open, check_no_inline_style):
        try:
            fn()
        except Exception as e:
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")
    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK 入口已接线 · 免责要点齐备 · 版本化重看 · 失败即显示 · 无内联样式")
    return 0


if __name__ == "__main__":
    sys.exit(main())
