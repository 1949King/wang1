"""
素材库模块 (MaterialsModule)
================================
从 modules.py 拆分出来的独立模块文件。

功能:
- 本地素材浏览（按类型分标签页）
- 在线素材预览（卡片式展示）
- 双击/拖拽添加到时间线
- 标签筛选（8个分类：视频/音频/图片/字幕/模板/特效/转场/贴纸）
- 本地素材导入（单文件/文件夹批量）
- 在线素材下载
- 右键菜单操作
"""

import os
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QScrollArea, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QFileDialog,
    QMessageBox, QGroupBox,
)
from PyQt6.QtCore import Qt, QMimeData, QUrl
from PyQt6.QtGui import QFont, QDrag

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
    - 本地素材 + 在线素材库
    - 视频,音频,图片,字幕,模板,特效,转场,贴纸
    """
    
    module_id = "materials"
    module_name = "素材库"
    module_icon = "📁"
    
    CAT_TAGS = ["全部", "视频", "音频", "图片", "字幕", "模板", "特效", "转场", "贴纸"]
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        header_layout = QHBoxLayout()
        header = QLabel("📁 素材库")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
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
        header_layout.addWidget(import_btn)
        layout.addLayout(header_layout)
        
        # 搜索 & 类型筛选
        search_layout = QHBoxLayout()
        search_layout.setSpacing(10)
        
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索素材...")
        self._search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
        """)
        self._search_input.textChanged.connect(lambda t: self._load_materials())
        search_layout.addWidget(self._search_input, 2)
        
        self._type_combo = QComboBox()
        self._type_combo.addItems(["全部", "视频", "音频", "图片", "字幕", "模板", "特效", "转场", "贴纸"])
        self._type_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 12px;
                min-width: 100px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        self._type_combo.currentTextChanged.connect(lambda t: self._load_materials())
        search_layout.addWidget(self._type_combo, 1)
        
        layout.addLayout(search_layout)
        
        # ═══════════════════════════════════════════════════════
        # 素材标签筛选栏
        # ═══════════════════════════════════════════════════════
        tag_layout = QHBoxLayout()
        tag_layout.setSpacing(6)
        self._material_tag_btns: dict = {}
        self._material_active_tag = "全部"
        for tag in self.CAT_TAGS:
            btn = QPushButton(tag)
            btn.setCheckable(True)
            btn.setChecked(tag == "全部")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {'#1e6bde' if tag == '全部' else '#2a2a2a'};
                    color: {'white' if tag == '全部' else '#999'};
                    border: 1px solid #333;
                    border-radius: 14px;
                    padding: 5px 14px;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background-color: #3a3a3a; color: #fff; }}
                QPushButton:checked {{ background-color: #1e6bde; color: #fff; border-color: #1e6bde; }}
            """)
            btn.clicked.connect(lambda checked, t=tag: self._apply_tag_filter(t))
            tag_layout.addWidget(btn)
            self._material_tag_btns[tag] = btn
        tag_layout.addStretch()
        layout.addLayout(tag_layout)
        
        # ═══════════════════════════════════════════════════════
        # 主内容区（本地素材 + 在线素材 双标签页）
        # ═══════════════════════════════════════════════════════
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #1a1a1a; }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #808080;
                padding: 10px 24px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
                margin-right: 2px;
            }
            QTabBar::tab:selected { background-color: #1e6bde; color: #ffffff; }
        """)
        
        # ── 本地素材标签页 ──
        self._local_tabs: dict = {}
        self._local_tab_index: dict = {}  # type_key -> 内层子标签页索引（供标签筛选按钮跳转）
        local_panel = QWidget()
        local_layout = QVBoxLayout(local_panel)
        local_layout.setContentsMargins(0, 10, 0, 0)
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
            
            # 导入按钮行
            btn_row = QHBoxLayout()
            import_file_btn = QPushButton("📁 导入文件")
            import_file_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:4px 10px;font-size:11px;} QPushButton:hover{background:#3a3a3a;color:#fff;}")
            import_file_btn.clicked.connect(lambda checked, tk=type_key: self._import_single_file(tk))
            btn_row.addWidget(import_file_btn)
            
            browse_folder_btn = QPushButton("📂 浏览文件夹")
            browse_folder_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;padding:4px 10px;font-size:11px;} QPushButton:hover{background:#3a3a3a;color:#fff;}")
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
        
        # 初始化本地素材管理器
        self._init_local_asset_manager()
        
        local_layout.addWidget(local_tabs, 1)
        self._tabs.addTab(local_panel, "📁 本地素材")
        
        # ── 在线素材标签页 ──
        online_widget = QWidget()
        online_layout = QVBoxLayout(online_widget)
        online_layout.setContentsMargins(0, 10, 0, 0)
        
        pager_layout = QHBoxLayout()
        self._page_label = QLabel("第 1 页")
        self._page_label.setStyleSheet("color: #808080; font-size: 12px;")
        pager_layout.addWidget(self._page_label)
        pager_layout.addStretch()
        
        self._prev_btn = QPushButton("◀ 上一页")
        self._prev_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:4px;padding:4px 12px;}QPushButton:hover{background:#3a3a3a;color:#fff;}QPushButton:disabled{color:#444;}")
        self._prev_btn.clicked.connect(lambda: self._change_page(-1))
        pager_layout.addWidget(self._prev_btn)
        
        self._next_btn = QPushButton("下一页 ▶")
        self._next_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:4px;padding:4px 12px;}QPushButton:hover{background:#3a3a3a;color:#fff;}QPushButton:disabled{color:#444;}")
        self._next_btn.clicked.connect(lambda: self._change_page(1))
        pager_layout.addWidget(self._next_btn)
        
        online_layout.addLayout(pager_layout)
        
        self._materials_grid = QTableWidget()
        self._materials_grid.setColumnCount(7)
        self._materials_grid.setHorizontalHeaderLabels(["预览", "名称", "类型", "标签", "下载量", "收藏", "操作"])
        self._materials_grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._materials_grid.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                color: #ffffff;
            }
            QTableWidget::item { border: none; }
            QHeaderView::section {
                background-color: #2a2a2a;
                padding: 10px;
                border: none;
                border-bottom: 1px solid #333333;
                font-weight: bold;
                color: #808080;
            }
            QTableWidget::item { padding: 8px; border-bottom: 1px solid #2a2a2a; }
            QTableWidget::item:selected { background-color: #1e6bde; }
        """)
        online_layout.addWidget(self._materials_grid, 1)
        
        self._tabs.addTab(online_widget, "🌐 在线素材")
        
        layout.addWidget(self._tabs, 1)
        
        # 页面状态
        self._current_page = 1
        self._page_size = 20
        self._current_materials = []
        
        self._load_materials()
    
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
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
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
                    for asset in assets[:100]:  # 限制显示100条
                        size_mb = asset.size / (1024 * 1024)
                        size_str = f"{size_mb:.1f}MB" if size_mb >= 1 else f"{asset.size / 1024:.0f}KB"
                        info = f"{asset.name} ({size_str})"
                        item = QListWidgetItem(info)
                        item.setData(Qt.ItemDataRole.UserRole, asset.path)  # 存储文件路径
                        item.setToolTip(f"拖拽或右键添加到时间线\n{asset.path}")
                        list_widget.addItem(item)
                if list_widget.count() == 0:
                    list_widget.addItem("（暂无素材，点击\"导入本地素材\"添加）")
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
        """按素材标签筛选显示 — 切换到对应类型的本地素材子标签页

        修复：此前只切到外层"📁 本地素材"这一个大标签页（本来就常驻显示），
        完全没有跳到内层按类型(video/audio/...)分的子标签页，点击"音频"
        "图片"等任何标签，界面都没有变化，形同摆设。
        """
        self._material_active_tag = tag
        for t, btn in self._material_tag_btns.items():
            btn.setChecked(t == tag)
        # 如果非"全部"，跳到对应类型的子标签页
        if tag != "全部":
            tag_map = {"视频": "video", "音频": "audio", "图片": "image",
                       "字幕": "subtitle", "模板": "template", "特效": "effect",
                       "转场": "transition", "贴纸": "sticker"}
            type_key = tag_map.get(tag)
            if type_key and hasattr(self, '_local_type_tabs'):
                for i in range(self._tabs.count()):
                    if self._tabs.tabText(i).startswith("📁"):
                        self._tabs.setCurrentIndex(i)
                        break
                sub_idx = self._local_tab_index.get(type_key)
                if sub_idx is not None:
                    self._local_type_tabs.setCurrentIndex(sub_idx)
            self._refresh_local_tabs()

    def _add_to_timeline(self, file_path: str):
        """将素材发送到编辑器时间线"""
        try:
            from .core import EventBus, EventType
            EventBus.get_instance().emit(EventType.MATERIAL_TO_TIMELINE,
                                         {"file_path": file_path}, source="materials")
        except Exception as e:
            logger.warning(f"发送素材到时间线失败: {e}")

    def _download_material(self, material):
        """下载在线素材到本地"""
        from PyQt6.QtWidgets import QMessageBox
        try:
            ext = getattr(material, 'format', 'mp4') or 'mp4'
            save_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                     "data", "downloads", f"{material.id}.{ext}")
            from .online_materials import online_material_library
            online_material_library.download_material(
                material.id, save_path,
                complete_callback=lambda ok, path: self._on_download_complete(ok, path)
            )
        except Exception as e:
            QMessageBox.warning(self, "错误", f"下载失败: {e}")

    def _on_download_complete(self, success: bool, path: str):
        """下载完成回调"""
        from PyQt6.QtWidgets import QMessageBox
        if success:
            QMessageBox.information(self, "下载完成", f"素材已保存到:\n{path}")
        else:
            QMessageBox.warning(self, "下载失败", f"无法下载该素材: {path}")

    def _download_and_add_timeline(self, material):
        """下载在线素材并添加到时间线"""
        from PyQt6.QtWidgets import QMessageBox
        try:
            ext = getattr(material, 'format', 'mp4') or 'mp4'
            save_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                     "data", "downloads", f"{material.id}.{ext}")
            from .online_materials import online_material_library
            online_material_library.download_material(
                material.id, save_path,
                complete_callback=lambda ok, path: self._on_timeline_download_complete(ok, path)
            )
        except Exception as e:
            QMessageBox.warning(self, "错误", f"操作失败: {e}")

    def _on_timeline_download_complete(self, success: bool, path: str):
        """下载完成 → 添加到时间线"""
        from PyQt6.QtWidgets import QMessageBox
        if success and os.path.exists(path):
            self._add_to_timeline(path)
            QMessageBox.information(self, "完成", "素材已下载并添加到时间线")
        else:
            QMessageBox.warning(self, "失败", f"无法下载该素材")
    
    def _import_local_assets(self):
        """导入本地文件到素材库"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
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
                    # 修复：import_asset() 失败时返回 None（不抛异常），此前不检查
                    # 返回值就 imported += 1，失败文件也被算作"导入成功"
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
            # 无管理器时直接显示文件路径
            for type_key, list_widget in self._local_tabs.items():
                _, exts = self._local_type_names[type_key]
                for f in files:
                    if any(f.lower().endswith(f".{e}") for e in exts):
                        list_widget.addItem(os.path.basename(f))

    def _browse_local_folder(self, type_key: str):
        """浏览文件夹，批量导入素材到指定类型"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
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
                            # 修复：import_asset() 失败时返回 None（不抛异常），此前不检查
                            # 返回值就 imported += 1，导致失败的文件也被计入"成功导入"
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

    def _change_page(self, delta: int):
        """翻页"""
        new_page = self._current_page + delta
        if new_page < 1:
            return
        self._current_page = new_page
        self._load_materials()

    def _load_materials(self):
        from .online_materials import online_material_library
        
        material_type = self._type_combo.currentText()
        keyword = self._search_input.text()
        
        materials = online_material_library.fetch_materials(
            material_type=material_type,
            keyword=keyword,
            page=self._current_page,
            page_size=self._page_size
        )
        
        self._current_materials = materials
        self._materials_grid.setRowCount(len(materials))
        
        type_icons = {
            "video": "🎬", "audio": "🎵", "image": "🖼️",
            "subtitle": "📝", "template": "📋", "effect": "✨",
            "transition": "🔄", "sticker": "🎭"
        }
        
        for row, material in enumerate(materials):
            # 缩略图 - 类型图标
            type_icon = type_icons.get(material.type, "📁")
            thumb_item = QTableWidgetItem(type_icon)
            thumb_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_item.setFont(QFont("Segoe UI Emoji", 18))
            self._materials_grid.setItem(row, 0, thumb_item)
            
            name_item = QTableWidgetItem(material.title)
            self._materials_grid.setItem(row, 1, name_item)
            
            type_item = QTableWidgetItem(f"{type_icon} {material.type}")
            self._materials_grid.setItem(row, 2, type_item)
            
            # 标签
            raw_tags = getattr(material, 'tags', None)
            if isinstance(raw_tags, list):
                tags = ' '.join(str(t) for t in raw_tags) or '通用 素材'
            else:
                tags = raw_tags or '通用 素材'
            tag_item = QTableWidgetItem(tags[:20])
            tag_item.setToolTip(tags)
            self._materials_grid.setItem(row, 3, tag_item)
            
            downloads_item = QTableWidgetItem(f"{material.downloads:,}")
            downloads_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._materials_grid.setItem(row, 4, downloads_item)
            
            # 收藏星标
            fav_btn = QPushButton("☆")
            fav_btn.setCheckable(True)
            fav_btn.setFlat(True)
            fav_btn.setStyleSheet("""
                QPushButton { color:#888; font-size:16px; border:none; background:transparent; }
                QPushButton:checked { color:#f59e0b; }
                QPushButton:hover { color:#f59e0b; }
            """)
            def _make_fav_toggle(btn, mat):
                def _toggle(checked):
                    mat.favorited = checked
                    btn.setText("⭐" if checked else "☆")
                return _toggle
            fav_btn.toggled.connect(_make_fav_toggle(fav_btn, material))
            self._materials_grid.setCellWidget(row, 5, fav_btn)
            
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(5, 2, 5, 2)
            action_layout.setSpacing(4)
            
            download_btn = QPushButton("下载" if material.is_free else f"¥{material.price}")
            download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e6bde;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 5px 12px;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #2a7bef; }
            """)
            download_btn.clicked.connect(lambda checked, m=material: self._download_material(m))
            action_layout.addWidget(download_btn)
            
            # 添加到时间线按钮
            if material.type in ("video", "audio", "image"):
                tl_btn = QPushButton("📥")
                tl_btn.setToolTip("添加到时间线")
                tl_btn.setFixedWidth(32)
                tl_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #22c55e; color: white; border: none;
                        border-radius: 4px; padding: 5px 8px; font-size: 14px;
                    }
                    QPushButton:hover { background-color: #16a34a; }
                """)
                def _make_tl_handler(mat):
                    return lambda: self._download_and_add_timeline(mat)
                tl_btn.clicked.connect(_make_tl_handler(material))
                action_layout.addWidget(tl_btn)
            
            self._materials_grid.setCellWidget(row, 6, action_widget)
        
        self._materials_grid.resizeColumnsToContents()
        
        self._page_label.setText(f"第 {self._current_page} 页")
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(len(materials) == self._page_size)
