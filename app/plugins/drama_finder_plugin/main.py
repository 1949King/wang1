"""
短剧筛选插件 (DramaFinderPlugin)
=================================
按照 PLUGIN_STANDARD.md 规范开发的独立插件。
提供多平台热门短剧/漫剧筛选、分类筛选、热度排序、佣金展示。

核心能力:
- 10+ 平台热门短剧榜单浏览（抖音/快手/腾讯/爱奇艺/优酷/B站/小红书/芒果/西瓜）
- 多维度筛选：平台 × 类型 × 分类 × 关键字 × 排序
- 双数据源策略：DramaCrawler 真实数据 > 静态缓存回退
- 每5分钟自动刷新 + 数据源健康监控
"""

import logging
import random
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGroupBox, QComboBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

from core.plugin_loader import (
    IPlugin, PluginInfo, PluginType, PluginCategory
)

logger = logging.getLogger("AI短剧编辑器.drama_finder_plugin")

# ============================================================
# 静态数据缓存（120条，4大类）
# ============================================================
DRAMAS = [
    ("重生之豪门千金", "douyin", "重生", 80, 12800000, 35, 98, "短剧", 15),
    ("霸总追妻火葬场", "kuaishou", "霸总", 100, 9560000, 42, 95, "短剧", 20),
    ("神医下山之逆天改命", "tencent", "医术", 60, 18700000, 28, 92, "短剧", 12),
    ("穿越之我在古代当首富", "youku", "穿越", 72, 11200000, 30, 91, "短剧", 18),
    ("复仇女王不流泪", "iqiyi", "复仇", 90, 14300000, 38, 96, "短剧", 16),
    ("末日求生之我是王者", "bilibili", "科幻", 50, 8900000, 25, 88, "短剧", 22),
    ("甜宠王妃不好惹", "xiaohongshu", "甜宠", 65, 10500000, 33, 94, "短剧", 14),
    ("神豪从签到开始", "douyin", "神豪", 120, 22000000, 45, 97, "短剧", 25),
    ("逆袭之最强赘婿", "kuaishou", "逆袭", 85, 13600000, 36, 93, "短剧", 19),
    ("修仙归来当奶爸", "mgtv", "修仙", 70, 9800000, 32, 90, "短剧", 17),
    ("军旅之特种兵王", "xigua", "军旅", 55, 7600000, 22, 87, "短剧", 13),
    ("校园之超级学霸", "bilibili", "校园", 40, 6500000, 18, 85, "短剧", 10),
    ("武侠之少年剑客", "tencent", "武侠", 48, 8200000, 24, 89, "漫剧", 21),
    ("玄幻之斗罗大陆", "bilibili", "玄幻", 156, 35000000, 50, 99, "漫剧", 30),
    ("都市之最强保镖", "iqiyi", "都市", 95, 12800000, 35, 94, "短剧", 16),
    ("美食之厨神下凡", "douyin", "美食", 30, 4500000, 15, 82, "短剧", 8),
    ("推理之名侦探", "youku", "侦探", 45, 7200000, 21, 86, "短剧", 11),
    ("喜剧之爆笑一家人", "kuaishou", "喜剧", 100, 16500000, 40, 95, "短剧", 24),
    ("灾难之末日崩塌", "tencent", "灾难", 36, 5800000, 16, 83, "短剧", 9),
    ("治愈之猫咪咖啡馆", "xiaohongshu", "治愈", 25, 3800000, 12, 80, "短剧", 7),
    ("体育之篮球少年", "bilibili", "体育", 52, 7800000, 23, 88, "漫剧", 15),
    ("冒险之古墓探险", "mgtv", "冒险", 42, 6900000, 19, 84, "短剧", 12),
    ("科幻之星际穿越", "iqiyi", "科幻", 68, 10400000, 31, 92, "短剧", 20),
    ("言情之时光倒流", "youku", "言情", 55, 8700000, 26, 87, "漫剧", 14),
    ("职场之升职记", "douyin", "职场", 40, 6300000, 17, 84, "短剧", 10),
    ("奇幻之魔法学院", "bilibili", "奇幻", 88, 11500000, 34, 93, "漫剧", 22),
    ("古装之凤还巢", "tencent", "古装", 75, 13200000, 37, 96, "短剧", 18),
    ("悬疑之迷雾重重", "iqiyi", "悬疑", 48, 7900000, 20, 86, "短剧", 11),
    ("热血之少年歌行", "bilibili", "热血", 62, 9600000, 29, 91, "漫剧", 16),
    ("萌宠之汪星人日常", "xiaohongshu", "萌宠", 20, 3200000, 10, 78, "短剧", 6),
    ("历史之大秦帝国", "youku", "历史", 110, 14500000, 39, 95, "短剧", 26),
    ("系统之签到成神", "kuaishou", "系统流", 130, 21000000, 44, 98, "短剧", 28),
    ("后宫之嫡女归来", "mgtv", "后宫", 80, 10800000, 31, 92, "短剧", 17),
    ("机甲之战神觉醒", "xigua", "机甲", 38, 5500000, 14, 81, "漫剧", 8),
    ("恐怖之夜半惊魂", "tencent", "恐怖", 30, 4200000, 13, 79, "短剧", 7),
    ("青春之同桌的你", "douyin", "青春", 28, 4800000, 15, 82, "短剧", 9),
    ("家族之豪门风云", "iqiyi", "家庭", 90, 12500000, 34, 94, "短剧", 20),
    ("动作之极限特工", "youku", "动作", 45, 7100000, 22, 85, "短剧", 12),
    ("惊悚之密室逃脱", "bilibili", "惊悚", 25, 4100000, 12, 80, "短剧", 8),
    ("满江红2", "youku", "历史", 1, 92000000, 180, 98, "电影", 1),
    ("流浪地球3", "iqiyi", "科幻", 1, 56000000, 120, 99, "电影", 2),
    ("哪吒之魔童归来", "tencent", "奇幻", 1, 78000000, 150, 98, "电影", 3),
    ("热辣人生", "iqiyi", "喜剧", 1, 42000000, 95, 97, "电影", 4),
    ("封神第二部", "tencent", "奇幻", 1, 65000000, 130, 96, "电影", 5),
    ("战狼3", "youku", "动作", 1, 85000000, 160, 99, "电影", 6),
    ("唐人街探案4", "iqiyi", "悬疑", 1, 72000000, 140, 97, "电影", 7),
    ("长津湖之水门桥续", "tencent", "战争", 1, 95000000, 170, 99, "电影", 8),
    ("独行月球2", "youku", "科幻", 1, 38000000, 85, 95, "电影", 9),
    ("人生大事续集", "iqiyi", "家庭", 1, 52000000, 105, 96, "电影", 10),
    ("无名2", "tencent", "悬疑", 1, 48000000, 98, 94, "电影", 11),
    ("飞驰人生3", "youku", "喜剧", 1, 61000000, 115, 97, "电影", 12),
    ("深海2", "bilibili", "奇幻", 1, 35000000, 75, 93, "电影", 13),
    ("庆余年第三季", "tencent", "古装", 48, 35000000, 88, 97, "电视剧", 1),
    ("长相思续", "youku", "言情", 40, 28000000, 75, 95, "电视剧", 2),
    ("狂飙重生", "iqiyi", "悬疑", 30, 45000000, 100, 99, "电视剧", 3),
    ("大奉打更人", "tencent", "玄幻", 36, 32000000, 82, 94, "电视剧", 4),
    ("与凤行2", "iqiyi", "言情", 40, 38000000, 90, 96, "电视剧", 5),
    ("三体第二季", "tencent", "科幻", 30, 52000000, 110, 99, "电视剧", 6),
    ("狐妖小红娘真人版", "iqiyi", "奇幻", 36, 42000000, 95, 97, "电视剧", 7),
    ("人世间续", "youku", "家庭", 58, 25000000, 68, 93, "电视剧", 8),
    ("县委大院2", "tencent", "职场", 40, 28000000, 72, 94, "电视剧", 9),
    ("少年歌行2", "youku", "武侠", 40, 31000000, 78, 95, "电视剧", 10),
    ("猎冰2", "iqiyi", "悬疑", 24, 35000000, 85, 96, "电视剧", 11),
    ("梦华录续", "tencent", "古装", 40, 26000000, 70, 93, "电视剧", 12),
    ("斗罗大陆2绝世唐门", "bilibili", "玄幻", 52, 18000000, 55, 94, "漫剧", 1),
    ("完美世界动画", "tencent", "玄幻", 160, 32000000, 80, 98, "漫剧", 2),
    ("一念永恒动画", "bilibili", "修仙", 106, 15000000, 48, 95, "漫剧", 3),
    ("凡人修仙传动漫", "bilibili", "修仙", 72, 22000000, 65, 97, "漫剧", 4),
    ("遮天动画", "tencent", "玄幻", 52, 16000000, 50, 93, "漫剧", 5),
    ("仙逆动画", "bilibili", "修仙", 48, 14000000, 45, 92, "漫剧", 6),
    ("神印王座动画", "tencent", "奇幻", 88, 19000000, 58, 94, "漫剧", 7),
    ("星辰变动画", "youku", "修仙", 60, 12000000, 42, 91, "漫剧", 8),
    ("雪鹰领主动画", "tencent", "玄幻", 78, 17000000, 52, 93, "漫剧", 9),
    ("武庚纪动画", "bilibili", "奇幻", 64, 13000000, 44, 90, "漫剧", 10),
    ("秦时明月7", "bilibili", "武侠", 30, 20000000, 60, 96, "漫剧", 11),
    ("画江湖之不良人7", "tencent", "武侠", 24, 18000000, 56, 95, "漫剧", 12),
    ("大王饶命2动画", "bilibili", "都市", 24, 11000000, 38, 89, "漫剧", 13),
]

PLATFORM_MAP = {
    "douyin": "📱抖音", "kuaishou": "🎬快手", "tencent": "📺腾讯",
    "iqiyi": "🎥爱奇艺", "youku": "🎞优酷", "bilibili": "B站",
    "xiaohongshu": "📕小红书", "mgtv": "🥭芒果", "xigua": "🍉西瓜"
}

# ============================================================
# DramaFinderWidget — 独立 UI 组件
# ============================================================

class DramaFinderWidget(QWidget):
    """
    短剧筛选 UI 组件
    提供完整的多平台短剧筛选交互界面。
    不再依赖 BaseModule，使用标准 QWidget 作为独立组件。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._dramas = DRAMAS
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(300000)
        QTimer.singleShot(200, self._refresh)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ---- 筛选栏 ----
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._platform_combo = QComboBox()
        self._platform_combo.addItem("全部平台", "all")
        for pid, name in PLATFORM_MAP.items():
            self._platform_combo.addItem(name, pid)
        self._platform_combo.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
            "QComboBox:hover{border-color:#333;}"
        )
        self._platform_combo.currentIndexChanged.connect(self._refresh)
        top_row.addWidget(self._platform_combo)

        self._type_combo = QComboBox()
        self._type_combo.addItems(["全部", "短剧", "漫剧", "电影", "电视剧"])
        self._type_combo.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
        )
        self._type_combo.currentIndexChanged.connect(self._refresh)
        top_row.addWidget(self._type_combo)

        self._cat_combo = QComboBox()
        self._cat_combo.addItem("全部", "all")
        cats = [
            "重生", "霸总", "医术", "穿越", "复仇", "科幻", "甜宠", "神豪",
            "逆袭", "修仙", "军旅", "校园", "武侠", "玄幻", "都市", "美食",
            "推理", "喜剧", "治愈", "古装", "悬疑", "热血", "萌宠", "后宫",
            "机甲", "系统流", "青春", "家庭", "动作", "惊悚"
        ]
        self._cat_combo.addItems(cats)
        self._cat_combo.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
        )
        self._cat_combo.currentIndexChanged.connect(self._refresh)
        top_row.addWidget(self._cat_combo)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["🔥热度", "👁播放", "💰佣金", "⭐评分", "🆕最新"])
        self._sort_combo.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
        )
        self._sort_combo.currentIndexChanged.connect(self._refresh)
        top_row.addWidget(self._sort_combo)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索短剧名称...")
        self._search_input.setStyleSheet(
            "QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
        )
        self._search_input.returnPressed.connect(self._refresh)
        top_row.addWidget(self._search_input, 1)

        top_row.addWidget(QLabel("5分钟自动刷新"))
        layout.addLayout(top_row)

        # ---- 数据源状态条 ----
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._data_status_label = QLabel("")
        self._data_status_label.setStyleSheet(
            "color:#ff5252;font-size:11px;font-weight:600;padding:2px 8px;"
            "background:#1a0a0a;border:1px solid #5a1a1a;border-radius:4px;"
        )
        self._data_status_label.setVisible(False)
        status_row.addWidget(self._data_status_label)
        status_row.addStretch()
        help_btn = QPushButton("❓ 数据源帮助")
        help_btn.setStyleSheet(
            "QPushButton{background:#1a1a1a;color:#aaa;border:1px solid #2a2a2a;"
            "border-radius:4px;padding:4px 10px;font-size:10px;}"
            "QPushButton:hover{background:#222;color:#fff;border-color:#444;}"
        )
        help_btn.setToolTip("查看短剧数据源使用说明 (Playwright / TikHub / 模拟)")
        help_btn.clicked.connect(self._show_data_source_help)
        status_row.addWidget(help_btn)
        layout.addLayout(status_row)

        # ---- 表格 ----
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["剧名", "平台", "分类", "集数", "播放量", "佣金/万", "热度", "操作"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 8):
            self._table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 80)
        self._table.setColumnWidth(2, 60)
        self._table.setColumnWidth(3, 50)
        self._table.setColumnWidth(4, 90)
        self._table.setColumnWidth(5, 70)
        self._table.setColumnWidth(6, 60)
        self._table.setColumnWidth(7, 100)
        self._table.setStyleSheet(
            "QTableWidget{background:#0a0a0a;border:1px solid #1a1a1a;"
            "border-radius:8px;color:#ccc;gridline-color:#151515;}"
            "QHeaderView::section{background:#121212;padding:8px;border:none;"
            "border-bottom:1px solid #1a1a1a;color:#666;font-size:10px;font-weight:600;}"
            "QTableWidget::item{padding:6px 8px;border-bottom:1px solid #151515;}"
            "QTableWidget::item:selected{background:#1e3a5f;color:#fff;}"
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        # ---- 底部信息栏 ----
        bot_row = QHBoxLayout()
        self._info_label = QLabel(
            f"共 {len(self._dramas)} 条 | 更新于 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._info_label.setStyleSheet("color:#555;font-size:10px;")
        bot_row.addWidget(self._info_label)
        bot_row.addStretch()
        refresh_btn = QPushButton("🔄 立即刷新")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;"
            "border-radius:4px;padding:5px 12px;font-size:10px;}"
            "QPushButton:hover{background:#3a3a3a;}"
        )
        refresh_btn.clicked.connect(self._refresh)
        bot_row.addWidget(refresh_btn)
        layout.addLayout(bot_row)

    # ============================================================
    # 核心逻辑
    # ============================================================

    def _refresh(self) -> None:
        """筛选刷新（静态数据 + 异步爬取真实数据）"""
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
        crawler_sort = sort_map.get(sort_text, "score")

        type_map = {
            "全部": "all", "短剧": "drama", "漫剧": "comic",
            "电影": "movie", "电视剧": "tv"
        }
        content_type = type_map.get(dtype, "all")

        self._populate_from_static(keyword, platform, dtype, category, sort_text)
        self._fetch_real_data_async(content_type, platform, category, crawler_sort,
                                    keyword, sort_text)

    def _fetch_real_data_async(self, content_type: str, platform: str, category: str | None,
                                crawler_sort: str, keyword: str, sort_text: str) -> None:
        """后台异步获取真实数据"""
        try:
            from app.modules.lego.drama_crawler import DramaCrawler
            crawler = DramaCrawler()

            def on_data_fetched(dramas):
                if dramas:
                    self._populate_from_crawler(dramas)
                self._refresh_data_status()

            def on_error(err_msg):
                logger.debug(f"[DramaFinderPlugin] 后台爬取失败, 保留静态数据: {err_msg}")
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
            logger.debug(f"[DramaFinderPlugin] 异步爬取启动失败: {e}")
            self._refresh_data_status()

    def _populate_from_crawler(self, dramas) -> None:
        """用 DramaCrawler 返回的真实数据填充表格"""
        self._table.setRowCount(0)
        self._table.setRowCount(len(dramas))
        self._info_label.setText(
            f"共 {len(dramas)} 条 (真实数据) | 更新于 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._info_label.setStyleSheet("color:#4caf50;font-size:10px;")
        for i, d in enumerate(dramas):
            name = getattr(d, "title", "")
            plat_id = getattr(d, "platform", "")
            cat = getattr(d, "category", "")
            eps = getattr(d, "episodes", 0)
            views = getattr(d, "views", 0)
            comm = getattr(d, "commission", 0)
            heat = getattr(d, "heat", 0)

            items = [
                name,
                PLATFORM_MAP.get(plat_id, plat_id),
                cat, str(eps),
                f"{views // 10000}万" if views >= 10000 else str(views),
                f"¥{int(comm)}",
                str(heat),
            ]
            for j, txt in enumerate(items):
                item = QTableWidgetItem(txt)
                if j == 0:
                    item.setForeground(QColor("#1e6bde"))
                elif j == 4:
                    item.setForeground(QColor("#4caf50"))
                elif j == 5:
                    item.setForeground(QColor("#ff9800"))
                self._table.setItem(i, j, item)

            select_btn = QPushButton("选择")
            select_btn.setStyleSheet(
                "QPushButton{background:#1e6bde;color:#fff;border:none;"
                "border-radius:4px;padding:3px 12px;font-size:10px;}"
                "QPushButton:hover{background:#1557b0;}"
            )
            select_btn.clicked.connect(
                lambda checked, n=name: QMessageBox.information(
                    self, "选择短剧", f"已选择: {n}"
                )
            )
            self._table.setCellWidget(i, 7, select_btn)

    def _populate_from_static(self, keyword: str, platform: str, dtype: str,
                               category: str | None, sort_text: str) -> None:
        """用硬编码静态数据填充表格(降级方案)"""
        self._table.setRowCount(0)
        filtered: list[tuple] = []
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
            random_views = views + random.randint(-views // 6, views // 6)
            random_heat = heat + random.randint(-4, 4)
            random_comm = comm + random.randint(-3, 5)
            filtered.append((
                name, plat, cat, eps, max(1000, random_views),
                max(1, random_comm), min(99, max(60, random_heat)),
                sub_type, rank
            ))

        sort_key = {"👁播放": 4, "💰佣金": 5, "⭐评分": 6, "🔥热度": 6, "🆕最新": 8}
        key = sort_key.get(sort_text[:2], 6)
        if sort_text.startswith("🆕"):
            filtered.sort(key=lambda x: x[8], reverse=True)
        else:
            filtered.sort(key=lambda x: x[key], reverse=True)

        self._table.setRowCount(len(filtered))
        self._info_label.setText(
            f"共 {len(filtered)} 条 (模拟数据) | 更新于 {datetime.now().strftime('%H:%M:%S')}"
        )
        self._info_label.setStyleSheet("color:#ff9800;font-size:10px;")
        for i, d in enumerate(filtered):
            name, plat_id, cat, eps, views, comm, heat, _sub, _rank = d
            items = [
                name,
                PLATFORM_MAP.get(plat_id, plat_id),
                cat, str(eps),
                f"{views // 10000}万" if views >= 10000 else str(views),
                f"¥{comm}",
                str(heat),
            ]
            for j, txt in enumerate(items):
                item = QTableWidgetItem(txt)
                if j == 0:
                    item.setForeground(QColor("#1e6bde"))
                elif j == 4:
                    item.setForeground(QColor("#4caf50"))
                elif j == 5:
                    item.setForeground(QColor("#ff9800"))
                self._table.setItem(i, j, item)

            select_btn = QPushButton("选择")
            select_btn.setStyleSheet(
                "QPushButton{background:#1e6bde;color:#fff;border:none;"
                "border-radius:4px;padding:3px 12px;font-size:10px;}"
                "QPushButton:hover{background:#1557b0;}"
            )
            select_btn.clicked.connect(
                lambda checked, n=name: QMessageBox.information(
                    self, "选择短剧", f"已选择: {n}"
                )
            )
            self._table.setCellWidget(i, 7, select_btn)

    def _refresh_data_status(self) -> None:
        """根据数据源健康状态更新顶部状态条"""
        try:
            from app.modules.lego.drama_crawler import DramaCrawler
            crawler = DramaCrawler()
            has_any_real = False
            fake_platforms: list[str] = []
            try:
                health = crawler.get_data_source_health()
                for pid, info in health.items():
                    if info.get("real"):
                        has_any_real = True
                        break
                    if info.get("api_class"):
                        fake_platforms.append(pid)
            except Exception:
                pass
            if has_any_real:
                self._data_status_label.setVisible(False)
            else:
                self._data_status_label.setText(
                    f"⚠️ 当前数据为模拟 ({len(fake_platforms)} 个平台未接入真实源)"
                )
                self._data_status_label.setVisible(True)
        except (ImportError, OSError, RuntimeError) as e:
            logger.debug(f"[DramaFinderPlugin] 刷新数据状态失败: {e}")
            self._data_status_label.setVisible(False)

    def _show_data_source_help(self) -> None:
        """弹窗显示数据源帮助"""
        try:
            from app.modules.lego.drama_crawler import DramaCrawler
            help_text = DramaCrawler.get_help_text()
        except Exception as e:
            help_text = (
                "数据源帮助文档加载失败, 请确认:\n"
                "  1. app/modules/lego/drama_crawler.py 文件存在\n"
                "  2. DramaCrawler.get_help_text() 方法可访问\n\n"
                f"原始错误: {e}"
            )
        dlg = QMessageBox(self)
        dlg.setWindowTitle("短剧数据源使用说明")
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText(help_text)
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.resize(620, 480)
        dlg.exec()

    def set_theme(self, theme: str) -> None:
        """设置主题"""
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)


# ============================================================
# Plugin — 插件主类 (符合 IPlugin 接口 + PLUGIN_STANDARD)
# ============================================================

class Plugin(IPlugin):
    """
    短剧筛选插件入口

    符合 PLUGIN_STANDARD.md 规范:
    - 实现 IPlugin 接口
    - 兼容 PluginManager (name/version/description 类属性 + initialize() 无参)

    同时满足两套插件系统的验证要求:
    - PluginManager._validate_plugin 检查 hasattr(name/version/description/initialize/run)
    - IPlugin 接口检查 plugin_info property + initialize(context)
    """

    # ═══ PluginManager 兼容属性 (hasattr 检查) ═══
    name: str = "短剧筛选"
    version: str = "1.0.0"
    description: str = "智能筛选热门短剧，分析热度与佣金。支持10+平台榜单浏览、多维度筛选、双数据源策略。"
    category: str = "运营工具"

    # ═══ IPlugin 接口属性 ═══
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="drama-finder",
            name=self.name,
            version=self.version,
            description=self.description,
            author="官方",
            plugin_type=PluginType.CUSTOM,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["短剧", "筛选", "数据分析", "榜单", "佣金", "运营"],
            min_engine_version="4.4.0",
        )

    def initialize(self, context: dict | None = None) -> bool:
        """
        初始化插件 (兼容两套接口)

        PluginManager 调用: initialize() 无参
        IPlugin 接口调用: initialize(context)

        context 可选包含:
          - 'event_bus': EventBus 实例
          - 'data_bus': DataBus 实例
          - 'parent_widget': 可选的父 QWidget
        """
        try:
            self._context = context or {}
            self._widget: DramaFinderWidget | None = None
            logger.info("[DramaFinderPlugin] 初始化完成")
            return True
        except Exception as e:
            logger.error(f"[DramaFinderPlugin] 初始化失败: {e}")
            return False

    def shutdown(self) -> bool:
        """关闭插件，清理资源"""
        try:
            if self._widget:
                self._widget.deleteLater()
                self._widget = None
            logger.info("[DramaFinderPlugin] 已关闭")
            return True
        except Exception as e:
            logger.error(f"[DramaFinderPlugin] 关闭失败: {e}")
            return False

    def get_ui_config(self) -> dict:
        """获取 UI 配置"""
        return {
            "name": "短剧筛选",
            "icon": "🎭",
            "description": "多平台热门短剧筛选，热度佣金分析",
            "category": "运营工具",
            "widget_class": "DramaFinderWidget",
            "params": [
                {
                    "name": "refresh_interval",
                    "type": "slider",
                    "min": 60,
                    "max": 1800,
                    "default": 300,
                    "label": "刷新间隔(秒)",
                    "description": "数据自动刷新间隔"
                },
                {
                    "name": "auto_fetch",
                    "type": "switch",
                    "default": True,
                    "label": "自动获取真实数据",
                    "description": "启用后自动调用 DramaCrawler 获取真实数据"
                }
            ]
        }

    def on_enable(self) -> None:
        """插件启用时调用"""
        logger.info("[DramaFinderPlugin] 已启用")

    def on_disable(self) -> None:
        """插件禁用时调用"""
        if self._widget:
            self._widget.setVisible(False)
        logger.info("[DramaFinderPlugin] 已禁用")

    def run(self, data=None):
        """
        运行插件并返回 UI 组件 (兼容 PLUGIN_STANDARD.md)
        首次调用时创建 DramaFinderWidget，后续返回已创建的实例。
        """
        if self._widget is None:
            parent = self._context.get("parent_widget") if self._context else None
            self._widget = DramaFinderWidget(parent)
        self._widget.setVisible(True)
        return self._widget

    def cleanup(self):
        """清理资源 (兼容 PLUGIN_STANDARD.md 的 cleanup 接口)"""
        self.shutdown()
