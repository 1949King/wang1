"""
角色管理模块 (Character Management Module)
=========================================

与剪辑模块的「角色面板」不同：
- 剪辑模块的角色面板 = 视频级的临时角色偏好（作用于当前剪辑）
- 本模块 = 全局的角色库（跨项目复用的角色资产，如短剧人物画像）

设计：
- 角色 = 可复用资产（人物画像 + 代表视频/台词 + 识别信息）
- 以 JSON 持久化到用户目录 ~/.video_editor_cache/characters/
- 支持：新增 / 编辑 / 删除 / 导入角色画像 / 从视频提取
"""

import json
import os
import datetime
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.characters")

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget,
    QListWidgetItem, QComboBox, QFileDialog, QMessageBox,
    QFrame, QGroupBox, QScrollArea, QInputDialog, QColorDialog,
    QTabWidget, QProgressBar, QSizePolicy,
)

from .base_module import BaseModule


# ---------------------------------------------------------------------------
# 角色数据模型
# ---------------------------------------------------------------------------

CHARACTER_FIELD_SCHEMA = [
    ("name",         "角色名",       "string",  True),
    ("gender",       "性别",         "enum",    False),  # enum: 男/女/其他
    ("age_range",    "年龄段",       "string",  False),  # 如: 青年 / 中年
    ("role_type",    "角色类型",     "enum",    False),  # enum: 主角 / 配角 / 反派
    ("tags",         "标签",         "list",    False),  # 逗号分隔
    ("appearance",   "外貌特征",     "text",    False),  # 衣着、发型、体态
    ("personality",  "性格特征",     "text",    False),  # 性格描述
    ("representative_line", "代表台词", "text",  False),
    ("background",   "人物背景",     "text",    False),
    ("notes",        "备注",         "text",    False),
]

GENDER_OPTIONS = ["男", "女", "其他"]
ROLE_OPTIONS = ["主角", "配角", "反派", "路人"]


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
            # 保存失败但内存中已添加，回滚并记录警告
            self._characters.pop()
            logger.warning(f"新增角色保存失败，已回滚内存变更: {new_id}")
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

        # 长文本字段
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        form_inner = QWidget()
        form_layout = QVBoxLayout(form_inner)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)

        self._appearance_edit = self._mk_text_edit("外貌特征（衣着、发型、体态等）")
        self._personality_edit = self._mk_text_edit("性格特征")
        self._line_edit_long = self._mk_text_edit("代表台词")
        self._bg_edit = self._mk_text_edit("人物背景")
        self._notes_edit = self._mk_text_edit("备注")

        for label_text, edit in [
            ("外貌特征", self._appearance_edit),
            ("性格特征", self._personality_edit),
            ("代表台词", self._line_edit_long),
            ("人物背景", self._bg_edit),
            ("备注", self._notes_edit),
        ]:
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color:#bbb;font-size:12px;font-weight:bold;")
            form_layout.addWidget(lbl)
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

    def _mk_text_edit(self, placeholder: str) -> QTextEdit:
        te = QTextEdit()
        te.setPlaceholderText(placeholder)
        te.setMaximumHeight(120)
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
        self._appearance_edit.setPlainText(c.get("appearance") or "")
        self._personality_edit.setPlainText(c.get("personality") or "")
        self._line_edit_long.setPlainText(c.get("representative_line") or "")
        self._bg_edit.setPlainText(c.get("background") or "")
        self._notes_edit.setPlainText(c.get("notes") or "")
        self.set_enabled(True)

    def clear(self):
        self._current_id = None
        self._name_edit.clear()
        self._age_edit.clear()
        self._tags_edit.clear()
        self._appearance_edit.clear()
        self._personality_edit.clear()
        self._line_edit_long.clear()
        self._bg_edit.clear()
        self._notes_edit.clear()
        self.set_enabled(False)

    def set_enabled(self, enabled: bool):
        for w in [
            self._name_edit, self._gender_combo, self._role_combo,
            self._age_edit, self._tags_edit, self._appearance_edit,
            self._personality_edit, self._line_edit_long,
            self._bg_edit, self._notes_edit, self._save_btn, self._delete_btn,
        ]:
            w.setEnabled(enabled)

    # ------ 动作 ------

    def _collect_data(self) -> Dict:
        tags_raw = self._tags_edit.text().strip()
        if tags_raw:
            tags = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()]
        else:
            tags = []
        return {
            "name": self._name_edit.text().strip(),
            "gender": self._gender_combo.currentText(),
            "role_type": self._role_combo.currentText(),
            "age_range": self._age_edit.text().strip(),
            "tags": tags,
            "appearance": self._appearance_edit.toPlainText().strip(),
            "personality": self._personality_edit.toPlainText().strip(),
            "representative_line": self._line_edit_long.toPlainText().strip(),
            "background": self._bg_edit.toPlainText().strip(),
            "notes": self._notes_edit.toPlainText().strip(),
        }

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
# 主模块 UI
# ---------------------------------------------------------------------------

class CharacterManagementModule(BaseModule):
    """角色管理模块：全局角色库，与剪辑模块中的临时角色偏好互补"""

    module_id = "characters"
    module_name = "角色管理"
    module_icon = "👥"

    def _setup_ui(self):
        self._store = CharacterStore()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 顶部标题 + 统计 + 操作
        header = QHBoxLayout()
        title = QLabel("👥 角色管理")
        title.setStyleSheet("font-size:20px;font-weight:bold;color:#fff;")
        header.addWidget(title)

        self._count_label = QLabel(self._count_text(0))
        self._count_label.setStyleSheet("color:#888;font-size:12px;")
        header.addSpacing(12)
        header.addWidget(self._count_label)
        header.addStretch()

        add_btn = QPushButton("➕ 新增")
        add_btn.setStyleSheet(self._btn_style("#1e6bde"))
        add_btn.clicked.connect(self._on_new)
        header.addWidget(add_btn)

        import_btn = QPushButton("📥 导入")
        import_btn.setStyleSheet(self._btn_style("#2a2a2a"))
        import_btn.clicked.connect(self._on_import)
        header.addWidget(import_btn)

        export_btn = QPushButton("📤 导出")
        export_btn.setStyleSheet(self._btn_style("#2a2a2a"))
        export_btn.clicked.connect(self._on_export)
        header.addWidget(export_btn)

        root.addLayout(header)

        # 主内容：左侧角色列表 + 右侧编辑面板
        body = QHBoxLayout()
        body.setSpacing(10)

        # -- 左侧 --
        left = QFrame()
        left.setStyleSheet("QFrame{background:#121212;border:1px solid #1e1e1e;border-radius:8px;}")
        left.setFixedWidth(280)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 8, 8)
        ll.setSpacing(6)

        search = QLineEdit()
        search.setPlaceholderText("🔍 搜索角色名 / 标签")
        search.setStyleSheet(self._line_style())
        search.textChanged.connect(self._on_filter)
        ll.addWidget(search)

        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget {
                background:#121212; color:#eee; border:none; font-size:13px;
            }
            QListWidget::item { padding:8px 10px; border-radius:4px; }
            QListWidget::item:selected { background:#1e6bde; color:#fff; }
            QListWidget::item:hover { background:#1a1a1a; }
        """)
        self._list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self._list, 1)

        self._empty_label = QLabel("还没有角色，点击右上角「➕ 新增」开始创建")
        self._empty_label.setStyleSheet("color:#666;font-size:12px;padding:16px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        ll.addWidget(self._empty_label)

        body.addWidget(left)

        # -- 右侧 --
        self._editor = CharacterEditorPanel(self._store)
        self._editor.saved.connect(self._refresh_list)
        body.addWidget(self._editor, 1)

        root.addLayout(body, 1)

        # 底部提示
        tip = QLabel("💡 提示：这里维护的是全局角色库。剪辑模块中的「角色面板」作用于当前视频的角色偏好。")
        tip.setStyleSheet("color:#666;font-size:11px;padding:4px;")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # 初次加载
        self._refresh_list()

    # ------ helpers ------

    @staticmethod
    def _btn_style(bg: str) -> str:
        return f"""
            QPushButton {{
                background:{bg}; color:#fff; border:none; border-radius:6px;
                padding:7px 16px; font-size:11px; font-weight:bold;
            }}
            QPushButton:hover {{ opacity:0.9; }}
        """

    @staticmethod
    def _line_style() -> str:
        return """
            QLineEdit {
                background:#1a1a1a; color:#eee; border:1px solid #2a2a2a;
                border-radius:6px; padding:8px; font-size:12px;
            }
            QLineEdit:focus { border:1px solid #1e6bde; }
        """

    def _count_text(self, n: int) -> str:
        return f"共 {n} 个角色"

    # ------ 动作 ------

    def _refresh_list(self, keep_current: bool = True):
        current_id = self._editor._current_id if keep_current and hasattr(self._editor, "_current_id") else None
        filter_text = ""
        # 从搜索框读
        for i in range(self.layout().count()):
            w = self.layout().itemAt(i)
            if w and w.widget() and isinstance(w.widget(), QLineEdit):
                filter_text = w.widget().text().strip().lower()
                break

        self._list.blockSignals(True)
        self._list.clear()
        chars = self._store.all()
        self._count_label.setText(self._count_text(len(chars)))

        if filter_text:
            chars = [c for c in chars if
                     filter_text in (c.get("name") or "").lower() or
                     filter_text in " ".join(c.get("tags") or []).lower()]

        if not chars:
            self._empty_label.setVisible(True)
            self._list.setVisible(False)
        else:
            self._empty_label.setVisible(False)
            self._list.setVisible(True)
            for c in chars:
                name = c.get("name") or "未命名"
                role = c.get("role_type") or ""
                tags = c.get("tags") or []
                tag_text = " · ".join(tags[:3])
                display = f"{name}"
                if role:
                    display += f"  [{role}]"
                if tag_text:
                    display += f"\n   #{tag_text}"
                item = QListWidgetItem(display)
                item.setData(Qt.ItemDataRole.UserRole, c.get("id"))
                self._list.addItem(item)
                if c.get("id") == current_id:
                    self._list.setCurrentRow(self._list.count() - 1)
        self._list.blockSignals(False)

    def _on_filter(self, text: str):
        self._refresh_list(keep_current=False)

    def _on_select(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            return
        char_id = current.data(Qt.ItemDataRole.UserRole)
        if char_id:
            self._editor.load_character(char_id)

    def _on_new(self):
        self._editor.clear()
        self._editor.set_enabled(True)
        self._name_edit_focus()

    def _name_edit_focus(self):
        # 让用户立刻开始输入
        self._editor._name_edit.setFocus()
        self._editor._name_edit.selectAll()

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择角色库文件", "", "JSON 角色库 (*.json)")
        if not path:
            return
        count = self._store.import_file(path, merge=True)
        if count > 0:
            QMessageBox.information(self, "导入成功", f"成功导入 {count} 个角色")
            self._refresh_list()
        else:
            QMessageBox.warning(self, "导入失败", "文件中没有可识别的角色数据")

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存角色库", "characters.json", "JSON 角色库 (*.json)")
        if not path:
            return
        if self._store.export(path):
            QMessageBox.information(self, "导出成功", f"角色库已保存到:\n{path}")
        else:
            QMessageBox.warning(self, "导出失败", "写入文件时出错")
