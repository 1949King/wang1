"""
角色 / AI 画布模块
=================
原「角色管理」主界面已替换为镶嵌的 infinite-canvas。

- 主视图：vendor/infinite-canvas（WebEngine）生图/生视频
- 角色库：CharacterStore 仍持久化；侧栏「角色库」编辑 + 生成资产挂载
- 回流：canvas_bridge → EventBus MATERIAL_TO_TIMELINE → 剪辑
- 插帧：可选开启线性补帧（非神经网络）

剪辑模块内「角色」页签仍是视频级临时偏好，与本模块互补。
"""

import json
import os
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
# 主模块 UI —— infinite-canvas 镶嵌（替换原列表式角色管理主界面）
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
    """角色 / AI 画布模块：镶嵌 infinite-canvas，生成物回流剪辑。"""

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
        self._status_label = None
        self._interp_check = None
        self._char_combo = None
        self._engine_combo = None
        self._library_panel = None
        self._bridge_started = False
        self._pending_canvas_url = ""
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

        # 顶栏
        header = QHBoxLayout()
        title = QLabel(f"{self.module_icon} {self.module_name}")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#fff;")
        header.addWidget(title)

        hint = QLabel("无限画布生图/生视频 → 发送到剪辑 · 角色库挂资产")
        hint.setStyleSheet("color:#888;font-size:11px;margin-left:8px;")
        header.addWidget(hint)
        header.addStretch()

        self._char_combo = QComboBox()
        self._char_combo.setMinimumWidth(140)
        self._char_combo.setStyleSheet(
            "QComboBox{background:#1a1a1a;color:#eee;border:1px solid #333;padding:4px 8px;border-radius:4px;}"
        )
        self._refresh_char_combo()
        header.addWidget(QLabel("挂到角色:"))
        header.addWidget(self._char_combo)

        self._interp_check = QCheckBox("入轨后线性补帧")
        self._interp_check.setStyleSheet("color:#ccc;")
        self._interp_check.setToolTip("非神经网络：帧差 + 线性混合（ai_interpolation）")
        header.addWidget(self._interp_check)

        # 画布引擎切换：拾光导演台（自研，默认） / infinite-canvas（开源）
        self._engine_combo = QComboBox()
        self._engine_combo.setMinimumWidth(170)
        self._engine_combo.setStyleSheet(
            "QComboBox{background:#1a1a1a;color:#eee;border:1px solid #333;padding:4px 8px;border-radius:4px;}"
        )
        self._engine_combo.addItem("🎛 拾光导演台", "shiguang")
        self._engine_combo.addItem("📐 infinite-canvas", "infinite")
        self._engine_combo.setToolTip("切换画布引擎：自研导演台或开源 infinite-canvas（切换会重启画布）")
        header.addWidget(self._engine_combo)

        start_btn = QPushButton("启动画布")
        start_btn.setStyleSheet(self._btn_style("#1e6bde"))
        start_btn.clicked.connect(self._on_start_canvas)
        header.addWidget(start_btn)

        agent_btn = QPushButton("连接 Agent")
        agent_btn.setStyleSheet(self._btn_style("#7c3aed"))
        agent_btn.setToolTip("启动 npx @basketikun/canvas-agent 并写入 WebView 连接信息")
        agent_btn.clicked.connect(self._on_connect_agent)
        header.addWidget(agent_btn)

        sync_btn = QPushButton("同步模型池")
        sync_btn.setStyleSheet(self._btn_style("#0d9488"))
        sync_btn.setToolTip("把模型广场 Provider/Key 合并进画布 channels（shiguang-*）")
        sync_btn.clicked.connect(self._on_sync_models)
        header.addWidget(sync_btn)

        reload_btn = QPushButton("刷新")
        reload_btn.setStyleSheet(self._btn_style("#2a2a2a"))
        reload_btn.clicked.connect(self._on_reload)
        header.addWidget(reload_btn)

        send_btn = QPushButton("发送文件到剪辑")
        send_btn.setStyleSheet(self._btn_style("#0d9488"))
        send_btn.clicked.connect(self._on_send_file)
        header.addWidget(send_btn)

        lib_btn = QPushButton("角色库")
        lib_btn.setStyleSheet(self._btn_style("#2a2a2a"))
        lib_btn.setCheckable(True)
        lib_btn.toggled.connect(self._toggle_library)
        header.addWidget(lib_btn)

        root.addLayout(header)

        self._status_label = QLabel("准备中…")
        self._status_label.setStyleSheet("color:#79c0ff;font-size:11px;padding:2px 4px;")
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

        # 主画布
        canvas_wrap = QFrame()
        canvas_wrap.setStyleSheet("QFrame{background:#0a0a0a;border:1px solid #1e1e1e;border-radius:8px;}")
        cw = QVBoxLayout(canvas_wrap)
        cw.setContentsMargins(0, 0, 0, 0)

        if WEBENGINE_AVAILABLE:
            self._web = QWebEngineView()
            self._install_inject_script()
            try:
                self._web.loadStarted.connect(self._on_web_load_started)
                self._web.loadFinished.connect(self._on_web_load_finished)
            except Exception as e:
                logger.debug("web load signals connect failed: %s", e)
            cw.addWidget(self._web, 1)
        else:
            self._web = None
            detail = WEBENGINE_IMPORT_ERROR or "未知原因"
            err = QLabel(
                "无法镶嵌画布（QtWebEngine 不可用）。\n"
                f"原因: {detail}\n\n"
                "请确认已安装: .venv312\\Scripts\\python.exe -m pip install PyQt6-WebEngine==6.10.0\n"
                "并完全退出后重新启动应用（须在创建窗口前加载 WebEngine）。\n\n"
                "临时方案：点「启动画布」会用系统浏览器打开 http://127.0.0.1:3000"
            )
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            err.setStyleSheet("color:#f87171;padding:24px;")
            err.setWordWrap(True)
            cw.addWidget(err, 1)

        body.addWidget(canvas_wrap, 1)
        root.addLayout(body, 1)

        tip = QLabel(
            "右下角「拾光剪影」面板：发送到剪辑 / 同步模型；"
            "「连接 Agent」按需拉起 :17371（不再进模块自动预热 Agent，避免卡住）；"
            "模型 Key 来自模型广场。插帧为线性补帧，非 RIFE。"
            "可选 Codex: codex mcp add infinite-canvas -- npx -y @basketikun/canvas-agent mcp"
        )
        tip.setStyleSheet("color:#666;font-size:11px;")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self._char_combo.currentIndexChanged.connect(lambda *_: self._sync_bridge_prefs())
        self._interp_check.toggled.connect(lambda *_: self._sync_bridge_prefs())

        # 画布引擎同步 + 切换回调
        self._sync_engine_combo()
        self._engine_combo.currentIndexChanged.connect(self._on_engine_changed)

        # 延迟启动桥与探测画布
        QTimer.singleShot(200, self._bootstrap)

    def _sync_engine_combo(self):
        """下拉框与当前生效引擎对齐（不触发切换回调）。"""
        if self._engine_combo is None:
            return
        try:
            from app.core.canvas_runtime import active_canvas_engine
        except ImportError:
            from core.canvas_runtime import active_canvas_engine  # type: ignore
        eng = active_canvas_engine()
        self._engine_combo.blockSignals(True)
        idx = self._engine_combo.findData(eng)
        if idx >= 0:
            self._engine_combo.setCurrentIndex(idx)
        self._engine_combo.blockSignals(False)

    def _on_engine_changed(self, index: int):
        """用户切换画布引擎：停旧服务 → 切环境变量 → 重启并加载新画布。"""
        if self._engine_combo is None:
            return
        eng = str(self._engine_combo.itemData(index) or "")
        try:
            from app.core.canvas_runtime import active_canvas_engine, set_active_canvas_engine
        except ImportError:
            from core.canvas_runtime import active_canvas_engine, set_active_canvas_engine  # type: ignore
        if not eng or eng == active_canvas_engine():
            return

        # 确认：切换会重启画布
        label = "拾光导演台（自研）" if eng == "shiguang" else "infinite-canvas（开源）"
        if not self._confirm_switch_engine(label):
            # 取消则回退到原引擎
            self._sync_engine_combo()
            return

        self._manual_canvas_start = True
        self._set_status(f"正在切换画布到 {label}（重启服务）…")
        try:
            set_active_canvas_engine(eng)
        except Exception as e:
            self._set_status(f"切换失败: {e}")
            self._sync_engine_combo()
            return

        # 延迟到新 runtime 就绪后加载
        QTimer.singleShot(0, self._restart_canvas_with_engine)

    def _confirm_switch_engine(self, label: str) -> bool:
        """切换画布引擎确认弹窗（绑定父窗口，符合 PyQt6 弹窗铁律）。"""
        ret = QMessageBox.question(
            self,
            "切换画布引擎",
            f"将切换到 {label}，当前画布服务会重启。\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return ret == QMessageBox.StandardButton.Yes

    def _restart_canvas_with_engine(self):
        """按新引擎重启画布并加载（在 set_active_canvas_engine 之后调用）。"""
        try:
            from app.core.canvas_runtime import get_canvas_runtime
        except ImportError:
            from core.canvas_runtime import get_canvas_runtime  # type: ignore
        rt = get_canvas_runtime()
        self._ensure_bridge()
        # 先清空 WebView，避免用户以为「切换没反应」
        if self._web is not None:
            try:
                from PyQt6.QtCore import QUrl
                self._web.setHtml(
                    "<html><body style='background:#0a0a0a;color:#888;"
                    "font-family:sans-serif;display:flex;align-items:center;"
                    "justify-content:center;height:100vh;margin:0'>"
                    "正在切换画布引擎…</body></html>"
                )
            except Exception:
                pass

        def work():
            def progress(msg: str):
                self._ui_status.emit(msg)

            ok, msg = rt.ensure_started(wait_seconds=45.0, on_progress=progress)
            self._ui_canvas_started.emit(ok, msg, rt.url if ok else "")

        threading.Thread(target=work, daemon=True, name="CanvasEngineSwitch").start()

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
        self._set_status("正在启动 canvas-agent…")

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
        self._set_status(msg)
        if ok and token:
            self._inject_agent_credentials(url, token, reload_page=False)
            QTimer.singleShot(
                800, lambda: self._inject_agent_credentials(url, token, False)
            )
        elif not ok:
            QMessageBox.warning(self, "连接 Agent", msg)

    def _on_sync_models(self):
        self._ensure_bridge()
        self._sync_bridge_prefs()
        self._set_status("正在同步模型池到画布…")
        self._run_js(
            "window.__shiguangSyncModels && window.__shiguangSyncModels(true);"
        )
        try:
            from app.modules.lego.model_config import load_active_provider, PROVIDERS
            ap = load_active_provider() or ""
            name = (PROVIDERS.get(ap) or {}).get("name") or ap or "未激活"
            self._set_status(f"已请求同步模型池 · 当前激活 {name}")
        except Exception:
            self._set_status("已请求同步模型池（画布将刷新）")

    def _bootstrap(self):
        self._ensure_bridge()
        self._sync_bridge_prefs()
        try:
            from app.core.canvas_runtime import get_canvas_runtime
        except ImportError:
            from core.canvas_runtime import get_canvas_runtime  # type: ignore
        rt = get_canvas_runtime()
        if rt.is_ready():
            self._load_canvas(rt.url)
            self._set_status(f"已连接 {rt.url}")
            QTimer.singleShot(800, self._maybe_inject_existing_agent)
            return
        # 进入模块即后台预热，避免干等「启动画布」
        try:
            from app.core.canvas_runtime import active_canvas_engine
        except ImportError:
            from core.canvas_runtime import active_canvas_engine  # type: ignore
        eng = active_canvas_engine()
        eng_label = "拾光导演台（自研）" if eng == "shiguang" else "infinite-canvas（开源）"
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
            self._inject_agent_credentials(rt.url, rt.token, False)
            QTimer.singleShot(
                1200, lambda: self._inject_agent_credentials(rt.url, rt.token, False)
            )
            # 不覆盖 loadFinished 的「画布已就绪」文案（若页面还在加载则稍后再写）
            return
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
            pass
        self._pending_canvas_url = url
        if self._web is None:
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
            self._set_status(f"画布已就绪 {url}" if url else "画布已就绪")
            logger.info("canvas page loadFinished ok url=%s", url)
        else:
            self._set_status(f"画布页面加载失败（请点「刷新」或「启动画布」） {url}")
            logger.warning("canvas page loadFinished FAIL url=%s", url)

    def _set_status(self, text: str):
        if self._status_label is not None:
            self._status_label.setText(text)

    def _on_start_canvas(self):
        self._ensure_bridge()
        self._manual_canvas_start = True
        try:
            from app.core.canvas_runtime import active_canvas_engine
        except ImportError:
            from core.canvas_runtime import active_canvas_engine  # type: ignore
        eng_label = "拾光导演台" if active_canvas_engine() == "shiguang" else "infinite-canvas"
        self._set_status(f"正在启动 {eng_label}…")
        try:
            from app.core.canvas_runtime import get_canvas_runtime
        except ImportError:
            from core.canvas_runtime import get_canvas_runtime  # type: ignore

        def work():
            rt = get_canvas_runtime()

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
