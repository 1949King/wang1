"""
短剧筛选可视化界面：封面卡片墙 + 右侧详情预览。
"""
# >>> FROZEN:drama-finder-ui:module BEGIN

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QLinearGradient, QBrush, QPen, QPixmap, QPalette,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QComboBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QScrollArea, QGridLayout, QSplitter, QStackedWidget,
    QSizePolicy,
)

logger = logging.getLogger("AI短剧编辑器.drama_finder_plugin.ui")

_PLATFORM_COLORS = {
    "douyin": ("#111827", "#ec4899"),
    "kuaishou": ("#1a1008", "#f97316"),
    "tencent": ("#0c1929", "#3b82f6"),
    "iqiyi": ("#0a1f14", "#22c55e"),
    "youku": ("#1a1005", "#eab308"),
    "bilibili": ("#1a0a14", "#fb7299"),
    "xiaohongshu": ("#1a0808", "#ef4444"),
    "mgtv": ("#1a1408", "#f59e0b"),
    "xigua": ("#081a10", "#84cc16"),
}


def _fmt_views(views: int) -> str:
    try:
        views = int(views)
    except Exception:
        return str(views)
    if views >= 100_000_000:
        return f"{views / 100_000_000:.1f}亿"
    if views >= 10_000:
        return f"{views // 10_000}万"
    return str(views)


def _fmt_comm(comm: float, *, yuan_wan: bool = False) -> str:
    try:
        comm = float(comm)
    except Exception:
        return str(comm)
    if yuan_wan and comm >= 10000:
        return f"¥{comm / 10000:.1f}万"
    if yuan_wan:
        return f"¥{int(comm)}"
    return f"¥{int(comm)}" if comm == int(comm) else f"¥{comm:.1f}"


def make_cover_pixmap(title: str, platform: str, w: int = 168, h: int = 236) -> QPixmap:
    """无真实封面时生成渐变海报预览。"""
    c0, c1 = _PLATFORM_COLORS.get(platform, ("#1e293b", "#6366f1"))
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor(c0))
    grad.setColorAt(1.0, QColor(c1))
    p.fillRect(0, 0, w, h, QBrush(grad))
    p.setPen(QPen(QColor(255, 255, 255, 28), 1))
    p.drawRoundedRect(1, 1, w - 2, h - 2, 10, 10)

    # 大号首字
    head = (title[:1] or "剧").upper()
    p.setPen(QColor(255, 255, 255, 230))
    f1 = QFont("Microsoft YaHei UI", 36, QFont.Weight.Bold)
    p.setFont(f1)
    p.drawText(0, int(h * 0.22), w, 60, Qt.AlignmentFlag.AlignHCenter, head)

    # 标题两行
    f2 = QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold)
    p.setFont(f2)
    p.setPen(QColor("#f8fafc"))
    t = title if len(title) <= 16 else title[:15] + "…"
    p.drawText(10, int(h * 0.55), w - 20, 56,
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, t)

    p.setPen(QColor(255, 255, 255, 160))
    f3 = QFont("Microsoft YaHei UI", 8)
    p.setFont(f3)
    p.drawText(8, h - 28, w - 16, 18, Qt.AlignmentFlag.AlignHCenter, "预览封面")
    p.end()
    return pm


class DramaCard(QFrame):
    """可点击封面卡片。"""

    def __init__(self, item: dict[str, Any], on_click, parent=None):
        super().__init__(parent)
        self.item = item
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(178, 290)
        self.setStyleSheet(
            "DramaCard{background:#161616;border:1px solid #262626;border-radius:10px;}"
            "DramaCard:hover{border-color:#3b82f6;background:#1a1f2a;}"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)

        cover = QLabel()
        cover.setFixedSize(162, 228)
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setPixmap(make_cover_pixmap(item["title"], item["platform"], 162, 228))
        cover.setStyleSheet("border-radius:8px;")
        lo.addWidget(cover)

        title = QLabel(item["title"])
        title.setStyleSheet("color:#fafafa;font-size:12px;font-weight:600;")
        title.setWordWrap(True)
        title.setMaximumHeight(34)
        lo.addWidget(title)

        meta = QLabel(
            f"{item['platform_label']} · 🔥{item['heat']} · {_fmt_views(item['views'])}"
        )
        meta.setStyleSheet("color:#d4d4d8;font-size:11px;")
        lo.addWidget(meta)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(self.item)
        super().mousePressEvent(event)


class DramaFinderWidget(QWidget):
    """短剧筛选可视化：卡片墙 + 右侧预览 + 可选列表。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        from app.plugins.drama_finder_plugin.main import DRAMAS, PLATFORM_MAP
        self._dramas = DRAMAS
        self._platform_map = PLATFORM_MAP
        self._items: list[dict[str, Any]] = []
        self._selected: dict[str, Any] | None = None
        self._view_mode = "cards"  # cards | table
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(300000)
        QTimer.singleShot(200, self._refresh)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.setStyleSheet("DramaFinderWidget{background:#0d0d0d;}")
        self.setMinimumSize(860, 560)

        # 标题
        head = QHBoxLayout()
        title = QLabel("🎭 短剧筛选")
        title.setStyleSheet("color:#fff;font-size:18px;font-weight:700;")
        head.addWidget(title)
        sub = QLabel("封面卡片浏览 · 右侧详情预览")
        sub.setStyleSheet("color:#a1a1aa;font-size:12px;margin-left:8px;")
        head.addWidget(sub)
        head.addStretch()
        self._btn_cards = QPushButton("卡片")
        self._btn_table = QPushButton("列表")
        for b, mode in ((self._btn_cards, "cards"), (self._btn_table, "table")):
            b.setCheckable(True)
            b.setStyleSheet(
                "QPushButton{background:#1a1a1a;color:#aaa;border:1px solid #333;"
                "border-radius:6px;padding:5px 12px;font-size:11px;}"
                "QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}"
            )
            b.clicked.connect(lambda _=False, m=mode: self._set_view_mode(m))
            head.addWidget(b)
        self._btn_cards.setChecked(True)
        layout.addLayout(head)

        # 筛选栏
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._platform_combo = QComboBox()
        self._platform_combo.addItem("全部平台", "all")
        for pid, name in self._platform_map.items():
            self._platform_combo.addItem(name, pid)
        self._type_combo = QComboBox()
        self._type_combo.addItems(["全部", "短剧", "漫剧", "电影", "电视剧"])
        self._cat_combo = QComboBox()
        self._cat_combo.addItem("全部", "all")
        cats = [
            "重生", "霸总", "医术", "穿越", "复仇", "科幻", "甜宠", "神豪",
            "逆袭", "修仙", "军旅", "校园", "武侠", "玄幻", "都市", "美食",
            "推理", "喜剧", "治愈", "古装", "悬疑", "热血", "萌宠", "后宫",
            "机甲", "系统流", "青春", "家庭", "动作", "惊悚"
        ]
        self._cat_combo.addItems(cats)
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["🔥热度", "👁播放", "💰佣金", "⭐评分", "🆕最新"])
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索短剧名称...")
        # 下拉弹出层在 Windows 上默认白底；若不设 QAbstractItemView 会白底浅字
        combo_ss = """
            QComboBox, QLineEdit {
                background: #1c1c1c;
                color: #f3f4f6;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                min-height: 22px;
            }
            QComboBox:hover, QLineEdit:hover { border-color: #60a5fa; }
            QComboBox::drop-down {
                border: none;
                width: 22px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #d4d4d8;
                width: 0; height: 0;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background: #1c1c1c;
                color: #f3f4f6;
                border: 1px solid #3f3f46;
                selection-background-color: #1e6bde;
                selection-color: #ffffff;
                outline: 0;
                padding: 4px;
            }
            QComboBox QAbstractItemView::item {
                color: #f3f4f6;
                background: #1c1c1c;
                min-height: 28px;
                padding: 4px 10px;
            }
            QComboBox QAbstractItemView::item:hover {
                background: #27272a;
                color: #ffffff;
            }
            QComboBox QAbstractItemView::item:selected {
                background: #1e6bde;
                color: #ffffff;
            }
            QLineEdit::placeholder { color: #a1a1aa; }
        """
        for w in (self._platform_combo, self._type_combo, self._cat_combo,
                  self._sort_combo, self._search_input):
            w.setStyleSheet(combo_ss)
            if isinstance(w, QComboBox):
                # 强制弹出列表用深色调色板，避免系统主题盖掉 QSS
                view = w.view()
                view.setStyleSheet(
                    "QAbstractItemView{background:#1c1c1c;color:#f3f4f6;"
                    "selection-background-color:#1e6bde;selection-color:#fff;}"
                    "QAbstractItemView::item{color:#f3f4f6;min-height:28px;padding:4px 10px;}"
                )
                pal = view.palette()
                pal.setColor(QPalette.ColorRole.Base, QColor("#1c1c1c"))
                pal.setColor(QPalette.ColorRole.Text, QColor("#f3f4f6"))
                pal.setColor(QPalette.ColorRole.Highlight, QColor("#1e6bde"))
                pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
                view.setPalette(pal)
                w.setPalette(pal)
        self._platform_combo.currentIndexChanged.connect(self._refresh)
        self._type_combo.currentIndexChanged.connect(self._refresh)
        self._cat_combo.currentIndexChanged.connect(self._refresh)
        self._sort_combo.currentIndexChanged.connect(self._refresh)
        self._search_input.returnPressed.connect(self._refresh)
        top_row.addWidget(self._platform_combo)
        top_row.addWidget(self._type_combo)
        top_row.addWidget(self._cat_combo)
        top_row.addWidget(self._sort_combo)
        top_row.addWidget(self._search_input, 1)
        tip = QLabel("5分钟自动刷新")
        tip.setStyleSheet("color:#a1a1aa;font-size:11px;")
        top_row.addWidget(tip)
        layout.addLayout(top_row)

        status_row = QHBoxLayout()
        self._data_status_label = QLabel("")
        self._data_status_label.setVisible(False)
        status_row.addWidget(self._data_status_label)
        status_row.addStretch()
        help_btn = QPushButton("❓ 数据源帮助")
        help_btn.setStyleSheet(
            "QPushButton{background:#1a1a1a;color:#aaa;border:1px solid #2a2a2a;"
            "border-radius:4px;padding:4px 10px;font-size:10px;}"
        )
        help_btn.clicked.connect(self._show_data_source_help)
        status_row.addWidget(help_btn)
        layout.addLayout(status_row)

        # 主体：卡片/列表 + 预览
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self._stack = QStackedWidget()
        # 卡片
        self._cards_host = QWidget()
        self._cards_grid = QGridLayout(self._cards_host)
        self._cards_grid.setContentsMargins(4, 4, 4, 4)
        self._cards_grid.setSpacing(12)
        self._cards_grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setStyleSheet(
            "QScrollArea{background:#0d0d0d;border:1px solid #1e1e1e;border-radius:8px;}"
        )
        cards_scroll.setWidget(self._cards_host)
        self._stack.addWidget(cards_scroll)

        # 列表
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["剧名", "平台", "分类", "集数", "播放量", "佣金", "热度", "操作"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 8):
            self._table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
        for c, w in enumerate([80, 60, 50, 90, 70, 60, 100], start=1):
            self._table.setColumnWidth(c, w)
        self._table.setStyleSheet(
            "QTableWidget{background:#0a0a0a;border:1px solid #1a1a1a;border-radius:8px;color:#e5e7eb;font-size:12px;}"
            "QHeaderView::section{background:#1a1a1a;padding:8px;border:none;color:#d4d4d8;font-size:11px;font-weight:600;}"
            "QTableWidget::item{color:#e5e7eb;padding:6px;}"
            "QTableWidget::item:selected{background:#1e3a5f;color:#ffffff;}"
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_table_select)
        self._stack.addWidget(self._table)
        splitter.addWidget(self._stack)

        # 右侧预览
        preview = QFrame()
        preview.setObjectName("dramaPreview")
        preview.setMinimumWidth(260)
        preview.setMaximumWidth(320)
        preview.setStyleSheet(
            "#dramaPreview{background:#121212;border:1px solid #242424;border-radius:12px;}"
        )
        plo = QVBoxLayout(preview)
        plo.setContentsMargins(14, 14, 14, 14)
        plo.setSpacing(10)
        ph = QLabel("详情预览")
        ph.setStyleSheet("color:#d4d4d8;font-size:12px;font-weight:600;")
        plo.addWidget(ph)
        self._preview_cover = QLabel()
        self._preview_cover.setFixedSize(220, 310)
        self._preview_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_cover.setStyleSheet(
            "background:#0a0a0a;border-radius:10px;border:1px solid #222;"
        )
        self._preview_cover.setPixmap(make_cover_pixmap("选择短剧", "douyin", 220, 310))
        plo.addWidget(self._preview_cover, 0, Qt.AlignmentFlag.AlignHCenter)

        self._preview_title = QLabel("点击左侧卡片查看预览")
        self._preview_title.setWordWrap(True)
        self._preview_title.setStyleSheet("color:#fafafa;font-size:16px;font-weight:700;")
        plo.addWidget(self._preview_title)

        self._preview_meta = QLabel("平台 / 分类 / 集数")
        self._preview_meta.setWordWrap(True)
        self._preview_meta.setStyleSheet("color:#d4d4d8;font-size:12px;")
        plo.addWidget(self._preview_meta)

        self._preview_stats = QLabel("")
        self._preview_stats.setWordWrap(True)
        self._preview_stats.setStyleSheet("color:#f4f4f5;font-size:13px;line-height:1.5;")
        plo.addWidget(self._preview_stats)

        self._preview_select = QPushButton("✓ 选择此剧")
        self._preview_select.setEnabled(False)
        self._preview_select.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:8px;"
            "padding:10px;font-size:12px;font-weight:600;}"
            "QPushButton:disabled{background:#333;color:#777;}"
            "QPushButton:hover:!disabled{background:#1557b0;}"
        )
        self._preview_select.clicked.connect(self._confirm_select)
        plo.addWidget(self._preview_select)
        plo.addStretch()
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([720, 280])
        layout.addWidget(splitter, 1)

        bot = QHBoxLayout()
        self._info_label = QLabel("加载中…")
        self._info_label.setStyleSheet("color:#a1a1aa;font-size:11px;")
        bot.addWidget(self._info_label)
        bot.addStretch()
        refresh_btn = QPushButton("🔄 立即刷新")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;"
            "border-radius:4px;padding:5px 12px;font-size:10px;}"
        )
        refresh_btn.clicked.connect(self._refresh)
        bot.addWidget(refresh_btn)
        layout.addLayout(bot)

    def _set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        self._btn_cards.setChecked(mode == "cards")
        self._btn_table.setChecked(mode == "table")
        self._stack.setCurrentIndex(0 if mode == "cards" else 1)
        self._render_items(self._items)

    def _clear_cards(self) -> None:
        while self._cards_grid.count():
            item = self._cards_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_items(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        # 卡片
        self._clear_cards()
        cols = max(2, min(5, (self.width() - 320) // 190 or 3))
        for i, it in enumerate(items):
            card = DramaCard(it, self._update_preview, self._cards_host)
            self._cards_grid.addWidget(card, i // cols, i % cols)
        if not items:
            empty = QLabel("暂无匹配短剧，请调整筛选条件")
            empty.setStyleSheet("color:#666;font-size:13px;padding:40px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cards_grid.addWidget(empty, 0, 0)

        # 表格
        self._table.setRowCount(0)
        self._table.setRowCount(len(items))
        for i, it in enumerate(items):
            vals = [
                it["title"], it["platform_label"], it["category"], str(it["episodes"]),
                _fmt_views(it["views"]), it["commission_text"], str(it["heat"]),
            ]
            for j, txt in enumerate(vals):
                cell = QTableWidgetItem(txt)
                if j == 0:
                    cell.setForeground(QColor("#60a5fa"))
                self._table.setItem(i, j, cell)
            btn = QPushButton("预览")
            btn.setStyleSheet(
                "QPushButton{background:#1e6bde;color:#fff;border:none;"
                "border-radius:4px;padding:3px 12px;font-size:10px;}"
            )
            btn.clicked.connect(lambda _=False, d=it: self._update_preview(d))
            self._table.setCellWidget(i, 7, btn)

        if items:
            self._update_preview(items[0])
        else:
            self._selected = None
            self._preview_title.setText("暂无数据")
            self._preview_select.setEnabled(False)

    def _update_preview(self, item: dict[str, Any]) -> None:
        self._selected = item
        self._preview_cover.setPixmap(
            make_cover_pixmap(item["title"], item["platform"], 220, 310)
        )
        self._preview_title.setText(item["title"])
        self._preview_meta.setText(
            f"{item['platform_label']}  ·  {item['category']}  ·  "
            f"{item['episodes']}集  ·  {item.get('sub_type', '短剧')}"
        )
        self._preview_stats.setText(
            f"🔥 热度 {item['heat']}\n"
            f"👁 播放 {_fmt_views(item['views'])}\n"
            f"💰 佣金 {item['commission_text']}\n"
            f"📦 来源 {item.get('source', '—')}"
        )
        self._preview_select.setEnabled(True)

    def _on_table_select(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if 0 <= idx < len(self._items):
            self._update_preview(self._items[idx])

    def _confirm_select(self) -> None:
        if not self._selected:
            return
        QMessageBox.information(self, "选择短剧", f"已选择: {self._selected['title']}")

    def _refresh(self) -> None:
        keyword = self._search_input.text().strip().lower()
        platform = self._platform_combo.currentData()
        dtype = self._type_combo.currentText()
        cat_idx = self._cat_combo.currentIndex()
        category = None if cat_idx == 0 else self._cat_combo.currentText()
        sort_text = self._sort_combo.currentText()
        sort_map = {
            "🔥热度": "heat", "👁播放": "views", "💰佣金": "commission",
            "⭐评分": "rating", "🆕最新": "freshness"
        }
        type_map = {
            "全部": "all", "短剧": "drama", "漫剧": "comic",
            "电影": "movie", "电视剧": "tv"
        }
        self._populate_from_static(keyword, platform, dtype, category, sort_text)
        self._fetch_real_data_async(
            type_map.get(dtype, "all"), platform, category,
            sort_map.get(sort_text, "score"), keyword, sort_text
        )

    def _fetch_real_data_async(self, content_type, platform, category, crawler_sort,
                               keyword, sort_text) -> None:
        try:
            from app.plugins.drama_finder_plugin.crawler import DramaCrawler
            crawler = DramaCrawler()

            def on_data_fetched(dramas):
                if dramas:
                    self._populate_from_crawler(dramas)
                self._refresh_data_status()

            def on_error(err_msg):
                logger.debug("后台爬取失败, 保留静态数据: %s", err_msg)
                self._refresh_data_status()

            crawler.fetch_dramas_async(
                content_type=content_type,
                platform=platform,
                category=category if category else "all",
                sort_by=crawler_sort,
                keyword=keyword,
                page=1,
                page_size=80,
                callback=on_data_fetched,
                error_callback=on_error,
            )
        except Exception as e:
            logger.debug("异步爬取启动失败: %s", e)
            self._refresh_data_status()

    def _populate_from_crawler(self, dramas) -> None:
        label, color = "数据", "#4caf50"
        try:
            from app.plugins.drama_finder_plugin.crawler import DramaCrawler
            fresh = DramaCrawler().get_data_freshness()
            if fresh.get("has_real"):
                label, color = "真实爬取", "#4caf50"
            elif fresh.get("has_static"):
                label, color = "静态缓存", "#ffb74d"
            elif fresh.get("is_pure_fallback"):
                label, color = "模拟数据", "#ff5252"
            else:
                label, color = "混合数据", "#ffb74d"
        except Exception as e:
            logger.debug(f"获取数据新鲜度状态失败: {e}")

        items = []
        for d in dramas:
            plat = getattr(d, "platform", "") or ""
            views = getattr(d, "views", 0) or 0
            try:
                views = int(views)
            except Exception:
                views = 0
            comm = getattr(d, "commission", 0) or 0
            try:
                comm = float(comm)
            except Exception:
                comm = 0.0
            cover = getattr(d, "cover_url", "") or ""
            items.append({
                "title": getattr(d, "title", "") or "",
                "platform": plat,
                "platform_label": self._platform_map.get(plat, plat),
                "category": getattr(d, "category", "") or "",
                "episodes": getattr(d, "episodes", 0) or 0,
                "views": views,
                "commission": comm,
                "commission_text": _fmt_comm(comm, yuan_wan=True),
                "heat": getattr(d, "heat", 0) or 0,
                "sub_type": getattr(d, "content_type", "") or "短剧",
                "cover_url": cover,
                "source": label,
            })
        self._info_label.setText(
            f"共 {len(items)} 条 ({label}) | 更新于 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._info_label.setStyleSheet(f"color:{color};font-size:12px;font-weight:600;")
        self._render_items(items)

    def _populate_from_static(self, keyword, platform, dtype, category, sort_text) -> None:
        filtered = []
        for d in self._dramas:
            name, plat, cat, eps, views, comm, heat, sub_type, rank = d
            if keyword and keyword not in name.lower():
                continue
            if platform != "all" and plat != platform:
                continue
            if dtype != "全部" and sub_type != dtype:
                continue
            if category and cat != category:
                continue
            rv = max(1000, views + random.randint(-views // 6, views // 6))
            rh = min(99, max(60, heat + random.randint(-4, 4)))
            rc = max(1, comm + random.randint(-3, 5))
            filtered.append({
                "title": name,
                "platform": plat,
                "platform_label": self._platform_map.get(plat, plat),
                "category": cat,
                "episodes": eps,
                "views": rv,
                "commission": rc,
                "commission_text": _fmt_comm(rc),
                "heat": rh,
                "sub_type": sub_type,
                "rank": rank,
                "cover_url": "",
                "source": "模拟数据",
            })
        if sort_text.startswith("🆕"):
            filtered.sort(key=lambda x: x.get("rank", 0), reverse=True)
        elif sort_text.startswith("👁"):
            filtered.sort(key=lambda x: x["views"], reverse=True)
        elif sort_text.startswith("💰"):
            filtered.sort(key=lambda x: x["commission"], reverse=True)
        else:
            filtered.sort(key=lambda x: x["heat"], reverse=True)

        self._info_label.setText(
            f"共 {len(filtered)} 条 (模拟数据) | 更新于 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._info_label.setStyleSheet("color:#fbbf24;font-size:12px;font-weight:600;")
        self._render_items(filtered)

    def _refresh_data_status(self) -> None:
        try:
            from app.plugins.drama_finder_plugin.crawler import DramaCrawler
            from app.modules.lego.stealth_browser import is_playwright_available
            crawler = DramaCrawler()
            fresh = crawler.get_data_freshness()
            pw = False
            try:
                pw = bool(is_playwright_available())
            except Exception:
                pw = False
            if fresh.get("has_real"):
                self._data_status_label.setText("✅ 已接入真实爬取数据源")
                self._data_status_label.setStyleSheet(
                    "color:#81c784;font-size:11px;font-weight:600;padding:2px 8px;"
                    "background:#0a1a0a;border:1px solid #1a5a1a;border-radius:4px;"
                )
                self._data_status_label.setVisible(True)
            elif fresh.get("has_static"):
                tip = "📦 当前为本地静态缓存（非实时榜单）"
                if not pw:
                    tip += " · 安装 Playwright 可启用抖音/B站真爬"
                self._data_status_label.setText(tip)
                self._data_status_label.setStyleSheet(
                    "color:#ffb74d;font-size:11px;font-weight:600;padding:2px 8px;"
                    "background:#1a140a;border:1px solid #5a4a1a;border-radius:4px;"
                )
                self._data_status_label.setVisible(True)
            else:
                self._data_status_label.setText(
                    "⚠️ 当前为随机模拟数据 · 请检查缓存或安装 Playwright"
                )
                self._data_status_label.setStyleSheet(
                    "color:#ff5252;font-size:11px;font-weight:600;padding:2px 8px;"
                    "background:#1a0a0a;border:1px solid #5a1a1a;border-radius:4px;"
                )
                self._data_status_label.setVisible(True)
        except Exception as e:
            logger.debug("刷新数据状态失败: %s", e)
            self._data_status_label.setVisible(False)

    def _show_data_source_help(self) -> None:
        try:
            from app.plugins.drama_finder_plugin.crawler import DramaCrawler
            help_text = DramaCrawler.get_help_text()
        except Exception as e:
            help_text = f"数据源帮助加载失败: {e}"
        dlg = QMessageBox(self)
        dlg.setWindowTitle("短剧数据源使用说明")
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText(help_text)
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()

    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._view_mode != "cards" or not self._items:
            return
        cols = max(2, min(5, (self.width() - 320) // 190 or 3))
        if getattr(self, "_last_cols", None) != cols:
            self._last_cols = cols
            QTimer.singleShot(80, lambda: self._render_items(self._items))
# <<< FROZEN:drama-finder-ui:module END
