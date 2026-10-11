"""
设置面板 (SettingsDialog)
==========================================

对标 AI-Canvas-tauri SettingsPanel.tsx + settings.css，重做「外观」「常规」两页，
视觉 1:1 对齐用户提供的 AI Canvas 截图（外观预设卡墙 / 主题模式 / 6 开关分组）。

Tab 结构（左侧 176px 导航 + 右侧 QStackedWidget）：
    外观   —— 头部(标题+主题chip+自动保存) · 导入/导出/保存预设 · 节点预览大图
              · 外观预设 2×2 卡墙 · 主题模式 3 段
    常规   —— 节点工具栏分段 · 画布笔记工具栏 · 素材引用 · 节点标题 · 窗口外观
              · 图形与性能 · 侧边栏（7 个分组，开关卡直抄 .sidebar-pref-card）
    存储 / ComfyUI / MCP / 关于

设计纪律：
- 单例(SettingsDialog.instance())，避免重复弹窗
- 所有颜色走 theme_tokens，自绘控件在 set_theme() 重绘
- 设置落 QSettings(拾光剪影 / Settings)
- 开关卡直抄 .sidebar-pref-card（整卡可点 + iOS 开关 + 迷你预览）

V4.43.1 任务 #286
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QSettings, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QPushButton,
    QListWidget, QListWidgetItem, QStackedWidget, QFrame, QScrollArea,
    QGridLayout,
)

from app.modules.lego.theme_manager import ThemeManager
from app.modules.lego.settings_widgets import (
    PreferenceCard, SegmentedControl, PresetCard, AppearancePreview,
)

logger = logging.getLogger("AI短剧编辑器.settings_panel")


# ═══════════════════════════════════════════════════════════════
# 设置键（单源真相，便于守卫 + 防拼写漂移）
# ═══════════════════════════════════════════════════════════════
# 外观
SETTING_KEY_APPEARANCE_PRESET = "appearance/preset"           # 外观预设 id
SETTING_KEY_THEME_MODE = "appearance/theme_mode"              # dark / light / system
# 外观 → 画布（V4.43.2：画布 canvasBackgrounds.ts 轮询 /host/canvas-settings 读取）
# 存 JSON 文件而非 QSettings：① 沙箱/无注册表权限环境也能写；② 画布通道可直接读文件；
# ③ 与项目既有「注册表 + JSON 双保险」思路一致。字段名即本组常量。
SETTING_KEY_CANVAS_BACKGROUND = "canvas_background"  # 画布背景 id
SETTING_KEY_CANVAS_THEME = "canvas_theme"            # 画布主题 dark/light（已解析）
SETTING_KEY_SETTINGS_REVISION = "revision"           # 递增版本号，驱动画布增量应用

#: 画布外观设置文件（单一真相源，画布经 /host/canvas-settings 读取）
CANVAS_APPEARANCE_FILE = (
    Path(__file__).resolve().parents[3] / "data" / "canvas_appearance.json"
)
# 常规 — 开关
SETTING_KEY_NODE_TOOLBAR_MODE = "ui/node_toolbar_mode"        # icons / icons-and-text
SETTING_KEY_NOTE_TOOLBAR = "ui/canvas_note_toolbar_visible"   # 画布笔记工具栏
SETTING_KEY_AUTO_REF_ASSET = "canvas/auto_ref_asset"          # 连线后自动 @ 素材
SETTING_KEY_NODE_TITLE = "ui/node_label_visible"              # 节点标题
SETTING_KEY_GLASS_FRAME = "ui/window_glass_frame"             # 窗口玻璃外框
SETTING_KEY_PERFORMANCE_MODE = "perf/performance_mode"        # 性能模式
SETTING_KEY_SIDEBAR_FLOATING = "ui/sidebar_floating"          # 侧边栏悬浮

ALL_PREFERENCE_KEYS = [
    SETTING_KEY_NOTE_TOOLBAR,
    SETTING_KEY_AUTO_REF_ASSET,
    SETTING_KEY_NODE_TITLE,
    SETTING_KEY_GLASS_FRAME,
    SETTING_KEY_PERFORMANCE_MODE,
    SETTING_KEY_SIDEBAR_FLOATING,
]


def _read_bool_setting(key: str, default: bool = True) -> bool:
    try:
        return bool(QSettings("拾光剪影", "Settings").value(key, default, type=bool))
    except Exception:
        return default


def _write_bool_setting(key: str, value: bool) -> None:
    try:
        s = QSettings("拾光剪影", "Settings")
        s.setValue(key, bool(value))
        s.sync()
    except Exception as e:
        logger.debug("写入设置失败 %s: %s", key, e)


def _read_str_setting(key: str, default: str = "") -> str:
    try:
        return str(QSettings("拾光剪影", "Settings").value(key, default))
    except Exception:
        return default


def _write_str_setting(key: str, value: str) -> None:
    try:
        s = QSettings("拾光剪影", "Settings")
        s.setValue(key, value)
        s.sync()
    except Exception as e:
        logger.debug("写入设置失败 %s: %s", key, e)


# ═══════════════════════════════════════════════════════════════
# 外观预设（4 个，对齐截图：深色 / 浅色 / 太阳系 / 磨砂曝光）
# ═══════════════════════════════════════════════════════════════
# (id, 名称, 预览底色, 强调色, 对应画布背景 id, 对应画布主题)
# V4.43.2：4 个预设**全部落地为真实画布背景**（移植 AI-Canvas backgroundOptions.ts），
#          不再是视觉占位 —— 点击即写 QSettings + 递增 revision，画布轮询到后应用。
PRESETS = [
    ("dark",          "深色",     "#0a0a0f", "#6366f1", "default",       "dark"),
    ("light",         "浅色",     "#F4F6FB", "#7280E4", "off-white",     "light"),
    ("solar-system",  "太阳系",   "#1a1030", "#a855f7", "solar-system",  "dark"),
    ("frosted-glass", "磨砂曝光", "#EEF1F8", "#6ECBAA", "frosted-glass", "light"),
]


def push_canvas_appearance(canvas_bg: str, theme: str) -> None:
    """把外观预设下发到画布（写 JSON + 递增 revision）。

    画布 `canvasBackgrounds.ts` 每 2.5s 轮询 `GET /host/canvas-settings`，
    只在 revision 变化时应用 —— 这样不会覆盖用户在画布内的本地主题切换。
    """
    try:
        payload = {
            "revision": 0,
            "canvas_background": str(canvas_bg),
            "theme": "light" if theme == "light" else "dark",
        }
        f = CANVAS_APPEARANCE_FILE
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            try:
                payload["revision"] = int(
                    json.loads(f.read_text(encoding="utf-8")).get("revision", 0)
                )
            except Exception:
                payload["revision"] = 0
        payload["revision"] += 1
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
        logger.debug("外观预设已下发画布: %s", payload)
    except Exception as e:
        logger.debug("下发画布外观失败: %s", e)

THEME_MODE_OPTIONS = [
    ("dark",   "☾  深色"),
    ("light",  "☀  浅色"),
    ("system", "🖥  跟随系统"),
]


# ═══════════════════════════════════════════════════════════════
# 主面板
# ═══════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    """设置主面板（V4.43.1）

    信号：
        preference_changed(str, bool) — 开关变化 (key, value)
        appearance_changed(str)       — 外观预设 / 主题模式变化
    """

    preference_changed = pyqtSignal(str, bool)
    appearance_changed = pyqtSignal(str)

    _instance: Optional["SettingsDialog"] = None

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(940, 660)
        self.setObjectName("settingsDialog")
        self.setProperty("theme", ThemeManager.instance().current_theme)

        self._pref_cards: list[PreferenceCard] = []
        self._preset_cards: list[PresetCard] = []

        self._build_ui()

    @classmethod
    def instance(cls, parent: Optional[QWidget] = None) -> "SettingsDialog":
        if cls._instance is None:
            cls._instance = cls(parent)
        return cls._instance

    # ─────────── 骨架 ───────────
    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左导航
        nav_holder = QWidget()
        nav_holder.setObjectName("settingsNavHolder")
        nav_holder.setFixedWidth(184)
        nav_layout = QVBoxLayout(nav_holder)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        nav_header = QLabel("⚙  设置")
        nav_header.setObjectName("settingsNavHeader")
        nav_header.setFixedHeight(56)
        nav_layout.addWidget(nav_header)

        self._nav = QListWidget()
        self._nav.setObjectName("settingsNav")
        self._nav.setSpacing(2)
        nav_layout.addWidget(self._nav)
        layout.addWidget(nav_holder)

        # 右内容
        self._stack = QStackedWidget()
        self._stack.setObjectName("settingsStack")
        layout.addWidget(self._stack, stretch=1)

        self._add_tab("🎨", "外观", self._build_appearance_page())
        self._add_tab("🎛", "常规", self._build_general_page())
        self._add_tab("🗂", "存储", self._build_storage_page())
        self._add_tab("🖥", "ComfyUI", self._placeholder_page("ComfyUI 安装目录与运行配置（已迁移至专门设置面板）"))
        self._add_tab("🔌", "MCP", self._placeholder_page("MCP 控制：端口 / 令牌 / 客户端配置片段（已迁移至专门设置面板）"))
        self._add_tab("❓", "关于", self._build_about_page())

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

    def _add_tab(self, icon: str, label: str, page: QWidget) -> None:
        item = QListWidgetItem(f"{icon}   {label}")
        item.setSizeHint(QSize(184, 44))
        self._nav.addItem(item)
        self._stack.addWidget(page)

    @staticmethod
    def _wrap_scroll(inner: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("settingsContent")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    @staticmethod
    def _section_title(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("sectionTitle")
        return lbl

    # ═══════════ 外观页（对齐截图 1）═══════════
    def _build_appearance_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        current_preset = _read_str_setting(SETTING_KEY_APPEARANCE_PRESET, "dark")
        theme_label = "深色" if not ThemeManager.instance().is_light else "浅色"

        # ── 头部：标题 + chip + 自动保存 ──
        head = QHBoxLayout()
        head_icon = QLabel("✨")
        head_icon.setObjectName("appearanceHeadIcon")
        head.addWidget(head_icon)
        head.addWidget(self._title_label("外观"))
        chip = QLabel(theme_label)
        chip.setObjectName("chipBrand")
        head.addWidget(chip)
        head.addStretch(1)
        auto_badge = QLabel("● 自动保存")
        auto_badge.setObjectName("autoSaveBadge")
        head.addWidget(auto_badge)
        layout.addLayout(head)

        sub = QLabel("外观预设包含画布、节点、连接线、连接手柄和所有页面配色")
        sub.setObjectName("settingsPageHint")
        layout.addWidget(sub)

        # ── 工具按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for icon, label, obj in [
            ("⬇", "导入", "ghostBtn"),
            ("⬆", "导出", "ghostBtn"),
            ("💾", "保存预设", "ghostBtn"),
        ]:
            b = QPushButton(f"{icon}  {label}")
            b.setObjectName(obj)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c, l=label: self._on_appearance_tool(l))
            btn_row.addWidget(b)
        override = QPushButton("🚫  覆盖当前预设")
        override.setObjectName("overrideBtn")
        override.setEnabled(False)
        btn_row.addWidget(override)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # ── 大预览 ──
        self._appearance_preview = AppearancePreview()
        self._appearance_preview.set_theme_label(theme_label)
        layout.addWidget(self._appearance_preview)

        # ── 外观预设 2×2 ──
        layout.addWidget(self._section_title("外观预设"))
        preset_hint = QLabel("选择、保存或管理完整外观配置")
        preset_hint.setObjectName("sectionHint")
        layout.addWidget(preset_hint)

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (pid, label, swatch, accent, _cgbg, _cgtheme) in enumerate(PRESETS):
            card = PresetCard(pid, label, swatch, accent)
            card.set_active(pid == current_preset)
            card.activated.connect(self._on_preset_activated)
            self._preset_cards.append(card)
            grid.addWidget(card, i // 2, i % 2)
        layout.addLayout(grid)

        # ── 主题模式 ──
        layout.addWidget(self._section_title("主题模式"))
        mode_hint = QLabel("选择整套界面的明暗基调")
        mode_hint.setObjectName("sectionHint")
        layout.addWidget(mode_hint)

        saved_mode = _read_str_setting(SETTING_KEY_THEME_MODE,
                                       "light" if ThemeManager.instance().is_light else "dark")
        self._theme_mode = SegmentedControl(THEME_MODE_OPTIONS, saved_mode, height=44)
        self._theme_mode.changed.connect(self._on_theme_mode_changed)
        layout.addWidget(self._theme_mode)

        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    @staticmethod
    def _title_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("settingsBigTitle")
        return lbl

    def _on_appearance_tool(self, label: str) -> None:
        logger.info("外观工具: %s（待接入真实导入导出）", label)

    def _on_preset_activated(self, preset_id: str) -> None:
        entry = next((p for p in PRESETS if p[0] == preset_id), None)
        if entry is None:
            return
        _pid, label, _swatch, _accent, canvas_bg, canvas_theme = entry
        _write_str_setting(SETTING_KEY_APPEARANCE_PRESET, preset_id)
        for card in self._preset_cards:
            card.set_active(card._preset_id == preset_id)
        self._appearance_preview.set_theme_label(label)

        # 1) 主程序主题（画布外的 UI）
        _write_str_setting(SETTING_KEY_THEME_MODE, canvas_theme)
        self._theme_mode.set_current(canvas_theme)
        try:
            ThemeManager.instance().apply_theme(canvas_theme)
        except Exception as e:
            logger.warning("应用预设主题失败: %s", e)
        # 2) 下发到画布（V4.43.2：4 个预设全部落地为真实画布背景）
        push_canvas_appearance(canvas_bg, canvas_theme)
        self.appearance_changed.emit(preset_id)

    def _on_theme_mode_changed(self, mode: str) -> None:
        _write_str_setting(SETTING_KEY_THEME_MODE, mode)
        try:
            ThemeManager.instance().apply_theme(mode)
        except Exception as e:
            logger.warning("应用主题模式失败: %s", e)
        self.appearance_changed.emit(mode)

    # ═══════════ 常规页（对齐截图 2）═══════════
    def _build_general_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(18)

        # ── 节点工具栏（分段） ──
        layout.addWidget(self._section_title("节点工具栏"))
        toolbar_mode = _read_str_setting(SETTING_KEY_NODE_TOOLBAR_MODE, "icons")
        self._toolbar_seg = SegmentedControl(
            [("icons", "○  极简图标"), ("icons-and-text", "▤  图标 + 文本")],
            toolbar_mode, height=40,
        )
        self._toolbar_seg.changed.connect(
            lambda v: _write_str_setting(SETTING_KEY_NODE_TOOLBAR_MODE, v)
        )
        layout.addWidget(self._toolbar_seg)

        # ── 6 个开关分组（直抄 .sidebar-pref-card） ──
        note_card = PreferenceCard(
            SETTING_KEY_NOTE_TOOLBAR, "显示笔记工具栏",
            "在画布左下角显示绘图与笔记工具",
            preview_kind="note_toolbar",
            on_desc="在画布左下角显示绘图与笔记工具",
            off_desc="隐藏工具栏，已有笔记仍可编辑",
            default_value=_read_bool_setting(SETTING_KEY_NOTE_TOOLBAR, True),
        )
        ref_card = PreferenceCard(
            SETTING_KEY_AUTO_REF_ASSET, "连线后自动 @ 素材",
            "新建连线时，将上游素材追加到生成节点的提示词中；已有引用不会重复添加。",
            preview_kind="auto_ref",
            default_value=_read_bool_setting(SETTING_KEY_AUTO_REF_ASSET, True),
        )
        title_card = PreferenceCard(
            SETTING_KEY_NODE_TITLE, "显示节点标题",
            "节点上方显示类型图标与名称，双击可重命名",
            preview_kind="node_title",
            on_desc="节点上方显示类型图标与名称，双击可重命名",
            off_desc="隐藏节点上方的标题栏，画布更简洁",
            default_value=_read_bool_setting(SETTING_KEY_NODE_TITLE, True),
        )
        glass_card = PreferenceCard(
            SETTING_KEY_GLASS_FRAME, "玻璃外框",
            "显示 5px 玻璃带与双层边缘高光",
            preview_kind="glass_frame",
            on_desc="显示 5px 玻璃带与双层边缘高光",
            off_desc="内容贴合窗口边缘，不显示外框",
            default_value=_read_bool_setting(SETTING_KEY_GLASS_FRAME, True),
        )
        perf_card = PreferenceCard(
            SETTING_KEY_PERFORMANCE_MODE, "性能模式",
            "保留完整视觉效果与界面动画",
            preview_kind="perf_mode",
            badge="卡顿或页面显示不全时开启",
            default_value=_read_bool_setting(SETTING_KEY_PERFORMANCE_MODE, False),
        )
        side_card = PreferenceCard(
            SETTING_KEY_SIDEBAR_FLOATING, "悬浮显示",
            "侧边栏停靠在窗口内侧",
            preview_kind="sidebar_floating",
            on_desc="侧边栏半隐于窗口边缘，悬浮在画布之上",
            off_desc="侧边栏停靠在窗口内侧",
            default_value=_read_bool_setting(SETTING_KEY_SIDEBAR_FLOATING, True),
        )

        for section, card in [
            ("画布笔记工具栏", note_card),
            ("素材引用", ref_card),
            ("节点标题", title_card),
            ("窗口外观", glass_card),
            ("图形与性能", perf_card),
            ("侧边栏", side_card),
        ]:
            layout.addWidget(self._section_title(section))
            layout.addWidget(card)
            self._pref_cards.append(card)
            card.toggled.connect(self.preference_changed.emit)

        # 性能模式脚注
        footnote = QLabel(
            "开启后将保存并自动重启，正在运行的任务会中断；"
            "关闭后下次启动恢复原生图形设置。"
        )
        footnote.setObjectName("settingsFootnote")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)

        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    # ═══════════ 其余页 ═══════════
    def _build_storage_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(self._section_title("存储健康"))
        hint = QLabel("空间占用分析 / 回收站清理 / 孤儿文件检测\n（后续版本接入，V4.44.0+）")
        hint.setObjectName("settingsPageHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    def _placeholder_page(self, text: str) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.addWidget(self._section_title(text))
        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    def _build_about_page(self) -> QWidget:
        from app.version import __version__, VERSION_INFO
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        row = QHBoxLayout()
        logo = QLabel("✨")
        f = QFont()
        f.setPointSize(26)
        logo.setFont(f)
        row.addWidget(logo)
        row.addWidget(self._title_label(f"拾光剪影 V{__version__}"))
        row.addStretch(1)
        layout.addLayout(row)

        sub = QLabel(VERSION_INFO.get("codename", ""))
        sub.setObjectName("settingsPageHint")
        layout.addWidget(sub)

        layout.addWidget(self._section_title("核心能力"))
        caps = QHBoxLayout()
        caps.setSpacing(6)
        for icon, label in [("🎬", "剪辑"), ("🎨", "画布"), ("🤖", "Agent"),
                            ("📝", "脚本"), ("🧩", "插件"), ("🔌", "MCP")]:
            c = QLabel(f"{icon} {label}")
            c.setObjectName("chip")
            caps.addWidget(c)
        caps.addStretch(1)
        layout.addLayout(caps)

        layout.addWidget(self._section_title("技术栈"))
        stack = QHBoxLayout()
        stack.setSpacing(6)
        for label in ["PyQt6", "React Flow", "TypeScript", "Vite", "MCP"]:
            c = QLabel(label)
            c.setObjectName("chipMuted")
            stack.addWidget(c)
        stack.addStretch(1)
        layout.addLayout(stack)

        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    # ─────────── 主题 ───────────
    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)
        for w in list(self._pref_cards) + list(self._preset_cards):
            try:
                w.set_theme(theme)
            except Exception as e:
                logger.debug("子控件主题刷新失败 %s: %s", type(w).__name__, e)
        seg = getattr(self, "_toolbar_seg", None)
        if seg is not None:
            seg.set_theme(theme)
        mode = getattr(self, "_theme_mode", None)
        if mode is not None:
            mode.set_theme(theme)
        prev = getattr(self, "_appearance_preview", None)
        if prev is not None:
            prev.update()

    def closeEvent(self, event):
        SettingsDialog._instance = None
        super().closeEvent(event)
