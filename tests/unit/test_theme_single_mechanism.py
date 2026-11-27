"""主题单一机制回归测试（2026-11-27）。

钉死的用户可见行为：
1. 主题只由 ThemeManager.apply_theme 驱动 —— 任何入口（标题栏主题按钮、按时间切换、
   不传 main_window 的调用）切换后，设置页的内联样式都与全局主题一致；
2. 设置页文字与背景的对比度达标（此前浅色下是「浅底浅字」）；
3. 深浅来回切换可逆 —— 切回深色后，各控件的内联样式与切换前完全一致。

背景：此前标题栏主题按钮只刷新全局 QSS，设置页自管的内联样式被落下；
且整段子串替换会自我污染，切回深色后页面留着白框。
"""
import re
from collections import Counter
from types import SimpleNamespace

import pytest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from app.modules.lego import settings_module as settings_mod
from app.modules.lego import theme_manager as theme_mod

ThemeManager = theme_mod.ThemeManager

# 正文文字对比度下限（WCAG AA）
_MIN_CONTRAST = 4.5


class _TempSettings(QSettings):
    """用临时 ini 代替注册表，避免读写用户真实设置"""

    _path = ""

    def __init__(self, *args, **kwargs):
        super().__init__(self._path, QSettings.Format.IniFormat)


def _rgb(color_name):
    color_name = color_name.lstrip("#")
    if len(color_name) == 3:
        color_name = "".join(ch * 2 for ch in color_name)
    return tuple(int(color_name[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(color_name):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(v) for v in _rgb(color_name))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first, second):
    """WCAG 对比度：1.0~21.0，越大越清晰"""
    bright, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def _pixel_counts(widget, rect=None):
    """grab 控件（或其局部区域），统计像素颜色出现次数"""
    image = widget.grab().toImage()
    if rect is not None:
        image = image.copy(*rect)
    return Counter(
        image.pixelColor(x, y).name()
        for y in range(0, image.height(), 2)
        for x in range(0, image.width(), 2)
    )


def _background_and_text(widget, rect=None):
    """返回 (背景色, 文字色)：背景=出现最多；文字=与背景差异明显者中出现最多"""
    counts = _pixel_counts(widget, rect)
    background = counts.most_common(1)[0][0]
    base = _rgb(background)
    text_candidates = [
        (count, name) for name, count in counts.items()
        if sum((a - b) ** 2 for a, b in zip(_rgb(name), base, strict=True)) > 60 ** 2
    ]
    text = max(text_candidates)[1] if text_candidates else background
    return background, text


def _normalize_stylesheet(stylesheet):
    """小写并把 3 位色展开成 6 位，使等价写法可比较"""
    lowered = stylesheet.lower()

    def expand(match):
        return "#" + "".join(ch * 2 for ch in match.group(1))

    return re.sub(r"#([0-9a-f]{3})(?![0-9a-f])", expand, lowered)


def _stylesheet_snapshot(page):
    """记录全部带内联样式控件的样式（可逆性断言用）"""
    return {
        id(widget): _normalize_stylesheet(widget.styleSheet())
        for widget in page.findChildren(QWidget)
        if widget.styleSheet()
    }


def _style_colors(stylesheet, prop_pattern):
    return re.findall(prop_pattern + r"\s*:\s*(#[0-9a-fA-F]{3,6})", stylesheet)


def _assert_settings_page_readable(page):
    """标题 / 说明 / 表格文字（全局 QSS 渲染）与背景对比度达标"""
    title_label = page._header.findChildren(QLabel)[0]
    for widget in (title_label, page._content_stack.widget(0).widget().findChildren(QLabel)[0],
                   page._shortcut_table.horizontalHeader()):
        background, text = _background_and_text(widget)
        assert _contrast(text, background) >= _MIN_CONTRAST, (
            f"{type(widget).__name__} 对比度不足: 文字 {text} / 背景 {background}"
        )


def _assert_inline_text_readable(widget):
    """内联样式控件的文字色与背景色对比度达标。

    背景优先取样式里写的 background；没写则取控件内部实际渲染出的底色（父容器的背景）。
    """
    stylesheet = widget.styleSheet()
    backgrounds = _style_colors(stylesheet, r"background(?:-color)?")
    if not backgrounds:
        backgrounds = [_pixel_counts(widget, (20, 60, 200, 60)).most_common(1)[0][0]]
    for text in _style_colors(stylesheet, r"(?<![-\w])color"):
        for background in backgrounds:
            assert _contrast(text, background) >= _MIN_CONTRAST, (
                f"{type(widget).__name__} 文字 {text} / 背景 {background} 对比度不足"
            )


@pytest.fixture
def settings_page(qt_app, tmp_path, monkeypatch):
    """全局深色已应用 → 再创建设置模块（模拟真实应用的懒加载顺序）"""
    monkeypatch.setattr(ThemeManager, "_instance", None)
    _TempSettings._path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(settings_mod, "QSettings", _TempSettings)
    monkeypatch.setattr(theme_mod, "QSettings", _TempSettings)

    root = QWidget()
    root.resize(1024, 700)
    ThemeManager.instance().apply_theme("dark", main_window=root)
    page = settings_mod.SettingsModule()
    QVBoxLayout(root).addWidget(page)
    # 模拟 MainWindow.refresh_module_themes：ThemeManager 回调 → 模块 set_theme
    root.refresh_module_themes = lambda theme: page.set_theme(theme)
    root.show()
    qt_app.processEvents()
    yield root, page
    root.close()
    root.deleteLater()
    qt_app.processEvents()


def _toggle_page(page):
    return page._content_stack.widget(7)


def test_lazy_created_page_is_readable_on_startup(settings_page):
    """懒加载的设置页创建时全局主题已应用：新控件必须匹配到全局 QSS"""
    _, page = settings_page
    _assert_settings_page_readable(page)


def test_header_style_toggle_keeps_settings_page_in_sync(settings_page):
    """只调 apply_theme（标题栏主题按钮的路径）：设置页内联样式必须跟着变"""
    root, page = settings_page
    ThemeManager.instance().apply_theme("light", main_window=root)

    assert _background_and_text(page._sidebar)[0] == "#ffffff"
    _assert_settings_page_readable(page)
    group = _toggle_page(page).findChildren(QGroupBox)[0]
    intro = [lb for lb in _toggle_page(page).findChildren(QLabel)
             if "padding: 10px" in lb.styleSheet()][0]
    _assert_inline_text_readable(group)
    _assert_inline_text_readable(intro)


def test_entry_without_main_window_also_refreshes(settings_page):
    """不传 main_window 的入口（画布设置页 / 设置面板）同样不能落下设置页"""
    _, page = settings_page
    ThemeManager.instance().apply_theme("light")

    assert _background_and_text(page._sidebar)[0] == "#ffffff"
    _assert_settings_page_readable(page)


def test_light_dark_round_trip_restores_inline_styles(settings_page):
    """深 → 浅 → 深：内联样式必须与最初完全一致（此前切回后留着白框）"""
    root, page = settings_page
    before = _stylesheet_snapshot(page)

    ThemeManager.instance().apply_theme("light", main_window=root)
    ThemeManager.instance().apply_theme("dark", main_window=root)

    assert _stylesheet_snapshot(page) == before
    _assert_settings_page_readable(page)


def test_theme_combo_follows_theme_manager_preference(settings_page):
    """任何入口改了主题后，设置页的主题下拉框显示同步（此前慢一拍或不变）"""
    root, page = settings_page

    ThemeManager.instance().apply_theme("light", main_window=root)
    assert page._theme_combo.currentText() == "浅色主题"

    ThemeManager.instance().apply_theme("dark", main_window=root)
    assert page._theme_combo.currentText() == "深色主题"


def test_main_window_refresh_calls_each_loaded_module(settings_page):
    """MainWindow.refresh_module_themes：逐个调用已加载模块的 set_theme"""
    from app.modules.lego.main_window import MainWindow

    _, page = settings_page
    main_window = SimpleNamespace(
        _modules={"settings": SimpleNamespace(instance=page),
                  "pending": SimpleNamespace(instance=None)},
    )

    MainWindow.refresh_module_themes(main_window, "light")

    assert _background_and_text(page._sidebar)[0] == "#ffffff"
