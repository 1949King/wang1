"""
editor_ui_builder_mixin.py
============================
EditorUiBuilderMixin: 从 editor_module.py 抽出的 UI 创建方法。

设计目标（遵循 .trae/rules/2.md §三 架构分层）:
- **最小侵入**: 方法体完全照搬, self 访问不变
- **零回归风险**: 方法签名/实现不变, 只是文件位置改变
- **单一职责**: 本 Mixin 承载 UI 面板创建(工具栏/预览/工具/左侧/特效/贴纸/时间线/参数/角色)
- **不独立实例化**: Mixin 模式, 必须混入宿主类使用

迁移的方法（共 10 个, 约 1255 行）:
1. _create_toolbar (原 L1012-1149, 138 行)
2. _create_preview_panel (原 L1151-1288, 138 行)
3. _create_tools_panel (原 L1290-1365, 76 行)
4. _make_effect_tab (原 L1534-1634, 101 行)
5. _make_sticker_tab (原 L1671-1759, 89 行)
6. _create_left_panel (原 L1761-1852, 92 行)
7. _create_timeline_panel (原 L1854-2050, 197 行)
8. _create_character_tab (原 L6185-6242, 58 行)
9. _refresh_character_panel (原 L6252-6431, 180 行)
10. _create_params_tab (原 L6929-7114, 186 行)

使用方式:
    class EditorModule(..., EditorUiBuilderMixin):
        ...
"""

from typing import Dict, Any, Optional, List
import os
import json
import logging
import subprocess
import threading

from PyQt6.QtCore import Qt, QTimer, QUrl, QEvent, QSize, QPoint
from PyQt6.QtGui import QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics, QShortcut, QKeySequence, QDrag, QPixmap, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QProgressBar, QListWidget,
    QListWidgetItem, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QInputDialog, QTabWidget, QCheckBox, QSlider,
    QTreeWidget, QTreeWidgetItem, QMenu, QToolButton, QApplication, QSizePolicy,
    QFormLayout, QSpacerItem, QToolTip, QStackedLayout
)

logger = logging.getLogger("AI短剧编辑器.editor")


class EditorUiBuilderMixin:
    """UI 创建 Mixin。

    本 Mixin 从 editor_module.py 抽出, 承载编辑器各 UI 面板的创建方法。
    """

    # ======================================================================
    # 抽取自 editor_module.py L1012-1149
    # ======================================================================
    def _create_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        toolbar.setFixedHeight(50)
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(15, 5, 15, 5)
        layout.setSpacing(10)
        
        # 工具栏与快捷键共用 editor_ux_commands 调度
        from app.modules.lego.editor_ux_commands import bind_action
        actions = [
            ("📁 导入", bind_action(self, "import")),
            ("📂 打开", bind_action(self, "open_project")),
            ("💾 保存", bind_action(self, "save_project")),
            ("✂️ 剪切", bind_action(self, "cut")),
            ("📋 复制", bind_action(self, "copy")),
            ("📄 粘贴", bind_action(self, "paste")),
            ("🗑️ 删除", bind_action(self, "delete")),
            ("🔄 撤销", bind_action(self, "undo"), "undo"),
            ("🔄 重做", bind_action(self, "redo"), "redo"),
            ("🧲 收拢", bind_action(self, "close_gap"), "close_gap"),
        ]

        for entry in actions:
            # 兼容 (text, cb) 和 (text, cb, tag) 两种条目
            if len(entry) == 3:
                text, callback, tag = entry
            else:
                text, callback = entry
                tag = ""
            btn = QPushButton(text)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #3a3a3a;
                    border-radius: 6px;
                    padding: 8px 12px;
                    font-size: 13px;
                    font-weight: 500;
                    height: 40px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border-color: #4a4a4a;
                }
                QPushButton:pressed {
                    background-color: #1e6bde;
                    border-color: #1e6bde;
                }
            """)
            btn.clicked.connect(callback)
            # 补短 P0#4：保存撤销/重做按钮引用，便于状态联动
            if tag == "undo":
                self._undo_btn = btn
                btn.setShortcut(QKeySequence("Ctrl+Z"))
                btn.setToolTip("撤销 (Ctrl+Z)")
            elif tag == "redo":
                self._redo_btn = btn
                btn.setShortcut(QKeySequence("Ctrl+Y"))
                btn.setToolTip("重做 (Ctrl+Y)")
            elif tag == "close_gap":
                btn.setToolTip("空隙收拢 / 波纹消隙 (Shift+Delete)")
            layout.addWidget(btn)

        layout.addStretch()
        
        # 内核选择下拉菜单
        kernel_layout = QHBoxLayout()
        kernel_label = QLabel("内核:")
        kernel_label.setStyleSheet("color: #808080; font-size: 13px; padding-right: 8px;")
        self._kernel_combo = QComboBox()
        self._kernel_combo.addItems(["自动选择", "轻量内核", "专业内核"])
        self._kernel_combo.setCurrentIndex(0)  # 默认由统一调度器自主选择内核
        self._kernel_combo.currentIndexChanged.connect(self._on_kernel_changed)
        self._kernel_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                min-width: 100px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: url(:/icons/arrow-down.png);
                width: 12px;
                height: 12px;
            }
        """)
        kernel_layout.addWidget(kernel_label)
        kernel_layout.addWidget(self._kernel_combo)
        layout.addLayout(kernel_layout)
        
        self._time_label = QLabel("00:00:00:00")
        self._time_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 14px; color: #1e6bde; padding: 0 10px;")
        layout.addWidget(self._time_label)
        
        export_btn = QPushButton("💾 导出")
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: 1px solid #1e6bde;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
                height: 40px;
            }
            QPushButton:hover {
                background-color: #1557b0;
                border-color: #1557b0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border-color: #0d47a1;
            }
        """)
        export_btn.clicked.connect(self._export_video)
        layout.addWidget(export_btn)

        # 补短 P0#4：toolbar 创建完毕，初始化撤销/重做按钮禁用态
        # （无历史时按钮应当不可点，避免用户误操作）
        if not getattr(self, '_action_history', []):
            if self._undo_btn is not None:
                self._undo_btn.setEnabled(False)
                self._undo_btn.setToolTip("无可撤销操作")
            if self._redo_btn is not None:
                self._redo_btn.setEnabled(False)
                self._redo_btn.setToolTip("无可重做操作")

        return toolbar

    # ======================================================================
    # 抽取自 editor_module.py L1151-1288
    # ======================================================================
    def _create_preview_panel(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame#previewCard {
                background-color: #121212; border: 1px solid #252525; border-radius: 12px;
            }
        """)
        card.setObjectName("previewCard")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1e1e1e;")
        title_bar.setFixedHeight(32)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_label = QLabel("🖥 预览窗口")
        title_label.setStyleSheet("color: #999999; font-size: 11px; font-weight: 600;")
        title_layout.addWidget(title_label)

        # 分级预览：1/4 · 1/2 · 100%（拖 scrub / 播放强制 1/4，静止回用户档）
        from app.modules.lego.editor_preview_ux import quality_combo_items
        q_lbl = QLabel("预览")
        q_lbl.setStyleSheet("color:#666;font-size:10px;padding-left:8px;")
        title_layout.addWidget(q_lbl)
        self._preview_quality_combo = QComboBox()
        self._preview_quality_combo.setFixedWidth(96)
        self._preview_quality_combo.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#ddd;border:1px solid #333;border-radius:4px;"
            "padding:1px 4px;font-size:10px;}QComboBox:hover{border-color:#1e6bde;}"
        )
        for text, pm_q in quality_combo_items():
            self._preview_quality_combo.addItem(text, pm_q)
        # 默认选中用户档
        want = getattr(self, "_user_preview_quality", "medium")
        for i in range(self._preview_quality_combo.count()):
            if self._preview_quality_combo.itemData(i) == want:
                self._preview_quality_combo.setCurrentIndex(i)
                break
        self._preview_quality_combo.setToolTip(
            "预览分辨率：粗剪 1/4 · 常规 1/2 · 精剪 100%；拖动/播放自动降至 1/4"
        )
        self._preview_quality_combo.currentIndexChanged.connect(self._on_preview_quality_combo)
        title_layout.addWidget(self._preview_quality_combo)

        self._proxy_toggle_btn = QPushButton("代理")
        self._proxy_toggle_btn.setCheckable(True)
        self._proxy_toggle_btn.setChecked(bool(getattr(self, "_proxy_preview_enabled", True)))
        self._proxy_toggle_btn.setFixedHeight(22)
        self._proxy_toggle_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#888;border:1px solid #333;border-radius:4px;"
            "padding:2px 8px;font-size:10px;}"
            "QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}"
        )
        self._proxy_toggle_btn.setToolTip("预览走代理媒体（导出仍用原片）；高码率/4K 建议开启")
        self._proxy_toggle_btn.toggled.connect(self.set_proxy_preview_enabled)
        title_layout.addWidget(self._proxy_toggle_btn)

        title_layout.addStretch()
        self._timecode_label = QLabel("00:00:00:00")
        self._timecode_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 12px; font-weight: 600; color: #1e6bde;")
        title_layout.addWidget(self._timecode_label)
        layout.addWidget(title_bar)
        
        body = QWidget()
        body_lo = QVBoxLayout(body)
        body_lo.setContentsMargins(8, 8, 8, 8)
        body_lo.setSpacing(8)
        
        self._preview_frame = QFrame()
        self._preview_frame.setStyleSheet("background-color: #000000; border-radius: 8px;")
        self._video_widget.setStyleSheet("background-color: #000000; border-radius: 8px;")
        pv_layout = QStackedLayout(self._preview_frame)
        pv_layout.setContentsMargins(0, 0, 0, 0)
        self._video_widget.setStyleSheet("background-color: #000000;")
        pv_layout.addWidget(self._video_widget)
        self._preview_label = QLabel("")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setScaledContents(False)
        self._preview_label.setStyleSheet("color: #666666; font-size: 16px; background-color: #000000;")
        self._preview_label.setMouseTracking(True)
        self._preview_label.installEventFilter(self)
        self._preview_frame.installEventFilter(self)
        self._preview_drag_active = False
        self._preview_drag_origin = None
        self._preview_drag_tf0 = None
        self._preview_drag_mode = "move"
        self._preview_drag_angle0 = 0.0
        pv_layout.addWidget(self._preview_label)
        pv_layout.setCurrentWidget(self._preview_label)
        body_lo.addWidget(self._preview_frame, 1)
        
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 4, 0, 0)
        controls_layout.setSpacing(6)
        
        self._progress_bar = QSlider(Qt.Orientation.Horizontal)
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setToolTip("拖动跳转时间线播放头")
        self._progress_bar.setStyleSheet("""
            QSlider::groove:horizontal {
                background-color: #1e1e1e; height: 4px; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background-color: #1e6bde; width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }
        """)
        self._progress_bar.sliderMoved.connect(self._on_progress_slider_moved)
        self._progress_bar.sliderReleased.connect(self._on_progress_slider_released)
        controls_layout.addWidget(self._progress_bar, 1)
        
        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setStyleSheet("color: #666666; font-size: 11px;")
        controls_layout.addWidget(self._time_label)

        # M2：预览区画幅提示（竖屏漫剧默认 9:16）
        self._preview_aspect_badge = QLabel(self._sequence_format.badge_text())
        self._preview_aspect_badge.setStyleSheet(
            "QLabel{background:#1a3a2a;color:#7ee787;border:1px solid #2f5139;"
            "border-radius:4px;padding:2px 8px;font-size:10px;font-weight:600;}"
        )
        self._preview_aspect_badge.setToolTip(
            "工程画幅 SSOT；点击切换 黑边/裁切；预览 letterbox；导出同步"
        )
        self._preview_aspect_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_aspect_badge.mousePressEvent = (  # type: ignore[method-assign]
            lambda _e: self._toggle_sequence_fit_mode()
        )
        controls_layout.addWidget(self._preview_aspect_badge)
        
        body_lo.addWidget(controls)
        
        layout.addWidget(body, 1)
        return card

    # ======================================================================
    # 抽取自 editor_module.py L1290-1365
    # ======================================================================
    def _create_tools_panel(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame#toolsCard {
                background-color: #121212; border: 1px solid #252525; border-radius: 12px;
            }
        """)
        card.setObjectName("toolsCard")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1e1e1e;")
        title_bar.setFixedHeight(32)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_label = QLabel("🔧 工具栏")
        title_label.setStyleSheet("color: #999999; font-size: 11px; font-weight: 600;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addWidget(title_bar)
        
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #121212; }
            QTabBar::tab {
                background-color: transparent; color: #888888; border: none;
                padding: 6px 8px; font-size: 11px; min-width: 40px;
                border-bottom: 2px solid transparent;
            }
            QTabBar::tab:selected {
                color: #ffffff; border-bottom: 2px solid #1e6bde;
            }
            QTabBar::tab:hover:!selected { color: #cccccc; }
        """)

        # 首屏只建「属性」；其余 Tab 点开再构造（显著缩短首次打开）
        self._tools_lazy_built: set = set()
        self._tools_lazy_factories: Dict[int, Any] = {}

        def _placeholder() -> QWidget:
            w = QWidget()
            lo = QVBoxLayout(w)
            lo.setContentsMargins(0, 0, 0, 0)
            lo.setSpacing(0)
            tip = QLabel("加载中…")
            tip.setStyleSheet("color:#666;font-size:11px;padding:16px;")
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lo.addWidget(tip)
            w._lazy_tip = tip  # type: ignore[attr-defined]
            return w

        def _add_lazy(title: str, factory) -> int:
            holder = _placeholder()
            idx = tabs.addTab(holder, title)
            self._tools_lazy_factories[idx] = factory
            return idx

        # 属性：选中片段立刻要用，同步构建
        tabs.addTab(self._make_pro_tab(), "属性")
        _add_lazy("调色", self._make_color_tab)
        _add_lazy("特效", self._make_effect_tab)
        _add_lazy("文字", self._make_text_tab)
        _add_lazy("贴纸", self._make_sticker_tab)
        _add_lazy("音频", self._make_audio_tab)
        _add_lazy("角色", self._create_character_tab)
        _add_lazy("AI", self._create_ai_tools_tab)
        self._agent_tab_index = _add_lazy("🤖 Agent", self._create_edit_agent_panel)
        _add_lazy("导出", self._create_params_tab)

        tabs.currentChanged.connect(self._on_tools_tab_changed)
        self._tools_tabs = tabs
        layout.addWidget(tabs, 1)
        return card

    # ======================================================================
    # 抽取自 editor_module.py L1534-1634
    # ======================================================================
    def _make_effect_tab(self):
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8,8,8,8)
        l.setSpacing(6)

        fl = self._sect("滤镜")
        self._filter_category_combo = QComboBox()
        self._filter_category_combo.addItems(
            ["全部", "电影感", "复古", "清新", "黑白", "暖色调", "冷色调", "梦幻", "锐利", "柔和", "都市", "黄昏"]
        )
        self._filter_category_combo.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 6px;font-size:10px;}QComboBox:hover{border-color:#333;}"
            "QComboBox::drop-down{border:none;width:14px;}"
            "QComboBox QAbstractItemView{background:#121212;color:#fff;border:1px solid #333;selection-background-color:#1e6bde;}"
        )
        self._add_cmb_row(fl.layout(), "分类", self._filter_category_combo)
        g = QGridLayout()
        g.setSpacing(4)
        fts = [("🎞原片","#666"),("🎬电影","#d4a574"),("📷复古","#c4956a"),("🌿清新","#7ec87b"),
               ("🖤黑白","#888"),("☀暖阳","#e8b86d"),("❄冷调","#7eb8da"),("💫梦幻","#c9a0dc"),
               ("🎯锐利","#6db3f2"),("🌾柔和","#e8c4a2"),("🏙都市","#5d7b93"),("🌅黄昏","#e8945a")]
        FILTER_KEYS = {
            "🎞原片": "", "🎬电影": "电影感", "📷复古": "复古", "🌿清新": "清新",
            "🖤黑白": "黑白", "☀暖阳": "暖色调", "❄冷调": "冷色调", "💫梦幻": "梦幻",
            "🎯锐利": "锐利", "🌾柔和": "柔和", "🏙都市": "都市", "🌅黄昏": "黄昏",
        }
        self._filter_buttons = []
        for i,(nm,hc) in enumerate(fts):
            b = QPushButton(nm)
            b.setStyleSheet(f"QPushButton{{background:#0a0a0a;color:#ccc;border:1px solid #222;border-left:3px solid {hc};border-radius:3px;padding:5px 6px;font-size:10px;text-align:left;}}QPushButton:hover{{background:#1a1a1a;color:#fff;}}")
            key = FILTER_KEYS.get(nm, "")
            if key == "":
                b.clicked.connect(lambda _, b=b: self._clear_filter())
            else:
                b.clicked.connect(lambda _, k=key: self._select_filter(k))
            g.addWidget(b,i//3,i%3)
            self._filter_buttons.append((b, key))
        self._filter_category_combo.currentTextChanged.connect(self._on_filter_category_changed)
        fl.layout().addLayout(g)
        self._filter_intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self._filter_intensity_slider.setRange(0, 100)
        self._filter_intensity_slider.setValue(50)
        self._filter_intensity_slider.setStyleSheet(
            "QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;"
            "border-radius:5px;margin:-3px 0;}"
        )
        self._filter_intensity_slider.valueChanged.connect(self._on_filter_intensity_live)
        self._add_setting_row(fl.layout(), "强度", self._filter_intensity_slider, "%")
        l.addWidget(fl)

        tr = self._sect("转场")
        self._transition_type_var = QComboBox()
        self._transition_type_var.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 6px;font-size:10px;}"
        )
        self._rebuild_transition_combo()
        self._add_cmb_row(tr.layout(), "类型", self._transition_type_var)
        self._transition_duration_var = QSpinBox()
        self._transition_duration_var.setRange(100, 3000)
        self._transition_duration_var.setValue(500)
        self._transition_duration_var.setStyleSheet(
            "QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 5px;font-size:10px;}"
        )
        self._add_setting_row(tr.layout(), "时长", self._transition_duration_var, "ms")
        self._transition_curve_var = QComboBox()
        self._transition_curve_var.addItems(
            ["线性", "缓入", "缓出", "缓入缓出", "弹性", "回弹"]
        )
        self._transition_curve_var.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 6px;font-size:10px;}"
        )
        self._add_cmb_row(tr.layout(), "曲线", self._transition_curve_var)
        l.addWidget(tr)

        efb = QHBoxLayout()
        afb = QPushButton("✅ 应用滤镜")
        afb.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        afb.clicked.connect(lambda: self._apply_active_filter_with_intensity())
        efb.addWidget(afb)
        atb = QPushButton("✅ 应用转场")
        atb.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#16a34a;}")
        atb.clicked.connect(self._apply_transition)
        efb.addWidget(atb)
        l.addLayout(efb)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)
        return t

    # ======================================================================
    # 抽取自 editor_module.py L1671-1759
    # ======================================================================
    def _make_sticker_tab(self):
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8,8,8,8)
        l.setSpacing(6)

        lib = self._sect("贴纸库")
        g = QGridLayout()
        g.setSpacing(4)
        stickers = [("❤", "爱心"), ("⭐", "星星"), ("🔥", "火焰"), ("💎", "钻石"),
                    ("🎵", "音符"), ("✨", "闪亮"), ("💬", "聊天气泡"), ("🏷", "标签"),
                    ("👑", "皇冠"), ("🎯", "靶心"), ("🌈", "彩虹"), ("🎪", "马戏团")]
        self._sticker_btns = []
        for i, (emoji, name) in enumerate(stickers):
            b = QPushButton(f"{emoji}\n{name}")
            b.setStyleSheet("QPushButton{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:6px;padding:8px 4px;font-size:10px;min-height:48px;}QPushButton:hover{background:#1a1a1a;border-color:#1e6bde;}")
            b.clicked.connect(lambda checked, n=name, e=emoji: self._add_sticker(n, e))
            self._sticker_btns.append(b)
            g.addWidget(b, i // 4, i % 4)
        lib.layout().addLayout(g)
        l.addWidget(lib)

        cst = self._sect("自定义贴纸")
        self._sticker_size = QSlider(Qt.Orientation.Horizontal); self._sticker_size.setRange(20,200); self._sticker_size.setValue(100)
        self._sticker_rot = QSlider(Qt.Orientation.Horizontal); self._sticker_rot.setRange(-360,360); self._sticker_rot.setValue(0)
        self._sticker_posx = QSlider(Qt.Orientation.Horizontal); self._sticker_posx.setRange(0,100); self._sticker_posx.setValue(50)
        self._sticker_posy = QSlider(Qt.Orientation.Horizontal); self._sticker_posy.setRange(0,100); self._sticker_posy.setValue(50)
        self._sticker_opacity = QSlider(Qt.Orientation.Horizontal); self._sticker_opacity.setRange(30,100); self._sticker_opacity.setValue(100)
        for sl in [self._sticker_size, self._sticker_rot, self._sticker_posx, self._sticker_posy, self._sticker_opacity]:
            sl.setStyleSheet("QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}QSlider::handle:horizontal{background:#22c55e;width:10px;height:10px;border-radius:5px;margin:-3px 0;}")
            sl.valueChanged.connect(self._on_sticker_param_live)
        self._add_setting_row(cst.layout(), "大小", self._sticker_size, "%")
        self._add_setting_row(cst.layout(), "旋转", self._sticker_rot, "°")
        self._add_setting_row(cst.layout(), "位置X", self._sticker_posx, "%")
        self._add_setting_row(cst.layout(), "位置Y", self._sticker_posy, "%")
        self._add_setting_row(cst.layout(), "透明度", self._sticker_opacity, "%")
        self._sticker_start = QDoubleSpinBox()
        self._sticker_start.setRange(0, 99999)
        self._sticker_start.setDecimals(1)
        self._sticker_start.setSingleStep(0.5)
        self._sticker_start.setValue(0.0)
        self._sticker_end = QDoubleSpinBox()
        self._sticker_end.setRange(0, 99999)
        self._sticker_end.setDecimals(1)
        self._sticker_end.setSingleStep(0.5)
        self._sticker_end.setValue(99999.0)
        for spn in (self._sticker_start, self._sticker_end):
            spn.setSuffix("s")
            spn.setStyleSheet("QDoubleSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
            spn.setToolTip("贴纸仅在此时间区间内显示/导出；出点留最大值表示到片尾")
            spn.valueChanged.connect(self._on_sticker_param_live)
        self._add_setting_row(cst.layout(), "入点", self._sticker_start)
        self._add_setting_row(cst.layout(), "出点", self._sticker_end)
        add_custom = QPushButton("📁 导入贴纸")
        add_custom.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#16a34a;}")
        add_custom.clicked.connect(self._import_sticker)
        cst.layout().addWidget(add_custom)
        l.addWidget(cst)

        bns = QHBoxLayout()
        apply_s = QPushButton("✅ 更新到画布")
        apply_s.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        apply_s.setToolTip("把当前大小/位置/旋转写到选中贴纸，并刷新预览")
        apply_s.clicked.connect(self._apply_sticker)
        bns.addWidget(apply_s)
        clear_s = QPushButton("🗑 清除贴纸")
        clear_s.setStyleSheet("QPushButton{background:#ef4444;color:#fff;border:none;border-radius:4px;padding:5px;font-size:10px;font-weight:600;}QPushButton:hover{background:#dc2626;}")
        clear_s.clicked.connect(self._clear_stickers)
        bns.addWidget(clear_s)
        l.addLayout(bns)

        self._sticker_list = QListWidget()
        self._sticker_list.setMaximumHeight(100)
        self._sticker_list.setStyleSheet("QListWidget{background:#0a0a0a;color:#ccc;border:1px solid #222;border-radius:4px;font-size:10px;}")
        self._sticker_list.currentRowChanged.connect(self._on_sticker_list_selected)
        l.addWidget(self._sticker_list)

        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0,0,0,0)
        o.addWidget(s)

        self._active_stickers = []
        return t

    # ======================================================================
    # 抽取自 editor_module.py L1761-1852
    # ======================================================================
    def _create_left_panel(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame#importCard {
                background-color: #121212; border: 1px solid #252525; border-radius: 12px;
            }
        """)
        card.setObjectName("importCard")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1e1e1e;")
        title_bar.setFixedHeight(36)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_label = QLabel("📁 导入栏")
        title_label.setStyleSheet("color: #999999; font-size: 11px; font-weight: 600;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addWidget(title_bar)
        
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)
        
        import_btn = QPushButton("🎬 导入视频")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde; color: white; border: none;
                border-radius: 8px; padding: 10px; font-size: 13px; font-weight: 600;
            }
            QPushButton:hover { background-color: #1557b0; }
        """)
        import_btn.clicked.connect(self._import_video)
        body_layout.addWidget(import_btn)
        
        drag_hint = QLabel("或拖拽文件到此处")
        drag_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drag_hint.setStyleSheet("color: #555555; font-size: 11px; padding: 4px;")
        body_layout.addWidget(drag_hint)
        
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #1e1e1e; max-height: 1px;")
        body_layout.addWidget(sep)
        
        fmt_label = QLabel("MP4 · AVI · MOV · MKV · WebM")
        fmt_label.setStyleSheet("color: #555555; font-size: 10px;")
        fmt_label.setWordWrap(True)
        body_layout.addWidget(fmt_label)
        
        # ── 素材预览区域 ──
        preview_sep = QFrame()
        preview_sep.setFrameShape(QFrame.Shape.HLine)
        preview_sep.setStyleSheet("background-color: #1e1e1e; max-height: 1px;")
        body_layout.addWidget(preview_sep)
        preview_title = QLabel("👁 素材预览")
        preview_title.setStyleSheet("color: #999999; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(preview_title)
        self._import_preview_label = QLabel("暂无预览")
        self._import_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._import_preview_label.setMinimumHeight(120)
        self._import_preview_label.setStyleSheet("""
            QLabel {
                background-color: #0a0a0a; border: 1px dashed #333;
                border-radius: 6px; color: #555; font-size: 11px;
            }
        """)
        body_layout.addWidget(self._import_preview_label)
        
        assets_label = QLabel("素材库")
        assets_label.setStyleSheet("color: #999999; font-size: 12px; font-weight: 600; margin-top: 6px;")
        body_layout.addWidget(assets_label)
        
        assets_list = QListWidget()
        assets_list.setStyleSheet("""
            QListWidget {
                background-color: #0a0a0a; border: 1px solid #1e1e1e; border-radius: 8px;
                color: #cccccc; font-size: 12px;
            }
            QListWidget::item { padding: 6px 10px; border-bottom: 1px solid #151515; }
            QListWidget::item:hover { background-color: #1a1a1a; color: #ffffff; }
        """)
        assets_list.addItems(["📹 视频素材", "🎵 音频素材", "🖼 图片素材", "📝 字幕素材"])
        body_layout.addWidget(assets_list)
        
        layout.addWidget(body, 1)
        return card

    # ======================================================================
    # 抽取自 editor_module.py L1854-2050
    # ======================================================================
    def _create_timeline_panel(self) -> QWidget:
        # 局部导入 TimelineWidget：原 editor_module.py 通过模块级懒加载代理提供此名，
        # 抽出到本 Mixin 后需就地导入，避免与宿主形成循环导入（同 _clear_msgbox 策略）。
        from .timeline_widget import TimelineWidget
        card = QFrame()
        card.setStyleSheet("""
            QFrame#timelineCard {
                background-color: #121212; border: 1px solid #252525; border-radius: 12px;
            }
        """)
        card.setObjectName("timelineCard")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1e1e1e;")
        title_bar.setFixedHeight(36)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(8, 4, 8, 4)
        title_layout.setSpacing(4)
        
        add_track_btn = QPushButton("➕ 轨道")
        add_track_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        add_track_btn.clicked.connect(lambda _: self._timeline_widget.add_track("新轨道", "video"))
        title_layout.addWidget(add_track_btn)
        
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedWidth(22)
        zoom_out_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:3px;padding:2px 4px;font-size:11px;font-weight:bold;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        zoom_out_btn.clicked.connect(lambda _: self._set_timeline_zoom(max(10, self._timeline_widget._zoom - 25)))
        zoom_out_btn.setToolTip("缩小")
        title_layout.addWidget(zoom_out_btn)
        
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(10, 3000)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.setToolTip("时间线缩放 10%~3000%；Ctrl+滚轮也可缩放")
        self._zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal{background:#222;height:3px;border-radius:2px;}
            QSlider::handle:horizontal{background:#1e6bde;width:10px;height:10px;border-radius:5px;margin:-3px 0;}
            QSlider::handle:horizontal:hover{background:#3b82f6;}
            QSlider::sub-page:horizontal{background:#1e6bde;height:3px;border-radius:2px;}
        """)
        self._zoom_slider.valueChanged.connect(lambda v: self._set_timeline_zoom(v))
        title_layout.addWidget(self._zoom_slider)
        
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedWidth(22)
        zoom_in_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:3px;padding:2px 4px;font-size:11px;font-weight:bold;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        zoom_in_btn.clicked.connect(lambda _: self._set_timeline_zoom(min(3000, self._timeline_widget._zoom + 25)))
        zoom_in_btn.setToolTip("放大")
        title_layout.addWidget(zoom_in_btn)
        
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;min-width:36px;")
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(self._zoom_label)

        zoom_fit_btn = QPushButton("⧉")
        zoom_fit_btn.setFixedWidth(24)
        zoom_fit_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:3px;"
            "padding:2px 4px;font-size:11px;}QPushButton:hover{background:#3a3a3a;color:#fff;}"
        )
        zoom_fit_btn.setToolTip("适应窗口（Ctrl+0）")
        zoom_fit_btn.clicked.connect(self._zoom_timeline_to_fit)
        title_layout.addWidget(zoom_fit_btn)

        self._razor_btn = QPushButton("✂")
        self._razor_btn.setFixedWidth(24)
        self._razor_btn.setCheckable(True)
        self._razor_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:3px;"
            "padding:2px 4px;font-size:11px;}QPushButton:hover{background:#3a3a3a;color:#fff;}"
            "QPushButton:checked{background:#c0392b;color:#fff;border:1px solid #e74c3c;}"
        )
        self._razor_btn.setToolTip("刀片工具（C 切换）：悬停切开线，点击切开；Ctrl+K 在播放头切开")
        self._razor_btn.clicked.connect(self._toggle_razor_tool)
        title_layout.addWidget(self._razor_btn)
        
        sep0 = QFrame()
        sep0.setStyleSheet("background-color:#333;min-width:1px;max-width:1px;")
        sep0.setFixedSize(1, 20)
        title_layout.addWidget(sep0)
        
        rew_btn = QPushButton("⏮")
        rew_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:11px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        rew_btn.clicked.connect(self._rewind)
        rew_btn.setToolTip("后退10秒")
        title_layout.addWidget(rew_btn)
        
        self._pp_btn = QPushButton("▶")
        self._pp_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:1px solid #1e6bde;border-radius:4px;padding:3px 10px;font-size:12px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        self._pp_btn.clicked.connect(self._play_pause)
        self._pp_btn.setToolTip("播放/暂停")
        title_layout.addWidget(self._pp_btn)
        
        ff_btn = QPushButton("⏭")
        ff_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:11px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        ff_btn.clicked.connect(self._fast_forward)
        ff_btn.setToolTip("快进10秒")
        title_layout.addWidget(ff_btn)
        
        # ── 倍速控制 ──
        speed_lbl = QLabel("⚡")
        speed_lbl.setStyleSheet("color:#888;font-size:11px;min-width:16px;")
        title_layout.addWidget(speed_lbl)
        self._playback_speed_combo = QComboBox()
        self._playback_speed_combo.addItems(["0.5x", "1x", "1.5x", "2x"])
        self._playback_speed_combo.setCurrentIndex(1)
        self._playback_speed_combo.setFixedWidth(58)
        self._playback_speed_combo.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #333;border-radius:4px;padding:2px 4px;font-size:10px;}QComboBox:hover{border-color:#1e6bde;}")
        self._playback_speed_combo.currentTextChanged.connect(self._on_playback_speed_changed)
        self._playback_speed_combo.setToolTip("播放倍速")
        title_layout.addWidget(self._playback_speed_combo)
        
        sep1 = QFrame()
        sep1.setStyleSheet("background-color:#333;min-width:1px;max-width:1px;")
        sep1.setFixedSize(1, 20)
        title_layout.addWidget(sep1)
        
        self._edit_agent_toggle_btn = QPushButton("🤖 剪辑 Agent")
        self._edit_agent_toggle_btn.setCheckable(True)
        self._edit_agent_toggle_btn.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:1px solid #16a34a;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:500;}QPushButton:checked{background:#1e6bde;border-color:#1e6bde;}QPushButton:hover{background:#16a34a;}")
        self._edit_agent_toggle_btn.clicked.connect(self._toggle_edit_agent_panel)
        title_layout.addWidget(self._edit_agent_toggle_btn)
        
        title_layout.addStretch()
        
        snap_btn = QPushButton("📌 吸附")
        snap_btn.setCheckable(True)
        snap_btn.setChecked(True)  # 默认开启，与 TimelineWidget._snap_enabled 一致
        snap_btn.setToolTip("吸附到播放头与相邻片缘（按像素阈值，放大后更精细；按住 Alt 临时关闭）")
        snap_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#888;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        snap_btn.toggled.connect(self._on_snap_toggled)
        title_layout.addWidget(snap_btn)
        self._snap_btn = snap_btn

        ripple_btn = QPushButton("🌊 波纹删")
        ripple_btn.setCheckable(True)
        ripple_btn.setChecked(bool(getattr(self, "_ripple_delete_enabled", True)))
        ripple_btn.setToolTip("开启：删除后后方片段前移闭合空隙；关闭：普通删除留白")
        ripple_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#888;border:1px solid #333;border-radius:4px;"
            "padding:3px 8px;font-size:10px;}"
            "QPushButton:checked{background:#0d9488;color:#fff;border-color:#0d9488;}"
            "QPushButton:hover{background:#3a3a3a;color:#fff;}"
        )
        ripple_btn.toggled.connect(self._on_ripple_delete_toggled)
        title_layout.addWidget(ripple_btn)
        self._ripple_btn = ripple_btn

        kf_btn = QPushButton("◆ 关键帧")
        kf_btn.setToolTip("在播放头为当前片段添加关键帧（不透明度/音量/缩放）")
        kf_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ddd;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        kf_btn.clicked.connect(self._on_add_keyframe_clicked)
        title_layout.addWidget(kf_btn)
        del_kf_btn = QPushButton("⌫ 删关键帧")
        del_kf_btn.setToolTip("删除当前播放头附近的关键帧")
        del_kf_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ddd;border:1px solid #333;border-radius:4px;padding:3px 8px;font-size:10px;}QPushButton:hover{background:#3a3a3a;color:#fff;}")
        del_kf_btn.clicked.connect(self._on_delete_keyframe_near_playhead)
        title_layout.addWidget(del_kf_btn)
        
        layout.addWidget(title_bar)
        
        body = QWidget()
        body_lo = QVBoxLayout(body)
        body_lo.setContentsMargins(8, 8, 8, 8)
        
        self._timeline_widget = TimelineWidget()
        self._timeline_widget._snap_enabled = True
        self._snap_enabled = True
        self._timeline_widget.clip_selected.connect(self._on_clip_selected)
        # 补短 P1#8：监听关键帧点击 - 落到具体 keyframe 数据上
        self._timeline_widget.clip_keyframe_clicked.connect(self._on_keyframe_clicked)
        # 连接拖放导入信号
        self._timeline_widget.files_dropped.connect(self._on_files_dropped)
        self._timeline_widget.clip_context_action.connect(self._on_timeline_clip_context)
        self._timeline_widget.playhead_moved.connect(self._on_timeline_playhead_moved)
        self._timeline_widget.clip_trim_committed.connect(self._on_clip_trim_committed)
        self._timeline_widget.razor_cut_at.connect(self._on_razor_cut_at)
        self._timeline_widget.razor_mode_changed.connect(self._on_razor_mode_changed)
        self._timeline_widget._track_volume_changed_cb = self._on_timeline_track_volume
        # Esc：优先取消拖拽/trim，其次退出刀片（时间线焦点；不抢模态对话框）
        try:
            self._razor_esc_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_Escape), self._timeline_widget
            )
            self._razor_esc_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self._razor_esc_shortcut.setEnabled(True)
            self._razor_esc_shortcut.activated.connect(self._on_timeline_escape)
        except Exception as e:
            logger.debug("注册 Esc 时间线快捷键失败: %s", e)
        body_lo.addWidget(self._timeline_widget, 3)

        layout.addWidget(body, 1)
        return card

    # ======================================================================
    # 抽取自 editor_module.py L6185-6242
    # ======================================================================
    def _create_character_tab(self) -> QWidget:
        """
        「角色」面板 — 剪辑模块内的临时角色管理
        读取 DramaStructure 中的角色列表，允许用户给角色打「优先保留/忽略」标签
        调整后写回 AnalysisCache（仅作用于当前视频，不跨视频复用）
        """
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)

        # 顶部标题 & 缓存状态
        st = self._sect("👥 角色（剪辑内临时标记）")
        st_lo = st.layout()
        info_row = QHBoxLayout()
        self._char_status_label = QLabel("等待视频分析...")
        self._char_status_label.setStyleSheet("color:#888888;font-size:11px;")
        info_row.addWidget(self._char_status_label)
        info_row.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#ffffff;border-radius:4px;padding:4px 10px;font-size:11px;}"
            "QPushButton:hover{background:#2d7ae8;}"
            "QPushButton:pressed{background:#1a5dc4;}"
        )
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh_character_panel)
        info_row.addWidget(refresh_btn)
        st_lo.addLayout(info_row)
        hint = QLabel("提示：角色仅作用于当前视频，调整后重新生成剪辑方案会生效。\n关闭程序后偏好保留（同视频下次打开仍然保留）。")
        hint.setStyleSheet("color:#666666;font-size:10px;")
        hint.setWordWrap(True)
        st_lo.addWidget(hint)

        # 角色列表容器（动态生成）
        self._char_list_container = QWidget()
        self._char_list_layout = QVBoxLayout(self._char_list_container)
        self._char_list_layout.setContentsMargins(0, 0, 0, 0)
        self._char_list_layout.setSpacing(6)
        self._char_list_layout.addStretch()
        l.addWidget(self._char_list_container, 1)

        s.setWidget(c)
        outer = QVBoxLayout(t)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(s)

        # 首次刷新（如果已有缓存则立即显示）
        try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, self._refresh_character_panel)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        return t

    # ======================================================================
    # 抽取自 editor_module.py L6252-6431
    # ======================================================================
    def _refresh_character_panel(self):
        """刷新角色列表（从 AnalysisCache 读取）"""
        # 安全检查：对象可能已被 Qt 销毁
        try:
            _ = self._char_status_label.isVisible()
        except (RuntimeError, AttributeError):
            return

        try:
            from .character_cache import AnalysisCache
        except Exception:
            self._safe_set_text(self._char_status_label, "角色缓存不可用")
            return

        # 清理旧 UI
        try:
            while self._char_list_layout.count() > 0:
                item = self._char_list_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
        except (RuntimeError, AttributeError):
            return

        video_path = getattr(self, "_video_source", None)
        if not video_path:
            self._safe_set_text(self._char_status_label, "尚未导入视频")
            try:
                self._char_list_layout.addStretch()
            except (RuntimeError, AttributeError) as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            return

        try:
            cache = AnalysisCache()
            drama = cache.get_drama(video_path)
            prefs = cache.get_character_prefs(video_path)
        except Exception as e:
            self._safe_set_text(self._char_status_label, f"读取缓存异常: {e}")
            try:
                self._char_list_layout.addStretch()
            except (RuntimeError, AttributeError) as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            return

        if drama is None or not getattr(drama, "characters", None):
            self._safe_set_text(self._char_status_label, "未检测到角色 — 请先运行「AI 智能剪辑」分析视频")
            try:
                empty = QLabel("分析完成后，角色将出现在这里供你标记。\n\n"
                              "• 点「忽略」：剪辑时会降低该角色镜头的优先级\n"
                              "• 点「优先保留」：剪辑时会提升该角色镜头的重要性\n"
                              "• 权重滑块：精细调整影响幅度")
                empty.setStyleSheet("color:#666666;font-size:11px;padding:16px;"
                                  "background:#1a1a1a;border-radius:6px;")
                empty.setWordWrap(True)
                self._char_list_layout.addWidget(empty)
                self._char_list_layout.addStretch()
            except (RuntimeError, AttributeError) as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
            return

        # 统计每个角色的出场次数（粗略：按 scenes 统计）
        scenes = getattr(drama, "scenes", []) or []
        char_appear = {}
        for sc in scenes:
            for name in (getattr(sc, "characters", None) or []):
                char_appear[name] = char_appear.get(name, 0) + 1

        total_chars = len(drama.characters)
        active_pref_count = sum(1 for p in prefs.values() if p is not None and hasattr(p, "__dict__") or (isinstance(p, dict) and p))

        self._safe_set_text(
            self._char_status_label,
            f"本视频共识别 {total_chars} 个角色 · 已标记 {len(prefs)} 个偏好"
        )

        # 为每个角色构建一行 UI
        for ch in drama.characters:
            name = str(getattr(ch, "name", "未知"))
            role_type = str(getattr(ch, "role_type", ""))
            traits = getattr(ch, "personality_traits", []) or []

            pref_obj = prefs.get(name)
            if pref_obj is not None:
                if hasattr(pref_obj, "keep"):
                    keep_default = bool(pref_obj.keep)
                    weight_default = float(getattr(pref_obj, "weight", 1.0))
                elif isinstance(pref_obj, dict):
                    keep_default = bool(pref_obj.get("keep", True))
                    weight_default = float(pref_obj.get("weight", 1.0))
                else:
                    keep_default = True
                    weight_default = 1.0
            else:
                keep_default = True
                weight_default = 1.0

            row = QFrame()
            row.setStyleSheet(
                "QFrame{background:#1a1a1a;border:1px solid #252525;border-radius:6px;}"
            )
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(6)

            # 顶部：角色名 + 类型标签 + 勾选框
            top_row = QHBoxLayout()
            label = QLabel(f"🎭 {name}")
            label.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
            top_row.addWidget(label)

            if role_type:
                tag = QLabel(role_type)
                tag.setStyleSheet("background:#1e6bde;color:#ffffff;font-size:10px;"
                                 "padding:2px 6px;border-radius:4px;")
                top_row.addWidget(tag)

            appear_count = char_appear.get(name, 0)
            count_label = QLabel(f"出现 {appear_count} 个场景")
            count_label.setStyleSheet("color:#888888;font-size:10px;")
            top_row.addWidget(count_label)
            top_row.addStretch()

            keep_check = QCheckBox("优先保留")
            keep_check.setChecked(keep_default)
            keep_check.setStyleSheet(
                "QCheckBox{color:#ffffff;font-size:11px;spacing:4px;}"
                "QCheckBox::indicator{width:14px;height:14px;border-radius:3px;"
                "border:2px solid #555555;background:#121212;}"
                "QCheckBox::indicator:checked{background:#22c55e;border:2px solid #22c55e;}"
            )
            top_row.addWidget(keep_check)
            row_layout.addLayout(top_row)

            # 标签
            if traits:
                t_row = QHBoxLayout()
                for t in list(traits)[:5]:
                    tl = QLabel(str(t))
                    tl.setStyleSheet(
                        "background:#252525;color:#aaaaaa;font-size:10px;"
                        "padding:2px 6px;border-radius:4px;"
                    )
                    t_row.addWidget(tl)
                t_row.addStretch()
                row_layout.addLayout(t_row)

            # 权重滑块
            slider_row = QHBoxLayout()
            sl_label = QLabel("影响权重")
            sl_label.setStyleSheet("color:#888888;font-size:10px;")
            slider_row.addWidget(sl_label)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(50, 200)  # 50% ~ 200%
            slider.setValue(int(round(weight_default * 100)))
            slider.setStyleSheet(
                "QSlider::groove:horizontal{height:4px;background:#333333;border-radius:2px;}"
                "QSlider::handle:horizontal{background:#1e6bde;width:12px;height:12px;"
                "margin:-4px 0;border-radius:6px;}"
                "QSlider::handle:horizontal:hover{background:#3b82f6;}"
            )
            slider_row.addWidget(slider, 1)

            pct_label = QLabel(f"{int(round(weight_default * 100))}%")
            pct_label.setStyleSheet("color:#aaaaaa;font-size:10px;min-width:32px;qproperty-alignment:AlignRight;")
            slider_row.addWidget(pct_label)
            row_layout.addLayout(slider_row)

            # 绑定：勾选/滑动 → 写回缓存
            self._bind_character_row_events(
                name=name,
                keep_check=keep_check,
                slider=slider,
                pct_label=pct_label,
            )

            self._char_list_layout.addWidget(row)

        self._char_list_layout.addStretch()

    # ======================================================================
    # 抽取自 editor_module.py L6929-7114
    # ======================================================================
    def _create_params_tab(self) -> QWidget:
        t = QWidget()
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:#121212;border:none;}")
        c = QWidget()
        l = QVBoxLayout(c)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(6)
        
        pi = self._sect("📊 项目信息")
        pi_lo = pi.layout()
        self._proj_res_label = QLabel("分辨率: --")
        self._proj_res_label.setStyleSheet("color:#1e6bde;font-size:10px;font-weight:600;")
        pi_lo.addWidget(self._proj_res_label)
        dur_row = QHBoxLayout()
        self._proj_dur_label = QLabel("时长: --")
        self._proj_dur_label.setStyleSheet("color:#888;font-size:10px;")
        dur_row.addWidget(self._proj_dur_label)
        self._proj_size_label = QLabel("预估: --")
        self._proj_size_label.setStyleSheet("color:#888;font-size:10px;")
        dur_row.addWidget(self._proj_size_label)
        dur_row.addStretch()
        pi_lo.addLayout(dur_row)
        l.addWidget(pi)
        
        mo = self._sect("🎯 输出模式")
        self._output_mode_var = QComboBox()
        # M2：漫剧竖屏预设置顶，并真正改分辨率/比例（此前仅展示文案）
        self._output_mode_var.addItems([
            "漫剧竖屏快切",
            "自定义参数",
            "30秒爆款引流",
            "90秒剧情解说",
            "8分钟挂车长视频",
            "B站横屏长视频",
        ])
        self._output_mode_var.setStyleSheet("QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:4px 8px;font-size:10px;}QComboBox:hover{border-color:#333;}")
        mo.layout().addWidget(self._output_mode_var)
        drama_btn = QPushButton("📱 一键漫剧竖屏 1080×1920")
        drama_btn.setStyleSheet(
            "QPushButton{background:#1a3a2a;color:#7ee787;border:1px solid #2f5139;"
            "border-radius:4px;padding:6px;font-size:10px;font-weight:600;}"
            "QPushButton:hover{background:#238636;color:#fff;}"
        )
        drama_btn.setToolTip("抖音/快手/小红书竖屏：9:16 · 1080x1920 · 30fps · 导出等比填充黑边")
        drama_btn.clicked.connect(self._apply_manju_portrait_preset)
        mo.layout().addWidget(drama_btn)
        landscape_btn = QPushButton("🖥️ 一键横屏 1920×1080")
        landscape_btn.setStyleSheet(
            "QPushButton{background:#1a2744;color:#79c0ff;border:1px solid #1f6feb;"
            "border-radius:4px;padding:6px;font-size:10px;font-weight:600;}"
            "QPushButton:hover{background:#1f6feb;color:#fff;}"
        )
        landscape_btn.setToolTip("B站/横屏：16:9 · 1920x1080 · 30fps · 导出等比填充黑边")
        landscape_btn.clicked.connect(self._apply_landscape_preset)
        mo.layout().addWidget(landscape_btn)
        ch_row = QHBoxLayout()
        csv_btn = QPushButton("章节 CSV")
        csv_btn.setToolTip("导出 chapter_markers 为 CSV，无章节则诚实失败")
        csv_btn.clicked.connect(self._export_chapters_csv)
        ffm_btn = QPushButton("章节 ffmetadata")
        ffm_btn.setToolTip("导出 FFmpeg 章节元数据")
        ffm_btn.clicked.connect(self._export_chapters_ffmetadata)
        ch_row.addWidget(csv_btn)
        ch_row.addWidget(ffm_btn)
        mo.layout().addLayout(ch_row)
        l.addWidget(mo)
        
        vo = self._sect("🎬 视频参数")
        vo_lo = vo.layout()
        self._platform_var = QComboBox()
        self._platform_var.addItems(["抖音", "快手", "视频号", "B站", "小红书", "默认"])
        self._resolution_var = QComboBox()
        self._resolution_var.addItems([
            "1080x1920", "720x1280", "1920x1080", "1280x720", "1080x1080", "3840x2160",
        ])
        self._aspect_var = QComboBox()
        self._aspect_var.addItems(["9:16", "16:9", "1:1", "4:3"])
        self._fit_mode_var = QComboBox()
        self._fit_mode_var.addItem("等比黑边", "contain")
        self._fit_mode_var.addItem("裁切铺满", "cover")
        self._fit_mode_var.setToolTip(
            "素材相对工程画幅：黑边=完整可见；裁切=铺满画幅（可能切边）。预览与导出同步。"
        )
        self._fps_var = QComboBox()
        self._fps_var.addItems(["30fps", "60fps", "24fps", "25fps", "50fps"])
        self._codec_var = QComboBox()
        self._codec_var.addItems(["H.264", "H.265", "VP9", "AV1"])
        self._format_var = QComboBox()
        self._format_var.addItems(["MP4", "MKV", "AVI", "MOV"])
        self._bitrate_var = QComboBox()
        self._bitrate_var.addItems(["3000k", "2000k", "5000k", "1M", "10M"])
        self._bitrate_control_var = QComboBox()
        self._bitrate_control_var.addItems(["CBR", "VBR", "CRF"])
        self._bitrate_control_var.setToolTip(
            "CBR=恒定码率（按上方比特率）；VBR=可变码率（上方比特率为目标均值）；"
            "CRF=恒定质量（忽略比特率，按下方质量档位控制体积/画质）"
        )
        self._quality_var = QComboBox()
        self._quality_var.addItems(["高", "中", "低"])
        self._quality_var.setToolTip("画质档位：CRF 模式下直接决定质量；其他模式下影响编码预设")
        self._gop_var = QSpinBox()
        self._gop_var.setRange(1, 300)
        self._gop_var.setValue(30)
        self._gop_var.setToolTip("关键帧间隔（GOP），越小 seek 越快但体积越大，直播/短视频常用等于帧率")
        _cmb_ss = (
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;"
            "padding:3px 6px;font-size:10px;}"
        )
        for cmb in (
            self._platform_var, self._resolution_var, self._aspect_var, self._fit_mode_var,
            self._fps_var, self._codec_var, self._format_var, self._bitrate_var,
            self._bitrate_control_var, self._quality_var,
        ):
            cmb.setStyleSheet(_cmb_ss)
        self._gop_var.setStyleSheet("QSpinBox{background:#0a0a0a;color:#fff;border:1px solid #222;border-radius:4px;padding:3px 5px;font-size:10px;}")
        self._add_cmb_row(vo_lo, "平台", self._platform_var)
        self._add_cmb_row(vo_lo, "分辨率", self._resolution_var)
        self._add_cmb_row(vo_lo, "比例", self._aspect_var)
        self._add_cmb_row(vo_lo, "适配", self._fit_mode_var)
        self._add_cmb_row(vo_lo, "帧率", self._fps_var)
        self._add_cmb_row(vo_lo, "编码", self._codec_var)
        self._add_cmb_row(vo_lo, "格式", self._format_var)
        self._add_cmb_row(vo_lo, "比特率", self._bitrate_var)
        self._add_cmb_row(vo_lo, "码控", self._bitrate_control_var)
        self._add_cmb_row(vo_lo, "质量", self._quality_var)
        self._add_setting_row(vo_lo, "GOP", self._gop_var)
        # M2：平台 / 输出模式联动预设；避免改平台时互相打架用 blockSignals
        self._platform_var.currentTextChanged.connect(self._on_export_platform_changed)
        self._output_mode_var.currentTextChanged.connect(self._on_export_output_mode_changed)
        self._aspect_var.currentTextChanged.connect(self._on_export_aspect_or_resolution_changed)
        self._resolution_var.currentTextChanged.connect(self._on_export_aspect_or_resolution_changed)
        self._fit_mode_var.currentIndexChanged.connect(self._on_export_fit_mode_changed)
        self._format_var.currentTextChanged.connect(self._on_export_format_changed)
        QTimer.singleShot(0, self._apply_manju_portrait_preset)
        l.addWidget(vo)
        
        au = self._sect("🔊 音频参数")
        au_lo = au.layout()
        self._audio_codec_var = QComboBox(); self._audio_codec_var.addItems(["AAC", "MP3", "WAV"])
        self._audio_channel_var = QComboBox(); self._audio_channel_var.addItems(["立体声", "单声道"])
        self._audio_sample_var = QComboBox(); self._audio_sample_var.addItems(["44100", "48000", "22050"])
        self._audio_bitrate_var = QComboBox(); self._audio_bitrate_var.addItems(["128k", "192k", "256k", "320k"])
        for cmb in (
            self._audio_codec_var, self._audio_channel_var,
            self._audio_sample_var, self._audio_bitrate_var,
        ):
            cmb.setStyleSheet(_cmb_ss)
        self._add_cmb_row(au_lo, "编码", self._audio_codec_var)
        self._add_cmb_row(au_lo, "通道", self._audio_channel_var)
        self._add_cmb_row(au_lo, "采样率", self._audio_sample_var)
        self._add_cmb_row(au_lo, "比特率", self._audio_bitrate_var)
        l.addWidget(au)
        
        self._hw_section = self._sect("⚡ 硬件加速")
        gpu_name = ""
        gpu_available = False
        try:
            from app.core.gpu_acceleration import get_gpu_detector
            gpu = get_gpu_detector().detect_gpu()
            if gpu.gpu_type.value != "none":
                gpu_name = gpu.name
                gpu_available = True
        except (ImportError, OSError) as _e:
            logger.warning("操作异常（已忽略）: %s", _e)
        label_text = f"启用硬件加速 ({gpu_name})" if gpu_name else "启用硬件加速 (NVENC)"
        self._hardware_accel_var = QCheckBox(label_text)
        self._hardware_accel_var.setStyleSheet("color:#888;font-size:10px;")
        self._hardware_accel_var.setChecked(gpu_available)
        self._hw_section.layout().addWidget(self._hardware_accel_var)
        l.addWidget(self._hw_section)
        self._hw_section.setVisible(True)
        
        exp_btn = QPushButton("💾 开始导出")
        exp_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px;font-size:12px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        exp_btn.clicked.connect(self._export_video)
        l.addWidget(exp_btn)
        QTimer.singleShot(0, self._refresh_export_project_info)
        
        l.addStretch()
        s.setWidget(c)
        o = QVBoxLayout(t)
        o.setContentsMargins(0, 0, 0, 0)
        o.addWidget(s)
        return t

