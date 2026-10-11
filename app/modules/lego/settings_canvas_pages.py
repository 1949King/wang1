"""
设置页 AI-Canvas 风格区块 (Settings Canvas Pages)
=================================================

把「外观」「常规」两页顶部的 AI-Canvas 风格区块从 settings_module.py 抽出来
（该文件已 2823 行超规模守卫基线，禁止继续变大 —— 见 _verify/check_file_size.py）。

提供两个构建函数 + 一个共享的「主题模式 → 既往下拉」桥接：
- build_appearance_top_block(mod) → 外观页顶部（头部 + 工具按钮 + 大预览 + 预设卡墙 + 主题模式）
- build_general_top_block(mod)    → 常规页顶部（节点工具栏分段 + 6 个 .sidebar-pref-card 开关）
- apply_theme_mode_combo(mod, mode) → 把 dark/light/system 同步到既有 _theme_combo（保留既有逻辑）

视觉 1:1 对齐用户提供的 AI Canvas 设置截图。控件直抄：
- PresetCard / AppearancePreview / SegmentedControl / PreferenceCard（settings_widgets.py）
- 开关卡 = .sidebar-pref-card（88×52 迷你预览 + iOS 开关）

V4.43.4 任务 #288
"""
from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QFrame,
)

from app.modules.lego.settings_widgets import (
    AppearancePreview, PresetCard, SegmentedControl, PreferenceCard,
)
from app.modules.lego.settings_panel import (
    PRESETS, THEME_MODE_OPTIONS,
    SETTING_KEY_APPEARANCE_PRESET, SETTING_KEY_THEME_MODE,
    SETTING_KEY_CANVAS_BACKGROUND,
    SETTING_KEY_NODE_TOOLBAR_MODE, SETTING_KEY_NOTE_TOOLBAR, SETTING_KEY_AUTO_REF_ASSET,
    SETTING_KEY_NODE_TITLE, SETTING_KEY_GLASS_FRAME, SETTING_KEY_PERFORMANCE_MODE,
    SETTING_KEY_SIDEBAR_FLOATING,
    _read_bool_setting, _read_str_setting, _write_str_setting,
    push_canvas_appearance,
)

logger = logging.getLogger("AI短剧编辑器.settings_canvas_pages")


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("sectionTitle")
    return lbl


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("sectionHint")
    return lbl


def _hr() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet("QFrame { color: #333333; }")
    return sep


# ═══════════════════════════════════════════════════════════════
# 主题模式 → 既往下拉桥接（mod._theme_combo → _on_theme_changed → settings_changed）
# ═══════════════════════════════════════════════════════════════
def apply_theme_mode_combo(mod, mode: str) -> None:
    """把 dark/light/system 同步到既有 _theme_combo，复用其 _on_theme_changed 全链路"""
    idx = {"dark": 0, "light": 1, "system": 2, "auto": 2}.get(mode, 0)
    combo = getattr(mod, "_theme_combo", None)
    if combo is not None and 0 <= idx < combo.count():
        combo.setCurrentIndex(idx)
    else:
        # 兜底：直接应用（分段控件早于 combo 存在时）
        try:
            from app.modules.lego.theme_manager import ThemeManager
            ThemeManager.instance().apply_theme("auto" if mode == "system" else mode)
        except Exception as e:
            logger.debug("兜底应用主题失败: %s", e)


def on_preset_activated(mod, preset_id: str) -> None:
    """外观预设点击 → 主程序主题 + 画布背景（V4.43.4：4 个预设 2×2 卡墙）

    V4.43.4：PRESETS 是 8 元组（id, label, swatch, accent, canvas_bg,
    canvas_theme, node_kind, chip_text）。custom 不在 4 套内，保留
    canvas_bg 通路以备扩展。
    """
    entry = next((p for p in PRESETS if p[0] == preset_id), None)
    if entry is None:
        return
    _pid, label, _swatch, _accent, canvas_bg, canvas_theme, _node_kind, _chip_text = entry

    # V4.43.4：custom 通路保留（4 套不含 custom，但保留自定义背景逻辑）
    image_b64 = None
    if preset_id == "custom":
        from app.modules.lego.settings_panel import _load_current_image_b64
        image_b64 = _load_current_image_b64()

    _write_str_setting(SETTING_KEY_APPEARANCE_PRESET, preset_id)
    for card in getattr(mod, "_preset_cards", []):
        card.set_active(card._preset_id == preset_id)
    prev = getattr(mod, "_appearance_preview", None)
    if prev is not None:
        prev.set_theme_label(label)
        prev.set_preset_id(preset_id)

    # 1) 主程序主题（画布外的 UI）
    _write_str_setting(SETTING_KEY_THEME_MODE, canvas_theme)
    seg = getattr(mod, "_theme_mode_seg", None)
    if seg is not None:
        seg.set_current(canvas_theme)
    apply_theme_mode_combo(mod, canvas_theme)
    # 2) 下发到画布（画布 canvasBackgrounds.ts 轮询应用；custom 带 image_b64）
    push_canvas_appearance(canvas_bg, canvas_theme, image_b64=image_b64)
    logger.info("外观预设 %s → 画布背景 %s / 主题 %s", preset_id, canvas_bg, canvas_theme)


def on_theme_mode_changed(mod, mode: str) -> None:
    """主题模式分段控件 → 驱动既有 _theme_combo + 同步画布主题（背景不变）"""
    _write_str_setting(SETTING_KEY_THEME_MODE, mode)
    apply_theme_mode_combo(mod, mode)
    resolved = mode if mode in ("dark", "light") else (
        "light" if 6 <= datetime.now().hour < 18 else "dark"
    )
    bg = _read_str_setting(SETTING_KEY_CANVAS_BACKGROUND, "default")
    push_canvas_appearance(bg, resolved)


# ═══════════════════════════════════════════════════════════════
# 外观页顶部区块（对齐截图 1）
# ═══════════════════════════════════════════════════════════════
def build_appearance_top_block(mod) -> QWidget:
    """返回外观页顶部 AI-Canvas 风格区块（控件挂到 mod：_preset_cards/_theme_mode_seg/_appearance_preview）"""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    current_preset = _read_str_setting(SETTING_KEY_APPEARANCE_PRESET, "dark")
    theme_label = "浅色" if mod._is_light_theme() else "深色"

    # 头部
    head = QHBoxLayout()
    head_icon = QLabel("✨")
    head_icon.setStyleSheet("font-size: 20px;")
    head.addWidget(head_icon)
    head_title = QLabel("外观")
    head_title.setObjectName("settingsBigTitle")
    head.addWidget(head_title)
    head_chip = QLabel(theme_label)
    head_chip.setObjectName("chipBrand")
    head.addWidget(head_chip)
    head.addStretch(1)
    auto_badge = QLabel("● 自动保存")
    auto_badge.setObjectName("autoSaveBadge")
    head.addWidget(auto_badge)
    layout.addLayout(head)

    sub = QLabel("外观预设包含画布、节点、连接线、连接手柄和所有页面配色")
    sub.setObjectName("settingsPageHint")
    layout.addWidget(sub)

    # 工具按钮
    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    for icon, label in [("⬇", "导入"), ("⬆", "导出"), ("💾", "保存预设")]:
        b = QPushButton(f"{icon}  {label}")
        b.setObjectName("ghostBtn")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _c, l=label: logger.info("外观工具: %s", l))
        btn_row.addWidget(b)
    override = QPushButton("🚫  覆盖当前预设")
    override.setObjectName("overrideBtn")
    override.setEnabled(False)
    btn_row.addWidget(override)
    btn_row.addStretch(1)
    layout.addLayout(btn_row)

    # 大预览
    mod._appearance_preview = AppearancePreview()
    mod._appearance_preview.set_theme_label(theme_label)
    layout.addWidget(mod._appearance_preview)

    # 外观预设 2×2（V4.43.4 复刻开源 4 套卡墙）
    layout.addWidget(_section("外观预设"))
    layout.addWidget(_hint("选择、保存或管理完整外观配置（4 套 2×2 卡墙，与画布一一对应）"))
    mod._preset_cards = []
    grid = QGridLayout()
    grid.setSpacing(12)
    for i, (pid, label, swatch, accent, _cgbg, _cgtheme, node_kind, chip_text) in enumerate(PRESETS):
        card = PresetCard(pid, label, swatch, accent, node_kind=node_kind, chip_text=chip_text)
        card.set_active(pid == current_preset)
        card.activated.connect(lambda p, m=mod: on_preset_activated(m, p))
        mod._preset_cards.append(card)
        # 2×2 网格
        grid.addWidget(card, i // 2, i % 2)
    layout.addLayout(grid)

    # 主题模式 3 段
    layout.addWidget(_section("主题模式"))
    layout.addWidget(_hint("选择整套界面的明暗基调"))
    saved_mode = _read_str_setting(
        SETTING_KEY_THEME_MODE, "light" if mod._is_light_theme() else "dark"
    )
    mod._theme_mode_seg = SegmentedControl(THEME_MODE_OPTIONS, saved_mode, height=44)
    mod._theme_mode_seg.changed.connect(lambda mode, m=mod: on_theme_mode_changed(m, mode))
    layout.addWidget(mod._theme_mode_seg)

    layout.addWidget(_hr())
    return container


# ═══════════════════════════════════════════════════════════════
# 常规页顶部区块（对齐截图 2）
# ═══════════════════════════════════════════════════════════════
def build_general_top_block(mod) -> QWidget:
    """返回常规页顶部 AI-Canvas 风格区块（控件挂到 mod：_toolbar_seg/_general_pref_cards）"""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    # 节点工具栏（分段）
    layout.addWidget(_section("节点工具栏"))
    toolbar_mode = _read_str_setting(SETTING_KEY_NODE_TOOLBAR_MODE, "icons")
    mod._toolbar_seg = SegmentedControl(
        [("icons", "○  极简图标"), ("icons-and-text", "▤  图标 + 文本")],
        toolbar_mode, height=40,
    )
    mod._toolbar_seg.changed.connect(
        lambda v: _write_str_setting(SETTING_KEY_NODE_TOOLBAR_MODE, v)
    )
    layout.addWidget(mod._toolbar_seg)

    # 6 个开关分组（直抄 .sidebar-pref-card）
    mod._general_pref_cards = []
    cards = [
        ("画布笔记工具栏", PreferenceCard(
            SETTING_KEY_NOTE_TOOLBAR, "显示笔记工具栏",
            "在画布左下角显示绘图与笔记工具",
            preview_kind="note_toolbar",
            on_desc="在画布左下角显示绘图与笔记工具",
            off_desc="隐藏工具栏，已有笔记仍可编辑",
            default_value=_read_bool_setting(SETTING_KEY_NOTE_TOOLBAR, True),
        )),
        ("素材引用", PreferenceCard(
            SETTING_KEY_AUTO_REF_ASSET, "连线后自动 @ 素材",
            "新建连线时，将上游素材追加到生成节点的提示词中；已有引用不会重复添加。",
            preview_kind="auto_ref",
            default_value=_read_bool_setting(SETTING_KEY_AUTO_REF_ASSET, True),
        )),
        ("节点标题", PreferenceCard(
            SETTING_KEY_NODE_TITLE, "显示节点标题",
            "节点上方显示类型图标与名称，双击可重命名",
            preview_kind="node_title",
            on_desc="节点上方显示类型图标与名称，双击可重命名",
            off_desc="隐藏节点上方的标题栏，画布更简洁",
            default_value=_read_bool_setting(SETTING_KEY_NODE_TITLE, True),
        )),
        ("窗口外观", PreferenceCard(
            SETTING_KEY_GLASS_FRAME, "玻璃外框",
            "显示 5px 玻璃带与双层边缘高光",
            preview_kind="glass_frame",
            on_desc="显示 5px 玻璃带与双层边缘高光",
            off_desc="内容贴合窗口边缘，不显示外框",
            default_value=_read_bool_setting(SETTING_KEY_GLASS_FRAME, True),
        )),
        ("图形与性能", PreferenceCard(
            SETTING_KEY_PERFORMANCE_MODE, "性能模式",
            "保留完整视觉效果与界面动画",
            preview_kind="perf_mode",
            badge="卡顿或页面显示不全时开启",
            default_value=_read_bool_setting(SETTING_KEY_PERFORMANCE_MODE, False),
        )),
        ("侧边栏", PreferenceCard(
            SETTING_KEY_SIDEBAR_FLOATING, "悬浮显示",
            "侧边栏停靠在窗口内侧",
            preview_kind="sidebar_floating",
            on_desc="侧边栏半隐于窗口边缘，悬浮在画布之上",
            off_desc="侧边栏停靠在窗口内侧",
            default_value=_read_bool_setting(SETTING_KEY_SIDEBAR_FLOATING, True),
        )),
    ]
    for section, card in cards:
        layout.addWidget(_section(section))
        layout.addWidget(card)
        mod._general_pref_cards.append(card)

    footnote = QLabel(
        "开启后将保存并自动重启，正在运行的任务会中断；关闭后下次启动恢复原生图形设置。"
    )
    footnote.setObjectName("settingsFootnote")
    footnote.setWordWrap(True)
    layout.addWidget(footnote)

    # ── V4.43.14：启动恢复（用户要求「写进设置 + 加开关」）──
    # 注意：上面 6 张 PreferenceCard 只 emit toggled、**从未被统一连接**（本次核实），
    # 所以这里**显式自行连接**，不再制造"看起来有开关、其实没接线"的坑。
    from . import session_state as _ss

    layout.addWidget(_section("启动恢复"))
    _resume_card = PreferenceCard(
        _ss.SETTING_KEY_RESUME_SESSION,
        "启动时恢复上次进度",
        "打开软件后直接跳回上次使用的模块与工程",
        preview_kind="perf_mode",
        on_desc="启动直接跳回上次的模块与工程，接着上次继续",
        off_desc="仅保留存档；手动进入该模块时仍可看到上次记录",
        default_value=_read_bool_setting(_ss.SETTING_KEY_RESUME_SESSION, True),
    )
    _resume_card.toggled.connect(
        lambda key, val: _write_str_setting(key, "1" if val else "0")
    )
    layout.addWidget(_resume_card)

    layout.addWidget(_hr())
    return container
