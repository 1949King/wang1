"""
插件中心模块 (PluginsModule)
=============================
从 modules.py 拆分出来的独立模块文件。

功能:
- 插件管理器集成（PluginManager + PluginStore）
- 插件商店浏览（分类筛选、安装/卸载）
- AI 特效工坊（提示词生成、参数可视化、保存特效预设）
- 插件评分与评价（5星制）
- 插件详情面板（版本/依赖/作者/更新）
- 插件更新检测
- 本地插件导入（.py/.zip）
"""

import json
import os
import time
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QScrollArea, QFrame, QMessageBox, QFileDialog,
    QDialog, QSlider, QLineEdit, QListWidget, QGroupBox,
    QTextEdit, QComboBox,
)
from PySide6.QtCore import Qt

from .base_module import BaseModule

logger = logging.getLogger("AI短剧编辑器.plugins")


class PluginsModule(BaseModule):
    module_id = "plugins"
    module_name = "插件中心"
    module_icon = "🧩"

    AI_EFFECT_PARAM_SPECS = [
        ("brightness", "亮度", 0.0, 2.0, 1.0, 100),
        ("contrast", "对比度", 0.0, 3.0, 1.0, 100),
        ("saturation", "饱和度", 0.0, 3.0, 1.0, 100),
        ("hue", "色相", -180.0, 180.0, 0.0, 1),
        ("exposure", "曝光", -1.0, 1.0, 0.0, 100),
        ("highlights", "高光", -1.0, 1.0, 0.0, 100),
        ("shadows", "阴影", -1.0, 1.0, 0.0, 100),
        ("sharpness", "锐化", 0.0, 2.0, 0.0, 100),
        ("vignette", "暗角", 0.0, 1.0, 0.0, 100),
        ("opacity", "强度", 0.0, 1.0, 1.0, 100),
    ]
    
    # 回退列表：仅真实存在于 app/plugins 的插件（与 plugin_store.OFFICIAL_ITEMS 对齐）
    STORE_PLUGINS = [
        ("🎨", "AI特效制作", "AI工具", "v1.0.0", "免费", "风格迁移/背景替换/超分/美颜（需 torch）"),
        ("💥", "动作特效", "特效工具", "v1.0.0", "免费", "动作场景动感特效"),
        ("😄", "喜剧特效", "特效工具", "v1.0.0", "免费", "喜剧风格氛围特效"),
        ("🌑", "暗调特效", "特效工具", "v1.0.0", "免费", "暗调冷色氛围特效"),
        ("✨", "金光特效", "特效工具", "v1.0.0", "免费", "金色光泽高光特效"),
        ("💡", "高亮特效", "特效工具", "v1.0.0", "免费", "画面高光增强"),
        ("👻", "恐怖特效", "特效工具", "v1.0.0", "免费", "恐怖片氛围特效"),
        ("🌸", "柔光特效", "特效工具", "v1.0.0", "免费", "柔光梦幻氛围"),
        ("🌅", "淡入淡出", "特效工具", "v1.0.0", "免费", "经典淡入淡出转场"),
        ("↔️", "滑动转场", "特效工具", "v1.0.0", "免费", "滑动过渡转场"),
        ("🌫️", "溶解转场", "特效工具", "v1.0.0", "免费", "溶解过渡转场"),
        ("🔄", "翻转转场", "特效工具", "v1.0.0", "免费", "翻转过渡转场"),
        ("📺", "故障转场", "特效工具", "v1.0.0", "免费", "故障抖动转场"),
        ("🌀", "旋转转场", "特效工具", "v1.0.0", "免费", "旋转过渡转场"),
        ("🧹", "擦除转场", "特效工具", "v1.0.0", "免费", "擦除过渡转场"),
        ("🔍", "缩放转场", "特效工具", "v1.0.0", "免费", "缩放过渡转场"),
    ]
    # PluginManager 为空时的兜底展示（勿再写虚构「已安装」）
    INSTALLED = []
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # 初始化插件管理器
        self._init_plugin_manager()
        
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        title = QLabel("🧩 插件中心")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#fff;")
        top_row.addWidget(title)
        top_row.addStretch()
        ai_effect_btn = QPushButton("✨ AI特效工坊")
        ai_effect_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:7px 14px;font-size:11px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        ai_effect_btn.clicked.connect(self._open_ai_effect_tab)
        top_row.addWidget(ai_effect_btn)
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:6px;padding:7px 12px;font-size:11px;}QPushButton:hover{background:#3a3a3a;}")
        refresh_btn.clicked.connect(self._refresh_installed)
        top_row.addWidget(refresh_btn)
        import_btn = QPushButton("导入")
        import_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:6px;padding:7px 16px;font-size:11px;}QPushButton:hover{background:#3a3a3a;}")
        import_btn.clicked.connect(self._import_plugin)
        top_row.addWidget(import_btn)
        layout.addLayout(top_row)
        
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("QTabWidget::pane{border:none;background:transparent;}QTabBar::tab{background:transparent;color:#888;border:none;padding:8px 16px;font-size:11px;}QTabBar::tab:selected{color:#fff;border-bottom:2px solid #1e6bde;}")
        
        self._installed_container = QWidget()
        self._installed_layout = QVBoxLayout(self._installed_container)
        self._installed_layout.setContentsMargins(0, 4, 0, 0)
        self._installed_layout.setSpacing(6)
        installed_scroll = QScrollArea()
        installed_scroll.setWidgetResizable(True)
        installed_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        installed_scroll.setWidget(self._installed_container)
        
        self._tabs.addTab(installed_scroll, "📦 已安装")
        self._ai_effect_tab_index = self._tabs.addTab(self._create_ai_effect_tab(), "✨ AI特效工坊")
        self._store_tab_index = self._tabs.addTab(self._create_store_tab(), "🛍️ 插件商店")
        layout.addWidget(self._tabs, 1)
        
        self._refresh_installed()
        # 刷新后若有加载失败，在状态栏式提示（避免假「已安装」）
        if self._plugin_mgr and hasattr(self._plugin_mgr, "get_load_errors"):
            errs = self._plugin_mgr.get_load_errors()
            if errs and hasattr(self, "_ai_effects_status_label"):
                self._refresh_ai_effects_load_status()
    
    def _init_plugin_manager(self):
        """初始化真实的插件管理器 + 插件商店"""
        try:
            from app.core.plugin_manager import PluginManager
            self._plugin_mgr = PluginManager()
            self._plugin_mgr.load_plugins()
            errs = getattr(self._plugin_mgr, "format_load_errors", lambda: "")()
            if errs:
                logger.warning("插件加载失败摘要:\n%s", errs)
        except Exception as e:
            logger.warning(f"插件管理器初始化失败: {e}")
            self._plugin_mgr = None
        
        # 初始化 PluginStore（商店数据 + 安装/卸载）
        try:
            from .plugin_store import PluginStore, ItemCategory
            self._store = PluginStore()
            self._store.fetch_store_items()  # 尝试拉取远程数据，失败则用本地
        except Exception as e:
            logger.warning(f"插件商店初始化失败: {e}")
            self._store = None
    
    def _refresh_installed(self):
        """刷新已安装列表 — 合并 PluginManager + PluginStore 数据"""
        # 清空现有卡片
        while self._installed_layout.count():
            item = self._installed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 收集 PluginStore 已安装项（按 item_id 去重）
        store_installed = {}
        if self._store:
            try:
                for it in self._store.get_items(installed_only=True):
                    store_installed[it.id] = it
            except Exception as e:
                logger.debug("获取已安装插件列表失败: %s", e)
        
        # 收集 PluginManager 已加载插件
        mgr_names = set()
        if self._plugin_mgr:
            for p in self._plugin_mgr.list_plugins():
                name = getattr(p, "name", "未知插件")
                mgr_names.add(name)
                enabled = getattr(p, "enabled", False)
                has_ui = self._plugin_offers_widget_ui(p)
                card = self._plugin_card(
                    "🧩", name,
                    getattr(p, "description", ""),
                    getattr(p, "version", "v1.0.0"),
                    "打开界面" if (enabled and has_ui) else ("已启用" if enabled else "已禁用"),
                    "#1e6bde" if (enabled and has_ui) else ("#4caf50" if enabled else "#555"),
                    (lambda checked, n=name: self._open_plugin_ui(n))
                    if (enabled and has_ui)
                    else (lambda checked, n=name: self._toggle_plugin(n)),
                    enabled
                )
                self._installed_layout.addWidget(card)
        
        # 追加 PluginStore 已安装但未被 PluginManager 加载的项目
        for item_id, it in store_installed.items():
            if it.name not in mgr_names:
                card = self._plugin_card(
                    "🧩", it.name, it.description, it.version,
                    "已启用", "#4caf50",
                    lambda checked, iid=item_id: self._uninstall_store_item(iid),
                    True
                )
                self._installed_layout.addWidget(card)
                mgr_names.add(it.name)
        
        # 兜底：若两者都为空，显示硬编码（并提示可能加载失败）
        if not mgr_names:
            load_hint = ""
            if self._plugin_mgr and hasattr(self._plugin_mgr, "format_load_errors"):
                load_hint = self._plugin_mgr.format_load_errors()
            if load_hint:
                tip = QLabel("插件加载失败（非空目录）：\n" + load_hint)
                tip.setWordWrap(True)
                tip.setStyleSheet("color:#ef4444;font-size:11px;padding:8px;")
                self._installed_layout.addWidget(tip)
            for icon, name, ver, cat, enabled, desc in self.INSTALLED:
                card = self._plugin_card(
                    icon, name, desc, ver,
                    "已启用" if enabled else "已禁用",
                    "#4caf50" if enabled else "#555",
                    lambda checked, n=name: None,
                    enabled
                )
                self._installed_layout.addWidget(card)
        
        self._installed_layout.addStretch()
        # 触发更新检测（每60秒最多一次）
        if not hasattr(self, '_last_update_check'):
            self._last_update_check = 0
        now = time.time()
        if now - self._last_update_check > 60:
            self._last_update_check = now
            self._check_plugin_updates()
    
    def _toggle_plugin(self, name: str):
        """切换插件启用/禁用状态"""
        if self._plugin_mgr:
            for p in self._plugin_mgr.list_plugins():
                if getattr(p, "name", "") == name:
                    if getattr(p, "enabled", False):
                        self._plugin_mgr.disable_plugin(p.id)
                    else:
                        self._plugin_mgr.enable_plugin(p.id)
                    break
        self._refresh_installed()
    
    def _install_store_item(self, item_id_or_name):
        """安装商店插件 — 优先通过 PluginStore，回退到旧逻辑"""
        # 1) 尝试通过 PluginStore 安装
        if self._store:
            try:
                # 查找 item_id（可能传入的是名称）
                item_id = item_id_or_name
                item = self._store.get_item(item_id_or_name)
                if item is None:
                    # 按名称搜索
                    for it in self._store.get_items():
                        if it.name == item_id_or_name:
                            item = it
                            item_id = it.id
                            break
                
                if item and not item.is_installed:
                    def on_progress(progress, msg):
                        pass  # UI 线程安全提示可后续增强
                    ok, msg = self._store.install_item(item_id, progress_callback=on_progress)
                    if ok:
                        QMessageBox.information(self, "安装成功", f"✅ {item.name} 已安装")
                        self._refresh_installed()
                        return
                    else:
                        QMessageBox.warning(self, "安装失败", msg)
                        return
            except Exception as e:
                logger.warning(f"PluginStore 安装失败 ({item_id_or_name}): {e}")
        
        # 2) 回退到 PluginManager 的简单安装
        if self._plugin_mgr:
            try:
                installed = self._plugin_mgr.install_plugin(item_id_or_name)
                if installed:
                    QMessageBox.information(self, "安装成功", f"✅ {item_id_or_name} 已安装")
                    self._refresh_installed()
                    return
            except Exception as e:
                logger.warning(f"插件安装失败 ({item_id_or_name}): {e}")
        
        # 修复：走到这里说明 PluginStore/PluginManager 两条自动安装路径都
        # 已经失败或不可用，安装并没有在进行中——此前用 information 弹窗
        # + "正在安装..."的措辞，容易让人以为还在等待一个后台过程完成。
        # 改为如实告知安装未自动完成，需要手动放置文件。
        QMessageBox.warning(self, "无法自动安装", f"未能自动安装 {item_id_or_name}。\n\n请手动将插件文件放入 plugins/ 或 plugins/external/ 目录后，\n点击\"导入\"按钮或重启应用加载。")
    
    def _uninstall_store_item(self, item_id_or_name: str):
        """卸载已安装的商店插件（兼容传入真实 item_id 或展示用 name）"""
        if not self._store:
            QMessageBox.warning(self, "卸载失败", "插件商店未就绪")
            return
        item_id = item_id_or_name
        try:
            if self._store.get_item(item_id_or_name) is None:
                # 调用方可能传入的是展示名（如详情弹窗按钮），按 name 反查 id
                for it in self._store.get_items():
                    if getattr(it, "name", None) == item_id_or_name:
                        item_id = it.id
                        break
        except Exception as e:
            logger.debug(f"卸载前反查插件 id 失败 ({item_id_or_name}): {e}")
        try:
            ok, msg = self._store.uninstall_item(item_id)
            if ok:
                QMessageBox.information(self, "卸载成功", "✅ 插件已卸载")
            else:
                QMessageBox.warning(self, "卸载失败", msg)
        except Exception as e:
            QMessageBox.warning(self, "卸载失败", str(e))
        self._refresh_installed()
    
    def _import_plugin(self):
        """导入本地插件文件"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择插件文件", "", "插件文件 (*.py *.zip)")
        if not file_path:
            return
        
        if self._plugin_mgr:
            try:
                if file_path.endswith(".py"):
                    # 复制到插件目录再加载
                    import shutil
                    dest = os.path.join("plugins", os.path.basename(file_path))
                    os.makedirs("plugins", exist_ok=True)
                    shutil.copy2(file_path, dest)
                    self._plugin_mgr.add_plugin_dir("plugins")
                    self._plugin_mgr.load_plugins()
                    QMessageBox.information(self, "导入成功", f"✅ {os.path.basename(file_path)} 已加载")
                    self._refresh_installed()
                else:
                    QMessageBox.information(self, "导入", f"已选择: {os.path.basename(file_path)}\n\n.zip 包部署暂未实现，请手动解压。")
            except Exception as e:
                QMessageBox.warning(self, "导入失败", str(e))
        else:
            # 修复：此前声称"文件路径已记录"，但这里没有任何持久化逻辑——
            # 关闭弹窗后这个路径就彻底丢了，下次插件引擎就绪也不会自动
            # 处理它。如实告知用户需要手动操作。
            QMessageBox.warning(self, "导入失败", f"已选择: {os.path.basename(file_path)}\n\n插件引擎未就绪，无法导入。请稍后重试，或手动将文件复制到 plugins/ 目录。")

    # ── 插件详情 ──

    def _show_plugin_detail(self, name: str, icon: str, desc: str, ver_info: str, installed: bool):
        """点击插件卡片 → 弹出详情面板（版本/描述/依赖/评分/操作/评价）"""
        from PySide6.QtWidgets import QDialog, QSlider
        from PySide6.QtCore import Qt as QtCore

        # 解析版本号
        ver_parts = ver_info.strip().split("\n")
        version = ver_parts[0] if ver_parts else "v1.0.0"
        price = ver_parts[1] if len(ver_parts) > 1 else ""

        dialog = QDialog(self)
        dialog.setWindowTitle(f"插件详情 - {name}")
        dialog.setMinimumSize(460, 520)
        dialog.setStyleSheet("QDialog{background:#121212;}")
        dlo = QVBoxLayout(dialog)
        dlo.setContentsMargins(24, 24, 24, 24)
        dlo.setSpacing(12)

        # 标题行
        header = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size:32px;")
        header.addWidget(icon_lbl)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-size:18px;font-weight:bold;color:#fff;")
        header.addWidget(name_lbl)
        header.addStretch()
        if installed:
            badge = QLabel("已安装")
            badge.setStyleSheet("background:#22c55e;color:#fff;font-size:10px;padding:2px 8px;border-radius:4px;")
            header.addWidget(badge)
        dlo.addLayout(header)

        # 版本和价格
        info_layout = QHBoxLayout()
        ver_lbl = QLabel(f"版本: {version}")
        ver_lbl.setStyleSheet("color:#888;font-size:12px;")
        info_layout.addWidget(ver_lbl)
        if price:
            price_lbl = QLabel(price)
            price_lbl.setStyleSheet("color:#f59e0b;font-size:12px;font-weight:600;")
            info_layout.addWidget(price_lbl)
        info_layout.addStretch()
        dlo.addLayout(info_layout)

        # 描述
        desc_group = QGroupBox("描述")
        desc_group.setStyleSheet("QGroupBox{color:#aaa;font-size:11px;border:1px solid #1e1e1e;border-radius:6px;margin-top:6px;padding-top:12px;background:#0a0a0a;} QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
        desc_layout = QVBoxLayout(desc_group)
        desc_lbl = QLabel(desc or "暂无描述")
        desc_lbl.setStyleSheet("color:#ccc;font-size:12px;")
        desc_lbl.setWordWrap(True)
        desc_layout.addWidget(desc_lbl)
        dlo.addWidget(desc_group)

        # ── 评分区（12.6 插件评价/评分） ──
        rating_group = QGroupBox("⭐ 评分与评价")
        rating_group.setStyleSheet("QGroupBox{color:#aaa;font-size:11px;border:1px solid #1e1e1e;border-radius:6px;margin-top:6px;padding-top:12px;background:#0a0a0a;} QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
        rating_lo = QVBoxLayout(rating_group)
        rating_lo.setSpacing(8)

        # 当前评分显示
        self._rating_info_lbl = QLabel("暂无评分")
        self._rating_info_lbl.setStyleSheet("color:#f59e0b;font-size:16px;font-weight:bold;")
        rating_lo.addWidget(self._rating_info_lbl)
        self._load_plugin_rating(name)

        # 星级评分滑块 (1-5星)
        rate_row = QHBoxLayout()
        rate_row.setSpacing(8)
        rate_label = QLabel("我的评分:")
        rate_label.setStyleSheet("color:#888;font-size:11px;")
        rate_row.addWidget(rate_label)

        self._star_btns = []
        star_bar = QHBoxLayout()
        star_bar.setSpacing(4)
        for i in range(1, 6):
            star_btn = QPushButton("☆")
            star_btn.setFixedSize(32, 32)
            star_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #666; border: none;
                    font-size: 18px;
                }
                QPushButton:hover { color: #f59e0b; }
            """)
            star_btn.setProperty("star_value", i)
            star_btn.clicked.connect(lambda checked, v=i: self._set_star_rating(name, v))
            self._star_btns.append(star_btn)
            star_bar.addWidget(star_btn)
        # 加载已保存评分
        self._restore_plugin_rating(name)
        rate_row.addLayout(star_bar)
        rate_row.addStretch()
        rating_lo.addLayout(rate_row)

        # 评价输入
        review_row = QHBoxLayout()
        self._review_input = QLineEdit()
        self._review_input.setPlaceholderText("写一条评价...")
        self._review_input.setStyleSheet("""
            QLineEdit {
                background: #0a0a0a; color: #ccc; border: 1px solid #252525;
                border-radius: 6px; padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #1e6bde; }
        """)
        review_row.addWidget(self._review_input, 1)
        submit_btn = QPushButton("发布")
        submit_btn.setStyleSheet("""
            QPushButton {
                background: #1e6bde; color: #fff; border: none;
                border-radius: 6px; padding: 8px 16px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background: #1557b0; }
        """)
        submit_btn.clicked.connect(lambda: self._submit_plugin_review(name))
        review_row.addWidget(submit_btn)
        rating_lo.addLayout(review_row)

        # 评价列表
        reviews_label = QLabel("用户评价:")
        reviews_label.setStyleSheet("color:#666;font-size:10px;")
        rating_lo.addWidget(reviews_label)

        self._reviews_list = QListWidget()
        self._reviews_list.setMaximumHeight(100)
        self._reviews_list.setStyleSheet("""
            QListWidget {
                background: #0a0a0a; border: 1px solid #1e1e1e; border-radius: 4px;
                font-size: 11px;
            }
            QListWidget::item { color: #aaa; padding: 4px 8px; }
        """)
        rating_lo.addWidget(self._reviews_list)
        self._load_plugin_reviews(name)

        dlo.addWidget(rating_group)

        # 更多信息
        extra_group = QGroupBox("更多信息")
        extra_group.setStyleSheet("QGroupBox{color:#aaa;font-size:11px;border:1px solid #1e1e1e;border-radius:6px;margin-top:6px;padding-top:12px;background:#0a0a0a;} QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
        extra_lo = QVBoxLayout(extra_group)
        for label, value in [("作者", "拾光剪影团队"), ("依赖", "无特殊依赖"), ("更新日期", "2026-06")]:
            row = QHBoxLayout()
            kl = QLabel(label)
            kl.setStyleSheet("color:#666;font-size:11px;min-width:60px;")
            row.addWidget(kl)
            vl = QLabel(value)
            vl.setStyleSheet("color:#ccc;font-size:11px;")
            row.addWidget(vl)
            row.addStretch()
            extra_lo.addLayout(row)
        dlo.addWidget(extra_group)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if not installed:
            install_btn = QPushButton("⬇ 安装")
            install_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px 20px;font-size:12px;font-weight:600;} QPushButton:hover{background:#1557b0;}")
            install_btn.clicked.connect(lambda: (self._install_store_item(name), dialog.accept()))
            btn_row.addWidget(install_btn)
        else:
            if self._plugin_has_ui(name):
                open_btn = QPushButton("打开界面")
                open_btn.setStyleSheet(
                    "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;"
                    "padding:8px 20px;font-size:12px;font-weight:600;}"
                    "QPushButton:hover{background:#1557b0;}"
                )
                open_btn.clicked.connect(
                    lambda _=False, n=name: (dialog.accept(), self._open_plugin_ui(n))
                )
                btn_row.addWidget(open_btn)
            uninstall_btn = QPushButton("🗑 卸载")
            uninstall_btn.setStyleSheet("QPushButton{background:#f44336;color:#fff;border:none;border-radius:6px;padding:8px 20px;font-size:12px;font-weight:600;} QPushButton:hover{background:#d32f2f;}")
            uninstall_btn.clicked.connect(lambda: (self._uninstall_store_item(name), dialog.accept()))
            btn_row.addWidget(uninstall_btn)
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:6px;padding:8px 20px;font-size:12px;} QPushButton:hover{background:#3a3a3a;}")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)
        dlo.addLayout(btn_row)

        dialog.exec()

    def _find_plugin_by_name(self, name: str):
        """按显示名查找已加载插件实例。"""
        if not self._plugin_mgr:
            return None
        plugins = self._plugin_mgr.list_plugins()
        if not plugins:
            return None
        # 兼容异常返回（字符串列表等）
        if all(isinstance(p, str) for p in plugins):
            return None
        for p in plugins:
            if getattr(p, "name", None) == name:
                return p
        return None

    # >>> FROZEN:plugin-host-ui:plugins-host BEGIN
    def _plugin_offers_widget_ui(self, plugin) -> bool:
        """是否提供可嵌入的 QWidget 界面。

        排除 AI 特效等：有 apply_effect 且 run() 返回 bool，应走「AI 特效工坊」专用入口。
        """
        if plugin is None or not callable(getattr(plugin, "run", None)):
            return False
        cfg = {}
        if callable(getattr(plugin, "get_ui_config", None)):
            try:
                cfg = plugin.get_ui_config() or {}
            except Exception:
                cfg = {}
        wc = str(cfg.get("widget_class") or "")
        # 特效管线插件：通用打开会误调 run()→bool
        if callable(getattr(plugin, "apply_effect", None)):
            return False
        if wc:
            return True
        # 旧式 UI 插件：实例上已有 _widget 槽位
        return hasattr(plugin, "_widget")

    def _plugin_has_ui(self, name: str) -> bool:
        """已安装且可打开可视化界面。"""
        return self._plugin_offers_widget_ui(self._find_plugin_by_name(name))

    def _ensure_plugin_initialized(self, plugin) -> None:
        """PluginManager 加载后未必调用 initialize；打开 UI 前补一次。"""
        if not callable(getattr(plugin, "initialize", None)):
            return
        ctx = getattr(plugin, "_context", None) or {}
        if not isinstance(ctx, dict):
            ctx = {}
        ctx = {**ctx, "parent_widget": self}
        # 缺 _widget / 未标记 initialized 时必须 initialize（勿默认 True 跳过）
        need = (not getattr(plugin, "_initialized", False)) or (not hasattr(plugin, "_widget"))
        if need:
            plugin.initialize(ctx)
        else:
            try:
                plugin._context = ctx
            except Exception as e:
                logger.debug("设置插件上下文失败: %s", e)




    def _open_plugin_ui(self, name: str):
        """打开插件可视化界面。"""
        plugin = self._find_plugin_by_name(name)
        if plugin is None:
            QMessageBox.warning(
                self, "无法打开", f"插件「{name}」未加载，请先在已安装列表中启用。"
            )
            return
        if not self._plugin_offers_widget_ui(plugin):
            QMessageBox.information(self, name, "该插件没有可视化界面（可能是特效/批处理插件）。")
            return
        try:
            self._ensure_plugin_initialized(plugin)
            result = plugin.run()
            if not isinstance(result, QWidget):
                QMessageBox.information(self, name, "插件已运行（无可视化界面）。")
                return
            dlg = QDialog(self)
            dlg.setWindowTitle(name)
            dlg.resize(1000, 720)
            dlg.setStyleSheet("QDialog{background:#121212;}")
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            result.setParent(dlg)
            lay.addWidget(result)
            result.show()

            def _detach(_result=0, w=result):
                try:
                    w.setParent(None)
                    w.hide()
                except Exception as e:
                    logger.debug("插件窗口分离失败: %s", e)

            dlg.finished.connect(_detach)
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "打开插件界面失败", str(e))
    # <<< FROZEN:plugin-host-ui:plugins-host END

    # ── 插件评分/评价存储 ──

    @staticmethod
    def _ratings_file() -> str:
        """插件评分持久化文件路径"""
        return os.path.join(os.path.dirname(__file__), "..", "data", "plugin_ratings.json")

    def _load_plugin_rating(self, plugin_name: str):
        """加载插件评分并更新UI"""
        try:
            ratings = {}
            path = self._ratings_file()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    ratings = json.load(f)
            pdata = ratings.get(plugin_name, {})
            avg = pdata.get("avg_rating", 0)
            count = pdata.get("count", 0)
            if count > 0:
                stars = "⭐" * int(round(avg)) + "☆" * (5 - int(round(avg)))
                self._rating_info_lbl.setText(f"{stars}  {avg:.1f}/5  ({count}人评价)")
            else:
                self._rating_info_lbl.setText("暂无评分")
        except Exception as e:
            logger.debug("加载插件评分失败: %s", e)

    def _restore_plugin_rating(self, plugin_name: str):
        """恢复用户对当前插件的评分（点亮星星）"""
        try:
            path = self._ratings_file()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    ratings = json.load(f)
                pdata = ratings.get(plugin_name, {})
                my_rating = pdata.get("user_rating", 0)
                for i, btn in enumerate(self._star_btns):
                    if i < my_rating:
                        btn.setText("★")
                        btn.setStyleSheet("QPushButton{background:transparent;color:#f59e0b;border:none;font-size:18px;}")
        except Exception as e:
            logger.debug("恢复插件评分失败: %s", e)

    def _set_star_rating(self, plugin_name: str, value: int):
        """用户设置星级评分"""
        for i, btn in enumerate(self._star_btns):
            if i < value:
                btn.setText("★")
                btn.setStyleSheet("QPushButton{background:transparent;color:#f59e0b;border:none;font-size:18px;}")
            else:
                btn.setText("☆")
                btn.setStyleSheet("QPushButton{background:transparent;color:#666;border:none;font-size:18px;}")
        # 持久化
        self._save_plugin_rating(plugin_name, value)

    def _save_plugin_rating(self, plugin_name: str, rating: int):
        """保存用户评分到本地JSON"""
        try:
            path = self._ratings_file()
            ratings = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    ratings = json.load(f)
            pdata = ratings.get(plugin_name, {"ratings": [], "reviews": [], "avg_rating": 0, "count": 0, "user_rating": 0})
            pdata["user_rating"] = rating
            all_ratings = list(pdata.get("ratings", []))
            all_ratings.append(rating)
            pdata["ratings"] = all_ratings
            pdata["count"] = len(all_ratings)
            pdata["avg_rating"] = round(sum(all_ratings) / len(all_ratings), 1) if all_ratings else 0
            ratings[plugin_name] = pdata
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(ratings, f, ensure_ascii=False, indent=2)
            self._load_plugin_rating(plugin_name)
        except Exception as e:
            logger.warning(f"保存插件评分失败: {e}")

    def _load_plugin_reviews(self, plugin_name: str):
        """加载插件评价列表"""
        self._reviews_list.clear()
        try:
            path = self._ratings_file()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    ratings = json.load(f)
                pdata = ratings.get(plugin_name, {})
                for review in pdata.get("reviews", [])[-10:]:  # 最近10条
                    stars = "⭐" * int(review.get("rating", 0))
                    self._reviews_list.addItem(f"{stars} {review.get('text', '')}")
        except Exception as e:
            logger.debug("加载插件评价失败: %s", e)

    def _submit_plugin_review(self, plugin_name: str):
        """提交插件评价"""
        text = self._review_input.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入评价内容")
            return
        # 获取当前评分
        my_rating = 0
        for i, btn in enumerate(self._star_btns):
            if btn.text() == "★":
                my_rating = i + 1
        if my_rating == 0:
            QMessageBox.warning(self, "提示", "请先给出星级评分")
            return
        try:
            path = self._ratings_file()
            ratings = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    ratings = json.load(f)
            pdata = ratings.get(plugin_name, {"ratings": [], "reviews": [], "avg_rating": 0, "count": 0, "user_rating": 0})
            pdata.setdefault("reviews", []).append({"rating": my_rating, "text": text, "time": time.strftime("%Y-%m-%d %H:%M:%S")})
            ratings[plugin_name] = pdata
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(ratings, f, ensure_ascii=False, indent=2)
            self._review_input.clear()
            self._load_plugin_reviews(plugin_name)
            self._load_plugin_rating(plugin_name)
            QMessageBox.information(self, "成功", "✅ 评价已发布")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"发布失败: {e}")

    # ── 插件更新检测 ──

    def _check_plugin_updates(self):
        """检查已安装插件是否有可用更新，有则通知用户"""
        updates_available = []

        if self._store:
            try:
                store_items = {it.name: it for it in self._store.get_items(installed_only=True)}
                for p in self._plugin_mgr.list_plugins() if self._plugin_mgr else []:
                    name = getattr(p, "name", "")
                    installed_ver = getattr(p, "version", "v1.0.0")
                    if name in store_items:
                        store_ver = store_items[name].version
                        if store_ver != installed_ver and self._version_gt(store_ver, installed_ver):
                            updates_available.append((name, installed_ver, store_ver))
            except Exception as e:
                logger.debug("插件更新检测失败: %s", e)

        if updates_available:
            msg = "发现以下插件可更新:\n\n"
            for name, old_ver, new_ver in updates_available:
                msg += f"  📦 {name}: {old_ver} → {new_ver}\n"
            msg += "\n是否前往商店更新？"
            reply = QMessageBox.question(self, "插件更新", msg,
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self._tabs.setCurrentIndex(getattr(self, "_store_tab_index", 3))  # 切换到商店标签

    @staticmethod
    def _version_gt(ver_a: str, ver_b: str) -> bool:
        """比较版本号 ver_a > ver_b"""
        def _parse(v):
            v = v.lstrip("vV")
            parts = []
            for p in v.split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return tuple(parts)
        try:
            return _parse(ver_a) > _parse(ver_b)
        except Exception:
            return False

    def _open_ai_effect_tab(self):
        """打开 AI 特效工坊标签页"""
        if hasattr(self, "_tabs") and hasattr(self, "_ai_effect_tab_index"):
            self._tabs.setCurrentIndex(self._ai_effect_tab_index)
            self._refresh_ai_effects_load_status()

    def _refresh_ai_effects_load_status(self):
        """检测 AI 特效插件能否加载，并更新状态条。"""
        label = getattr(self, "_ai_effects_status_label", None)
        if label is None:
            return
        ok, detail = self._probe_ai_effects_plugin()
        if ok:
            label.setText("● 深度学习特效插件：可加载")
            label.setStyleSheet("color:#22c55e;font-size:11px;font-weight:600;")
            label.setToolTip(detail)
        else:
            label.setText("● 深度学习特效插件：加载失败（点「打开面板」看详情）")
            label.setStyleSheet("color:#ef4444;font-size:11px;")
            label.setToolTip(detail)
        # 同时汇总 PluginManager 其它加载错误
        if self._plugin_mgr and hasattr(self._plugin_mgr, "format_load_errors"):
            errs = self._plugin_mgr.format_load_errors()
            if errs:
                tip = (label.toolTip() or "") + "\n\n其它插件加载失败:\n" + errs
                label.setToolTip(tip.strip())

    def _probe_ai_effects_plugin(self):
        """返回 (ok: bool, detail: str)。只测加载，不重做特效算法。"""
        try:
            from app.plugins import ai_effects_plugin as pkg
            err = getattr(pkg, "PLUGIN_LOAD_ERROR", "") or ""
            Plugin = getattr(pkg, "Plugin", None)
            Widget = getattr(pkg, "AIEffectsWidget", None)
            if err or Plugin is None:
                return False, err or "Plugin 入口为 None（导入失败）"
            # 尝试实例化（不强制 initialize，避免立刻下模型）
            inst = Plugin()
            name = getattr(inst, "name", "") or "AI特效制作"
            detail = f"已导入 {name}"
            if Widget is None:
                # main 里懒加载 UI
                try:
                    from app.plugins.ai_effects_plugin.main import _load_ai_effects_widget
                    Widget = _load_ai_effects_widget()
                except Exception as e:
                    return False, f"插件类可导入，但 UI 失败: {e}"
            if Widget is None:
                return False, "AIEffectsWidget 不可用"
            return True, detail
        except Exception as e:
            return False, f"导入失败: {e}"

    def _open_ai_effects_studio(self):
        """打开真实深度学习特效面板；失败则明文提示。"""
        ok, detail = self._probe_ai_effects_plugin()
        if not ok:
            QMessageBox.warning(
                self,
                "AI 特效插件无法加载",
                f"{detail}\n\n"
                "常见原因：缺依赖（torch / opencv / Pillow）、插件包导入异常。\n"
                "本页下方「参数工坊」仍可生成调色预设，不依赖该插件。",
            )
            self._refresh_ai_effects_load_status()
            return
        try:
            from app.plugins.ai_effects_plugin.main import Plugin, _load_ai_effects_widget
            plugin = Plugin()
            # 轻量 initialize；失败也继续尝试开 UI
            if not getattr(plugin, "_initialized", False):
                init_ok = plugin.initialize({})
                if not init_ok:
                    partial = getattr(plugin, "_last_error", "") or "initialize 返回 False"
                    QMessageBox.warning(
                        self,
                        "AI 特效初始化未完全成功",
                        f"{partial}\n\n仍将尝试打开面板；部分特效可能不可用。",
                    )
            Widget = _load_ai_effects_widget()
            dlg = QDialog(self)
            dlg.setWindowTitle("AI 特效制作")
            dlg.resize(900, 640)
            lay = QVBoxLayout(dlg)
            lay.addWidget(Widget(plugin, dlg))
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(
                self,
                "打开 AI 特效面板失败",
                f"{e}\n\n请查看日志；特效算法本身未改动，仅加载链路。",
            )
        self._refresh_ai_effects_load_status()

    def _create_ai_effect_tab(self):
        """创建 AI 特效工坊可视化界面"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        # 加载状态 + 打开真实插件面板
        status_row = QHBoxLayout()
        self._ai_effects_status_label = QLabel("● 深度学习特效插件：检测中…")
        self._ai_effects_status_label.setStyleSheet("color:#888;font-size:11px;")
        self._ai_effects_status_label.setWordWrap(True)
        status_row.addWidget(self._ai_effects_status_label, 1)
        open_studio_btn = QPushButton("打开深度学习特效面板")
        open_studio_btn.setStyleSheet(
            "QPushButton{background:#7c3aed;color:#fff;border:none;border-radius:6px;"
            "padding:7px 12px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#6d28d9;}"
        )
        open_studio_btn.clicked.connect(self._open_ai_effects_studio)
        status_row.addWidget(open_studio_btn)
        layout.addLayout(status_row)

        hero = QFrame()
        hero.setStyleSheet("QFrame{background:#121212;border:1px solid #1e1e1e;border-radius:12px;}")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(8)

        title = QLabel("✨ AI 特效参数工坊（调色预设）")
        title.setStyleSheet("color:#fff;font-size:18px;font-weight:bold;")
        hero_layout.addWidget(title)

        desc = QLabel(
            "下方用于生成调色/滤镜参数并写入 effects.json。"
            "深度学习特效（超分/美颜等）请点上方「打开深度学习特效面板」。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#888;font-size:12px;line-height:18px;")
        hero_layout.addWidget(desc)
        layout.addWidget(hero)

        config_group = QGroupBox("基础信息")
        config_group.setStyleSheet("QGroupBox{color:#aaa;font-size:11px;border:1px solid #1e1e1e;border-radius:8px;margin-top:8px;padding-top:14px;background:#0f0f0f;} QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(8)

        name_row = QHBoxLayout()
        name_label = QLabel("特效名称")
        name_label.setStyleSheet("color:#888;font-size:11px;min-width:64px;")
        name_row.addWidget(name_label)
        self._ai_effect_name_input = QLineEdit()
        self._ai_effect_name_input.setPlaceholderText("例如：爆款短剧冷白光")
        self._ai_effect_name_input.setStyleSheet("QLineEdit{background:#0a0a0a;color:#ccc;border:1px solid #252525;border-radius:6px;padding:8px 10px;font-size:12px;}QLineEdit:focus{border-color:#1e6bde;}")
        name_row.addWidget(self._ai_effect_name_input, 1)
        config_layout.addLayout(name_row)

        select_row = QHBoxLayout()
        category_label = QLabel("分类")
        category_label.setStyleSheet("color:#888;font-size:11px;min-width:64px;")
        select_row.addWidget(category_label)
        self._ai_effect_category_combo = QComboBox()
        self._ai_effect_category_combo.addItem("调色", "color")
        self._ai_effect_category_combo.addItem("滤镜", "filter")
        self._ai_effect_category_combo.addItem("风格化", "style")
        self._ai_effect_category_combo.setStyleSheet("QComboBox{background:#0a0a0a;color:#ccc;border:1px solid #252525;border-radius:6px;padding:6px 10px;font-size:12px;}")
        select_row.addWidget(self._ai_effect_category_combo)

        style_label = QLabel("AI风格")
        style_label.setStyleSheet("color:#888;font-size:11px;margin-left:12px;")
        select_row.addWidget(style_label)
        self._ai_effect_style_combo = QComboBox()
        self._ai_effect_style_combo.addItem("电影质感", "cinematic")
        self._ai_effect_style_combo.addItem("爆款短剧", "viral")
        self._ai_effect_style_combo.addItem("赛博霓虹", "neon")
        self._ai_effect_style_combo.addItem("温暖治愈", "warm")
        self._ai_effect_style_combo.addItem("复古胶片", "retro")
        self._ai_effect_style_combo.setStyleSheet("QComboBox{background:#0a0a0a;color:#ccc;border:1px solid #252525;border-radius:6px;padding:6px 10px;font-size:12px;}")
        select_row.addWidget(self._ai_effect_style_combo)
        select_row.addStretch()
        config_layout.addLayout(select_row)

        prompt_label = QLabel("提示词")
        prompt_label.setStyleSheet("color:#888;font-size:11px;")
        config_layout.addWidget(prompt_label)
        self._ai_effect_prompt_input = QTextEdit()
        self._ai_effect_prompt_input.setPlaceholderText("例如：悬疑短剧，夜景，冷色调，高对比，人物边缘更清晰，带一点暗角")
        self._ai_effect_prompt_input.setFixedHeight(88)
        self._ai_effect_prompt_input.setStyleSheet("QTextEdit{background:#0a0a0a;color:#ccc;border:1px solid #252525;border-radius:6px;padding:8px 10px;font-size:12px;}QTextEdit:focus{border-color:#1e6bde;}")
        self._ai_effect_prompt_input.textChanged.connect(self._update_ai_effect_preview)
        config_layout.addWidget(self._ai_effect_prompt_input)

        btn_row = QHBoxLayout()
        generate_btn = QPushButton("AI 生成参数")
        generate_btn.setStyleSheet("QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;padding:8px 18px;font-size:12px;font-weight:600;}QPushButton:hover{background:#1557b0;}")
        generate_btn.clicked.connect(self._generate_ai_effect_params)
        btn_row.addWidget(generate_btn)
        save_btn = QPushButton("保存为特效预设")
        save_btn.setStyleSheet("QPushButton{background:#22c55e;color:#fff;border:none;border-radius:6px;padding:8px 18px;font-size:12px;font-weight:600;}QPushButton:hover{background:#16a34a;}")
        save_btn.clicked.connect(self._save_ai_effect_preset)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        config_layout.addLayout(btn_row)
        layout.addWidget(config_group)

        params_group = QGroupBox("可视化参数")
        params_group.setStyleSheet("QGroupBox{color:#aaa;font-size:11px;border:1px solid #1e1e1e;border-radius:8px;margin-top:8px;padding-top:14px;background:#0f0f0f;} QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}")
        params_layout = QVBoxLayout(params_group)
        params_layout.setSpacing(8)

        self._ai_effect_sliders = {}
        self._ai_effect_value_labels = {}
        for key, label, min_value, max_value, default, scale in self.AI_EFFECT_PARAM_SPECS:
            row = QHBoxLayout()
            text_label = QLabel(label)
            text_label.setStyleSheet("color:#888;font-size:11px;min-width:54px;")
            row.addWidget(text_label)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(int(min_value * scale), int(max_value * scale))
            slider.setValue(int(default * scale))
            slider.setStyleSheet("QSlider::groove:horizontal{height:4px;background:#252525;border-radius:2px;}QSlider::handle:horizontal{background:#1e6bde;width:14px;margin:-5px 0;border-radius:7px;}QSlider::sub-page:horizontal{background:#1e6bde;border-radius:2px;}")
            slider.valueChanged.connect(lambda value, k=key: self._on_ai_effect_slider_changed(k, value))
            row.addWidget(slider, 1)

            value_label = QLabel(self._format_ai_effect_value(key, slider.value()))
            value_label.setStyleSheet("color:#ccc;font-size:11px;min-width:46px;")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(value_label)

            self._ai_effect_sliders[key] = slider
            self._ai_effect_value_labels[key] = value_label
            params_layout.addLayout(row)
        layout.addWidget(params_group)

        preview_group = QGroupBox("预览摘要")
        preview_group.setStyleSheet("QGroupBox{color:#aaa;font-size:11px;border:1px solid #1e1e1e;border-radius:8px;margin-top:8px;padding-top:14px;background:#0f0f0f;} QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}")
        preview_layout = QVBoxLayout(preview_group)
        self._ai_effect_preview_label = QLabel()
        self._ai_effect_preview_label.setWordWrap(True)
        self._ai_effect_preview_label.setStyleSheet("color:#ccc;font-size:12px;line-height:18px;padding:4px;")
        preview_layout.addWidget(self._ai_effect_preview_label)
        layout.addWidget(preview_group)
        layout.addStretch()

        scroll.setWidget(container)
        self._update_ai_effect_preview()
        try:
            self._refresh_ai_effects_load_status()
        except Exception as e:
            logger.warning("AI特效加载状态刷新失败: %s", e)
        return scroll

    def _on_ai_effect_slider_changed(self, key: str, value: int):
        """同步 AI 特效参数数值和预览摘要"""
        label = self._ai_effect_value_labels.get(key)
        if label:
            label.setText(self._format_ai_effect_value(key, value))
        self._update_ai_effect_preview()

    def _format_ai_effect_value(self, key: str, raw_value: int) -> str:
        """格式化滑块数值"""
        spec = self._get_ai_effect_spec(key)
        if not spec:
            return str(raw_value)
        scale = spec[-1]
        value = raw_value / scale
        if scale == 1:
            return str(int(value))
        return f"{value:.2f}"

    def _get_ai_effect_spec(self, key: str):
        """获取 AI 特效参数定义"""
        for spec in self.AI_EFFECT_PARAM_SPECS:
            if spec[0] == key:
                return spec
        return None

    def _get_ai_effect_values(self) -> dict:
        """读取当前 AI 特效参数值"""
        values = {}
        for key, _label, _min_value, _max_value, _default, scale in self.AI_EFFECT_PARAM_SPECS:
            slider = self._ai_effect_sliders.get(key)
            if slider:
                values[key] = round(slider.value() / scale, 3)
        return values

    def _generate_ai_effect_params(self):
        """根据提示词和风格生成一组可编辑的特效参数"""
        prompt = self._ai_effect_prompt_input.toPlainText().strip().lower()
        style = self._ai_effect_style_combo.currentData()

        values = {key: default for key, _label, _min_value, _max_value, default, _scale in self.AI_EFFECT_PARAM_SPECS}
        if style == "cinematic":
            values.update({"contrast": 1.25, "saturation": 0.9, "highlights": -0.2, "shadows": -0.15, "sharpness": 0.45, "vignette": 0.28})
        elif style == "viral":
            values.update({"brightness": 1.08, "contrast": 1.18, "saturation": 1.35, "sharpness": 0.55, "opacity": 0.95})
        elif style == "neon":
            values.update({"contrast": 1.35, "saturation": 1.75, "hue": 18, "exposure": 0.1, "sharpness": 0.65, "vignette": 0.18})
        elif style == "warm":
            values.update({"brightness": 1.12, "contrast": 1.08, "saturation": 1.18, "hue": 8, "highlights": 0.1, "shadows": 0.12})
        elif style == "retro":
            values.update({"brightness": 0.96, "contrast": 1.12, "saturation": 0.78, "hue": 12, "sharpness": 0.18, "vignette": 0.35})

        if any(word in prompt for word in ("冷", "悬疑", "夜", "蓝", "暗")):
            values.update({"brightness": min(values["brightness"], 0.95), "contrast": max(values["contrast"], 1.25), "hue": -10, "shadows": -0.25, "vignette": max(values["vignette"], 0.3)})
        if any(word in prompt for word in ("暖", "治愈", "阳光", "柔和")):
            values.update({"brightness": max(values["brightness"], 1.12), "saturation": max(values["saturation"], 1.15), "hue": 10, "highlights": 0.12})
        if any(word in prompt for word in ("清晰", "锐", "质感", "细节")):
            values["sharpness"] = max(values["sharpness"], 0.75)
        if any(word in prompt for word in ("黑白", "灰", "压抑")):
            values.update({"saturation": 0.25, "contrast": max(values["contrast"], 1.3)})
        if any(word in prompt for word in ("淡", "梦幻", "轻")):
            values.update({"contrast": min(values["contrast"], 0.95), "opacity": 0.82, "highlights": 0.18})

        for key, value in values.items():
            spec = self._get_ai_effect_spec(key)
            slider = self._ai_effect_sliders.get(key)
            if spec and slider:
                _param, _label, min_value, max_value, _default, scale = spec
                safe_value = max(min_value, min(max_value, value))
                slider.setValue(int(round(safe_value * scale)))

        if not self._ai_effect_name_input.text().strip():
            self._ai_effect_name_input.setText(self._suggest_ai_effect_name(prompt, style))
        self._update_ai_effect_preview()

    def _suggest_ai_effect_name(self, prompt: str, style: str) -> str:
        """按风格和提示词生成默认特效名"""
        style_names = {
            "cinematic": "电影质感",
            "viral": "爆款短剧",
            "neon": "赛博霓虹",
            "warm": "温暖治愈",
            "retro": "复古胶片",
        }
        if "悬疑" in prompt or "夜" in prompt:
            return f"{style_names.get(style, 'AI')}悬疑光影"
        if "暖" in prompt or "治愈" in prompt:
            return f"{style_names.get(style, 'AI')}暖光"
        return f"{style_names.get(style, 'AI')}特效"

    def _update_ai_effect_preview(self):
        """刷新 AI 特效预览摘要"""
        if not hasattr(self, "_ai_effect_preview_label"):
            return
        values = self._get_ai_effect_values() if hasattr(self, "_ai_effect_sliders") else {}
        changed = []
        for key, label, _min_value, _max_value, default, _scale in self.AI_EFFECT_PARAM_SPECS:
            value = values.get(key, default)
            if abs(value - default) >= 0.01:
                changed.append(f"{label} {value:g}")
        prompt = self._ai_effect_prompt_input.toPlainText().strip() if hasattr(self, "_ai_effect_prompt_input") else ""
        summary = "、".join(changed[:8]) if changed else "当前为基础原始参数，可输入提示词后点击 AI 生成参数。"
        if prompt:
            summary = f"提示词：{prompt}\n参数变化：{summary}"
        self._ai_effect_preview_label.setText(summary)

    def _save_ai_effect_preset(self):
        """保存 AI 特效为现有 effects.json 可读取的预设"""
        name = self._ai_effect_name_input.text().strip()
        prompt = self._ai_effect_prompt_input.toPlainText().strip()
        if not name:
            QMessageBox.warning(self, "保存失败", "请先填写特效名称")
            return
        if not prompt:
            QMessageBox.warning(self, "保存失败", "请先填写 AI 提示词，便于后续追溯特效来源")
            return

        effect_id = self._make_ai_effect_id(name)
        values = self._get_ai_effect_values()
        parameters = {}
        for key, _label, min_value, max_value, _default, scale in self.AI_EFFECT_PARAM_SPECS:
            step = 1.0 / scale
            parameters[key] = {
                "type": "float",
                "default": values.get(key, _default),
                "min": min_value,
                "max": max_value,
                "step": step,
            }

        effect_data = {
            "name": name,
            "category": self._ai_effect_category_combo.currentData() or "filter",
            "description": f"AI生成特效：{prompt[:120]}",
            "parameters": parameters,
            "ai_prompt": prompt,
            "ai_style": self._ai_effect_style_combo.currentData(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        saved_files = []
        try:
            for path in self._effect_preset_files():
                data = {}
                if path.exists():
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                data[effect_id] = effect_data
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                saved_files.append(str(path))
        except Exception as e:
            logger.warning(f"保存 AI 特效预设失败: {e}")
            QMessageBox.warning(self, "保存失败", f"写入特效预设失败：{e}")
            return

        QMessageBox.information(self, "保存成功", f"✅ 已保存 AI 特效预设：{name}\nID: {effect_id}\n\n写入文件：\n" + "\n".join(saved_files))

    def _make_ai_effect_id(self, name: str) -> str:
        """生成稳定的 AI 特效预设 ID"""
        safe = "".join(ch.lower() if ch.isascii() and ch.isalnum() else "_" for ch in name)
        safe = "_".join(part for part in safe.split("_") if part)
        if not safe:
            safe = str(int(time.time()))
        return f"ai_{safe}"

    def _effect_preset_files(self) -> list:
        """返回需要同步写入的特效预设文件"""
        current = Path(__file__).resolve()
        project_root = current.parents[3]
        candidates = [
            project_root / "effects" / "effects.json",
            current.parent / "effects" / "effects.json",
        ]
        result = []
        for path in candidates:
            if path not in result and (path.exists() or not result):
                result.append(path)
        return result
    
    def _plugin_card(self, icon, name, detail, extra, btn_text, btn_color, callback, enabled=True):
        card = QFrame()
        card.setStyleSheet("QFrame{background:#121212;border:1px solid #1e1e1e;border-radius:10px;}" + ("opacity:0.6;" if not enabled else ""))
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        cl = QHBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(10)
        ic = QLabel(icon)
        ic.setStyleSheet("font-size:20px;")
        ic.setFixedWidth(32)
        cl.addWidget(ic)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        nm = QLabel(name)
        nm.setStyleSheet("color:#ccc;font-size:12px;font-weight:600;")
        mid.addWidget(nm)
        dt = QLabel(detail)
        dt.setStyleSheet("color:#555;font-size:10px;")
        dt.setWordWrap(True)
        mid.addWidget(dt)
        cl.addLayout(mid, 1)
        ex = QLabel(extra)
        ex.setStyleSheet("color:#666;font-size:10px;")
        ex.setFixedWidth(55)
        ex.setAlignment(Qt.AlignmentFlag.AlignRight)
        cl.addWidget(ex)
        btn = QPushButton(btn_text)
        btn.setStyleSheet(f"QPushButton{{background:{btn_color};color:#fff;border:none;border-radius:6px;padding:5px 14px;font-size:10px;font-weight:600;}}QPushButton:hover{{opacity:0.85;}}")
        btn.clicked.connect(callback)
        cl.addWidget(btn)
        # 点击卡片（非按钮区域）弹出详情
        card.mousePressEvent = lambda e, n=name, icn=icon, desc=detail, ver=extra, installed=(btn_text in ("已安装", "已启用", "已禁用", "打开界面")): self._show_plugin_detail(n, icn, desc, ver, installed)
        return card
    
    def _create_store_tab(self):
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        c = QWidget()
        lo = QVBoxLayout(c)
        lo.setContentsMargins(0, 4, 0, 0)
        lo.setSpacing(6)
        
        # 保存商店内容容器引用，用于分类筛选重绘
        self._store_content = lo
        self._store_category = "全部"
        
        cat_row = QHBoxLayout()
        cat_row.setSpacing(4)
        categories = ["全部", "视频处理", "AI工具", "导出工具", "字幕工具", "音频工具", "特效工具", "运营工具"]
        cat_map = {"全部": None, "视频处理": "VIDEO_PROCESSING", "AI工具": "AI_TOOLS",
                    "导出工具": "EXPORT_TOOLS", "字幕工具": "SUBTITLE_TOOLS",
                    "音频工具": "AUDIO_TOOLS", "特效工具": "EFFECT_TOOLS", "运营工具": "OPERATION_TOOLS"}
        for cat_text in categories:
            btn = QPushButton(cat_text)
            btn.setStyleSheet(
                "QPushButton{background:#1a1a1a;color:#888;border:1px solid #222;border-radius:4px;padding:4px 10px;font-size:10px;}"
                "QPushButton:hover{background:#2a2a2a;color:#ccc;}"
                "QPushButton:checked{background:#1e6bde;color:#fff;border-color:#1e6bde;}"
            )
            btn.setCheckable(True)
            if cat_text == "全部":
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, ct=cat_text, cm=cat_map: self._filter_store(ct, cm))
            cat_row.addWidget(btn)
        cat_row.addStretch()
        lo.addLayout(cat_row)
        
        # 商店列表容器
        self._store_list_container = QVBoxLayout()
        self._store_list_container.setSpacing(6)
        lo.addLayout(self._store_list_container)
        lo.addStretch()
        
        # 填充商店内容
        self._populate_store_list()
        s.setWidget(c)
        return s
    
    def _filter_store(self, cat_text: str, cat_map: dict):
        """按分类筛选商店列表"""
        self._store_category = cat_text
        # 更新分类按钮状态
        for i in range(self._store_content.count()):
            w = self._store_content.itemAt(i)
            if w and isinstance(w.layout(), QHBoxLayout):
                for j in range(w.layout().count()):
                    btn = w.layout().itemAt(j).widget()
                    if isinstance(btn, QPushButton) and btn.isCheckable():
                        btn.setChecked(btn.text() == cat_text)
        self._populate_store_list()
    
    def _populate_store_list(self):
        """用 PluginStore 数据填充商店列表"""
        # 清空现有列表
        while self._store_list_container.count():
            item = self._store_list_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        items_displayed = False
        
        # 优先从 PluginStore 获取
        if self._store:
            try:
                from .plugin_store import ItemCategory
                cat_map = {"全部": None, "视频处理": ItemCategory.VIDEO_PROCESSING,
                           "AI工具": ItemCategory.AI_TOOLS, "导出工具": ItemCategory.EXPORT_TOOLS,
                           "字幕工具": ItemCategory.SUBTITLE_TOOLS, "音频工具": ItemCategory.AUDIO_TOOLS,
                           "特效工具": ItemCategory.EFFECT_TOOLS, "运营工具": ItemCategory.OPERATION_TOOLS}
                filter_cat = cat_map.get(self._store_category)
                store_items = self._store.get_items(category=filter_cat) if filter_cat else self._store.get_items()
                
                for it in store_items:
                    price_str = "免费" if it.is_free else f"¥{it.price:.0f}"
                    btn_text = "已安装" if it.is_installed else "安装"
                    btn_color = "#555" if it.is_installed else ("#1e6bde" if it.is_free else "#9c27b0")
                    card = self._plugin_card(
                        it.icon or "🧩", it.name, it.description,
                        f"{price_str}\n{it.version}",
                        btn_text, btn_color,
                        lambda checked, iid=it.id: self._install_store_item(iid),
                        not it.is_installed
                    )
                    self._store_list_container.addWidget(card)
                    items_displayed = True
            except Exception as e:
                logger.warning(f"从 PluginStore 获取商品失败: {e}")
        
        # 回退到硬编码列表
        if not items_displayed:
            for icon, name, cat, ver, price, desc in self.STORE_PLUGINS:
                if self._store_category != "全部" and self._store_category != cat:
                    continue
                card = self._plugin_card(
                    icon, name, desc, f"{price}\n{ver}",
                    "安装",
                    "#1e6bde" if price == "免费" else "#9c27b0",
                    lambda checked, n=name: self._install_store_item(n)
                )
                self._store_list_container.addWidget(card)
        
        if not items_displayed and self._store_list_container.count() == 0:
            empty = QLabel("暂无插件")
            empty.setStyleSheet("color:#555;font-size:12px;padding:20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._store_list_container.addWidget(empty)
