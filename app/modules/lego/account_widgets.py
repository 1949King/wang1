"""
账号运营模块
============

多平台账号管理 + 图形化数据展示
支持: 抖音、快手、视频号、小红书、B站、微博、知乎、头条、百家号、大鱼号、腾讯视频、爱奇艺等
"""

import random
import json
import os as _os
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.account_widgets")

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QLineEdit,
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QDateTimeEdit, QFrame, QScrollArea, QGroupBox,
    QProgressBar, QSlider, QDial, QLCDNumber
)
from PyQt6.QtCore import Qt, QTimer, QDateTime, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFont


class PlatformInfo:
    """平台信息"""
    
    PLATFORMS = {
        "douyin": {"name": "抖音", "icon": "📱", "color": "#000000", "bg_color": "#1a1a1a", "max_accounts": 10},
        "kuaishou": {"name": "快手", "icon": "🎬", "color": "#FF4500", "bg_color": "#2a1a0a", "max_accounts": 10},
        "weixin": {"name": "视频号", "icon": "💬", "color": "#07C160", "bg_color": "#0a2a1a", "max_accounts": 5},
        "xiaohongshu": {"name": "小红书", "icon": "📕", "color": "#FF2442", "bg_color": "#2a0a15", "max_accounts": 6},
        "bilibili": {"name": "B站", "icon": "哔哩", "color": "#00A1D6", "bg_color": "#0a2a35", "max_accounts": 5},
        "weibo": {"name": "微博", "icon": "🐦", "color": "#E6162D", "bg_color": "#2a0a0a", "max_accounts": 5},
        "zhihu": {"name": "知乎", "icon": "🔵", "color": "#0084FF", "bg_color": "#0a1a2a", "max_accounts": 3},
        "toutiao": {"name": "头条", "icon": "📰", "color": "#F85959", "bg_color": "#2a0a0a", "max_accounts": 5},
        "baijiahao": {"name": "百家号", "icon": "📝", "color": "#2932E1", "bg_color": "#0a0a2a", "max_accounts": 3},
        "dayu": {"name": "大鱼号", "icon": "🐟", "color": "#FF6600", "bg_color": "#2a1a0a", "max_accounts": 3},
        "qq_video": {"name": "腾讯视频", "icon": "📺", "color": "#FF9800", "bg_color": "#2a1a0a", "max_accounts": 3},
        "iqiyi": {"name": "爱奇艺", "icon": "🎥", "color": "#00BE06", "bg_color": "#0a2a0a", "max_accounts": 3},
        "youku": {"name": "优酷", "icon": "🎞️", "color": "#1E90FF", "bg_color": "#0a1a2a", "max_accounts": 3},
        "mgtv": {"name": "芒果TV", "icon": "🥭", "color": "#FF6600", "bg_color": "#2a1a0a", "max_accounts": 3},
        "sohu": {"name": "搜狐视频", "icon": "🦊", "color": "#FF6600", "bg_color": "#2a1a0a", "max_accounts": 3},
        "xigua": {"name": "西瓜视频", "icon": "🍉", "color": "#FF4444", "bg_color": "#2a0a0a", "max_accounts": 5},
        "douyin_wx": {"name": "抖音小程序", "icon": "📱", "color": "#333333", "bg_color": "#1a1a1a", "max_accounts": 10},
        "kuaishou_wx": {"name": "快手小程序", "icon": "🎬", "color": "#FF6633", "bg_color": "#2a1a0a", "max_accounts": 10},
        "pinduoduo": {"name": "拼多多", "icon": "🛒", "color": "#E02E24", "bg_color": "#2a0a0a", "max_accounts": 3},
        "taobao": {"name": "淘宝", "icon": "🛍️", "color": "#FF5000", "bg_color": "#2a1a0a", "max_accounts": 3},
        "jd": {"name": "京东", "icon": "📦", "color": "#E2231A", "bg_color": "#2a0a0a", "max_accounts": 3},
        "douban": {"name": "豆瓣", "icon": "🎬", "color": "#00B51D", "bg_color": "#0a2a0a", "max_accounts": 2},
    }


class StatCard(QWidget):
    """统计卡片组件"""
    
    def __init__(self, title: str, value: str, icon: str, color: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._value = value
        self._icon = icon
        self._color = color
        self._setup_ui()
    
    def _setup_ui(self):
        self.setMinimumSize(150, 100)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #1a1a1a;
                border-radius: 12px;
                border: 1px solid #333333;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(8)
        
        header_layout = QHBoxLayout()
        icon_label = QLabel(self._icon)
        icon_label.setStyleSheet("font-size: 18px;")
        header_layout.addWidget(icon_label)
        
        title_label = QLabel(self._title)
        title_label.setStyleSheet("color: #808080; font-size: 12px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        value_label = QLabel(self._value)
        value_label.setObjectName("value_label")
        value_label.setStyleSheet(f"""
            QLabel#value_label {{
                font-size: 24px;
                font-weight: bold;
                color: {self._color};
            }}
        """)
        layout.addWidget(value_label)
    
    def set_value(self, value: str):
        self.findChild(QLabel, "value_label").setText(value)


class MiniChart(QWidget):
    """迷你图表组件"""
    
    def __init__(self, data: List[float], color: str = "#1e6bde", parent=None):
        super().__init__(parent)
        self._data = data or [0, 0, 0, 0, 0, 0, 0]
        self._color = QColor(color)
        self.setMinimumHeight(60)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        if not self._data:
            return
        
        max_val = max(self._data) if max(self._data) > 0 else 1
        bar_width = w / len(self._data)
        
        for i, val in enumerate(self._data):
            bar_height = (val / max_val) * (h - 10)
            x = i * bar_width + 2
            y = h - bar_height - 5
            
            painter.setBrush(QBrush(self._color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(int(x), int(y), int(bar_width - 4), int(bar_height))
    
    def set_data(self, data: List[float]):
        self._data = data
        self.update()


class ProgressRing(QWidget):
    """进度环组件"""
    
    def __init__(self, value: float = 0, color: str = "#1e6bde", parent=None):
        super().__init__(parent)
        self._value = value
        self._color = QColor(color)
        self.setMinimumSize(80, 80)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        side = min(w, h)
        
        painter.translate(w / 2, h / 2)
        painter.scale(side / 100, side / 100)
        
        painter.setPen(QPen(QColor("#333333"), 8))
        painter.drawArc(-40, -40, 80, 80, 0, 360 * 16)
        
        painter.setPen(QPen(self._color, 8))
        painter.drawArc(-40, -40, 80, 80, -90 * 16, int(self._value * 360 * 16 / 100))
    
    def set_value(self, value: float):
        self._value = value
        self.update()


class AccountCard(QWidget):
    """账号卡片组件"""
    
    clicked = pyqtSignal(str)
    
    def __init__(self, platform_id: str, account_name: str, fans: int, status: str, parent=None):
        super().__init__(parent)
        self._platform_id = platform_id
        self._account_name = account_name
        self._fans = fans
        self._status = status
        self._setup_ui()
    
    def _setup_ui(self):
        pinfo = PlatformInfo.PLATFORMS.get(self._platform_id, {})
        platform_name = pinfo.get("name", self._platform_id)
        icon = pinfo.get("icon", "📱")
        color = pinfo.get("color", "#808080")
        
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #1a1a1a;
                border-radius: 10px;
                border: 1px solid #333333;
            }}
            QWidget:hover {{
                border-color: {color};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        
        header_layout = QHBoxLayout()
        platform_label = QLabel(f"{icon} {platform_name}")
        platform_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
        header_layout.addWidget(platform_label)
        
        status_label = QLabel("●" if self._status == "正常" else "○")
        status_label.setStyleSheet(f"color: {'#22c55e' if self._status == '正常' else '#ef4444'}; font-size: 10px;")
        header_layout.addWidget(status_label)
        
        layout.addLayout(header_layout)
        
        name_label = QLabel(f"@{self._account_name}")
        name_label.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")
        layout.addWidget(name_label)
        
        fans_label = QLabel(f"粉丝: {self._format_number(self._fans)}")
        fans_label.setStyleSheet("color: #808080; font-size: 12px;")
        layout.addWidget(fans_label)
        
        stats_layout = QHBoxLayout()
        
        for label, value in [("今日发布", str(random.randint(0, 5))), ("点赞", self._format_number(random.randint(100, 10000)))]:
            stat_widget = QWidget()
            stat_layout = QVBoxLayout(stat_widget)
            stat_layout.setContentsMargins(0, 0, 0, 0)
            stat_layout.setSpacing(2)
            
            v = QLabel(value)
            v.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
            stat_layout.addWidget(v)
            
            l = QLabel(label)
            l.setStyleSheet("color: #666666; font-size: 10px;")
            stat_layout.addWidget(l)
            
            stats_layout.addWidget(stat_widget)
        
        layout.addLayout(stats_layout)
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def _format_number(self, num: int) -> str:
        if num >= 100000000:
            return f"{num/100000000:.1f}亿"
        elif num >= 10000:
            return f"{num/10000:.1f}万"
        return str(num)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._platform_id)
        super().mousePressEvent(event)


class BarChart(QWidget):
    """水平条形图组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[Dict] = []
        self.setMinimumHeight(200)
    
    def set_items(self, items: List[Dict]):
        self._items = items
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if not self._items:
            return
        
        h = self.height()
        item_height = min(40, h // len(self._items) - 5)
        
        max_val = max(item.get("value", 0) for item in self._items)
        if max_val == 0:
            max_val = 1
        
        for i, item in enumerate(self._items):
            y = i * (item_height + 5) + 5
            
            name = item.get("name", "")
            value = item.get("value", 0)
            color = QColor(item.get("color", "#1e6bde"))
            
            painter.setPen(QColor("#808080"))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(5, y + item_height // 2 + 5, name)
            
            bar_width = int((value / max_val) * (self.width() - 120))
            if bar_width > 0:
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(100, y, bar_width, item_height - 5)
            
            painter.setPen(QColor("#ffffff"))
            painter.drawText(100 + bar_width + 10, y + item_height // 2 + 5, str(value))


def _load_accounts_from_file() -> Optional[List[tuple]]:
    """从 data/bound_accounts.json 加载账号列表，失败返回 None"""
    try:
        workspace = Path(__file__).parent.parent.parent.parent
        af = workspace / "data" / "bound_accounts.json"
        if not af.exists():
            return None
        with open(af, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 转换为 (platform, name, fans_num, status) 元组列表
        result = []
        for platform, accounts in data.items():
            for acc in accounts:
                name = acc.get("name", "@未命名")
                fans_str = acc.get("fans", "0")
                status = acc.get("status", "正常")
                # 粉丝数转换: "12.5万粉" → 125000
                fans_num = 0
                try:
                    s = fans_str.replace("万粉", "").replace("粉", "").replace(",", "")
                    if "万" in fans_str:
                        fans_num = int(float(s.replace("万", "")) * 10000)
                    elif "k" in fans_str.lower():
                        fans_num = int(float(s.lower().replace("k", "")) * 1000)
                    else:
                        fans_num = int(float(s))
                except (ValueError, TypeError):
                    fans_num = 0
                result.append((platform, name, fans_num, status))
        logger.info(f"从文件加载 {len(result)} 个账号")
        return result if result else None
    except Exception as e:
        logger.warning(f"加载账号文件失败: {e}")
        return None


def create_enhanced_accounts_tab() -> QWidget:
    """创建增强版账号管理标签页"""
    def _add_account():
        """添加账号"""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QComboBox, QLineEdit, QMessageBox
        
        dialog = QDialog()
        dialog.setWindowTitle("添加账号")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        form = QFormLayout()
        
        platform_combo = QComboBox()
        platform_combo.addItems(["抖音", "快手", "视频号", "小红书", "B站", "微博", "知乎", "头条", "百家号", "大鱼号", "腾讯视频", "爱奇艺"])
        form.addRow("平台:", platform_combo)
        
        account_name = QLineEdit()
        account_name.setPlaceholderText("输入账号名称")
        form.addRow("账号名称:", account_name)
        
        account_id = QLineEdit()
        account_id.setPlaceholderText("输入账号ID或用户名")
        form.addRow("账号ID:", account_id)
        
        layout.addLayout(form)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            platform = platform_combo.currentText()
            name = account_name.text()
            acc_id = account_id.text()
            
            if name and acc_id:
                try:
                    from .openclow_engine import get_openclow_engine
                    engine = get_openclow_engine()
                    engine.add_account(platform, acc_id, {"name": name, "status": "正常", "fans": 0})
                    QMessageBox.information(None, "成功", f"账号 {name} 添加成功")
                except Exception as e:
                    QMessageBox.warning(None, "错误", f"添加失败: {e}")
            else:
                QMessageBox.warning(None, "错误", "请填写完整的账号信息")
    
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(20)
    
    header_layout = QHBoxLayout()
    title = QLabel("📱 账号管理")
    title.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
    header_layout.addWidget(title)
    header_layout.addStretch()
    
    refresh_btn = QPushButton("🔄 同步")
    refresh_btn.setStyleSheet("""
        QPushButton {
            background-color: #22c55e;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
        }
        QPushButton:hover { background-color: #16a34a; }
    """)
    header_layout.addWidget(refresh_btn)
    
    add_btn = QPushButton("+ 添加账号")
    add_btn.setStyleSheet("""
        QPushButton {
            background-color: #1e6bde;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
        }
        QPushButton:hover { background-color: #1557b0; }
    """)
    add_btn.clicked.connect(lambda: _add_account())
    header_layout.addWidget(add_btn)
    
    layout.addLayout(header_layout)
    
    stats_layout = QHBoxLayout()
    stats_layout.setSpacing(15)
    
    # 从实际数据计算统计摘要
    active_count = sum(1 for _, _, _, status in sample_accounts if status == "正常")
    total_fans = sum(fans for _, _, fans, _ in sample_accounts)
    if total_fans >= 10000:
        fans_display = f"{total_fans // 10000}万" if total_fans % 10000 == 0 else f"{total_fans / 10000:.1f}万"
    else:
        fans_display = str(total_fans)
    
    stat_cards = [
        ("总账号", str(len(sample_accounts)), "📊", "#1e6bde"),
        ("活跃账号", str(active_count), "✅", "#22c55e"),
        ("总平台", str(len(set(p for p, *_ in sample_accounts))), "📤", "#f59e0b"),
        ("总粉丝", fans_display, "👥", "#ec4899"),
    ]
    
    for title, value, icon, color in stat_cards:
        card = StatCard(title, value, icon, color)
        stats_layout.addWidget(card)
    
    layout.addLayout(stats_layout)
    
    filter_layout = QHBoxLayout()
    filter_layout.addWidget(QLabel("平台:"))
    
    platform_combo = QComboBox()
    platform_combo.addItem("全部平台", "all")
    for pid, pinfo in PlatformInfo.PLATFORMS.items():
        platform_combo.addItem(f"{pinfo['icon']} {pinfo['name']}", pid)
    platform_combo.setStyleSheet("""
        QComboBox {
            background-color: #2a2a2a;
            color: white;
            border: 1px solid #333333;
            border-radius: 4px;
            padding: 6px 12px;
        }
    """)
    filter_layout.addWidget(platform_combo)
    
    filter_layout.addWidget(QLabel("状态:"))
    status_combo = QComboBox()
    status_combo.addItems(["全部", "正常", "异常", "未激活"])
    status_combo.setStyleSheet("""
        QComboBox {
            background-color: #2a2a2a;
            color: white;
            border: 1px solid #333333;
            border-radius: 4px;
            padding: 6px 12px;
        }
    """)
    filter_layout.addWidget(status_combo)
    filter_layout.addStretch()
    
    layout.addLayout(filter_layout)
    
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("border: none;")
    
    accounts_widget = QWidget()
    accounts_layout = QGridLayout(accounts_widget)
    accounts_layout.setSpacing(15)
    
    # 优先从 bound_accounts.json 加载，失败时使用示例数据
    sample_accounts = _load_accounts_from_file() or [
        ("douyin", "短剧剪辑师", 125000, "正常"),
        ("douyin", "短剧达人号", 89000, "正常"),
        ("douyin", "影视剪辑王", 256000, "正常"),
        ("kuaishou", "快手短剧", 67000, "正常"),
        ("kuaishou", "快手影视号", 45000, "正常"),
        ("weixin", "视频号主", 45000, "正常"),
        ("weixin", "微信短剧", 32000, "正常"),
        ("xiaohongshu", "小红书博主", 230000, "正常"),
        ("xiaohongshu", "短剧推荐官", 156000, "正常"),
        ("bilibili", "B站UP主", 156000, "正常"),
        ("bilibili", "影视解说", 98000, "正常"),
        ("weibo", "微博大V", 89000, "正常"),
        ("weibo", "短剧博主", 56000, "正常"),
        ("zhihu", "知乎答者", 34000, "正常"),
        ("toutiao", "头条作者", 56000, "正常"),
        ("toutiao", "头条影视", 42000, "正常"),
        ("baijiahao", "百家号主", 12000, "正常"),
        ("dayu", "大鱼号主", 8000, "异常"),
        ("qq_video", "腾讯视频", 45000, "正常"),
        ("iqiyi", "爱奇艺号", 38000, "正常"),
        ("youku", "优酷创作者", 28000, "正常"),
        ("mgtv", "芒果创作者", 22000, "正常"),
        ("sohu", "搜狐视频", 18000, "正常"),
        ("xigua", "西瓜视频", 67000, "正常"),
        ("douyin_wx", "抖音小程序", 89000, "正常"),
        ("kuaishou_wx", "快手小程序", 76000, "正常"),
        ("pinduoduo", "拼多多店铺", 45000, "正常"),
        ("taobao", "淘宝店铺", 56000, "正常"),
        ("jd", "京东店铺", 38000, "正常"),
        ("douban", "豆瓣影评", 12000, "正常"),
    ]
    
    for i, (platform, name, fans, status) in enumerate(sample_accounts):
        card = AccountCard(platform, name, fans, status)
        accounts_layout.addWidget(card, i // 3, i % 3)
    
    scroll.setWidget(accounts_widget)
    layout.addWidget(scroll, 1)
    
    return tab


def create_enhanced_dashboard_tab() -> QWidget:
    """创建增强版数据看板标签页"""
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(20)
    
    header_layout = QHBoxLayout()
    title = QLabel("📊 数据看板")
    title.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
    header_layout.addWidget(title)
    header_layout.addStretch()
    
    period_combo = QComboBox()
    period_combo.addItems(["今日", "本周", "本月", "本年"])
    period_combo.setStyleSheet("""
        QComboBox {
            background-color: #2a2a2a;
            color: white;
            border: 1px solid #333333;
            border-radius: 4px;
            padding: 6px 12px;
        }
    """)
    header_layout.addWidget(period_combo)
    
    layout.addLayout(header_layout)
    
    overview_layout = QHBoxLayout()
    overview_layout.setSpacing(15)
    
    dashboard_stats = [
        ("总播放量", "12.5亿", "📈", "#1e6bde", [1200000, 1500000, 1800000, 2100000, 2400000, 2800000, 3200000]),
        ("总点赞", "856.3万", "❤️", "#ec4899", [85000, 87000, 89000, 92000, 95000, 98000, 102000]),
        ("总评论", "45.2万", "💬", "#f59e0b", [4500, 5200, 5800, 6400, 7000, 7500, 8200]),
        ("总分享", "23.8万", "🔄", "#22c55e", [2300, 2500, 2800, 3100, 3400, 3700, 4000]),
        ("新增粉丝", "+5.6万", "👥", "#8b5cf6", [5600, 6200, 6800, 7200, 7800, 8400, 9200]),
        ("预估收益", "¥8.9万", "💰", "#f97316", [8900, 9200, 9800, 10200, 10800, 11500, 12300]),
    ]
    
    for stat_data in dashboard_stats:
        title, value, icon, color, chart_data = stat_data
        
        stat_widget = QWidget()
        stat_widget.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border-radius: 12px;
                border: 1px solid #333333;
            }
        """)
        
        stat_layout = QVBoxLayout(stat_widget)
        stat_layout.setContentsMargins(15, 12, 15, 12)
        stat_layout.setSpacing(8)
        
        header_layout = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 18px;")
        header_layout.addWidget(icon_label)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #808080; font-size: 12px;")
        header_layout.addWidget(title_label)
        
        stat_layout.addLayout(header_layout)
        
        value_label = QLabel(value)
        value_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color};")
        stat_layout.addWidget(value_label)
        
        chart = MiniChart(chart_data, color)
        stat_layout.addWidget(chart)
        
        overview_layout.addWidget(stat_widget)
    
    layout.addLayout(overview_layout)
    
    charts_layout = QHBoxLayout()
    charts_layout.setSpacing(20)
    
    platform_chart = QWidget()
    platform_chart.setStyleSheet("""
        QWidget {
            background-color: #1a1a1a;
            border-radius: 12px;
            border: 1px solid #333333;
        }
    """)
    platform_layout = QVBoxLayout(platform_chart)
    platform_layout.setContentsMargins(20, 20, 20, 20)
    platform_layout.setSpacing(15)
    
    chart_title = QLabel("📊 平台数据分布")
    chart_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
    platform_layout.addWidget(chart_title)
    
    platform_data = [
        {"name": "抖音", "value": 45600, "color": "#000000"},
        {"name": "小红书", "value": 38200, "color": "#FF2442"},
        {"name": "B站", "value": 28400, "color": "#00A1D6"},
        {"name": "快手", "value": 19600, "color": "#FF4500"},
        {"name": "微博", "value": 12800, "color": "#E6162D"},
        {"name": "其他", "value": 8500, "color": "#808080"},
    ]
    
    bar_chart = BarChart()
    bar_chart.set_items(platform_data)
    platform_layout.addWidget(bar_chart, 1)
    
    charts_layout.addWidget(platform_chart, 1)
    
    trend_chart = QWidget()
    trend_chart.setStyleSheet("""
        QWidget {
            background-color: #1a1a1a;
            border-radius: 12px;
            border: 1px solid #333333;
        }
    """)
    trend_layout = QVBoxLayout(trend_chart)
    trend_layout.setContentsMargins(20, 20, 20, 20)
    trend_layout.setSpacing(15)
    
    trend_title = QLabel("📈 7日趋势")
    trend_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
    trend_layout.addWidget(trend_title)
    
    trend_widget = QWidget()
    trend_widget.setMinimumHeight(150)
    trend_widget.setStyleSheet("background-color: #2a2a2a; border-radius: 8px;")
    trend_layout.addWidget(trend_widget, 1)
    
    days_layout = QHBoxLayout(trend_widget)
    days_layout.setContentsMargins(10, 10, 10, 10)
    days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for day in days:
        day_label = QLabel(day)
        day_label.setStyleSheet("color: #808080; font-size: 11px;")
        day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        days_layout.addWidget(day_label)
    
    charts_layout.addWidget(trend_chart, 1)
    
    layout.addLayout(charts_layout, 1)
    
    return tab
