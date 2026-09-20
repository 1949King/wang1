# -*- coding: utf-8 -*-
"""真实 GUI 环境下导航栏折叠态诊断。

复现主窗口环境（app 字体 + ThemeManager 全局 QSS + 真实模块 emoji 图标），
折叠后截图 + 输出每个按钮的几何/文本/字体回退信息，定位「图标不显示」根因。
"""
import os
import sys

sys.path.insert(0, r"D:\拾光剪影")
os.chdir(r"D:\拾光剪影")

OUT_LINES = []


def out(*args):
    line = " ".join(str(a) for a in args)
    OUT_LINES.append(line)


from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

# ── 模拟主窗口环境 ──
f = app.font()
f.setFamily("Microsoft YaHei")
f.setPointSize(14)
app.setFont(f)

try:
    from app.modules.lego.theme_manager import ThemeManager

    ThemeManager.instance().apply_theme("dark")
    out("[env] ThemeManager dark applied")
except Exception as e:  # noqa: BLE001
    out("[env] ThemeManager failed:", e)

from app.modules.lego.main_window import NavigationBar  # noqa: E402

bar = NavigationBar()

# 真实模块定义（与 module_registry 一致的 id/name/icon）
MODULES = [
    ("home", "首页", "🏠"),
    ("editor", "剪辑", "🎬"),
    ("settings", "设置", "⚙️"),
    ("help", "帮助", "❓"),
    ("models", "模型管理", "🤖"),
    ("characters", "AI 画布", "🎨"),
]
for mid, name, icon in MODULES:
    bar.add_module(mid, name, icon)
bar.select_module("models")  # 模拟截图 2：模型广场选中
bar.set_collapsed(True)
bar.show()
app.processEvents()
app.processEvents()

# ── 截图 ──
bar.grab().save(r"D:\拾光剪影\_nav_diag_collapsed.png")
out("[shot] _nav_diag_collapsed.png saved, bar size =", bar.width(), "x", bar.height())

# ── 几何与字体信息 ──
out("nav.width =", bar.width(), " layout.margins =", bar.layout().contentsMargins().left(),
    bar.layout().contentsMargins().top(), bar.layout().contentsMargins().right(),
    bar.layout().contentsMargins().bottom())
for mid, btn in bar._buttons.items():
    fi = btn.fontInfo()
    g = btn.geometry()
    out(
        f"btn[{mid}] geo=({g.x()},{g.y()},{g.width()}x{g.height()})",
        f"text={btn.text()!r}",
        f"fontInfo={fi.family()}/{fi.pointSize()}px",
        f"visible={btn.isVisible()}",
    )

tb = bar._toggle_btn
out("toggle geo =", tb.geometry(), "text =", repr(tb.text()), "visible =", tb.isVisible())

with open(r"D:\拾光剪影\_nav_diag_out.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT_LINES))
print("DIAG_DONE")
app.quit()
