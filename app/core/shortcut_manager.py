"""
快捷键管理系统 (ShortcutManager)
================================
对标 Shotcut/OpenShot 的可自定义快捷键系统。

特性:
- 内置默认快捷键集 (与 Shotcut/OpenShot 一致)
- JSON 配置文件加载/保存
- 用户自定义快捷键
- 按键冲突检测
- 快捷键编辑器 UI
- 上下文作用域 (全局/时间线/预览)
"""
import os
import json
import logging
from typing import Dict, List, Optional, Callable, Set, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QKeySequenceEdit, QMessageBox,
    QLineEdit, QComboBox, QWidget,
)

logger = logging.getLogger("AI短剧编辑器.shortcuts")


class ShortcutContext(str, Enum):
    """快捷键作用域"""
    GLOBAL = "global"           # 全局
    TIMELINE = "timeline"       # 时间线
    PREVIEW = "preview"         # 预览窗口
    EXPORT = "export"           # 导出


# 默认快捷键定义（对标 Shotcut）
DEFAULT_SHORTCUTS: Dict[str, Dict[str, str]] = {
    # === 文件操作 ===
    "file.new":                  {"key": "Ctrl+N",        "context": "global",   "desc": "新建项目"},
    "file.open":                 {"key": "Ctrl+O",        "context": "global",   "desc": "打开项目"},
    "file.save":                 {"key": "Ctrl+S",        "context": "global",   "desc": "保存项目"},
    "file.save_as":              {"key": "Ctrl+Shift+S",  "context": "global",   "desc": "另存为"},
    "file.export":               {"key": "Ctrl+E",        "context": "global",   "desc": "导出视频"},
    "file.import":               {"key": "Ctrl+I",        "context": "global",   "desc": "导入媒体"},

    # === 撤销/重做 ===
    "edit.undo":                 {"key": "Ctrl+Z",        "context": "global",   "desc": "撤销"},
    "edit.redo":                 {"key": "Ctrl+Y",        "context": "global",   "desc": "重做"},
    "edit.undo_history":         {"key": "Ctrl+Shift+Z",  "context": "global",   "desc": "撤销历史"},

    # === 剪辑操作 (Timeline 上下文) ===
    "clip.cut":                  {"key": "Ctrl+X",        "context": "timeline", "desc": "剪切片段"},
    "clip.copy":                 {"key": "Ctrl+C",        "context": "timeline", "desc": "复制片段"},
    "clip.paste":                {"key": "Ctrl+V",        "context": "timeline", "desc": "粘贴片段"},
    "clip.delete":               {"key": "Delete",        "context": "timeline", "desc": "删除片段"},
    "clip.ripple_delete":        {"key": "Shift+Delete",  "context": "timeline", "desc": "波纹删除"},
    "clip.lift":                 {"key": "Ctrl+Shift+Delete", "context": "timeline", "desc": "提升片段"},
    "clip.split":                {"key": "S",             "context": "timeline", "desc": "在播放头处分割"},
    "clip.split_all":            {"key": "Ctrl+Shift+S",  "context": "timeline", "desc": "分割所有轨道"},
    "clip.duplicate":            {"key": "Ctrl+D",        "context": "timeline", "desc": "复制片段"},
    "clip.enable":               {"key": "Shift+E",       "context": "timeline", "desc": "启用/禁用片段"},

    # === 选择 ===
    "select.all":                {"key": "Ctrl+A",        "context": "timeline", "desc": "全选"},
    "select.none":               {"key": "Ctrl+Shift+A",  "context": "timeline", "desc": "取消选择"},
    "select.left_track":         {"key": "Up",            "context": "timeline", "desc": "选择上一轨道"},
    "select.right_track":        {"key": "Down",          "context": "timeline", "desc": "选择下一轨道"},

    # === 播放控制 (Preview 上下文) ===
    "play.play_pause":           {"key": "Space",         "context": "preview",  "desc": "播放/暂停"},
    "play.stop":                 {"key": "K",             "context": "preview",  "desc": "停止"},
    "play.forward":              {"key": "L",             "context": "preview",  "desc": "快进"},
    "play.backward":             {"key": "J",             "context": "preview",  "desc": "快退"},
    "play.next_frame":           {"key": "Right",         "context": "preview",  "desc": "下一帧"},
    "play.prev_frame":           {"key": "Left",          "context": "preview",  "desc": "上一帧"},
    "play.next_second":          {"key": "Shift+Right",   "context": "preview",  "desc": "下一秒"},
    "play.prev_second":          {"key": "Shift+Left",    "context": "preview",  "desc": "上一秒"},
    "play.next_marker":          {"key": "Ctrl+Right",    "context": "preview",  "desc": "下一标记"},
    "play.prev_marker":          {"key": "Ctrl+Left",     "context": "preview",  "desc": "上一标记"},
    "play.start":                {"key": "Home",          "context": "preview",  "desc": "跳到开始"},
    "play.end":                  {"key": "End",           "context": "preview",  "desc": "跳到结束"},
    "play.loop":                 {"key": "Ctrl+L",        "context": "preview",  "desc": "循环播放"},

    # === 标记 ===
    "marker.add":                {"key": "M",             "context": "timeline", "desc": "添加标记"},
    "marker.edit":               {"key": "Ctrl+M",        "context": "timeline", "desc": "编辑标记"},
    "marker.ripple":             {"key": "Ctrl+Shift+M",  "context": "timeline", "desc": "波纹标记"},

    # === 视图 ===
    "view.zoom_in":              {"key": "Ctrl+=",        "context": "global",   "desc": "放大时间线"},
    "view.zoom_out":             {"key": "Ctrl+-",        "context": "global",   "desc": "缩小时间线"},
    "view.zoom_fit":             {"key": "Ctrl+0",        "context": "global",   "desc": "适应窗口"},
    "view.fullscreen":           {"key": "F11",           "context": "global",   "desc": "全屏"},

    # === 轨道 ===
    "track.add_video":           {"key": "Ctrl+Shift+V",  "context": "timeline", "desc": "添加视频轨道"},
    "track.add_audio":           {"key": "Ctrl+Shift+A",  "context": "timeline", "desc": "添加音频轨道"},
    "track.add_subtitle":        {"key": "Ctrl+Shift+T",  "context": "timeline", "desc": "添加字幕轨道"},
    "track.toggle_mute":         {"key": "M",             "context": "timeline", "desc": "切换静音"},
    "track.toggle_solo":         {"key": "Shift+M",       "context": "timeline", "desc": "切换独奏"},
    "track.toggle_lock":         {"key": "L",             "context": "timeline", "desc": "切换锁定"},

    # === AI 智能剪辑 ===
    "ai.auto_clip":              {"key": "Ctrl+R",        "context": "global",   "desc": "AI 智能剪辑"},
    "ai.optimize_viral":         {"key": "Ctrl+Shift+R",  "context": "global",   "desc": "AI 爆款优化"},
    "ai.generate_subtitle":      {"key": "Ctrl+Shift+B",  "context": "global",   "desc": "AI 自动字幕"},
}


@dataclass
class ShortcutBinding:
    """单个快捷键绑定"""
    action_id: str           # 动作标识 (e.g. "file.save")
    key_sequence: str        # 按键序列字符串
    context: str             # 作用域
    description: str = ""    # 中文描述

    def to_dict(self) -> Dict:
        return {"key": self.key_sequence, "context": self.context, "desc": self.description}

    @classmethod
    def from_default(cls, action_id: str) -> "ShortcutBinding":
        """从默认配置构造"""
        cfg = DEFAULT_SHORTCUTS.get(action_id, {})
        return cls(
            action_id=action_id,
            key_sequence=cfg.get("key", ""),
            context=cfg.get("context", "global"),
            description=cfg.get("desc", ""),
        )


class ShortcutManager(QObject):
    """
    快捷键管理器 (单例)
    - 维护所有动作的快捷键
    - 提供 QAction 注册接口
    - 加载/保存用户自定义配置

    单例由本模块底部的 `shortcut_manager` 全局实例提供（全库唯一构造点）。
    曾用 `__new__` 返回缓存实例，但 **PyQt6 下「覆写 `__new__` 返回缓存实例」与
    「`__init__` 内调用 `super().__init__()`」的组合会触发 C 层无限递归**，
    导致 `import app.core.shortcut_manager` 直接栈溢出（0xC00000FD，Python 无法捕获）。
    最小复现与条件对照见 `docs/冷启动性能诊断报告.md` §7.5b。
    """

    shortcut_changed = pyqtSignal(str, str)  # (action_id, new_key)

    def __init__(self, config_path: str = ""):
        # ⚠️ super().__init__() 必须在任何 self 属性访问之前调用：
        # PyQt6 在 QObject 基类未初始化时读取实例属性会抛
        # `RuntimeError: super-class __init__() of type X was never called`。
        super().__init__()
        if getattr(self, '_initialized', False):
            return
        self._initialized = True

        # 动作回调: { action_id: callback }
        self._actions: Dict[str, Callable] = {}
        # QAction 引用: { action_id: QAction } - 由 UI 层注册
        self._qactions: Dict[str, "QAction"] = {}
        # 当前快捷键绑定: { action_id: ShortcutBinding }
        self._bindings: Dict[str, ShortcutBinding] = {}
        # 配置文件路径
        if not config_path:
            try:
                from app.core.config_paths import get_user_data_dir
                base = get_user_data_dir()
            except ImportError:
                base = os.path.join(os.path.expanduser("~"), ".ai_short_drama_editor")
            os.makedirs(base, exist_ok=True)
            config_path = os.path.join(base, "shortcuts.json")
        self._config_path = config_path

        # 初始化默认绑定
        for action_id in DEFAULT_SHORTCUTS:
            self._bindings[action_id] = ShortcutBinding.from_default(action_id)

        # 加载用户自定义
        self.load()

    # ---- 动作管理 ----

    def register_action(self, action_id: str, callback: Callable):
        """注册动作回调 (供程序内部使用)"""
        self._actions[action_id] = callback

    def register_qaction(self, action_id: str, qaction):
        """注册 QAction 引用 (供 UI 层使用, 自动应用快捷键)"""
        self._qactions[action_id] = qaction
        binding = self._bindings.get(action_id)
        if binding and binding.key_sequence:
            qaction.setShortcut(QKeySequence(binding.key_sequence))

    def unregister_action(self, action_id: str):
        """注销动作"""
        self._actions.pop(action_id, None)
        self._qactions.pop(action_id, None)

    # ---- 快捷键管理 ----

    def get_binding(self, action_id: str) -> Optional[ShortcutBinding]:
        return self._bindings.get(action_id)

    def get_all_bindings(self) -> List[ShortcutBinding]:
        return list(self._bindings.values())

    def set_shortcut(self, action_id: str, key_sequence: str) -> bool:
        """
        设置快捷键

        Returns:
            True 成功, False 失败 (冲突)
        """
        # 检查冲突
        conflict = self._check_conflict(action_id, key_sequence)
        if conflict:
            logger.warning(f"快捷键冲突: {key_sequence} 已被 [{conflict}] 占用")
            return False

        binding = self._bindings.get(action_id)
        if not binding:
            binding = ShortcutBinding(action_id, key_sequence, "global", "")
            self._bindings[action_id] = binding
        else:
            binding.key_sequence = key_sequence

        # 更新已注册的 QAction
        if action_id in self._qactions:
            self._qactions[action_id].setShortcut(QKeySequence(key_sequence))

        self.shortcut_changed.emit(action_id, key_sequence)
        return True

    def reset_to_default(self, action_id: str = "") -> bool:
        """重置为默认快捷键"""
        if action_id:
            default = DEFAULT_SHORTCUTS.get(action_id)
            if not default:
                return False
            self._bindings[action_id] = ShortcutBinding.from_default(action_id)
            if action_id in self._qactions:
                self._qactions[action_id].setShortcut(
                    QKeySequence(default["key"])
                )
        else:
            # 重置全部
            self._bindings.clear()
            for aid in DEFAULT_SHORTCUTS:
                self._bindings[aid] = ShortcutBinding.from_default(aid)
                if aid in self._qactions:
                    self._qactions[aid].setShortcut(
                        QKeySequence(DEFAULT_SHORTCUTS[aid]["key"])
                    )
        return True

    def _check_conflict(self, exclude_action_id: str, key_sequence: str) -> Optional[str]:
        """检测快捷键冲突, 返回冲突的 action_id 或 None"""
        if not key_sequence:
            return None
        for aid, binding in self._bindings.items():
            if aid == exclude_action_id:
                continue
            if binding.key_sequence.lower() == key_sequence.lower():
                return aid
        return None

    # ---- 持久化 ----

    def save(self, path: str = "") -> bool:
        """保存到 JSON"""
        path = path or self._config_path
        try:
            data = {
                "version": "1.0",
                "bindings": {
                    aid: binding.to_dict()
                    for aid, binding in self._bindings.items()
                },
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"保存快捷键配置失败: {e}")
            return False

    def load(self, path: str = "") -> bool:
        """从 JSON 加载"""
        path = path or self._config_path
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            bindings_data = data.get("bindings", {})
            for action_id, cfg in bindings_data.items():
                if action_id in self._bindings:
                    self._bindings[action_id].key_sequence = cfg.get("key", "")
                    self._bindings[action_id].context = cfg.get("context", "global")
                else:
                    self._bindings[action_id] = ShortcutBinding(
                        action_id=action_id,
                        key_sequence=cfg.get("key", ""),
                        context=cfg.get("context", "global"),
                        description=cfg.get("desc", ""),
                    )
            return True
        except Exception as e:
            logger.error(f"加载快捷键配置失败: {e}")
            return False

    def export_config(self, path: str) -> bool:
        """导出配置 (用户分享)"""
        return self.save(path)

    def import_config(self, path: str) -> bool:
        """导入配置"""
        return self.load(path)


# 全局实例
shortcut_manager = ShortcutManager()


# ============================================================
# 快捷键编辑器 UI
# ============================================================

class ShortcutEditorDialog(QDialog):
    """
    快捷键编辑器 (对标 Shotcut 的 Keyboard Shortcuts 面板)

    支持:
    - 按键录制
    - 冲突检测
    - 搜索过滤
    - 重置默认
    - 导入/导出配置
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键设置")
        self.resize(720, 560)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #ccc; }
            QLabel { color: #ccc; }
            QLineEdit, QComboBox {
                background: #2a2a2a; color: #ccc; border: 1px solid #444;
                border-radius: 3px; padding: 4px;
            }
            QPushButton {
                background: #2a2a2a; color: #ccc; border: 1px solid #444;
                border-radius: 3px; padding: 6px 14px;
            }
            QPushButton:hover { background: #353535; }
            QPushButton#primary { background: #1e6bde; border-color: #1e6bde; }
            QPushButton#primary:hover { background: #2978e8; }
            QTableWidget {
                background: #252525; alternate-background-color: #2a2a2a;
                gridline-color: #333; color: #ccc; border: 1px solid #333;
            }
            QHeaderView::section {
                background: #2a2a2a; color: #aaa; border: 0;
                border-bottom: 1px solid #444; padding: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 顶部标题
        title = QLabel("⌨ 快捷键设置 (对标 Shotcut 风格)")
        title.setStyleSheet("font-size:14px;font-weight:bold;color:#fff;")
        layout.addWidget(title)

        # 搜索 + 作用域过滤
        filter_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 搜索动作...")
        self._search.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._search, 1)

        self._context_filter = QComboBox()
        self._context_filter.addItem("全部作用域", "")
        self._context_filter.addItem("全局", "global")
        self._context_filter.addItem("时间线", "timeline")
        self._context_filter.addItem("预览", "preview")
        self._context_filter.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self._context_filter)

        layout.addLayout(filter_row)

        # 快捷键表格
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["动作", "描述", "作用域", "快捷键"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.doubleClicked.connect(self._on_edit_shortcut)
        layout.addWidget(self._table, 1)

        # 提示
        tip = QLabel("💡 双击\"快捷键\"列进行修改，按 Esc 取消，按 Backspace 清空")
        tip.setStyleSheet("color:#888;font-size:11px;")
        layout.addWidget(tip)

        # 按钮
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("🔄 重置默认")
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)

        export_btn = QPushButton("📤 导出...")
        export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(export_btn)

        import_btn = QPushButton("📥 导入...")
        import_btn.clicked.connect(self._on_import)
        btn_row.addWidget(import_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("💾 保存")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

        # 加载数据
        self._populate_table()

    def _populate_table(self, search_text: str = "", context_filter: str = ""):
        """填充表格"""
        bindings = shortcut_manager.get_all_bindings()
        self._table.setRowCount(0)
        for b in bindings:
            # 过滤
            if search_text:
                s = search_text.lower()
                if (s not in b.action_id.lower()
                        and s not in b.description.lower()
                        and s not in b.key_sequence.lower()):
                    continue
            if context_filter and b.context != context_filter:
                continue

            row = self._table.rowCount()
            self._table.insertRow(row)

            # 动作 ID
            item = QTableWidgetItem(b.action_id)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, item)

            # 描述
            item = QTableWidgetItem(b.description)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 1, item)

            # 作用域
            ctx_map = {"global": "全局", "timeline": "时间线", "preview": "预览"}
            item = QTableWidgetItem(ctx_map.get(b.context, b.context))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 2, item)

            # 快捷键
            item = QTableWidgetItem(b.key_sequence)
            self._table.setItem(row, 3, item)

    def _apply_filter(self):
        """应用过滤"""
        search = self._search.text().strip()
        ctx = self._context_filter.currentData() or ""
        self._populate_table(search, ctx)

    def _on_edit_shortcut(self, index):
        """双击编辑快捷键"""
        if index.column() != 3:
            return
        row = index.row()
        action_id = self._table.item(row, 0).text()
        current_key = self._table.item(row, 3).text()

        editor = QKeySequenceEdit(QKeySequence(current_key))
        if editor.exec() == QDialog.DialogCode.Accepted:
            new_key = editor.keySequence().toString()
            if not new_key:
                # 用户清空
                shortcut_manager.set_shortcut(action_id, "")
                self._table.item(row, 3).setText("")
                return

            success = shortcut_manager.set_shortcut(action_id, new_key)
            if success:
                self._table.item(row, 3).setText(new_key)
            else:
                QMessageBox.warning(
                    self, "冲突",
                    f"快捷键 '{new_key}' 已被其他动作占用，请选择其他组合。"
                )

    def _on_reset(self):
        """重置默认"""
        ret = QMessageBox.question(
            self, "确认", "确定要将所有快捷键重置为默认值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret == QMessageBox.StandardButton.Yes:
            shortcut_manager.reset_to_default()
            self._populate_table()

    def _on_save(self):
        """保存配置"""
        if shortcut_manager.save():
            QMessageBox.information(self, "成功", "快捷键配置已保存")
            self.accept()
        else:
            QMessageBox.critical(self, "失败", "保存失败，请检查文件权限")

    def _on_export(self):
        """导出配置"""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出快捷键配置", "shortcuts.json",
            "JSON Files (*.json)"
        )
        if path:
            if shortcut_manager.export_config(path):
                QMessageBox.information(self, "成功", f"已导出到: {path}")
            else:
                QMessageBox.critical(self, "失败", "导出失败")

    def _on_import(self):
        """导入配置"""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "导入快捷键配置", "",
            "JSON Files (*.json)"
        )
        if path:
            if shortcut_manager.import_config(path):
                self._populate_table()
                QMessageBox.information(self, "成功", "已导入新配置")
            else:
                QMessageBox.critical(self, "失败", "导入失败")
