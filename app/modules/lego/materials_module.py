"""
素材库模块 (MaterialsModule)
================================
从 modules.py 拆分出来的独立模块文件。

功能:
- 本地素材浏览（按类型分标签页）
- 双击/拖拽添加到时间线
- 标签筛选（8个分类：视频/音频/图片/字幕/模板/特效/转场/贴纸）
- 本地素材导入（单文件/文件夹批量）
- 右键菜单操作
- 提示词库分区（GitHub JSON + 本地包，细分类 / 收藏）

在线素材网站直达已迁至「帮助 → 素材网站直达」，不再内置假目录。
"""

import os
import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QListWidget, QListWidgetItem, QMenu,
)
from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtGui import QDrag

from .base_module import BaseModule

logger = logging.getLogger("AI短剧编辑器.materials")


class _DraggableAssetList(QListWidget):
    """支持拖拽到时间线的素材列表"""

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            item = self.currentItem()
            if item:
                file_path = item.data(Qt.ItemDataRole.UserRole)
                if file_path:
                    drag = QDrag(self)
                    mime = QMimeData()
                    mime.setUrls([QUrl.fromLocalFile(file_path)])
                    mime.setText(file_path)
                    drag.setMimeData(mime)
                    drag.exec(Qt.DropAction.CopyAction)
                    return
        super().mouseMoveEvent(event)


class MaterialsModule(BaseModule):
    """
    素材库模块
    - 本地素材导入与浏览
    - 提示词库分区（细分类 / 收藏）
    """

    module_id = "materials"
    module_name = "素材库"
    module_icon = "📁"

    CAT_TAGS = ["全部", "视频", "音频", "图片", "字幕", "模板", "特效", "转场", "贴纸"]

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()
        header = QLabel("📁 素材库")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # 顶层分区：本地素材 | 提示词库
        self._zone_tabs = QTabWidget()
        self._zone_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #121212; }
            QTabBar::tab {
                background-color: #1c1c1c;
                color: #999;
                padding: 8px 22px;
                font-size: 13px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #161616; color: #fff;
                border-bottom: 2px solid #1e6bde;
            }
        """)
        local_zone = QWidget()
        self._build_local_zone(local_zone)
        self._zone_tabs.addTab(local_zone, "📂 本地素材")

        try:
            from .prompt_library_panel import PromptLibraryPanel
            prompt_zone = PromptLibraryPanel(self)
            self._prompt_panel = prompt_zone
            self._zone_tabs.addTab(prompt_zone, "✨ 提示词库")
        except Exception as e:
            logger.warning(f"提示词库面板加载失败: {e}")
            fallback = QLabel(f"提示词库暂不可用：{e}")
            fallback.setStyleSheet("color:#f87171;padding:20px;")
            self._zone_tabs.addTab(fallback, "✨ 提示词库")

        layout.addWidget(self._zone_tabs, 1)

    def _build_local_zone(self, host: QWidget):
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        tip_row = QHBoxLayout()
        tip = QLabel("仅管理本机素材。免费/商用素材网站请到「帮助 → 素材网站直达」打开后下载，再回到此页导入。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #808080; font-size: 12px;")
        tip_row.addWidget(tip, 1)
        import_btn = QPushButton("📥 导入本地素材")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #1557b0; }
        """)
        import_btn.clicked.connect(self._import_local_assets)
        tip_row.addWidget(import_btn)
        layout.addLayout(tip_row)

        tag_layout = QHBoxLayout()
        tag_layout.setSpacing(6)
        self._material_tag_btns: dict = {}
        self._material_active_tag = "全部"
        for tag in self.CAT_TAGS:
            btn = QPushButton(tag)
            btn.setCheckable(True)
            btn.setChecked(tag == "全部")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #999;
                    border: 1px solid #333;
                    border-radius: 14px;
                    padding: 5px 14px;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #3a3a3a; color: #fff; }
                QPushButton:checked { background-color: #1e6bde; color: #fff; border-color: #1e6bde; }
            """)
            btn.clicked.connect(lambda checked, t=tag: self._apply_tag_filter(t))
            tag_layout.addWidget(btn)
            self._material_tag_btns[tag] = btn
        tag_layout.addStretch()
        layout.addLayout(tag_layout)

        self._local_tabs: dict = {}
        self._local_tab_index: dict = {}
        local_tabs = QTabWidget()
        self._local_type_tabs = local_tabs
        local_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #161616; }
            QTabBar::tab {
                background-color: #222;
                color: #999;
                padding: 6px 16px;
                font-size: 12px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background-color: #1a1a1a; color: #fff; border-bottom: 2px solid #1e6bde; }
        """)
        self._local_type_names = {
            "video": ("📹 视频", ["mp4", "avi", "mov", "mkv", "webm", "flv", "wmv"]),
            "audio": ("🎵 音频", ["mp3", "wav", "aac", "flac", "ogg", "m4a"]),
            "image": ("🖼️ 图片", ["jpg", "jpeg", "png", "gif", "bmp", "webp", "svg"]),
            "subtitle": ("📝 字幕", ["srt", "ass", "vtt", "sbv"]),
            "template": ("📋 模板", ["json", "aep", "fcpxml"]),
            "effect": ("✨ 特效", ["json"]),
            "transition": ("🔄 转场", ["json"]),
            "sticker": ("🎭 贴纸", ["png", "gif", "webp", "svg"]),
        }
        for type_key, (label, exts) in self._local_type_names.items():
            tab_widget = QWidget()
            tab_layout = QVBoxLayout(tab_widget)
            tab_layout.setContentsMargins(8, 8, 8, 8)

            btn_row = QHBoxLayout()
            import_file_btn = QPushButton("📁 导入文件")
            import_file_btn.setStyleSheet(
                "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;"
                "padding:4px 10px;font-size:11px;} QPushButton:hover{background:#3a3a3a;color:#fff;}"
            )
            import_file_btn.clicked.connect(lambda checked, tk=type_key: self._import_single_file(tk))
            btn_row.addWidget(import_file_btn)

            browse_folder_btn = QPushButton("📂 浏览文件夹")
            browse_folder_btn.setStyleSheet(
                "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;"
                "padding:4px 10px;font-size:11px;} QPushButton:hover{background:#3a3a3a;color:#fff;}"
            )
            browse_folder_btn.clicked.connect(lambda checked, tk=type_key: self._browse_local_folder(tk))
            btn_row.addWidget(browse_folder_btn)
            btn_row.addStretch()
            tab_layout.addLayout(btn_row)

            list_widget = _DraggableAssetList()
            list_widget.setStyleSheet("""
                QListWidget {
                    background-color: #111111;
                    color: #cccccc;
                    border: 1px solid #252525;
                    border-radius: 6px;
                    font-size: 12px;
                }
                QListWidget::item {
                    padding: 8px 12px;
                    border-bottom: 1px solid #1e1e1e;
                }
                QListWidget::item:hover {
                    background-color: #1a2530;
                    color: #ffffff;
                }
                QListWidget::item:selected {
                    background-color: #112244;
                    color: #ffffff;
                }
            """)
            list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            list_widget.customContextMenuRequested.connect(
                lambda pos, lw=list_widget: self._on_local_context_menu(pos, lw))
            list_widget.itemDoubleClicked.connect(self._on_local_item_double_clicked)
            tab_layout.addWidget(list_widget, 1)

            self._local_tab_index[type_key] = local_tabs.count()
            local_tabs.addTab(tab_widget, label)
            self._local_tabs[type_key] = list_widget

        self._init_local_asset_manager()
        layout.addWidget(local_tabs, 1)
        self._refresh_local_tabs()

    def _init_local_asset_manager(self):
        """初始化本地素材管理器"""
        self._local_asset_mgr = None
        try:
            from app.core.local_asset_manager import LocalAssetManager
            self._local_asset_mgr = LocalAssetManager()
        except Exception as e:
            logger.debug(f"LocalAssetManager 初始化失败: {e}")

    def _import_single_file(self, type_key: str):
        """导入单个文件到指定素材类型"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        _, exts = self._local_type_names[type_key]
        ext_filter = f"{type_key} 文件 (" + " ".join(f"*.{e}" for e in exts) + ")"
        file_path, _ = QFileDialog.getOpenFileName(self, f"选择{type_key}文件", "", ext_filter)
        if not file_path:
            return
        try:
            if self._local_asset_mgr:
                self._local_asset_mgr.import_asset(file_path)
                self._refresh_local_tabs()
                QMessageBox.information(self, "导入成功", f"已导入: {os.path.basename(file_path)}")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def _refresh_local_tabs(self):
        """使用 LocalAssetManager 刷新本地素材标签页"""
        if self._local_asset_mgr is None:
            return
        try:
            for type_key, list_widget in self._local_tabs.items():
                list_widget.clear()
                assets = self._local_asset_mgr.get_assets(asset_type=type_key)
                if assets:
                    for asset in assets[:100]:
                        size_mb = asset.size / (1024 * 1024)
                        size_str = f"{size_mb:.1f}MB" if size_mb >= 1 else f"{asset.size / 1024:.0f}KB"
                        info = f"{asset.name} ({size_str})"
                        item = QListWidgetItem(info)
                        item.setData(Qt.ItemDataRole.UserRole, asset.path)
                        item.setToolTip(f"拖拽或右键添加到时间线\n{asset.path}")
                        list_widget.addItem(item)
                if list_widget.count() == 0:
                    list_widget.addItem("（暂无素材，点击「导入本地素材」添加）")
        except Exception as e:
            logger.warning(f"刷新本地素材标签页失败: {e}")

    def _on_local_context_menu(self, pos, list_widget):
        """本地素材右键菜单"""
        item = list_widget.itemAt(pos)
        if not item:
            return
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if not file_path:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1a1a1a; color: #ffffff;
                border: 1px solid #333333; border-radius: 6px; padding: 5px;
            }
            QMenu::item { padding: 8px 25px; }
            QMenu::item:selected { background-color: #1e6bde; }
        """)

        add_action = menu.addAction("📥 添加到时间线")
        add_action.triggered.connect(lambda: self._add_to_timeline(file_path))
        menu.exec(list_widget.mapToGlobal(pos))

    def _apply_tag_filter(self, tag: str):
        """按素材标签筛选显示 — 切换到对应类型子标签页"""
        self._material_active_tag = tag
        for t, btn in self._material_tag_btns.items():
            btn.setChecked(t == tag)
        if tag != "全部":
            tag_map = {
                "视频": "video", "音频": "audio", "图片": "image",
                "字幕": "subtitle", "模板": "template", "特效": "effect",
                "转场": "transition", "贴纸": "sticker",
            }
            type_key = tag_map.get(tag)
            if type_key:
                sub_idx = self._local_tab_index.get(type_key)
                if sub_idx is not None:
                    self._local_type_tabs.setCurrentIndex(sub_idx)
            self._refresh_local_tabs()

    def _add_to_timeline(self, file_path: str):
        """将素材发送到编辑器时间线"""
        try:
            from .core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.MATERIAL_TO_TIMELINE,
                {"file_path": file_path},
                source="materials",
            )
        except Exception as e:
            logger.warning(f"发送素材到时间线失败: {e}")

    def _import_local_assets(self):
        """导入本地文件到素材库"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        all_exts = []
        for _, exts in self._local_type_names.values():
            all_exts.extend(f"*.{e}" for e in exts)
        filter_str = "媒体文件 (" + " ".join(all_exts) + ")"

        files, _ = QFileDialog.getOpenFileNames(self, "选择本地素材", "", filter_str)
        if not files:
            return

        if self._local_asset_mgr:
            imported = 0
            failed = 0
            for f in files:
                try:
                    result = self._local_asset_mgr.import_asset(f)
                    if result is not None:
                        imported += 1
                    else:
                        failed += 1
                        logger.warning(f"导入素材失败 ({os.path.basename(f)}): 不支持的类型或文件不存在")
                except Exception as e:
                    failed += 1
                    logger.warning(f"导入素材失败 ({os.path.basename(f)}): {e}")
            if imported > 0:
                msg = f"已导入 {imported} 个素材到本地库"
                if failed:
                    msg += f"（另有 {failed} 个失败）"
                QMessageBox.information(self, "导入成功", msg)
                self._refresh_local_tabs()
            elif failed:
                QMessageBox.warning(self, "导入失败", f"选中的 {failed} 个文件全部导入失败，详见日志")
        else:
            for type_key, list_widget in self._local_tabs.items():
                _, exts = self._local_type_names[type_key]
                for f in files:
                    if any(f.lower().endswith(f".{e}") for e in exts):
                        list_widget.addItem(os.path.basename(f))

    def _browse_local_folder(self, type_key: str):
        """浏览文件夹，批量导入素材到指定类型"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        folder = QFileDialog.getExistingDirectory(self, "选择素材文件夹")
        if not folder:
            return

        _, exts = self._local_type_names[type_key]
        imported = 0
        failed = 0
        for root, _, files in os.walk(folder):
            for f in files:
                if any(f.lower().endswith(f".{e}") for e in exts):
                    full_path = os.path.join(root, f)
                    try:
                        if self._local_asset_mgr:
                            result = self._local_asset_mgr.import_asset(full_path)
                            if result is not None:
                                imported += 1
                            else:
                                failed += 1
                        else:
                            imported += 1
                    except Exception as e:
                        failed += 1
                        logger.debug(f"导入素材失败 ({f}): {e}")

        if imported > 0:
            msg = f"从文件夹中导入了 {imported} 个素材"
            if failed:
                msg += f"（另有 {failed} 个导入失败，详见日志）"
            QMessageBox.information(self, "文件夹导入", msg)
            self._refresh_local_tabs()
        elif failed:
            QMessageBox.warning(self, "导入失败", f"找到 {failed} 个匹配文件，但全部导入失败，详见日志")
        else:
            QMessageBox.information(self, "提示", "所选文件夹中没有找到匹配类型的素材文件")

    def _on_local_item_double_clicked(self, item: QListWidgetItem):
        """双击本地素材 → 添加到时间线"""
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if file_path:
            self._add_to_timeline(file_path)
