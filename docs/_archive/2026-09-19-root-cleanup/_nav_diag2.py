# -*- coding: utf-8 -*-
"""真实 MainWindow 环境下导航栏折叠态复现。

与 _nav_diag.py（独立 NavigationBar）不同：本脚本加载真实 MainWindow，
复现 app/main_qt6.py 的启动环境（Fusion 样式 + YaHei 10pt + 真实 QSettings），
分两次截图：
  ① 启动态：nav_mode 按用户持久化值（compact）
  ② 字体应用态：模拟设置面板保存（_apply_font_settings 递归 setFont YaHei 14pt）
输出 PNG + 几何/字体信息，用于对比定位「折叠后图标不显示」。
"""
import os
import sys

sys.path.insert(0, r"D:\拾光剪影")
os.chdir(r"D:\拾光剪影")

OUT_LINES = []


def out(*args):
    line = " ".join(str(a) for a in args)
    OUT_LINES.append(line)


from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

# 沙箱黑名单：app.core.config_manager / auth / gpu_acceleration 会探测 wmic，
# 在诊断里短路掉（抛 FileNotFoundError 走原有 except 分支），避免沙箱拦截整条命令。
import subprocess as _sp

_orig_run = _sp.run


def _safe_run(*args, **kwargs):
    cmd = args[0] if args else kwargs.get("args", [])
    if cmd and "wmic" in str(cmd[0]).lower():
        raise FileNotFoundError("wmic disabled in sandbox diag")
    return _orig_run(*args, **kwargs)


_sp.run = _safe_run

app = QApplication(sys.argv)
app.setStyle("Fusion")  # 复现 app/main_qt6.py
from PyQt6.QtGui import QFont
app.setFont(QFont("Microsoft YaHei", 10))  # 复现 main_qt6 启动字体

out("[env] Fusion + YaHei/10pt, DPR =", app.devicePixelRatio())

from app.modules.lego.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.show()
out("[win] shown, size =", win.width(), "x", win.height())

STATE = {"phase": 0}


def dump_nav(tag):
    nav = win._nav_bar
    out(f"---- {tag} ----")
    out("nav.width =", nav.width(), "fixedW =", nav.width(),
        "isVisible =", nav.isVisible(), "collapsed =", nav.is_collapsed())
    lay = nav.layout()
    if lay is not None:
        m = lay.contentsMargins()
        out("nav.layout.margins =", m.left(), m.top(), m.right(), m.bottom())
    for mid, btn in nav._buttons.items():
        g = btn.geometry()
        fi = btn.fontInfo()
        f = btn.font()
        out(
            f"btn[{mid}] geo=({g.x()},{g.y()},{g.width()}x{g.height()})",
            f"text={btn.text()!r}",
            f"fontInfo={fi.family()}/{fi.pointSize()}pt/{fi.pixelSize()}px",
            f"font.family={f.family()}/{f.pointSize()}pt",
            f"visible={btn.isVisible()}",
            f"minW={btn.minimumWidth()} maxW={btn.maximumWidth()}",
        )
    tb = nav._toggle_btn
    out("toggle geo =", tb.geometry(), "text =", repr(tb.text()),
        "visible =", tb.isVisible())


def shot1():
    dump_nav("① 启动态（nav_mode=用户持久化值）")
    STATE["phase"] = 1
    win._nav_bar.grab().save(r"D:\拾光剪影\_nav_real_1_startup.png")
    out("[shot1] saved")

    # ② 模拟设置面板保存：_apply_font_settings 递归 setFont（用户存的是 YaHei/14）
    settings = {"font_size": 14, "font_family": "Microsoft YaHei"}
    try:
        win._apply_font_settings(settings)
        out("[phase2] _apply_font_settings(YaHei/14) 已执行")
    except Exception as e:  # noqa: BLE001
        out("[phase2] _apply_font_settings 失败:", e)
    QTimer.singleShot(800, shot2)


def shot2():
    dump_nav("② 字体应用态（递归 setFont YaHei/14pt 之后）")
    win._nav_bar.grab().save(r"D:\拾光剪影\_nav_real_2_fontapplied.png")
    out("[shot2] saved")
    with open(r"D:\拾光剪影\_nav_diag2_out.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(OUT_LINES))
    print("DIAG2_DONE")
    app.quit()


QTimer.singleShot(2500, shot1)  # 等主题/懒加载全部落地
app.exec()
