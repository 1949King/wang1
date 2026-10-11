"""
Qt6 主窗口 - 剪映同款标签页布局
==============================
专业级架构：左侧导航 + 标签页切换 + 底部状态栏
"""

from typing import Dict, List, Optional, Type, Any
from dataclasses import dataclass
from enum import Enum
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QPushButton, QFrame,
    QStatusBar, QSizePolicy, QScrollArea, QSpacerItem,
    QTabWidget, QSplitter, QToolBar, QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QSettings
from PyQt6.QtGui import QIcon, QFont, QColor, QAction

from .core import EventBus, EventType, MasterClock, DataBus
from .auth import auth_service  # 修复 P0-A: 移除 main_window.py 内的伪 User/AuthService,统一从 auth 模块导入
from .module_registry import get_registry, ModuleTier  # 模块注册表：分级 + 开关
from .theme_manager import ThemeManager  # 全局主题管理器
from .nav_icons import (  # 导航模块矢量图标（QtSvg 缺失时自动回退 emoji）
    NAV_MODULE_ICON_SIZE,
    make_nav_icon,
    nav_icon_available,
)
from app.version import __version__

logger = logging.getLogger("AI短剧编辑器.main_window")


class ModuleState(Enum):
    NOT_LOADED = "not_loaded"
    LOADING = "loading"
    LOADED = "loaded"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


@dataclass
class ModuleInfo:
    id: str
    name: str
    icon: str
    description: str
    widget_class: Optional[Type[QWidget]] = None
    instance: Optional[QWidget] = None
    state: ModuleState = ModuleState.INACTIVE


class NavigationButton(QPushButton):
    """导航按钮 - 剪映风格"""

    def __init__(self, text: str, icon: str = "", module_id: str = ""):
        super().__init__()
        self.module_id = module_id
        self._is_active = False
        self._is_hovered = False
        self._theme = "dark"  # 默认深色主题
        self._icon = icon      # emoji：仅在矢量图标不可用时兜底
        self._text = text
        self._collapsed = False
        # 该模块是否有矢量图标且 QtSvg 可用（否则整条回退到 emoji，行为与改造前一致）
        self._has_vector_icon = nav_icon_available(module_id)
        self._vector_applied = False   # _apply_content 内更新：是否真的用上了矢量图标

        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 图标 + 文字由 _update_style → _apply_content 统一设置
        # （替代原先把 emoji 拼进 setText 的写法）
        self._update_style()

    def _icon_color(self) -> str:
        """图标色随主题与交互状态变化 —— 这正是矢量图标相对 emoji 的核心优势：
        emoji 的颜色由系统字体决定，主题切换与选中态都改不动它。"""
        if self._is_active:
            return "#f8fbff"                       # 选中：压在 accent 底色上的白
        if self._theme == "light":
            return "#172033" if self._is_hovered else "#3d4d63"
        return "#edf3ff" if self._is_hovered else "#c2cfe4"

    def _apply_content(self):
        """设置按钮的图标与文字；矢量不可用时回退到 emoji 内联文本。

        折叠态只留图标；展开态图标 + 文字。文字不再自带前导空格 ——
        emoji 时代的缩进由 QSS 的 padding-left 负责，这里保持一致。
        """
        if self._has_vector_icon:
            icon = make_nav_icon(
                self.module_id, self._icon_color(), size=NAV_MODULE_ICON_SIZE
            )
            if icon is not None:
                self.setIcon(icon)
                self.setIconSize(QSize(NAV_MODULE_ICON_SIZE, NAV_MODULE_ICON_SIZE))
                self.setText("" if self._collapsed else self._text)
                self._vector_applied = True
                return
        # ── 兜底：维持改造前的 emoji 内联文本行为 ──
        self._vector_applied = False
        self.setIcon(QIcon())
        if self._collapsed:
            self.setText(self._icon if self._icon else "•")
        else:
            self.setText(f"  {self._icon}  {self._text}" if self._icon else self._text)

    def set_collapsed(self, collapsed: bool):
        """折叠时只显示图标（居中），展开恢复文字（两种模式都悬浮显示名称）"""
        self._collapsed = collapsed
        if collapsed:
            self.setMinimumWidth(44)
            self.setMaximumWidth(44)
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
        self._apply_content()
        # 折叠态只剩一个图标，是唯一的信息入口：走 emoji 兜底时必须把 emoji
        # 一并写进提示（用户可能认图不认字）；使用矢量图标时名字本身就够了。
        if collapsed and not self._vector_applied:
            self.setToolTip(f"{self._icon} {self._text}".strip())
        else:
            self.setToolTip(self._text)
        # 折叠/展开的 text-align 与 padding 不同，必须重算样式，
        # 否则沿用展开态 left+16px 会把 44px 按钮里的图标挤偏
        self._update_style()
    
    def set_theme(self, theme: str):
        """设置主题"""
        self._theme = theme
        self._update_style()
    
    def set_active(self, active: bool):
        self._is_active = active
        self._update_style()
    
    def enterEvent(self, event):
        self._is_hovered = True
        if not self._is_active:
            self._update_style()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        self._is_hovered = False
        if not self._is_active:
            self._update_style()
        super().leaveEvent(event)
    
    def _update_style(self):
        # 图标色随状态变化，样式重算时必须一并刷新图标内容。
        # （emoji 做不到这件事 —— 它的颜色由系统字体决定。）
        self._apply_content()
        palette = {
            "light": {
                "text": "#172033",
                "muted": "#56657a",
                "surface": "#fcfdff",
                "hover": "#dde7f4",
                "active": "#2563eb",
                "active_hover": "#1d4ed8",
                "active_text": "#f8fbff",
                "border": "#d7e0ec",
            },
            "dark": {
                "text": "#edf3ff",
                "muted": "#aab6cc",
                "surface": "#101621",
                "hover": "#1f2b42",
                "active": "#2f7bff",
                "active_hover": "#4d8dff",
                "active_text": "#f8fbff",
                "border": "#253044",
            },
        }["light" if self._theme == "light" else "dark"]

        # 折叠态图标居中：展开态的 left+16px 会把 44px 按钮里的图标挤到偏右
        palette["align"] = (
            "center; padding-left: 0px;"
            if self._collapsed
            else "left; padding-left: 16px;"
        )

        # 侧栏是高频入口，选中、悬停、默认态必须一眼可分辨。
        if self._theme == "light":
            if self._is_active:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: %(active)s;
                        color: %(active_text)s;
                        border: 1px solid %(active)s;
                        border-radius: 10px;
                        text-align: %(align)s;
                        font-size: 14px;
                        font-weight: 700;
                    }
                    QPushButton:hover {
                        background-color: %(active_hover)s;
                    }
                """ % palette)
            elif self._is_hovered:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: %(hover)s;
                        color: %(text)s;
                        border: 1px solid %(border)s;
                        border-radius: 10px;
                        text-align: %(align)s;
                        font-size: 14px;
                        font-weight: 500;
                    }
                """ % palette)
            else:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: %(muted)s;
                        border: 1px solid transparent;
                        border-radius: 10px;
                        text-align: %(align)s;
                        font-size: 14px;
                        font-weight: 400;
                    }
                    QPushButton:hover {
                        background-color: %(hover)s;
                        color: %(text)s;
                        border: 1px solid %(border)s;
                    }
                """ % palette)
        else:  # 深色主题
            if self._is_active:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: %(active)s;
                        color: %(active_text)s;
                        border: 1px solid %(active)s;
                        border-radius: 10px;
                        text-align: %(align)s;
                        font-size: 14px;
                        font-weight: 700;
                    }
                    QPushButton:hover {
                        background-color: %(active_hover)s;
                    }
                """ % palette)
            elif self._is_hovered:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: %(hover)s;
                        color: %(text)s;
                        border: 1px solid %(border)s;
                        border-radius: 10px;
                        text-align: %(align)s;
                        font-size: 14px;
                        font-weight: 500;
                    }
                """ % palette)
            else:
                self.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: %(muted)s;
                        border: 1px solid transparent;
                        border-radius: 10px;
                        text-align: %(align)s;
                        font-size: 14px;
                        font-weight: 400;
                    }
                    QPushButton:hover {
                        background-color: %(hover)s;
                        color: %(text)s;
                        border: 1px solid %(border)s;
                    }
                """ % palette)


_NAV_TOGGLE_ICON_SIZE = 18          # 逻辑像素；按钮 28×28，四周留 5px 呼吸

# 图标色跟随主题的 text_primary。对比度实测（相对导航栏底色 bg_secondary）：
#   深色 #edf3ff on #101621 ≈ 16:1
#   浅色 #172033 on #fcfdff ≈ 16:1
# 旧实现把颜色写死成 #aab6cc（深色主题的 text_secondary），浅色主题下
# 只有 2.0:1 —— 远低于 UI 组件 3:1 下限，看上去就是个空框。
_NAV_TOGGLE_ICON_COLORS = {"dark": "#edf3ff", "light": "#172033"}


def _make_nav_toggle_icon(collapsed: bool, color: str) -> "QIcon":
    """绘制导航栏「折叠 / 展开」图标（矢量，不依赖字体字形）。

    图形语义 = 「一整块面板 + 折叠方向」：
      · 圆角外框   —— 整块面板（导航栏所占的那一列）
      · 左侧实心条 —— 导航栏本体
      · 单尖角箭头 —— 点击后它往哪走
          展开态 → 朝左（把它收窄到左边缘）
          折叠态 → 朝右（把它向右展开回来）

    为什么弃用字符 `«` / `»`：
      1. 依赖字体字形 —— 字体缺字或字重偏细时，14px 落在 28px 按钮里几乎不可见；
      2. 语义抽象 —— 看不出它管的是「整条导航栏」，而非某个具体功能；
      3. 旧样式把颜色写死成深色主题色，浅色主题下对比度掉到 2.0:1。
    """
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QGuiApplication, QPainter, QPen, QPixmap, QPolygonF

    # 高分屏：位图按屏幕 DPR 放大、再设回 DPR，保证边缘锐利
    try:
        _screen = QGuiApplication.primaryScreen()
        dpr = float(_screen.devicePixelRatio()) if _screen else 1.0
    except Exception:
        dpr = 1.0
    dpr = max(1.0, min(dpr, 4.0))

    size = _NAV_TOGGLE_ICON_SIZE
    pm = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    col = QColor(color)

    # 1) 外框 = 整块面板
    frame_pen = QPen(col)
    frame_pen.setWidthF(1.4)
    painter.setPen(frame_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(1.7, 2.7, 14.6, 12.6), 2.6, 2.6)

    # 2) 左侧实心条 = 导航栏本体
    #    内缩一圈再画，避免压住外框左侧描边 —— 否则左侧糊成一整块，
    #    「面板 + 里面的侧栏」这两层结构就读不出来了。
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(col)
    painter.drawRoundedRect(QRectF(3.3, 4.2, 3.1, 9.6), 1.1, 1.1)

    # 3) 方向箭头
    arrow_pen = QPen(col)
    arrow_pen.setWidthF(1.7)
    arrow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    arrow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(arrow_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if collapsed:
        pts = [(10.6, 6.5), (13.0, 9.0), (10.6, 11.5)]   # 朝右：展开
    else:
        pts = [(13.4, 6.5), (11.0, 9.0), (13.4, 11.5)]   # 朝左：收起
    painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))

    painter.end()
    return QIcon(pm)


class NavigationBar(QWidget):
    """左侧导航栏 - 剪映深色风格"""
    
    module_selected = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._buttons: Dict[str, NavigationButton] = {}
        self._current_module: Optional[str] = None
        self._theme = "dark"
        self._collapsed = False
        self._setup_ui()
    
    def set_theme(self, theme: str):
        """设置导航栏主题 - 通过theme属性让全局QSS自动响应"""
        # 更新所有导航按钮的主题
        self._theme = "light" if theme == "light" else "dark"
        for button in self._buttons.values():
            button.set_theme(self._theme)
        
        # 设置theme属性，让全局QSS属性选择器自动响应
        self.setProperty("theme", self._theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", self._theme)

        # 折叠按钮用的是内联样式（不受全局 QSS 属性选择器影响），
        # 必须在此手动刷新图标与配色 —— 漏掉这行就是浅色主题下「空框」的成因。
        self._apply_toggle_btn_style()
        
        # 更新logo标签颜色（内联样式，不受全局QSS影响）
        if theme == "light":
            self._logo_label.setStyleSheet("""
                QLabel {
                    font-size: 18px;
                    font-weight: 800;
                    color: #2563eb;
                    padding: 10px 0;
                }
            """)
            # 更新版本标签颜色
            self._version_label.setStyleSheet("color: #56657a; font-size: 12px; padding-left: 2px;")
            # 更新分隔线颜色
            self._separator.setStyleSheet("background-color: #e3eaf3; max-height: 1px; margin: 16px 0;")
        else:
            self._logo_label.setStyleSheet("""
                QLabel {
                    font-size: 18px;
                    font-weight: 800;
                    color: #edf3ff;
                    padding: 10px 0;
                }
            """)
            # 更新版本标签颜色
            self._version_label.setStyleSheet("color: #aab6cc; font-size: 12px; padding-left: 2px;")
            # 更新分隔线颜色
            self._separator.setStyleSheet("background-color: #1c2638; max-height: 1px; margin: 16px 0;")
    
    def _setup_ui(self):
        self.setFixedWidth(220)
        self.setObjectName("sideBar")
        # 不设置硬编码背景样式，由全局QSS根据theme属性自动应用
        self.setProperty("theme", self._theme)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(12)
        
        logo_widget = QWidget()
        logo_layout = QHBoxLayout(logo_widget)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(4)
        self._logo_layout = logo_layout  # 折叠态需让折叠按钮居中

        self._logo_label = QLabel("🎬 拾光剪影")
        self._logo_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: 800;
                color: #edf3ff;
                padding: 10px 0;
            }
        """)
        logo_layout.addWidget(self._logo_label, 1)

        self._toggle_btn = QPushButton()
        self._toggle_btn.setFixedSize(28, 28)
        self._toggle_btn.setIconSize(QSize(_NAV_TOGGLE_ICON_SIZE, _NAV_TOGGLE_ICON_SIZE))
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._on_toggle_clicked)
        # 图标与配色统一由 _apply_toggle_btn_style 负责（主题感知）。
        # 旧写法在这里内联写死深色主题色，且 set_theme() 从不更新它 ——
        # 浅色主题下图标色 #aab6cc 落在 #fcfdff 上只有 2.0:1，等于看不见。
        self._apply_toggle_btn_style(collapsed=False)
        logo_layout.addWidget(self._toggle_btn)

        # 修复：此处原来是 logo_layout.addWidget(logo_widget)——把容器加进它
        # 自己的布局（自嵌套），Qt 布局计算错乱导致 logo 图标与折叠按钮重叠。
        # 正确做法：logo_widget 加入外层主布局 layout。
        layout.addWidget(logo_widget)

        self._version_label = QLabel(f"v{__version__} Qt6版")
        self._version_label.setStyleSheet("color: #aab6cc; font-size: 12px; padding-left: 2px;")
        layout.addWidget(self._version_label)
        
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.Shape.HLine)
        self._separator.setStyleSheet("background-color: #1c2638; max-height: 1px; margin: 16px 0;")
        layout.addWidget(self._separator)
        
        self._button_container = QWidget()
        self._button_layout = QVBoxLayout(self._button_container)
        self._button_layout.setContentsMargins(0, 0, 0, 0)
        self._button_layout.setSpacing(8)
        layout.addWidget(self._button_container)
        
        layout.addStretch()
    
    def add_module(self, module_id: str, name: str, icon: str = ""):
        """添加导航按钮（已存在则不重复添加）

        修复（2026-09-17 折叠态图标不显示）：MainWindow._setup_ui 先按持久化
        nav_mode=compact 调 set_collapsed(True)，此时 _buttons 还是空表，折叠
        循环没作用到任何按钮；随后 _setup_default_modules 才 add_module——
        新按钮按展开态初始化（"图标+名称"、left+16px），塞进 60px 窄栏文字
        被裁没，图标消失。故新按钮创建时必须继承栏当前的折叠态。"""
        if module_id in self._buttons:
            return
        button = NavigationButton(name, icon, module_id)
        button.set_theme(self._theme)
        if self._collapsed:
            button.set_collapsed(True)
        button.clicked.connect(lambda: self._on_button_clicked(module_id))
        self._buttons[module_id] = button
        self._button_layout.addWidget(button)

    def remove_module(self, module_id: str):
        """移除导航按钮（运行时开关关闭时调用）"""
        if module_id not in self._buttons:
            return
        btn = self._buttons.pop(module_id)
        btn.setParent(None)
        btn.deleteLater()
        # 如果移除的是当前选中项，则切回 home
        if self._current_module == module_id:
            self._current_module = None
            if "home" in self._buttons:
                self._on_button_clicked("home")

    def has_module(self, module_id: str) -> bool:
        return module_id in self._buttons

    def _on_button_clicked(self, module_id: str):
        if self._current_module:
            self._buttons[self._current_module].set_active(False)
        
        self._current_module = module_id
        self._buttons[module_id].set_active(True)
        self.module_selected.emit(module_id)
    
    def select_module(self, module_id: str):
        if module_id in self._buttons:
            self._on_button_clicked(module_id)

    # —— 折叠/展开 ——

    def _apply_toggle_btn_style(self, collapsed: Optional[bool] = None):
        """刷新折叠按钮的图标与配色（主题感知 + 状态感知）。

        必须由 `set_theme()` 与 `set_collapsed()` 共同调用：
        原先该按钮的样式只在 `_setup_ui` 里设置一次、颜色写死为深色主题值，
        主题切换后不会更新 —— 浅色主题下图标对比度只有 2.0:1，肉眼等同空框。
        """
        if collapsed is None:
            collapsed = self._collapsed
        theme = "light" if self._theme == "light" else "dark"

        self._toggle_btn.setIcon(
            _make_nav_toggle_icon(collapsed, _NAV_TOGGLE_ICON_COLORS[theme])
        )
        # 提示语说清「点了会怎样」，而不只是复述按钮名
        self._toggle_btn.setToolTip(
            "展开导航栏（显示模块名称）" if collapsed
            else "收起导航栏（只保留图标，腾出画面宽度）"
        )

        # 给按钮一个淡底色块而不是只有描边 —— 「看起来像按钮」本身就是可发现性
        if theme == "light":
            self._toggle_btn.setStyleSheet("""
                QPushButton {
                    background: #eef3f9;
                    border: 1px solid #dce5f0;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background: #dde7f4;
                    border: 1px solid #c6d4e6;
                }
                QPushButton:pressed {
                    background: #cfdcef;
                }
            """)
        else:
            self._toggle_btn.setStyleSheet("""
                QPushButton {
                    background: #172033;
                    border: 1px solid #253044;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background: #1f2b42;
                    border: 1px solid #31405c;
                }
                QPushButton:pressed {
                    background: #25334c;
                }
            """)

    def set_collapsed(self, collapsed: bool):
        """折叠/展开导航栏：折叠时只显示图标，宽度缩到 60px

        几何账（2026-09-17 修复折叠图标残缺）：折叠宽 60、主布局左右边距
        收窄为各 8 → 按钮可用宽 = 60-16 = 44px，与 NavigationButton 折叠
        固定宽 44 精确吻合。此前折叠宽 56 但边距仍是 16+16 → 可用仅 24px，
        44px 按钮被裁掉一半（图标残缺、悬浮区过小连 tooltip 都难触发）。
        """
        self._collapsed = collapsed
        target_w = 60 if collapsed else 220
        self.setFixedWidth(target_w)
        lay = self.layout()
        if lay is not None:
            if collapsed:
                lay.setContentsMargins(8, 12, 8, 12)
            else:
                lay.setContentsMargins(16, 20, 16, 20)

        # logo + 版本 + 分隔线：折叠时隐藏
        self._logo_label.setVisible(not collapsed)
        self._version_label.setVisible(not collapsed)
        self._separator.setVisible(not collapsed)

        # 折叠按钮在窄栏内居中
        if collapsed:
            self._logo_layout.setAlignment(self._toggle_btn, Qt.AlignmentFlag.AlignCenter)
        else:
            self._logo_layout.setAlignment(self._toggle_btn, Qt.AlignmentFlag.AlignLeft)

        # 所有导航按钮：折叠时只保留图标（居中样式）
        for btn in self._buttons.values():
            btn.set_collapsed(collapsed)

        # 折叠按钮：图标方向 + 提示语都随状态翻转（同时刷新主题配色）
        self._apply_toggle_btn_style(collapsed)

    def is_collapsed(self) -> bool:
        return getattr(self, "_collapsed", False)

    def set_nav_mode(self, mode: str):
        """导航栏显示模式（主题设置里的持久化选项）：
        "compact" = 仅显示图标（悬浮显示名称）；"full" = 显示图标和名称。
        与折叠状态共用同一套几何，但作为持久化模式存在；折叠按钮的
        手动切换也会同步写回该设置（同一事实源）。"""
        self.set_collapsed(mode == "compact")

    def _on_toggle_clicked(self):
        self.set_collapsed(not self.is_collapsed())
        # 手动折叠/展开同样持久化，重启后保持
        try:
            QSettings("拾光剪影", "Settings").setValue(
                "nav_mode", "compact" if self.is_collapsed() else "full"
            )
        except Exception as e:
            logger.debug("持久化导航栏模式失败: %s", e)


class MainWindow(QMainWindow):
    """
    主窗口 - 剪映同款标签页布局
    
    结构：
    ├── 左侧导航栏（固定）
    │     ├── 首页
    │     ├── 剪辑
    │     ├── 文案生成
    │     ├── 多任务
    │     ├── 素材库
    │     ├── 插件中心
    │     └── 性能监控
    ├── 中央内容区（标签页切换）
    └── 底部状态栏（全局提示、监控）
    """
    
    def __init__(self):
        super().__init__()
        self._modules: Dict[str, ModuleInfo] = {}
        self._event_bus = EventBus.get_instance()
        
        self._lazy_loaded_modules: Dict[str, bool] = {}
        self._module_loading_queue: List[str] = []
        self._current_loading_module: Optional[str] = None
        self._pending_module_actions: Dict[str, dict] = {}
        self._preload_priority: Dict[str, int] = {
            'home': 1,
            'editor': 2,
            'copywriting': 3,
            'tasks': 4,
            'characters': 5,
            'extensions': 6,
            'materials': 7,
            'performance': 9,
            'models': 10,
            'settings': 11,
            'help': 12
        }
        
        self._auth_service = auth_service
        self._settings = QSettings("拾光剪影", "Settings")
        self._setup_ui()
        self._setup_default_modules()
        self._update_auth_status()

        # 修复：窗口几何保存钩子刻意不放进 closeEvent（该方法属于 exit-media
        # 冻结区，未解冻不能碰），改用 QApplication.aboutToQuit 信号，
        # 效果等价（真正退出前触发一次）但不触碰冻结符号。
        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._save_window_geometry)
        except Exception as e:
            logger.debug(f"绑定窗口几何保存钩子失败: {e}")
        
        self._apply_initial_theme()
        self._setup_lazy_loading()
    
    def _apply_initial_theme(self):
        """应用初始主题（通过 ThemeManager 统一管理）"""
        tm = ThemeManager.instance()
        saved_theme = self._settings.value("theme")
        if saved_theme:
            tm.apply_theme(saved_theme, main_window=self)
        else:
            # 根据时间自动切换
            from datetime import datetime
            hour = datetime.now().hour
            tm.apply_theme("light" if 6 <= hour < 18 else "dark", main_window=self)
    
    def _apply_time_based_theme(self):
        """根据时间自动应用主题（兼容旧调用）"""
        from datetime import datetime
        hour = datetime.now().hour
        ThemeManager.instance().apply_theme(
            "light" if 6 <= hour < 18 else "dark", main_window=self
        )
    
    def _setup_lazy_loading(self):
        """延迟加载：仅标记首页；禁止后台 _on_module_selected（会抢激活并卡主线程）。"""
        self._preload_module("home")
    
    def _preload_module(self, module_id: str):
        """预加载指定模块（仅标记，不实例化、不切换）。"""
        if module_id in self._lazy_loaded_modules:
            return
        
        try:
            # 懒注册模块的 widget_class 为 None，需按 _mod_def 判定其可加载性
            info = self._modules.get(module_id)
            if info and (info.widget_class or getattr(info, "_mod_def", None)):
                self._lazy_loaded_modules[module_id] = True
                logger.info(f"模块 {module_id} 已预加载")
        except Exception as e:
            logger.warning(f"模块 {module_id} 预加载失败: {e}")
    
    def _start_background_loading(self):
        """兼容旧调用：已禁用后台抢激活加载。"""
        return
    
    def _load_next_module(self):
        """兼容旧调用：已禁用。"""
        return
    
    def _load_module_async(self, module_id: str):
        """兼容旧调用：已禁用（勿再走 _on_module_selected）。"""
        self._current_loading_module = None
        if module_id in self._module_loading_queue:
            self._module_loading_queue.remove(module_id)
    
    def get_loading_status(self) -> Dict[str, Any]:
        """获取加载状态"""
        return {
            'loaded_modules': list(self._lazy_loaded_modules.keys()),
            'loading_queue': self._module_loading_queue.copy(),
            'current_loading': self._current_loading_module,
            'total_modules': len(self._modules),
            'loading_progress': len(self._lazy_loaded_modules) / len(self._modules) * 100
        }
    
    def preload_all_modules(self):
        """预加载所有模块"""
        for module_id in self._preload_priority.keys():
            self._preload_module(module_id)
    
    def clear_lazy_cache(self):
        """清理延迟加载缓存"""
        self._lazy_loaded_modules.clear()
        self._module_loading_queue.clear()
        self._current_loading_module = None
        logger.info("延迟加载缓存已清理")
    
    def _setup_ui(self):
        self.setWindowTitle(f"拾光剪影 v{__version__}")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)
        self._restore_window_geometry()
        
        central_widget = QWidget()
        central_widget.setObjectName("contentContainer")
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        nav_content_layout = QHBoxLayout()
        nav_content_layout.setContentsMargins(0, 0, 0, 0)
        nav_content_layout.setSpacing(0)
        
        self._nav_bar = NavigationBar()
        self._nav_bar.module_selected.connect(self._on_module_selected)
        nav_content_layout.addWidget(self._nav_bar)

        # 应用持久化的导航栏显示模式（主题设置 →「导航栏」；full=图标+名称 / compact=仅图标）
        try:
            saved_nav_mode = self._settings.value("nav_mode", "full")
            self._nav_bar.set_nav_mode("compact" if saved_nav_mode == "compact" else "full")
        except Exception as e:
            logger.debug("应用导航栏显示模式失败: %s", e)
        
        content_widget = QWidget()
        content_widget.setObjectName("moduleContainer")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 顶部状态栏 - 显示授权状态
        # V4.42.0 起改为 Trae IDE 风格 4 按钮：🔔 通知 / 🎨 主题 / ⚙ 设置 / 👤 用户中心
        # 设计目标：把"消息/主题/设置/帮助/反馈/检查更新/退出登录"统一到最顶上，
        #          主程序登顶之前那种"登录+激活"两个冷按钮让位给完整用户中心面板。
        self._top_status_bar = QFrame()
        self._top_status_bar.setObjectName("headerBar")
        self._top_status_bar.setFixedHeight(40)
        top_layout = QHBoxLayout(self._top_status_bar)
        top_layout.setContentsMargins(16, 0, 16, 0)
        top_layout.setSpacing(8)

        # 左侧状态信息
        self._status_label = QLabel("未登录 / 未授权")
        self._status_label.setStyleSheet("color: #fbbf24; font-size: 13px; font-weight: 600;")
        top_layout.addWidget(self._status_label)

        top_layout.addStretch()

        # 右侧 4 按钮（按 Trae IDE 排序：通知 → 主题 → 设置 → 用户中心）
        # 通知按钮 — 暂作为统一入口占位，点击触发用户中心面板的通知段
        self._notif_btn = QPushButton("🔔")
        self._notif_btn.setObjectName("headerBarIconBtn")
        self._notif_btn.setFixedHeight(28)
        self._notif_btn.setFixedWidth(36)
        self._notif_btn.setToolTip("通知中心")
        self._notif_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._notif_btn.clicked.connect(self._on_notif_btn_clicked)
        top_layout.addWidget(self._notif_btn)

        # 主题按钮 — 直接 light/dark 切换（避免再开面板）
        self._theme_btn = QPushButton("🎨")
        self._theme_btn.setObjectName("headerBarIconBtn")
        self._theme_btn.setFixedHeight(28)
        self._theme_btn.setFixedWidth(36)
        self._theme_btn.setToolTip("切换主题")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        top_layout.addWidget(self._theme_btn)

        # 设置按钮 — 直跳设置模块（按用户要求"置顶"）
        self._header_settings_btn = QPushButton("⚙")
        self._header_settings_btn.setObjectName("headerBarIconBtn")
        self._header_settings_btn.setFixedHeight(28)
        self._header_settings_btn.setFixedWidth(36)
        self._header_settings_btn.setToolTip("设置")
        self._header_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_settings_btn.clicked.connect(self._show_settings)
        top_layout.addWidget(self._header_settings_btn)

        # 用户中心按钮 — 已登录显示头像文字 / 未登录显示"登录"
        self._user_btn = QPushButton("登录")
        self._user_btn.setObjectName("primaryBtn")
        self._user_btn.setFixedHeight(28)
        self._user_btn.setFixedWidth(80)
        self._user_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._user_btn.clicked.connect(self._on_user_btn_clicked)
        top_layout.addWidget(self._user_btn)
        
        content_layout.addWidget(self._top_status_bar)
        
        self._tab_widget = QTabWidget()
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setTabsClosable(False)
        self._tab_widget.setMovable(True)
        self._tab_widget.tabBar().hide()
        content_layout.addWidget(self._tab_widget)
        
        nav_content_layout.addWidget(content_widget, 1)
        
        main_layout.addLayout(nav_content_layout, 1)
        
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        self._event_bus.on(EventType.MODULE_ACTIVATED, self._on_module_activated)
        self._event_bus.on(EventType.PROVIDER_ACTIVATED, self._on_provider_sync_canvas_models)
        # 功能开关变更：动态刷新导航栏
        self._event_bus.on(EventType.MODULE_CONFIG_CHANGED,
                           lambda _evt: self.apply_module_changes())
        # 主题切换：同步更新全局UI
        self._event_bus.on(EventType.THEME_CHANGED, self._on_theme_changed)
    
    def _setup_default_modules(self):
        """从模块注册表读取并注册已启用的模块（核心 + 开启的高级/实验）"""
        registry = get_registry()

        enabled = registry.enabled_modules()
        logger.info(
            "注册表启动：共 %d 个模块定义，当前启用 %d 个，关闭 %d 个",
            len(registry.all_modules()),
            len(enabled),
            len(registry.disabled_modules()),
        )

        for mod in enabled:
            module_id = mod["id"]
            name = mod["name"]
            icon = mod.get("icon", "")
            desc = mod.get("description", "")
            # 真懒加载（冷启动 P2）：此处只做「有没有界面类」的**静态判定**，不 import。
            # 原先走 `_lazy_import_widget_class(mod)` + `register_module(...)`，
            # 名字叫 lazy 但对全部启用模块逐个 importlib.import_module，
            # 实测 _setup_default_modules 因此耗时 0.217s（editor_module 0.075s 最重），
            # 窗口要等 8 个模块全部导入完才出现。
            # 现改为登记 mod_def，widget_class 由 _get_widget_class_lazy 在首次激活时导入
            # —— 复用早已存在但启动路径没走上的懒加载机制。
            if not mod.get("import_module") or not mod.get("import_class"):
                logger.warning("模块 %s 无界面类，已从导航栏省略", module_id)
                continue
            self.register_module_lazy(module_id, name, icon, desc, mod)

        # 预加载优先级按注册表顺序自动生成
        for idx, mod in enumerate(enabled):
            self._preload_priority[mod["id"]] = idx + 1

        self._nav_bar.select_module("home")

    def _lazy_import_widget_class(self, mod_def: dict):
        """
        延迟导入：按需 import 模块类，避免启动时一次性加载所有 UI 代码。
        导入失败时记日志并跳过（不再因 optional 静默吞掉）。
        """
        import_module = mod_def.get("import_module")
        import_class = mod_def.get("import_class")

        if not import_module or not import_class:
            return None

        try:
            # 相对导入：from .xxx import YYY
            package = "app.modules.lego" if import_module.startswith(".") else None
            # 使用 importlib 做相对导入
            import importlib
            if package and import_module.startswith("."):
                module = importlib.import_module(import_module, package=package)
            else:
                module = importlib.import_module(import_module)
            widget_class = getattr(module, import_class, None)
            return widget_class
        except Exception as e:
            logger.warning("模块 %s (%s) 导入失败: %s", mod_def.get("id"), import_class, e)
            return None

    def apply_module_changes(self):
        """
        运行时刷新导航栏：根据注册表最新开关状态动态增删导航按钮。
        由设置面板的「功能开关」保存后调用。
        使用 QTimer 延迟到下一个事件循环，避免阻塞UI
        """
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._apply_module_changes_impl)

    def _apply_module_changes_impl(self):
        """实际执行模块变更（延迟到下一个事件循环）"""
        registry = get_registry()
        current_enabled = {m["id"] for m in registry.enabled_modules()}

        # 1) 新增：注册表中已启用但导航栏尚未显示
        for mod in registry.enabled_modules():
            mid = mod["id"]
            if not self._nav_bar.has_module(mid):
                # 懒加载 widget_class（不立即实例化）
                self.register_module_lazy(
                    mid, mod["name"], mod.get("icon", ""),
                    mod.get("description", ""), mod
                )
                logger.info("运行时启用模块: %s", mid)

        # 2) 移除：导航栏中显示但注册表已关闭
        for mid in list(self._modules.keys()):
            info = self._modules[mid]
            if mid not in current_enabled:
                # 从导航栏移除按钮
                self._nav_bar.remove_module(mid)
                # 从标签页移除实例
                if info.instance is not None:
                    for i in range(self._tab_widget.count()):
                        if self._tab_widget.tabText(i) == f"{info.icon} {info.name}":
                            self._tab_widget.removeTab(i)
                            break
                    info.instance.deleteLater()
                    info.instance = None
                info.state = ModuleState.INACTIVE
                logger.info("运行时关闭模块: %s", mid)

    def register_module(self, module_id: str, name: str, icon: str, description: str,
                       widget_class: Type[QWidget] = None):
        """注册模块"""
        info = ModuleInfo(
            id=module_id,
            name=name,
            icon=icon,
            description=description,
            widget_class=widget_class
        )
        self._modules[module_id] = info
        self._nav_bar.add_module(module_id, name, icon)

    def register_module_lazy(self, module_id: str, name: str, icon: str, description: str,
                            mod_def: dict):
        """懒加载注册模块（不立即导入widget_class，避免阻塞UI）"""
        # 存储模块定义，但不立即导入 widget_class
        info = ModuleInfo(
            id=module_id,
            name=name,
            icon=icon,
            description=description,
            widget_class=None  # 延迟到首次激活时导入
        )
        info._mod_def = mod_def  # 保存模块定义用于延迟加载
        self._modules[module_id] = info
        self._nav_bar.add_module(module_id, name, icon)
    
    def _get_widget_class_lazy(self, module_id: str):
        """延迟获取 widget_class"""
        info = self._modules.get(module_id)
        if not info or info.widget_class:
            return info.widget_class if info else None

        mod_def = getattr(info, '_mod_def', None)
        if not mod_def:
            return None

        widget_class = self._lazy_import_widget_class(mod_def)
        if widget_class:
            info.widget_class = widget_class
        return widget_class

    def set_module_widget(self, module_id: str, widget: QWidget):
        """设置模块界面"""
        if module_id not in self._modules:
            return

        info = self._modules[module_id]

        if info.instance:
            for i in range(self._tab_widget.count()):
                if self._tab_widget.tabText(i) == f"{info.icon} {info.name}":
                    self._tab_widget.removeTab(i)
                    break

        info.instance = widget
        current_theme = ThemeManager.instance().current_theme
        widget.setProperty("theme", current_theme)
        for child in widget.findChildren(QWidget):
            child.setProperty("theme", current_theme)
        self._tab_widget.addTab(widget, f"{info.icon} {info.name}")

    def get_module_widget(self, module_id: str) -> Optional[QWidget]:
        """获取模块界面"""
        if module_id in self._modules:
            return self._modules[module_id].instance
        return None

    def _on_module_selected(self, module_id: str):
        """模块选中事件"""
        if module_id not in self._modules:
            return

        info = self._modules[module_id]

        if info.instance:
            self._activate_module(module_id, info)
            return

        # 懒注册模块的 widget_class 初始为 None（只有 _mod_def），
        # 因此不能只看 widget_class —— 否则懒注册的模块永远进不了加载流程。
        if (info.widget_class or getattr(info, "_mod_def", None)) \
                and info.state == ModuleState.INACTIVE:
            info.state = ModuleState.LOADING
            self._show_loading_indicator(module_id)
            self._load_module_with_progress(module_id)

    def _show_loading_indicator(self, module_id: str):
        """显示加载指示器"""
        info = self._modules.get(module_id)
        if not info:
            return

        loading_widget = QWidget()
        loading_layout = QVBoxLayout(loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        spinner = QLabel("⏳")
        spinner.setStyleSheet("font-size: 48px;")
        loading_layout.addWidget(spinner)

        loading_label = QLabel(f"正在加载 {info.name}...")
        loading_label.setStyleSheet("color: #ffffff; font-size: 16px;")
        loading_layout.addWidget(loading_label)

        self.set_module_widget(module_id, loading_widget)

    def _load_module_with_progress(self, module_id: str):
        """带进度的模块加载"""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._perform_module_load(module_id))

    def _perform_module_load(self, module_id: str):
        """执行模块加载（在主线程中）"""
        info = self._modules.get(module_id)
        if not info:
            return

        # 如果是懒加载注册的模块，先获取 widget_class
        if not info.widget_class:
            widget_class = self._get_widget_class_lazy(module_id)
            if not widget_class:
                self._show_module_error(module_id, "无法加载模块类")
                return

        try:
            widget = info.widget_class()

            if module_id == "settings":
                widget.settings_changed.connect(self._on_settings_changed)

            info.state = ModuleState.LOADED
            info.instance = widget
            self.set_module_widget(module_id, widget)
            self._activate_module(module_id, info)
        except Exception as e:
            import traceback
            logger.error(f"模块 {module_id} 加载失败: {e}")
            traceback.print_exc()
            self._show_module_error(module_id, str(e))

    def _show_module_error(self, module_id: str, error_msg: str):
        """显示模块加载错误"""
        info = self._modules.get(module_id)
        if not info:
            return

        info.state = ModuleState.ERROR
        error_widget = QWidget()
        error_layout = QVBoxLayout(error_widget)
        error_label = QLabel(f"模块 {info.name} 加载失败\n错误信息: {error_msg}")
        error_label.setStyleSheet("color: #ff4757; padding: 20px;")
        error_layout.addWidget(error_label)
        self.set_module_widget(module_id, error_widget)

    def _activate_module(self, module_id: str, info):
        """激活并显示模块"""
        if info.instance:
            for i in range(self._tab_widget.count()):
                if self._tab_widget.tabText(i) == f"{info.icon} {info.name}":
                    self._tab_widget.setCurrentIndex(i)
                    break
        
        if info.state != ModuleState.ERROR:
            info.state = ModuleState.ACTIVE
            self._event_bus.emit(
                EventType.MODULE_ACTIVATED,
                {"module_id": module_id, "module_name": info.name}
            )
            self._flush_pending_module_action(module_id)
    
    def _on_settings_changed(self, setting_type, settings):
        """设置更改事件处理"""
        if "theme" in settings:
            theme = settings["theme"]
            self._apply_theme(theme)
            # 持久化主题设置
            self._settings.setValue("theme", theme)

        # 导航栏显示模式（设置→外观→主题设置→「导航栏」；即时生效）
        if "nav_mode" in settings:
            mode = settings["nav_mode"]
            if hasattr(self, "_nav_bar"):
                try:
                    self._nav_bar.set_nav_mode("compact" if mode == "compact" else "full")
                except Exception as e:
                    logger.debug("应用导航栏显示模式失败: %s", e)

        if "font_size" in settings or "font_family" in settings:
            self._apply_font_settings(settings)
    
    def _on_theme_changed(self, event):
        """响应设置模块的主题切换事件，同步全局UI（通过 ThemeManager 统一处理）"""
        theme = event.data.get("theme", "dark")
        self._apply_theme(theme)
        # 同步刷新已实例化的用户中心面板
        panel = getattr(self, "_user_center_panel", None)
        if panel is not None:
            try:
                panel.on_theme_changed(theme)
            except Exception as e:
                logger.debug("同步用户中心面板主题失败: %s", e)

    def _apply_theme(self, theme):
        """
        应用主题 - 通过 ThemeManager 统一管理

        历史问题修复：
        1. 卡死 → ThemeManager 内置 _applying 防递归标志位，避免 EventBus 往复触发死循环
        2. 未生效 → 通过 QApplication.setStyleSheet() 全局应用 QSS，
                    主窗口 setProperty("theme", ...) 让所有子控件自动级联响应
        3. 性能 → 不再使用 findChildren + unpolish/polish 暴力遍历
        """
        tm = ThemeManager.instance()
        tm.apply_theme(theme, main_window=self)
        actual_theme = tm.current_theme

        # 更新导航栏主题（保留模块自身的导航栏样式逻辑）
        if hasattr(self, "_nav_bar"):
            try:
                self._nav_bar.set_theme(actual_theme)
            except Exception as e:
                logger.debug("导航栏主题更新失败: %s", e)

        # 给所有已加载模块设置 theme 属性（不调用 set_theme 避免重复触发）
        for module_id, module_info in self._modules.items():
            if module_info.instance:
                try:
                    module_info.instance.setProperty("theme", actual_theme)
                    for child in module_info.instance.findChildren(QWidget):
                        child.setProperty("theme", actual_theme)
                except Exception as e:
                    logger.debug("模块 %s 主题属性设置失败: %s", module_id, e)

        # 持久化主题设置
        self._settings.setValue("theme", theme)
        self._settings.setValue("resolved_theme", actual_theme)

    def _apply_font_settings(self, settings):
        """应用字体设置"""
        font_size = settings.get("font_size", 14)
        font_family = settings.get("font_family", "Microsoft YaHei")
        
        # 应用字体设置到整个应用
        font = self.font()
        font.setFamily(font_family)
        font.setPointSize(font_size)
        self.setFont(font)
        
        # 应用字体设置到子控件
        def apply_font_to_widget(widget):
            widget.setFont(font)
            for child in widget.children():
                if hasattr(child, 'setFont'):
                    apply_font_to_widget(child)
        
        # 应用到中央部件
        apply_font_to_widget(self.centralWidget())
        
        # 应用到导航栏
        if hasattr(self, "_nav_bar"):
            apply_font_to_widget(self._nav_bar)
        
        # 应用到所有模块
        for module_id, module_info in self._modules.items():
            if module_info.instance:
                apply_font_to_widget(module_info.instance)
    
    # NOTE: _apply_dark_theme / _apply_light_theme 已被 ThemeManager 取代，不再需要
    # 主题 QSS 现在统一由 ThemeManager._build_qss() 生成，通过 QApplication 级别应用
    
    def _flush_pending_module_action(self, module_id: str) -> None:
        """交付 MODULE_ACTIVATED 携带的子页跳转 / 工作流提示（模块懒加载完成后调用）。"""
        pending = self._pending_module_actions.pop(module_id, None)
        if not pending:
            return

        widget = self.get_module_widget(module_id)
        action = pending.get("action")
        workflow_hint = pending.get("workflow_hint")
        nav_hint = pending.get("hint")

        # 携带数据交付（如文案模块「推送到剪辑模块」）：此时模块已确定加载
        # 完成、监听器已注册，emit 才是真正有接收方的
        data_payload = pending.get("data")
        if data_payload:
            self._event_bus.emit(EventType.COPY_GENERATED, data_payload)

        # 修复：首页「最近项目」双击此前只切到编辑器页签，从不真正加载工程——
        # 这里补上真正的打开逻辑
        if module_id == "editor" and action == "open_project":
            project_path = pending.get("project")
            if widget is not None and project_path and hasattr(widget, "import_project"):
                try:
                    widget.import_project(project_path)
                except Exception as e:
                    self.show_status(f"打开工程失败: {e}", "#f97316")
            return

        if module_id == "editor" and workflow_hint and widget:
            if hasattr(widget, "_on_workflow_hint_received"):
                widget._on_workflow_hint_received(workflow_hint)
            elif nav_hint:
                self.show_status(nav_hint, "#ea580c")

        if module_id == "characters" and pending.get("sync_models") and widget:
            if hasattr(widget, "_on_sync_models"):
                try:
                    widget._on_sync_models()
                except Exception as e:
                    self.show_status(f"同步模型池失败: {e}", "#f97316")
            if nav_hint:
                self.show_status(nav_hint, "#14b8a6")
            return

        if module_id == "characters" and nav_hint:
            self.show_status(nav_hint, "#14b8a6")

    def _on_provider_sync_canvas_models(self, _event) -> None:
        """模型管理保存/激活 Key 后，若 AI 画布已加载则静默同步模型池（不切页签）。"""
        info = self._modules.get("characters")
        if not info or not info.instance:
            return
        widget = info.instance
        if hasattr(widget, "_on_provider_activated_sync"):
            try:
                widget._on_provider_activated_sync(_event)
            except Exception as e:
                logger.debug("画布模型池静默同步失败: %s", e)

    def _on_module_activated(self, event):
        """模块激活事件处理 — 支持携带数据、子页跳转与工作流提示"""
        data = event.data if isinstance(event.data, dict) else {}
        # _activate_module 会广播 {module_id, module_name}，不是跨模块跳转请求
        if data.get("module_id") and not data.get("target"):
            return

        target = data.get("target")
        if not target and isinstance(event.data, str):
            target = event.data
        payload = data.get("data")
        action = data.get("action")
        workflow_hint = data.get("workflow_hint")
        nav_hint = data.get("hint")
        project_path = data.get("project")

        if not target:
            return

        # M1：旧事件 target=plugins → 拓展中心 extensions
        if target == "plugins":
            target = "extensions"

        registry = get_registry()
        if not registry.is_enabled(target):
            self.show_status(f"模块「{target}」未启用，请在设置 → 功能开关中打开", "#f97316")
            return

        if target not in self._modules or not self._nav_bar.has_module(target):
            self.show_status(f"导航中无模块「{target}」", "#f97316")
            return

        if action or workflow_hint or nav_hint or payload or data.get("sync_models"):
            self._pending_module_actions[target] = {
                "action": action,
                "workflow_hint": workflow_hint,
                "hint": nav_hint,
                "project": project_path,
                "data": payload,
                "sync_models": bool(data.get("sync_models")),
            }

        self._nav_bar.select_module(target)

        # 模块已实例化时 select_module 不会再次走 _activate_module，需立即交付
        info = self._modules.get(target)
        if info and info.instance and info.state != ModuleState.ERROR:
            QTimer.singleShot(0, lambda mid=target: self._flush_pending_module_action(mid))
        # 修复：此前不管目标模块是否已加载，这里都会立即 emit COPY_GENERATED，
        # 但如果模块还没加载（懒加载走 QTimer.singleShot(50,...) 异步创建），
        # 此刻根本没有监听者，payload 会直接丢失且没有任何提示——用户以为
        # "推送成功"，编辑器里实际什么都没收到。现在统一改为通过
        # _pending_module_actions → _flush_pending_module_action 交付，
        # 保证只在模块真正加载完成（监听器已注册）之后才发送。
    
    def switch_to_module(self, module_id: str):
        """切换到指定模块"""
        self._nav_bar.select_module(module_id)
    
    def show_status(self, message: str, color: str = "#808080"):
        """显示状态消息"""
        self._status_bar.showMessage(message, 3000)  # 3秒后自动消失
        self._status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: #2a2a2a;
                color: {color};
                font-size: 13px;
                font-weight: 500;
            }}
        """)
    
    def _show_help(self):
        """显示帮助信息"""
        from .help_module import HelpModule
        if "help" in self._modules and not self._modules["help"].instance:
            self.set_module_widget("help", HelpModule())
        self.switch_to_module("help")
    
    def _show_settings(self):
        """显示设置界面"""
        from .settings_module import SettingsModule
        if "settings" in self._modules and not self._modules["settings"].instance:
            self.set_module_widget("settings", SettingsModule())
        self.switch_to_module("settings")
    
    def _on_login_clicked(self):
        """登录按钮点击事件 - 异步非阻塞方式"""
        from .login_window import LoginWindow
        login_window = LoginWindow(parent=self)
        login_window.login_success.connect(self._on_login_success)
        login_window.show()
    
    def _on_login_success(self):
        """登录成功回调"""
        self._update_auth_status()
        self.show_status("登录成功", "#4caf50")
        # 同步刷新用户中心面板（如已实例化）
        panel = getattr(self, "_user_center_panel", None)
        if panel is not None:
            try:
                panel.refresh_state()
            except Exception as e:
                logger.debug("刷新用户中心面板失败: %s", e)
    
    def _on_activate_clicked(self):
        """激活按钮点击事件 - 异步非阻塞方式"""
        from .login_window import ActivationWindow
        activation_window = ActivationWindow(parent=self)
        activation_window.activation_success.connect(self._on_activation_success)
        activation_window.show()
    
    def _on_activation_success(self):
        """激活成功回调"""
        self._update_auth_status()
        self.show_status("激活成功", "#4caf50")
        panel = getattr(self, "_user_center_panel", None)
        if panel is not None:
            try:
                panel.refresh_state()
            except Exception as e:
                logger.debug("刷新用户中心面板失败: %s", e)
    
    def _update_auth_status(self):
        """更新授权状态"""
        if self._auth_service.is_logged_in:
            user = self._auth_service.current_user
            if user and user.is_vip:
                expire_date = user.vip_expire
                if expire_date > 0:
                    from datetime import datetime
                    expire_str = datetime.fromtimestamp(expire_date).strftime("%Y-%m-%d")
                    self._status_label.setText(f"已登录 - VIP 到期: {expire_str}")
                    self._status_label.setStyleSheet("color: #4caf50; font-size: 13px; font-weight: 500;")
                else:
                    self._status_label.setText("已登录 - VIP")
                    self._status_label.setStyleSheet("color: #4caf50; font-size: 13px; font-weight: 600;")
            else:
                self._status_label.setText(f"已登录 - {user.nickname}")
                self._status_label.setStyleSheet("color: #4caf50; font-size: 13px; font-weight: 500;")
            # V4.42.0: headerBar 用户中心按钮跟着改文案
            if hasattr(self, "_user_btn") and self._user_btn is not None:
                nickname = (user.nickname or user.email or "已登录") if user else "已登录"
                first_ch = nickname[0].upper() if nickname else "U"
                prefix = "👑" if (user and getattr(user, "is_vip", False)) else "👤"
                self._user_btn.setText(f"{prefix} {first_ch}")
        else:
            self._status_label.setText("未登录 / 未授权")
            self._status_label.setStyleSheet("color: #f59e0b; font-size: 13px; font-weight: 500;")
            if hasattr(self, "_user_btn") and self._user_btn is not None:
                self._user_btn.setText("登录")

    # ────── V4.42.0 顶部 headerBar 4 按钮（通知/主题/设置/用户中心）──────
    def _toggle_theme(self):
        """快速切换 dark / light 主题（headerBar 主题按钮）"""
        tm = ThemeManager.instance()
        try:
            current = getattr(tm, "current_theme", None) or "dark"
        except Exception:
            current = "dark"
        new_theme = "light" if current == "dark" else "dark"
        self._apply_theme(new_theme)
        self._settings.setValue("theme", new_theme)
        self.show_status(f"已切换到{('浅色' if new_theme == 'light' else '深色')}主题", "#4caf50")

    def _on_notif_btn_clicked(self):
        """通知按钮 — 弹通知中心面板（V4.42.1 起不再是复用用户中心）"""
        self._popup_notification_center()

    def _on_user_btn_clicked(self):
        """用户中心按钮 — 弹面板"""
        self._popup_user_center()

    def _get_user_center_panel(self):
        """懒加载用户中心面板单例"""
        if getattr(self, "_user_center_panel", None) is None:
            from .user_center_panel import UserCenterPanel
            from app.core.update_manager import update_manager
            self._user_center_panel = UserCenterPanel(
                auth_service=self._auth_service,
                theme_manager=ThemeManager.instance(),
                update_manager=update_manager,
                parent=self,
            )
            self._wire_user_center_signals(self._user_center_panel)
        return self._user_center_panel

    def _wire_user_center_signals(self, panel):
        """把用户中心面板的 11 个业务信号接到 main_window 现有方法上"""
        panel.login_requested.connect(self._on_login_clicked)
        panel.activate_requested.connect(self._on_activate_clicked)
        panel.settings_requested.connect(self._show_settings)
        panel.theme_requested.connect(self._toggle_theme)
        panel.help_requested.connect(self._show_help)
        panel.feedback_requested.connect(self._on_feedback_clicked)
        panel.check_update_requested.connect(self._on_check_update_clicked)
        panel.logout_requested.connect(self._on_logout_completed)
        panel.notifications_requested.connect(self._on_notifications_clicked)
        panel.upgrade_requested.connect(self._on_activate_clicked)
        panel.register_requested.connect(self._on_register_clicked)

    def _popup_user_center(self):
        """在 _user_btn 正下方弹出用户中心面板"""
        panel = self._get_user_center_panel()
        try:
            panel.refresh_state()
        except Exception as e:
            logger.debug("刷新用户中心面板失败: %s", e)
        panel.popup_below(self._user_btn)

    def _on_logout_completed(self):
        """退出登录后的 UI 同步"""
        self._update_auth_status()
        self.show_status("已退出登录", "#fbbf24")

    def _on_feedback_clicked(self):
        """意见反馈 — 弹 FeedbackDialog"""
        self._popup_feedback_dialog()

    def _on_notifications_clicked(self):
        """通知中心 — 弹 NotificationCenterPanel"""
        self._popup_notification_center()

    def _on_register_clicked(self):
        """注册入口 — 直接复用登录窗口并切到注册 Tab"""
        self._on_login_clicked()

    def _on_check_update_clicked(self):
        """检查更新 — 调 update_manager.check_async()，并写通知中心留痕"""
        try:
            from app.core.update_manager import update_manager
            update_manager.check_async()
            # 把触发动作写到通知中心（让用户有可视化的等待反馈）
            try:
                from app.core.notification_store import notification_store, TYPE_UPDATE, LEVEL_INFO
                notification_store().notify(
                    title="开始检查更新",
                    body="后台正在查询最新版本，完成后会写入通知中心",
                    type=TYPE_UPDATE,
                    level=LEVEL_INFO,
                )
            except Exception:
                pass
            self.show_status("正在检查更新…", "#3b82f6")
        except Exception as e:
            logger.error("触发更新检查失败: %s", e)
            self.show_status("检查更新失败，请稍后重试", "#ef4444")

    def _popup_feedback_dialog(self):
        """弹 FeedbackDialog"""
        from .feedback_dialog import FeedbackDialog
        dialog = FeedbackDialog(parent=self)
        dialog.submitted.connect(self._on_feedback_submitted)
        dialog.exec()

    def _on_feedback_submitted(self, payload: dict):
        """反馈提交成功回调"""
        try:
            from app.core.notification_store import LEVEL_SUCCESS
            self.show_status(
                f"感谢反馈（{payload.get('category','')}）",
                "#10b981" if LEVEL_SUCCESS == LEVEL_SUCCESS else "#3b82f6",
            )
        except Exception:
            self.show_status("感谢反馈", "#10b981")
        # 顺手刷新通知中心徽章
        panel = getattr(self, "_user_center_panel", None)
        if panel is not None:
            try:
                panel.refresh_unread_badge()
            except Exception:
                pass

    def _popup_notification_center(self):
        """在 _notif_btn 正下方弹出通知中心面板"""
        from .notification_center_panel import NotificationCenterPanel
        panel = getattr(self, "_notification_center_panel", None)
        if panel is None:
            from app.core.notification_store import notification_store
            panel = NotificationCenterPanel(
                notification_store=notification_store(),
                theme_manager=ThemeManager.instance(),
                parent=self,
            )
            # 通知中心面板内的"意见反馈/检查更新"按钮：复用 main_window 入口
            panel.feedback_requested.connect(self._on_feedback_clicked)
            panel.check_update_requested.connect(self._on_check_update_clicked)
            # mark_all_read / clear_all 触发后，刷新 user_center_panel 的徽章
            panel.mark_all_read_requested.connect(self._refresh_user_badge)
            panel.clear_all_requested.connect(self._refresh_user_badge)
            panel.delete_requested.connect(self._refresh_user_badge)
            panel.item_clicked.connect(self._refresh_user_badge)
            self._notification_center_panel = panel
        try:
            panel.refresh()
        except Exception as e:
            logger.debug("刷新通知中心面板失败: %s", e)
        panel.popup_below(self._notif_btn)

    def _refresh_user_badge(self, *_args):
        """通知中心变更后刷新 user_center_panel 的未读徽章"""
        panel = getattr(self, "_user_center_panel", None)
        if panel is not None:
            try:
                panel.refresh_unread_badge()
            except Exception as e:
                logger.debug("刷新用户中心徽章失败: %s", e)
    
    def _restore_window_geometry(self):
        """按「记住窗口大小和位置」设置恢复上次退出时的窗口几何信息。

        修复：设置页里的"记住窗口大小和位置"复选框此前只是创建出来摆在
        UI 上，从未和任何真实的保存/恢复逻辑接线——不管勾不勾都没有任何
        效果，窗口每次启动都是写死的 1600x1000。
        """
        try:
            if not self._settings.value("remember_window", True, type=bool):
                return
            geometry = self._settings.value("window_geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except Exception as e:
            logger.debug(f"恢复窗口几何信息失败: {e}")

    def _save_window_geometry(self):
        """退出前按设置保存窗口几何信息（配合 _restore_window_geometry）。"""
        try:
            if self._settings.value("remember_window", True, type=bool):
                self._settings.setValue("window_geometry", self.saveGeometry())
            else:
                self._settings.remove("window_geometry")
        except Exception as e:
            logger.debug(f"保存窗口几何信息失败: {e}")

    def closeEvent(self, event):
        """关闭事件"""
        logger.info("用户关闭主窗口")
        # 先停一切媒体，再存盘/拆控件，避免 Windows WMF 关窗后仍出声
        self._stop_all_media_on_exit()
        logger.info("保存项目状态...")
        self._event_bus.emit(EventType.PROJECT_SAVED, {})
        logger.info("清理资源...")
        
        for module_name, module_info in self._modules.items():
            if module_info.instance:
                try:
                    if hasattr(module_info.instance, 'cleanup'):
                        module_info.instance.cleanup()
                    elif hasattr(module_info.instance, 'on_deactivated'):
                        module_info.instance.on_deactivated()
                    logger.debug(f"模块 {module_name} 已清理")
                except Exception as e:
                    logger.warning(f"清理模块 {module_name} 失败: {e}")
        
        try:
            from modules.lego.async_track_renderer import shutdown_async_track_renderer
            shutdown_async_track_renderer()
            logger.info("异步轨道渲染系统已关闭")
        except ImportError as e:
            logger.debug("异步轨道渲染模块未启用: %s", e)
        except Exception as e:
            logger.debug(f"关闭异步渲染系统: {e}")
        
        logger.info("应用关闭完成")
        for child in self.findChildren(QWidget):
            try:
                child.close()
            except Exception as e:
                logger.debug("子窗口关闭失败: %s", e)
        event.accept()

    # >>> FROZEN:exit-media:main-window BEGIN
    def _stop_all_media_on_exit(self):
        """关闭前强制停止所有 QMediaPlayer，防止幽灵音频。"""
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PyQt6.QtCore import QUrl
        except Exception:
            return
        # 模块级（剪辑主音/BGM）
        for module_info in self._modules.values():
            inst = module_info.instance
            if not inst:
                continue
            try:
                if hasattr(inst, "cleanup"):
                    inst.cleanup()
                elif hasattr(inst, "_shutdown_media"):
                    inst._shutdown_media(release_source=True)
                elif hasattr(inst, "on_deactivated"):
                    inst.on_deactivated()
            except Exception as e:
                logger.debug("模块媒体停止失败: %s", e)
        # 兜底：窗口树内所有播放器
        try:
            for player in self.findChildren(QMediaPlayer):
                try:
                    ao = player.audioOutput()
                    if isinstance(ao, QAudioOutput):
                        ao.setMuted(True)
                        ao.setVolume(0.0)
                except Exception as e:
                    logger.debug("播放器静音失败: %s", e)
                try:
                    player.stop()
                    player.setSource(QUrl())
                except Exception as e:
                    logger.debug("播放器停止失败: %s", e)
        except Exception as e:
            logger.debug("全局 QMediaPlayer 停止失败: %s", e)
    # <<< FROZEN:exit-media:main-window END
