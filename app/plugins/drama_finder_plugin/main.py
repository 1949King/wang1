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

from app.core.plugin_loader import (
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
# DramaFinderWidget — 可视化 UI（卡片墙 + 右侧预览）
# ============================================================
try:
    from .drama_ui import DramaFinderWidget  # noqa: E402
except ImportError:
    from drama_ui import DramaFinderWidget  # type: ignore

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
    version: str = "1.1.1"
    description: str = "智能筛选热门短剧，分析热度与佣金。支持10+平台榜单浏览、多维度筛选、双数据源策略。"
    category: str = "运营工具"

    def __init__(self):
        # >>> FROZEN:drama-finder-ui:plugin-lifecycle BEGIN
        # PluginManager 只实例化、不调用 initialize；属性须在此就绪，避免 run() AttributeError
        self._context: dict = {}
        self._widget: DramaFinderWidget | None = None
        self._initialized: bool = False
        # <<< FROZEN:drama-finder-ui:plugin-lifecycle END

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
            if not hasattr(self, "_widget"):
                self._widget = None
            self._initialized = True
            logger.info("[DramaFinderPlugin] 初始化完成")
            return True
        except Exception as e:
            logger.error(f"[DramaFinderPlugin] 初始化失败: {e}")
            self._initialized = False
            return False

    def shutdown(self) -> bool:
        """关闭插件，清理资源"""
        try:
            w = getattr(self, "_widget", None)
            if w is not None:
                w.deleteLater()
                self._widget = None
            self._initialized = False
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
        w = getattr(self, "_widget", None)
        if w is not None:
            w.setVisible(False)
        logger.info("[DramaFinderPlugin] 已禁用")

    def run(self, data=None):
        """
        运行插件并返回 UI 组件 (兼容 PLUGIN_STANDARD.md)
        首次调用时创建 DramaFinderWidget，后续返回已创建的实例。
        """
        # >>> FROZEN:drama-finder-ui:run BEGIN
        if not getattr(self, "_initialized", False):
            self.initialize(getattr(self, "_context", None) or {})
        if getattr(self, "_widget", None) is None:
            ctx = getattr(self, "_context", None) or {}
            parent = ctx.get("parent_widget")
            self._widget = DramaFinderWidget(parent)
        self._widget.setVisible(True)
        return self._widget
        # <<< FROZEN:drama-finder-ui:run END

    def cleanup(self):
        """清理资源 (兼容 PLUGIN_STANDARD.md 的 cleanup 接口)"""
        self.shutdown()
