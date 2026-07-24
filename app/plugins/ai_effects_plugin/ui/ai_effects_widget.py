"""
AI特效制作插件 - 用户界面组件
提供完整的AI特效控制面板，包含效果选择、参数调节、预览等功能
"""

import numpy as np
import cv2
from typing import Dict, Any, Optional, Callable
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QSlider,
    QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox,
    QTabWidget, QScrollArea, QFrame, QProgressBar,
    QMessageBox, QColorDialog, QLineEdit, QTextEdit,
    QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap, QFont, QIcon, QPainter, QColor


class EffectProcessorThread(QThread):
    """AI特效处理线程（避免阻塞UI）"""
    
    progress_updated = pyqtSignal(int)
    processing_complete = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, plugin_instance, frame_data: np.ndarray, params: dict):
        super().__init__()
        self.plugin = plugin_instance
        self.frame_data = frame_data
        self.params = params
    
    def run(self):
        try:
            # 模拟进度更新
            for i in range(0, 101, 20):
                self.progress_updated.emit(i)
                self.msleep(50)  # 模拟处理时间
            
            # 执行实际的特效处理
            result = self.plugin.apply_effect(self.frame_data, self.params)
            
            self.progress_updated.emit(100)
            self.processing_complete.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(str(e))


class AIEffectsWidget(QWidget):
    """
    AI特效制作插件主界面
    
    提供完整的用户交互界面，包括：
    - 5大特效类别标签页（风格迁移、背景替换、超分辨率、智能美颜、物体移除）
    - 每种效果的详细参数控制面板
    - 实时预览功能
    - 处理进度显示
    - 快捷预设选择
    
    信号:
        effect_applied(np.ndarray): 特效应用完成，返回处理后的图像
        preview_requested(dict): 请求预览（带参数）
    """
    
    effect_applied = pyqtSignal(np.ndarray)
    preview_requested = pyqtSignal(dict)
    
    def __init__(self, plugin_instance=None, parent=None):
        super().__init__(parent)
        
        self.plugin = plugin_instance
        self.current_image: Optional[np.ndarray] = None
        self.processing_thread: Optional[EffectProcessorThread] = None
        
        # 当前参数状态
        self.current_params: Dict[str, Any] = {
            'effect_type': 'style_transfer'
        }
        
        self._setup_ui()
        self._connect_signals()
        
        print("[UI] AI特效控制面板已初始化")
    
    def _setup_ui(self):
        """设置UI布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)
        
        # ====== 标题栏 ======
        title_layout = QHBoxLayout()
        title_label = QLabel("🎨 AI特效制作")
        title_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        main_layout.addLayout(title_layout)
        
        # ====== 主标签页（5种特效） ======
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { 
                border: 1px solid #ddd; 
                border-radius: 5px; 
                background: white;
            }
            QTabBar::tab {
                background: #f0f0f0;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #4A90E2;
                color: white;
            }
            QTabBar::tab:hover:!selected {
                background: #e0e0e0;
            }
        """)
        
        # 创建各特效的标签页
        self._create_style_transfer_tab()
        self._create_background_replace_tab()
        self._create_super_resolution_tab()
        self._create_beauty_filter_tab()
        self._create_object_removal_tab()
        
        main_layout.addWidget(self.tab_widget)
        
        # ====== 操作按钮区 ======
        button_layout = QHBoxLayout()
        
        # 预设按钮
        self.preset_btn = QPushButton("📋 应用预设")
        self.preset_btn.setToolTip("加载预设参数配置")
        button_layout.addWidget(self.preset_btn)
        
        # 重置按钮
        self.reset_btn = QPushButton("🔄 重置参数")
        self.reset_btn.setToolTip("恢复默认参数值")
        button_layout.addWidget(self.reset_btn)
        
        button_layout.addStretch()
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(200)
        button_layout.addWidget(self.progress_bar)
        
        # 应用按钮
        self.apply_btn = QPushButton("✨ 应用特效")
        self.apply_btn.setMinimumHeight(36)
        self.apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90E2;
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #357ABD;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        button_layout.addWidget(self.apply_btn)
        
        main_layout.addLayout(button_layout)
        
        # 设置整体样式
        self.setStyleSheet("""
            QWidget {
                font-family: "Microsoft YaHei";
                font-size: 12px;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ddd;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #ddd;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                margin: -5px 0;
                background: #4A90E2;
                border-radius: 8px;
            }
            QComboBox {
                padding: 5px;
                border: 1px solid #ddd;
                border-radius: 3px;
                min-width: 120px;
            }
        """)
    
    def _create_style_transfer_tab(self):
        """创建风格迁移标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 效果说明
        info_label = QLabel("🖼️ 将图像转换为指定的艺术风格，支持梵高、赛博朋克、动漫等8种风格")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 5px; background: #f9f9f9; border-radius: 3px;")
        layout.addWidget(info_label)
        
        # 参数组
        param_group = QGroupBox("参数设置")
        param_layout = QGridLayout(param_group)
        
        # 艺术风格选择
        param_layout.addWidget(QLabel("艺术风格:"), 0, 0)
        self.style_combo = QComboBox()
        self.style_combo.addItems([
            "赛博朋克 🌃",
            "梵高星空 🌀",
            "莫奈睡莲 💐",
            "毕加索抽象 🔷",
            "动漫风 ✨",
            "油画 🎨",
            "水彩画 💧",
            "素描 ✏️"
        ])
        self.style_combo.setCurrentText("赛博朋克 🌃")
        param_layout.addWidget(self.style_combo, 0, 1)
        
        # 风格强度
        param_layout.addWidget(QLabel("风格强度:"), 1, 0)
        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(80)
        self.strength_label = QLabel("0.80")
        strength_hbox = QHBoxLayout()
        strength_hbox.addWidget(self.strength_slider)
        strength_hbox.addWidget(self.strength_label)
        param_layout.addLayout(strength_hbox, 1, 1)
        
        # 保留原色选项
        self.preserve_color_cb = QCheckBox("保留原图颜色")
        self.preserve_color_cb.setChecked(True)
        param_layout.addWidget(self.preserve_color_cb, 2, 0, 1, 2)
        
        layout.addWidget(param_group)
        
        # 预览区域
        preview_group = QGroupBox("效果预览")
        preview_layout = QVBoxLayout(preview_group)
        
        self.style_preview_label = QLabel("暂无预览")
        self.style_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.style_preview_label.setMinimumHeight(150)
        self.style_preview_label.setStyleSheet(
            "background: #f5f5f5; border: 1px dashed #ccc; border-radius: 5px;"
        )
        preview_layout.addWidget(self.style_preview_label)
        
        layout.addWidget(preview_group)
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "风格迁移")
    
    def _create_background_replace_tab(self):
        """创建背景替换标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        info_label = QLabel("🎬 智能识别前景人物并替换背景，支持纯色、模糊、自定义图片等多种模式")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 5px; background: #f9f9f9; border-radius: 3px;")
        layout.addWidget(info_label)
        
        param_group = QGroupBox("参数设置")
        param_layout = QGridLayout(param_group)
        
        # 背景类型
        param_layout.addWidget(QLabel("背景类型:"), 0, 0)
        self.bg_type_combo = QComboBox()
        self.bg_type_combo.addItems([
            "模糊背景 🌫️",
            "纯色背景 🎨",
            "渐变背景 🌈",
            "自定义图片 📷",
            "透明背景 🔲"
        ])
        param_layout.addWidget(self.bg_type_combo, 0, 1)
        
        # 背景颜色（仅纯色模式）
        param_layout.addWidget(QLabel("背景颜色:"), 1, 0)
        color_layout = QHBoxLayout()
        self.bg_color_btn = QPushButton("  ")
        self.bg_color_btn.setFixedSize(40, 28)
        self.bg_color_btn.setStyleSheet("background-color: #4A90E2; border: 1px solid #999; border-radius: 3px;")
        self.bg_color_edit = QLineEdit("#4A90E2")
        self.bg_color_edit.setMaximumWidth(100)
        color_layout.addWidget(self.bg_color_btn)
        color_layout.addWidget(self.bg_color_edit)
        param_layout.addLayout(color_layout, 1, 1)
        
        # 模糊程度
        param_layout.addWidget(QLabel("模糊半径:"), 2, 0)
        self.blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.blur_slider.setRange(0, 50)
        self.blur_slider.setValue(15)
        self.blur_label = QLabel("15")
        blur_hbox = QHBoxLayout()
        blur_hbox.addWidget(self.blur_slider)
        blur_hbox.addWidget(self.blur_label)
        param_layout.addLayout(blur_hbox, 2, 1)
        
        # 边缘平滑度
        param_layout.addWidget(QLabel("边缘平滑:"), 3, 0)
        self.edge_smooth_slider = QSlider(Qt.Orientation.Horizontal)
        self.edge_smooth_slider.setRange(0, 20)
        self.edge_smooth_slider.setValue(5)
        self.edge_smooth_label = QLabel("5")
        edge_hbox = QHBoxLayout()
        edge_hbox.addWidget(self.edge_smooth_slider)
        edge_hbox.addWidget(self.edge_smooth_label)
        param_layout.addLayout(edge_hbox, 3, 1)
        
        layout.addWidget(param_group)
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "背景替换")
    
    def _create_super_resolution_tab(self):
        """创建超分辨率标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        info_label = QLabel("🔍 使用深度学习提升图像/视频分辨率，最高可放大4倍并同步降噪")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 5px; background: #f9f9f9; border-radius: 3px;")
        layout.addWidget(info_label)
        
        param_group = QGroupBox("参数设置")
        param_layout = QGridLayout(param_group)
        
        # 放大倍数
        param_layout.addWidget(QLabel("放大倍数:"), 0, 0)
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["2倍放大 (推荐)", "3倍放大", "4倍放大"])
        param_layout.addWidget(self.scale_combo, 0, 1)
        
        # 质量模式
        param_layout.addWidget(QLabel("质量模式:"), 1, 0)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["快速模式 ⚡", "均衡模式 ⚖️", "高质量模式 🎯"])
        param_layout.addWidget(self.quality_combo, 1, 1)
        
        # 降噪强度
        param_layout.addWidget(QLabel("降噪强度:"), 2, 0)
        self.denoise_slider = QSlider(Qt.Orientation.Horizontal)
        self.denoise_slider.setRange(0, 100)
        self.denoise_slider.setValue(30)
        self.denoise_label = QLabel("0.30")
        denoise_hbox = QHBoxLayout()
        denoise_hbox.addWidget(self.denoise_slider)
        denoise_hbox.addWidget(self.denoise_label)
        param_layout.addLayout(denoise_hbox, 2, 1)
        
        # 信息提示
        info_text = QLabel(
            "💡 提示：\n"
            "• 2倍放大速度快，适合实时预览\n"
            "• 4倍放大质量最佳但耗时较长\n"
            "• 建议先使用降噪去除噪点"
        )
        info_text.setStyleSheet("color: #888; font-size: 11px; padding: 10px;")
        param_layout.addWidget(info_text, 3, 0, 1, 2)
        
        layout.addWidget(param_group)
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "超分辨率")
    
    def _create_beauty_filter_tab(self):
        """创建智能美颜标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        info_label = QLabel("✨ AI驱动的美颜效果，自动检测人脸并进行磨皮、美白、瘦脸、大眼等处理")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 5px; background: #f9f9f9; border-radius: 3px;")
        layout.addWidget(info_label)
        
        # 美颜参数组
        beauty_group = QGroupBox("美颜参数")
        beauty_layout = QGridLayout(beauty_group)
        
        # 磨皮
        beauty_layout.addWidget(QLabel("磨皮强度:"), 0, 0)
        self.smoothing_slider = QSlider(Qt.Orientation.Horizontal)
        self.smoothing_slider.setRange(0, 100)
        self.smoothing_slider.setValue(50)
        self.smoothing_label = QLabel("0.50")
        smoothing_hbox = QHBoxLayout()
        smoothing_hbox.addWidget(self.smoothing_slider)
        smoothing_hbox.addWidget(self.smoothing_label)
        beauty_layout.addLayout(smoothing_hbox, 0, 1)
        
        # 白化
        beauty_layout.addWidget(QLabel("美白强度:"), 1, 0)
        self.whitening_slider = QSlider(Qt.Orientation.Horizontal)
        self.whitening_slider.setRange(0, 100)
        self.whitening_slider.setValue(30)
        self.whitening_label = QLabel("0.30")
        whitening_hbox = QHBoxLayout()
        whitening_hbox.addWidget(self.whitening_slider)
        whitening_hbox.addWidget(self.whitening_label)
        beauty_layout.addLayout(whitening_hbox, 1, 1)
        
        # 瘦脸
        beauty_layout.addWidget(QLabel("瘦脸程度:"), 2, 0)
        self.face_slim_slider = QSlider(Qt.Orientation.Horizontal)
        self.face_slim_slider.setRange(0, 100)
        self.face_slim_slider.setValue(20)
        self.face_slim_label = QLabel("0.20")
        face_hbox = QHBoxLayout()
        face_hbox.addWidget(self.face_slim_slider)
        face_hbox.addWidget(self.face_slim_label)
        beauty_layout.addLayout(face_hbox, 2, 1)
        
        # 大眼
        beauty_layout.addWidget(QLabel("大眼效果:"), 3, 0)
        self.eye_large_slider = QSlider(Qt.Orientation.Horizontal)
        self.eye_large_slider.setRange(0, 100)
        self.eye_large_slider.setValue(15)
        self.eye_large_label = QLabel("0.15")
        eye_hbox = QHBoxLayout()
        eye_hbox.addWidget(self.eye_large_slider)
        eye_hbox.addWidget(self.eye_large_label)
        beauty_layout.addLayout(eye_hbox, 3, 1)
        
        # 自然模式开关
        self.natural_look_cb = QCheckBox("启用自然效果模式（推荐）")
        self.natural_look_cb.setChecked(True)
        beauty_layout.addWidget(self.natural_look_cb, 4, 0, 1, 2)
        
        layout.addWidget(beauty_group)
        
        # 预设组
        preset_group = QGroupBox("快捷预设")
        preset_layout = QVBoxLayout(preset_group)
        
        preset_btn_layout = QHBoxLayout()
        
        self.btn_natural = QPushButton("自然清新")
        self.btn_natural.setToolTip("轻微美化，保持真实感")
        
        self.btn_soft = QPushButton("柔光女神")
        self.btn_soft.setToolTip("柔和梦幻的美颜效果")
        
        self.btn_glamour = QPushButton("精致妆容")
        self.btn_glamourToolTip("明显的美妆效果")
        
        self.btn_korean = QPushButton("韩式偶像")
        self.btn_korean.setToolTip("韩流明星风格")
        
        for btn in [self.btn_natural, self.btn_soft, self.btn_glamour, self.btn_korean]:
            btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 12px;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    background: white;
                }
                QPushButton:hover {
                    background: #f0f0f0;
                    border-color: #4A90E2;
                }
            """)
            preset_btn_layout.addWidget(btn)
        
        preset_layout.addLayout(preset_btn_layout)
        layout.addWidget(preset_group)
        
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "智能美颜")
    
    def _create_object_removal_tab(self):
        """创建物体移除标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        info_label = QLabel("🗑️ 智能移除画面中的指定物体（水印、路人、杂物等）并自动填充背景")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 5px; background: #f9f9f9; border-radius: 3px;")
        layout.addWidget(info_label)
        
        # 移除设置组
        removal_group = QGroupBox("移除设置")
        removal_layout = QGridLayout(removal_group)
        
        # 移除模式
        removal_layout.addWidget(QLabel("移除模式:"), 0, 0)
        self.removal_mode_combo = QComboBox()
        self.removal_mode_combo.addItems([
            "自动检测 🤖",
            "手动框选 ▢",
            "笔刷涂抹 🖌️"
        ])
        removal_layout.addWidget(self.removal_mode_combo, 0, 1)
        
        # 填充方法
        removal_layout.addWidget(QLabel("填充方法:"), 1, 0)
        self.fill_method_combo = QComboBox()
        self.fill_method_combo.addItems([
            "AI修复 (推荐) 🧠",
            "内容感知填充 🔄",
            "模糊填充 🌫️",
            "仿制图章 📋"
        ])
        removal_layout.addWidget(self.fill_method_combo, 1, 1)
        
        # 笔刷大小
        removal_layout.addWidget(QLabel("笔刷大小:"), 2, 0)
        self.brush_size_spin = QSpinBox()
        self.brush_size_spin.setRange(5, 100)
        self.brush_size_spin.setValue(30)
        removal_layout.addWidget(self.brush_size_spin, 2, 1)
        
        # 边缘羽化
        removal_layout.addWidget(QLabel("边缘羽化:"), 3, 0)
        self.feather_slider = QSlider(Qt.Orientation.Horizontal)
        self.feather_slider.setRange(0, 50)
        self.feather_slider.setValue(10)
        self.feather_label = QLabel("10")
        feather_hbox = QHBoxLayout()
        feather_hbox.addWidget(self.feather_slider)
        feather_hbox.addWidget(self.feather_label)
        removal_layout.addLayout(feather_hbox, 3, 1)
        
        layout.addWidget(removal_group)
        
        # 自动检测目标选择
        target_group = QGroupBox("自动检测目标（多选）")
        target_layout = QVBoxLayout(target_group)
        
        targets_row1 = QHBoxLayout()
        self.cb_text = QCheckBox("文字/水印")
        self.cb_logo = QCheckBox("Logo图标")
        self.cb_stamp = QCheckBox("印章")
        self.cb_date = QCheckBox("日期戳")
        for cb in [self.cb_text, self.cb_logo, self.cb_stamp, self.cb_date]:
            cb.setChecked(False)
            targets_row1.addWidget(cb)
        
        targets_row2 = QHBoxLayout()
        self.cb_person = QCheckBox("人物")
        self.cb_car = QCheckBox("汽车")
        self.cb_building = QCheckBox("建筑")
        
        for cb in [self.cb_person, self.cb_car, self.cb_building]:
            cb.setChecked(False)
            targets_row2.addWidget(cb)
        
        target_layout.addLayout(targets_row1)
        target_layout.addLayout(targets_row2)
        layout.addWidget(target_group)
        
        layout.addStretch()
        
        self.tab_widget.addTab(widget, "物体移除")
    
    def _connect_signals(self):
        """连接信号和槽函数"""
        
        # 标签页切换时保存当前参数
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # 风格迁移参数
        self.strength_slider.valueChanged.connect(
            lambda v: self.strength_label.setText(f"{v/100:.2f}"))
        self.style_combo.currentTextChanged.connect(self._on_style_changed)
        
        # 背景替换参数
        self.blur_slider.valueChanged.connect(
            lambda v: self.blur_label.setText(str(v)))
        self.edge_smooth_slider.valueChanged.connect(
            lambda v: self.edge_smooth_label.setText(str(v)))
        self.bg_color_btn.clicked.connect(self._on_color_select)
        
        # 超分辨率参数
        self.denoise_slider.valueChanged.connect(
            lambda v: self.denoise_label.setText(f"{v/100:.2f}"))
        
        # 美颜参数滑块
        self.smoothing_slider.valueChanged.connect(
            lambda v: self.smoothing_label.setText(f"{v/100:.2f}"))
        self.whitening_slider.valueChanged.connect(
            lambda v: self.whitening_label.setText(f"{v/100:.2f}"))
        self.face_slim_slider.valueChanged.connect(
            lambda v: self.face_slim_label.setText(f"{v/100:.2f}"))
        self.eye_large_slider.valueChanged.connect(
            lambda v: self.eye_large_label.setText(f"{v/100:.2f}"))
        
        # 物体移除参数
        self.feather_slider.valueChanged.connect(
            lambda v: self.feather_label.setText(str(v)))
        
        # 预设按钮
        self.btn_natural.clicked.connect(lambda: self._apply_beauty_preset('natural'))
        self.btn_soft.clicked.connect(lambda: self._apply_beauty_preset('soft'))
        self.btn_glamour.clicked.connect(lambda: self._apply_beauty_preset('glamour'))
        self.btn_korean.clicked.connect(lambda: self._apply_beauty_preset('korean_idol'))
        
        # 操作按钮
        self.reset_btn.clicked.connect(self._reset_params)
        self.apply_btn.clicked.connect(self._apply_effect)
    
    @pyqtSlot(int)
    def _on_tab_changed(self, index: int):
        """标签页切换事件"""
        tab_names = ['style_transfer', 'background_replace', 
                    'super_resolution', 'beauty_filter', 'object_removal']
        if index < len(tab_names):
            self.current_params['effect_type'] = tab_names[index]
            print(f"[UI] 切换到特效类型: {tab_names[index]}")
    
    @pyqtSlot(str)
    def _on_style_changed(self, style_name: str):
        """风格选择变化"""
        style_map = {
            "梵高星空 🌀": "vangogh",
            "莫奈睡莲 💐": "monet",
            "毕加索抽象 🔷": "picasso",
            "赛博朋克 🌃": "cyberpunk",
            "动漫风 ✨": "anime",
            "油画 🎨": "oil_painting",
            "水彩画 💧": "watercolor",
            "素描 ✏️": "sketch"
        }
        self.current_params['style_name'] = style_map.get(style_name, 'cyberpunk')
    
    @pyqtSlot()
    def _on_color_select(self):
        """颜色选择对话框"""
        color = QColorDialog.getColor(QColor("#4A90E2"), self, "选择背景颜色")
        if color.isValid():
            hex_color = color.name()
            self.bg_color_edit.setText(hex_color)
            self.bg_color_btn.setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #999; border-radius: 3px;"
            )
    
    def _apply_beauty_preset(self, preset_name: str):
        """应用美颜预设"""
        from .effects.beauty_filter import SkinRetouchingPreset
        
        preset = SkinRetouchingPreset.get_preset(preset_name)
        if not preset:
            return
        
        params = preset['params']
        
        # 更新UI控件
        self.smoothing_slider.setValue(int(params['smoothing_level'] * 100))
        self.whitening_slider.setValue(int(params['whitening_level'] * 100))
        self.face_slim_slider.setValue(int(params['face_slimming'] * 100))
        self.eye_large_slider.setValue(int(params['eye_enlargement'] * 100))
        self.natural_look_cb.setChecked(params['natural_look'])
        
        print(f"[UI] 已应用美颜预设: {preset['name']}")
    
    @pyqtSlot()
    def _reset_params(self):
        """重置当前标签页的参数到默认值"""
        current_tab = self.tab_widget.currentIndex()
        
        # 根据不同标签页重置对应参数
        if current_tab == 0:  # 风格迁移
            self.style_combo.setCurrentIndex(0)
            self.strength_slider.setValue(80)
            self.preserve_color_cb.setChecked(True)
        
        elif current_tab == 1:  # 背景替换
            self.bg_type_combo.setCurrentIndex(0)
            self.bg_color_edit.setText("#4A90E2")
            self.bg_color_btn.setStyleSheet("background-color: #4A90E2; border: 1px solid #999;")
            self.blur_slider.setValue(15)
            self.edge_smooth_slider.setValue(5)
        
        elif current_tab == 2:  # 超分辨率
            self.scale_combo.setCurrentIndex(0)
            self.quality_combo.setCurrentIndex(0)
            self.denoise_slider.setValue(30)
        
        elif current_tab == 3:  # 智能美颜
            self.smoothing_slider.setValue(50)
            self.whitening_slider.setValue(30)
            self.face_slim_slider.setValue(20)
            self.eye_large_slider.setValue(15)
            self.natural_look_cb.setChecked(True)
        
        elif current_tab == 4:  # 物体移除
            self.removal_mode_combo.setCurrentIndex(0)
            self.fill_method_combo.setCurrentIndex(0)
            self.brush_size_spin.setValue(30)
            self.feather_slider.setValue(10)
            
            for cb in [self.cb_text, self.cb_logo, self.cb_stamp, 
                      self.cb_date, self.cb_person, self.cb_car, self.cb_building]:
                cb.setChecked(False)
        
        print(f"[UI] 已重置参数（标签页{current_tab}）")
    
    def _collect_current_params(self) -> Dict[str, Any]:
        """收集当前标签页的所有参数"""
        current_tab = self.tab_widget.currentIndex()
        params = {}
        
        # 基础参数：确定特效类型
        effect_types = ['style_transfer', 'background_replace',
                       'super_resolution', 'beauty_filter', 'object_removal']
        params['effect_type'] = effect_types[current_tab]
        
        if current_tab == 0:  # 风格迁移
            style_map = {"梵高星空 🌀": "vangogh", "莫奈睡莲 💐": "monet",
                        "毕加索抽象 🔷": "picasso", "赛博朋克 🌃": "cyberpunk",
                        "动漫风 ✨": "anime", "油画 🎨": "oil_painting",
                        "水彩画 💧": "watercolor", "素描 ✏️": "sketch"}
            params.update({
                'style_name': style_map.get(self.style_combo.currentText(), 'cyberpunk'),
                'style_strength': self.strength_slider.value() / 100.0,
                'preserve_color': self.preserve_color_cb.isChecked()
            })
        
        elif current_tab == 1:  # 背景替换
            bg_type_map = {"模糊背景 🌫️": "blur", "纯色背景 🎨": "solid_color",
                          "渐变背景 🌈": "gradient", "自定义图片 📷": "image",
                          "透明背景 🔲": "transparent"}
            params.update({
                'background_type': bg_type_map.get(self.bg_type_combo.currentText(), 'blur'),
                'background_color': self.bg_color_edit.text(),
                'blur_strength': self.blur_slider.value(),
                'edge_smoothness': self.edge_smooth_slider.value()
            })
        
        elif current_tab == 2:  # 超分辨率
            scale_map = {"2倍放大 (推荐)": "2", "3倍放大": "3", "4倍放大": "4"}
            quality_map = {"快速模式 ⚡": "fast", "均衡模式 ⚖️": "balanced",
                         "高质量模式 🎯": "quality"}
            params.update({
                'scale_factor': scale_map.get(self.scale_combo.currentText(), '2'),
                'model_quality': quality_map.get(self.quality_combo.currentText(), 'fast'),
                'denoise_strength': self.denoise_slider.value() / 100.0
            })
        
        elif current_tab == 3:  # 智能美颜
            params.update({
                'smoothing': self.smoothing_slider.value() / 100.0,
                'whitening': self.whitening_slider.value() / 100.0,
                'face_slimming': self.face_slim_slider.value() / 100.0,
                'eye_enlargement': self.eye_large_slider.value() / 100.0,
                'natural_look': self.natural_look_cb.isChecked()
            })
        
        elif current_tab == 4:  # 物体移除
            mode_map = {"自动检测 🤖": "auto_detect", "手动框选 ▢": "manual_select",
                       "笔刷涂抹 🖌️": "brush_paint"}
            fill_map = {"AI修复 (推荐) 🧠": "ai_inpainting", "内容感知填充 🔄": "content_aware",
                       "模糊填充 🌫️": "blur_fill", "仿制图章 📋": "clone_stamp"}
            
            # 收集选中的目标物体
            targets = []
            if self.cb_text.isChecked(): targets.append('text')
            if self.cb_logo.isChecked(): targets.append('logo')
            if self.cb_stamp.isChecked(): targets.append('stamp')
            if self.cb_date.isChecked(): targets.append('date_stamp')
            if self.cb_person.isChecked(): targets.append('person')
            if self.cb_car.isChecked(): targets.append('car')
            if self.cb_building.isChecked(): targets.append('building')
            
            params.update({
                'removal_mode': mode_map.get(self.removal_mode_combo.currentText(), 'auto_detect'),
                'fill_method': fill_map.get(self.fill_method_combo.currentText(), 'ai_inpainting'),
                'brush_size': self.brush_size_spin.value(),
                'edge_feathering': self.feather_slider.value(),
                'target_objects': targets if targets else None
            })
        
        self.current_params = params
        return params
    
    @pyqtSlot()
    def _apply_effect(self):
        """应用特效（在后台线程中执行）"""
        if self.current_image is None:
            QMessageBox.warning(self, "提示", "请先载入图像！")
            return
        
        if not self.plugin:
            QMessageBox.critical(self, "错误", "插件未正确初始化！")
            return
        
        # 收集当前参数
        params = self._collect_current_params()
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.apply_btn.setEnabled(False)
        self.apply_btn.setText("⏳ 处理中...")
        
        # 在后台线程中处理
        self.processing_thread = EffectProcessorThread(
            self.plugin, 
            self.current_image.copy(),
            params
        )
        
        self.processing_thread.progress_updated.connect(self.progress_bar.setValue)
        self.processing_thread.processing_complete.connect(self._on_processing_complete)
        self.processing_thread.error_occurred.connect(self._on_processing_error)
        
        self.processing_thread.start()
    
    @pyqtSlot(object)
    def _on_processing_complete(self, result: np.ndarray):
        """处理完成回调"""
        self.progress_bar.setVisible(False)
        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("✨ 应用特效")
        
        # 发送结果信号
        self.effect_applied.emit(result)
        
        # 更新预览（如果在风格迁移页面）
        if self.tab_widget.currentIndex() == 0 and result is not None:
            self._update_preview(result)
        
        print(f"[UI] ✅ 特效应用完成，输出尺寸: {result.shape[1]}x{result.shape[0]}")
    
    @pyqtSlot(str)
    def _on_processing_error(self, error_msg: str):
        """处理错误回调"""
        self.progress_bar.setVisible(False)
        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("✨ 应用特效")
        
        QMessageBox.critical(self, "处理错误", f"特效处理失败:\n{error_msg}")
        print(f"[UI] ❌ 处理错误: {error_msg}")
    
    def set_input_image(self, image: np.ndarray):
        """设置输入图像"""
        self.current_image = image.copy()
        print(f"[UI] 已设置输入图像: {image.shape[1]}x{image.shape[0]}")
    
    def get_output_image(self) -> Optional[np.ndarray]:
        """获取最近一次的处理结果（如果需要缓存的话）"""
        # 这里可以添加输出图像的缓存机制
        return None
    
    def _update_preview(self, image: np.ndarray):
        """更新预览区域显示"""
        try:
            # 缩放到合适的预览尺寸
            max_size = 300
            h, w = image.shape[:2]
            
            if max(h, w) > max_size:
                scale = max_size / max(h, w)
                new_w, new_h = int(w * scale), int(h * scale)
                preview_img = cv2.resize(image, (new_w, new_h))
            else:
                preview_img = image
            
            # BGR转RGB用于Qt显示
            if len(preview_img.shape) == 3 and preview_img.shape[2] == 3:
                preview_rgb = cv2.cvtColor(preview_img, cv2.COLOR_BGR2RGB)
            else:
                preview_rgb = preview_img
            
            height, width, channel = preview_rgb.shape
            bytes_per_line = 3 * width
            
            q_image = QImage(
                preview_rgb.data, width, height, 
                bytes_per_line, QImage.Format.Format_RGB888
            ).copy()
            
            pixmap = QPixmap.fromImage(q_image)
            self.style_preview_label.setPixmap(pixmap)
            
        except Exception as e:
            print(f"[UI] 更新预览失败: {e}")
            self.style_preview_label.setText("预览生成失败")
    
    def enable_controls(self, enabled: bool = True):
        """启用或禁用所有控件"""
        self.apply_btn.setEnabled(enabled)
        self.tab_widget.setEnabled(enabled)
        self.reset_btn.setEnabled(enabled)
    
    def get_plugin_info_dict(self) -> Dict[str, Any]:
        """获取插件信息（供外部调用）"""
        if self.plugin:
            return {
                'plugin_id': self.plugin.plugin_info.id,
                'plugin_name': self.plugin.plugin_info.name,
                'version': self.plugin.plugin_info.version,
                'supported_effects': self.plugin.get_supported_effects()
            }
        return {}


# ==================== 便捷工厂函数 ====================

def create_ai_effects_panel(plugin_instance=None, parent=None) -> AIEffectsWidget:
    """
    创建AI特效控制面板的便捷函数
    
    Args:
        plugin_instance: Plugin实例（可选）
        parent: 父QWidget（可选）
    
    Returns:
        AIEffectsWidget: 配置好的UI组件实例
    """
    return AIEffectsWidget(plugin_instance, parent)


def show_ai_effects_dialog(image: np.ndarray, parent=None) -> Optional[np.ndarray]:
    """
    以对话框形式显示AI特效编辑器
    
    Args:
        image: 要编辑的numpy图像
        parent: 父窗口
    
    Returns:
        处理后的图像，如果取消则返回None
    """
    from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QDialogButtonBox
    
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    
    dialog = QDialog(parent)
    dialog.setWindowTitle("AI特效制作")
    dialog.setMinimumSize(500, 700)
    
    layout = QVBoxLayout(dialog)
    
    # 创建插件实例和UI
    from ..main import Plugin
    plugin = Plugin()
    plugin.initialize({})
    
    panel = create_ai_effects_panel(plugin)
    panel.set_input_image(image)
    layout.addWidget(panel)
    
    # 对话框按钮
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    
    result_image = None
    
    def on_effect_applied(img):
        nonlocal result_image
        result_image = img
    
    panel.effect_applied.connect(on_effect_applied)
    
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return result_image or image
    
    return None


__all__ = [
    'AIEffectsWidget',
    'EffectProcessorThread',
    'create_ai_effects_panel',
    'show_ai_effects_dialog'
]
