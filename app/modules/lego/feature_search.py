"""
功能搜索栏模块 (FeatureSearchBar)
=================================
提供工具栏全局搜索功能：
  - 模糊匹配（中文 / 拼音首字母 / 拼音片段 / 英文关键词）
  - 弹出式结果列表，键盘上下选择 + Enter 跳转
  - 点击结果自动切换到对应 Tab 并触发功能

使用方式：
    bar = FeatureSearchBar(parent, tabs_widget, feature_index)
    layout.addWidget(bar)
"""

from __future__ import annotations
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QFrame,
    QStyledItemDelegate, QStyle, QStyleOptionViewItem
)


# ═══════════════════════════════════════════════════════════════
# 拼音映射表 — 覆盖本应用中出现的所有中文功能名
# ═══════════════════════════════════════════════════════════════

_PINYIN_MAP: Dict[str, str] = {
    # 工具栏
    "导": "dao", "入": "ru", "剪": "jian", "切": "qie", "复": "fu", "制": "zhi",
    "粘": "zhan", "贴": "tie", "删": "shan", "除": "chu", "撤": "che", "销": "xiao",
    "重": "chong", "做": "zuo", "出": "chu", "内": "nei", "核": "he",
    # 属性 tab
    "属": "shu", "性": "xing", "变": "bian", "换": "huan", "缩": "suo", "放": "fang",
    "旋": "xuan", "转": "zhuan", "锚": "mao", "点": "dian", "中": "zhong", "心": "xin",
    "左": "zuo", "上": "shang", "右": "you", "下": "xia", "合": "he", "成": "cheng",
    "不": "bu", "透": "tou", "明": "ming", "度": "du", "混": "hun", "正": "zheng",
    "常": "chang", "暗": "an", "叠": "die", "加": "jia", "深": "shen", "亮": "liang",
    "滤": "lv", "屏": "ping", "柔": "rou", "光": "guang", "强": "qiang", "差": "cha",
    "排": "pai", "色": "se", "相": "xiang", "饱": "bao", "和": "he",
    "画": "hua", "位": "wei", "置": "zhi", "大": "da", "小": "xiao", "边": "bian",
    "框": "kuang", "智": "zhi", "能": "neng", "抠": "kou", "像": "xiang",
    "绿": "lv", "蓝": "lan", "自": "zi", "定": "ding", "义": "yi", "容": "rong",
    "软": "ruan", "化": "hua", "速": "su", "裁": "cai", "预": "yu", "设": "she",
    "慢": "man", "快": "kuai", "缓": "huan", "入": "ru", "阶": "jie", "梯": "ti",
    "倒": "dao", "动": "dong", "因": "yin", "子": "zi",
    # 调色 tab
    "调": "diao", "基": "ji", "础": "chu", "校": "jiao", "曝": "pu", "曝": "pu",
    "对": "dui", "高": "gao", "阴": "yin", "影": "ying", "白": "bai", "黑": "hei",
    "彩": "cai", "整": "zheng", "然": "ran", "温": "wen", "调": "diao",
    "锐": "rui", "片": "pian", "复": "fu", "古": "gu", "暖": "uan",
    "青": "qing", "橙": "cheng", "经": "jing", "典": "dian", "日": "ri", "系": "xi",
    "清": "qing", "新": "xin", "赛": "sai", "博": "bo", "朋": "peng",
    "废": "fei", "土": "tu", "糖": "tang", "果": "guo", "夜": "ye", "蓝": "lan",
    "曲": "qu", "线": "xian", "通": "tong", "道": "dao", "红": "hong",
    "部": "bu", "间": "jian",
    # 特效 tab
    "特": "te", "效": "xiao", "电": "dian", "感": "gan", "梦": "meng", "幻": "huan",
    "都": "du", "市": "shi", "黄": "huang", "昏": "hun", "淡": "dan", "滑": "hua",
    "模": "mo", "糊": "hu", "翻": "fan", "溶": "rong", "解": "jie", "擦": "ca",
    "推": "tui", "类": "lei", "型": "xing", "时": "shi", "长": "chang", "弹": "tan",
    "性": "xing", "回": "hui",
    # 文字 tab
    "文": "wen", "字": "zi", "幕": "mu", "列": "lie", "表": "biao", "添": "tian",
    "加": "jia", "生": "sheng", "成": "cheng", "机": "ji", "器": "qi", "识": "shi",
    "别": "bie", "语": "yu", "音": "yin", "语": "yu", "言": "yan",
    "合": "he", "并": "bing", "编": "bian", "辑": "ji", "样": "yang", "式": "shi",
    "体": "ti", "粗": "cu", "斜": "xie", "描": "miao", "边": "bian", "阴": "yin",
    "背": "bei", "景": "jing",
    # 贴纸 tab
    "爱": "ai", "星": "xing", "火": "huo", "焰": "yan", "钻": "zuan", "石": "shi",
    "乐": "le", "符": "fu", "闪": "shan", "聊": "liao", "天": "tian", "气": "qi",
    "泡": "pao", "标": "biao", "签": "qian", "表": "biao", "情": "qing",
    # 音频 tab
    "频": "pin", "增": "zeng", "强": "qiang", "降": "jiang", "噪": "zao",
    "截": "jie", "取": "qu", "添": "tian", "背": "bei", "景": "jing",
    "提": "ti", "取": "qu", "声": "sheng", "人": "ren", "淡": "dan",
    "均": "jun", "衡": "heng", "器": "qi", "低": "di", "中": "zhong", "高": "gao",
    "压": "ya", "缩": "suo", "比": "bi", "混": "hun", "响": "xiang",
    "无": "wu", "房": "fang", "厅": "ting", "教": "jiao", "堂": "tang",
    "板": "ban", "式": "shi", "簧": "huang", "音": "yin", "乐": "yue",
    "踩": "cai", "点": "dian", "节": "jie", "拍": "pai", "灵": "ling",
    "敏": "min",
    # AI tab
    "引": "yin", "擎": "qing", "状": "zhuang", "态": "tai", "模": "mo", "待": "dai",
    "务": "wu", "处": "chu", "理": "li", "历": "li", "史": "shi",
    # 角色 tab
    "角": "jiao", "色": "se",
    # 导出 tab
    "导": "dao", "出": "chu", "视": "shi", "频": "pin",
    # 通用
    "应": "ying", "用": "yong", "清": "qing", "除": "chu", "原": "yuan",
    "强": "qiang", "选": "xuan", "择": "ze", "开": "kai", "始": "shi",
    "束": "shu", "结": "jie", "停": "ting",
    # 补充字符
    "镜": "jing", "头": "tou", "档": "dang", "案": "an", "库": "ku",
    "库": "ku", "管": "guan", "理": "li", "设": "she", "置": "zhi",
    "分": "fen", "辨": "bian", "率": "lv", "码": "ma", "格": "ge",
    "屏": "ping", "段": "duan", "段": "duan", "区": "qu", "间": "jian",
}

def _get_pinyin_initials(text: str) -> str:
    """提取中文文本的拼音首字母串。非中文字符保留原样。"""
    result = []
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            py = _PINYIN_MAP.get(ch, '')
            if py:
                result.append(py[0])
            else:
                result.append(ch)
        else:
            result.append(ch.lower())
    return ''.join(result)

def _get_pinyin_full(text: str) -> str:
    """提取中文文本的完整拼音（无空格连接）。非中文字符保留原样小写。"""
    result = []
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            py = _PINYIN_MAP.get(ch, '')
            if py:
                result.append(py)
            else:
                result.append(ch)
        else:
            result.append(ch.lower())
    return ''.join(result)


# ═══════════════════════════════════════════════════════════════
# 功能索引数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class FeatureItem:
    """单个可搜索功能项"""
    name: str                         # 显示名称，如 "电影感滤镜"
    tab_index: int                    # 目标 Tab 索引（-1 表示不切换）
    callback: Optional[Callable] = None  # 跳转后执行的回调
    description: str = ""             # 简短描述
    icon: str = ""                    # emoji 图标
    aliases: List[str] = field(default_factory=list)  # 额搜索别名（英文/拼音片段）
    category: str = ""                # 分类标签

    # 运行时缓存（首次搜索时计算）
    _search_text: str = field(default="", repr=False)
    _initials: str = field(default="", repr=False)
    _pinyin: str = field(default="", repr=False)


class FeatureIndex:
    """功能索引 — 管理所有可搜索功能项"""

    def __init__(self):
        self._items: List[FeatureItem] = []

    def add(self, item: FeatureItem):
        """添加一个功能项"""
        # 预计算搜索文本
        combined = item.name + " " + " ".join(item.aliases)
        item._search_text = combined.lower()
        item._initials = _get_pinyin_initials(item.name)
        item._pinyin = _get_pinyin_full(item.name)
        # 把别名也拼进 pinyin 搜索域
        for alias in item.aliases:
            if '\u4e00' <= alias[0] <= '\u9fff' if alias else False:
                item._pinyin += " " + _get_pinyin_full(alias)
                item._initials += " " + _get_pinyin_initials(alias)
        self._items.append(item)

    def search(self, query: str, max_results: int = 12) -> List[tuple]:
        """
        模糊搜索，返回 (FeatureItem, score) 列表，按相关度降序。
        评分规则：
          - 精确匹配名称: 100
          - 名称包含查询: 80
          - 拼音首字母匹配: 70
          - 拼音完整匹配: 60
          - 别名/关键词匹配: 50
          - 单字散落匹配: 30
        """
        if not query or not query.strip():
            return []

        q = query.strip().lower()
        q_initials = _get_pinyin_initials(query)
        results: List[tuple] = []

        for item in self._items:
            score = 0
            name_lower = item.name.lower()

            # 1. 精确匹配
            if q == name_lower:
                score = 100
            # 2. 名称包含查询
            elif q in name_lower:
                score = 80 + (10 if name_lower.startswith(q) else 0)
            # 3. 拼音首字母匹配
            elif q_initials and q_initials in item._initials:
                score = 70
            # 4. 完整拼音包含
            elif q in item._pinyin:
                score = 60
            # 5. 别名/关键词匹配
            elif q in item._search_text:
                score = 50
            # 6. 散落单字匹配（查询的每个字都出现在名称中）
            else:
                all_chars = name_lower + item._pinyin + item._initials + item._search_text
                if all(c in all_chars for c in q if c.strip()):
                    # 计算匹配字符比例
                    matched = sum(1 for c in q if c in all_chars)
                    total = len(q)
                    if matched / total > 0.6:
                        score = 30

            if score > 0:
                results.append((item, score))

        # 按分数降序，取前 max_results 个
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:max_results]

    @property
    def items(self) -> List[FeatureItem]:
        return self._items


# ═══════════════════════════════════════════════════════════════
# 搜索结果列表代理 — 自定义绘制
# ═══════════════════════════════════════════════════════════════

class _ResultDelegate(QStyledItemDelegate):
    """自定义搜索结果项的绘制样式"""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        painter.save()

        # 背景
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#1e6bde"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#1a1a2e"))
        else:
            painter.fillRect(option.rect, QColor("#121212"))

        item: FeatureItem = index.data(Qt.ItemDataRole.UserRole)
        if not item:
            painter.restore()
            return

        rect = option.rect
        x = rect.x() + 10
        y = rect.y()

        # 图标
        if item.icon:
            painter.setPen(QColor("#ffffff") if option.state & QStyle.StateFlag.State_Selected else QColor("#cccccc"))
            painter.drawText(x, y, 24, rect.height(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, item.icon)
            x += 26

        text_color = QColor("#ffffff") if option.state & QStyle.StateFlag.State_Selected else QColor("#e0e0e0")
        cat_color = QColor("#aaccff") if option.state & QStyle.StateFlag.State_Selected else QColor("#1e6bde")

        # 名称
        painter.setPen(text_color)
        font = painter.font()
        font.setPointSize(9)
        font.setWeight(font.Weight.Medium)
        painter.setFont(font)
        painter.drawText(x, y, rect.width() - x - 10, rect.height() // 2 + 2,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, item.name)

        # 描述
        if item.description:
            painter.setPen(QColor("#888888") if not (option.state & QStyle.StateFlag.State_Selected) else QColor("#cccccc"))
            font2 = painter.font()
            font2.setPointSize(8)
            font2.setWeight(font2.Weight.Normal)
            painter.setFont(font2)
            painter.drawText(x, y + rect.height() // 2 - 2, rect.width() - x - 10, rect.height() // 2,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, item.description)

        # 分类标签（右上角）
        if item.category:
            cat_font = painter.font()
            cat_font.setPointSize(7)
            painter.setFont(cat_font)
            painter.setPen(cat_color)
            cat_text = item.category
            fm = painter.fontMetrics()
            cat_w = fm.horizontalAdvance(cat_text) + 8
            painter.drawText(rect.right() - cat_w - 8, y, cat_w, 20,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, cat_text)

        painter.restore()


# ═══════════════════════════════════════════════════════════════
# 搜索栏主组件
# ═══════════════════════════════════════════════════════════════

class FeatureSearchBar(QFrame):
    """
    全局功能搜索栏
    - QLineEdit 输入框 + 弹出式结果列表
    - 模糊匹配中文/拼音首字母/拼音/英文关键词
    - 选中结果后切换到对应 Tab 并执行回调
    """

    feature_triggered = pyqtSignal(str)  # 功能名称

    def __init__(self, parent=None, tabs_widget=None, feature_index: Optional[FeatureIndex] = None):
        super().__init__(parent)
        self._tabs = tabs_widget
        self._index = feature_index or FeatureIndex()
        self._popup: Optional[QListWidget] = None
        self._delegate = _ResultDelegate()

        self.setFixedHeight(32)
        self.setStyleSheet("""
            QFrame#searchBar {
                background-color: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
            }
            QFrame#searchBar:focus-within {
                border: 1px solid #1e6bde;
                background-color: #1e1e1e;
            }
        """)
        self.setObjectName("searchBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # 搜索图标
        self._icon_label = QLabel("🔍")
        self._icon_label.setStyleSheet("font-size: 14px; background: transparent; border: none;")
        layout.addWidget(self._icon_label)

        # 输入框
        self._input = QLineEdit()
        self._input.setPlaceholderText("搜索功能...")
        self._input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit::placeholder-text {
                color: #555555;
            }
        """)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._on_return)
        layout.addWidget(self._input, 1)

        # 快捷键提示
        self._hint = QLabel("Ctrl+K")
        self._hint.setStyleSheet("color: #444444; font-size: 10px; background: transparent; border: none;")
        layout.addWidget(self._hint)

        # 延迟搜索（防抖）
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._do_search)

        self.installEventFilter(self)

    def set_feature_index(self, index: FeatureIndex):
        self._index = index

    def set_tabs_widget(self, tabs):
        self._tabs = tabs

    def focus_search(self):
        """聚焦搜索框并全选文本"""
        self._input.setFocus()
        self._input.selectAll()

    # ── 事件处理 ──

    def _on_text_changed(self, text: str):
        if not text.strip():
            self._hide_popup()
            return
        self._debounce.start()

    def _do_search(self):
        query = self._input.text().strip()
        if not query:
            self._hide_popup()
            return

        results = self._index.search(query)
        self._show_popup(results)

    def _on_return(self):
        """Enter 键：选中第一个结果"""
        if self._popup and self._popup.count() > 0:
            self._select_item(self._popup.item(0))

    def _show_popup(self, results: List[tuple]):
        if not results:
            self._hide_popup()
            return

        if not self._popup:
            self._popup = QListWidget()
            self._popup.setItemDelegate(self._delegate)
            self._popup.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
            self._popup.setStyleSheet("""
                QListWidget {
                    background-color: #121212;
                    border: 1px solid #2a2a2a;
                    border-radius: 8px;
                    padding: 4px;
                    outline: none;
                }
                QListWidget::item {
                    height: 44px;
                    border-radius: 4px;
                }
            """)
            self._popup.itemClicked.connect(self._on_item_clicked)
            # 关闭时清空输入焦点
            self._popup.installEventFilter(self)

        self._popup.clear()

        for item, score in results:
            li = QListWidgetItem()
            li.setData(Qt.ItemDataRole.UserRole, item)
            self._popup.addItem(li)

        # 计算弹出位置
        pos = self.mapToGlobal(self.rect().bottomLeft())
        popup_width = max(self.width(), 340)
        popup_height = min(len(results) * 48 + 12, 400)
        self._popup.setGeometry(pos.x(), pos.y() + 2, popup_width, popup_height)
        self._popup.show()
        self._popup.setCurrentRow(0)

    def _hide_popup(self):
        if self._popup:
            self._popup.hide()

    def _on_item_clicked(self, list_item: QListWidgetItem):
        self._select_item(list_item)

    def _select_item(self, list_item: QListWidgetItem):
        """选中一个搜索结果：切换 Tab + 执行回调"""
        item: Optional[FeatureItem] = list_item.data(Qt.ItemDataRole.UserRole)
        if not item:
            return

        # 切换到目标 Tab
        if item.tab_index >= 0:
            tabs = self._tabs
            # fallback: 从父组件链中查找 QTabWidget
            if tabs is None:
                from PyQt6.QtWidgets import QTabWidget
                p = self.parent()
                while p is not None:
                    if isinstance(p, QTabWidget):
                        tabs = p
                        break
                    # 查找兄弟/祖先中的 QTabWidget
                    for child in p.findChildren(QTabWidget):
                        tabs = child
                        break
                    if tabs:
                        break
                    p = p.parent()
            if tabs is not None:
                tabs.setCurrentIndex(item.tab_index)
            else:
                print(f"[FeatureSearch] ⚠️ 未找到 QTabWidget，无法切换到 tab_index={item.tab_index}")

        # 执行回调
        if item.callback:
            try:
                item.callback()
            except Exception as e:
                print(f"[FeatureSearch] 回调执行失败 '{item.name}': {e}")

        self.feature_triggered.emit(item.name)
        self._hide_popup()
        self._input.clear()
        self._input.clearFocus()

    # ── 键盘导航 ──

    def eventFilter(self, obj, event: QEvent):
        if obj == self._popup and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._hide_popup()
                self._input.clearFocus()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._popup.currentRow() >= 0:
                    self._select_item(self._popup.currentItem())
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                # 让 QListWidget 自己处理上下键
                return False
            # 其他按键转回输入框
            self._input.setFocus()
            self._input.event(event)
            return True

        if obj == self and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._hide_popup()
                self._input.clear()
                return True

        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        """键盘上下键在弹出列表中导航"""
        if self._popup and self._popup.isVisible():
            key = event.key()
            if key == Qt.Key.Key_Up:
                row = self._popup.currentRow()
                if row > 0:
                    self._popup.setCurrentRow(row - 1)
                return
            if key == Qt.Key.Key_Down:
                row = self._popup.currentRow()
                if row < self._popup.count() - 1:
                    self._popup.setCurrentRow(row + 1)
                return
        super().keyPressEvent(event)


# ═══════════════════════════════════════════════════════════════
# 构建编辑器功能索引
# ═══════════════════════════════════════════════════════════════

def build_editor_feature_index(editor) -> FeatureIndex:
    """
    根据编辑器实例构建完整的功能搜索索引。
    editor 参数是 EditorModule 实例。

    设计要点：tab 切换直接嵌入 callback，通过 editor._tools_tabs 操作，
    不依赖搜索栏自身的 _tabs 引用（避免引用丢失导致切换失效）。
    """
    idx = FeatureIndex()

    # Tab 索引映射（与 _create_tools_panel 中 addTab 顺序一致）
    TAB_PROPERTY = 0    # 属性
    TAB_COLOR = 1       # 调色
    TAB_EFFECT = 2      # 特效
    TAB_TEXT = 3        # 文字
    TAB_STICKER = 4     # 贴纸
    TAB_AUDIO = 5       # 音频
    TAB_CHARACTER = 6   # 角色
    TAB_AI = 7          # AI
    TAB_EXPORT = 8      # 导出

    def _go(tab_idx, action=None):
        """生成回调：先切换 tab，再执行 action"""
        def _cb():
            tabs = getattr(editor, '_tools_tabs', None)
            if tabs is not None and tab_idx >= 0:
                tabs.setCurrentIndex(tab_idx)
            if action:
                try:
                    action()
                except Exception as e:
                    print(f"[FeatureSearch] 回调执行失败: {e}")
        return _cb

    # ── 工具栏操作（不需要切换 tab）──
    idx.add(FeatureItem(
        name="导入视频", tab_index=-1, callback=editor._import_video,
        icon="📁", category="工具栏",
        description="导入视频文件到项目",
        aliases=["import", "open video", "daoru", "dr"]
    ))
    idx.add(FeatureItem(
        name="剪切片段", tab_index=-1, callback=editor._cut_clip,
        icon="✂️", category="工具栏",
        description="在播放头位置剪切当前片段",
        aliases=["cut", "split", "jianqie", "jq", "fenGe"]
    ))
    idx.add(FeatureItem(
        name="复制片段", tab_index=-1, callback=editor._copy_clip,
        icon="📋", category="工具栏",
        description="复制选中的片段",
        aliases=["copy", "fuzhi", "fz"]
    ))
    idx.add(FeatureItem(
        name="粘贴片段", tab_index=-1, callback=editor._paste_clip,
        icon="📄", category="工具栏",
        description="粘贴已复制的片段",
        aliases=["paste", "niantie", "nt"]
    ))
    idx.add(FeatureItem(
        name="删除片段", tab_index=-1, callback=editor._delete_clip,
        icon="🗑️", category="工具栏",
        description="删除选中的片段",
        aliases=["delete", "remove", "shanchu", "sc"]
    ))
    idx.add(FeatureItem(
        name="撤销", tab_index=-1, callback=editor._undo,
        icon="🔄", category="工具栏",
        description="撤销上一步操作 (Ctrl+Z)",
        aliases=["undo", "chexiao", "cx"]
    ))
    idx.add(FeatureItem(
        name="重做", tab_index=-1, callback=editor._redo,
        icon="🔄", category="工具栏",
        description="重做已撤销的操作 (Ctrl+Y)",
        aliases=["redo", "chongzuo", "cz"]
    ))
    idx.add(FeatureItem(
        name="导出视频", tab_index=-1, callback=_go(TAB_EXPORT, editor._export_video),
        icon="💾", category="工具栏",
        description="导出/渲染最终视频",
        aliases=["export", "render", "daochu", "dc", "shuchu"]
    ))

    # ── 属性 Tab ──
    idx.add(FeatureItem(
        name="变换 - 位置/缩放/旋转", tab_index=-1, callback=_go(TAB_PROPERTY),
        icon="📐", category="属性",
        description="调整片段的位置、缩放、旋转角度",
        aliases=["transform", "position", "scale", "rotate", "bianhuan", "suofang", "xuanzhuan"]
    ))
    idx.add(FeatureItem(
        name="画中画", tab_index=-1, callback=_go(TAB_PROPERTY, getattr(editor, '_apply_pip', None)),
        icon="📺", category="属性",
        description="添加画中画效果（叠加小窗口）",
        aliases=["pip", "picture in picture", "huazhonghua", "pyp", "hzhy"]
    ))
    idx.add(FeatureItem(
        name="智能抠像 / 绿幕", tab_index=-1, callback=_go(TAB_PROPERTY, getattr(editor, '_apply_chroma_key', None)),
        icon="🎨", category="属性",
        description="色度键抠像，去除绿幕/蓝幕背景",
        aliases=["chroma key", "green screen", "kouxiang", "lvse", "lv_mu", "seDuJian"]
    ))
    idx.add(FeatureItem(
        name="变速 / 慢放 / 快放", tab_index=-1, callback=_go(TAB_PROPERTY, getattr(editor, '_apply_speed_ramp', None)),
        icon="⚡", category="属性",
        description="调整播放速度，支持慢放、快放、缓入缓出",
        aliases=["speed", "slow motion", "fast forward", "biansu", "manfang", "kuaifang", "suDu"]
    ))
    idx.add(FeatureItem(
        name="不透明度 / 混合模式", tab_index=-1, callback=_go(TAB_PROPERTY),
        icon="🔮", category="属性",
        description="调整片段透明度和混合模式（叠加/滤色/柔光等）",
        aliases=["opacity", "blend mode", "toumingdu", "hunhe", "butouming"]
    ))

    # ── 调色 Tab ──
    idx.add(FeatureItem(
        name="基础调色 - 曝光/对比度", tab_index=-1, callback=_go(TAB_COLOR),
        icon="🎨", category="调色",
        description="调整曝光、对比度、高光、阴影、白色、黑色",
        aliases=["basic color", "exposure", "contrast", "jichu", "diaose", "baoguang", "duibidu"]
    ))
    idx.add(FeatureItem(
        name="色彩调整 - 饱和度/色温", tab_index=-1, callback=_go(TAB_COLOR),
        icon="🌡️", category="调色",
        description="调整饱和度、自然饱和度、色温、色调、锐度",
        aliases=["saturation", "temperature", "baoheDU", "seWen", "seDiao"]
    ))
    idx.add(FeatureItem(
        name="LUT 预设", tab_index=-1, callback=_go(TAB_COLOR),
        icon="🎬", category="调色",
        description="一键应用电影胶片、复古暖调、青橙色调等预设",
        aliases=["lut", "preset", "filter", "yushe", "dianying", "fugu", "qingcheng"]
    ))
    idx.add(FeatureItem(
        name="HSL 调整", tab_index=-1, callback=_go(TAB_COLOR),
        icon="🌈", category="调色",
        description="色相/饱和度/明度三通道独立调整",
        aliases=["hsl", "hue", "saturation", "luminance", "seXiang", "baohe", "mingDu"]
    ))
    idx.add(FeatureItem(
        name="曲线调色", tab_index=-1, callback=_go(TAB_COLOR, getattr(editor, '_apply_curve_color', None)),
        icon="📈", category="调色",
        description="RGB/红/绿/蓝通道曲线调色，暗部/中间调/亮部分区控制",
        aliases=["curve", "qvxian", "RGB", "tongdao"]
    ))

    # ── 特效 Tab ──
    filter_names = [
        ("电影感滤镜", "dianyinggan", "movie", "cinematic"),
        ("复古滤镜", "fugu", "retro", "vintage"),
        ("清新滤镜", "qingxin", "fresh", "clean"),
        ("黑白滤镜", "heibai", "black white", "monochrome", "grayscale"),
        ("暖色调滤镜", "nuanse", "warm", "nuanSeDiao"),
        ("冷色调滤镜", "lengdiao", "cool", "cold", "lengSeDiao"),
        ("梦幻滤镜", "menghuan", "dream", "fantasy"),
        ("锐利滤镜", "ruili", "sharp", "sharpen"),
        ("柔和滤镜", "rouhe", "soft", "blur"),
        ("都市滤镜", "dushi", "urban", "city"),
        ("黄昏滤镜", "huanghun", "sunset", "dusk"),
    ]
    for display_name, py_alias, *en_aliases in filter_names:
        key = display_name.replace("滤镜", "")
        action = (lambda k=key: editor._select_filter(k)) if hasattr(editor, '_select_filter') else None
        idx.add(FeatureItem(
            name=display_name, tab_index=-1, callback=_go(TAB_EFFECT, action),
            icon="🎞️", category="滤镜",
            description=f"应用{key}风格滤镜效果",
            aliases=[py_alias] + list(en_aliases)
        ))
    idx.add(FeatureItem(
        name="清除滤镜 / 恢复原片", tab_index=-1, callback=_go(TAB_EFFECT, getattr(editor, '_clear_filter', None)),
        icon="🗑️", category="滤镜",
        description="移除当前滤镜，恢复原始画面",
        aliases=["clear filter", "reset", "qingchu", "huanyuan", "yuanPian"]
    ))

    transition_names = [
        ("淡入淡出转场", "danru danchu", "fade", "fadeIn"),
        ("滑动转场", "huadong", "slide", "sliding"),
        ("缩放转场", "suofang", "zoom", "scale"),
        ("模糊转场", "mohu", "blur", "dissolve"),
        ("翻转转场", "fanzhuan", "flip", "rotate"),
        ("溶解转场", "rongjie", "dissolve", "melt"),
        ("擦除转场", "cacchu", "wipe", "erasing"),
        ("推入转场", "tuiru", "push", "slide in"),
        ("旋转转场", "xuanzhuan", "rotate", "spin"),
    ]
    for display_name, py_alias, *en_aliases in transition_names:
        idx.add(FeatureItem(
            name=display_name, tab_index=-1, callback=_go(TAB_EFFECT),
            icon="🔄", category="转场",
            description=f"应用{display_name.replace('转场', '')}转场效果",
            aliases=[py_alias] + list(en_aliases)
        ))

    # ── 文字 Tab ──
    idx.add(FeatureItem(
        name="添加字幕", tab_index=-1, callback=_go(TAB_TEXT, getattr(editor, '_add_subtitle', None)),
        icon="➕", category="文字",
        description="手动添加一条字幕",
        aliases=["add subtitle", "tianjia", "zimu", "add caption"]
    ))
    idx.add(FeatureItem(
        name="AI 自动生成字幕", tab_index=-1, callback=_go(TAB_TEXT, getattr(editor, '_generate_ai_subtitles', None)),
        icon="🤖", category="文字",
        description="使用 AI 语音识别自动生成字幕",
        aliases=["ai subtitle", "auto caption", "speech recognition", "AI zimu", "zidong", "shengcheng"]
    ))
    idx.add(FeatureItem(
        name="导入字幕文件", tab_index=-1, callback=_go(TAB_TEXT, getattr(editor, '_import_subtitles', None)),
        icon="📥", category="文字",
        description="从 SRT/ASS 文件导入字幕",
        aliases=["import subtitle", "srt", "ass", "daoru", "zimu"]
    ))
    idx.add(FeatureItem(
        name="导出字幕文件", tab_index=-1, callback=_go(TAB_TEXT, getattr(editor, '_export_subtitles', None)),
        icon="📤", category="文字",
        description="导出字幕为 SRT 文件",
        aliases=["export subtitle", "srt", "daochu", "zimu"]
    ))
    idx.add(FeatureItem(
        name="合并字幕", tab_index=-1, callback=_go(TAB_TEXT, getattr(editor, '_merge_subtitle', None)),
        icon="🔗", category="文字",
        description="合并相邻的字幕条目",
        aliases=["merge subtitle", "hebing", "zimu"]
    ))

    # ── 贴纸 Tab ──
    idx.add(FeatureItem(
        name="贴纸库", tab_index=-1, callback=_go(TAB_STICKER),
        icon="✨", category="贴纸",
        description="浏览和添加贴纸（爱心、星星、火焰等）",
        aliases=["sticker", "emoji", "tiezhi", "biaoqing", "sticker library"]
    ))

    # ── 音频 Tab ──
    idx.add(FeatureItem(
        name="音频增强", tab_index=-1, callback=_go(TAB_AUDIO, getattr(editor, '_enhance_audio', None)),
        icon="🔊", category="音频",
        description="增强音频音量和清晰度",
        aliases=["audio enhance", "boost", "zengqiang", "yinPin"]
    ))
    idx.add(FeatureItem(
        name="音频降噪", tab_index=-1, callback=_go(TAB_AUDIO, getattr(editor, '_denoise_audio', None)),
        icon="🎤", category="音频",
        description="降低背景噪声",
        aliases=["denoise", "noise reduction", "jiangzao", "zaoyin"]
    ))
    idx.add(FeatureItem(
        name="截取音频", tab_index=-1, callback=_go(TAB_AUDIO, getattr(editor, '_crop_audio', None)),
        icon="✂️", category="音频",
        description="截取选定范围的音频片段",
        aliases=["crop audio", "trim", "jietiqu", "jieQu"]
    ))
    idx.add(FeatureItem(
        name="添加背景音乐 BGM", tab_index=-1, callback=_go(TAB_AUDIO, getattr(editor, '_add_bgm', None)),
        icon="🎵", category="音频",
        description="添加背景音乐文件",
        aliases=["bgm", "background music", "tianjia", "beijing", "yinyue"]
    ))
    idx.add(FeatureItem(
        name="提取人声", tab_index=-1, callback=_go(TAB_AUDIO, getattr(editor, '_extract_vocal', None)),
        icon="👤", category="音频",
        description="从音频中分离提取人声",
        aliases=["extract vocal", "vocal separation", "tiQu", "renSheng", "voice"]
    ))
    idx.add(FeatureItem(
        name="淡入淡出", tab_index=-1, callback=_go(TAB_AUDIO, getattr(editor, '_apply_fade_effects', None)),
        icon="🎵", category="音频",
        description="应用音频淡入/淡出效果",
        aliases=["fade in", "fade out", "danru", "danchu", "fadeIn", "fadeOut"]
    ))
    idx.add(FeatureItem(
        name="均衡器", tab_index=-1, callback=_go(TAB_AUDIO),
        icon="🎛️", category="音频",
        description="调整低频/中频/高频",
        aliases=["equalizer", "eq", "junhengQi", "diPin", "gaoPin"]
    ))
    idx.add(FeatureItem(
        name="音乐踩点 / 节拍检测", tab_index=-1, callback=_go(TAB_AUDIO, getattr(editor, '_detect_beats', None)),
        icon="🥁", category="音频",
        description="自动检测音乐节拍点，辅助卡点剪辑",
        aliases=["beat detection", "music sync", "caidian", "jiePai", "beat"]
    ))

    # ── AI Tab ──
    idx.add(FeatureItem(
        name="FunClip 智能剪辑", tab_index=-1, callback=_go(TAB_AI, getattr(editor, '_funclip_process', None)),
        icon="🎬", category="AI工具",
        description="阿里达摩院 FunClip，自动剪辑分段",
        aliases=["funclip", "auto clip", "alibaba", "zidong", "jianJi"]
    ))
    idx.add(FeatureItem(
        name="AutoClip 高光识别", tab_index=-1, callback=_go(TAB_AI, getattr(editor, '_autoclip_process', None)),
        icon="⚡", category="AI工具",
        description="AI 高光识别，多镜头自动组接",
        aliases=["autoclip", "highlight", "gaoGuang", "shiBie"]
    ))
    idx.add(FeatureItem(
        name="Fusion 视频修复", tab_index=-1, callback=_go(TAB_AI, getattr(editor, '_videofusion_process', None)),
        icon="✨", category="AI工具",
        description="视频修复与画质增强",
        aliases=["fusion", "video restore", "xiufu", "huazhi", "enhance"]
    ))
    idx.add(FeatureItem(
        name="LoRA 风格迁移", tab_index=-1, callback=_go(TAB_AI, getattr(editor, '_lora_edit_process', None)),
        icon="🎨", category="AI工具",
        description="AI 创意编辑与风格迁移",
        aliases=["lora", "style transfer", "fengGe", "qianYi", "chuangYi"]
    ))
    idx.add(FeatureItem(
        name="AI 字幕识别", tab_index=-1, callback=_go(TAB_AI, getattr(editor, '_generate_ai_subtitles', None)),
        icon="📝", category="AI工具",
        description="语音识别自动生成字幕",
        aliases=["ai subtitle", "speech to text", "AI zimu", "yuyin", "shibie"]
    ))
    idx.add(FeatureItem(
        name="AI 音频处理", tab_index=-1, callback=_go(TAB_AI, getattr(editor, '_enhance_audio', None)),
        icon="🔊", category="AI工具",
        description="AI 降噪增强与人声分离",
        aliases=["ai audio", "denoise", "enhance", "AI yinPin", "jiangZao"]
    ))

    # ── 角色 Tab ──
    idx.add(FeatureItem(
        name="角色管理", tab_index=-1, callback=_go(TAB_CHARACTER),
        icon="👤", category="角色",
        description="管理项目中的角色设定",
        aliases=["character", "role", "juese", "guanLi"]
    ))

    # ── 导出 Tab ──
    idx.add(FeatureItem(
        name="导出设置", tab_index=-1, callback=_go(TAB_EXPORT),
        icon="💾", category="导出",
        description="设置分辨率、码率、格式等导出参数",
        aliases=["export settings", "render", "daochu", "sheZhi", "fenBianLv"]
    ))

    return idx
