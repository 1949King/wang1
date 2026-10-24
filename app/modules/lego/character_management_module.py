"""
角色 / AI 画布模块
=================
原「角色管理」主界面已替换为镶嵌的自研拾光导演台画布。

- 主视图：vendor/shiguang-canvas（WebEngine）生图/生视频
- 角色库：CharacterStore 仍持久化；侧栏「角色库」编辑 + 生成资产挂载
- 回流：canvas_bridge → EventBus MATERIAL_TO_TIMELINE → 剪辑
- 插帧：可选开启线性补帧（非神经网络）

剪辑模块内「角色」页签仍是视频级临时偏好，与本模块互补。
"""

import json
import os
import re
import time
import datetime
import logging
import threading
from typing import Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.characters")

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget,
    QListWidgetItem, QComboBox, QFileDialog, QMessageBox,
    QFrame, QGroupBox, QScrollArea, QInputDialog, QColorDialog,
    QTabWidget, QProgressBar, QSizePolicy, QCheckBox,
    QToolButton, QMenu,
)

from .base_module import BaseModule


# ---------------------------------------------------------------------------
# 状态栏文案清洗（2026-10-19 · 用户授权解冻 stage3d-core）
# ---------------------------------------------------------------------------
#
# 动机（用户实测截图反馈）：「打开 AI 画布，顶上总是有一条网页链接，很烦。」
#
# 根因：canvas-agent 启动成功时，后端 `ensure_started()` 返回的消息里带
# `http://127.0.0.1:17371?token=…`，`_set_status()` 原样 setText，于是地址常驻
# 顶栏。地址本身是**给 Codex/MCP 用的调试信息**，不是给用户看的产品文案。
#
# 纪律：状态栏只放人类可读文案；URL / token 一律剥掉（需要时走「⋯ → 复制
# Agent 地址」显式取）。空文案直接隐藏状态条，不占位。
_URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff（）()<>\"'，。；：、]+")
_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])token=[A-Za-z0-9._\-]+")


def _strip_urls(text: str) -> str:
    """剥掉文案里的 URL / token，并压缩多余空白。"""
    if not text:
        return ""
    cleaned = _URL_RE.sub("", text)
    cleaned = _TOKEN_RE.sub("", cleaned)
    # URL 剥掉后常留下「：」或括号尾巴，压缩一下空白更自然
    cleaned = re.sub(r"[（(]\s*[）)]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ：:，,、")
    return cleaned


# ---------------------------------------------------------------------------
# 角色数据模型
# ---------------------------------------------------------------------------

# 字段定义：(key, 中文标签, 类型, 是否必填, 分组)
#
# 分组决定字段「流向哪里」，改分组前先确认消费方：
#   base   — 基础身份，渲染在面板头部（不出现在滚动表单里）
#   visual — 影响生图/生视频提示词（build_character_prompt 读取，仅此组进提示词）
#   inner  — 内在人格，供剧本创作与跨集一致性校验；**不进提示词**
#            （画面描述里塞「核心欲望」只会污染出图，这是刻意的隔离）
#   other  — 其他长文本
#
# ⚠️ 新增字段需同步 4 处，否则「填了不生效」或「前端看不到」：
#   ① 本表
#   ② app/core/canvas_bridge.py::build_character_prompt（仅 visual 组）
#   ③ app/core/canvas_server.py::/host/characters（已改为按本表派生，无需手工加）
#   ④ vendor/shiguang-canvas 与 vendor/AI-Canvas-tauri 两处 node-factory.ts 的 CharacterEntry
CHARACTER_FIELD_SCHEMA = [
    # ---- 基础身份 ----
    ("name",         "角色名",       "string",  True,  "base"),
    ("gender",       "性别",         "enum",    False, "base"),  # enum: 男/女/其他
    ("age_range",    "年龄段",       "string",  False, "base"),  # 如: 青年 / 中年
    ("role_type",    "角色类型",     "enum",    False, "base"),  # enum: 主角 / 配角 / 反派
    ("tags",         "标签",         "list",    False, "base"),  # 逗号分隔
    # ---- 形象与符号（进生图提示词）----
    ("appearance",     "外貌特征",   "text",    False, "visual"),  # 衣着、发型、体态
    ("temperament",    "气质倾向",   "text",    False, "visual"),  # 如: 清冷疏离 / 温润克己
    ("memory_anchors", "标志性符号", "text",    False, "visual"),  # 跨集可辨识的固定视觉符号
    ("personality",    "性格特征",   "text",    False, "visual"),  # 性格描述
    # 捏脸卡片（FaceCard.tsx）写回的 faceParams JSON 串。放 visual 组 ⇒ 进生图提示词；
    # 由 canvas_bridge.build_character_prompt 转成文字（结构/枚举/色板的唯一真相源在画布侧 faceParams.ts）。
    ("face_params", "捏脸参数（画布捏脸卡片写入）", "text", False, "visual"),
    # ---- 内在人格（剧本一致性；不进提示词）----
    ("values",           "价值排序",   "text",  False, "inner"),  # 最看重什么、如何排序
    ("core_desire",      "核心欲望",   "text",  False, "inner"),  # 驱动行动的根本诉求
    ("relations",        "关系网",     "text",  False, "inner"),  # 与关键人物的关系及张力
    ("backstory_events", "关键经历",   "text",  False, "inner"),  # 塑造其性格的关键事件
    ("sensory_triggers", "情绪触发点", "text",  False, "inner"),  # 什么会激起强烈情绪
    ("thinking_pattern", "思维模式",   "text",  False, "inner"),  # 归因方式 / 自动化思维
    ("feedback_pattern", "应激反应",   "text",  False, "inner"),  # 受挫 / 被认可时的行为倾向
    ("speech_style",     "语言风格",   "text",  False, "inner"),  # 语气 / 口头禅 / 说话习惯
    # ---- 其他 ----
    ("representative_line", "代表台词", "text",  False, "other"),
    ("background",   "人物背景",     "text",    False, "other"),
    ("notes",        "备注",         "text",    False, "other"),
    # 缺口①：交给 3D 导演台的身体预设。放 other 组（**不进生图提示词** ⇒ 不必改
    # canvas_bridge.build_character_prompt，冻结区的桥接行为零变化）。
    ("human_variant", "体型预设（3D 导演台）", "enum", False, "other"),
]

# 分组渲染顺序 + 显示名（UI 渲染与提示词筛选共用同一份定义）
CHARACTER_FIELD_GROUPS = [
    ("base",   "基础身份"),
    ("visual", "形象与符号 · 影响出图"),
    ("inner",  "内在人格 · 剧本一致性"),
    ("other",  "其他"),
]

# 头部单行控件承载的字段，不重复出现在滚动表单里
_HEADER_FIELD_KEYS = ("name", "gender", "age_range", "role_type", "tags")


def characters_schema_by_group(group: str) -> List[tuple]:
    """按分组取字段定义（保持 schema 原序）。"""
    return [f for f in CHARACTER_FIELD_SCHEMA if f[4] == group]


GENDER_OPTIONS = ["男", "女", "其他"]
ROLE_OPTIONS = ["主角", "配角", "反派", "路人"]

# 3D 导演台体型预设（缺口①）：值必须与画布 `riggedHumanoid.ts::HUMAN_PRESETS` 的 key
# **逐字相同**，否则导演台查不到预设、只能退回「按性别/年龄段推断」的兜底。
# 唯一真相源在画布侧，这里只是「可选项镜像」；改动需同步 _verify/check_character_schema.py 与本表。
HUMAN_VARIANT_OPTIONS = [
    ("", "未指定（按性别/年龄段推断）"),
    ("male_std", "男·标准"),
    ("female_std", "女·标准"),
    ("male_thin", "男·瘦"),
    ("male_heavy", "男·胖"),
    ("child", "儿童"),
]

# enum 字段 → 可选值来源。(value, 显示文本) 成对；值为 "" 表示「未指定」。
# 注意：gender / role_type 虽也是 enum，但由头部单行控件承载（见 _HEADER_FIELD_KEYS），
# 不会走到滚动表单的 enum 分支，故无需登记在这里。
_ENUM_SOURCES: Dict[str, List[tuple]] = {
    "human_variant": HUMAN_VARIANT_OPTIONS,
}


def enum_options(key: str) -> List[tuple]:
    """取 enum 字段的可选值；无来源返回空列表（调用方退化为纯文本框，绝不静默丢字段）。"""
    return list(_ENUM_SOURCES.get(key, []))


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------

class CharacterStore:
    """角色库的 JSON 持久化"""

    def __init__(self, store_path: Optional[str] = None):
        if store_path is None:
            home = os.path.expanduser("~")
            store_path = os.path.join(home, ".video_editor_cache", "characters", "library.json")
        self._path = store_path
        self._ensure_dir()
        self._characters: List[Dict] = self._load()

    # ---------- 内部 ----------

    def _ensure_dir(self):
        d = os.path.dirname(self._path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)

    def _load(self) -> List[Dict]:
        if not os.path.isfile(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            logger.warning(f"角色数据加载失败 ({self._path}): {e}")
            return []

    def _save(self) -> bool:
        self._ensure_dir()
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._characters, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"角色数据保存失败 ({self._path}): {e}")
            return False

    # ---------- 对外 ----------

    def all(self) -> List[Dict]:
        return list(self._characters)

    def get(self, char_id: str) -> Optional[Dict]:
        for c in self._characters:
            if c.get("id") == char_id:
                return c
        return None

    def add(self, data: Dict) -> str:
        """新增角色。自动生成 id，返回新 id"""
        new_id = data.get("id") or f"char_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:17]}"
        data = dict(data)
        data["id"] = new_id
        data["created_at"] = data.get("created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._characters.append(data)
        if not self._save():
            # 修复：此前保存失败时虽然正确回滚了内存变更，但依然 return new_id（真值），
            # 调用方 `_on_save` 只看 `if new_id:` 就判定成功，磁盘写入失败也会弹"保存成功"
            self._characters.pop()
            logger.warning(f"新增角色保存失败，已回滚内存变更: {new_id}")
            return ""
        return new_id

    def update(self, char_id: str, data: Dict) -> bool:
        for i, c in enumerate(self._characters):
            if c.get("id") == char_id:
                old_data = dict(self._characters[i])
                merged = dict(c)
                merged.update(data)
                merged["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._characters[i] = merged
                if not self._save():
                    # 保存失败，回滚到旧数据
                    self._characters[i] = old_data
                    logger.warning(f"更新角色保存失败，已回滚: {char_id}")
                    return False
                return True
        return False

    def remove(self, char_id: str) -> bool:
        before = len(self._characters)
        removed_chars = [c for c in self._characters if c.get("id") == char_id]
        self._characters = [c for c in self._characters if c.get("id") != char_id]
        if len(self._characters) != before:
            if not self._save():
                # 保存失败，恢复删除的条目
                self._characters.extend(removed_chars)
                logger.warning(f"删除角色保存失败，已回滚: {char_id}")
                return False
            return True
        return False

    def export(self, target_path: str, char_ids: Optional[List[str]] = None) -> bool:
        try:
            data = self._characters if char_ids is None else [c for c in self._characters if c.get("id") in char_ids]
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"角色导出失败 ({target_path}): {e}")
            return False

    def import_file(self, source_path: str, merge: bool = True) -> int:
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                incoming = json.load(f)
            if not isinstance(incoming, list):
                return 0
            count = 0
            for c in incoming:
                if not isinstance(c, dict):
                    continue
                c = dict(c)
                c["id"] = c.get("id") or f"char_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}_{count}"
                c["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c["created_at"] = c.get("created_at") or c["updated_at"]
                self._characters.append(c)
                count += 1
            if count:
                if not self._save():
                    # 持久化失败，回滚导入的条目
                    self._characters = self._characters[:-count]
                    logger.error(f"角色导入后保存失败，已回滚 {count} 条记录")
                    return 0
            return count
        except Exception as e:
            logger.error(f"角色导入失败: {e}")
            return 0

    def count(self) -> int:
        return len(self._characters)


# ---------------------------------------------------------------------------
# 角色详情编辑面板
# ---------------------------------------------------------------------------

class CharacterEditorPanel(QWidget):
    """右侧：角色详情 / 编辑面板"""

    saved = pyqtSignal()  # 保存后触发，通知外部刷新

    def __init__(self, store: CharacterStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._current_id: Optional[str] = None
        self._build_ui()
        self.set_enabled(False)

    # ------ UI ------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # 头部：角色名 + 操作
        header = QFrame()
        header.setStyleSheet("QFrame{background:#121212;border:1px solid #1e1e1e;border-radius:8px;}")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 12, 14, 12)
        hl.setSpacing(8)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("请输入角色名（必填）")
        self._name_edit.setStyleSheet(self._line_edit_style())
        hl.addWidget(self._name_edit)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(12)
        self._gender_combo = QComboBox()
        self._gender_combo.addItems(GENDER_OPTIONS)
        self._gender_combo.setStyleSheet(self._combo_style())

        self._role_combo = QComboBox()
        self._role_combo.addItems(ROLE_OPTIONS)
        self._role_combo.setStyleSheet(self._combo_style())

        self._age_edit = QLineEdit()
        self._age_edit.setPlaceholderText("年龄段（如：青年）")
        self._age_edit.setStyleSheet(self._line_edit_style())

        meta_row.addWidget(QLabel("性别"))
        meta_row.addWidget(self._gender_combo)
        meta_row.addWidget(QLabel("类型"))
        meta_row.addWidget(self._role_combo)
        meta_row.addWidget(QLabel("年龄段"))
        meta_row.addWidget(self._age_edit, 1)
        hl.addLayout(meta_row)

        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("标签（英文逗号分隔，如：总裁, 善良, 职场）")
        self._tags_edit.setStyleSheet(self._line_edit_style())
        hl.addWidget(self._tags_edit)

        root.addWidget(header)

        # 长文本字段：按 schema 分组动态生成
        # 加字段只需改 CHARACTER_FIELD_SCHEMA —— 此处不再逐个硬编码控件，
        # 避免「schema 加了字段、UI 忘了加控件」这类漂移
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        form_inner = QWidget()
        form_layout = QVBoxLayout(form_inner)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)

        self._text_edits: Dict[str, QTextEdit] = {}
        # enum 字段的下拉框。此前动态生成器只认 text/string ⇒ enum 字段**根本没有控件**，
        # 新加一个 enum 字段会表现为「标题看得见、值填不了、保存后永远是空」的静默失效。
        self._enum_combos: Dict[str, QComboBox] = {}
        for group_key, group_label in CHARACTER_FIELD_GROUPS:
            fields = [
                f for f in characters_schema_by_group(group_key)
                if f[0] not in _HEADER_FIELD_KEYS and f[2] in ("text", "string", "enum")
            ]
            if not fields:
                continue  # base 组已由头部单行控件承载
            group_lbl = QLabel(group_label)
            group_lbl.setStyleSheet(
                "color:#7c9cbf;font-size:11px;font-weight:bold;"
                "padding-top:8px;border-top:1px solid #242424;"
            )
            form_layout.addWidget(group_lbl)
            # inner 组字段普遍短，压缩高度以免面板过长
            box_h = 76 if group_key == "inner" else 104
            for key, label, ftype, _required, _group in fields:
                lbl = QLabel(label)
                lbl.setStyleSheet("color:#bbb;font-size:12px;font-weight:bold;")
                form_layout.addWidget(lbl)
                opts = enum_options(key) if ftype == "enum" else []
                if opts:
                    # 有枚举来源 ⇒ 下拉框（值存在 itemData 里，与显示文本解耦）
                    combo = QComboBox()
                    for value, text in opts:
                        combo.addItem(text, value)
                    combo.setStyleSheet(self._combo_style())
                    self._enum_combos[key] = combo
                    form_layout.addWidget(combo)
                    continue
                # 无枚举来源的 enum / 常规文本 ⇒ 文本框兜底，绝不静默丢字段
                edit = self._mk_text_edit("", max_height=box_h)
                self._text_edits[key] = edit
                form_layout.addWidget(edit)

        form_layout.addStretch()
        form_scroll.setWidget(form_inner)
        root.addWidget(form_scroll, 1)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._save_btn = QPushButton("💾 保存")
        self._save_btn.setStyleSheet(self._primary_btn_style())
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        self._delete_btn = QPushButton("🗑️ 删除")
        self._delete_btn.setStyleSheet(self._danger_btn_style())
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        root.addLayout(btn_row)

    def _mk_text_edit(self, placeholder: str = "", max_height: int = 120) -> QTextEdit:
        te = QTextEdit()
        te.setPlaceholderText(placeholder)
        te.setMaximumHeight(max_height)
        te.setStyleSheet("""
            QTextEdit {
                background:#1a1a1a; color:#eee; border:1px solid #2a2a2a;
                border-radius:6px; padding:8px; font-size:12px;
            }
            QTextEdit:focus { border:1px solid #1e6bde; }
        """)
        return te

    @staticmethod
    def _line_edit_style() -> str:
        return """
            QLineEdit {
                background:#1a1a1a; color:#eee; border:1px solid #2a2a2a;
                border-radius:6px; padding:8px; font-size:12px;
            }
            QLineEdit:focus { border:1px solid #1e6bde; }
        """

    @staticmethod
    def _combo_style() -> str:
        return """
            QComboBox {
                background:#1a1a1a; color:#eee; border:1px solid #2a2a2a;
                border-radius:6px; padding:6px 10px; font-size:12px; min-width:80px;
            }
            QComboBox:focus { border:1px solid #1e6bde; }
            QComboBox QAbstractItemView {
                background:#1a1a1a; color:#eee; border:1px solid #2a2a2a;
                selection-background-color:#1e6bde;
            }
        """

    @staticmethod
    def _primary_btn_style() -> str:
        return """
            QPushButton {
                background:#1e6bde; color:#fff; border:none; border-radius:6px;
                padding:8px 20px; font-size:12px; font-weight:bold;
            }
            QPushButton:hover { background:#2a7fea; }
            QPushButton:pressed { background:#1a5cc0; }
            QPushButton:disabled { background:#2a2a2a; color:#666; }
        """

    @staticmethod
    def _danger_btn_style() -> str:
        return """
            QPushButton {
                background:#c62828; color:#fff; border:none; border-radius:6px;
                padding:8px 20px; font-size:12px; font-weight:bold;
            }
            QPushButton:hover { background:#d84343; }
            QPushButton:pressed { background:#a01818; }
            QPushButton:disabled { background:#2a2a2a; color:#666; }
        """

    # ------ 数据 ------

    def load_character(self, char_id: str):
        c = self._store.get(char_id)
        if not c:
            self.clear()
            return
        self._current_id = char_id
        self._name_edit.setText(c.get("name", ""))
        gender = c.get("gender") or "男"
        idx = self._gender_combo.findText(gender)
        self._gender_combo.setCurrentIndex(idx if idx >= 0 else 0)
        role = c.get("role_type") or "配角"
        idx = self._role_combo.findText(role)
        self._role_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._age_edit.setText(c.get("age_range") or "")
        tags = c.get("tags")
        if isinstance(tags, list):
            tags = ", ".join(tags)
        self._tags_edit.setText(tags or "")
        for key, edit in self._text_edits.items():
            edit.setPlainText(c.get(key) or "")
        for key, combo in self._enum_combos.items():
            idx = combo.findData(c.get(key) or "")
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.set_enabled(True)

    def clear(self):
        self._current_id = None
        self._name_edit.clear()
        self._age_edit.clear()
        self._tags_edit.clear()
        for edit in self._text_edits.values():
            edit.clear()
        for combo in self._enum_combos.values():
            combo.setCurrentIndex(0)
        self.set_enabled(False)

    def set_enabled(self, enabled: bool):
        widgets = [
            self._name_edit, self._gender_combo, self._role_combo,
            self._age_edit, self._tags_edit,
            *self._text_edits.values(),
            *self._enum_combos.values(),
            self._save_btn, self._delete_btn,
        ]
        for w in widgets:
            w.setEnabled(enabled)

    # ------ 动作 ------

    def _collect_data(self) -> Dict:
        tags_raw = self._tags_edit.text().strip()
        if tags_raw:
            tags = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()]
        else:
            tags = []
        data = {
            "name": self._name_edit.text().strip(),
            "gender": self._gender_combo.currentText(),
            "role_type": self._role_combo.currentText(),
            "age_range": self._age_edit.text().strip(),
            "tags": tags,
        }
        for key, edit in self._text_edits.items():
            data[key] = edit.toPlainText().strip()
        for key, combo in self._enum_combos.items():
            data[key] = str(combo.currentData() or "")
        return data

    def _on_save(self):
        data = self._collect_data()
        if not data["name"]:
            QMessageBox.warning(self, "保存失败", "角色名不能为空")
            self._name_edit.setFocus()
            return
        success = False
        if self._current_id:
            success = self._store.update(self._current_id, data)
        else:
            new_id = self._store.add(data)
            if new_id:
                self._current_id = new_id
                success = True
        if not success:
            QMessageBox.warning(self, "保存失败",
                "角色数据写入磁盘失败，请检查磁盘空间和文件权限。\n数据可能未持久化保存。")
            return
        self.saved.emit()
        QMessageBox.information(self, "保存成功", f"角色「{data['name']}」已保存")

    def _on_delete(self):
        if not self._current_id:
            return
        name = self._name_edit.text() or "该角色"
        r = QMessageBox.question(self, "确认删除", f"确定删除「{name}」？此操作不可恢复。")
        if r != QMessageBox.StandardButton.Yes:
            return
        if self._store.remove(self._current_id):
            self.clear()
            self.saved.emit()
        else:
            QMessageBox.warning(self, "删除失败",
                "角色删除后数据写入磁盘失败，请检查磁盘空间和文件权限。")


# ---------------------------------------------------------------------------
# 主模块 UI —— 自研拾光导演台画布镶嵌（替换原列表式角色管理主界面）
# ---------------------------------------------------------------------------

WEBENGINE_AVAILABLE = False
WEBENGINE_IMPORT_ERROR = ""
QWebEngineView = object  # type: ignore
QWebEngineScript = object  # type: ignore
QWebEngineProfile = object  # type: ignore


def _probe_webengine() -> bool:
    """探测 QtWebEngine（可在 main 预加载后再调）。"""
    global WEBENGINE_AVAILABLE, WEBENGINE_IMPORT_ERROR
    global QWebEngineView, QWebEngineScript, QWebEngineProfile
    if WEBENGINE_AVAILABLE and QWebEngineView is not object:
        return True
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView as _View
        from PyQt6.QtWebEngineCore import QWebEngineScript as _Script
        from PyQt6.QtWebEngineCore import QWebEngineProfile as _Profile
        QWebEngineView = _View
        QWebEngineScript = _Script
        QWebEngineProfile = _Profile
        WEBENGINE_AVAILABLE = True
        WEBENGINE_IMPORT_ERROR = ""
        return True
    except Exception as e:
        WEBENGINE_AVAILABLE = False
        WEBENGINE_IMPORT_ERROR = f"{type(e).__name__}: {e}"
        logger.warning("QtWebEngine 不可用: %s", WEBENGINE_IMPORT_ERROR)
        return False


_probe_webengine()


class CharacterManagementModule(BaseModule):
    """角色 / AI 画布模块：镶嵌自研拾光导演台画布，生成物回流剪辑。"""

    module_id = "characters"
    module_name = "AI 画布"
    module_icon = "🎨"

    # 跨线程回主 UI：后台 CanvasWarmup / Agent 线程禁止用 QTimer.singleShot
    #（非归属线程调度时常不触发 → 服务已起但 WebView 永不 load、状态卡在「正在预热」）
    _ui_status = pyqtSignal(str)
    _ui_canvas_started = pyqtSignal(bool, str, str)  # ok, msg, url
    _ui_agent_done = pyqtSignal(bool, str, str, str)  # ok, msg, url, token

    def __init__(self):
        self._store = CharacterStore()
        self._web = None
        self._web_host = None  # 延后挂载 WebEngine 的容器 layout
        self._web_placeholder = None
        self._status_label = None
        self._interp_check = None
        self._char_combo = None
        self._library_panel = None
        self._bridge_started = False
        self._pending_canvas_url = ""
        self._canvas_load_retries = 0
        self._agent_btn = None
        self._agent_connected = False
        super().__init__()
        self._ui_status.connect(self._set_status)
        self._ui_canvas_started.connect(self._after_start)
        self._ui_agent_done.connect(self._on_agent_done_ui)

    def _setup_ui(self):
        # 再探一次：main 可能已在 QApplication 前预加载成功
        _probe_webengine()
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 顶栏（2026-10-19 · 用户授权解冻 stage3d-core）
        #
        # 改造动机（用户实测截图反馈）：「打开 AI 画布，顶上一排功能 + 一条网页链接，
        # 很烦；参考项目的顶栏只有 3 个元素。」
        #
        # 原则：**日常入口留一级，一次性系统动作收进「⋯ 更多」二级菜单**。
        #  一级保留：模块标题 / 挂到角色 / 补帧开关 / 更多
        #  二级收纳：启动画布 / 连接 Agent / 同步模型池 / 刷新 / 发送文件 / 角色库
        # 未动：bridge、WebEngine、端口、canvas-agent 运行时、GLB/骨骼逻辑。
        header = QHBoxLayout()
        title = QLabel(f"{self.module_icon} {self.module_name}")
        # V4.43.8（用户授权解冻 stage3d-core）：去掉内联 color:#fff —— 浅色主题下白字白底
        # 不可见。颜色交给全局 QSS 的 #titleLabel，只保留字号/字重。
        title.setObjectName("titleLabel")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        header.addWidget(title)

        hint = QLabel("生成 → 发送到剪辑 · 角色库挂资产")
        hint.setObjectName("hintLabel")
        hint.setStyleSheet("font-size:11px;margin-left:8px;")
        header.addWidget(hint)
        header.addStretch()

        # 形态切换（小白 / 专业）**刻意不在这里**：
        # 2026-10-19 用户纠正 —— 它属于「视图级」操作，必须和画布内的
        # 「画布 / 3D 导演台」并排（见 CanvasShell 的第二个 `.seg`），
        # 不放宿主顶栏「挂到角色」这边。真源是 store 的 editorTier，宿主不参与。

        self._char_combo = QComboBox()
        self._char_combo.setMinimumWidth(140)
        # V4.43.8（用户授权解冻 stage3d-core）：删掉内联硬编码深色框（#1a1a1a）。
        # 内联样式**优先于**全局 QSS，导致：① 深色下与工具栏背景几乎同色、文字发暗
        # （用户截图圈出的「看不清」）；② 浅色下变黑框、与浅色工具栏撞色。
        # 改走全局 QComboBox[theme] 样式，随主题自适应。**未动** GLB/骨骼/端口/预热时机。
        self._refresh_char_combo()
        header.addWidget(QLabel("挂到角色:"))
        header.addWidget(self._char_combo)

        self._interp_check = QCheckBox("补帧")
        # V4.43.8：去掉内联 color:#ccc，交给全局 QCheckBox[theme] 样式
        self._interp_check.setToolTip("入轨后线性补帧（帧差 + 线性混合，非神经网络）")
        header.addWidget(self._interp_check)

        # ── 「⋯ 更多」：收纳一次性系统动作（不常驻顶栏） ──
        more_btn = QToolButton()
        more_btn.setText("⋯")
        more_btn.setToolTip("更多：启动画布 / 连接 Agent / 同步模型池 / 刷新 / 发送文件 / 角色库")
        more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more_btn)

        self._act_start = menu.addAction("启动画布")
        self._act_start.triggered.connect(lambda _=False: self._on_start_canvas())

        self._act_agent = menu.addAction("连接 Agent（Codex/MCP 工具通道）")
        self._act_agent.setToolTip(
            "启动本机 canvas-agent（:17371），供 Codex/MCP 调画布。"
            "这是工具通道，与画布内嵌助手无关，也不影响 3D 导演台。"
        )
        self._act_agent.triggered.connect(lambda _=False: self._on_connect_agent())

        menu.addSeparator()
        self._act_sync = menu.addAction("同步模型池")
        # 2026-10-25（用户要求）：本地模型放进画布模块，不必切到「模型管理」模块。
        # 复用同一份 LocalModelsPanel（已下载 / 下载 / 打开目录），主模块页签保持不变。
        self._act_local_models = menu.addAction("本地模型（已下载 / 下载）")
        self._act_local_models.setToolTip(
            "列出本机已下载的生图/生视频模型（SD1.5/SDXL/SVD/Wan），可直接下载缺失项")
        self._act_local_models.triggered.connect(lambda _=False: self._on_open_local_models())
        self._act_sync.triggered.connect(lambda _=False: self._on_sync_models())
        self._act_reload = menu.addAction("刷新画布")
        self._act_reload.triggered.connect(lambda _=False: self._on_reload())
        self._act_send = menu.addAction("发送文件到剪辑")
        self._act_send.triggered.connect(lambda _=False: self._on_send_file())

        menu.addSeparator()
        self._act_copy_agent = menu.addAction("复制 Agent 地址")
        self._act_copy_agent.setToolTip(
            "调试用：把 canvas-agent 的地址复制到剪贴板；地址不常驻界面"
        )
        self._act_copy_agent.triggered.connect(lambda _=False: self._copy_agent_url())

        self._act_lib = menu.addAction("角色库")
        self._act_lib.setCheckable(True)
        self._act_lib.toggled.connect(self._toggle_library)

        more_btn.setMenu(menu)
        header.addWidget(more_btn)

        # 兼容旧引用：`self._agent_btn` 现在指向 QAction（只用于文案/禁用，
        # 不再有 setStyleSheet —— 见 `_apply_agent_btn_state` 的适配）。
        self._agent_btn = self._act_agent

        root.addLayout(header)

        # 状态条：**无消息时不占位**（2026-10-19 顶栏瘦身，用户授权解冻 stage3d-core）
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color:#79c0ff;font-size:11px;padding:2px 4px;")
        self._status_label.setVisible(False)
        root.addWidget(self._status_label)

        body = QHBoxLayout()
        body.setSpacing(6)

        # 可选左侧角色库（默认隐藏）
        self._library_panel = QFrame()
        self._library_panel.setVisible(False)
        self._library_panel.setFixedWidth(320)
        self._library_panel.setStyleSheet(
            "QFrame{background:#121212;border:1px solid #1e1e1e;border-radius:8px;}"
        )
        ll = QVBoxLayout(self._library_panel)
        ll.setContentsMargins(6, 6, 6, 6)
        lib_title = QLabel("角色库（资产挂载）")
        lib_title.setStyleSheet("color:#eee;font-weight:bold;")
        ll.addWidget(lib_title)
        self._editor = CharacterEditorPanel(self._store)
        self._editor.saved.connect(self._on_library_saved)
        ll.addWidget(self._editor, 1)
        # 简易列表
        self._lib_list = QListWidget()
        self._lib_list.setMaximumHeight(160)
        self._lib_list.setStyleSheet(
            "QListWidget{background:#0d0d0d;color:#eee;border:1px solid #222;}"
            "QListWidget::item:selected{background:#1e6bde;}"
        )
        self._lib_list.currentItemChanged.connect(self._on_lib_select)
        ll.addWidget(self._lib_list)
        add_char = QPushButton("新增角色")
        add_char.clicked.connect(self._on_new_char)
        ll.addWidget(add_char)
        body.addWidget(self._library_panel)
        self._refresh_lib_list()

        # 主画布：先出壳，WebEngine 延后到真正 load 时再创建（缩短进模块卡顿）
        canvas_wrap = QFrame()
        canvas_wrap.setStyleSheet("QFrame{background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;}")
        cw = QVBoxLayout(canvas_wrap)
        cw.setContentsMargins(0, 0, 0, 0)
        self._web_host = cw
        self._web = None

        if WEBENGINE_AVAILABLE:
            ph = QLabel("画布壳已就绪\n正在准备 WebEngine / 静态服务…")
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setStyleSheet("color:#64748b;font-size:13px;padding:32px;")
            ph.setWordWrap(True)
            self._web_placeholder = ph
            cw.addWidget(ph, 1)
        else:
            self._web_placeholder = None
            detail = WEBENGINE_IMPORT_ERROR or "未知原因"
            err = QLabel(
                "无法镶嵌画布（QtWebEngine 不可用）。\n"
                f"原因: {detail}\n\n"
                "请确认已安装: .venv312\\Scripts\\python.exe -m pip install PyQt6-WebEngine==6.10.0\n"
                "并完全退出后重新启动应用（须在创建窗口前加载 WebEngine）。\n\n"
                "临时方案：点「启动画布」会用系统浏览器打开"
            )
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            err.setStyleSheet("color:#f87171;padding:24px;")
            err.setWordWrap(True)
            cw.addWidget(err, 1)

        body.addWidget(canvas_wrap, 1)
        root.addLayout(body, 1)

        # 2026-10-19（用户授权解冻 stage3d-core）：删掉常驻底部的开发者长提示。
        #
        # 原实现是一条 `tip` QLabel：「「连接 Agent」拉起本机 :17371 工具通道
        # （Codex/MCP）… 可选 Codex: codex mcp add canvas-agent -- npx -y …」
        # —— 这是**给集成开发者的说明书**，不是给用户的状态。用户实测截图反馈
        # 「底下那条又长又技术的东西很烦」。同样的信息已收进「⋯ → 连接 Agent」
        # 的 tooltip 与「复制 Agent 地址」，不该在画布上常驻一整行。
        self._char_combo.currentIndexChanged.connect(lambda *_: self._sync_bridge_prefs())
        self._interp_check.toggled.connect(lambda *_: self._sync_bridge_prefs())

        # 延迟启动桥与探测画布；定期刷新 Agent 按钮状态
        # 注意：只在该模块真正可见时才预热 —— 原来这里无条件预热，导致没点进
        # 「AI 画布」也会在启动阶段白烧一份 桥 + 静态服务 + WebEngine + 前端包
        QTimer.singleShot(200, self._bootstrap_if_visible)
        self._agent_poll = QTimer(self)
        self._agent_poll.setInterval(10000)
        self._agent_poll.timeout.connect(self._poll_agent_btn_state)
        self._agent_poll.start()
        QTimer.singleShot(1500, self._poll_agent_btn_state)

    def _btn_style(self, bg: str) -> str:
        return (
            f"QPushButton{{background:{bg};color:#fff;border:none;border-radius:6px;"
            f"padding:7px 12px;font-size:11px;font-weight:bold;}}"
            f"QPushButton:hover{{opacity:0.9;}}"
            f"QPushButton:checked{{background:#1e6bde;}}"
        )

    def _sync_bridge_prefs(self):
        try:
            from app.core.canvas_bridge import set_bridge_prefs
        except ImportError:
            from core.canvas_bridge import set_bridge_prefs  # type: ignore
        char_id = self._selected_character_id()
        char_name = self._selected_character_name()
        if char_name.startswith("("):
            char_id, char_name = "", ""
        char_prompt = ""
        if char_id:
            try:
                from app.core.canvas_bridge import build_character_prompt
            except ImportError:
                from core.canvas_bridge import build_character_prompt  # type: ignore
            char = self._store.get(char_id) if self._store else None
            char_prompt = build_character_prompt(char if isinstance(char, dict) else None)
        interp = bool(self._interp_check.isChecked()) if self._interp_check else False
        active = ""
        active_label = ""
        try:
            from app.modules.lego.model_config import (
                PROVIDERS,
                ensure_active_provider_sensible,
                load_active_provider,
            )
            ensure_active_provider_sensible()
            active = load_active_provider() or ""
            active_label = (PROVIDERS.get(active) or {}).get("name") or active
        except Exception:
            pass
        set_bridge_prefs(
            character_id=char_id,
            character_name=char_name,
            character_prompt=char_prompt,
            enable_interpolation=interp,
            active_provider=active,
            active_provider_label=active_label,
        )
        # 刷新画布面板副标题（若 inject 已加载）
        self._run_js(
            "window.__shiguangRefreshPrefsSubtitle && window.__shiguangRefreshPrefsSubtitle();"
        )

    def _run_js(self, script: str):
        if self._web is None or not WEBENGINE_AVAILABLE:
            return
        try:
            self._web.page().runJavaScript(script)
        except Exception as e:
            logger.debug("runJavaScript failed: %s", e)

    def _apply_agent_btn_state(self, connected: bool, url: str = ""):
        """「⋯ 更多 → 连接 Agent」菜单项反映是否已监听（工具通道，非 3D 角色）。

        2026-10-19（用户授权解冻 stage3d-core）：按钮已收进二级菜单，控件类型从
        QPushButton 改为 QAction —— **QAction 没有 setStyleSheet**，且地址不再写进
        文案（只保留一句可读状态）；完整 URL 只由「复制 Agent 地址」显式提供。
        """
        self._agent_connected = bool(connected)
        act = self._agent_btn
        if act is None:
            return
        if connected:
            act.setText("Agent 已连接（工具通道）")
            act.setToolTip(
                "canvas-agent 已就绪，供 Codex/MCP 调用画布。\n"
                "需要地址时用「复制 Agent 地址」。"
            )
        else:
            act.setText("连接 Agent（Codex/MCP 工具通道）")
            act.setToolTip(
                "启动本机 canvas-agent（:17371），供 Codex/MCP 调画布。"
                "这是工具通道，与画布内嵌助手无关，也不影响 3D 导演台。"
            )

    def _poll_agent_btn_state(self):
        try:
            from app.core.canvas_agent_runtime import get_canvas_agent_runtime
        except ImportError:
            from core.canvas_agent_runtime import get_canvas_agent_runtime  # type: ignore
        try:
            rt = get_canvas_agent_runtime()
            on = bool(rt.is_listening() and rt.token)
            self._apply_agent_btn_state(on, rt.url if on else "")
        except Exception:
            pass

    def _inject_agent_credentials(self, url: str, token: str, reload_page: bool = False):
        u = (url or "").replace("\\", "\\\\").replace("'", "\\'")
        t = (token or "").replace("\\", "\\\\").replace("'", "\\'")
        js = (
            f"window.__shiguangApplyAgent && window.__shiguangApplyAgent('{u}','{t}',"
            f"{'true' if reload_page else 'false'});"
        )
        self._run_js(js)

    def _on_connect_agent(self):
        self._ensure_bridge()
        self._set_status("正在启动 canvas-agent（:17371，工具通道，非 3D 角色）…")
        if self._agent_btn is not None:
            self._agent_btn.setEnabled(False)
            self._agent_btn.setText("连接中…")

        def work():
            try:
                from app.core.canvas_agent_runtime import get_canvas_agent_runtime
            except ImportError:
                from core.canvas_agent_runtime import get_canvas_agent_runtime  # type: ignore

            rt = get_canvas_agent_runtime()

            def progress(msg: str):
                self._ui_status.emit(msg)

            ok, msg = rt.ensure_started(wait_seconds=60.0, on_progress=progress)
            self._ui_agent_done.emit(ok, msg, rt.url if ok else "", rt.token or "")

        threading.Thread(target=work, daemon=True, name="CanvasAgentStart").start()

    def _on_agent_done_ui(self, ok: bool, msg: str, url: str, token: str):
        """主线程：Agent 启动结果。"""
        if self._agent_btn is not None:
            self._agent_btn.setEnabled(True)
        self._set_status(msg if ok else f"Agent 失败：{msg}")
        if ok and token:
            self._apply_agent_btn_state(True, url)
            self._inject_agent_credentials(url, token, reload_page=False)
            QTimer.singleShot(
                800, lambda: self._inject_agent_credentials(url, token, False)
            )
            # 向 WebView 推送状态文案，顶栏 chip 会轮询到 listening
            safe = (msg or "Agent 已连接").replace("\\", "\\\\").replace("'", "\\'")
            self._run_js(
                f"window.__shiguangSetStatus && window.__shiguangSetStatus('{safe}');"
            )
        else:
            self._apply_agent_btn_state(False)
            if not ok:
                # canvas-agent 是外部 Node MCP 工具通道，自研画布 Agent 不受影响
                # 失败时只在状态栏提示，不弹 QMessageBox 烦用户
                short = (msg or "").split("\n")[0][:80]
                self._set_status(f"Agent 未连接（可忽略）: {short}")
                logger.info("canvas-agent 连接失败（非致命）: %s", msg[:200])

    def _on_open_local_models(self):
        """打开「本地模型」弹窗（2026-10-25）。

        为什么放在画布模块：用户要在画布这边直接看/拉本地权重，不想切模块找入口。
        内容与「模型管理 → 本地模型」页签同源（LocalModelsPanel），不另写一份。
        """
        dlg = getattr(self, "_local_models_dlg", None)
        if dlg is not None:
            dlg.raise_()
            dlg.activateWindow()
            return
        try:
            from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

            from .local_models_panel import LocalModelsPanel
        except Exception as e:
            self._set_status(f"本地模型面板不可用：{e}")
            return
        box = QDialog(self)
        box.setWindowTitle("本地模型（已下载 / 下载）")
        box.resize(1000, 640)
        lay = QVBoxLayout(box)
        lay.addWidget(LocalModelsPanel(box))
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=box)
        btn_close = btns.button(QDialogButtonBox.StandardButton.Close)
        if btn_close is not None:
            btn_close.clicked.connect(box.close)
        lay.addWidget(btns)
        box.finished.connect(lambda *_: setattr(self, "_local_models_dlg", None))
        self._local_models_dlg = box
        box.show()

    def _on_sync_models(self):
        self._sync_models_to_canvas(force_reload=True)

    def _on_provider_activated_sync(self, _event=None):
        """模型管理保存/激活 Key 后静默同步模型池（不切换页签、不整页刷新）。"""
        if not self._web:
            return
        self._sync_models_to_canvas(force_reload=False)

    def _sync_models_to_canvas(self, *, force_reload: bool):
        self._ensure_bridge()
        self._sync_bridge_prefs()
        label = "正在同步模型池到画布…" if force_reload else "模型 Key 已更新，同步模型池…"
        self._set_status(label)
        flag = "true" if force_reload else "false"
        self._run_js(
            f"window.__shiguangSyncModels && window.__shiguangSyncModels({flag});"
        )
        try:
            from app.modules.lego.model_config import load_active_provider, PROVIDERS
            ap = load_active_provider() or ""
            name = (PROVIDERS.get(ap) or {}).get("name") or ap or "未激活"
            self._set_status(f"已同步模型池 · 当前激活 {name}")
        except Exception:
            self._set_status("已同步模型池到画布")

    def _ensure_web_view(self) -> bool:
        """首次需要加载页面时再创建 QWebEngineView（进模块只出壳）。"""
        if os.environ.get("SHIGUANG_NO_WEBENGINE") == "1":
            # 2026-10-25（授权解冻）：本机 PyQt6 6.10.2 + WebEngine 6.10.0 混装 ⇒ 渲染必崩。
            # 由 main_qt6 子进程预检置位；这里短路返回 False，_load_canvas 会落到
            # webbrowser.open(url)（画布在系统浏览器里照常可用，不再是黑屏）。
            self._set_status("本机 QtWebEngine 不可用 ⇒ 正在用系统浏览器打开画布…")
            logger.warning("QtWebEngine disabled by probe ⇒ open canvas in system browser")
            return False
        if self._web is not None:
            return True
        if not WEBENGINE_AVAILABLE:
            return False
        host = self._web_host
        if host is None:
            return False
        t0 = time.perf_counter()
        self._web = QWebEngineView()
        # 2026-10-19（解冻 stage3d-core）：把 WebView 的 JS console 镜像到 Python 日志。
        # 背景：3D 侧异常（GLB 归一化、骨骼矩阵、渲染尺寸）只体现在前端 console，
        # 宿主侧完全看不见，之前排查只能靠用户截图猜。这里只镜像 Warning/Error 级
        # 与带 Stage3D / RiggedHumanoid 前缀的消息，避免普通 log 刷屏；失败静默降级
        # （日志能力不得影响画布加载本身）。
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage as _QEP

            class _ConsoleMirrorPage(_QEP):
                def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
                    try:
                        m = str(message or "")[:600]
                        if not m:
                            return
                        # 注意：不要对 level 做 int() —— PyQt6 的 Qt 枚举可能抛 TypeError，
                        # 一抛就被本函数的 except 吞掉，导致「镜像装了但一条日志都没有」
                        # （2026-10-19 实测踩过）。改用字符串判断，任何版本都安全。
                        lv = str(level)
                        if (
                            "Warn" in lv
                            or "Error" in lv
                            or "Stage3D" in m
                            or "RiggedHumanoid" in m
                        ):
                            logger.info(
                                "[webview] %s:%s %s",
                                str(source).rsplit("/", 1)[-1], line, m,
                            )
                    except Exception:
                        pass

            self._web.setPage(_ConsoleMirrorPage(self._web))
        except Exception as e:
            logger.debug("console mirror page 安装失败: %s", e)
        self._install_inject_script()
        try:
            self._web.loadStarted.connect(self._on_web_load_started)
            self._web.loadFinished.connect(self._on_web_load_finished)
            # 渲染进程/GPU 子进程崩溃时兜底：黑屏但服务仍在，靠普通 load() 不一定能救回
            self._web.page().renderProcessTerminated.connect(self._on_render_process_terminated)
        except Exception as e:
            logger.debug("web load signals connect failed: %s", e)
        if self._web_placeholder is not None:
            host.removeWidget(self._web_placeholder)
            self._web_placeholder.deleteLater()
            self._web_placeholder = None
        host.addWidget(self._web, 1)
        logger.info(
            "canvas WebEngineView created in %.0fms",
            (time.perf_counter() - t0) * 1000,
        )
        return True

    def _bootstrap_if_visible(self):
        """延迟预热：只有模块真正可见时才启动画布。

        setup_ui 之后 200ms 触发。若此时「AI 画布」不是当前页（QTabWidget 未显示
        本页），则什么都不做，等 showEvent / on_activated 再预热。
        """
        if getattr(self, "_booted", False):
            return
        try:
            visible = bool(self.isVisible())
        except Exception:
            visible = True  # 判断失败时按可见处理，避免画布永不启动
        if visible:
            self._bootstrap()

    def showEvent(self, event):  # noqa: N802 (Qt 命名)
        """切到本模块时预热画布（QTabWidget 切页会触发 showEvent）。

        不依赖宿主是否调用 on_activated —— 实测宿主没有调用该生命周期钩子。
        """
        super().showEvent(event)
        if getattr(self, "_booted", False):
            return
        QTimer.singleShot(0, self._bootstrap)

    def _bootstrap(self):
        # 幂等：预热只做一次，重复进入模块不重复起桥 / 建 WebEngine
        if getattr(self, "_booted", False):
            return
        self._booted = True
        _t_all = time.perf_counter()
        _t0 = time.perf_counter()
        self._ensure_bridge()
        _ms_bridge = (time.perf_counter() - _t0) * 1000
        _t0 = time.perf_counter()
        self._sync_bridge_prefs()
        _ms_prefs = (time.perf_counter() - _t0) * 1000
        try:
            from app.core.canvas_runtime import get_canvas_runtime
        except ImportError:
            from core.canvas_runtime import get_canvas_runtime  # type: ignore
        _t0 = time.perf_counter()
        rt = get_canvas_runtime()
        _ready = rt.is_ready()
        _ms_probe = (time.perf_counter() - _t0) * 1000
        logger.info(
            "画布预热计时 bridge=%.0fms prefs=%.0fms probe=%.0fms ready=%s total=%.0fms",
            _ms_bridge,
            _ms_prefs,
            _ms_probe,
            _ready,
            (time.perf_counter() - _t_all) * 1000,
        )
        if _ready:
            self._load_canvas(rt.url)
            self._set_status(f"已连接 {rt.url}")
            QTimer.singleShot(800, self._maybe_inject_existing_agent)
            return
        eng_label = "拾光导演台（自研）"
        self._set_status(f"正在预热 {eng_label}（有 dist 则秒开）…")

        def progress(msg: str):
            self._ui_status.emit(msg)

        rt.warmup_async(
            on_progress=progress,
            on_done=lambda ok, msg: self._ui_canvas_started.emit(
                ok, msg, rt.url if ok else ""
            ),
        )

    def _maybe_inject_existing_agent(self):
        """画布就绪后：仅当 Agent 已在运行时注入凭证；不自动拉起 npx（太慢）。

        需要 Agent 时请点顶栏「连接 Agent」。
        """
        try:
            from app.core.canvas_agent_runtime import get_canvas_agent_runtime
        except ImportError:
            from core.canvas_agent_runtime import get_canvas_agent_runtime  # type: ignore
        rt = get_canvas_agent_runtime()
        if rt.is_listening() and rt.token:
            self._apply_agent_btn_state(True, rt.url)
            self._inject_agent_credentials(rt.url, rt.token, False)
            QTimer.singleShot(
                1200, lambda: self._inject_agent_credentials(rt.url, rt.token, False)
            )
            # 不覆盖 loadFinished 的「画布已就绪」文案（若页面还在加载则稍后再写）
            return
        self._apply_agent_btn_state(False)
        # 不自动 warmup agent —— 那是「预热太慢」的主因之一；需 Agent 时点「连接 Agent」
        return

    def _ensure_bridge(self):
        if self._bridge_started:
            return
        try:
            from app.core.canvas_bridge import get_canvas_bridge
        except ImportError:
            from core.canvas_bridge import get_canvas_bridge  # type: ignore
        ok = get_canvas_bridge().start()
        self._bridge_started = ok
        if ok:
            logger.info("canvas bridge ready")

    def _install_inject_script(self):
        if not WEBENGINE_AVAILABLE or self._web is None:
            return
        try:
            js = """
            (function(){
              function load(){
                if (window.__SHIGUANG_BRIDGE_INJECTED__) return;
                var s=document.createElement('script');
                s.src='http://127.0.0.1:18765/inject.js?t='+Date.now();
                s.onerror=function(){};
                document.documentElement.appendChild(s);
              }
              if (document.readyState==='loading') document.addEventListener('DOMContentLoaded', load);
              else load();
              setTimeout(load, 1500);
            })();
            """
            script = QWebEngineScript()
            script.setName("shiguang-bridge-loader")
            script.setSourceCode(js)
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setRunsOnSubFrames(True)
            self._web.page().scripts().insert(script)
        except Exception as e:
            logger.warning("inject script failed: %s", e)

    def _load_canvas(self, url: str):
        # 附带 bridge session token，供导演台 /host/* 鉴权
        try:
            from app.core.canvas_bridge import session_token
            tok = session_token()
            if tok and "token=" not in url:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}token={tok}"
        except Exception:
            logger.debug("canvas session token attach failed", exc_info=True)
        self._pending_canvas_url = url
        if not self._ensure_web_view():
            import webbrowser
            webbrowser.open(url)
            return
        from PyQt6.QtCore import QUrl
        logger.info("loading canvas url=%s", url)
        self._web.load(QUrl(url))

    def _on_web_load_started(self):
        if self._pending_canvas_url:
            self._set_status(f"正在加载画布页面… {self._pending_canvas_url}")

    def _on_web_load_finished(self, ok: bool):
        url = self._pending_canvas_url or ""
        if ok:
            self._canvas_load_retries = 0
            self._set_status(f"画布已就绪 {url}" if url else "画布已就绪")
            logger.info("canvas page loadFinished ok url=%s", url)
            return
        # 2026-10-25（用户授权解冻 stage3d-core）：页面打不开最常见原因是
        # **画布静态服务没起**（3011 无监听）——此前只提示「点刷新/启动画布」，
        # 用户看到的就是白屏 + 一句报错。现在先探 is_ready()：不在就先自动启动，
        # 成功后经 _after_start 自动重新加载；真起不来才把原因写状态栏。
        try:
            from app.core.canvas_runtime import get_canvas_runtime
        except ImportError:
            from core.canvas_runtime import get_canvas_runtime  # type: ignore
        try:
            _rt = get_canvas_runtime()
        except Exception:
            _rt = None
        if _rt is not None and not _rt.is_ready():
            self._canvas_load_retries = 0
            logger.warning("canvas service not ready ⇒ auto start then reload (url=%s)", url)
            self._set_status("画布服务未启动，正在自动启动…")
            self._on_start_canvas()
            # 自动路径不弹模态框（失败原因已写状态栏，用户可再点「启动画布」）
            self._manual_canvas_start = False
            return
        retries = int(getattr(self, "_canvas_load_retries", 0) or 0)
        if retries < 3 and url and self._web is not None:
            self._canvas_load_retries = retries + 1
            self._set_status(f"画布加载失败，正在重试（{retries + 1}/3）… {url}")
            logger.warning("canvas page loadFinished FAIL, retry %d/3 url=%s",
                           retries + 1, url)
            QTimer.singleShot(600 * (retries + 1), lambda u=url: self._retry_load_canvas(u))
            return
        self._set_status(f"画布页面加载失败（请点「刷新」或「启动画布」） {url}")
        logger.warning("canvas page loadFinished FAIL url=%s", url)

    def _on_render_process_terminated(self, status, exit_code):
        """画布渲染进程 / GPU 子进程被杀时的兜底重载。

        点击节点后整页黑屏、但「画布已连接」仍在，通常是 Chromium 子进程崩溃；
        对崩溃类状态做带退避的自动 reload，普通/导航类状态忽略。
        """
        # 崩溃类终止状态（Crashed=2 / Killed=3），避免普通导航也误重载
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage
            crashed = status in (
                QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus,
                QWebEnginePage.RenderProcessTerminationStatus.KilledTerminationStatus,
            )
        except Exception:
            crashed = int(status or 0) > 0
        if not crashed:
            return

        logger.warning(
            "canvas render process terminated status=%s exit=%s, preparing auto-reload",
            status, exit_code,
        )
        url = getattr(self, "_pending_canvas_url", "") or ""
        if not url or self._web is None:
            self._set_status("画布渲染进程异常，请点「刷新」重载")
            return

        # 60s 窗口内连续崩溃 ≥3 次则停止自动重载，防止崩溃循环拖死应用
        now = time.time()
        window_start = float(getattr(self, "_render_crash_window_start", 0.0) or 0.0)
        crash_count = int(getattr(self, "_render_crash_count", 0) or 0)
        if now - window_start > 60.0:
            window_start = now
            crash_count = 0
        if crash_count >= 3:
            self._set_status("画布渲染进程反复崩溃，已停止自动重载（请重启应用）")
            logger.error("canvas render process kept crashing, auto-reload stopped")
            return
        self._render_crash_window_start = window_start
        self._render_crash_count = crash_count + 1

        delay = 800 * (2 ** crash_count)  # 0.8s / 1.6s / 3.2s 逐次退避
        logger.info("auto-reloading canvas in %dms (attempt %d)", delay, crash_count + 1)
        QTimer.singleShot(delay, lambda u=url: self._retry_load_canvas(u))

    def _retry_load_canvas(self, url: str):
        if not url or self._web is None:
            return
        if url != getattr(self, "_pending_canvas_url", ""):
            return
        from PyQt6.QtCore import QUrl
        logger.info("retrying canvas url=%s", url)
        self._web.load(QUrl(url))

    def _set_status(self, text: str):
        """状态栏文案（面向用户，**绝不显示 URL / token**）。

        2026-10-19（用户授权解冻 stage3d-core）：canvas-agent 启动成功时后端返回的
        消息带 `http://127.0.0.1:17371?token=…`，原样 setText 会让地址常驻顶栏
        （用户实测「顶上总有一条网页链接，很烦」）。这里统一清洗；空文案直接隐藏
        状态条，不占位。需要地址时走「⋯ → 复制 Agent 地址」显式取。
        """
        if self._status_label is None:
            return
        cleaned = _strip_urls(text or "")
        if cleaned:
            self._status_label.setText(cleaned)
            self._status_label.setVisible(True)
        else:
            self._status_label.clear()
            self._status_label.setVisible(False)

    def _copy_agent_url(self):
        """把 canvas-agent 地址复制到剪贴板（调试用，不常驻界面）。"""
        try:
            from app.core.canvas_agent_runtime import get_canvas_agent_runtime
        except ImportError:
            from core.canvas_agent_runtime import get_canvas_agent_runtime  # type: ignore
        try:
            rt = get_canvas_agent_runtime()
            url = (rt.url or "").strip()
        except Exception as e:
            logger.debug("读取 canvas-agent 地址失败: %s", e)
            url = ""
        if not url:
            self._set_status("Agent 未连接，没有可复制的地址")
            return
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(url)
            self._set_status("Agent 地址已复制到剪贴板")
        except Exception as e:
            logger.warning("复制 Agent 地址失败: %s", e)
            self._set_status("复制 Agent 地址失败")

    def _on_start_canvas(self):
        self._ensure_bridge()
        self._manual_canvas_start = True
        try:
            from app.core.canvas_runtime import active_canvas_engine
        except ImportError:
            from core.canvas_runtime import active_canvas_engine  # type: ignore
        eng_label = "拾光导演台"
        self._set_status(f"正在启动 {eng_label}…")
        try:
            from app.core.canvas_runtime import get_canvas_runtime
        except ImportError:
            from core.canvas_runtime import get_canvas_runtime  # type: ignore

        def work():
            rt = get_canvas_runtime()
            # engine=tauri 时把 Python 后端 session token 注入 canvas_runtime，
            # 由 _start_tauri_process 通过环境变量传给 Tauri 子进程。
            # engine=shiguang 时此调用不影响原 inject.js 注入流程。
            try:
                from app.core.canvas_bridge import session_token
                rt.set_bridge_credentials(session_token())
            except Exception as e:
                logger.warning("set_bridge_credentials failed: %s", e)

            def progress(msg: str):
                self._ui_status.emit(msg)

            ok, msg = rt.ensure_started(wait_seconds=45.0, on_progress=progress)
            self._ui_canvas_started.emit(ok, msg, rt.url if ok else "")

        threading.Thread(target=work, daemon=True, name="CanvasManualStart").start()

    def _after_start(self, ok: bool, msg: str, url: str):
        self._set_status(msg)
        if ok and url:
            self._load_canvas(url)
            QTimer.singleShot(800, self._maybe_inject_existing_agent)
            return
        manual = bool(getattr(self, "_manual_canvas_start", False))
        self._manual_canvas_start = False
        if manual:
            QMessageBox.warning(self, "启动画布", msg)

    def _on_reload(self):
        self._ensure_bridge()
        try:
            from app.core.canvas_runtime import get_canvas_runtime
        except ImportError:
            from core.canvas_runtime import get_canvas_runtime  # type: ignore
        rt = get_canvas_runtime()
        if rt.is_ready():
            self._canvas_load_retries = 0
            self._load_canvas(rt.url)
            self._set_status(f"已刷新 {rt.url}")
        else:
            self._set_status("画布未运行，请先「启动画布」")

    def _selected_character_id(self) -> str:
        if self._char_combo is None:
            return ""
        return str(self._char_combo.currentData() or "")

    def _selected_character_name(self) -> str:
        if self._char_combo is None:
            return ""
        return self._char_combo.currentText().strip()
        # skip "(不挂角色)"

    def _on_send_file(self):
        self._ensure_bridge()
        self._sync_bridge_prefs()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择画布生成的图片或视频",
            "",
            "媒体 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.mkv *.webm *.avi);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            from app.core.canvas_bridge import ingest_local_file
        except ImportError:
            from core.canvas_bridge import ingest_local_file  # type: ignore

        char_id = self._selected_character_id()
        char_name = self._selected_character_name()
        if char_name.startswith("("):
            char_id, char_name = "", ""
        interp = bool(self._interp_check.isChecked()) if self._interp_check else False
        res = ingest_local_file(
            path,
            title=os.path.basename(path),
            character_id=char_id,
            character_name=char_name,
            send_to_editor=True,
            enable_interpolation=interp,
        )
        if res.get("success"):
            self._set_status(res.get("message") or "已发送")
            QMessageBox.information(self, "已发送到剪辑", res.get("message") or "成功")
            self._refresh_char_combo()
        else:
            QMessageBox.warning(self, "发送失败", res.get("message") or "未知错误")

    def _toggle_library(self, on: bool):
        if self._library_panel is not None:
            self._library_panel.setVisible(bool(on))
            if on:
                self._refresh_lib_list()

    def _refresh_char_combo(self):
        if self._char_combo is None:
            return
        cur = self._char_combo.currentData()
        self._char_combo.blockSignals(True)
        self._char_combo.clear()
        self._char_combo.addItem("(不挂角色)", "")
        for c in self._store.all():
            self._char_combo.addItem(c.get("name") or c.get("id") or "未命名", c.get("id"))
        if cur:
            idx = self._char_combo.findData(cur)
            if idx >= 0:
                self._char_combo.setCurrentIndex(idx)
        self._char_combo.blockSignals(False)

    def _refresh_lib_list(self):
        if not hasattr(self, "_lib_list") or self._lib_list is None:
            return
        self._lib_list.clear()
        for c in self._store.all():
            name = c.get("name") or "未命名"
            n_assets = len(c.get("generated_assets") or [])
            item = QListWidgetItem(f"{name}  ({n_assets} 资产)")
            item.setData(Qt.ItemDataRole.UserRole, c.get("id"))
            self._lib_list.addItem(item)

    def _on_lib_select(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            return
        char_id = current.data(Qt.ItemDataRole.UserRole)
        if char_id:
            self._editor.load_character(char_id)
            idx = self._char_combo.findData(char_id) if self._char_combo else -1
            if idx >= 0:
                self._char_combo.setCurrentIndex(idx)

    def _on_new_char(self):
        self._editor.clear()
        self._editor.set_enabled(True)
        self._editor._name_edit.setFocus()

    def _on_library_saved(self):
        self._refresh_lib_list()
        self._refresh_char_combo()

    def on_activated(self):
        self._bootstrap()
        self._refresh_char_combo()

    def on_deactivated(self):
        pass
